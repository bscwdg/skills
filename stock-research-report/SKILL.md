---
name: stock-research-report
description: 生成有来源标注的个股研究报告，面向 A 股或其他上市公司分析，使用火山方舟模型上下文以及 dataPro、豆包搜索等内置 harness 工具。用户要求分析个股、生成详细报告、查询近期成交量、涨跌幅、上次涨停时间、财务摘要、公告新闻、风险因素、结构化市场研究简报，或需要配置 Codex/OpenClaw 的火山方舟 Agent Plan harness 工具时使用。
---

# 个股研究报告

## 概览

使用 `dataPro` 获取专业结构化数据，使用豆包搜索补充公开信息，生成有来源、有时间戳、有风险提示的个股研究报告。报告只用于信息整理与研究辅助，不构成投资建议。

## 配置检查

生成报告前，先确认当前 Agent 是否已经具备必要的 harness 工具。

- 如果无法使用 `dataPro` 或豆包搜索，阅读 `references/volcengine-harness.md`，并优先使用一键配置脚本。
- OpenClaw 默认使用：`python scripts/setup_harness.py openclaw`。
- Codex 默认使用：`python scripts/setup_harness.py codex`。
- 如果用户只想注入 MCP 工具、不想修改模型或 provider，使用：`python scripts/setup_harness.py <target> --mode mcp-only`。
- 配置完成后，提醒用户重启目标 Agent。

## 报告流程

1. 规范化股票名称或代码，尽量补齐交易所后缀。
2. 优先用 `dataPro` 查询结构化行情、交易、财务和估值数据。
3. 再用豆包搜索查询官方公告、交易所披露、公司背景、新闻和行业事件。
4. 对关键数字和日期做交叉验证。
5. 为关键指标标注来源和数据时间。
6. 按 `references/report-template.md` 的结构生成最终报告。
7. 明确写出数据缺口、来源冲突和合规声明。

## 数据优先级

- **结构化市场指标**：优先使用 `dataPro`，必须包含最新交易日或数据时间。
- **近期成交量与成交额**：优先使用 `dataPro`，同时给出最新值及 5 日/20 日均量对比。
- **涨跌幅**：优先使用 `dataPro`，同时给出当日及 5/20/60 日区间表现。
- **上次涨停时间**：优先使用专业数据集的明确字段；如果没有可靠数据，不要静默估算。
- **财务指标**：优先使用 `dataPro`，并结合年报、半年报、季报公告解释变化。
- **公告与事件**：优先使用公司公告、交易所披露、巨潮资讯等官方或准官方来源；新闻只作为背景补充。

更多查询清单和冲突处理规则见 `references/data-protocol.md`。

## 报告要求

- 使用中文 Markdown 输出。
- 对关键指标使用表格。
- 明确区分事实、解读和风险。
- 不输出确定性的买入/卖出建议、目标价、收益承诺或个性化投资建议。
- 对过期、缺失、冲突或未验证的数据显式标注。
- 结尾必须列出数据来源、时间戳和未取得的数据。

## 参考文件

- 用户要求一键配置、OpenClaw 配置、Codex 配置或简化 harness 配置时，运行 `scripts/setup_harness.py`。
- 配置 Codex/OpenClaw 或排查缺失 harness 工具时，阅读 `references/volcengine-harness.md`。
- 查询个股数据或处理来源冲突前，阅读 `references/data-protocol.md`。
- 起草最终报告前，阅读 `references/report-template.md`。
- 撰写结论、建议或风险提示前，阅读 `references/compliance.md`。
