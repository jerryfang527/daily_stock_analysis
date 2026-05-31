# -*- coding: utf-8 -*-
"""Optional AlphaSift stock screening endpoint."""

from __future__ import annotations

import importlib
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_config_dep
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC

router = APIRouter()

ALLOWED_ALPHASIFT_INSTALL_SPECS = frozenset({DEFAULT_ALPHASIFT_INSTALL_SPEC})


class AlphaSiftScreenRequest(BaseModel):
    market: str = Field("cn", min_length=1, max_length=16)
    strategy: str = Field("dual_low", min_length=1, max_length=64)
    max_results: int = Field(20, ge=1, le=100)


@router.get("/status")
def alphasift_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    adapter_status: Dict[str, Any] = {}
    available = _is_alphasift_available()
    if available:
        try:
            adapter_status = _get_dsa_adapter().get_status()
            available = bool(adapter_status.get("available", True))
        except HTTPException:
            available = False
    return {
        "enabled": bool(config.alphasift_enabled),
        "available": available,
        "install_spec_is_default": _is_default_alphasift_install_spec(config.alphasift_install_spec),
        "contract_version": adapter_status.get("contract_version"),
        "version": adapter_status.get("version"),
        "strategy_count": adapter_status.get("strategy_count"),
    }


@router.post("/install")
def alphasift_install(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)
    return _install_alphasift(config)


def _install_alphasift(config: Config) -> Dict[str, Any]:
    install_spec_is_default = _is_default_alphasift_install_spec(config.alphasift_install_spec)
    if _is_alphasift_available():
        _get_dsa_adapter()
        return _build_install_response(
            already_installed=True,
            install_spec_is_default=install_spec_is_default,
        )

    install_spec = _validate_install_spec(config.alphasift_install_spec)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", install_spec],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_install_failed", "message": f"自动安装 AlphaSift 失败：{exc}"},
        ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"pip exited with code {completed.returncode}"
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_install_failed",
                "message": f"自动安装 AlphaSift 失败：{detail}",
            },
        )

    importlib.invalidate_caches()
    if not _is_alphasift_available():
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_unavailable", "message": "AlphaSift 安装完成，但当前进程仍无法导入 alphasift。请重启后端后重试。"},
        )
    _get_dsa_adapter()

    return _build_install_response(
        already_installed=False,
        install_spec_is_default=_is_default_alphasift_install_spec(install_spec),
    )


def _validate_install_spec(raw_install_spec: str) -> str:
    install_spec = (raw_install_spec or "").strip()
    if not install_spec or install_spec.lower() == "alphasift":
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_install_spec_missing",
                "message": f"请先将 ALPHASIFT_INSTALL_SPEC 配置为受信任来源：{DEFAULT_ALPHASIFT_INSTALL_SPEC}。",
            },
        )

    if install_spec not in ALLOWED_ALPHASIFT_INSTALL_SPECS:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "alphasift_install_spec_not_allowed",
                "message": (
                    "出于安全考虑，自动安装 AlphaSift 仅允许使用受信任来源："
                    f"{DEFAULT_ALPHASIFT_INSTALL_SPEC}。如需使用本地路径或 wheel，请先手动安装到当前 Python 环境。"
                ),
            },
        )

    return install_spec


@router.get("/strategies")
def alphasift_strategies(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)
    adapter = _get_dsa_adapter()
    strategies = adapter.list_strategies()
    return {
        "enabled": True,
        "strategies": strategies,
        "strategy_count": len(strategies),
    }


@router.post("/screen")
def alphasift_screen(
    request: AlphaSiftScreenRequest,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    _ensure_alphasift_enabled(config)

    adapter = _get_dsa_adapter()
    try:
        raw = adapter.screen(
            request.strategy,
            market=request.market,
            max_results=request.max_results,
            use_llm=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "alphasift_screen_rejected", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_screen_failed", "message": f"AlphaSift 选股运行失败：{exc}"},
        ) from exc
    candidates = _normalize_candidates(raw)
    return {
        "enabled": True,
        "candidates": candidates[: request.max_results],
        "candidate_count": len(candidates[: request.max_results]),
        "run_id": raw.get("run_id") if isinstance(raw, dict) else None,
        "strategy": raw.get("strategy") if isinstance(raw, dict) else request.strategy,
        "market": raw.get("market") if isinstance(raw, dict) else request.market,
        "snapshot_count": raw.get("snapshot_count") if isinstance(raw, dict) else None,
        "after_filter_count": raw.get("after_filter_count") if isinstance(raw, dict) else None,
        "llm_ranked": raw.get("llm_ranked") if isinstance(raw, dict) else None,
        "llm_market_view": raw.get("llm_market_view") if isinstance(raw, dict) else "",
        "llm_selection_logic": raw.get("llm_selection_logic") if isinstance(raw, dict) else "",
        "llm_portfolio_risk": raw.get("llm_portfolio_risk") if isinstance(raw, dict) else "",
        "llm_coverage": raw.get("llm_coverage") if isinstance(raw, dict) else None,
        "llm_parse_errors": raw.get("llm_parse_errors", []) if isinstance(raw, dict) else [],
        "warnings": raw.get("warnings", []) if isinstance(raw, dict) else [],
        "source_errors": raw.get("source_errors", []) if isinstance(raw, dict) else [],
    }


def _ensure_alphasift_enabled(config: Config) -> None:
    if not config.alphasift_enabled:
        raise HTTPException(
            status_code=403,
            detail={"error": "alphasift_disabled", "message": "ALPHASIFT_ENABLED is false."},
        )


def _is_alphasift_available() -> bool:
    try:
        _import_alphasift()
        return True
    except HTTPException:
        return False


def _import_alphasift() -> Any:
    try:
        return importlib.import_module("alphasift")
    except Exception as exc:
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_unavailable",
                "message": f"AlphaSift 未安装或未挂载到当前 Python 环境，无法导入 alphasift：{exc}",
            },
        ) from exc


def _get_dsa_adapter() -> Any:
    alphasift = _import_alphasift()
    adapter = getattr(alphasift, "dsa_adapter", None)
    if adapter is None:
        try:
            adapter = importlib.import_module("alphasift.dsa_adapter")
        except Exception as exc:
            raise HTTPException(
                status_code=424,
                detail={
                    "error": "alphasift_adapter_unavailable",
                    "message": f"AlphaSift 已安装，但缺少 DSA 稳定适配层 alphasift.dsa_adapter：{exc}",
                },
            ) from exc
    for attr in ("list_strategies", "screen"):
        if not callable(getattr(adapter, attr, None)):
            raise HTTPException(
                status_code=424,
                detail={
                    "error": "alphasift_adapter_unavailable",
                    "message": f"AlphaSift DSA 适配层缺少可调用接口：{attr}",
                },
            )
    return adapter


def _normalize_candidates(raw: Any) -> List[Dict[str, Any]]:
    data = _to_plain(raw)
    items = data
    if isinstance(data, dict):
        for key in ("candidates", "picks", "items", "results", "stocks"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []
    return [_normalize_candidate(item, index + 1) for index, item in enumerate(items)]


def _normalize_candidate(raw: Any, rank: int) -> Dict[str, Any]:
    item = _to_plain(raw)
    if not isinstance(item, dict):
        item = {"code": str(item)}
    source = item.get("raw") if isinstance(item.get("raw"), dict) else item
    return {
        "rank": item.get("rank") or source.get("rank") or rank,
        "code": item.get("code") or source.get("code") or item.get("symbol") or source.get("symbol") or item.get("stock_code") or source.get("stock_code") or "",
        "name": item.get("name") or source.get("name") or item.get("stock_name") or source.get("stock_name") or "",
        "score": _first_present(item, source, "score", "final_score"),
        "screen_score": _first_present(item, source, "screen_score"),
        "reason": item.get("reason") or source.get("reason") or source.get("ranking_reason") or source.get("risk_summary") or item.get("summary") or _build_candidate_reason(source),
        "risk_level": item.get("risk_level") or source.get("risk_level") or "",
        "risk_flags": item.get("risk_flags") or source.get("risk_flags") or [],
        "llm_score": _first_present(item, source, "llm_score"),
        "llm_confidence": _first_present(item, source, "llm_confidence"),
        "llm_sector": item.get("llm_sector") or source.get("llm_sector") or "",
        "llm_theme": item.get("llm_theme") or source.get("llm_theme") or "",
        "llm_tags": item.get("llm_tags") or source.get("llm_tags") or [],
        "llm_thesis": item.get("llm_thesis") or source.get("llm_thesis") or "",
        "llm_catalysts": item.get("llm_catalysts") or source.get("llm_catalysts") or [],
        "llm_risks": item.get("llm_risks") or source.get("llm_risks") or [],
        "llm_watch_items": item.get("llm_watch_items") or source.get("llm_watch_items") or [],
        "llm_invalidators": item.get("llm_invalidators") or source.get("llm_invalidators") or [],
        "llm_style_fit": item.get("llm_style_fit") or source.get("llm_style_fit") or "",
        "price": _first_present(item, source, "price"),
        "change_pct": _first_present(item, source, "change_pct"),
        "amount": _first_present(item, source, "amount"),
        "industry": item.get("industry") or source.get("industry") or "",
        "factor_scores": item.get("factor_scores") or source.get("factor_scores") or {},
        "post_analysis_summaries": item.get("post_analysis_summaries") or source.get("post_analysis_summaries") or {},
        "post_analysis_tags": item.get("post_analysis_tags") or source.get("post_analysis_tags") or [],
        "raw": source,
    }


def _first_present(primary: Dict[str, Any], source: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if primary.get(key) is not None:
            return primary.get(key)
        if source.get(key) is not None:
            return source.get(key)
    return None


def _build_candidate_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries")
    if isinstance(summaries, dict):
        summary = next((str(value) for value in summaries.values() if value), "")
        if summary:
            return summary

    factors = item.get("factor_scores")
    parts: List[str] = []
    if isinstance(factors, dict) and factors:
        top_factors = sorted(
            ((key, value) for key, value in factors.items() if isinstance(value, (int, float))),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = "、".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"主要因子：{factor_text}")
    if item.get("industry"):
        parts.append(f"行业：{item['industry']}")
    if item.get("risk_level"):
        parts.append(f"风险等级：{item['risk_level']}")
    return "；".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _build_install_response(already_installed: bool, install_spec_is_default: bool) -> Dict[str, Any]:
    return {
        "installed": True,
        "already_installed": already_installed,
        "install_spec_is_default": install_spec_is_default,
    }


def _is_default_alphasift_install_spec(install_spec: str) -> bool:
    return (install_spec or "").strip() == DEFAULT_ALPHASIFT_INSTALL_SPEC
