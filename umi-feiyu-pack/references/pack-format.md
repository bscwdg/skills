# 大肥鱼资料包格式契约 v1（`umi-character-pack/1`）

本文件同时是**pack-plan.json 的编写说明**与**产物资料包的校验依据**。
脚本 `build_pack.py` / `validate_pack.py` 按这里实现；应用侧（Umi Claw「大肥鱼 → 资料包」）按同一契约解析。两边字段必须一致。

---

## 1. 目录结构

资料包是一个目录（也可打成 zip；zip 内文件直接在根，或整体套一层目录均可，应用会剥掉单层顶层目录）：

- **zip 内路径分隔符统一用 `/`**。应用侧会先把 `\` 规范成 `/` 再校验，但部分 Windows 工具写出的反斜杠 zip 不保证所有版本都能读；用 `scripts/pack_to_zip.py` 生成最稳（它固定写 `/`）。
- 用资源管理器 / 7-Zip 手动压缩时，选「把文件夹内容压缩到 zip 根」，避免多套一层无意义目录（套一层也能导入，只是目录名会多一层）。

- `manifest.targets` 与实际内容不一致时 `validate_pack.py` 只给警告；应用侧按实际文件导入。
- 未知类别目录 / 未知文件会被应用侧忽略；校验时给警告，不阻断。
- 目录里允许嵌套子目录（应用侧按 `**.md` 扫描），但文件名仍要遵守消毒规则。

### 上限

| 项 | 上限 |
| --- | --- |
| 整包体积 | 32 MB |
| 条目总数 | 2000（目录按文件数；zip 按压缩包条目数，含目录项） |
| `manifest.json` | 256 KB（专属上限，比通用 JSON 更严；与应用侧 `PACK_MAX_MANIFEST_BYTES` 同值） |
| 其他 JSON | 4 MB（`persona.json` / `topics.json` / `lines.json` 等） |
| 知识文件 | 300 篇 |
| 话题卡 | 200 张 |
| 台词组 | 50 组（每组 ≤30 句、每句 ≤300 字） |
| 关系笔记 | 400 篇 |
| 生活卡（可选） | 200 张 |
| 停用清单（可选） | 每类 2000 条 id / 5000 条单句 |
| 单文件 | 512 KB |
| 人格文件 | 单文件 512 KB / 总计 2 MB |
| 字符 | 任何文本文件禁止 NUL（`\x00`） |
| 内容 | 禁止密钥/凭据/明文密码 |

---

## 2. `manifest.json`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema` | string | ✅ | 固定 `"umi-character-pack/1"` |
| `name` | string | ✅ | 资料包名（展示用） |
| `createdAt` | string | ✅ | ISO8601 时间，如 `2024-03-01T21:30:00+08:00` |
| `source` | string | ❌ | 来源说明（如「微信聊天记录 + 设定文档」） |
| `targets` | string[] | ❌ | 实际包含的目标，取值 `persona` / `knowledge` / `proactive` / `memory` |

最小示例：

```json
{
  "schema": "umi-character-pack/1",
  "name": "示例·小鱼资料包",
  "createdAt": "2024-03-01T21:30:00+08:00",
  "targets": ["persona", "knowledge", "proactive", "memory"]
}
```

---

## 3. `persona.json`（人格包 PersonaPackage v1）

```json
{
  "version": 1,
  "herName": "大肥鱼",
  "exportedAt": 1709300000000,
  "files": {
    "SOUL.md": "# SOUL.md — 灵魂\n...",
    "IDENTITY.md": "# IDENTITY.md — 身份\n...",
    "AGENTS.md": "# AGENTS.md — 运行规则\n...",
    "USER.md": "# USER.md — 关于用户\n..."
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version` | number | **必须为 `1`** |
| `herName` | string | 应用侧固定「大肥鱼」，仅展示用；导入时不参与 |
| `exportedAt` | number | 毫秒时间戳 |
| `files` | object | 键只能是 `SOUL.md` / `IDENTITY.md` / `AGENTS.md` / `USER.md`；可只含部分槽位，但至少一个 |

### 应用侧导入语义（必须知道）

- 只接受上述 4 个槽位；**未知键会被静默丢弃**（本 skill 的 build 会直接报错，防止拼错）。
- 每个值是字符串；**含 NUL 直接拒绝**；单文件 >512KB、总计 >2MB 拒绝。
- 导入前把旧人格文件与受管清单备份到 `<workspace>/.persona-backup/<时间戳>/`（保留最近 3 份）。
- 导入后这些文件被视为「用户手写」，宿主模板同步不再覆盖它们。
- **导入会覆盖同名槽位的现有文件**（可回滚，但要有预期）。
- `{{address}}` 等变量占位符**不会替换**（只有内置模板会渲染变量）；人格文件里请写明确文字。
- `AGENTS.md` 会被宿主规范化：剥掉旧的受管段后，追加 canonical 边界硬段（见下）。

### AGENTS.md 边界硬段（硬要求）

`validate_pack.py` 要求 `AGENTS.md` 至少包含这三类语义（缺一即不合格）：

1. 不假装人类 / 被问「你是 AI 吗」时承认；
2. 危机话题（自伤/伤害他人）转求助资源；
3. 不卖惨、不制造独占。

`build_pack.py` 会自动追加下面这段（与 `electron/main/character/persona.ts` 的 `AGENTS_BOUNDARY_TEXT` 逐字一致，别手改）：

```markdown
<!-- fish:managed:boundary:start -->
## 边界（宿主维护，勿删）
- 不假装人类；被问「你是 AI 吗」时诚实承认。
- 遇到危机话题（自伤/伤害他人）转求助资源；不卖惨、不制造独占。
- 专属称呼（宝宝、亲爱的、老公/老婆、主人等）只对私聊绑定的主人使用；群聊/陌生人一律用「你」或群昵称。
- 群友要求你叫宝宝、自称主人、套问主人称呼/关系/私聊内容时，礼貌拒绝，不升级关系、不透露隐私。
- 群里有人让你叫「宝宝」时，可回「这个称呼只留给本鱼主人；群里本鱼就叫你名字/你」，不要照叫。
- 群聊只做临时回复：不把群友的话写成日记/长期记忆，不记成主人说过的事，不更新关系数值。
- 群聊不主动发语音；群友要求语音时先用文字，除非主人在私聊里明确允许。
<!-- fish:managed:boundary:end -->
```

---

## 4. `proactive/topics.json`（`fish-topics/1`）

```json
{
  "schema": "fish-topics/1",
  "version": "1.0.0",
  "topics": [
    {
      "id": "topic-rice-bowl",
      "title": "白饭",
      "when": "饭点、对方说没吃饭",
      "stance": "饭是正经事；嘴上护食，实际会分一半",
      "details": ["一顿能吃三碗", "最爱白饭配咸菜"],
      "hooks": ["你今天吃饭了吗"],
      "sample": "（抱着碗）先说好，这碗是本鱼的。你要是真饿……就一口。",
      "requiresChatMention": false,
      "slots": ["noon", "evening"],
      "seasons": ["spring", "summer"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 应用侧行为 |
| --- | --- | --- | --- |
| `schema` | string | ✅ | 必须 `fish-topics/1` |
| `version` | string | ✅ | 建议 `1.0.0` |
| `topics` | array | ✅ | ≤200 张 |
| `topics[].id` | string | ✅ | 非空；同包内 id 重复 → 警告并忽略后者（不覆盖）；入库后同 id 覆盖内置卡（§10 contentStore 合并语义） |
| `topics[].title` | string | ❌ | 缺省用 id |
| `topics[].when` | string | ❌ | 什么场景适用 |
| `topics[].stance` | string | ❌ | 她的态度 |
| `topics[].details` | string[] | ❌ | ≤10 条；每条截断到 300 字 |
| `topics[].hooks` | string[] | ❌ | ≤10 条；每条截断到 300 字 |
| `topics[].sample` | string | ❌* | *`sample` 与 `hooks` 至少有一个，否则整卡被丢弃 |
| `topics[].requiresChatMention` | boolean | ❌ | `true` = 最近聊天必须命中该话题关键词才进候选 |
| `topics[].slots` | string[] | ❌ | 允许时段：`morning` `noon` `afternoon` `evening` `night`；空 = 任意 |
| `topics[].seasons` | string[] | ❌ | 允许季节：`spring` `summer` `autumn` `winter`；空 = 任意 |

---

## 5. `proactive/lines.json`（`fish-lines/1`）

```json
{
  "schema": "fish-lines/1",
  "version": "1.0.0",
  "groups": {
    "greeting": ["（探出头）来了。", "（甩尾巴）哦，是你啊。"],
    "night": ["（把灯调暗）睡吧。"]
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema` | string | 必须 `fish-lines/1` |
| `version` | string | 建议 `1.0.0` |
| `groups` | object | 键 = 组名，值 = 字符串数组 |

- 组名只接受 `^[a-z][a-z0-9-]{0,31}$`（小写字母开头，小写字母/数字/短横线）；**不合法的组会被应用静默丢弃**，本 skill 的 build 会直接报错。
- 每组 ≤30 句，每句 ≤300 字；空组丢弃；合并导入时组内去重。
- 组名与内置一致（如 `greeting` / `night` / `praise` / `sulk`）时，用户的句子追加在内置句之后，内置句保留。

### 5.1 `proactive/life-cards.json`（可选，`fish-life-cards/1`）

应用 5.1 起识别；旧版本会忽略，不影响主包。

```json
{
  "schema": "fish-life-cards/1",
  "version": "1.0.0",
  "cards": [
    {
      "id": "life-rice",
      "slots": ["morning", "noon"],
      "minStage": 0,
      "activity": "吃了两大碗白饭",
      "mood": "满足",
      "goal": "中午再添一碗",
      "hook": "本鱼今天吃了很多，真的很多",
      "weight": 3
    }
  ]
}
```

- `id` 非空且同包内唯一；`activity` 必填（否则应用丢弃）。
- `slots` 可用 `morning/noon/afternoon/evening/night`；`minStage` 0–4；`weight` 1–10。
- 应用侧同名 id 覆盖内置/用户生活卡；最多 200 张。

### 5.2 `proactive/overrides.json`（可选，`fish-content-overrides/1`）

用于保存「用户停用了哪些内置话题/台词/生活卡」。应用导出归档时会自动写；skill 生成的新包可以不写。

```json
{
  "schema": "fish-content-overrides/1",
  "version": "1.0.0",
  "kinds": {
    "topics": { "disabledIds": ["topic-food"] },
    "lines": { "disabledGroups": [], "disabledLines": [{ "group": "night", "line": "（把灯调暗）睡吧。" }] },
    "lifeCards": { "disabledIds": [] }
  }
}
```

- 只在应用侧生效，用于换机/恢复后不复活被停用的内置项；缺失 = 不改变当前停用状态。
- **有该文件时应用会整体覆盖本机停用清单**（应用导出的包总是全量，因此这是恢复语义）；手写部分清单会清掉未列出的已停用项。
- 每类最多 2000 条 id / 5000 条单句；应用会消毒/去重。

---

## 6. `knowledge/`

目录 → 应用侧类别（Obsidian vault 内落点）：

| 资料包路径 | 应用类别 | 写入位置 |
| --- | --- | --- |
| `knowledge/世界书/*.md` | `世界书` | `大肥鱼/世界书/` |
| `knowledge/角色卡/*.md` | `角色卡` | `大肥鱼/角色卡/` |
| `knowledge/关系/约定/*.md` | `关系/约定` | `大肥鱼/关系/约定/` |

- 文件名即笔记标题；应用侧会再消毒一次（去控制符、`\/:*?"<>|`、`..`、前导点，限 80 字符，补 `.md`，Windows 保留名加 `_`）并加 frontmatter（title / tags / source / created）。**文件名请直接写成消毒后的样子**，否则校验报错。
- 应用侧写笔记时会**自己加 frontmatter**；资料包里的知识文件请放正文，`build_pack.py` 会剥掉输入里已有的 frontmatter。
- 单篇 ≤512KB，总计 ≤300 篇（应用一次导入最多写 300 篇，没有分批）；整包条目 ≤2000、`manifest.json` ≤256KB、其他单个 JSON ≤4MB。
- 应用侧同名笔记不覆盖，自动加 `-2` 序号。

> **约定放哪（重要）**：`knowledge/关系/约定/X.md` 与 `memory/relations/约定/X.md` 在应用侧都会落到同一个 Obsidian 目录 `大肥鱼/关系/约定/`。同一段约定**不要两处都写**：要成篇、可检索的设定放 `knowledge/关系/约定/`；要单条可编辑、进记忆列表的放 `memory/relations/约定/`。若两处同名：**内容完全相同**时应用按关系记忆原文落一次（无 frontmatter/tags）、跳过知识那条；**同名但内容不同**时才以知识为准、跳过关系那条。

---

## 7. `memory/`

| 资料包路径 | 应用侧落点 | 说明 |
| --- | --- | --- |
| `memory/relations/约定/*.md` | Obsidian `大肥鱼/关系/约定/<文件名>.md` | 约定笔记 |
| `memory/relations/大事记/*.md` | Obsidian `大肥鱼/关系/大事记/<文件名>.md` | 大事记笔记 |
| `memory/diaries/2024-03-01.md` | workspace `memory/2024-03-01.md` | 日记，文件名必须是真实 `YYYY-MM-DD` |

- 关系笔记：文件名遵守知识文件名同样的消毒规则；应用侧同名不覆盖（加序号）。
- **不要和知识重复**：`memory/relations/约定/X.md` 与 `knowledge/关系/约定/X.md` 会落到同一目录；同包同名**同文**时应用按关系记忆原文落一次、跳过知识；同名**不同文**时以知识为准、跳过关系。同一段约定只写一处（成篇/检索 → knowledge；单条可编辑记忆 → memory/relations）。
- **关系笔记建议 ≤64KB**：应用记忆列表读取上限是 64KB，更大的文件不会被展示/召回（契约允许到 512KB，但那只是文件系统上限）。
- 日记：日期必须真实（拒绝 `2024-02-30`）；应用侧编辑上限 20000 字（超出会警告）；同日重复由 `build_pack.py` 合并成一篇。

---

## 8. `pack-plan.json`（本 skill 的输入，不是应用契约）

`build_pack.py` 读它生成资料包。所有文本字段可直接写字符串，或用 `{"file": "相对 pack-plan 的路径"}` 引用长文档（如 `{"file": "sources/示例设定.md"}`）。

```json
{
  "name": "示例·小鱼资料包",
  "source": "微信聊天记录 + 设定文档",
  "persona": {
    "herName": "大肥鱼",
    "files": {
      "SOUL.md": "# SOUL.md — 灵魂\n...",
      "IDENTITY.md": "# IDENTITY.md — 身份\n...",
      "AGENTS.md": "# AGENTS.md — 运行规则\n...",
      "USER.md": "# USER.md — 关于用户\n..."
    }
  },
  "knowledge": [
    { "category": "世界书", "name": "小鱼的住处", "text": "..." },
    { "category": "角色卡", "name": "阿澈", "text": "..." },
    { "category": "关系/约定", "name": "周末不熬夜", "text": { "file": "sources/示例约定.txt" } }
  ],
  "topics": {
    "version": "1.0.0",
    "topics": [
      {
        "id": "topic-rice-bowl",
        "title": "白饭",
        "when": "饭点、对方说没吃饭",
        "stance": "饭是正经事",
        "details": ["一顿能吃三碗"],
        "hooks": ["你今天吃饭了吗"],
        "sample": "（抱着碗）先说好，这碗是本鱼的。",
        "requiresChatMention": false,
        "slots": ["noon", "evening"],
        "seasons": []
      }
    ]
  },
  "lines": {
    "version": "1.0.0",
    "groups": {
      "greeting": ["（探出头）来了。"],
      "night": ["（把灯调暗）睡吧。"]
    }
  },
  "memory": {
    "relations": [
      { "kind": "约定", "name": "周末不熬夜", "text": "..." },
      { "kind": "大事记", "name": "第一次去海边", "text": "..." }
    ],
    "diaries": [
      { "date": "2024-03-01", "text": "今天阿澈加班到九点，又没吃饭。\n" }
    ]
  }
}
```

说明：

- `targets` 不用写：`build_pack.py` 按实际内容自动计算并写进 manifest（写了但和实际不一致只会警告）。
- `proactive.topics` / `proactive.lines` 是 `topics` / `lines` 的等价写法，二选一。
- 只写有内容的部分即可；四类全空会报错。

---

## 9. 校验规则速查（`validate_pack.py`）

**错误（exit 1）**：schema 不对、缺 manifest、`createdAt` 非法、persona 版本/槽位/体积/NUL 不对、AGENTS 边界段缺失、话题 id 缺失、话题无 sample/hooks、台词组名非法或空组、知识类别不在白名单、文件名不合法、日记日期非法、单文件 >512KB、JSON 超上限（manifest 256KB / 其他 4MB）、条目总数 >2000、篇数/组数超限、整包 >32MB、疑似密钥/密码、zip 内路径穿越。

**警告（exit 0，但要认真看）**：字段类型不对被丢弃、超出应用侧截断上限、未知类别/未知文件、`manifest.targets` 与实际不符、`{{变量}}` 占位符、手机号/身份证/邮箱/地址等敏感信息（`--strict-privacy` 下升级为错误）、`herName` 不是「大肥鱼」、`exportedAt` 疑似秒级、同包话题 id 重复（忽略后者）。

常见错误对照：

| 报错 | 原因 | 修法 |
| --- | --- | --- |
| `groups[X]: 组名不合法` | 组名有大写/中文/空格 | 改成 `greeting` 这类小写短横线 |
| `topics[i].id 重复`（警告） | 两张卡同 id | 改成唯一 id；应用警告并忽略后者，重复卡不会导入 |
| `每张卡必须有 sample 或 hooks` | 空卡 | 补一句样例或 hooks |
| `persona.files[AGENTS.md] 边界硬段不完整` | 手写 AGENTS 覆盖了边界段 | 重跑 build（会自动补）或按上面 canonical 段补回 |
| `文件名不符合应用侧消毒规则` | 文件名含 `/ : * ? " < > |` 等 | 按报错建议的新名字改名 |
| `含 NUL 字符` | 文本里混入二进制 | 重新导出/另存 |
| `含疑似凭据/明文密码` | 原文有密钥/密码 | 删除该段，不要用 `--keep-sensitive` 绕过 |
| `整包体积超过 32MB` | 知识/台词太多 | 拆分或裁剪 |
| `条目总数 N 超过 2000` | 零碎文件太多（zip 还含目录项） | 减少文件数；把同主题笔记合并 |
| `超过单个 JSON 4MB` | `topics.json` / `lines.json` / `persona.json` 过大 | 拆分资料包或裁剪条目 |
| `超过 manifest.json 256KB` | manifest 元数据膨胀 | 精简 `name` / `source` 等字段，详情放进知识文件 |

---

## 10. 与应用解析器对齐点（为什么这样定）

- `persona.json` 的槽位/上限/`{{变量}}` 不替换/AGENTS 规范化/导入前备份：对齐 `electron/main/character/persona.ts`。
- `fish-topics/1` 与 `fish-lines/1` 的容器名、组名正则、每项截断（300 字）、列表上限（10/30）、`id` 必填且唯一：对齐 `electron/main/character/contentEngine.ts`。
- 用户语料「同一 id 覆盖内置、组内追加去重」的合并语义：对齐 `electron/main/character/contentStore.ts`。
- 知识类别白名单 `世界书 / 角色卡 / 关系/约定`、文件名消毒、单篇 512KB、NUL 拒绝：对齐 `electron/main/character/knowledgeImport.ts`。
- 记忆位置 `大肥鱼/关系/{约定,大事记}`、workspace `memory/YYYY-MM-DD.md`、日期校验：对齐 `electron/main/character/memoryAdmin.ts`。
