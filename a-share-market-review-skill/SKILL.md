---
name: a-share-market-review-skill
description: 生成中文 A 股午间复盘和收盘复盘。用户要求大 A 午间复盘、A 股午评、A 股收盘复盘、下午收盘复盘、沪深指数解读、板块轮动分析、涨跌停情绪或中国 A 股市场简报时使用。
---

# A-Share Market Review Skill

Use this skill to produce a professional Chinese review of the China A-share market at midday or after the close.

## Workflow

1. Identify the report session from the user request:
   - Use `midday` for 午间收盘、午评、上午盘复盘.
   - Use `close` for 下午收盘、全天复盘、收盘点评.
   - If unspecified, infer from current China market time when possible; otherwise ask for the session or default to `close`.

2. Run the bundled market data script:

   ```bash
   node "$SKILL_DIR/scripts/a_share_review.js" --session close
   ```

   On Windows CMD, use:

   ```cmd
   node "%SKILL_DIR%\scripts\a_share_review.js" --session close
   ```

   Replace `close` with `midday` for 午间复盘.

3. Parse the JSON output:
   - Use `market_indices` for 上证指数、深证成指、创业板指、科创 50、沪深 300.
   - Use `strong_sectors` for领涨行业/题材.
   - Use `weak_sectors` for领跌行业/题材.
   - Use `market_breadth` for涨跌家数、涨停/跌停、市场情绪.
   - Treat `change_pct` as percentage change and `close` as the latest index point or sector value.

4. Add context when available:
   - Prefer available web/search tools for fresh A-share news, 政策、成交额、北向/主力资金、汇率、商品、港股或海外市场影响.
   - If search is unavailable, infer cautiously from 指数分化、板块强弱、涨跌停情绪 and the script output.
   - Do not invent specific policy, rumor, or news catalysts that were not observed.

5. Write the final answer in Chinese with a concise professional analyst tone.

## Midday Report Template

```markdown
📌 **大A午间收盘复盘 | [当前日期]**
---

📊 **指数表现**
* **上证指数**：`点位`（`涨跌幅%`）
* **深证成指**：`点位`（`涨跌幅%`）
* **创业板指**：`点位`（`涨跌幅%`）
* **科创 50**：`点位`（`涨跌幅%`）

[一句话总结上午盘主线：指数强弱、量能、题材活跃度、风险偏好。]

🔥 **上午强势方向**
1. **[板块/题材]**（`代码`）涨跌幅：`涨幅%`
   — [解释领涨逻辑，区分政策、产业、业绩、资金或事件驱动。]
2. **[板块/题材]**（`代码`）涨跌幅：`涨幅%`
   — [解释持续性与午后观察点。]

🧊 **上午弱势方向**
1. **[板块/题材]**（`代码`）涨跌幅：`跌幅%`
   — [说明回落原因或风险偏好变化。]
2. **[板块/题材]**（`代码`）涨跌幅：`跌幅%`
   — [说明是否为跷跷板、补跌或资金撤离。]

🌡️ **市场情绪**
* 涨跌家数：`上涨家数` / `下跌家数`
* 涨停/跌停：`涨停家数` / `跌停家数`
* 情绪判断：[强/中性/弱，以及原因。]

🎯 **午后观察**
[给出 2-3 个观察点，例如指数能否放量、主线是否扩散、弱势板块是否止跌。]

---
*⚠️ 免责声明：以上内容仅为市场复盘与信息整理，不构成投资建议。*
```

## Close Report Template

```markdown
📌 **大A收盘复盘 | [当前日期]**
---

📊 **全天指数表现**
* **上证指数**：`点位`（`涨跌幅%`）
* **深证成指**：`点位`（`涨跌幅%`）
* **创业板指**：`点位`（`涨跌幅%`）
* **沪深 300**：`点位`（`涨跌幅%`）

[一句话总结全天市场：指数结构、成交热度、赚钱效应与风格偏好。]

🔥 **领涨主线**
1. **[板块/题材]**（`代码`）涨跌幅：`涨幅%`
   — [解释资金选择该方向的核心逻辑。]
2. **[板块/题材]**（`代码`）涨跌幅：`涨幅%`
   — [评估持续性和扩散情况。]
3. **[板块/题材]**（`代码`）涨跌幅：`涨幅%`
   — [补充相关催化或交易特征。]

🔴 **领跌方向**
1. **[板块/题材]**（`代码`）涨跌幅：`跌幅%`
   — [解释拖累因素或资金流出信号。]
2. **[板块/题材]**（`代码`）涨跌幅：`跌幅%`
   — [说明风险是否局部扩散。]

🌡️ **情绪与资金面**
* 涨跌家数：`上涨家数` / `下跌家数`
* 涨停/跌停：`涨停家数` / `跌停家数`
* 情绪判断：[强/中性/弱，以及与指数表现是否背离。]

🧭 **明日策略观察**
[给出方向性观察，不给个股买卖指令：主线延续、轮动切换、风险点、指数关键位置。]

---
*⚠️ 免责声明：以上内容仅为市场复盘与信息整理，不构成投资建议。*
```

## Output Rules

- Keep the report compact unless the user asks for a deep version.
- Distinguish clearly between `midday` and `close`; do not mix 午后展望 with 明日策略 unless the session matches.
- Label uncertain inferences as “可能”“倾向于”“需观察”.
- Do not present fallback or mock data as real-time market data.
- Do not provide personalized buy/sell instructions or individual stock recommendations.
