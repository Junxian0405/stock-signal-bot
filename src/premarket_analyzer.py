"""
专业盘前分析系统 — Pre-Market Analyzer (精简版)
功能：
  - 13项技术指标分析
  - Tavily 抓取近3天新闻 + 美国宏观政策新闻
  - Gemini AI 综合分析（精简版，每股 ≤200字）
  - 只在盘前 04:00 / 07:00 / 09:00 ET 触发
"""

import os
import re
import json
import time
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
import pytz
from google import genai
from google.genai import types

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY   = os.environ["GEMINI_API_KEY"]
TAVILY_API_KEY   = os.environ["TAVILY_API_KEY"]

# 从环境变量读取自选股列表 (例如: "MU,SNDK,AAPL,TSLA")
# 若未设置则使用默认股票池
DEFAULT_STOCKS = "AAPL,MSFT,NVDA,TSLA,AMZN,GOOGL,META,AMD,INTC,SPY"
STOCK_LIST_RAW = os.environ.get("STOCK_LIST", DEFAULT_STOCKS)
WATCHLIST = [s.strip().upper() for s in STOCK_LIST_RAW.split(",") if s.strip()]

# 公司中文名映射（找不到则使用 ticker 本身）
COMPANY_NAMES = {
    "AAPL":  "Apple",      "MSFT": "Microsoft",   "NVDA": "NVIDIA",
    "TSLA":  "Tesla",      "AMZN": "Amazon",      "GOOGL": "Alphabet",
    "META":  "Meta",       "AMD":  "AMD",         "INTC": "Intel",
    "SPY":   "S&P 500 ETF","MU":   "Micron",      "SNDK": "SanDisk",
    "QQQ":   "纳指 ETF",   "ARM":  "Arm Holdings","PLTR": "Palantir",
    "SOFI":  "SoFi",       "SMCI": "Super Micro", "AVGO": "Broadcom",
    "ASML":  "ASML",       "TSM":  "台积电",      "BABA": "阿里巴巴",
    "NFLX":  "Netflix",    "DIS":  "Disney",      "BA":   "波音",
    "JPM":   "摩根大通",   "GS":   "高盛",        "C":    "花旗",
    "COIN":  "Coinbase",   "MSTR": "MicroStrategy","RBLX": "Roblox",
    "UBER":  "Uber",       "LYFT": "Lyft",        "PYPL": "PayPal",
    "SHOP":  "Shopify",    "SQ":   "Block",       "CRM":  "Salesforce",
    "ORCL":  "甲骨文",     "ADBE": "Adobe",       "NOW":  "ServiceNow",
}

ET              = pytz.timezone("America/New_York")
PREMARKET_HOURS = {4, 7, 9}

genai_client = genai.Client(api_key=GEMINI_API_KEY)

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    """自动分段发送，避免 Telegram 4096 字符上限"""
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 3800
    chunks  = [message[i:i + max_len] for i in range(0, len(message), max_len)]
    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        time.sleep(0.5)

# ─── NEWS (TAVILY) ────────────────────────────────────────────────────────────

def fetch_news(ticker: str, company: str) -> list[dict]:
    """抓取近3天股票相关新闻（精简版：1次调用）"""
    try:
        url     = "https://api.tavily.com/search"
        payload = {
            "api_key":      TAVILY_API_KEY,
            "query":        f"{ticker} {company} stock news earnings",
            "search_depth": "basic",
            "max_results":  5,
            "days":         3,
            "include_domains": [
                "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com",
                "marketwatch.com", "seekingalpha.com", "finance.yahoo.com",
            ],
        }
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {
                "title":   item.get("title", ""),
                "content": item.get("content", "")[:300],
                "date":    item.get("published_date", "")[:10],
            }
            for item in data.get("results", [])
        ]
    except Exception as e:
        print(f"[NEWS ERROR] {ticker}: {e}")
        return []

def fetch_macro_news() -> list[dict]:
    """抓取美国宏观/政策新闻（共用，1次调用）"""
    try:
        url     = "https://api.tavily.com/search"
        payload = {
            "api_key":      TAVILY_API_KEY,
            "query":        "US Federal Reserve interest rate policy stock market tariff",
            "search_depth": "basic",
            "max_results":  4,
            "days":         3,
        }
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {"title": item.get("title", ""), "content": item.get("content", "")[:250]}
            for item in data.get("results", [])
        ]
    except Exception as e:
        print(f"[MACRO NEWS ERROR]: {e}")
        return []

# ─── TECHNICAL INDICATORS ─────────────────────────────────────────────────────

def compute_rsi(close, period=14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 2)

def compute_rsi_series(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

def compute_macd(close):
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return (
        round(float(macd.iloc[-1]), 4),
        round(float(signal.iloc[-1]), 4),
        round(float((macd - signal).iloc[-1]), 4),
    )

def compute_ema(close, period) -> float:
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def compute_ma(close, period) -> float:
    return round(float(close.rolling(period).mean().iloc[-1]), 4)

def compute_bollinger(close, period=20, std_dev=2.0) -> dict:
    sma       = close.rolling(period).mean()
    std       = close.rolling(period).std()
    upper     = sma + std_dev * std
    lower     = sma - std_dev * std
    price     = float(close.iloc[-1])
    cur_upper = float(upper.iloc[-1])
    cur_lower = float(lower.iloc[-1])
    cur_mid   = float(sma.iloc[-1])
    bandwidth = (cur_upper - cur_lower) / cur_mid if cur_mid != 0 else 0
    pct_b     = (price - cur_lower) / (cur_upper - cur_lower) if (cur_upper - cur_lower) != 0 else 0.5
    bw_s      = ((upper - lower) / sma).dropna()
    recent    = bw_s.iloc[-50:] if len(bw_s) >= 50 else bw_s
    squeeze   = bandwidth <= float(recent.quantile(0.20))
    breakout  = "up" if price > cur_upper else ("down" if price < cur_lower else "inside")
    return {
        "upper": round(cur_upper, 2), "middle": round(cur_mid, 2),
        "lower": round(cur_lower, 2), "pct_b": round(pct_b, 3),
        "squeeze": squeeze, "breakout": breakout,
    }

def compute_obv(close, volume) -> dict:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv       = (direction * volume).cumsum()
    slope     = float(obv.iloc[-1]) - float(obv.iloc[-6]) if len(obv) >= 6 else 0
    p_now     = float(close.iloc[-1])
    p_prev    = float(close.iloc[-6]) if len(close) >= 6 else p_now
    return {
        "obv_trend":    "up" if slope > 0 else "down",
        "bull_diverge": (p_now < p_prev) and (slope > 0),
        "bear_diverge": (p_now > p_prev) and (slope < 0),
    }

def compute_volume_surge(volume) -> dict:
    avg   = float(volume.rolling(20).mean().iloc[-1])
    cur   = float(volume.iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {"ratio": round(ratio, 2), "surge": ratio >= 2.0}

def compute_atr(high, low, close, period=14) -> dict:
    prev  = close.shift(1)
    tr    = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr   = float(tr.rolling(period).mean().iloc[-1])
    atr_p = float(tr.rolling(period).mean().iloc[-5]) if len(tr) >= 5 else atr
    return {
        "atr":       round(atr, 4),
        "atr_pct":   round((atr / float(close.iloc[-1])) * 100, 2),
        "expanding": atr > atr_p,
    }

def compute_stochastic(high, low, close, k_period=14, d_period=3) -> dict:
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    k  = 100 * (close - ll) / (hh - ll + 1e-9)
    d  = k.rolling(d_period).mean()
    kv = round(float(k.iloc[-1]), 2)
    dv = round(float(d.iloc[-1]), 2)
    kp = float(k.iloc[-2]) if len(k) >= 2 else kv
    dp = float(d.iloc[-2]) if len(d) >= 2 else dv
    return {
        "k": kv, "d": dv,
        "cross_up":   (kp < dp) and (kv > dv) and kv < 30,
        "cross_down": (kp > dp) and (kv < dv) and kv > 70,
    }

def compute_vwap(df) -> float:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap    = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return round(float(vwap.iloc[-1]), 2)

def compute_gap(df) -> dict:
    if len(df) < 2:
        return {"gap_pct": 0.0, "gap_up": False, "gap_down": False}
    prev  = float(df["Close"].iloc[-2])
    open_ = float(df["Open"].iloc[-1])
    pct   = ((open_ - prev) / prev) * 100
    return {"gap_pct": round(pct, 2), "gap_up": pct >= 2.0, "gap_down": pct <= -2.0}

def compute_rsi_divergence(close) -> dict:
    rsi = compute_rsi_series(close)
    if len(close) < 10:
        return {"bull": False, "bear": False}
    pn, pp = float(close.iloc[-1]), float(close.iloc[-10])
    rn, rp = float(rsi.iloc[-1]),   float(rsi.iloc[-10])
    return {"bull": (pn < pp) and (rn > rp), "bear": (pn > pp) and (rn < rp)}

def compute_support_resistance(df) -> dict:
    r10     = df.tail(10)
    resist  = round(float(r10["High"].max()), 2)
    support = round(float(r10["Low"].min()), 2)
    return {"resistance": resist, "support": support}

# ─── SIGNAL ENGINE ────────────────────────────────────────────────────────────

def get_signal(price, rsi, macd, macd_sig, ema9, ema21, ma50, ma200,
               boll, obv, vol, atr, stoch, vwap, rsi_div):
    buy_v, sell_v = 0, 0
    alerts = []

    if rsi < 35:   buy_v  += 1
    elif rsi > 65: sell_v += 1

    if macd > macd_sig:   buy_v  += 1
    elif macd < macd_sig: sell_v += 1

    if ema9 > ema21:   buy_v  += 1
    elif ema9 < ema21: sell_v += 1

    if price > ma50 and ma50 > ma200: buy_v  += 1
    elif price < ma50:                sell_v += 1

    if boll["squeeze"]:
        alerts.append("BB Squeeze")
    elif boll["breakout"] == "up":
        buy_v += 1; alerts.append("BB Breakout UP")
    elif boll["breakout"] == "down":
        sell_v += 1; alerts.append("BB Breakout DOWN")

    if boll["pct_b"] < 0.05:   buy_v  += 1
    elif boll["pct_b"] > 0.95: sell_v += 1

    if obv["obv_trend"] == "up":   buy_v  += 1
    elif obv["obv_trend"] == "down": sell_v += 1

    if obv["bull_diverge"]:
        buy_v += 1; alerts.append("OBV Bull Div")
    if obv["bear_diverge"]:
        sell_v += 1; alerts.append("OBV Bear Div")

    if vol["surge"]:
        if price >= ma50:
            buy_v += 1; alerts.append(f"Vol Surge {vol['ratio']}x")
        else:
            sell_v += 1; alerts.append(f"Vol Surge {vol['ratio']}x↓")

    if stoch["cross_up"]:
        buy_v += 1; alerts.append("Stoch Cross UP")
    elif stoch["cross_down"]:
        sell_v += 1; alerts.append("Stoch Cross DOWN")
    elif stoch["k"] < 20:   buy_v  += 1
    elif stoch["k"] > 80:   sell_v += 1

    if price > vwap:   buy_v  += 1
    elif price < vwap: sell_v += 1

    if rsi_div["bull"]:
        buy_v += 1; alerts.append("RSI Bull Div")
    if rsi_div["bear"]:
        sell_v += 1; alerts.append("RSI Bear Div")

    if atr["expanding"] and not boll["squeeze"]:
        if buy_v > sell_v:
            buy_v += 1; alerts.append("ATR Expanding↑")
        else:
            sell_v += 1; alerts.append("ATR Expanding↓")

    if buy_v >= 7:    return "BUY STRONG", buy_v, sell_v, alerts
    elif buy_v >= 5:  return "BUY",         buy_v, sell_v, alerts
    elif sell_v >= 7: return "SELL STRONG", buy_v, sell_v, alerts
    elif sell_v >= 5: return "SELL",        buy_v, sell_v, alerts
    else:             return "HOLD",        buy_v, sell_v, alerts

# ─── MARKET DATA ──────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, retries: int = 3) -> Optional[pd.DataFrame]:
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period="6mo", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 30:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            if attempt < retries - 1:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                print(f"[RETRY] {ticker} attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[ERROR] {ticker}: {e}")
                return None

# ─── FULL STOCK ANALYSIS ──────────────────────────────────────────────────────

def analyze(ticker: str) -> Optional[dict]:
    try:
        df = fetch_ohlcv(ticker)
        if df is None or len(df) < 30:
            return None

        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()
        price  = round(float(close.iloc[-1]), 2)

        prev1 = float(close.iloc[-2]) if len(close) >= 2 else price
        prev5 = float(close.iloc[-6]) if len(close) >= 6 else price
        chg1  = round(((price - prev1) / prev1) * 100, 2)
        chg5  = round(((price - prev5) / prev5) * 100, 2)

        rsi                   = compute_rsi(close)
        macd_v, sig_v, hist_v = compute_macd(close)
        ema9                  = compute_ema(close, 9)
        ema21                 = compute_ema(close, 21)
        ma50                  = compute_ma(close, 50)
        ma200                 = compute_ma(close, 200)
        boll                  = compute_bollinger(close)
        obv_d                 = compute_obv(close, volume)
        vol_d                 = compute_volume_surge(volume)
        atr_d                 = compute_atr(high, low, close)
        stoch                 = compute_stochastic(high, low, close)
        vwap                  = compute_vwap(df)
        rsi_div               = compute_rsi_divergence(close)
        gap                   = compute_gap(df)
        sr                    = compute_support_resistance(df)

        signal, buy_v, sell_v, alerts = get_signal(
            price, rsi, macd_v, sig_v, ema9, ema21,
            ma50, ma200, boll, obv_d, vol_d, atr_d,
            stoch, vwap, rsi_div,
        )

        w52_high = round(float(high.tail(252).max()), 2)
        w52_low  = round(float(low.tail(252).min()), 2)

        return {
            "ticker":    ticker,
            "company":   COMPANY_NAMES.get(ticker, ticker),
            "price":     price,
            "chg1":      chg1, "chg5": chg5,
            "signal":    signal, "buy_v": buy_v, "sell_v": sell_v,
            "alerts":    alerts,
            "rsi":       rsi,
            "macd":      macd_v, "macd_sig": sig_v, "macd_hist": hist_v,
            "ema9":      ema9, "ema21": ema21,
            "ma50":      ma50, "ma200":  ma200,
            "boll":      boll, "obv":   obv_d, "vol": vol_d,
            "atr":       atr_d, "stoch": stoch, "vwap": vwap,
            "gap":       gap, "sr":     sr,
            "w52_high":  w52_high, "w52_low": w52_low,
        }
    except Exception as e:
        print(f"[ANALYZE ERROR] {ticker}: {e}")
        return None

# ─── GEMINI AI ANALYSIS (精简版) ──────────────────────────────────────────────

def gemini_analyze(tech: dict, news: list[dict], macro_news: list[dict]) -> dict:
    """精简版 Gemini 分析，控制 token 用量"""
    try:
        news_text = "\n".join([
            f"- [{n.get('date', '')}] {n['title'][:80]}: {n['content'][:120]}"
            for n in news[:5]
        ]) or "无相关新闻"

        macro_text = "\n".join([
            f"- {n['title'][:80]}"
            for n in macro_news[:4]
        ]) or "无宏观新闻"

        prompt = f"""你是华尔街资深分析师。基于以下数据，用简体中文做精简盘前分析。

【{tech['ticker']} ({tech['company']})】
昨收 ${tech['price']} | 昨涨跌 {tech['chg1']:+.2f}% | 5日 {tech['chg5']:+.2f}%
52周高低: ${tech['w52_high']} / ${tech['w52_low']}
支撑/压力: ${tech['sr']['support']} / ${tech['sr']['resistance']}

技术: RSI {tech['rsi']} | MACD {tech['macd']}/{tech['macd_sig']} | BB%B {tech['boll']['pct_b']} | Stoch {tech['stoch']['k']} | Vol {tech['vol']['ratio']}x
EMA9/21: {tech['ema9']}/{tech['ema21']} | MA50/200: {tech['ma50']}/{tech['ma200']} | VWAP {tech['vwap']}
信号: {tech['signal']} ({tech['buy_v']}买/{tech['sell_v']}卖) | 警报: {','.join(tech['alerts']) or '无'}

近3天新闻:
{news_text}

宏观/政策:
{macro_text}

严格返回JSON（无markdown），所有字段简洁不超过指定字数：
{{
  "open_low": 数字,
  "open_high": 数字,
  "action": "立即买入/考虑买入/观望/考虑卖出/立即卖出",
  "reason": "30字内核心理由",
  "target_1w": 数字,
  "stop_loss": 数字,
  "news_sentiment": "强烈看涨/看涨/中性/看跌/强烈看跌",
  "news_impact": "40字内新闻影响摘要",
  "catalyst": "30字内未来催化剂",
  "risk_level": "低/中/高",
  "rating": "强烈买入/买入/持有/卖出/强烈卖出",
  "summary": "60字内综合点评"
}}"""

        response = genai_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)

    except Exception as e:
        print(f"[GEMINI ERROR] {tech['ticker']}: {e}")
        return {
            "open_low":       tech["price"] * 0.99,
            "open_high":      tech["price"] * 1.01,
            "action":         "观望",
            "reason":         "AI分析暂不可用",
            "target_1w":      tech["price"],
            "stop_loss":      round(tech["price"] * 0.95, 2),
            "news_sentiment": "中性",
            "news_impact":    "无法获取",
            "catalyst":       "无法预测",
            "risk_level":     "中",
            "rating":         "持有",
            "summary":        "AI暂不可用，请参考技术指标。",
        }

# ─── MESSAGE BUILDER (精简版) ────────────────────────────────────────────────

SIGNAL_ZH = {
    "BUY STRONG":  "✅✅ 强烈看涨",
    "BUY":         "✅ 看涨",
    "SELL STRONG": "❌❌ 强烈看跌",
    "SELL":        "❌ 看跌",
    "HOLD":        "⏸ 中性",
}

ACTION_EMOJI = {
    "立即买入": "🚀", "考虑买入": "✅", "观望": "⏸",
    "考虑卖出": "⚠️", "立即卖出": "❌",
}

RATING_EMOJI = {
    "强烈买入": "🟢🟢", "买入": "🟢", "持有": "🟡",
    "卖出": "🔴",     "强烈卖出": "🔴🔴",
}

SENTIMENT_EMOJI = {
    "强烈看涨": "🔥", "看涨": "📈", "中性": "😐",
    "看跌": "📉",    "强烈看跌": "💀",
}

RISK_EMOJI = {"低": "🟢", "中": "🟡", "高": "🔴"}

def confidence_bar(buy_v: int, sell_v: int, signal: str) -> str:
    total = 13
    if "BUY" in signal:
        f = min(buy_v, total)
        return "🟩" * f + "⬜" * (total - f)
    elif "SELL" in signal:
        f = min(sell_v, total)
        return "🟥" * f + "⬜" * (total - f)
    return "🟨" * 5 + "⬜" * 8

def build_stock_card(tech: dict, ai: dict) -> str:
    """精简版股票卡片，每股 ≤200字"""
    sig_label = SIGNAL_ZH.get(tech["signal"], tech["signal"])
    conf_bar  = confidence_bar(tech["buy_v"], tech["sell_v"], tech["signal"])
    act_e     = ACTION_EMOJI.get(ai["action"], "⏸")
    rat_e     = RATING_EMOJI.get(ai["rating"], "🟡")
    sen_e     = SENTIMENT_EMOJI.get(ai["news_sentiment"], "😐")
    risk_e    = RISK_EMOJI.get(ai["risk_level"], "🟡")
    chg_a     = "📈" if tech["chg1"] >= 0 else "📉"

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{tech['ticker']}</b> {tech['company']} ｜ ${tech['price']} {chg_a} {tech['chg1']:+.2f}%\n"
        f"\n"
        f"🎯 <b>开盘区间</b> ${ai['open_low']:.2f} ~ ${ai['open_high']:.2f}\n"
        f"📍 1周目标 <b>${ai['target_1w']}</b> ｜ 止损 <b>${ai['stop_loss']}</b>\n"
        f"\n"
        f"{act_e} <b>开盘建议：{ai['action']}</b>\n"
        f"   {ai['reason']}\n"
        f"\n"
        f"{rat_e} 评级：<b>{ai['rating']}</b> ｜ {sen_e} 情绪：{ai['news_sentiment']} ｜ {risk_e} 风险：{ai['risk_level']}\n"
        f"\n"
        f"📊 技术 {sig_label} {conf_bar}\n"
        f"   <i>RSI {tech['rsi']} · MACD {tech['macd']} · BB%B {tech['boll']['pct_b']} · "
        f"Vol {tech['vol']['ratio']}x · MA50 {tech['ma50']}</i>\n"
        f"   ⚡ {' · '.join(tech['alerts']) if tech['alerts'] else '无特殊警报'}\n"
        f"\n"
        f"📰 <b>新闻：</b>{ai['news_impact']}\n"
        f"🔮 <b>催化剂：</b>{ai['catalyst']}\n"
        f"💬 <b>点评：</b>{ai['summary']}"
    )

def build_premarket_report(results: list[dict], time_str: str) -> str:
    lines = [
        "<b>🌅 专业盘前分析报告</b>",
        f"📅 {time_str}（美东时间）",
        "技术指标 + Tavily新闻 + Gemini AI 综合分析",
        "",
    ]

    rating_order = {"强烈买入": 0, "买入": 1, "持有": 2, "卖出": 3, "强烈卖出": 4}
    results.sort(key=lambda x: rating_order.get(x["ai"].get("rating", "持有"), 2))

    for r in results:
        lines.append(build_stock_card(r["tech"], r["ai"]))
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    ratings    = [r["ai"].get("rating", "持有") for r in results]
    strong_buy = ratings.count("强烈买入")
    buy        = ratings.count("买入")
    hold       = ratings.count("持有")
    sell       = ratings.count("卖出") + ratings.count("强烈卖出")

    lines.append("<b>📋 开盘汇总</b>")
    lines.append(f"🟢🟢 强烈买入 {strong_buy} ｜ 🟢 买入 {buy} ｜ 🟡 持有 {hold} ｜ 🔴 卖出 {sell}")

    high_risk = [r["tech"]["ticker"] for r in results if r["ai"].get("risk_level") == "高"]
    if high_risk:
        lines.append(f"⚠️ <b>高风险股：</b>{', '.join(high_risk)}")

    lines.append("")
    lines.append("<i>⚠️ AI辅助生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。</i>")
    return "\n".join(lines)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    now_et   = datetime.now(ET)
    time_str = now_et.strftime("%Y-%m-%d %H:%M ET")

    if now_et.hour not in PREMARKET_HOURS:
        print(f"[SKIP] {time_str} 不在盘前时段。")
        return

    print(f"[START] 盘前分析 — {time_str}")
    print(f"[INFO] 自选股池 ({len(WATCHLIST)} 支): {', '.join(WATCHLIST)}")

    print("[INFO] 抓取宏观新闻...")
    macro_news = fetch_macro_news()
    print(f"       共 {len(macro_news)} 条")

    results = []
    for ticker in WATCHLIST:
        print(f"[INFO] 分析 {ticker}...")

        tech = analyze(ticker)
        if not tech:
            print(f"       [SKIP] 技术数据不足")
            continue

        company = COMPANY_NAMES.get(ticker, ticker)
        news    = fetch_news(ticker, company)
        print(f"       新闻 {len(news)} 条")

        ai = gemini_analyze(tech, news, macro_news)
        print(f"       评级: {ai.get('rating')} | 建议: {ai.get('action')}")

        results.append({"tech": tech, "ai": ai})
        time.sleep(1)

    if not results:
        send_telegram(
            f"⚠️ 盘前分析：本次周期未能获取任何数据。\n"
            f"已尝试 {len(WATCHLIST)} 支股票，全部失败。\n"
            f"时间：{time_str}"
        )
        return

    report = build_premarket_report(results, time_str)
    send_telegram(report)
    print(f"[OK] 报告已发送，共 {len(results)} 支股票。")

if __name__ == "__main__":
    main()
