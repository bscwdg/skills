# Skills 工作区

这个仓库用于存放和维护可复用的 AI Skills。这些技能不只面向 Codex，也可供 OpenClaw 等兼容 Skill 机制的智能体读取和使用。

每个技能通常以独立目录组织，核心入口是 `SKILL.md`，并可按需包含 `scripts/`、`references/`、`assets/`、`agents/` 等资源。当前目录下的 Skill 已统一使用中文描述和中文界面元数据。

## 已有 Skills

| Skill | 目录 | 适用对象 | 用途 |
| --- | --- | --- | --- |
| `codex-skill-builder` | `codex-skill-builder/` | Codex、OpenClaw 或其他需要维护 Skill 的智能体 | 创建、更新、审查和验证 Skills。适合设计新技能、改进 `SKILL.md`、规划资源目录、维护界面元数据、检查 frontmatter 与结构规范。 |
| `stock-research-report` | `stock-research-report/` | Codex、OpenClaw 或配置了火山方舟 harness 的智能体 | 生成有来源标注的中文个股研究报告。优先使用 `dataPro` 获取结构化行情/财务数据，用豆包搜索补充公告、新闻和背景，并内置 OpenClaw/Codex 一键配置脚本。 |
| `us-stock-morning-skill` | `us-stock-morning-skill/` | Codex、OpenClaw 或其他可运行脚本并生成报告的智能体 | 生成中文美股开盘前早报或收盘后复盘。基于三大指数、行业/主题 ETF 强弱、宏观与消息面背景，输出专业、简洁的市场简报。 |
| `a-share-market-review-skill` | `a-share-market-review-skill/` | Codex、OpenClaw 或其他可运行脚本并生成报告的智能体 | 生成中文 A 股午间复盘和收盘复盘。基于沪深主要指数、行业/题材强弱、涨跌家数和市场情绪，输出午后观察或明日策略观察。 |
| `ppt-builder-skill` | `ppt-builder-skill/` | Codex、OpenClaw 或其他可运行 Node 脚本的智能体 | 从主题生成原生 `.pptx` 演示文稿。先产出大纲供确认，再按 JSON spec 调用脚本渲染幻灯片，内置 `default` / `dark` / `corporate` 三套预设主题。 |

## `codex-skill-builder`

该技能用于把重复的智能体工作流沉淀为可复用 Skill，并帮助维护 Skill 质量。

主要能力：

- 设计技能触发场景和用户请求示例。
- 选择符合规范的 lowercase hyphen-case 技能名称。
- 判断内容应放入 `SKILL.md`、`scripts/`、`references/` 还是 `assets/`。
- 创建或更新面向客户端展示的元数据，例如 `agents/openai.yaml`。
- 使用本地检查脚本验证技能目录结构和元数据。

常用校验命令：

```bash
python codex-skill-builder/scripts/inspect_skill.py <path-to-skill-folder>
```

## `stock-research-report`

该技能用于生成带来源、带时间戳、带风险提示的中文个股研究报告，适合以下请求：

- “生成贵州茅台（600519.SH）的个股研究报告”
- “分析某只股票最近成交量、涨跌幅和上次涨停时间”
- “整理一只股票的财务摘要、公告新闻和主要风险”
- “给 OpenClaw/Codex 一键配置火山方舟 dataPro 和豆包搜索”

工作流程：

1. 检查当前 Agent 是否具备 `dataPro` 和豆包搜索。
2. 若缺少工具，运行 `scripts/setup_harness.py` 为 `openclaw` 或 `codex` 一键配置火山方舟 harness。
3. 优先用 `dataPro` 查询结构化行情、交易、财务和估值数据。
4. 使用豆包搜索补充公告、交易所披露、新闻和行业背景。
5. 按 `references/report-template.md` 输出中文 Markdown 报告，并列出来源、数据时间、缺口和合规声明。

一键配置示例：

```bash
python stock-research-report/scripts/setup_harness.py openclaw
python stock-research-report/scripts/setup_harness.py codex
```

只注入 MCP 工具、不修改模型/provider：

```bash
python stock-research-report/scripts/setup_harness.py openclaw --mode mcp-only
python stock-research-report/scripts/setup_harness.py codex --mode mcp-only
```

> 注意：该技能只做信息整理和研究辅助，不构成证券投资建议。

## `us-stock-morning-skill`

该技能用于生成中文美股市场早报/复盘，适合以下请求：

- “生成今天的美股早报”
- “分析美股开盘前市场情况”
- “做一份美股收盘复盘”
- “解读三大指数和板块轮动”

工作流程：

1. 运行 `scripts/seedance.js` 获取市场数据。
2. 解析脚本返回的 `market_indices`、`strong_sectors`、`weak_sectors`。
3. 结合可获得的实时新闻、宏观背景或谨慎推理补充解释。
4. 生成包含大盘指数、强弱板块、市场风向、策略提示和免责声明的中文 Markdown 报告。

数据脚本示例：

```bash
node us-stock-morning-skill/scripts/seedance.js
```

> 注意：如果脚本返回备用或 mock 数据，报告中不应将其表述为实时数据。

## `a-share-market-review-skill`

该技能用于生成中文 A 股市场午间/收盘复盘，适合以下请求：

- “生成今天的大 A 午间复盘”
- “写一份 A 股午评”
- “做一份下午收盘复盘”
- “分析今天沪深指数和板块轮动”

工作流程：

1. 判断用户需要 `midday` 午间复盘还是 `close` 收盘复盘。
2. 运行 `scripts/a_share_review.js` 获取指数、板块和市场广度数据。
3. 解析脚本返回的 `market_indices`、`strong_sectors`、`weak_sectors`、`market_breadth`。
4. 生成包含指数表现、强弱板块、市场情绪、午后观察或明日策略观察的中文 Markdown 报告。

数据脚本示例：

```bash
node a-share-market-review-skill/scripts/a_share_review.js --session close
```

> 注意：如果脚本返回备用或 mock 数据，报告中不应将其表述为实时数据。

## `ppt-builder-skill`

该技能用于从主题生成原生 `.pptx` 演示文稿，适合以下请求：

- “帮我做一个 PPT”
- “生成一份汇报幻灯片”
- “把这份大纲做成演示文稿”
- “make a slide deck for ...”

工作流程：

1. 明确主题、受众、页数、语言与视觉主题（`default` / `dark` / `corporate`）。
2. 生成大纲（每页标题 + 要点），向用户展示并请求确认或微调。
3. 大纲确认后，按 `references/slide-spec.md` 写出 JSON spec 文件。
4. 首次使用在 skill 目录安装依赖：`npm install`（脚本依赖 `pptxgenjs`）。
5. 运行脚本生成 `.pptx`，报告输出路径。

脚本示例：

```bash
cd ppt-builder-skill
npm install
node scripts/build_pptx.js spec.json -o output.pptx
```

`spec.json` 的完整 schema、布局字段与端到端示例见 `ppt-builder-skill/references/slide-spec.md`。

## 目录结构约定

```text
skill-name/
├── SKILL.md          # 必需：技能元数据与执行说明
├── scripts/          # 可选：确定性脚本或工具
├── references/       # 可选：较长的参考资料、清单或规范
├── assets/           # 可选：输出时复用的模板、图片、字体等
└── agents/           # 可选：特定客户端或智能体的展示/集成元数据
```

## 维护建议

- 保持 `SKILL.md` 简洁，把触发条件写在 YAML `description` 中。
- 优先使用中文描述，便于中文场景触发和维护。
- 优先使用通用描述，避免把 Skill 限定为只能由某一个客户端使用。
- 只保留 `name` 和 `description` 两个 frontmatter 字段，除非目标运行时明确支持更多字段。
- 对脚本、模板和参考资料使用明确路径，并在 `SKILL.md` 中说明何时读取或运行。
- 修改技能后运行对应校验脚本，确认名称、frontmatter、资源引用和占位内容都符合预期。

## 批量校验

```bash
python codex-skill-builder/scripts/inspect_skill.py codex-skill-builder
python codex-skill-builder/scripts/inspect_skill.py stock-research-report
python codex-skill-builder/scripts/inspect_skill.py us-stock-morning-skill
python codex-skill-builder/scripts/inspect_skill.py a-share-market-review-skill
python codex-skill-builder/scripts/inspect_skill.py ppt-builder-skill
```