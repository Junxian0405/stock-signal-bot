# 📊 Stock Signal Bot

Runs entirely on **GitHub Actions** — free, no server, no Mac needs to be on.
Sends plain-English **Buy / Sell / Hold** signals straight to your **Telegram** every hour during US market hours, plus a dedicated deep scan before the market opens every morning.

**Market:** NASDAQ / NYSE  
**Schedule:** Mon–Fri, 04:00 AM – 8:00 PM ET  
**Pre-market scans:** 04:00, 07:00, 09:00 ET (deep scan with gap alerts)  
**Data:** Yahoo Finance via yfinance (~15 min delay during live hours)  
**Language:** Python · Runs free on GitHub Actions

---

## 🧠 How Signals Work

The bot runs **13 technical indicators** on every stock in your watchlist. Each indicator casts a BUY or SELL vote. The final signal is decided by how many agree:

| Signal | What it means | Votes needed |
|---|---|---|
| ✅✅ STRONG BUY | Very high confidence — many indicators agree | 7+ say BUY |
| ✅ BUY | Looks good to enter | 5–6 say BUY |
| ⏸ HOLD | Mixed signals — no clear direction yet | Fewer than 5 either way |
| ❌ SELL | Consider exiting or avoiding | 5–6 say SELL |
| ❌❌ STRONG SELL | High confidence — get out or avoid | 7+ say SELL |

### The 13 Indicators

| # | Indicator | What it checks |
|---|---|---|
| 1 | **RSI** | Is the stock oversold (cheap) or overbought (expensive)? |
| 2 | **MACD** | Is momentum turning upward or downward? |
| 3 | **EMA 9 / 21** | Short-term trend — is the fast line above or below the slow line? |
| 4 | **MA 50 / 200** | Long-term trend — is price above or below its long-term average? |
| 5 | **Bollinger Band Breakout** | Did price break out of its normal range? |
| 6 | **Bollinger %B** | Where exactly is price sitting inside the band? |
| 7 | **OBV Trend** | Is money overall flowing into or out of this stock? |
| 8 | **OBV Divergence** | Is smart money quietly buying while price is still down (or vice versa)? |
| 9 | **Volume Surge** | Is trading volume unusually high (2× normal or more)? |
| 10 | **Stochastic** | Is short-cycle momentum at a turning point? |
| 11 | **VWAP** | Is today's price above or below today's average traded price? |
| 12 | **RSI Divergence** | Hidden reversal signal — price going one way, RSI going another |
| 13 | **ATR Expanding** | Is volatility expanding to confirm the move? |

### Special Alerts

On top of the main signal, the bot also highlights:

- 🔵 **Bollinger Squeeze** — bands are very tight, a big move is building up
- 🚀 **Gap Up** — stock opened 2%+ higher than yesterday (strong overnight interest)
- 💥 **Gap Down** — stock opened 2%+ lower than yesterday (bad news or heavy selling)
- 🔥 **Volume Surge** — trading volume is 2× or more above the 20-day average
- 🧠 **OBV / RSI Divergence** — hidden smart money signal detected

---

## 📱 What Your Telegram Message Looks Like

**Standard hourly scan:**
```
📊 Stock Signal Report
📈 Market Hours  ·  2025-05-06 11:00 ET

Here is what the market is telling us right now:

━━━━━━━━━━━━━━━━━━━━━━━
NVDA   $875.00

✅✅ STRONG BUY — Very high confidence. Many signals agree.

Confidence: 🟩🟩🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜
8/13 signals say BUY

Why the bot says this:
  💪 Healthy momentum (RSI 38) — buyers are active and in control
  📊 Short-term trend is UP — the fast line crossed above the slow line
  🏔 Long-term trend is UP — price is above the 200-day average (healthy)
  ⬆️ Price broke above the upper Bollinger Band — strong upward breakout
  🔥 Volume is 2.8× above normal — unusually heavy buying activity detected
  🧠 Smart money is quietly buying while price is still down (hidden bullish signal)
  🔄 Momentum just flipped upward from oversold zone — early buy signal confirmed
  📍 Price $875 is ABOVE today's average traded price $861 — buyers dominating today

Special alerts:
  ⚡ BB Breakout UP
  ⚡ Volume Surge 2.8x
  ⚡ RSI Bull Divergence

Numbers: RSI 38 · MACD 0.42 · BB%B 0.12 · Vol 2.8x · MA50 840 · MA200 720

━━━━━━━━━━━━━━━━━━━━━━━
Summary
  ✅ 3 stock(s) — BUY signal
  ❌ 2 stock(s) — SELL signal
  ⏸ 5 stock(s) — No clear signal, wait

⚠️ Not financial advice. Always do your own research before trading.
```

**Pre-market deep scan (04:00 / 07:00 / 09:00 ET):**
```
🌅 Pre-Market Early Warning
Before the market opens  ·  2025-05-06 07:00 ET

Here is what to watch before 9:30 AM:

━━━━━━━━━━━━━━━━━━━━━━━
TSLA   $172.50

✅ BUY — Looks good to enter a position.

Confidence: 🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜
6/13 signals say BUY

Why the bot says this:
  🚀 Opened +3.2% HIGHER than yesterday — strong overnight interest or good news
  🔥 Volume is 3.1× above normal — unusually heavy buying activity detected
  🔵 Bollinger Bands are very tight (squeeze) — a big move is building up
  💰 Overall money flow is moving INTO this stock — accumulation in progress

Special alerts:
  ⚡ GAP UP +3.20%
  ⚡ Volume Surge 3.1x
  ⚡ BB Squeeze — big move coming

Numbers: RSI 44 · MACD 0.18 · BB%B 0.51 · Vol 3.1x · MA50 168 · MA200 195

━━━━━━━━━━━━━━━━━━━━━━━
⚡ Watch closely at open: TSLA, NVDA
These have the strongest signals going into the open.
```

---

## 🚀 Setup Guide (5 Steps)

### Step 1 — Create a Telegram Bot

1. Open Telegram → search for **@BotFather**
2. Send `/newbot` → follow the prompts → copy your **Bot Token** (looks like `123456:ABCdef...`)
3. Send any message to your new bot to start the chat
4. Get your **Chat ID** — open this URL in your browser (replace `<YOUR_TOKEN>`):
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Look for `"chat":{"id": 123456789}` in the response — that number is your Chat ID

---

### Step 2 — Create a GitHub Repository

1. Go to [github.com](https://github.com) → click **New repository**
2. Name it anything you like, e.g. `stock-signal-bot`
3. Set visibility to **Private** (recommended) or Public
4. Upload all 4 files keeping this exact folder structure:

```


> ⚠️ The `.github` folder must be at the **root** of the repo. If it ends up inside another folder the workflow will not trigger.

---

### Step 3 — Add Your Telegram Secrets

In your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two secrets exactly as shown:

| Secret Name | Where to get it |
|---|---|
| `TELEGRAM_TOKEN` | From @BotFather when you created the bot |
| `TELEGRAM_CHAT_ID` | From the getUpdates URL in Step 1 |

---

### Step 4 — Enable GitHub Actions

1. Click the **Actions** tab in your repo
2. If prompted, click **"I understand my workflows, go ahead and enable them"**
3. To test right away: click **Stock Signal Bot** → **Run workflow** → **Run workflow**

You should get a Telegram message within 1–2 minutes. If nothing arrives, check **Actions** → click the run → read the logs for errors.

---

### Step 5 — Customize Your Watchlist

Open `src/analyzer.py` and find the `WATCHLIST` near the top of the file:

```python
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "GOOGL", "META", "AMD", "INTC", "SPY"
]
```

Add, remove, or replace any tickers you want to track. Use the exact ticker symbol from Yahoo Finance or NASDAQ (e.g. `"PLTR"`, `"SOFI"`, `"ARM"`, `"SMCI"`).

> 💡 Keep the list under 20 tickers to stay within GitHub Actions' 10-minute timeout per run.

---

## ⏰ Full Schedule

The bot runs automatically Mon–Fri on this schedule (all times ET):

| Time (ET) | Session | What happens |
|---|---|---|
| 04:00 AM | 🌅 Pre-market | Deep scan — overnight gaps, early volume |
| 07:00 AM | 🌅 Pre-market | Mid scan — news building, futures direction |
| 09:00 AM | 🌅 Pre-market | Final warning — 30 min before open |
| 09:30 AM | 📈 Market open | First market-hours signal |
| 10:00 – 15:00 | 📈 Market hours | Hourly signals |
| 04:00 PM | 📈 Market close | Closing signal |
| 05:00 – 08:00 PM | 🌆 After-hours | Hourly after-hours signals |

---

## ❓ FAQ

**Why is the price not exactly live?**  
Yahoo Finance free data has about a 15-minute delay during market hours. For swing trading, pre-market gap detection, and squeeze signals this is completely fine — these setups develop over hours, not seconds. For tick-by-tick day trading you would need a paid real-time data source.

**Can I track more than 10 stocks?**  
Yes — just add more tickers to `WATCHLIST`. Keep it under 20 to stay within the 10-minute GitHub Actions timeout per run.

**I did not get a message at a certain hour. Is that normal?**  
GitHub Actions cron can occasionally run a few minutes late or skip a run during peak load on their servers. This is rare and normal for the free tier.

**How do I stop the bot completely?**  
Go to your repo → **Actions** tab → click **Stock Signal Bot** → click **Disable workflow**.

**How do I change the scan times or frequency?**  
Edit `.github/workflows/stock-alert.yml` and adjust the cron lines. All times in the workflow file are in UTC, not ET.

**Can the bot place trades automatically?**  
No. This bot is read-only — it only reads market data and sends Telegram messages. It does not connect to any brokerage and cannot place orders.

---

## ⚠️ Disclaimer

This bot is for **informational and educational purposes only**. It does not constitute financial advice. Signals are generated purely from technical indicators applied to historical price data — past patterns do not guarantee future results. Always do your own research and consider consulting a licensed financial advisor before making any investment or trading decision. You trade entirely at your own risk.
