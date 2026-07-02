# Slide Spec 规范

`build_pptx.js` 读取一个 JSON 文件作为幻灯片规格（spec），据此生成 `.pptx`。本文档定义 spec 的结构、各布局字段与主题取值。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 演示文稿标题，用于标题页与文件元数据 |
| `subtitle` | string | 否 | 标题页副标题 |
| `author` | string | 否 | 作者，显示于标题页底部并写入文件属性 |
| `theme` | string | 否 | 主题名：`default` / `dark` / `corporate`，默认 `default` |
| `slides` | array | 是 | 幻灯片对象数组，按顺序渲染 |

## 主题

| 主题 | 背景 | 标题色 | 强调色 | 适用场景 |
| --- | --- | --- | --- | --- |
| `default` | 白底 | 深蓝 | 亮蓝 | 通用、商务汇报 |
| `dark` | 深灰底 | 白字 | 青蓝 | 科技、发布会的暗光环境 |
| `corporate` | 浅灰底 | 深灰 | 橙色 | 企业内训、品牌风 |

字体统一使用 `Microsoft YaHei`（中英文兼容）。CLI 的 `--theme` 参数会覆盖 spec 中的 `theme` 字段。

## 布局（layout）

每张幻灯片通过 `layout` 字段选择渲染方式。所有布局均可选填 `notes`（演讲备注，不显示在正片上）。

### `title` — 标题页
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `layout` | `"title"` | 是 | |
| `title` | string | 是 | 大标题 |
| `subtitle` | string | 否 | 副标题 |
| `author` | string | 否 | 作者署名 |

### `bullets` — 项目符号页
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `layout` | `"bullets"` | 是 | |
| `title` | string | 是 | 页面标题 |
| `bullets` | array | 否 | 字符串数组，或 `{ "text": string, "level": number }` 对象数组；`level` 0 为一级，1 为二级缩进 |
| `notes` | string | 否 | 演讲备注 |

### `section` — 章节分隔页
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `layout` | `"section"` | 是 | |
| `title` | string | 是 | 章节名 |
| `subtitle` | string | 否 | 章节说明 |

整页以强调色为背景、白色大字呈现，用于段落切换。

### `two-column` — 双栏页
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `layout` | `"two-column"` | 是 | |
| `title` | string | 是 | 页面标题 |
| `columns` | `[array, array]` | 否 | 二维数组，`columns[0]` 为左栏、`columns[1]` 为右栏；每栏同 `bullets` 元素格式 |
| `notes` | string | 否 | 演讲备注 |

### `quote` — 引用页
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `layout` | `"quote"` | 是 | |
| `quote` | string | 是 | 引文正文 |
| `author` | string | 否 | 出处/署名，自动加前缀 `— ` |
| `notes` | string | 否 | 演讲备注 |

## 编写建议

- 单页 `bullets` 不超过 6 条，单条文字不超过 30 字，避免满屏文字。
- 用 `section` 页把内容分成 3–5 个段落，节奏更清晰。
- 二级要点用 `{ "text": "...", "level": 1 }` 表达，不要靠手敲空格缩进。
- 演讲者想说的、但不希望显示在屏幕上的话放进 `notes`。
- 未知 `layout` 会被跳过并在 stderr 给出警告，不会中断生成。

## 端到端示例

```json
{
  "title": "2026 下半年产品规划",
  "subtitle": "从增长到留存",
  "author": "产品团队",
  "theme": "default",
  "slides": [
    { "layout": "title", "title": "2026 下半年产品规划", "subtitle": "从增长到留存", "author": "产品团队" },
    { "layout": "section", "title": "一、上半年回顾" },
    {
      "layout": "bullets",
      "title": "关键指标",
      "bullets": [
        "月活同比增长 32%",
        { "text": "留存低于行业基准 5pp", "level": 1 },
        "付费转化率 4.1%"
      ],
      "notes": "留存是本次规划的核心命题。"
    },
    {
      "layout": "two-column",
      "title": "机会与风险",
      "columns": [
        ["下沉市场空白", "AI 能力可复用"],
        ["竞品加速", "团队招聘滞后"]
      ]
    },
    { "layout": "quote", "quote": "增长是结果，留存才是产品力。", "author": "CEO 周会发言" },
    { "layout": "section", "title": "二、下半年目标" },
    {
      "layout": "bullets",
      "title": "三大战役",
      "bullets": ["留存提升计划", "付费体系重构", "AI 功能矩阵"]
    }
  ]
}
```
