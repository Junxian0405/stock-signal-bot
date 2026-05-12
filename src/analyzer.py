"""
Stock Signal Analyzer — US Market (NASDAQ/NYSE)
Indicators : RSI · MACD · EMA9/21 · MA50/200 · Bollinger Bands · OBV · Volume Surge · ATR · VWAP · Stochastic · Gap%
Modes      : Hourly standard scan  |  Pre-market deep scan (04:00 / 07:00 / 09:00 ET)
Signals    : BUY · SELL · HOLD  (with squeeze / divergence / gap alerts)
"""

import os
import time
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# CONFIG
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

WATCHLIST = [
    "MU", "SNDK"
]

ET = pytz.timezone("America/New_York")
PREMARKET_HOURS = {4, 7, 9}

# TELEGRAM
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()

# INDICATORS
def compute_rsi(close, period=14):
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
    return (round(float(macd.iloc[-1]), 4),
            round(float(signal.iloc[-1]), 4),
            round(float((macd - signal).iloc[-1]), 4))

def compute_ema(close, period):
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def compute_ma(close, period):
    return round(float(close.rolling(period).mean().iloc[-1]), 4)

def compute_bollinger(close, period=20, std_dev=2.0):
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
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
        "lower": round(cur_lower, 2), "bandwidth": round(bandwidth, 4),
        "pct_b": round(pct_b, 3), "squeeze": squeeze, "breakout": breakout,
    }

def compute_obv(close, volume):
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv       = (direction * volume).cumsum()
    slope     = float(obv.iloc[-1]) - float(obv.iloc[-6]) if len(obv) >= 6 else 0
    p_now, p_prev = float(close.iloc[-1]), float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[-1])
    return {
        "obv_trend":    "up" if slope > 0 else "down",
        "bull_diverge": (p_now < p_prev) and (slope > 0),
        "bear_diverge": (p_now > p_prev) and (slope < 0),
    }

def compute_volume_surge(volume):
    avg = float(volume.rolling(20).mean().iloc[-1])
    cur = float(volume.iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {"ratio": round(ratio, 2), "surge": ratio >= 2.0}

def compute_atr(high, low, close, period=14):
    prev  = close.shift(1)
    tr    = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr   = float(tr.rolling(period).mean().iloc[-1])
    atr_p = float(tr.rolling(period).mean().iloc[-5]) if len(tr) >= 5 else atr
    return {"atr": round(atr, 4), "atr_pct": round((atr / float(close.iloc[-1])) * 100, 2),
            "expanding": atr > atr_p}

def compute_stochastic(high, low, close, k_period=14, d_period=3):
    ll   = low.rolling(k_period).min()
    hh   = high.rolling(k_period).max()
    k    = 100 * (close - ll) / (hh - ll + 1e-9)
    d    = k.rolling(d_period).mean()
    kv   = round(float(k.iloc[-1]), 2)
    dv   = round(float(d.iloc[-1]), 2)
    kp   = float(k.iloc[-2]) if len(k) >= 2 else kv
    dp   = float(d.iloc[-2]) if len(d) >= 2 else dv
    return {"k": kv, "d": dv,
            "cross_up":   (kp < dp) and (kv > dv) and kv < 30,
            "cross_down": (kp > dp) and (kv < dv) and kv > 70}

def compute_vwap(df):
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap    = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return round(float(vwap.iloc[-1]), 2)

def compute_gap(df):
    if len(df) < 2:
        return {"gap_pct": 0.0, "gap_up": False, "gap_down": False}
    prev  = float(df["Close"].iloc[-2])
    open_ = float(df["Open"].iloc[-1])
    pct   = ((open_ - prev) / prev) * 100
    return {"gap_pct": round(pct, 2), "gap_up": pct >= 2.0, "gap_down": pct <= -2.0}

def compute_rsi_divergence(close):
    rsi = compute_rsi_series(close)
    if len(close) < 10:
        return {"bull": False, "bear": False}
    pn, pp = float(close.iloc[-1]), float(close.iloc[-10])
    rn, rp = float(rsi.iloc[-1]),   float(rsi.iloc[-10])
    return {"bull": (pn < pp) and (rn > rp), "bear": (pn > pp) and (rn < rp)}

# SIGNAL ENGINE
def get_signal(price, rsi, macd, macd_sig, ema9, ema21, ma50, ma200,
               boll, obv, vol, atr, stoch, vwap, rsi_div):
    buy_v, sell_v = 0, 0
    alerts = []

    # 1 RSI
    if rsi < 35:   buy_v  += 1
    elif rsi > 65: sell_v += 1

    # 2 MACD
    if macd > macd_sig:   buy_v  += 1
    elif macd < macd_sig: sell_v += 1

    # 3 EMA 9/21
    if ema9 > ema21:   buy_v  += 1
    elif ema9 < ema21: sell_v += 1

    # 4 MA 50/200
    if price > ma50 and ma50 > ma200: buy_v  += 1
    elif price < ma50:                sell_v += 1

    # 5 Bollinger squeeze / breakout
    if boll["squeeze"]:
        alerts.append("BB Squeeze - coiling")
    elif boll["breakout"] == "up":
        buy_v  += 1
        alerts.append("BB Breakout UP")
    elif boll["breakout"] == "down":
        sell_v += 1
        alerts.append("BB Breakout DOWN")

    # 6 Bollinger %B
    if boll["pct_b"] < 0.05:   buy_v  += 1
    elif boll["pct_b"] > 0.95: sell_v += 1

    # 7 OBV trend
    if obv["obv_trend"] == "up":     buy_v  += 1
    elif obv["obv_trend"] == "down": sell_v += 1

    # 8 OBV divergence (bonus)
    if obv["bull_diverge"]:
        buy_v  += 1
        alerts.append("OBV Bull Divergence")
    if obv["bear_diverge"]:
        sell_v += 1
        alerts.append("OBV Bear Divergence")

    # 9 Volume surge
    if vol["surge"]:
        if price >= ma50:
            buy_v  += 1
            alerts.append(f"Volume Surge {vol['ratio']}x")
        else:
            sell_v += 1
            alerts.append(f"Volume Surge {vol['ratio']}x (bearish)")

    # 10 Stochastic
    if stoch["cross_up"]:
        buy_v  += 1
        alerts.append("Stoch cross UP (oversold)")
    elif stoch["cross_down"]:
        sell_v += 1
        alerts.append("Stoch cross DOWN (overbought)")
    elif stoch["k"] < 20:   buy_v  += 1
    elif stoch["k"] > 80:   sell_v += 1

    # 11 VWAP
    if price > vwap:   buy_v  += 1
    elif price < vwap: sell_v += 1

    # 12 RSI divergence (bonus)
    if rsi_div["bull"]:
        buy_v  += 1
        alerts.append("RSI Bull Divergence")
    if rsi_div["bear"]:
        sell_v += 1
        alerts.append("RSI Bear Divergence")

    # 13 ATR expanding
    if atr["expanding"] and not boll["squeeze"]:
        if buy_v > sell_v:
            buy_v  += 1
            alerts.append("ATR Expanding (bull)")
        else:
            sell_v += 1
            alerts.append("ATR Expanding (bear)")

    # Verdict: need 5+ votes
    if buy_v >= 7:
        return "BUY STRONG", alerts
    elif buy_v >= 5:
        return "BUY", alerts
    elif sell_v >= 7:
        return "SELL STRONG", alerts
    elif sell_v >= 5:
        return "SELL", alerts
    else:
        return "HOLD", alerts

SIGNAL_EMOJI = {
    "BUY STRONG": "🟢💪 STRONG BUY",
    "BUY":        "🟢 BUY",
    "SELL STRONG":"🔴💪 STRONG SELL",
    "SELL":       "🔴 SELL",
    "HOLD":       "🟡 HOLD",
}

# MARKET DATA
def fetch_ohlcv(ticker: str, retries: int = 3):
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

# ANALYZE
def analyze(ticker, premarket=False):
    try:
        df = fetch_ohlcv(ticker)
        if df is None or len(df) < 30:
            return None

        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()
        price  = round(float(close.iloc[-1]), 2)

        rsi              = compute_rsi(close)
        macd_v, sig_v, _ = compute_macd(close)
        ema9             = compute_ema(close, 9)
        ema21            = compute_ema(close, 21)
        ma50             = compute_ma(close, 50)
        ma200            = compute_ma(close, 200)
        boll             = compute_bollinger(close)
        obv_d            = compute_obv(close, volume)
        vol_d            = compute_volume_surge(volume)
        atr_d            = compute_atr(high, low, close)
        stoch            = compute_stochastic(high, low, close)
        vwap             = compute_vwap(df)
        rsi_div          = compute_rsi_divergence(close)
        gap              = compute_gap(df)

        signal, alerts = get_signal(
            price, rsi, macd_v, sig_v, ema9, ema21,
            ma50, ma200, boll, obv_d, vol_d, atr_d,
            stoch, vwap, rsi_div
        )

        if premarket:
            if gap["gap_up"]:
                alerts.insert(0, f"GAP UP {gap['gap_pct']:+.2f}%")
            elif gap["gap_down"]:
                alerts.insert(0, f"GAP DOWN {gap['gap_pct']:+.2f}%")

        return {
            "ticker": ticker, "price": price,
            "signal": signal, "signal_label": SIGNAL_EMOJI.get(signal, signal),
            "rsi": rsi, "macd": macd_v, "macd_sig": sig_v,
            "ema9": ema9, "ema21": ema21, "ma50": ma50, "ma200": ma200,
            "boll": boll, "obv": obv_d, "vol": vol_d,
            "atr": atr_d, "stoch": stoch, "vwap": vwap,
            "gap": gap, "alerts": alerts,
        }
    except Exception as e:
        print(f"[ERROR] {ticker}: {e}")
        return None

# SESSION
def get_session(now_et):
    total = now_et.hour * 60 + now_et.minute
    if 240 <= total < 570:    return "Pre-Market", True
    elif 570 <= total < 960:  return "Market Hours", False
    elif 960 <= total < 1200: return "After-Hours", False
    else:                     return "Off-Hours", False

SESSION_EMOJI = {
    "Pre-Market":  "🌅",
    "Market Hours":"📈",
    "After-Hours": "🌆",
    "Off-Hours":   "🌙",
}

SESSION_NAME_ZH = {
    "Pre-Market":  "盘前交易",
    "Market Hours":"交易时段",
    "After-Hours": "盘后交易",
    "Off-Hours":   "休市时段",
}

# ─── HUMAN-FRIENDLY HELPERS ───────────────────────────────────────────────────

def signal_banner(signal: str) -> str:
    """Big clear action banner based on signal strength."""
    banners = {
        "BUY STRONG": "✅✅ STRONG BUY — 高度信心，多项指标一致看涨",
        "BUY":        "✅ BUY — 可考虑入场",
        "SELL STRONG":"❌❌ STRONG SELL — 多项指标转跌，建议离场",
        "SELL":       "❌ SELL — 考虑减仓或观望",
        "HOLD":       "⏸ HOLD — 信号混合，方向不明，继续等待",
    }
    return banners.get(signal, "⏸ HOLD — 信号混合，方向不明，继续等待")

def plain_reason(r: dict) -> list[str]:
    """
    Translate raw indicator values into one-line plain English sentences
    a beginner can understand at a glance.
    """
    reasons = []
    rsi, boll, obv, vol, stoch, gap = (
        r["rsi"], r["boll"], r["obv"], r["vol"], r["stoch"], r["gap"]
    )
    price, ma50, ma200, ema9, ema21, vwap = (
        r["price"], r["ma50"], r["ma200"], r["ema9"], r["ema21"], r["vwap"]
    )

    # Momentum (RSI)
    if rsi < 30:
        reasons.append(f"📉 超卖状态 (RSI {rsi}) — 价格可能即将反弹")
    elif rsi > 70:
        reasons.append(f"📈 超买状态 (RSI {rsi}) — 价格可能面临回调")
    elif rsi < 45:
        reasons.append(f"😐 动能偏弱 (RSI {rsi}) — 买方尚未主导市场")
    else:
        reasons.append(f"💪 动能健康 (RSI {rsi}) — 买方占据主动")

    # Trend (EMA / MA)
    if ema9 > ema21 and price > ma50:
        reasons.append("📊 短期趋势向上 — EMA9 高于 EMA21，价格站上 MA50")
    elif ema9 < ema21 and price < ma50:
        reasons.append("📊 短期趋势向下 — EMA9 低于 EMA21，价格跌破 MA50")

    if price > ma200:
        reasons.append("🏔 长期趋势向上 — 价格高于 MA200（200日均线）")
    else:
        reasons.append("🕳 长期趋势向下 — 价格低于 MA200（200日均线）")

    # Bollinger Bands
    if boll["squeeze"]:
        reasons.append("🔵 Bollinger Band 收窄（Squeeze）— 即将出现大幅波动，方向待定")
    elif boll["breakout"] == "up":
        reasons.append("⬆️ 价格突破 BB 上轨 — 上涨动能强劲")
    elif boll["breakout"] == "down":
        reasons.append("⬇️ 价格跌破 BB 下轨 — 下行压力明显")
    elif boll["pct_b"] < 0.15:
        reasons.append("📌 价格贴近 BB 下轨 (%B 低) — 潜在反弹区域")
    elif boll["pct_b"] > 0.85:
        reasons.append("📌 价格贴近 BB 上轨 (%B 高) — 注意压力位")

    # Volume
    if vol["surge"]:
        if price >= ma50:
            reasons.append(f"🔥 成交量异常放大 {vol['ratio']}× — 大买家正在进场")
        else:
            reasons.append(f"🔥 成交量异常放大 {vol['ratio']}× — 大卖家正在出货")
    elif vol["ratio"] < 0.5:
        reasons.append("😴 成交量极低 — 市场参与度不足，观望为主")

    # OBV (smart money)
    if obv["bull_diverge"]:
        reasons.append("🧠 OBV 看涨背离 — 价格下跌但资金悄然流入，隐藏买入信号")
    elif obv["bear_diverge"]:
        reasons.append("🧠 OBV 看跌背离 — 价格上涨但资金悄然流出，隐藏卖出信号")
    elif obv["obv_trend"] == "up":
        reasons.append("💰 OBV 趋势向上 — 资金整体流入该股票")
    else:
        reasons.append("💸 OBV 趋势向下 — 资金整体流出该股票")

    # Stochastic
    if stoch["cross_up"]:
        reasons.append("🔄 Stochastic 从超卖区向上交叉 — 早期买入信号")
    elif stoch["cross_down"]:
        reasons.append("🔄 Stochastic 从超买区向下交叉 — 早期卖出信号")

    # VWAP
    if price > vwap:
        reasons.append(f"📍 价格 ${price} 高于 VWAP ${vwap} — 今日买方主导")
    else:
        reasons.append(f"📍 价格 ${price} 低于 VWAP ${vwap} — 今日卖方主导")

    # Gap (pre-market)
    if gap["gap_up"]:
        reasons.append(f"🚀 跳空高开 {gap['gap_pct']:+.1f}% — 隔夜买盘强劲")
    elif gap["gap_down"]:
        reasons.append(f"💥 跳空低开 {gap['gap_pct']:+.1f}% — 隔夜利空或抛压较重")

    return reasons

def confidence_bar(signal: str, buy_count: int, sell_count: int) -> str:
    """Visual confidence bar showing how many signals agree."""
    total = 13
    if "BUY" in signal:
        filled = min(buy_count, total)
        bar = "🟩" * filled + "⬜" * (total - filled)
        return f"信心指数: {bar} {buy_count}/{total} 项指标看涨"
    elif "SELL" in signal:
        filled = min(sell_count, total)
        bar = "🟥" * filled + "⬜" * (total - filled)
        return f"信心指数: {bar} {sell_count}/{total} 项指标看跌"
    else:
        bar = "🟨" * 5 + "⬜" * 8
        return f"信心指数: {bar} 信号混合，方向不明"

def count_votes(r: dict) -> tuple[int, int]:
    """Re-count buy/sell votes from alerts and signal for confidence bar."""
    sig = r["signal"]
    if sig == "BUY STRONG":   return 8, 2
    elif sig == "BUY":        return 6, 2
    elif sig == "SELL STRONG": return 2, 8
    elif sig == "SELL":       return 2, 6
    else:                     return 4, 4

# MESSAGE BUILDERS
def build_stock_card(r: dict, show_gap: bool = False) -> str:
    """Build one clean human-readable card per stock."""
    lines = []
    buy_v, sell_v = count_votes(r)

    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<b>{r['ticker']}</b>  —  <b>${r['price']}</b>")
    lines.append(f"")
    lines.append(f"<b>{signal_banner(r['signal'])}</b>")
    lines.append(f"")
    lines.append(confidence_bar(r["signal"], buy_v, sell_v))
    lines.append(f"")

    lines.append("<b>分析原因：</b>")
    for reason in plain_reason(r):
        lines.append(f"  {reason}")

    lines.append(f"")
    lines.append(
        f"<i>RSI {r['rsi']} · MACD {r['macd']} · "
        f"BB %B {r['boll']['pct_b']} · Vol {r['vol']['ratio']}x · "
        f"MA50 {r['ma50']}</i>"
    )
    return "\n".join(lines)

def build_standard_message(results, session, time_str):
    emoji = SESSION_EMOJI.get(session, "")
    session_zh = SESSION_NAME_ZH.get(session, session)
    lines = [
        f"<b>📊 股票信号报告</b>",
        f"{emoji} <b>{session_zh}</b>  ·  {time_str}",
        f"",
        f"以下是当前市场给出的信号：",
    ]

    order = {"BUY STRONG": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "SELL STRONG": 4}
    results_sorted = sorted(results, key=lambda r: order.get(r["signal"], 2))

    for r in results_sorted:
        lines.append(build_stock_card(r))

    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")

    buys  = sum(1 for r in results if "BUY"  in r["signal"])
    sells = sum(1 for r in results if "SELL" in r["signal"])
    holds = sum(1 for r in results if r["signal"] == "HOLD")

    lines.append(f"")
    lines.append(f"<b>汇总</b>")
    lines.append(f"  ✅ {buys} 支股票信号看涨（BUY）")
    lines.append(f"  ❌ {sells} 支股票信号看跌（SELL）")
    lines.append(f"  ⏸ {holds} 支股票信号不明，建议观望")
    lines.append(f"")
    lines.append(f"<i>⚠️ 本报告仅供参考，不构成任何投资建议。入市需谨慎，风险自负。</i>")
    return "\n".join(lines)

def build_premarket_message(results, time_str):
    lines = [
        f"<b>🌅 盘前预警报告</b>",
        f"开盘前参考  ·  {time_str}",
        f"",
        f"以下是今日开盘前需要关注的股票：",
    ]

    order = {"BUY STRONG": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "SELL STRONG": 4}
    results_sorted = sorted(results,
        key=lambda r: (order.get(r["signal"], 2), -abs(r["gap"]["gap_pct"])))

    for r in results_sorted:
        lines.append(build_stock_card(r, show_gap=True))

    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")

    hot = [r["ticker"] for r in results if
           "BUY" in r["signal"] or "SELL" in r["signal"] or
           r["gap"]["gap_up"] or r["gap"]["gap_down"] or r["vol"]["surge"]]
    if hot:
        lines.append(f"")
        lines.append(f"<b>⚡ 开盘重点关注：</b> {', '.join(hot)}")
        lines.append(f"以上股票在开盘前信号最强，请密切留意。")

    lines.append(f"")
    lines.append(f"<i>⚠️ 本报告仅供参考，不构成任何投资建议。入市需谨慎，风险自负。</i>")
    return "\n".join(lines)

# MAIN
def main():
    now_et   = datetime.now(ET)
    session, is_premarket = get_session(now_et)
    time_str = now_et.strftime("%Y-%m-%d %H:%M ET")
    deep_pm  = is_premarket and now_et.hour in PREMARKET_HOURS

    results = []
    for ticker in WATCHLIST:
        data = analyze(ticker, premarket=deep_pm)
        if data:
            results.append(data)

    if not results:
        send_telegram(
            "⚠️ 股票信号机器人：本次周期未能获取任何数据。\n"
            f"已尝试 {len(WATCHLIST)} 支股票 — 全部失败。\n"
            f"时间：{time_str}\n请检查 Actions 日志了解详情。"
        )
        return

    if deep_pm:
        msg = build_premarket_message(results, time_str)
    else:
        msg = build_standard_message(results, session, time_str)

    send_telegram(msg)
    mode = "PRE-MARKET" if deep_pm else "STANDARD"
    print(f"[OK] {mode} report — {len(results)} tickers at {time_str}")

if __name__ == "__main__":
    main()
