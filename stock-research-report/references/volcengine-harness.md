# 火山方舟 Harness 配置

当用户需要为 Codex/OpenClaw 配置个股报告工作流，或当前 Agent 无法使用 `dataPro` / 豆包搜索时，阅读本文件。

## 必要能力

- 已开通支持内置 harness 的火山方舟 Agent Plan。
- `dataPro`：用于查询专业结构化数据集。
- 豆包搜索：用于查询公开网页、公告、新闻和背景信息。
- 目标 Agent 支持 `arkcli helper` 注入；本 Skill 重点支持 `codex` 和 `openclaw`。

## 一键配置

优先使用本 Skill 自带的包装脚本，避免让用户记忆多条 `arkcli` 参数。

配置 OpenClaw，同时设置火山方舟模型/provider 并注入 MCP harness：

```bash
python scripts/setup_harness.py openclaw
```

配置 Codex，同时设置火山方舟模型/provider 并注入 MCP harness：

```bash
python scripts/setup_harness.py codex
```

只注入 MCP 工具，不修改模型/provider：

```bash
python scripts/setup_harness.py openclaw --mode mcp-only
python scripts/setup_harness.py codex --mode mcp-only
```

只预览底层 `arkcli` 命令，不修改配置：

```bash
python scripts/setup_harness.py openclaw --dry-run
```

配置完成后，重启目标 Agent，新的 MCP server 才会加载。

## 底层 arkcli 命令

配置模型/provider，同时注入 MCP harness：

```bash
arkcli helper configure codex --with-mcp
arkcli helper configure openclaw --with-mcp
```

只注入 MCP 工具，不修改模型/provider：

```bash
arkcli helper mcp codex
arkcli helper mcp openclaw
```

只有在包装脚本不可用，或需要更高级参数时，才建议用户直接运行这些底层命令。

## 工具分工

- `dataPro`：优先用于个股结构化数据、市场指标、财务指标和专业时间序列事实。
- 豆包搜索：用于补充官方公告、交易所披露、公司页面、公开新闻和行业背景。
- 火山方舟模型：用于规划查询、归纳信息、处理冲突和撰写最终报告。

## 配置判断规则

- 用户说“给 Codex 用”或当前在 Codex 中使用时，目标选择 `codex`。
- 用户说“兼容 OpenClaw”或在 OpenClaw 中使用时，目标选择 `openclaw`。
- 用户要完整接入时，使用 `python scripts/setup_harness.py <target>`。
- 用户只想加数据/搜索工具时，使用 `python scripts/setup_harness.py <target> --mode mcp-only`。
- 如果出现登录、401、权限、套餐问题，先处理 arkcli 认证/profile/Agent Plan 问题，再继续生成报告。

## 外部参考

- Agent Plan 计费与套餐说明：https://www.volcengine.com/docs/82379/2479086?lang=zh#billing
- Harness / dataPro 相关说明：https://www.volcengine.com/docs/82379/2301412?lang=zh

不要声称这些链接保证某个具体金融字段一定可用。必须在运行时检查工具是否可用、字段是否实际返回。
