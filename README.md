# 📊 Short-Term Trading Signal Bot

完全跑在 **GitHub Actions** 上 —— 免费、无需服务器、电脑不用开机。
专为**日内交易 ~ 波段交易**（持仓周期：日内 ~ 1周）设计，每天在 6 个**黄金时段**自动推送 **Telegram 信号**，结合**短线优化的技术指标 + 实时新闻 + Google Gemini AI** 综合分析，给出 **1-10 分**买卖评分。

**市场：** NASDAQ / NYSE
**K线数据：** Yahoo Finance via yfinance（1h × 60天 + 日线 × 3月，约 15 min 延迟）
**基本面/事件：** Finnhub 免费层（📅 财报日历 · 🏛 分析师评级 · 🧑‍💼 Insider Trading · 📰 个股新闻）
**宏观新闻：** Tavily API（FED / CPI / 关税）
**AI：** Google Gemini 3 Flash Preview（首选）+ 4 层 cascade 自动 fallback
**语言：** Python 3.11

---

## 🧠 信号是怎么来的

每只股票分析流程：

```
1h K线 (60天) yfinance      ─┐
日线 (3月)    yfinance      ─┤
                              ├── 短线技术指标 ── 买/卖 各 0-10 分
📅 财报日历     Finnhub      ─┤
🏛 分析师评级   Finnhub      ─┤
🧑‍💼 Insider 交易 Finnhub      ─┤
📰 个股新闻     Finnhub      ─┤
🌐 宏观新闻     Tavily       ─┴── Gemini AI ── 综合评分 1-10 + 执行建议
```

### 📅 财报日历 —— 短线最重要的防风险机制

短线交易的头号杀手是**财报隔夜跳空**：你以为持仓 3 天，结果第 2 天财报后跳空 -15%。
本 bot 自动检测未来 14 天财报：

| 距离财报 | 标记 | bot 行为 |
|---------|------|---------|
| ≤3 天 | 🚨🚨 | Gemini 强制建议"日内"或"观望"，不持仓过夜 |
| ≤7 天 | ⚠️ | 卡片显眼警告 + 汇总置顶 |
| ≤14 天 | 📅 | 简短提示 |
| >14 天 | 不显示 | 无影响 |

### 📐 1-10 评分对应建议

| 分数 | 建议 | 含义 |
|------|------|------|
| **10** | 🚀🚀 强烈买入 | 极强买入信号（多重技术确认 + 强催化剂） |
| **8-9** | 🚀🚀 强烈买入 | 多指标一致看涨，新闻面正向 |
| **6-7** | 🟢 买入 | 趋势向好，可考虑入场 |
| **5** | 🟡 观望 | 信号矛盾或方向不明，等待更清晰信号 |
| **3-4** | 🔴 卖出 | 技术转弱或催化剂转负，建议减仓 |
| **1-2** | ❌❌ 强烈卖出 | 多指标看跌或重大利空，立即离场 |

### 🎯 短线指标组合（每个都为日内/波段优化）

| # | 指标 | 设置 | 作用 |
|---|------|------|------|
| 1 | **RSI(7)** | 短周期 7（标准 14 太慢） | 短线超买超卖 |
| 2 | **MACD(5/13/5)** | Linda Raschke 日内经典 | 短期动能转折 |
| 3 | **EMA 9/21** | 短期均线交叉 | 短线趋势方向 |
| 4 | **VWAP（当日）** | 仅用当日 bar 计算 | 日内多空分界 |
| 5 | **Bollinger Bands(20)** | %B + 收窄 + 突破 | 波动率 / 突破信号 |
| 6 | **Stochastic(9,3)** | 比标准 14,3 更快 | 短期反转拐点 |
| 7 | **Volume Surge** | ≥1.8x 20-bar 均量 | 资金确认 |
| 8 | **ATR(14)** | 日线 ATR | 止损距离参考 |
| 9 | **5-bar 动能** | 近 5 根 1h 涨跌幅 | 短线方向强度 |
| 10 | **Gap** | 日线跳空 ≥1.5% | 盘前催化 |
| 11 | **近 10 日支撑/压力** | 日线高低点 | 入场/止损位 |

> 💡 **删除了哪些**：MA50/MA200、OBV、RSI 日线背离 —— 这些是长线/趋势确认指标，对日内—周交易意义不大。

### 📋 报告会告诉你

每只股票都会输出：

- 🎯 **入场区间**（不是单一价格，而是合理建仓范围）
- 📍 **双目标价**（短期 1-3 天 + 1 周）
- 🛑 **ATR 止损价**（基于实际波动率）
- ⏱ **建议持仓周期**（日内 / 2-3 天 / 3-5 天 / 1 周）
- 💪 **信心度**（指标与新闻的一致性）
- 📰 **新闻影响摘要** + 🔮 **未来 1 周潜在催化剂**
- 💡 **具体执行建议**（什么价位买/卖、何时止损）

---

## ⏰ 触发时段（每日 6 次黄金窗口）

| # | 时间 (ET) | 时段 | 为什么是关键时刻 |
|---|----------|------|-----------------|
| 1 | **08:30** | 盘前 | CPI/PPI/Jobs/GDP 等经济数据高峰发布时段 |
| 2 | **09:45** | 开盘 15 分钟后 | 跳过开盘剧烈震荡，初步方向确认 |
| 3 | **10:30** | 开盘 1 小时后 | 首小时反转窗口，机构建仓关键点 |
| 4 | **14:00** | 午后 | FOMC 利率声明固定时段 |
| 5 | **15:30** | Power Hour | 最后 30 分钟，决定是否过夜 |
| 6 | **16:15** | 收盘后 15 分钟 | 财报集中发布时段 |

### ⚠️ 关于时区的重要说明

工作流 cron 使用 **UTC** 时间，按 **EDT（夏令时，UTC-4）** 校准。

- ✅ **3 月 ~ 11 月（EDT）**：上面的 ET 时间**准确**
- ⚠️ **11 月 ~ 3 月（EST，UTC-5）**：所有触发会**晚 1 小时**（例如 08:30 ET 变 09:30 ET 触发）

**处理方式（任选一种）：**
1. 接受冬季晚 1 小时（多数短线交易者按 ET 思考，习惯就好）
2. 每年 3 月 / 11 月手动调整 `.github/workflows/stock-alert.yml` 里的 cron（所有时数 ±1）
3. 切换到 `cron-utils` + 自建调度（复杂度高，不推荐）

> 📅 **2026 年 EDT/EST 切换日**：3 月 8 日（开始 EDT）、11 月 1 日（开始 EST）

---

## 🚀 部署指南

### Step 1 — 准备 Telegram Bot

1. Telegram 搜索 **@BotFather** → 发送 `/newbot` → 复制 **Bot Token**
2. 给新 bot 发任意消息以激活会话
3. 浏览器打开 `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. 在响应里找到 `"chat":{"id": 123456789}` —— 这个数字就是 **Chat ID**

### Step 2 — 准备 API Keys

| 服务 | 用途 | 获取方式 |
|------|------|---------|
| **Telegram** | 接收推送 | @BotFather |
| **Google Gemini** | AI 综合分析 | https://aistudio.google.com/apikey（免费配额充足） |
| **Finnhub** | 财报/分析师/Insider/个股新闻 | https://finnhub.io/register（**60 次/分钟免费**，注册即用） |
| **Tavily** | 宏观/政策新闻 | https://tavily.com（每月 1000 次免费，只用于宏观） |

> 💡 **Gemini 多 key 轮换**：建议申请 2-3 个 Gemini key 用逗号分隔，自动规避配额限制

### Step 3 — Fork / Clone 仓库

```
stock-signal-bot/
├── .github/workflows/stock-alert.yml    # 调度器
├── src/analyzer.py                       # 核心分析逻辑
├── requirements.txt                      # Python 依赖
└── README.md
```

### Step 4 — 配置 GitHub Secrets

仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | 必填 | 内容 |
|-------------|------|------|
| `TELEGRAM_TOKEN` | ✅ | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | ✅ | Telegram Chat ID |
| `GEMINI_API_KEYS` | ✅ | 一个或多个 Gemini key，逗号分隔 |
| `FINNHUB_API_KEY` | ✅ | Finnhub API Key（财报/分析师/Insider 必需） |
| `TAVILY_API_KEY` | 可选 | Tavily API Key（仅宏观新闻，不填则跳过宏观） |
| `STOCK_LIST` | 可选 | 自选股，逗号分隔（如 `MU,SNDK,NVDA,AMD`），不设则用默认 |

可选 Repository Variables（**Settings → Variables**）：
- `GEMINI_MODEL` — 默认 `gemini-2.5-flash`
- `GEMINI_MODEL_FALLBACK` — 默认 `gemini-2.0-flash`

### Step 5 — 启用并测试

1. 仓库 → **Actions** 标签 → 启用 workflows
2. 选择 **短线交易信号 Short-Term Signal Bot** → **Run workflow** 手动触发一次
3. 1-2 分钟内应该收到 Telegram 推送
4. 没收到 → 看 **Actions** run 的日志排查

---

## 📱 报告示例

```
📊 短线交易信号报告
🌅 盘前 ｜ 📅 2026-05-14 08:30 ET
1h技术指标 + 实时新闻 + Gemini AI 综合评分 (1-10)

━━━━━━━━━━━━━━━━━━━━━━
NVDA NVIDIA ｜ $895.40 📈 +2.34%

🚀🚀 强烈买入  🟩🟩🟩🟩🟩🟩🟩🟩🟩⬜  9/10
   AI 推理需求超预期 + 突破 BB 上轨，放量确认

⏱ 持仓 2-3天 ｜ 🟡 风险 中 ｜ 💪 信心 高

🎯 入场区间 $890.00 ~ $898.00
📍 目标1 $920 ｜ 目标2 $950
🛑 止损 $872

⚠️ 财报 2026-05-22 amc（7 天后）— 注意跳空风险
🏛 分析师 买 31 · 持 3 · 卖 0  (2026-05)
🧑‍💼 高管净买入 +125,000 股（30天，看涨）✅

📊 技术面  买 8/10 ｜ 卖 1/10
   RSI(7) 64 · MACD +0.420 · BB%B 0.92
   VWAP $887 · Vol 2.8x · 动能 +3.45%
   支撑 $860 · 压力 $902 · ATR $14.50
   ⚡ BB 上轨突破 · 放量 2.8x↑ · MACD 金叉

📰 新闻：CSP 厂商 Q3 GPU 订单创纪录
🔮 催化剂：5/22 财报，可能上修指引
💡 执行建议：$890-898 分批买入，3 天目标 $920，跌破 $872 止损
🤖 gemini-2.5-flash

━━━━━━━━━━━━━━━━━━━━━━
📋 汇总
🚀🚀 强烈买入 2 ｜ 🟢 买入 1 ｜ 🟡 观望 1 ｜ 🔴 卖出 0 ｜ ❌❌ 强烈卖出 0
⭐ 重点关注：NVDA(9), AMD(7), MU(7)

⚠️ AI 辅助生成，仅供短线交易参考，不构成投资建议。请严格执行止损。
```

---

## ❓ FAQ

**Q：为什么用 1h K 线而不是日线？**
A：短线交易需要更快的信号。日线对持仓周期 1-7 天的交易者太慢，关键的盘中突破/反转在日线上看不出来。1h K 线在 60 天数据下提供约 400 根 bar，对短线指标足够。

**Q：价格不是实时的吗？**
A：Yahoo Finance 免费数据约 15 分钟延迟。对于"日内 ~ 1 周"持仓的策略完全够用 —— 我们追的是趋势和突破，不是 tick 级别的快讯。

**Q：能加多少只股票？**
A：建议 ≤15 只。每只约 8-10 秒（数据 + 新闻 + AI），超过 15 只可能撞 GitHub Actions 的 15 分钟 timeout。也要注意 Tavily/Gemini 的免费额度。每只股票推送**独立 Telegram 消息**（不再拼成一长条），所以加多少都不会被截断。

**Q：免费 API 额度够用吗？**
A：本 bot 内置 **5 层 Gemini 模型 cascade**（全部为当前活跃的免费层模型，已剔除 deprecated 的 2.0 系列），遇 503/429 自动按顺序降级：

| 顺序 | 模型 | 状态 | 角色 |
|------|------|------|------|
| 1 | `gemini-3-flash-preview` | Preview | ⭐ **首选**（质量最高） |
| 2 | `gemini-3.1-flash-lite` | Stable | Gemini 3 家族稳定兜底 |
| 3 | `gemini-2.5-flash` | Stable | 成熟推理，JSON 输出稳定 |
| 4 | `gemini-2.5-flash-lite` | Stable | 免费配额最慷慨 |
| 5 | `gemini-3.1-flash-lite-preview` | Preview | Preview 期配额限制更宽松 |

单 key 跑 15 只股票 × 6 次/天 = 90 次/天，**单个 3-flash-preview 就够用**。建议申请 2-3 个 key 用逗号填 `GEMINI_API_KEYS`，bot 会自动轮换。

> 💡 想动态调整不必改代码：在 GitHub 仓库 **Settings → Variables** 设置 `GEMINI_MODEL` / `GEMINI_MODEL_FALLBACK` 即可覆盖默认值。

- **Tavily 免费版**：每月 1000 次 → 15 只 × 2 次/触发 × 6 次/天 × 22 工作日 ≈ 3960 次，**不够，建议升级或减少股票数到 ≤4 只**

**Q：AI 挂了会怎样？**
A：Bot 有**三级保护**：
1. **503 / UNAVAILABLE / INTERNAL（服务端故障）**：自动指数退避重试（3s → 6s → 12s）
2. **429 / RESOURCE_EXHAUSTED（配额耗尽）**：立即切下一个 model 或 key
3. **全部失败**：fallback 到纯技术评分推导，基于 ATR 自动计算入场/止损/目标位，绝不发空报告

**Q：能自动下单吗？**
A：不能。本 bot 只读市场数据 + 发 Telegram。**不连接任何券商**。

**Q：怎么关闭？**
A：Actions 标签 → 短线交易信号 → **Disable workflow**

**Q：怎么改触发时间？**
A：编辑 `.github/workflows/stock-alert.yml`，注意 cron 是 **UTC** 时间。EDT 时段 UTC = ET + 4，EST 时段 UTC = ET + 5。

---

## ⚠️ 免责声明

本工具仅供**信息和教育用途**。所有信号基于历史数据的技术指标与 AI 推断生成 —— **历史规律不保证未来表现**。投资有风险，入市需谨慎，所有交易决策请自行判断并咨询持牌财务顾问。**严格执行止损是短线交易的生命线**。
