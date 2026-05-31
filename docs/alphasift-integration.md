# AlphaSift 选股集成

AlphaSift 是 DSA 默认关闭的可选选股能力。用户可以通过环境变量或 Web 设置页开启；开启后 DSA 会自动检查并安装 AlphaSift，并通过 AlphaSift 提供的稳定 DSA 适配层读取策略与运行选股。

AlphaSift 结果仅用于研究和辅助判断，不构成投资建议。市场有风险，交易决策和损益由使用者自行承担。

## 开启方式

最小配置：

```bash
ALPHASIFT_ENABLED=true
```

也可以在 Web 设置页打开 AlphaSift 选股开关。Web 开关会写入 `ALPHASIFT_ENABLED=true`，重新加载运行时配置，并触发一次 AlphaSift 可用性检查或自动安装。

高级配置：

```bash
ALPHASIFT_INSTALL_SPEC=git+https://github.com/ZhuLinsen/alphasift.git
```

普通用户通常不需要修改 `ALPHASIFT_INSTALL_SPEC`。该值用于固定自动安装来源到 AlphaSift 官方 GitHub 仓库，避免未认证请求触发任意 pip 安装。AlphaSift 与 DSA 共用同一 Python 环境，并复用 DSA 已加载的环境变量和数据源/LLM 配置，不要求维护单独的 AlphaSift `.env`。

AlphaSift 选股默认开启 LLM 重排，并复用 DSA 的 `LLM_*` 配置。`LLM_TIMEOUT_SEC` 可控制单次 LLM 请求超时，默认 60 秒；超时或上游不可用时，AlphaSift 会降级返回本地筛选排序结果和 warning，而不是让 Web 请求长期挂起。

## 集成契约

DSA 只依赖 AlphaSift 的稳定适配层：

```python
alphasift.dsa_adapter.get_status()
alphasift.dsa_adapter.list_strategies()
alphasift.dsa_adapter.screen(strategy, market="cn", max_results=20)
```

DSA 不直接依赖 AlphaSift 内部的 pipeline、models、strategy 实现。AlphaSift 内部可以演进，但需要保持 `dsa_adapter` 的返回结构兼容。

## API

```text
GET  /api/v1/alphasift/status
POST /api/v1/alphasift/install
GET  /api/v1/alphasift/strategies
POST /api/v1/alphasift/screen
```

`/strategies` 的策略列表来自 AlphaSift，不在 DSA 前端硬编码。`/screen` 返回的候选结果由 AlphaSift 适配层提供，默认开启 AlphaSift 的 LLM 重排，并返回候选代码、名称、分数、LLM 分数、LLM 判断、原因、风险等级、风险标签、价格、行业、因子分数和运行统计等字段。

当前 AlphaSift pipeline 仅支持 `market="cn"`。DSA Web 只展示 A 股选项；如果后端收到其他市场，会返回可读的 400 错误，而不是 500。

请求示例：

```json
{
  "market": "cn",
  "strategy": "dual_low",
  "max_results": 20
}
```

## 失败与回滚

AlphaSift 不可用、安装失败或适配层缺失时，只影响选股页面，不影响 DSA 主流程、每日分析、单股分析、报告和通知。

回滚方式：

```bash
ALPHASIFT_ENABLED=false
```

关闭后 Web 左侧导航隐藏“选股”入口，后端拒绝新的 AlphaSift 选股请求。
