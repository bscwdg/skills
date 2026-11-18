---
name: umi-feiyu-pack
description: 把微信/QQ 聊天记录、Word(.docx)、PDF、txt/md/HTML 文档，以及其他 AI 角色应用导出的角色卡与世界书（SillyTavern/Chub 的 Character Card V1/V2/V3 JSON、PNG 内嵌 chara/ccv3 角色卡、World Info/Lorebook JSON）整理成 Umi Claw「大肥鱼」可一键导入的资料包（人格 / 知识 / 主动消息 / 记忆）。用户想给大肥鱼喂人设、把聊天记录变成她的人格与记忆、把设定文档导入世界书/角色卡、导入现成角色卡/世界书、生成 fish-topics/1 话题卡或 fish-lines/1 台词库、或要求「生成/校验大肥鱼资料包」时使用；也用于把结果打成 umi-character-pack/1 目录或 zip 交给应用侧导入。
---

# 大肥鱼资料包生成器

把一批本地资料整理成 Umi Claw「大肥鱼」的资料包（格式契约 `umi-character-pack/1`）。

- **输入**：微信/QQ 聊天记录导出、Word(.docx)、PDF、txt/md/HTML，以及 SillyTavern / Chub 等应用的 Character Card JSON（V1/V2/V3）、PNG 内嵌角色卡、World Info / Lorebook JSON。
- **输出**：一个目录（可再打 zip），包含人格文件、知识笔记、主动消息话题/台词、关系与日记；在 Umi Claw「大肥鱼 → 资料包」里一键导入。
- **全程本地处理**：脚本只读输入、只写你指定的工作目录，不联网、不上传。

## 隐私红线（不可协商）

- 只在本地处理；不把原文、文件路径、隐私内容发到任何外部服务。
- 默认丢弃敏感信息：`build_pack.py` 自动脱敏手机号、身份证号、银行卡号、邮箱、门牌地址；检测到密钥/私钥/Token/明文密码**直接失败**，要求删除。
- 无法可靠自动识别的（密码、真实姓名、学校单位、他人隐私）必须按 `references/conversion-guide.md` 的脱敏清单人工检查。
- 不要把原始聊天记录整段塞进资料包；只保留提炼后的性格、设定、约定、日记片段。
- 涉及真实第三方：先化名，不写可识别的个人信息。示例只用合成内容，不要把真实用户数据写进 `examples/`。

## 前置检查

1. `python --version` ≥ 3.9。脚本只用 Python 标准库；`scripts/` 内脚本互相依赖 `pack_common.py`，请整体使用，不要单独拷走一个脚本。
2. PDF 需要可选依赖：`python -m pip install pypdf`（或 `pdfminer.six`）。缺库时脚本明确报错并给替代方案，不会静默跳过。
3. 准备工作目录（例如 `D:\feiyu-pack-work`），原始资料放 `<工作目录>/输入/`。
4. 可回退：应用侧导入资料包前会自动把当前内容备份为「大肥鱼资料包-<时间>」目录（资料包格式），需要回滚时用「导入资料包（文件夹）」把它导回去即可。

## 工作流

### 1) 收集输入

把聊天记录导出、Word、PDF、文本，以及现成的角色卡/世界书 JSON、PNG 角色卡放进 `<工作目录>/输入/`。

- 支持：`.txt` `.md` `.html` `.docx` `.pdf` `.json` `.png`
- `.json` 会自动辨识三种情况：**Character Card V2/V3**（`{spec, spec_version, data}`）、**V1 扁平卡**（顶层 `name/description/personality/...`）、**World Info / Lorebook**（顶层 `entries` 或 `world_info`）。
- `.png` 只读取内嵌的 `chara` / `ccv3` 文本块（Character Card 规范）；普通图片没有这些块，会警告跳过。
- 不支持：旧版 `.doc`（先另存为 `.docx`/`.txt`）、PNG 以外的普通图片里的文字（先用图片理解/OCR 转成文字）、非角色卡/世界书结构的 JSON（会原样保留并警告，不会误当角色卡）。

### 2) 提取

```bash
python scripts/extract_sources.py "<工作目录>/输入" -o "<工作目录>/提取结果"
```

产出：

- `sources/*.md`：每份输入的纯文本；角色卡会按「名字/描述/性格/场景/开场/示例对话/创作者备注/系统提示词/备选开场白/其他字段」分段，世界书每条一个二级标题（`comment` 或关键词命名），正文保留 `content`。未知/非法 JSON 原样保留。
- `messages.jsonl`：聊天消息，字段 `ts / speaker / text`
- `stats.json`：每个文件的字符数、是否识别为聊天、消息数、警告；`files[].kind` 标记 `character-card` / `world-info` / `json-raw`，`files[].format` 标记具体格式（如 `character-card-v2`、`character-card-v3`、`character-card-v1`、`world-info`）。

能识别的聊天格式（同一文件可混用）：`2024-03-01 21:12:00 昵称`、`昵称(QQ号)`、`2024-03-01 21:12:00 昵称: 内容`、`[2024-03-01 21:12:00] 昵称: 内容`、`昵称 2024-03-01 21:12`、只有日期的分组行（后接 `昵称: 内容`）。

JSON / PNG 的识别边界：

- 角色卡：V2/V3 靠 `spec`（`chara_card_v2` / `chara_card_v3`）或 `data` 里的 `name` + 角色卡字段；V1 必须是「`name` + 至少两个角色卡字段」的扁平结构，普通配置 JSON 不会被误判。
- 世界书：顶层 `entries`（对象或数组）、`world_info.entries`、`world_info` 直接映射都支持；条目必须有 `content`，或「关键词 + comment」；`disable:true` / `enabled:false` 的条目跳过。
- PNG：带 `chara` 优先、没有则用 `ccv3`；内嵌 base64 JSON 损坏算文件失败，普通 PNG（无这两个块）只在警告里跳过。
- 文件扩展名大小写不敏感；JSON 解码沿用 `utf-8-sig → GB18030 → UTF-16` 兜底。

退出码 1 = 有文件没提取成功（如缺 PDF 库、PNG 内嵌角色卡损坏、编码无法识别），按输出里的替代方案补齐后再继续；未知 JSON 与普通 PNG 只给警告，不算失败。

### 3) 阅读与提炼

读 `sources/*.md` 与 `messages.jsonl`，按 `references/conversion-guide.md` 的启发式提炼：

| 提炼结果 | 放到哪里 |
| --- | --- |
| 她的说话方式、性格、在意的东西 | `persona` 的 `SOUL.md` / `IDENTITY.md` |
| 角色卡的 `description` / `personality` / `scenario` | `persona` 的 `SOUL.md` / `IDENTITY.md` + `knowledge/角色卡/` |
| 角色卡的开场白、备选开场白、示例对话 | `proactive/lines.json` 的台词、`proactive/topics.json` 的风格（先改写 `{{char}}`/`{{user}}`） |
| 世界书条目的 `content` / `comment` | `knowledge/世界书/` |
| 称呼规则、运行规则 | `persona` 的 `AGENTS.md` |
| 关于用户（称呼、习惯、雷区） | `persona` 的 `USER.md` |
| 世界观、地点、物件、关系史 | `knowledge/世界书/` |
| 人物设定 | `knowledge/角色卡/` |
| 双方约定（成篇、要检索） | `knowledge/关系/约定/` |
| 双方约定（单条、要可编辑记忆） | `memory/relations/约定/` |
| 重要事件 | `memory/relations/大事记/` |
| 日常话题 / 台词 | `proactive/topics.json` / `proactive/lines.json` |
| 具体某天发生的事 | `memory/diaries/YYYY-MM-DD.md` |

角色卡/世界书的逐字段映射、宏改写与版权/隐私注意，见 `references/conversion-guide.md` 的「从角色卡/世界书 JSON 提炼」一节。

> **同一段约定不要两处都写**：`knowledge/关系/约定/X.md` 与 `memory/relations/约定/X.md` 在应用侧都会落到 `大肥鱼/关系/约定/`；同包同名**同文**时应用按关系记忆原文落一次（无 frontmatter/tags）、跳过知识那条；同名**不同文**时才以知识为准、跳过关系那条。要成篇/可检索放 knowledge，要单条可编辑记忆放 memory，二选一。

### 4) 写 pack-plan.json

按 `references/pack-format.md` 的结构写 `<工作目录>/pack-plan.json`（字段完整说明 + 最小示例）。长文档可用 `{"file": "sources/xxx.md"}` 引用，路径相对 pack-plan 所在目录。

### 5) 生成资料包

```bash
python scripts/build_pack.py "<工作目录>/pack-plan.json" -o "<工作目录>/资料包" --force
```

- 自动补 `AGENTS.md` 边界硬段、消毒文件名、去重、校验上限、默认脱敏。
- `--keep-sensitive`：关闭默认脱敏（确需保留虚构地址等）；`--strict-privacy`：发现个人敏感信息直接报错（不脱敏）。
- 逐条看警告：多数警告意味着应用侧会截断/忽略那部分内容。

### 6) 校验（必须全绿）

```bash
python scripts/validate_pack.py "<工作目录>/资料包"
```

- 退出码 0 = 合格（允许有警告）；1 = 不合格，按错误清单逐条修。
- 也可直接校验 zip：`python scripts/validate_pack.py "<工作目录>/资料包.zip"`。
- 需要打 zip：`python scripts/pack_to_zip.py "<工作目录>/资料包" -o "<工作目录>/资料包.zip"`。

### 7) 交付

向用户报告：资料包路径、统计（人格槽位 / 知识篇数 / 话题 / 台词 / 关系 / 日记）、警告清单、脱敏了什么。提醒：导入前应用会自动整包备份。

## 导入到 Umi Claw

两条路径，任选：

1. **把技能装进 Umi Claw**：在「技能」页点「导入技能 zip」，选择本仓库根目录的 `umi-feiyu-pack.zip`（包内顶层目录必须是 `umi-feiyu-pack/SKILL.md`）；或解压到 `<数据目录>/config/.openclaw/skills/umi-feiyu-pack/`。装好后在聊天里让 agent 用该技能生成资料包。
2. **只导入资料包**：生成好的资料包在「大肥鱼 → 资料包」卡里用「导入资料包（文件夹）」或「导入 zip」一键导入人格/知识/主动消息/记忆；导入前应用会自动整包备份为「大肥鱼资料包-<时间>」目录，可再导入恢复。

## 质量门槛

交付前逐条确认：

- `validate_pack.py` 退出码 0（错误为 0）。
- 没有整段复制原始聊天；话题卡每张有 `sample` 或 `hooks`；台词组名是小写短横线。
- 同一段约定没有同时写进 `knowledge/关系/约定/` 与 `memory/relations/约定/`（同名会被应用去重跳过）。
- 人格文件里没有 `{{address}}` 之类变量占位符（应用导入不会替换变量）。
- `AGENTS.md` 含边界硬段（不假装人类 / 危机转介 / 不卖惨不制造独占）。
- 敏感信息已脱敏，或用户明确要求保留且确认是虚构内容。
- 从角色卡/世界书提炼时，`{{char}}`/`{{user}}` 宏已改写成真实称呼，`disable:true` 条目没有导入，`creator_notes`/`creator`/`source` 等作者元数据没有当成人设。
- 上限：整包 ≤32MB、条目总数 ≤2000、`manifest.json` ≤256KB（专属）、其他单个 JSON ≤4MB、知识 ≤300 篇、话题 ≤200 张、台词组 ≤50 组、关系 ≤400 篇、生活卡 ≤200 张、单文件 ≤512KB。

## 已知限制

- **PDF**：依赖可选库 `pypdf`/`pdfminer.six`；未安装时报错并给替代方案（用 agent 的 PDF 阅读工具转文本，或用 office 技能转 docx）。扫描件需要 OCR。
- **.docx**：用 zipfile + XML 解析，只提取正文段落文字；图片、文本框、批注、页眉页脚不提取。
- **旧版 .doc / PNG 以外的图片里的字**不支持，先转换。
- **角色卡 JSON**：只识别 Character Card V1 扁平结构、V2/V3 的 `{spec, spec_version, data}`（含 `chara_card_v2` / `chara_card_v3`）。字段按原文写入 Markdown，不解析或替换 `{{char}}`/`{{user}}` 宏；`extensions`、`assets` 等未列入常用段的字段会以 JSON 形式保留在「其他字段」，但不会自动转换成资料包字段，需要人工按 `references/conversion-guide.md` 提炼。其他形状的 JSON 不会猜成角色卡：原样保留到 `sources/` 并警告。
- **世界书 JSON**：支持 `entries`（对象/数组）、`world_info.entries`、`world_info` 直接映射。只把 `comment` / `key` / `keysecondary` / `content` 转成 Markdown；`order`、`probability`、`position` 等触发/排序元数据不进入 `sources/`（提炼知识笔记用不到）。`disable:true` / `enabled:false` 的条目跳过并给警告。
- **PNG 角色卡**：用标准库 `struct`/`zlib`/`base64` 读 `tEXt`/`zTXt`/`iTXt` 里的 `chara`（优先）或 `ccv3`，不依赖 Pillow，也不提取图像内容。普通 PNG（没有这两个块）会警告跳过、不算失败；内嵌 base64/JSON 损坏或 PNG 结构损坏会以退出码 1 报错。只支持 PNG，JPG/WebP 等格式不读。
- **JSON 大小/编码**：单文件上限 64MB；编码沿用 `utf-8-sig → GB18030 → UTF-16` 兜底，非这几种编码会报错并提示另存为 UTF-8。
- **聊天格式**千差万别：无法识别的行会留在 `sources/*.md` 原文里，`messages.jsonl` 可能不全，需人工核对 `stats.json`。
- **脱敏是启发式**：地址、密码、真实姓名无法 100% 识别，人工检查是必须的。
- **应用侧会截断**：话题 `details`/`hooks` 各取 10 条、每条 300 字；每组台词取 30 句、每句 300 字；超限内容不生效。
- 导入人格包会覆盖同名槽位文件（导入前自动备份旧人格）；只想改一个文件时，不要整包含 `AGENTS.md`。

## 资源

- `references/pack-format.md`：完整字段契约 + 最小合法示例 + 与应用解析器的对齐点。**写 pack-plan 前必读。**
- `references/conversion-guide.md`：聊天记录 → 人格/世界书/角色卡/约定/话题/台词的抽取启发式、角色卡/世界书 JSON 的逐字段映射、脱敏清单、质量问题清单。**提炼前必读。**
- `examples/`：合成示例（`sources/` 输入、`pack-plan.json`、`示例资料包/` 产物）。其中 `sources/角色卡V2示例.json`、`sources/world-info示例.json`、`sources/角色卡示例.png` 演示角色卡/世界书输入，可照抄结构。

复现示例（在本 skill 目录下运行；`提取结果/` 是本地生成物，不随仓库提交）：

```bash
python scripts/extract_sources.py examples/sources -o examples/提取结果
python scripts/build_pack.py examples/pack-plan.json -o examples/示例资料包 --force
python scripts/validate_pack.py examples/示例资料包
```
