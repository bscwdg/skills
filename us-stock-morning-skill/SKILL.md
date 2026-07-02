---
name: us-stock-morning-skill
description: 生成中文美股开盘前早报或收盘后复盘，覆盖美股主要指数、行业 ETF 强弱和宏观新闻背景。用户要求美股早报、美股开盘前分析、收盘复盘、三大指数解读、sector ETF rotation 或 US stock market briefing 时使用。
---

# US Stock Morning Skill

Use this skill to produce a professional Chinese market briefing for US stocks before the open or after the close.

## Workflow

1. Run the bundled market data script to collect major index and sector ETF data:

   ```bash
   node "$SKILL_DIR/scripts/seedance.js"
   ```

   On Windows CMD, use:

   ```cmd
   node "%SKILL_DIR%\scripts\seedance.js"
   ```

2. Parse the JSON output:
   - Use `market_indices` for Nasdaq Composite, S&P 500, and Dow Jones Industrial Average performance.
   - Use `strong_sectors` for the strongest sector or thematic ETFs.
   - Use `weak_sectors` for the weakest sector or thematic ETFs.
   - Treat `change_pct` as percentage change and `close` as the latest point or price.

3. Add current market context when available:
   - Prefer available web/search tools for fresh macro headlines, earnings news, Fed/rate expectations, oil, yields, dollar, or geopolitical catalysts.
   - If search is unavailable or blocked, infer cautiously from index divergence and sector rotation in the script output.
   - Clearly avoid inventing specific news events that were not observed.

4. Write the final answer in Chinese with a professional, concise analyst tone.

## Report Template

```markdown
📅 **美股早报 | [当前日期]**
---

📊 **大盘指数表现**
* 🟢/🔴 **纳斯达克综合指数**：`点位`（`涨跌幅%`）
* 🟢/🔴 **标普 500 指数**：`点位`（`涨跌幅%`）
* 🟢/🔴 **道琼斯工业平均指数**：`点位`（`涨跌幅%`）

[基于三大指数表现，用一句话概括市场风险偏好、成长/价值风格或多空情绪。]

🔥 **主流行业核心 ETF 热力图**
* 🟢 **强势板块（Top Gainers）**
  1. **[板块名称]**（`代码`）涨跌幅：`涨幅%` | 分类：`[分类标签]`
     — [结合数据和可验证新闻，解释资金流入逻辑。]
  2. **[板块名称]**（`代码`）涨跌幅：`涨幅%` | 分类：`[分类标签]`
     — [解释该板块领涨背后的宏观、盈利或风险偏好线索。]

* 🔴 **弱势板块（Top Losers）**
  1. **[板块名称]**（`代码`）涨跌幅：`跌幅%` | 分类：`[分类标签]`
     — [解释该板块回落反映的防御情绪、利率压力或基本面压力。]
  2. **[板块名称]**（`代码`）涨跌幅：`跌幅%` | 分类：`[分类标签]`
     — [说明该弱势是否属于轮动、避险或事件驱动。]

📰 **市场风向透视**
* **【板块轮动解读】** [总结资金从哪些板块流出、流入哪些板块，以及这对市场风格的含义。]
* **【宏观与消息面】** [结合可获得的新闻或谨慎推断，说明利率、美元、油价、财报或政策因素。]

💡 **今日投资策略建议**
[给出理性的方向提示，例如关注强势主线延续性、控制追高风险、观察防御板块表现等。]

---
*⚠️ 免责声明：投资有风险，入市需谨慎。以上内容由 AI 基于公开市场数据和可获得信息自动分析，不构成任何投资操作建议。*
```

## Output Rules

- Keep the report compact unless the user asks for a deeper version.
- Label uncertain inferences as “可能”“倾向于”“需继续观察”.
- Do not present stale fallback data as real-time data if the script source indicates a backup or mock source.
- Do not provide personalized buy/sell instructions; frame strategy as risk-aware market observation.
