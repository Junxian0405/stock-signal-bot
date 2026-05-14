"""
Short-Term Trading Analyzer — Day / Swing Trading (持仓周期：日内 ~ 1周)

数据：1h K线 (60天) + 日线 (3月) 作为支撑/压力/缺口上下文
指标：短线优化（RSI(7) · MACD(5/13/5) · EMA9/21 · VWAP · BB(20) · Vol Surge ·
       Stoch(9,3) · ATR · Gap · 5-bar Momentum · 10-day S/R）
评分：技术买/卖 各 0-10 + Gemini AI 综合评分 1-10（结合新闻与指标）
新闻：Tavily 抓近3天股票相关 + 美国宏观/政策
"""

import os
import re
import json
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Optional
import pytz
from google import genai
from google.genai import types

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "")
FINNHUB_API_KEY  = os.environ.get("FINNHUB_API_KEY", "")

FINNHUB_BASE = "https://finnhub.io/api/v1"

_raw_keys       = os.environ.get("GEMINI_API_KEYS", "")
GEMINI_API_KEYS = [k.strip() for k in _raw_keys.split(",") if k.strip()]

GEMINI_MODEL          = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODEL_FALLBACK = os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-2.0-flash")
GEMINI_REQUEST_DELAY  = float(os.environ.get("GEMINI_REQUEST_DELAY", "2.0"))

# 模型 cascade：按配额从严到宽排序，免费层最后兜底
# (gemini-2.0-flash-lite: 30 RPM / 1500 RPD，最慷慨的免费配额)
_extra_fallbacks = ["gemini-2.0-flash-lite", "gemini-2.5-flash-lite"]
MODEL_CASCADE = []
_seen = set()
for _m in [GEMINI_MODEL, GEMINI_MODEL_FALLBACK, *_extra_fallbacks]:
    if _m and _m not in _seen:
        MODEL_CASCADE.append(_m)
        _seen.add(_m)

DEFAULT_STOCKS = "MU,SNDK"
STOCK_LIST_RAW = os.environ.get("STOCK_LIST", DEFAULT_STOCKS)
WATCHLIST      = [s.strip().upper() for s in STOCK_LIST_RAW.split(",") if s.strip()]

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

ET = pytz.timezone("America/New_York")

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    """发送单条消息。超长（>3800 字）时自动分段，但通常用于单只股票卡片，长度可控。"""
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 3800
    chunks  = [message[i:i + max_len] for i in range(0, len(message), max_len)] or [""]
    for chunk in chunks:
        if not chunk:
            continue
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")
        time.sleep(0.6)  # 避免 Telegram bot rate limit (~1 msg/sec to same chat)

# ─── FINNHUB （短线必备数据：财报/分析师/Insider/个股新闻）────────────────────

def finnhub_get(endpoint: str, params: dict = None) -> Optional[dict]:
    """Finnhub 统一请求封装。无 API key 时静默跳过。"""
    if not FINNHUB_API_KEY:
        return None
    params = dict(params or {})
    params["token"] = FINNHUB_API_KEY
    try:
        resp = requests.get(f"{FINNHUB_BASE}{endpoint}", params=params, timeout=10)
        if resp.status_code != 200:
            print(f"[FINNHUB] {endpoint} HTTP {resp.status_code}: {resp.text[:100]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[FINNHUB ERROR] {endpoint}: {e}")
        return None

def fetch_news(ticker: str, company: str = "") -> list[dict]:
    """近 3 天公司新闻（Finnhub）。比 Tavily 更精准，专门针对该 ticker。"""
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=3)
    data = finnhub_get("/company-news", {
        "symbol": ticker,
        "from":   start.isoformat(),
        "to":     today.isoformat(),
    })
    if not data:
        return []
    # 按时间排序，最新优先
    items = sorted(data, key=lambda x: x.get("datetime", 0), reverse=True)
    return [
        {
            "title":   n.get("headline", "")[:120],
            "content": n.get("summary", "")[:280],
            "date":    datetime.fromtimestamp(n.get("datetime", 0)).strftime("%Y-%m-%d")
                       if n.get("datetime") else "",
            "source":  n.get("source", ""),
        }
        for n in items[:5]
    ]

def fetch_earnings_date(ticker: str) -> Optional[dict]:
    """未来 14 天内的财报日期。对短线交易**至关重要**——
    财报前一晚跳空是日内/周交易最大杀手。"""
    from datetime import date, timedelta
    today = date.today()
    end = today + timedelta(days=14)
    data = finnhub_get("/calendar/earnings", {
        "from":   today.isoformat(),
        "to":     end.isoformat(),
        "symbol": ticker,
    })
    if not data:
        return None
    events = data.get("earningsCalendar") or []
    if not events:
        return None
    events.sort(key=lambda x: x.get("date", ""))
    e = events[0]
    try:
        e_date = datetime.strptime(e.get("date", ""), "%Y-%m-%d").date()
        days_to = (e_date - today).days
    except Exception:
        return None
    return {
        "date":    e.get("date", ""),
        "days_to": days_to,
        "hour":    e.get("hour", ""),       # bmo (盘前) / amc (盘后)
        "eps_est": e.get("epsEstimate"),
        "rev_est": e.get("revenueEstimate"),
    }

def fetch_recommendations(ticker: str) -> Optional[dict]:
    """近期分析师评级分布。"""
    data = finnhub_get("/stock/recommendation", {"symbol": ticker})
    if not data or len(data) == 0:
        return None
    latest = data[0]  # 最近一个月
    return {
        "strong_buy":  int(latest.get("strongBuy", 0)),
        "buy":         int(latest.get("buy", 0)),
        "hold":        int(latest.get("hold", 0)),
        "sell":        int(latest.get("sell", 0)),
        "strong_sell": int(latest.get("strongSell", 0)),
        "period":      latest.get("period", ""),
    }

def fetch_insider(ticker: str) -> Optional[dict]:
    """近 30 天 insider 交易（高管买卖）。
    高管净买入是强力看涨信号；净卖出意义弱（多为预定计划）。"""
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=30)
    data = finnhub_get("/stock/insider-transactions", {
        "symbol": ticker,
        "from":   start.isoformat(),
    })
    if not data or not data.get("data"):
        return None
    recent = data["data"][:20]
    buy_shares  = sum(t.get("change", 0) for t in recent if t.get("change", 0) > 0)
    sell_shares = sum(abs(t.get("change", 0)) for t in recent if t.get("change", 0) < 0)
    return {
        "buy_shares":  int(buy_shares),
        "sell_shares": int(sell_shares),
        "net":         int(buy_shares - sell_shares),
        "count":       len(recent),
    }

def fetch_macro_news() -> list[dict]:
    """抓宏观/政策新闻（FED、CPI、关税等） —— 共享，全 watchlist 只调用一次。"""
    if not TAVILY_API_KEY:
        return []
    try:
        resp = requests.post("https://api.tavily.com/search", json={
            "api_key":      TAVILY_API_KEY,
            "query":        "US Federal Reserve interest rate CPI stock market tariff today",
            "search_depth": "basic",
            "max_results":  4,
            "days":         2,
        }, timeout=15)
        if resp.status_code != 200:
            return []
        return [{"title": i.get("title", ""), "content": i.get("content", "")[:250]}
                for i in resp.json().get("results", [])]
    except Exception as e:
        print(f"[MACRO NEWS ERROR]: {e}")
        return []

# ─── SHORT-TERM INDICATORS (DAY/SWING OPTIMIZED) ──────────────────────────────

def compute_rsi(close, period: int = 7) -> float:
    """RSI(7) - 比标准 14 更敏感，适合日内/短线。"""
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 2)

def compute_macd(close, fast: int = 5, slow: int = 13, signal: int = 5) -> dict:
    """MACD(5/13/5) - Linda Raschke 经典日内设置。"""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    sig   = macd.ewm(span=signal, adjust=False).mean()
    hist  = macd - sig
    cross_up   = (hist.iloc[-2] < 0 and hist.iloc[-1] > 0) if len(hist) >= 2 else False
    cross_down = (hist.iloc[-2] > 0 and hist.iloc[-1] < 0) if len(hist) >= 2 else False
    return {
        "macd":       round(float(macd.iloc[-1]), 4),
        "signal":     round(float(sig.iloc[-1]),  4),
        "hist":       round(float(hist.iloc[-1]), 4),
        "cross_up":   bool(cross_up),
        "cross_down": bool(cross_down),
    }

def compute_ema(close, period: int) -> float:
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def compute_bollinger(close, period: int = 20, std_dev: float = 2.0) -> dict:
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    price     = float(close.iloc[-1])
    cu, cl, cm = float(upper.iloc[-1]), float(lower.iloc[-1]), float(sma.iloc[-1])
    bw    = (cu - cl) / cm if cm != 0 else 0
    pct_b = (price - cl) / (cu - cl) if (cu - cl) != 0 else 0.5
    bw_s  = ((upper - lower) / sma).dropna()
    recent = bw_s.iloc[-50:] if len(bw_s) >= 50 else bw_s
    squeeze  = bool(bw <= float(recent.quantile(0.20)))
    breakout = "up" if price > cu else ("down" if price < cl else "inside")
    return {
        "upper": round(cu, 2), "middle": round(cm, 2), "lower": round(cl, 2),
        "pct_b": round(pct_b, 3), "squeeze": squeeze, "breakout": breakout,
    }

def compute_volume_surge(volume) -> dict:
    """放量倍率（vs 20-bar 均量），≥1.8x 视为异动。"""
    avg = float(volume.rolling(20).mean().iloc[-1])
    cur = float(volume.iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {"ratio": round(ratio, 2), "surge": ratio >= 1.8}

def compute_atr(high, low, close, period: int = 14) -> dict:
    prev = close.shift(1)
    tr   = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr  = float(tr.rolling(period).mean().iloc[-1])
    return {
        "atr":     round(atr, 4),
        "atr_pct": round((atr / float(close.iloc[-1])) * 100, 2),
    }

def compute_stochastic(high, low, close, k: int = 9, d: int = 3) -> dict:
    """Stochastic(9,3) - 比标准 14,3 更适合短线。"""
    ll = low.rolling(k).min()
    hh = high.rolling(k).max()
    kv = 100 * (close - ll) / (hh - ll + 1e-9)
    dv = kv.rolling(d).mean()
    k_now = round(float(kv.iloc[-1]), 2)
    d_now = round(float(dv.iloc[-1]), 2)
    kp = float(kv.iloc[-2]) if len(kv) >= 2 else k_now
    dp = float(dv.iloc[-2]) if len(dv) >= 2 else d_now
    return {
        "k": k_now, "d": d_now,
        "cross_up":   bool((kp < dp) and (k_now > d_now) and k_now < 30),
        "cross_down": bool((kp > dp) and (k_now < d_now) and k_now > 70),
    }

def compute_vwap_today(df) -> float:
    """当日 VWAP（以最新交易日所有 bar 计算）。"""
    try:
        last_date = df.index[-1].date()
        today = df[df.index.date == last_date]
        if len(today) == 0:
            today = df.tail(7)
    except Exception:
        today = df.tail(7)
    typical = (today["High"] + today["Low"] + today["Close"]) / 3
    vwap = (typical * today["Volume"]).cumsum() / today["Volume"].cumsum()
    return round(float(vwap.iloc[-1]), 2)

def compute_gap(df_daily) -> dict:
    """基于日线计算今日跳空。"""
    if len(df_daily) < 2:
        return {"gap_pct": 0.0, "gap_up": False, "gap_down": False}
    prev  = float(df_daily["Close"].iloc[-2])
    open_ = float(df_daily["Open"].iloc[-1])
    pct   = ((open_ - prev) / prev) * 100
    return {"gap_pct": round(pct, 2), "gap_up": pct >= 1.5, "gap_down": pct <= -1.5}

def compute_support_resistance(df_daily, lookback: int = 10) -> dict:
    """近 N 日支撑/压力（基于日线 high/low）。"""
    r = df_daily.tail(lookback)
    return {
        "resistance": round(float(r["High"].max()), 2),
        "support":    round(float(r["Low"].min()),  2),
    }

def compute_momentum(close, period: int = 5) -> float:
    """N-bar 动能 (%)，捕捉短线方向。"""
    if len(close) < period + 1:
        return 0.0
    return round((float(close.iloc[-1]) / float(close.iloc[-1 - period]) - 1) * 100, 2)

# ─── TECHNICAL SCORING (0-10 buy / 0-10 sell) ─────────────────────────────────

def compute_technical_score(price, rsi, macd, ema9, ema21, boll, vol, stoch,
                            vwap, momentum, gap):
    """
    短线技术评分。返回 (buy_score 0-10, sell_score 0-10, alerts)。
    每项权重已按短线交易调整。
    """
    buy, sell = 0, 0
    alerts = []

    # 1. RSI(7)
    if rsi <= 25:    buy += 2; alerts.append(f"RSI({rsi}) 严重超卖")
    elif rsi <= 35:  buy += 1
    elif rsi >= 75:  sell += 2; alerts.append(f"RSI({rsi}) 严重超买")
    elif rsi >= 65:  sell += 1

    # 2. MACD(5/13/5) - 短期动能
    if macd["cross_up"]:    buy += 2;  alerts.append("MACD 金叉")
    elif macd["cross_down"]: sell += 2; alerts.append("MACD 死叉")
    elif macd["hist"] > 0:   buy += 1
    elif macd["hist"] < 0:   sell += 1

    # 3. EMA 9/21 短期趋势
    if ema9 > ema21 and price > ema9:    buy  += 1
    elif ema9 < ema21 and price < ema9:  sell += 1

    # 4. VWAP - 日内关键位
    if price > vwap * 1.005:    buy  += 1
    elif price < vwap * 0.995:  sell += 1

    # 5. Bollinger Bands
    if boll["squeeze"]:
        alerts.append("BB 收窄（蓄势待发）")
    if boll["breakout"] == "up":
        buy += 2; alerts.append("BB 上轨突破")
    elif boll["breakout"] == "down":
        sell += 2; alerts.append("BB 下轨跌破")
    elif boll["pct_b"] < 0.10:
        buy += 1
    elif boll["pct_b"] > 0.90:
        sell += 1

    # 6. Volume surge
    if vol["surge"]:
        if momentum > 0:
            buy += 1; alerts.append(f"放量 {vol['ratio']}x↑")
        else:
            sell += 1; alerts.append(f"放量 {vol['ratio']}x↓")

    # 7. Stochastic(9,3) cross
    if stoch["cross_up"]:    buy  += 1; alerts.append("Stoch 底部金叉")
    elif stoch["cross_down"]: sell += 1; alerts.append("Stoch 顶部死叉")

    # 8. 5-bar 动能
    if momentum >= 3:    buy  += 1
    elif momentum <= -3: sell += 1

    # 9. Gap (盘前/开盘重点)
    if gap["gap_up"]:    alerts.append(f"高开 {gap['gap_pct']:+.1f}%")
    elif gap["gap_down"]: alerts.append(f"低开 {gap['gap_pct']:+.1f}%")

    return min(buy, 10), min(sell, 10), alerts

# ─── MARKET DATA ──────────────────────────────────────────────────────────────

def fetch_intraday(ticker: str, retries: int = 3) -> Optional[pd.DataFrame]:
    """1h × 60d，含盘前盘后。"""
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period="60d", interval="1h",
                             progress=False, auto_adjust=True, prepost=True)
            if df is None or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(10 * (2 ** attempt))
            else:
                print(f"[ERROR intraday] {ticker}: {e}")
                return None

def fetch_daily(ticker: str, retries: int = 3) -> Optional[pd.DataFrame]:
    """日线 3 月（支撑/压力/缺口上下文）。"""
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period="3mo", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 20:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5 * (2 ** attempt))
            else:
                print(f"[ERROR daily] {ticker}: {e}")
                return None

# ─── FULL ANALYSIS ────────────────────────────────────────────────────────────

def analyze(ticker: str) -> Optional[dict]:
    try:
        df_h = fetch_intraday(ticker)
        df_d = fetch_daily(ticker)
        if df_h is None or df_d is None:
            return None

        close_h = df_h["Close"].squeeze()
        high_h  = df_h["High"].squeeze()
        low_h   = df_h["Low"].squeeze()
        vol_h   = df_h["Volume"].squeeze()
        price   = round(float(close_h.iloc[-1]), 2)

        # 日线变动 (短线参考)
        chg1 = round(((price - float(df_d["Close"].iloc[-2])) /
                       float(df_d["Close"].iloc[-2])) * 100, 2) if len(df_d) >= 2 else 0.0
        chg5 = round(((price - float(df_d["Close"].iloc[-6])) /
                       float(df_d["Close"].iloc[-6])) * 100, 2) if len(df_d) >= 6 else 0.0

        rsi      = compute_rsi(close_h, period=7)
        macd_d   = compute_macd(close_h, fast=5, slow=13, signal=5)
        ema9     = compute_ema(close_h, 9)
        ema21    = compute_ema(close_h, 21)
        boll     = compute_bollinger(close_h, period=20)
        vol_d    = compute_volume_surge(vol_h)
        atr_h    = compute_atr(high_h, low_h, close_h)
        # 日线 ATR 用于止损（小时 ATR 偏小）
        atr_dly  = compute_atr(df_d["High"].squeeze(), df_d["Low"].squeeze(),
                                df_d["Close"].squeeze())
        stoch    = compute_stochastic(high_h, low_h, close_h, k=9, d=3)
        vwap     = compute_vwap_today(df_h)
        momentum = compute_momentum(close_h, period=5)
        gap      = compute_gap(df_d)
        sr       = compute_support_resistance(df_d, lookback=10)

        buy_s, sell_s, alerts = compute_technical_score(
            price, rsi, macd_d, ema9, ema21, boll, vol_d, stoch,
            vwap, momentum, gap,
        )

        return {
            "ticker": ticker,
            "company": COMPANY_NAMES.get(ticker, ticker),
            "price": price, "chg1": chg1, "chg5": chg5,
            "rsi": rsi, "macd": macd_d, "ema9": ema9, "ema21": ema21,
            "boll": boll, "vol": vol_d,
            "atr_h": atr_h, "atr_d": atr_dly,
            "stoch": stoch, "vwap": vwap, "momentum": momentum,
            "gap": gap, "sr": sr,
            "buy_score": buy_s, "sell_score": sell_s, "alerts": alerts,
        }
    except Exception as e:
        print(f"[ANALYZE ERROR] {ticker}: {e}")
        return None

# ─── GEMINI AI ────────────────────────────────────────────────────────────────

def gemini_analyze(tech: dict, news: list[dict], macro_news: list[dict]) -> dict:
    news_text = "\n".join([
        f"- [{n.get('date', '')}] {n['title'][:80]}: {n['content'][:140]}"
        for n in news[:5]
    ]) or "无相关新闻"
    macro_text = "\n".join([f"- {n['title'][:80]}" for n in macro_news[:4]]) or "无宏观新闻"

    # ─── 基本面/事件 (Finnhub) ───
    earn = tech.get("earnings")
    if earn:
        hour_zh = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}.get(earn.get("hour", ""), "")
        earnings_text = f"⚠️ {earn['days_to']} 天后 ({earn['date']} {hour_zh}) 公布财报"
        if earn.get("eps_est") is not None:
            earnings_text += f"，市场预期 EPS ${earn['eps_est']}"
    else:
        earnings_text = "未来 14 天无财报"

    recs = tech.get("recs")
    if recs:
        recs_text = (f"评级分布 ({recs['period']}): "
                     f"强烈买{recs['strong_buy']}/买{recs['buy']}/持{recs['hold']}/"
                     f"卖{recs['sell']}/强卖{recs['strong_sell']}")
    else:
        recs_text = "无分析师评级数据"

    ins = tech.get("insider")
    if ins:
        if ins["net"] > 0:
            insider_text = f"高管净买入 +{ins['net']:,} 股（近30天，{ins['count']}笔）✅ 看涨"
        elif ins["net"] < -10000:
            insider_text = f"高管净卖出 {ins['net']:,} 股（近30天，{ins['count']}笔）"
        else:
            insider_text = f"高管交易平衡（近30天 {ins['count']}笔）"
    else:
        insider_text = "无 insider 数据"

    prompt = f"""你是资深短线交易员，专做日内交易和波段交易（持仓周期：日内 ~ 1周）。
请基于下列数据，给出"短线交易"建议——综合考虑新闻催化、基本面事件、技术信号。

【{tech['ticker']} ({tech['company']})】
现价 ${tech['price']} | 日涨跌 {tech['chg1']:+.2f}% | 5日涨跌 {tech['chg5']:+.2f}%
近10日支撑/压力: ${tech['sr']['support']} / ${tech['sr']['resistance']}
日线 ATR(14): ${tech['atr_d']['atr']} ({tech['atr_d']['atr_pct']}%) ← 用于止损参考

⚠️ 基本面与事件（**短线优先级最高**）:
- 财报: {earnings_text}
- 分析师: {recs_text}
- Insider: {insider_text}

短线技术指标 (1h K线):
- RSI(7): {tech['rsi']}
- MACD(5/13/5): hist={tech['macd']['hist']:+.4f} (金叉={tech['macd']['cross_up']}, 死叉={tech['macd']['cross_down']})
- EMA9/21: {tech['ema9']} / {tech['ema21']}
- Bollinger(20): %B={tech['boll']['pct_b']}, squeeze={tech['boll']['squeeze']}, breakout={tech['boll']['breakout']}
- Stoch(9,3): K={tech['stoch']['k']} D={tech['stoch']['d']}
- 当日 VWAP: ${tech['vwap']}
- 5-bar 动能: {tech['momentum']:+.2f}%
- 成交量: {tech['vol']['ratio']}x (放量={tech['vol']['surge']})
- 跳空: {tech['gap']['gap_pct']:+.2f}%

技术评分: 买入信号 {tech['buy_score']}/10 ｜ 卖出信号 {tech['sell_score']}/10
警报: {', '.join(tech['alerts']) or '无'}

近3天个股新闻:
{news_text}

宏观/政策新闻:
{macro_text}

⚡ **关键规则**：如果 3 天内有财报，必须建议"日内"或"观望"——不要建议持仓过财报夜（跳空风险极高）。
如果高管近期有显著净买入，提升 1-2 分评分。

【任务】综合"新闻催化 × 技术信号"，给出短线交易建议。
评分标准 (score 1-10)：
  10 = 极强买入信号（多重确认 + 强催化）
  8-9 = 强烈买入
  6-7 = 买入
  5   = 中性观望（信号矛盾或不明）
  4   = 卖出
  2-3 = 强烈卖出
  1   = 极强卖出信号

严格返回 JSON（不要 markdown 代码块）：
{{
  "score": 整数 1-10,
  "action": "强烈买入/买入/观望/卖出/强烈卖出",
  "hold_period": "日内/2-3天/3-5天/1周",
  "entry_low":  数字（建议入场价下限）,
  "entry_high": 数字（建议入场价上限）,
  "target_1":   数字（第一目标，短期 1-3 天）,
  "target_2":   数字（第二目标，1周内）,
  "stop_loss":  数字（基于 ATR/支撑位的止损）,
  "reason":     "40字内：核心决策理由（新闻+指标）",
  "news_impact":"30字内：新闻对短期的影响判断",
  "catalyst":   "30字内：未来1周潜在催化剂",
  "risk_level": "低/中/高",
  "confidence": "高/中/低（指标和新闻一致性）",
  "summary":    "60字内：具体执行建议（什么价位买/卖、持有多久、止损位）"
}}"""

    # ─── 重试策略 ───
    # 三层 cascade × N 个 key × 最多 3 次（指数退避用于 503/500/UNAVAILABLE）
    # 429 (配额耗尽)：立即跳到下一个 (key,model) 组合，不浪费时间
    # 503/500/UNAVAILABLE：等 3s/6s/12s 后重试同 (key,model)（服务端临时故障）
    last_err = "unknown"
    for model in MODEL_CASCADE:
        for api_key in GEMINI_API_KEYS:
            for attempt in range(3):
                try:
                    client = genai.Client(api_key=api_key)
                    if attempt == 0:
                        time.sleep(GEMINI_REQUEST_DELAY)
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.3,
                            response_mime_type="application/json",
                        ),
                    )
                    raw = re.sub(r"```json|```", "", response.text.strip()).strip()
                    result = json.loads(raw)
                    result["_model"] = model
                    print(f"[AI OK] {tech['ticker']} — {model} → "
                          f"{result.get('action')} ({result.get('score')}/10)")
                    return result
                except Exception as e:
                    err = str(e)
                    last_err = err
                    err_short = err[:120].replace("\n", " ")
                    print(f"[AI try{attempt+1}/3] {tech['ticker']} {model} "
                          f"...{api_key[-6:]}: {err_short}")

                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        # 此 (model,key) 已超配额，立即跳过
                        break
                    if any(code in err for code in ("503", "500", "UNAVAILABLE", "INTERNAL")):
                        # 临时故障：退避后重试同 key/model
                        if attempt < 2:
                            wait = 3 * (2 ** attempt)  # 3s, 6s
                            print(f"           ↳ 服务端临时故障，{wait}s 后重试...")
                            time.sleep(wait)
                            continue
                        break
                    # 其他错误（解析失败、auth 等）—— 不重试
                    break

    # ─── 全部模型/key 都失败 → 纯技术评分推导 ───
    print(f"[AI FALLBACK] {tech['ticker']} 全部模型失败，启用技术面 fallback。最后错误：{last_err[:80]}")
    net = tech["buy_score"] - tech["sell_score"]
    score = max(1, min(10, 5 + net // 2))
    if score >= 8:   action = "强烈买入"
    elif score >= 6: action = "买入"
    elif score <= 2: action = "强烈卖出"
    elif score <= 4: action = "卖出"
    else:            action = "观望"
    atr_d = tech["atr_d"]["atr"]
    return {
        "score": score, "action": action, "hold_period": "2-3天",
        "entry_low":  round(tech["price"] - atr_d * 0.3, 2),
        "entry_high": round(tech["price"] + atr_d * 0.3, 2),
        "target_1":   round(tech["price"] + atr_d * 1.0, 2),
        "target_2":   round(tech["price"] + atr_d * 2.0, 2),
        "stop_loss":  round(tech["price"] - atr_d * 1.5, 2),
        "reason":     "AI不可用，仅技术评分",
        "news_impact":"无法获取",
        "catalyst":   "未知",
        "risk_level": "中", "confidence": "低",
        "summary":    "AI 暂不可用，仅参考技术面。",
        "_model":     "fallback",
    }

# ─── MESSAGE BUILDER ──────────────────────────────────────────────────────────

ACTION_EMOJI = {
    "强烈买入": "🚀🚀", "买入": "🟢", "观望": "🟡",
    "卖出":   "🔴",   "强烈卖出": "❌❌",
}
RISK_EMOJI = {"低": "🟢", "中": "🟡", "高": "🔴"}
CONF_EMOJI = {"高": "💪", "中": "✋", "低": "⚠️"}

def score_bar(score: int) -> str:
    """1-10 可视化条。"""
    s = max(1, min(10, int(score)))
    if s >= 7:   emoji = "🟩"
    elif s <= 4: emoji = "🟥"
    else:        emoji = "🟨"
    return emoji * s + "⬜" * (10 - s) + f"  <b>{s}/10</b>"

def _earnings_line(tech: dict) -> str:
    """财报提示行：3 天内显眼警告 / 7 天内黄色提示 / 14 天内简短信息。"""
    e = tech.get("earnings")
    if not e:
        return ""
    days = e.get("days_to", 99)
    hour_zh = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}.get(e.get("hour", ""), "")
    if days <= 3:
        prefix = "🚨🚨"
        suffix = " — <b>不建议持仓过夜！</b>"
    elif days <= 7:
        prefix = "⚠️"
        suffix = " — 注意跳空风险"
    else:
        prefix = "📅"
        suffix = ""
    return f"{prefix} <b>财报 {e['date']} {hour_zh}（{days} 天后）</b>{suffix}\n"

def _recs_line(tech: dict) -> str:
    r = tech.get("recs")
    if not r:
        return ""
    bullish = r["strong_buy"] + r["buy"]
    bearish = r["sell"] + r["strong_sell"]
    total = bullish + r["hold"] + bearish
    if total == 0:
        return ""
    return (f"🏛 <b>分析师</b> 买{bullish} · 持{r['hold']} · 卖{bearish}"
            f" <i>({r['period']})</i>\n")

def _insider_line(tech: dict) -> str:
    i = tech.get("insider")
    if not i or i["count"] == 0:
        return ""
    if i["net"] > 0:
        return f"🧑‍💼 <b>高管净买入</b> +{i['net']:,} 股（30天，看涨）✅\n"
    elif i["net"] < -10000:
        return f"🧑‍💼 高管净卖出 {i['net']:,} 股（30天）\n"
    return ""

def build_stock_card(tech: dict, ai: dict) -> str:
    score   = int(ai.get("score", 5))
    act_e   = ACTION_EMOJI.get(ai["action"], "🟡")
    risk_e  = RISK_EMOJI.get(ai["risk_level"], "🟡")
    conf_e  = CONF_EMOJI.get(ai["confidence"], "✋")
    chg_arrow = "📈" if tech["chg1"] >= 0 else "📉"

    # 基本面 / 事件块（如果没数据就空）
    fundamentals = _earnings_line(tech) + _recs_line(tech) + _insider_line(tech)
    fundamentals_block = f"\n{fundamentals}" if fundamentals else ""

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{tech['ticker']}</b> {tech['company']} ｜ ${tech['price']} {chg_arrow} {tech['chg1']:+.2f}%\n"
        f"\n"
        f"{act_e} <b>{ai['action']}</b>  {score_bar(score)}\n"
        f"   {ai['reason']}\n"
        f"\n"
        f"⏱ 持仓 <b>{ai['hold_period']}</b> ｜ {risk_e} 风险 {ai['risk_level']} ｜ {conf_e} 信心 {ai['confidence']}\n"
        f"\n"
        f"🎯 <b>入场区间</b> ${ai['entry_low']:.2f} ~ ${ai['entry_high']:.2f}\n"
        f"📍 目标1 <b>${ai['target_1']}</b> ｜ 目标2 <b>${ai['target_2']}</b>\n"
        f"🛑 止损 <b>${ai['stop_loss']}</b>\n"
        f"{fundamentals_block}"
        f"\n"
        f"📊 <b>技术面</b>  买 {tech['buy_score']}/10 ｜ 卖 {tech['sell_score']}/10\n"
        f"   <i>RSI(7) {tech['rsi']} · MACD {tech['macd']['hist']:+.3f} · BB%B {tech['boll']['pct_b']}</i>\n"
        f"   <i>VWAP ${tech['vwap']} · Vol {tech['vol']['ratio']}x · 动能 {tech['momentum']:+.2f}%</i>\n"
        f"   <i>支撑 ${tech['sr']['support']} · 压力 ${tech['sr']['resistance']} · ATR ${tech['atr_d']['atr']}</i>\n"
        f"   ⚡ {' · '.join(tech['alerts']) if tech['alerts'] else '无特殊警报'}\n"
        f"\n"
        f"📰 <b>新闻：</b>{ai['news_impact']}\n"
        f"🔮 <b>催化剂：</b>{ai['catalyst']}\n"
        f"💡 <b>执行建议：</b>{ai['summary']}\n"
        f"<i>🤖 {ai.get('_model', 'unknown')}</i>"
    )

SESSION_EMOJI = {"Pre-Market":"🌅","Market Hours":"📈","After-Hours":"🌆","Off-Hours":"🌙"}
SESSION_NAME_ZH = {"Pre-Market":"盘前","Market Hours":"盘中","After-Hours":"盘后","Off-Hours":"休市"}

def get_session(now_et: datetime) -> str:
    total = now_et.hour * 60 + now_et.minute
    if   240 <= total < 570:  return "Pre-Market"
    elif 570 <= total < 960:  return "Market Hours"
    elif 960 <= total < 1200: return "After-Hours"
    else:                     return "Off-Hours"

def build_header(time_str: str, session: str, n: int) -> str:
    """开头消息：时段 + 标题。"""
    sess_e  = SESSION_EMOJI.get(session, "")
    sess_zh = SESSION_NAME_ZH.get(session, session)
    return (
        f"<b>📊 短线交易信号报告</b>\n"
        f"{sess_e} <b>{sess_zh}</b> ｜ 📅 {time_str}\n"
        f"<i>1h技术指标 + 实时新闻 + Gemini AI 综合评分 (1-10)</i>\n"
        f"📦 共 {n} 支股票，按评分高→低推送"
    )

def build_summary(results: list[dict]) -> str:
    """结尾消息：汇总统计 + 重点 + 免责。"""
    scores      = [int(r["ai"].get("score", 5)) for r in results]
    strong_buy  = sum(1 for s in scores if s >= 8)
    buy         = sum(1 for s in scores if 6 <= s < 8)
    hold        = sum(1 for s in scores if 4 < s < 6)
    sell        = sum(1 for s in scores if 2 < s <= 4)
    strong_sell = sum(1 for s in scores if s <= 2)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "<b>📋 本轮汇总</b>",
        f"🚀🚀 强烈买入 {strong_buy} ｜ 🟢 买入 {buy} ｜ "
        f"🟡 观望 {hold} ｜ 🔴 卖出 {sell} ｜ ❌❌ 强烈卖出 {strong_sell}",
    ]

    top = [r for r in results if int(r["ai"].get("score", 5)) >= 7]
    if top:
        names = ", ".join([f"{r['tech']['ticker']}({r['ai']['score']})" for r in top])
        lines.append(f"⭐ <b>重点关注：</b>{names}")

    # 财报周内警告（短线最重要的风险提醒）
    earnings_this_week = []
    for r in results:
        e = r["tech"].get("earnings")
        if e and e.get("days_to", 99) <= 7:
            earnings_this_week.append(f"{r['tech']['ticker']}({e['days_to']}天)")
    if earnings_this_week:
        lines.append(f"🚨 <b>本周财报：</b>{', '.join(earnings_this_week)} — 严控隔夜持仓")

    risky = [r["tech"]["ticker"] for r in results if r["ai"].get("risk_level") == "高"]
    if risky:
        lines.append(f"⚠️ <b>高风险：</b>{', '.join(risky)}")

    fallback = [r["tech"]["ticker"] for r in results
                if r["ai"].get("_model") == "fallback"]
    if fallback:
        lines.append(f"🤖 <b>仅技术面（AI 不可用）：</b>{', '.join(fallback)}")

    lines.append("")
    lines.append("<i>⚠️ AI 辅助生成，仅供短线交易参考，不构成投资建议。请严格执行止损。</i>")
    return "\n".join(lines)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    now_et   = datetime.now(ET)
    time_str = now_et.strftime("%Y-%m-%d %H:%M ET")
    session  = get_session(now_et)

    print(f"[START] 短线分析 — {time_str} ({session})")
    print(f"[INFO] 自选股 ({len(WATCHLIST)}): {', '.join(WATCHLIST)}")

    print("[INFO] 抓取宏观新闻...")
    macro_news = fetch_macro_news()
    print(f"       共 {len(macro_news)} 条")

    results = []
    for ticker in WATCHLIST:
        print(f"[INFO] 分析 {ticker}...")
        tech = analyze(ticker)
        if not tech:
            print(f"       [SKIP] 数据不足")
            continue
        company = COMPANY_NAMES.get(ticker, ticker)

        # ─── Finnhub 数据集（短线必备）───
        news      = fetch_news(ticker, company)
        earnings  = fetch_earnings_date(ticker)
        recs      = fetch_recommendations(ticker)
        insider   = fetch_insider(ticker)

        # 把基本面数据塞进 tech，方便后续使用
        tech["earnings"] = earnings
        tech["recs"]     = recs
        tech["insider"]  = insider

        ern_info = ""
        if earnings:
            ern_info = f" ｜ 📅 财报 {earnings['date']}（{earnings['days_to']}天后）"
        print(f"       新闻{len(news)}条 ｜ 技术买{tech['buy_score']}/卖{tech['sell_score']}{ern_info}")

        ai = gemini_analyze(tech, news, macro_news)
        results.append({"tech": tech, "ai": ai})
        time.sleep(1)

    if not results:
        send_telegram(
            f"⚠️ 短线分析：本次周期未能获取任何数据。\n"
            f"已尝试 {len(WATCHLIST)} 支股票，全部失败。\n"
            f"时间：{time_str}"
        )
        return

    # 按评分排序，高分先推
    results.sort(key=lambda r: -int(r["ai"].get("score", 5)))

    # 1) 开头消息
    send_telegram(build_header(time_str, session, len(results)))

    # 2) 每只股票一条独立消息（避免单条消息过长）
    for r in results:
        send_telegram(build_stock_card(r["tech"], r["ai"]))

    # 3) 结尾汇总
    send_telegram(build_summary(results))

    print(f"[OK] 报告已发送：1 header + {len(results)} 卡片 + 1 汇总")

if __name__ == "__main__":
    main()
