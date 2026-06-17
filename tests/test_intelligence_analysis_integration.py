# -*- coding: utf-8 -*-
"""Tests for using persisted intelligence in analysis contexts."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from src.config import Config, get_config
from src.core.pipeline import StockAnalysisPipeline
from src.market_analyzer import MarketAnalyzer
from src.repositories.intelligence_repo import IntelligenceRepository
from src.storage import DatabaseManager


class PersistedIntelligenceAnalysisIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "intel_analysis.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.config = get_config()
        repo = IntelligenceRepository()
        now = datetime.now()
        repo.upsert_items([
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "Company wins major AI order",
                "summary": "Order expands visibility for next quarter.",
                "url": "https://news.example.com/symbol",
                "source": "symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "600519",
                "market": "cn",
            },
            {
                "source_name": "market-feed",
                "source_type": "rss",
                "title": "Policy support lifts market sentiment",
                "summary": "Market-level catalyst.",
                "url": "https://news.example.com/market",
                "source": "market-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "market",
                "scope_value": None,
                "market": "cn",
            },
        ])

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config._instance = None
        os.environ.pop("DATABASE_PATH", None)
        self._temp_dir.cleanup()

    def test_pipeline_loads_persisted_symbol_and_market_intelligence(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config
        context = pipeline._load_persisted_intelligence_context(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
        )
        self.assertIsNotNone(context)
        assert context is not None
        self.assertIn("本地资讯证据池", context)
        self.assertIn("Company wins major AI order", context)
        self.assertIn("https://news.example.com/symbol", context)

    def test_market_review_merges_persisted_market_intelligence(self) -> None:
        analyzer = MarketAnalyzer(config=self.config, region="cn")
        merged = analyzer._merge_persisted_market_intelligence([])
        self.assertTrue(any(item.get("title") == "Policy support lifts market sentiment" for item in merged))
        item = next(item for item in merged if item.get("title") == "Policy support lifts market sentiment")
        self.assertEqual(item["snippet"], "Market-level catalyst.")
        self.assertEqual(item["url"], "https://news.example.com/market")


if __name__ == "__main__":
    unittest.main()
