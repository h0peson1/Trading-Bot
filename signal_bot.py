"""
LDE Signal Bot & Telegram Controller
Architecture:
- Higher Timeframe (4H): Tracks market structure, 4H displacement, liquidity sweeps, and FVGs.
  Dispatches comprehensive multi-pair market update after every 4-hour candle close.
- Lower Timeframe (15m): Continuous execution timeframe for trade entries.
  Scans 15m candles in real-time for Sweep -> Displacement -> Engulfing / FVG Retest setups.
  Dispatches instant entry alerts with 4H confluence ratings.
- Mobile Interactive Telegram Controller: Persistent buttons for manual scans, status, and backtests.
"""

import sys
import time
import threading
import argparse
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests
import yfinance as yf
import config
import fundamentals

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

RECENT_ALERTS = set()
LAST_UPDATE_ID = 0
CYCLE_COUNTER = 0
LAST_4H_SLOT = ""
LAST_4H_DISPATCH_TIME = "None yet"


# ---------------------------------------------------------------------------
# Timing & Schedule Helpers (4-Hour Candle Boundaries & 15m Scans)
# ---------------------------------------------------------------------------
def get_next_4h_close_utc() -> datetime:
    """
    Returns the UTC datetime of the next 4-hour candle close.
    Standard 4H candle closes: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
    """
    now = datetime.now(timezone.utc)
    curr_hour = now.hour
    next_hour = ((curr_hour // 4) + 1) * 4
    if next_hour >= 24:
        next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        next_close = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    return next_close


def get_time_until_next_4h_close() -> str:
    """Returns human-readable duration until next 4H candle close."""
    now = datetime.now(timezone.utc)
    target = get_next_4h_close_utc()
    delta = target - now
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def get_current_4h_slot_key() -> str:
    """
    Returns a unique string for the current completed 4H slot,
    e.g. '2026-10-15-08' representing the 08:00-12:00 UTC candle slot.
    """
    now = datetime.now(timezone.utc)
    slot_hour = (now.hour // 4) * 4
    return f"{now.strftime('%Y-%m-%d')}-{slot_hour:02d}"


# ---------------------------------------------------------------------------
# Telegram API Helpers with Persistent Keyboard
# ---------------------------------------------------------------------------
def get_persistent_keyboard():
    """Returns persistent phone reply keyboard at bottom of screen."""
    return {
        "keyboard": [
            [
                {"text": "📊 Backtest Gold (Multi-TF)"},
                {"text": "📰 Macro News"},
            ],
            [
                {"text": "⚡ Macro Backtest"},
                {"text": "🔍 Scan Market Now"},
                {"text": "ℹ️ Bot Status"},
            ],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send_telegram(message: str, with_keyboard: bool = False) -> bool:
    """Send HTML formatted message to Telegram, automatically chunking if > 3800 chars."""
    if (
        not config.TELEGRAM_BOT_TOKEN
        or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE"
        or not config.TELEGRAM_CHAT_ID
        or config.TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE"
    ):
        print("[Telegram preview]:", message)
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

    # Chunk message if it exceeds Telegram's 4096 character limit
    chunks = []
    if len(message) > 3800:
        lines = message.split("\n\n")
        curr = ""
        for block in lines:
            if len(curr) + len(block) + 2 > 3800:
                if curr:
                    chunks.append(curr.strip())
                curr = block
            else:
                curr = f"{curr}\n\n{block}" if curr else block
        if curr:
            chunks.append(curr.strip())
    else:
        chunks = [message]

    success = True
    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if with_keyboard and idx == len(chunks) - 1:
            payload["reply_markup"] = get_persistent_keyboard()

        try:
            r = requests.post(url, json=payload, timeout=25)
            r.raise_for_status()
        except Exception as e:
            print(f"[Telegram Send Error]: {e}")
            success = False

    return success


def send_startup_banner():
    """Send startup banner detailing 4H updates and 15m entry execution."""
    next_close = get_next_4h_close_utc()
    countdown = get_time_until_next_4h_close()
    msg = (
        f"🟢 <b>LDE TRADING BOT IS LIVE!</b>\n\n"
        f"• <b>Update Timer:</b> Every 4 hours (after every 4H candle close)\n"
        f"• <b>Trade Entry Timeframe:</b> <b>15-Minute Candles (15m TF)</b>\n"
        f"• <b>Strategy:</b> 4H HTF Market Structure ➔ 15M Sweep + Retest Entries\n"
        f"• <b>Next 4H Candle Close:</b> {next_close.strftime('%H:%M UTC')} (in {countdown})\n"
        f"• <b>Pairs Monitored:</b> {', '.join(config.SYMBOLS.keys())}\n\n"
        f"📱 <i>Control buttons are pinned below! Tap any button anytime from your phone.</i>"
    )
    return send_telegram(msg, with_keyboard=True)


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------
def fetch_candles(ticker: str, interval: str) -> pd.DataFrame:
    """Fetch recent historical candles from yfinance."""
    period_map = {
        "15m": "30d",
        "30m": "30d",
        "1h": "60d",
        "4h": "60d",
        "1d": "1y",
    }
    period = period_map.get(interval, "30d")

    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval, auto_adjust=True)
    except Exception as e:
        print(f"Error fetching {ticker} ({interval}): {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    col_map = {c: c.lower() for c in df.columns}
    df = df.rename(columns=col_map)
    required = ["open", "high", "low", "close"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    df = df[required].copy()
    df.dropna(inplace=True)
    return df


# ---------------------------------------------------------------------------
# LDE Strategy Logic Components
# ---------------------------------------------------------------------------
def candle_body_ratio(row) -> float:
    body = abs(row["close"] - row["open"])
    total = row["high"] - row["low"]
    return body / total if total > 0 else 0.0


def is_bullish_engulfing(prev, curr) -> bool:
    return (
        prev["close"] < prev["open"]
        and curr["close"] > curr["open"]
        and curr["open"] <= prev["close"]
        and curr["close"] >= prev["open"]
    )


def is_bearish_engulfing(prev, curr) -> bool:
    return (
        prev["close"] > prev["open"]
        and curr["close"] < curr["open"]
        and curr["open"] >= prev["close"]
        and curr["close"] <= prev["open"]
    )


def find_liquidity_sweep(df: pd.DataFrame, direction: str, lookback: int = 40) -> bool:
    if len(df) < lookback + 5:
        return False

    prior_window = df.iloc[-(lookback + 3):-2]
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    if direction == "buy":
        prior_low = prior_window["low"].min()
        swept = (curr["low"] < prior_low) or (prev["low"] < prior_low)
        closed_above = curr["close"] > prior_low
        return swept and closed_above
    else:
        prior_high = prior_window["high"].max()
        swept = (curr["high"] > prior_high) or (prev["high"] > prior_high)
        closed_below = curr["close"] < prior_high
        return swept and closed_below


def has_displacement(df: pd.DataFrame, direction: str) -> bool:
    min_needed = config.DISPLACEMENT_COMPARE + config.MAX_DISPLACEMENT_CANDLES + 2
    if len(df) < min_needed:
        return False

    recent_candles = df.iloc[-config.MAX_DISPLACEMENT_CANDLES:]
    baseline = df.iloc[-(config.MAX_DISPLACEMENT_CANDLES + config.DISPLACEMENT_COMPARE):-config.MAX_DISPLACEMENT_CANDLES]

    avg_range = (baseline["high"] - baseline["low"]).mean()
    if avg_range == 0:
        return False

    for _, candle in recent_candles.iterrows():
        b_ratio = candle_body_ratio(candle)
        c_range = candle["high"] - candle["low"]
        is_large = c_range >= avg_range * 1.25
        is_strong_body = b_ratio >= config.MIN_BODY_RATIO

        if direction == "buy":
            is_directional = candle["close"] > candle["open"]
        else:
            is_directional = candle["close"] < candle["open"]

        if is_large and is_strong_body and is_directional:
            return True

    return False


def detect_fvg(df: pd.DataFrame, direction: str) -> str:
    if len(df) < 4:
        return ""

    c1 = df.iloc[-3]
    c3 = df.iloc[-1]

    if direction == "buy" and c3["low"] > c1["high"]:
        gap_size = c3["low"] - c1["high"]
        return f" | <b>15M FVG:</b> {format_price(c1['high'])}–{format_price(c3['low'])} (+{gap_size:.4f})"
    elif direction == "sell" and c3["high"] < c1["low"]:
        gap_size = c1["low"] - c3["high"]
        return f" | <b>15M FVG:</b> {format_price(c3['high'])}–{format_price(c1['low'])} (-{gap_size:.4f})"

    return ""


def format_price(val: float) -> str:
    if val >= 1000:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    else:
        return f"{val:.6f}"


# ---------------------------------------------------------------------------
# 4-Hour Higher Timeframe (HTF) Market Analysis & Scheduled Updates
# ---------------------------------------------------------------------------
def analyze_4h_bias(df4: pd.DataFrame) -> dict:
    """
    Evaluates market structure, 50 EMA, sweeps, and Fair Value Gaps on the 4H timeframe.
    Generates institutional explanation and concrete potential entry and exit levels.
    """
    if len(df4) < 25:
        close_p = df4.iloc[-1]["close"] if not df4.empty else 0.0
        return {
            "bias": "NEUTRAL ⚪",
            "close": close_p,
            "change_pct": 0.0,
            "explanation": "Insufficient historical candles to determine 4H structure.",
            "plan": {
                "type": "WAIT",
                "entry_desc": "Gathering candle data",
                "entry_zone": "N/A",
                "invalidation_sl": "N/A",
                "tp1": "N/A",
                "tp2": "N/A",
            },
        }

    # Evaluate the most recently closed 4H candle
    c_prev = df4.iloc[-3]
    c_curr = df4.iloc[-2]

    close = c_curr["close"]
    prev_close = c_prev["close"]
    change_pct = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

    # 50 EMA on 4H
    ema50 = df4["close"].ewm(span=50, adjust=False).mean().iloc[-2]

    # Lookback window for key structural swings
    lookback = df4.iloc[-30:-2]
    recent_swing_high = lookback["high"].max()
    recent_swing_low = lookback["low"].min()

    # 4H Fair Value Gap check
    c1 = df4.iloc[-4]
    c3 = df4.iloc[-2]
    has_bull_fvg = c3["low"] > c1["high"]
    has_bear_fvg = c3["high"] < c1["low"]

    fvg_low, fvg_high = None, None
    if has_bull_fvg:
        fvg_low, fvg_high = c1["high"], c3["low"]
    elif has_bear_fvg:
        fvg_low, fvg_high = c3["high"], c1["low"]

    # 4H Liquidity Sweep check
    swept_low = c_curr["low"] < recent_swing_low and c_curr["close"] > recent_swing_low
    swept_high = c_curr["high"] > recent_swing_high and c_curr["close"] < recent_swing_high

    # Determine Bias, Narrative Explanation, and Concrete Entries/Exits
    if close > ema50 and (swept_low or c_curr["close"] > c_curr["open"]):
        bias = "BULLISH 🟢"
        explanation = f"Price closed at {format_price(close)} (+{change_pct:.2f}%) holding above 4H 50 EMA ({format_price(ema50)})."
        if swept_low:
            explanation += f" Swept liquidity below prior swing low ({format_price(recent_swing_low)}) with immediate rejection."
        elif has_bull_fvg:
            explanation += f" Strong bullish displacement printed an active 4H Fair Value Gap between {format_price(fvg_low)} and {format_price(fvg_high)}."
        else:
            explanation += " Institutional orderflow remains bullish with buyers defending higher swing lows."

        # Potential Entry Zone
        if has_bull_fvg:
            entry_min, entry_max = fvg_low, fvg_high
            entry_mid = (entry_min + entry_max) / 2.0
            entry_desc = f"Retest of 4H Discount FVG ({format_price(entry_min)}–{format_price(entry_max)}) on 15M bullish rejection"
        else:
            entry_mid = (recent_swing_low + close) / 2.0
            entry_min = min(entry_mid, close * 0.998)
            entry_max = close
            entry_desc = f"15M Pullback Retest Zone ({format_price(entry_min)}–{format_price(entry_max)})"

        # Structural Stop Loss & Targets
        base_low = min(c_curr["low"], c_prev["low"], recent_swing_low, entry_min)
        buffer = 2.0 if close >= 1000 else 0.0015
        sl = base_low - buffer
        risk = abs(entry_mid - sl)
        if risk <= 0:
            risk = close * 0.005
        tp1 = entry_mid + (risk * 1.5)
        tp2 = entry_mid + (risk * 2.5)

        plan = {
            "type": "BUY / LONG",
            "entry_zone": f"{format_price(entry_min)} – {format_price(entry_max)} (Mid: {format_price(entry_mid)})",
            "entry_desc": entry_desc,
            "invalidation_sl": f"{format_price(sl)} (Below 4H swing structural low)",
            "tp1": f"{format_price(tp1)} (1:1.5 R:R — Scale 50% & SL to Breakeven)",
            "tp2": f"{format_price(tp2)} (1:2.5 R:R — Major swing high liquidity)",
        }

    elif close < ema50 and (swept_high or c_curr["close"] < c_curr["open"]):
        bias = "BEARISH 🔴"
        explanation = f"Price closed at {format_price(close)} ({change_pct:.2f}%) below 4H 50 EMA ({format_price(ema50)})."
        if swept_high:
            explanation += f" Swept buy-side liquidity above prior swing high ({format_price(recent_swing_high)}) and rejected downward."
        elif has_bear_fvg:
            explanation += f" Bearish displacement formed an active 4H Fair Value Gap between {format_price(fvg_high)} and {format_price(fvg_low)}."
        else:
            explanation += " Institutional sellers maintain dominance with consecutive lower highs."

        # Potential Entry Zone
        if has_bear_fvg:
            entry_min, entry_max = fvg_low, fvg_high
            entry_mid = (entry_min + entry_max) / 2.0
            entry_desc = f"Retest of 4H Premium FVG ({format_price(entry_min)}–{format_price(entry_max)}) on 15M bearish rejection"
        else:
            entry_mid = (recent_swing_high + close) / 2.0
            entry_min = close
            entry_max = max(entry_mid, close * 1.002)
            entry_desc = f"15M Retracement Zone ({format_price(entry_min)}–{format_price(entry_max)})"

        # Structural Stop Loss & Targets
        base_high = max(c_curr["high"], c_prev["high"], recent_swing_high, entry_max)
        buffer = 2.0 if close >= 1000 else 0.0015
        sl = base_high + buffer
        risk = abs(sl - entry_mid)
        if risk <= 0:
            risk = close * 0.005
        tp1 = entry_mid - (risk * 1.5)
        tp2 = entry_mid - (risk * 2.5)

        plan = {
            "type": "SELL / SHORT",
            "entry_zone": f"{format_price(entry_min)} – {format_price(entry_max)} (Mid: {format_price(entry_mid)})",
            "entry_desc": entry_desc,
            "invalidation_sl": f"{format_price(sl)} (Above 4H swing structural high)",
            "tp1": f"{format_price(tp1)} (1:1.5 R:R — Scale 50% & SL to Breakeven)",
            "tp2": f"{format_price(tp2)} (1:2.5 R:R — Major swing low liquidity)",
        }
    else:
        bias = "NEUTRAL / RANGE ⚪"
        range_size = abs(recent_swing_high - recent_swing_low)
        mid_range = (recent_swing_high + recent_swing_low) / 2.0
        explanation = f"Price closed at {format_price(close)} ({change_pct:+.2f}%) oscillating around 4H 50 EMA ({format_price(ema50)}). Consolidating between Support ({format_price(recent_swing_low)}) and Resistance ({format_price(recent_swing_high)})."

        plan = {
            "type": "RANGE PLAY (Play Extremes)",
            "entry_zone": f"Longs near {format_price(recent_swing_low)} | Shorts near {format_price(recent_swing_high)}",
            "entry_desc": "Wait for 15M liquidity sweep at range extremes before executing",
            "invalidation_sl": f"Long SL below {format_price(recent_swing_low)} | Short SL above {format_price(recent_swing_high)}",
            "tp1": f"{format_price(mid_range)} (50% Equilibrium of Range)",
            "tp2": f"Opposite range edge ({format_price(recent_swing_high)} for Longs / {format_price(recent_swing_low)} for Shorts)",
        }

    return {
        "bias": bias,
        "close": close,
        "change_pct": change_pct,
        "explanation": explanation,
        "plan": plan,
    }


def send_4h_market_update(is_startup: bool = False):
    """
    Assembles and dispatches the comprehensive 4-Hour Market Close & Multi-Asset Briefing.
    Explains 4H market structure and gives concrete potential 15M entries and exits.
    Fires right after each 4H candle closes (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
    """
    global LAST_4H_DISPATCH_TIME
    now_utc = datetime.now(timezone.utc)
    LAST_4H_DISPATCH_TIME = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    next_close = get_next_4h_close_utc()
    countdown = get_time_until_next_4h_close()

    header_title = "INITIAL 4H MARKET BRIEFING" if is_startup else "4-HOUR CANDLE CLOSE & MARKET UPDATE"
    blocks = [
        f"📊 <b>{header_title}</b>\n"
        f"<i>Time: {now_utc.strftime('%H:%M UTC')} • 15M Trade Execution Active</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    ]

    for name, ticker in config.SYMBOLS.items():
        try:
            df4 = fetch_candles(ticker, "4h")
            if df4.empty:
                continue
            res = analyze_4h_bias(df4)
            plan = res["plan"]
            sign = "+" if res["change_pct"] >= 0 else ""

            block = (
                f"<b>{name}:</b> {format_price(res['close'])} ({sign}{res['change_pct']:.2f}%) | <b>{res['bias']}</b>\n"
                f"• <b>Market Context:</b> {res['explanation']}\n"
                f"• <b>🎯 Potential 15M Entries:</b> {plan['entry_zone']}\n"
                f"  <i>Strategy:</i> {plan['entry_desc']}\n"
                f"• <b>🛑 Potential Exits:</b>\n"
                f"  - <i>Invalidation (SL):</i> {plan['invalidation_sl']}\n"
                f"  - <i>Target 1 (TP1):</i> {plan['tp1']}\n"
                f"  - <i>Target 2 (TP2):</i> {plan['tp2']}"
            )
            blocks.append(block)
        except Exception as e:
            print(f"Error compiling 4H update for {name}: {e}")

    blocks.append(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>Next 4H Candle Close:</b> {next_close.strftime('%H:%M UTC')} (in {countdown})\n"
        f"🎯 <i>Bot is actively scanning every closed 15-minute candle to trigger live entries!</i>"
    )

    message = "\n\n".join(blocks)
    send_telegram(message)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📢 4-Hour Market Update sent to Telegram!")


# ---------------------------------------------------------------------------
# 15-Minute Lower Timeframe (LTF) Trade Entry Scanner
# ---------------------------------------------------------------------------
def scan_15m_entry(symbol_name: str, ticker: str, htf_bias_str: str) -> list:
    """
    Scans the 15-minute timeframe for high-probability LDE entries:
    - 15m Liquidity Sweep
    - 15m Displacement
    - 15m Engulfing Confirmation
    - 15m FVG Retest / Limit Entry
    Cross-checks confluence with 4H HTF bias.
    """
    signals = []
    df = fetch_candles(ticker, config.ENTRY_TIMEFRAME)
    if df.empty or len(df) < (config.LOOKBACK_CANDLES + 5):
        return signals

    curr = df.iloc[-2]
    prev = df.iloc[-3]
    candle_time = str(curr.name)
    eval_df = df.iloc[:-1]

    # 1. Bullish Setup on 15m
    if (
        find_liquidity_sweep(eval_df, "buy", lookback=40)
        and has_displacement(eval_df, "buy")
        and is_bullish_engulfing(prev, curr)
    ):
        alert_key = (symbol_name, "15m", candle_time, "BUY")
        if alert_key not in RECENT_ALERTS:
            RECENT_ALERTS.add(alert_key)
            fvg_text = detect_fvg(eval_df, "buy")

            c1 = eval_df.iloc[-3]
            c3 = eval_df.iloc[-1]
            has_fvg = c3["low"] > c1["high"]
            if has_fvg:
                entry = (c1["high"] + c3["low"]) / 2.0
                entry_type = "Limit Entry (50% 15M FVG Retest)"
            else:
                entry = curr["close"]
                entry_type = "Market Close Entry (15M)"

            sl = min(c1["low"], prev["low"], curr["low"])
            risk = abs(entry - sl)
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2.5)

            # Confluence check with 4H Higher Timeframe
            if "BULLISH" in htf_bias_str:
                confluence_badge = "🔥 <b>HIGH CONFLUENCE (4H HTF + 15M ALIGNED)</b>"
            elif "BEARISH" in htf_bias_str:
                confluence_badge = "⚡ <b>15M COUNTER-TREND SCALP (Against 4H Trend)</b>"
            else:
                confluence_badge = "⚪ <b>15M RANGE SETUP (4H Neutral)</b>"

            signals.append(
                f"⚡ <b>LDE 15M TRADE ENTRY ALERT</b>\n\n"
                f"🟢 <b>BUY {symbol_name} (15-Minute Execution)</b>\n"
                f"• {confluence_badge}\n"
                f"• <b>4H HTF Bias:</b> {htf_bias_str}\n"
                f"• <b>Trigger:</b> 15M Sweep ➔ Displacement ➔ Bullish Engulfing{fvg_text}\n"
                f"• <b>{entry_type}:</b> {format_price(entry)}\n"
                f"• <b>Stop Loss:</b> {format_price(sl)} (Risk: {format_price(risk)})\n"
                f"• <b>🎯 TP1 (1:1.5 - Take 50% & SL to BE):</b> {format_price(tp1)}\n"
                f"• <b>🎯 TP2 (1:2.5 - Final Target):</b> {format_price(tp2)}\n"
                f"• <i>Closed 15M Candle:</i> {candle_time}"
            )

    # 2. Bearish Setup on 15m
    if (
        find_liquidity_sweep(eval_df, "sell", lookback=40)
        and has_displacement(eval_df, "sell")
        and is_bearish_engulfing(prev, curr)
    ):
        alert_key = (symbol_name, "15m", candle_time, "SELL")
        if alert_key not in RECENT_ALERTS:
            RECENT_ALERTS.add(alert_key)
            fvg_text = detect_fvg(eval_df, "sell")

            c1 = eval_df.iloc[-3]
            c3 = eval_df.iloc[-1]
            has_fvg = c3["high"] < c1["low"]
            if has_fvg:
                entry = (c1["low"] + c3["high"]) / 2.0
                entry_type = "Limit Entry (50% 15M FVG Retest)"
            else:
                entry = curr["close"]
                entry_type = "Market Close Entry (15M)"

            sl = max(c1["high"], prev["high"], curr["high"])
            risk = abs(sl - entry)
            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2.5)

            # Confluence check with 4H Higher Timeframe
            if "BEARISH" in htf_bias_str:
                confluence_badge = "🔥 <b>HIGH CONFLUENCE (4H HTF + 15M ALIGNED)</b>"
            elif "BULLISH" in htf_bias_str:
                confluence_badge = "⚡ <b>15M COUNTER-TREND SCALP (Against 4H Trend)</b>"
            else:
                confluence_badge = "⚪ <b>15M RANGE SETUP (4H Neutral)</b>"

            signals.append(
                f"⚡ <b>LDE 15M TRADE ENTRY ALERT</b>\n\n"
                f"🔴 <b>SELL {symbol_name} (15-Minute Execution)</b>\n"
                f"• {confluence_badge}\n"
                f"• <b>4H HTF Bias:</b> {htf_bias_str}\n"
                f"• <b>Trigger:</b> 15M Sweep ➔ Displacement ➔ Bearish Engulfing{fvg_text}\n"
                f"• <b>{entry_type}:</b> {format_price(entry)}\n"
                f"• <b>Stop Loss:</b> {format_price(sl)} (Risk: {format_price(risk)})\n"
                f"• <b>🎯 TP1 (1:1.5 - Take 50% & SL to BE):</b> {format_price(tp1)}\n"
                f"• <b>🎯 TP2 (1:2.5 - Final Target):</b> {format_price(tp2)}\n"
                f"• <i>Closed 15M Candle:</i> {candle_time}"
            )

    if len(RECENT_ALERTS) > 1000:
        RECENT_ALERTS.clear()

    return signals


# ---------------------------------------------------------------------------
# Telegram Updates Listener (Processes Button Taps and Commands)
# ---------------------------------------------------------------------------
def handle_telegram_updates():
    """Poll for user button taps and text commands."""
    global LAST_UPDATE_ID
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"

    while True:
        try:
            params = {"timeout": 15, "offset": LAST_UPDATE_ID + 1}
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("result", []):
                    LAST_UPDATE_ID = item["update_id"]

                    if "message" in item:
                        msg = item["message"]
                        text = msg.get("text", "").strip()
                        cmd = text.lower()

                        if "backtest gold" in cmd or cmd in ["/gold", "/backtest"]:
                            send_telegram("⏳ <i>Running Gold (XAUUSD) multi-timeframe backtest... computing win rate and returns...</i>")
                            try:
                                import gold_backtest_telegram
                                report = gold_backtest_telegram.execute_gold_backtest_study()
                                send_telegram(report)
                            except Exception as ex:
                                send_telegram(f"❌ Error during Gold backtest: {ex}")

                        elif "macro news" in cmd or cmd in ["/macronews", "/news"]:
                            try:
                                news_msg = fundamentals.fetch_macro_news(limit=5)
                                send_telegram(f"📰 <b>Latest Macro News:</b>\n{news_msg}")
                            except Exception as e:
                                send_telegram(f"❌ Error fetching macro news: {e}")

                        elif "macro backtest" in cmd or cmd in ["/macrobt", "/macro"]:
                            send_telegram("⏳ <i>Running 10-Year Gold Macro Backtest under CPI, NFP & FOMC news events...</i>")
                            try:
                                import gold_1000_news_backtest
                                gold_1000_news_backtest.compile_and_send_macro_report()
                            except Exception as ex:
                                send_telegram(f"❌ Error during Macro backtest: {ex}")

                        elif "scan market" in cmd or cmd in ["/scan", "scan"]:
                            send_telegram("🔍 <i>Scanning 15-Minute candles across all pairs right now...</i>")
                            run_15m_cycle(is_manual=True)

                        elif "status" in cmd or cmd in ["/status", "status"]:
                            next_close = get_next_4h_close_utc()
                            countdown = get_time_until_next_4h_close()
                            status_msg = (
                                f"<b>📊 LDE Bot Live Status & Timer</b>\n\n"
                                f"• <b>Bot State:</b> 🟢 Running 24/7\n"
                                f"• <b>Update Timer:</b> Every 4 Hours (on 4H candle close)\n"
                                f"• <b>Entry Timeframe:</b> <b>15-Minute (15m TF)</b>\n"
                                f"• <b>Next 4H Candle Close:</b> {next_close.strftime('%H:%M UTC')} (in {countdown})\n"
                                f"• <b>Last 4H Update Dispatched:</b> {LAST_4H_DISPATCH_TIME}\n"
                                f"• <b>15M Scan Cycles Completed:</b> {CYCLE_COUNTER}\n"
                                f"• <b>Monitored Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
                                f"• <b>Current UTC Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            )
                            send_telegram(status_msg)

                        elif cmd in ["/start", "/menu", "menu", "help"]:
                            send_startup_banner()

        except Exception:
            time.sleep(2)

        time.sleep(1)


# ---------------------------------------------------------------------------
# Scanner Execution Loop
# ---------------------------------------------------------------------------
def run_15m_cycle(is_manual: bool = False):
    """
    Executes a 15-minute entry scan across all pairs.
    If valid 15m setups exist, dispatches entry alerts immediately.
    """
    global CYCLE_COUNTER
    CYCLE_COUNTER += 1

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] Cycle #{CYCLE_COUNTER}: Scanning 15m candles for {len(config.SYMBOLS)} pairs...")
    all_signals = []

    for name, ticker in config.SYMBOLS.items():
        try:
            # 1. Fetch 4H HTF bias
            df4 = fetch_candles(ticker, "4h")
            htf_bias = analyze_4h_bias(df4)["bias"] if not df4.empty else "NEUTRAL ⚪"

            # 2. Scan 15m for entries
            sigs = scan_15m_entry(name, ticker, htf_bias)
            if sigs:
                all_signals.extend(sigs)
        except Exception as e:
            print(f"Error scanning {name} ({ticker}): {e}")

    if all_signals:
        for sig in all_signals:
            send_telegram(sig)
        print(f"[{now_str}] 🚨 Dispatched {len(all_signals)} 15M entry alert(s)!")
    elif is_manual:
        countdown = get_time_until_next_4h_close()
        manual_msg = (
            f"🔍 <b>15-Minute Scan Complete (Manual Check)</b>\n\n"
            f"• <b>Checked:</b> {len(config.SYMBOLS)} pairs on 15m TF\n"
            f"• <b>Result:</b> No trigger criteria reached on recent closed 15m candles.\n"
            f"• <b>Next 4H Update:</b> In {countdown}"
        )
        send_telegram(manual_msg)


def main():
    global LAST_4H_SLOT
    parser = argparse.ArgumentParser(description="LDE Signal Scanner Bot & Interactive Controller")
    parser.add_argument("--test", action="store_true", help="Send menu and test message")
    parser.add_argument("--once", action="store_true", help="Run a single scan iteration and exit")
    args = parser.parse_args()

    if args.test:
        send_startup_banner()
        return

    print("=" * 65)
    print("  [>] LDE SIGNAL BOT & TELEGRAM CONTROLLER ACTIVE")
    print(f"  Pairs: {', '.join(config.SYMBOLS.keys())}")
    print(f"  Higher Timeframe (HTF): 4H (4-Hour Candle Close Updates)")
    print(f"  Execution Timeframe (LTF): 15m (Real-time Trade Entry Signals)")
    print(f"  Periodic Updates: Every 4 hours on candle close")
    print("=" * 65)

    # Start Telegram Listener Thread for mobile button interactions
    listener_thread = threading.Thread(target=handle_telegram_updates, daemon=True)
    listener_thread.start()
    print("  [✓] Interactive Telegram Button Listener running.")

    # Send startup welcome banner with persistent keyboard
    send_startup_banner()

    # Dispatch initial 4H market overview so user has immediate briefing
    LAST_4H_SLOT = get_current_4h_slot_key()
    send_4h_market_update(is_startup=True)

    if args.once:
        run_15m_cycle(is_manual=True)
        return

    while True:
        try:
            # 1. Check if a 4-hour candle has closed
            current_slot = get_current_4h_slot_key()
            if current_slot != LAST_4H_SLOT:
                print(f"\n[>] 4-Hour Candle Close detected for slot {current_slot}! Dispatching 4H market update...")
                send_4h_market_update()
                LAST_4H_SLOT = current_slot

            # 2. Run 15m entry scan across all pairs
            run_15m_cycle()

        except KeyboardInterrupt:
            print("\nBot stopped by user.")
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected cycle error: {e}")

        # Sleep scan interval before checking next closed 15m candle
        time.sleep(config.SCAN_INTERVAL)


if __name__ == "__main__":
    main()
