"""
Axiory Advanced Price Action Signal Bot & Telegram Controller
Based on: Axiory Advanced Price Action Guide

Architecture:
- Higher Timeframe (4H):
  * Pure Market Structure via Swing Highs & Lows (HH, HL, LH, LL) — NO lagging indicators
  * Active Impulse Legs & 50.0% - 61.8% Fibonacci Golden Zone
  * Break of Structure (BOS) Trend Reversals & Trendline 3rd-Point Touches
  * Dispatches comprehensive multi-pair market update after every 4-hour candle close
- Execution Timeframe (15m):
  * Continuous real-time scanning on closed 15m candles
  * Checks for retracement pullbacks into the 4H 50%–61.8% Golden Zone / Trendline
  * Requires completed Candlestick Rejection confirmation:
    - Bullish / Bearish Pin Bar (Hammer / Shooting Star)
    - Bullish / Bearish Engulfing
    - Morning Star / Evening Star
  * Strict Risk Management: Stop Loss beyond rejection wick, TP1 (1:1.5R - 50% take & BE), TP2 (1:3.0R target)
- Mobile Interactive Telegram Controller:
  * Persistent phone buttons for scans, market structure, active Fib zones, and bot status.
"""

import sys
import time
import threading
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd
import requests
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
    """Returns the UTC datetime of the next 4-hour candle close (00, 04, 08, 12, 16, 20 UTC)."""
    now = datetime.now(timezone.utc)
    curr_hour = now.hour
    next_hour = ((curr_hour // 4) + 1) * 4
    if next_hour >= 24:
        next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        next_close = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    return next_close


def get_time_until_next_4h_close() -> str:
    """Returns human-readable countdown to next 4H candle close."""
    now = datetime.now(timezone.utc)
    target = get_next_4h_close_utc()
    delta = target - now
    total_seconds = max(0, int(delta.total_seconds()))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def get_current_4h_slot_key() -> str:
    """Returns a unique string for the current completed 4H slot, e.g. '2026-10-16-08'."""
    now = datetime.now(timezone.utc)
    slot_hour = (now.hour // 4) * 4
    return f"{now.strftime('%Y-%m-%d')}-{slot_hour:02d}"


# ---------------------------------------------------------------------------
# Telegram API Helpers with Persistent Phone Keyboard
# ---------------------------------------------------------------------------
def get_persistent_keyboard() -> dict:
    """Returns persistent phone reply keyboard at bottom of screen."""
    return {
        "keyboard": [
            [
                {"text": "🔍 Scan 15M Entries"},
                {"text": "📊 4H Market Structure"},
            ],
            [
                {"text": "📐 Active Fib Zones"},
                {"text": "📰 Macro News"},
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

    # Chunk message if needed
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
    """Send startup banner detailing the Axiory Price Action strategy and buttons."""
    next_close = get_next_4h_close_utc()
    countdown = get_time_until_next_4h_close()
    msg = (
        f"🟢 <b>AXIORY PRICE ACTION SIGNAL BOT IS LIVE!</b>\n\n"
        f"• <b>Core Methodology:</b> Pure Price Action (Axiory Advanced Guide)\n"
        f"• <b>Higher Timeframe (4H):</b> Market Structure (HH, HL, LH, LL) & 50%–61.8% Fib Zones\n"
        f"• <b>Execution Timeframe (15m):</b> Pin Bar, Engulfing, & Morning/Evening Star Rejections\n"
        f"• <b>Risk/Reward Ratio:</b> 1:1.5 (TP1 scale 50% & BE) ➔ <b>1:3.0+ (TP2 Target)</b>\n"
        f"• <b>No Lagging Indicators:</b> 100% Raw Price Action\n"
        f"• <b>Next 4H Candle Close:</b> {next_close.strftime('%H:%M UTC')} (in {countdown})\n"
        f"• <b>Monitored Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n\n"
        f"📱 <i>Control buttons are pinned below! Tap any button anytime from your phone.</i>"
    )
    return send_telegram(msg, with_keyboard=True)


# ---------------------------------------------------------------------------
# Data Fetching & Caching (Twelve Data API with Rate Limiting)
# ---------------------------------------------------------------------------
HTF_CACHE: Dict[str, dict] = {}
LAST_API_CALL_TIME = 0.0


def fetch_candles(ticker: str, interval: str) -> pd.DataFrame:
    """Fetch recent historical candles from Twelve Data REST API with polite rate pacing."""
    global LAST_API_CALL_TIME

    # Respect Twelve Data free tier limits: pace calls by at least 1.5 seconds
    elapsed = time.time() - LAST_API_CALL_TIME
    if elapsed < 1.5:
        time.sleep(1.5 - elapsed)

    outputsize = config.TWELVEDATA_OUTPUTSIZE.get(interval, 200)
    params = {
        "symbol": ticker,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": config.TWELVEDATA_API_KEY,
        "timezone": "UTC",
    }

    data = None
    for attempt in range(2):
        try:
            LAST_API_CALL_TIME = time.time()
            resp = requests.get(
                "https://api.twelvedata.com/time_series",
                params=params,
                timeout=30,
            )
            if resp.status_code == 429:
                print(f"Rate limited (429) for {ticker}. Waiting 8s before retry...")
                time.sleep(8)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
            else:
                print(f"Error fetching {ticker} ({interval}): {e}")
                return pd.DataFrame()

    if not data or data.get("status") == "error" or "values" not in data:
        msg = data.get("message", "Unknown error") if data else "No response"
        print(f"Twelve Data error for {ticker} ({interval}): {msg}")
        return pd.DataFrame()

    df = pd.DataFrame(data["values"])
    if df.empty:
        return pd.DataFrame()

    # Convert types
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("datetime").set_index("datetime")
    df = df[["open", "high", "low", "close"]].dropna()
    return df


def format_price(val: float) -> str:
    """Formats price based on scale (forex pips vs crypto/metals)."""
    if val >= 1000:
        return f"{val:,.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    else:
        return f"{val:.6f}"


# ---------------------------------------------------------------------------
# Pure Price Action Engine: Swing Points & Market Structure (HH, HL, LH, LL)
# ---------------------------------------------------------------------------
class SwingPoint:
    def __init__(self, index: int, time: str, price: float, swing_type: str):
        self.index = index
        self.time = time
        self.price = price
        self.swing_type = swing_type  # "HIGH" or "LOW"
        self.label = ""               # "HH", "LH", "HL", "LL"


def find_swing_points(df: pd.DataFrame, order: int = 3) -> List[SwingPoint]:
    """
    Identifies fractal swing highs and swing lows using an N-bar local extrema window.
    Compares consecutive pivots to classify Higher Highs (HH), Lower Highs (LH),
    Higher Lows (HL), and Lower Lows (LL).
    """
    if len(df) < (order * 2 + 5):
        return []

    highs = df["high"].values
    lows = df["low"].values
    times = df.index
    swings: List[SwingPoint] = []

    # Search for confirmed local extrema (leaving 'order' candles on right side)
    for i in range(order, len(df) - order):
        curr_high = highs[i]
        curr_low = lows[i]

        # 1. Swing High Check
        is_high = True
        for o in range(1, order + 1):
            if curr_high <= highs[i - o] or curr_high <= highs[i + o]:
                is_high = False
                break
        if is_high:
            swings.append(SwingPoint(i, str(times[i]), float(curr_high), "HIGH"))

        # 2. Swing Low Check
        is_low = True
        for o in range(1, order + 1):
            if curr_low >= lows[i - o] or curr_low >= lows[i + o]:
                is_low = False
                break
        if is_low:
            swings.append(SwingPoint(i, str(times[i]), float(curr_low), "LOW"))

    swings.sort(key=lambda s: s.index)

    # Classify consecutive Highs and Lows
    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None

    for s in swings:
        if s.swing_type == "HIGH":
            if last_high is not None:
                s.label = "HH" if s.price > last_high.price else "LH"
            else:
                s.label = "HIGH"
            last_high = s
        elif s.swing_type == "LOW":
            if last_low is not None:
                s.label = "HL" if s.price > last_low.price else "LL"
            else:
                s.label = "LOW"
            last_low = s

    return swings


# ---------------------------------------------------------------------------
# Fibonacci Retracement Calculator (Chapter 6 — Pages 16–19)
# ---------------------------------------------------------------------------
def calculate_fibonacci_levels(swing_low: float, swing_high: float, trend: str) -> dict:
    """
    Calculates Fibonacci Retracement levels from the active impulse leg:
    - 38.2% minor retracement
    - 50.0% & 61.8% Golden Retracement Entry Zone
    - 100.0% structural invalidation level
    """
    range_span = swing_high - swing_low
    if range_span <= 0:
        return {}

    if "BULLISH" in trend:
        # Pullback downward into discount zone
        fib50 = swing_high - (range_span * config.FIB_ENTRY_50)
        fib618 = swing_high - (range_span * config.FIB_ENTRY_618)
        return {
            "peak": swing_high,
            "fib382": swing_high - (range_span * config.FIB_LEVEL_382),
            "fib50": fib50,
            "fib618": fib618,
            "invalidation": swing_low,
            "zone_top": fib50,
            "zone_bottom": fib618,
        }
    else:
        # Pullback upward into premium zone
        fib50 = swing_low + (range_span * config.FIB_ENTRY_50)
        fib618 = swing_low + (range_span * config.FIB_ENTRY_618)
        return {
            "trough": swing_low,
            "fib382": swing_low + (range_span * config.FIB_LEVEL_382),
            "fib50": fib50,
            "fib618": fib618,
            "invalidation": swing_high,
            "zone_bottom": fib50,
            "zone_top": fib618,
        }


# ---------------------------------------------------------------------------
# Trendline 3rd-Point Projection (Chapter 3 — Pages 7–8)
# ---------------------------------------------------------------------------
def calculate_trendline_3rd_point(swings: List[SwingPoint], trend: str, curr_index: int) -> Optional[float]:
    """
    Calculates projected 3rd touch level by projecting a line across the last 2 confirmed swing points.
    Formula: y = y1 + slope * (x - x1)
    """
    if "BULLISH" in trend:
        lows = [s for s in swings if s.swing_type == "LOW"]
        if len(lows) < 2:
            return None
        p1, p2 = lows[-2], lows[-1]
        dx = p2.index - p1.index
        if dx <= 0:
            return None
        slope = (p2.price - p1.price) / dx
        return p2.price + slope * (curr_index - p2.index)
    elif "BEARISH" in trend:
        highs = [s for s in swings if s.swing_type == "HIGH"]
        if len(highs) < 2:
            return None
        p1, p2 = highs[-2], highs[-1]
        dx = p2.index - p1.index
        if dx <= 0:
            return None
        slope = (p2.price - p1.price) / dx
        return p2.price + slope * (curr_index - p2.index)
    return None


# ---------------------------------------------------------------------------
# Higher Timeframe (4H) Market Structure Analysis
# ---------------------------------------------------------------------------
def analyze_4h_bias(df4: pd.DataFrame) -> dict:
    """
    Evaluates 4H pure price action structure:
    1. Swing Points (HH, HL, LH, LL)
    2. Trend State: BULLISH, BEARISH, BOS REVERSAL, or RANGING
    3. Active Fibonacci 50%–61.8% Golden Zone
    4. Trendline 3rd Point level
    """
    if len(df4) < 25:
        close_p = df4.iloc[-1]["close"] if not df4.empty else 0.0
        return {
            "bias": "NEUTRAL ⚪",
            "close": close_p,
            "change_pct": 0.0,
            "explanation": "Gathering historical candles for structure mapping.",
            "fibs": {},
            "trendline_level": None,
            "plan": {"type": "WAIT", "entry_zone": "N/A", "invalidation_sl": "N/A", "tp1": "N/A", "tp2": "N/A"}
        }

    c_prev = df4.iloc[-3]
    c_curr = df4.iloc[-2]
    current_close = c_curr["close"]
    prev_close = c_prev["close"]
    change_pct = ((current_close - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

    swings = find_swing_points(df4, order=config.SWING_ORDER)
    highs = [s for s in swings if s.swing_type == "HIGH"]
    lows = [s for s in swings if s.swing_type == "LOW"]

    if len(highs) < 2 or len(lows) < 2:
        return {
            "bias": "NEUTRAL ⚪",
            "close": current_close,
            "change_pct": change_pct,
            "explanation": "Establishing initial market structure swing points.",
            "fibs": {},
            "trendline_level": None,
            "plan": {"type": "WAIT", "entry_zone": "N/A", "invalidation_sl": "N/A", "tp1": "N/A", "tp2": "N/A"}
        }

    latest_h = highs[-1]
    latest_l = lows[-1]

    # Check for Break of Structure (BOS - Reversal Trading from Page 11-12)
    is_bos_bearish = (latest_h.label == "HH") and (current_close < latest_l.price)
    is_bos_bullish = (latest_l.label == "LL") and (current_close > latest_h.price)

    # Standard Structural Trend with Chronological Impulse Verification
    is_bullish = (latest_h.label == "HH" and latest_l.label == "HL" and latest_h.index > latest_l.index)
    is_bearish = (latest_h.label == "LH" and latest_l.label == "LL" and latest_l.index > latest_h.index)

    # 100 SMA Macro Trend Alignment (Chapter 5 Axiory Guide)
    if config.USE_100_SMA_FILTER and len(df4) >= 100:
        sma100 = df4["close"].rolling(window=100).mean().iloc[-2]
        if is_bullish and current_close < sma100:
            is_bullish = False
        elif is_bearish and current_close > sma100:
            is_bearish = False

    if is_bos_bearish:
        bias = "REVERSAL_BEARISH_BOS ⚠️"
        explanation = f"Uptrend broken: Price closed below previous Higher Low ({format_price(latest_l.price)})."
        fibs = calculate_fibonacci_levels(current_close, latest_h.price, "BEARISH")
    elif is_bos_bullish:
        bias = "REVERSAL_BULLISH_BOS ⚠️"
        explanation = f"Downtrend broken: Price closed above previous Lower High ({format_price(latest_h.price)})."
        fibs = calculate_fibonacci_levels(latest_l.price, current_close, "BULLISH")
    elif is_bullish:
        bias = "BULLISH 🟢"
        explanation = f"Uptrend active: Making Higher Highs ({format_price(latest_h.price)}) & Higher Lows ({format_price(latest_l.price)})."
        fibs = calculate_fibonacci_levels(latest_l.price, latest_h.price, "BULLISH")
    elif is_bearish:
        bias = "BEARISH 🔴"
        explanation = f"Downtrend active: Making Lower Highs ({format_price(latest_h.price)}) & Lower Lows ({format_price(latest_l.price)})."
        fibs = calculate_fibonacci_levels(latest_l.price, latest_h.price, "BEARISH")
    else:
        bias = "RANGING ⚪"
        explanation = f"Consolidating between Swing High ({format_price(latest_h.price)}) & Swing Low ({format_price(latest_l.price)})."
        fibs = calculate_fibonacci_levels(latest_l.price, latest_h.price, "BULLISH")

    # Trendline 3rd Point
    tl_level = calculate_trendline_3rd_point(swings, bias, len(df4) - 2)

    # Build Plan
    plan = {}
    if "BULLISH" in bias and fibs:
        entry_mid = (fibs["zone_top"] + fibs["zone_bottom"]) / 2.0
        buffer = 2.0 if current_close >= 1000 else 0.0010
        sl = fibs["invalidation"] - buffer
        risk = max(entry_mid - sl, current_close * 0.004)
        tp1 = entry_mid + (risk * config.TP1_RR)
        tp2 = entry_mid + (risk * config.TP2_RR)

        plan = {
            "type": "BUY / LONG",
            "entry_zone": f"{format_price(fibs['zone_bottom'])} – {format_price(fibs['zone_top'])} (50%–61.8% Golden Fib)",
            "invalidation_sl": f"{format_price(sl)} (Below Swing Low)",
            "tp1": f"{format_price(tp1)} (1:{config.TP1_RR} R:R — Scale 50% & SL to BE)",
            "tp2": f"{format_price(tp2)} (1:{config.TP2_RR} R:R — Full Target)",
        }
    elif "BEARISH" in bias and fibs:
        entry_mid = (fibs["zone_top"] + fibs["zone_bottom"]) / 2.0
        buffer = 2.0 if current_close >= 1000 else 0.0010
        sl = fibs["invalidation"] + buffer
        risk = max(sl - entry_mid, current_close * 0.004)
        tp1 = entry_mid - (risk * config.TP1_RR)
        tp2 = entry_mid - (risk * config.TP2_RR)

        plan = {
            "type": "SELL / SHORT",
            "entry_zone": f"{format_price(fibs['zone_bottom'])} – {format_price(fibs['zone_top'])} (50%–61.8% Golden Fib)",
            "invalidation_sl": f"{format_price(sl)} (Above Swing High)",
            "tp1": f"{format_price(tp1)} (1:{config.TP1_RR} R:R — Scale 50% & SL to BE)",
            "tp2": f"{format_price(tp2)} (1:{config.TP2_RR} R:R — Full Target)",
        }
    else:
        plan = {
            "type": "WAIT / RANGE",
            "entry_zone": "Wait for breakout or clean pullback",
            "invalidation_sl": "N/A",
            "tp1": "N/A",
            "tp2": "N/A",
        }

    return {
        "bias": bias,
        "close": current_close,
        "change_pct": change_pct,
        "explanation": explanation,
        "latest_high": latest_h,
        "latest_low": latest_l,
        "fibs": fibs,
        "trendline_level": tl_level,
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# Candlestick Confirmation Triggers (Chapter 9 Cheat Sheet)
# ---------------------------------------------------------------------------
def detect_candlestick_trigger(eval_df: pd.DataFrame, trend_bias: str) -> Optional[Dict[str, Any]]:
    """
    Evaluates completed candles for price action triggers:
    - Pin Bar / Hammer (Bullish rejection) / Shooting Star (Bearish rejection)
    - Bullish / Bearish Engulfing
    - Morning Star (Bullish bottom reversal) / Evening Star (Bearish top reversal)
    """
    if len(eval_df) < 4:
        return None

    curr = eval_df.iloc[-1]
    prev = eval_df.iloc[-2]
    prev2 = eval_df.iloc[-3]

    curr_range = curr["high"] - curr["low"]
    if curr_range <= 0:
        return None

    curr_body = abs(curr["close"] - curr["open"])
    curr_upper_wick = curr["high"] - max(curr["open"], curr["close"])
    curr_lower_wick = min(curr["open"], curr["close"]) - curr["low"]

    # 1. Bullish Triggers
    if "BULLISH" in trend_bias:
        # A. Bullish Pin Bar (Hammer)
        is_bull_pin = (
            curr_lower_wick >= (2.0 * curr_body)
            and curr_lower_wick >= (0.50 * curr_range)
            and curr_upper_wick <= (0.25 * curr_range)
            and curr["close"] >= curr["open"]
        )
        if is_bull_pin:
            return {
                "signal": "BUY",
                "pattern": "Bullish Pin Bar / Hammer",
                "entry": curr["close"],
                "sl": curr["low"],
                "detail": f"Lower wick rejected downward pressure (wick: {format_price(curr_lower_wick)})",
            }

        # B. Bullish Engulfing (High-Conviction Body Expansion)
        prev_bearish = prev["close"] < prev["open"]
        curr_bullish = curr["close"] > curr["open"]
        if prev_bearish and curr_bullish and curr["close"] >= prev["high"] and curr_body >= (0.55 * curr_range):
            return {
                "signal": "BUY",
                "pattern": "Bullish Engulfing",
                "entry": curr["close"],
                "sl": min(curr["low"], prev["low"]),
                "detail": "Bullish body fully engulfed prior candle high with strong expansion",
            }

        # C. Morning Star (3-Candle Reversal)
        c1_bearish = prev2["close"] < prev2["open"]
        c1_body = abs(prev2["open"] - prev2["close"])
        c2_body = abs(prev["close"] - prev["open"])
        c2_range = prev["high"] - prev["low"]
        c2_small = c2_range > 0 and (c2_body / c2_range) <= 0.35
        c3_bullish = curr["close"] > curr["open"]
        c3_penetrates = curr["close"] >= (prev2["close"] + 0.50 * c1_body)

        if c1_bearish and c2_small and c3_bullish and c3_penetrates and c1_body > 0:
            return {
                "signal": "BUY",
                "pattern": "Morning Star (3-Candle Reversal)",
                "entry": curr["close"],
                "sl": min(curr["low"], prev["low"], prev2["low"]),
                "detail": "3-candle morning star completed with strong green close",
            }

    # 2. Bearish Triggers
    elif "BEARISH" in trend_bias:
        # A. Bearish Pin Bar (Shooting Star)
        is_bear_pin = (
            curr_upper_wick >= (2.0 * curr_body)
            and curr_upper_wick >= (0.50 * curr_range)
            and curr_lower_wick <= (0.25 * curr_range)
            and curr["close"] <= curr["open"]
        )
        if is_bear_pin:
            return {
                "signal": "SELL",
                "pattern": "Bearish Pin Bar / Shooting Star",
                "entry": curr["close"],
                "sl": curr["high"],
                "detail": f"Upper wick rejected upward pressure (wick: {format_price(curr_upper_wick)})",
            }

        # B. Bearish Engulfing (High-Conviction Body Expansion)
        prev_bullish = prev["close"] > prev["open"]
        curr_bearish = curr["close"] < curr["open"]
        if prev_bullish and curr_bearish and curr["close"] <= prev["low"] and curr_body >= (0.55 * curr_range):
            return {
                "signal": "SELL",
                "pattern": "Bearish Engulfing",
                "entry": curr["close"],
                "sl": max(curr["high"], prev["high"]),
                "detail": "Bearish body fully engulfed prior candle low with strong expansion",
            }

        # C. Evening Star (3-Candle Reversal)
        c1_bullish = prev2["close"] > prev2["open"]
        c1_body = abs(prev2["open"] - prev2["close"])
        c2_body = abs(prev["close"] - prev["open"])
        c2_range = prev["high"] - prev["low"]
        c2_small = c2_range > 0 and (c2_body / c2_range) <= 0.35
        c3_bearish = curr["close"] < curr["open"]
        c3_penetrates = curr["close"] <= (prev2["close"] - 0.50 * c1_body)

        if c1_bullish and c2_small and c3_bearish and c3_penetrates and c1_body > 0:
            return {
                "signal": "SELL",
                "pattern": "Evening Star (3-Candle Reversal)",
                "entry": curr["close"],
                "sl": max(curr["high"], prev["high"], prev2["high"]),
                "detail": "3-candle evening star completed with strong red close",
            }

    return None


# ---------------------------------------------------------------------------
# 4-Hour Market Update Dispatcher
# ---------------------------------------------------------------------------
def send_4h_market_update(is_startup: bool = False):
    """Compiles and broadcasts the 4H market structure and Fibonacci overview."""
    global LAST_4H_DISPATCH_TIME
    now_utc = datetime.now(timezone.utc)
    LAST_4H_DISPATCH_TIME = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    header_title = "INITIAL 4H MARKET BRIEFING" if is_startup else "4-HOUR CANDLE CLOSE & MARKET UPDATE"
    blocks = [
        f"📊 <b>{header_title}</b>\n"
        f"<i>Time: {now_utc.strftime('%H:%M UTC')} • Axiory Price Action Strategy</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    ]

    for name, ticker in config.SYMBOLS.items():
        try:
            df4 = fetch_candles(ticker, "4h")
            if df4.empty:
                continue
            res = analyze_4h_bias(df4)
            HTF_CACHE[ticker] = res  # Cache 4H analysis
            plan = res["plan"]
            sign = "+" if res["change_pct"] >= 0 else ""

            fib_info = ""
            if res.get("fibs"):
                f = res["fibs"]
                fib_info = (
                    f"\n• <b>📐 4H Golden Fib Zone:</b> {format_price(f['zone_bottom'])} – {format_price(f['zone_top'])}\n"
                    f"  - <i>38.2% Minor:</i> {format_price(f['fib382'])}\n"
                    f"  - <i>Invalidation:</i> {format_price(f['invalidation'])}"
                )

            tl_info = ""
            if res.get("trendline_level"):
                tl_info = f"\n• <b>📈 3rd-Point Trendline:</b> {format_price(res['trendline_level'])}"

            block = (
                f"<b>{name}:</b> {format_price(res['close'])} ({sign}{res['change_pct']:.2f}%) | <b>{res['bias']}</b>\n"
                f"• <b>Market Structure:</b> {res['explanation']}"
                f"{fib_info}"
                f"{tl_info}\n"
                f"• <b>🎯 Planned Setup:</b> {plan['entry_zone']}\n"
                f"  - <i>Invalidation (SL):</i> {plan['invalidation_sl']}\n"
                f"  - <i>Target 1 (TP1):</i> {plan['tp1']}\n"
                f"  - <i>Target 2 (TP2):</i> {plan['tp2']}"
            )
            blocks.append(block)
        except Exception as e:
            print(f"Error compiling 4H update for {name}: {e}")

    countdown = get_time_until_next_4h_close()
    blocks.append(f"━━━━━━━━━━━━━━━━━━━━\n⏳ <b>Next 4H Candle Close:</b> In {countdown}")
    full_msg = "\n\n".join(blocks)
    send_telegram(full_msg, with_keyboard=True)


# ---------------------------------------------------------------------------
# 15-Minute Entry Execution Scanner
# ---------------------------------------------------------------------------
def scan_15m_entry(symbol_name: str, ticker: str, htf_analysis: dict) -> list:
    """
    Scans the 15-minute timeframe for high-probability Axiory Price Action entries:
    - Retracement pullback into the 4H 50%–61.8% Golden Zone or 3rd Trendline touch
    - Candlestick Rejection Trigger (Pin Bar, Engulfing, Morning/Evening Star)
    - 1:3+ Risk/Reward management
    """
    signals = []
    df = fetch_candles(ticker, config.ENTRY_TIMEFRAME)
    if df.empty or len(df) < 15:
        return signals

    # Evaluate the most recently completed candle
    curr = df.iloc[-2]
    candle_time = curr.name

    # Hard age filter — ignore candles older than ~25 minutes
    now = datetime.now(timezone.utc)
    if candle_time.tzinfo is None:
        candle_time = candle_time.tz_localize("UTC")
    if (now - candle_time) > timedelta(minutes=25):
        return signals

    eval_df = df.iloc[:-1]
    bias = htf_analysis.get("bias", "NEUTRAL ⚪")
    fibs = htf_analysis.get("fibs", {})
    tl_level = htf_analysis.get("trendline_level")

    # Check if price touched the Golden Zone or Trendline
    in_fib_zone = False
    if fibs:
        c_low = curr["low"]
        c_high = curr["high"]
        zone_top = max(fibs["zone_top"], fibs["zone_bottom"])
        zone_bottom = min(fibs["zone_top"], fibs["zone_bottom"])
        in_fib_zone = (c_low <= zone_top) and (c_high >= zone_bottom)

    near_trendline = False
    if tl_level:
        tol = curr["close"] * 0.0015
        near_trendline = abs(curr["low"] - tl_level) <= tol or abs(curr["high"] - tl_level) <= tol

    # Must be reacting at a key level (Fib Zone or Trendline)
    if not (in_fib_zone or near_trendline):
        return signals

    # Candlestick Confirmation Trigger
    trigger = detect_candlestick_trigger(eval_df, bias)
    if not trigger:
        return signals

    alert_direction = trigger["signal"]
    alert_key = (symbol_name, "15m", str(candle_time), alert_direction)
    if alert_key in RECENT_ALERTS:
        return signals

    RECENT_ALERTS.add(alert_key)
    if len(RECENT_ALERTS) > 1000:
        RECENT_ALERTS.clear()

    # Entry Price & Order Type (Pending Limit 50% Retest vs Market)
    if config.ENTRY_MODE == "LIMIT_50_RETEST":
        entry = (curr["high"] + curr["low"]) / 2.0
        entry_label = "Pending Limit Entry (50% Retest)"
    else:
        entry = trigger["entry"]
        entry_label = "Market Entry"

    sl = trigger["sl"]

    # Dynamic volatility buffer (0.15% of price)
    buffer = max(entry * 0.0015, 0.0006)
    if alert_direction == "BUY":
        sl = sl - buffer
        risk = abs(entry - sl)
        tp1 = entry + (risk * config.TP1_RR)
        tp2 = entry + (risk * config.TP2_RR)
        badge = "🟢 <b>BUY / LONG</b>"
    else:
        sl = sl + buffer
        risk = abs(sl - entry)
        tp1 = entry - (risk * config.TP1_RR)
        tp2 = entry - (risk * config.TP2_RR)
        badge = "🔴 <b>SELL / SHORT</b>"

    zone_label = "50%–61.8% Golden Fib Zone" if in_fib_zone else "3rd-Point Trendline Support/Resistance"

    scale_pct = int(config.SCALE_TP1_RATIO * 100)
    alert_text = (
        f"{config.SIGNAL_PREFIX}\n\n"
        f"{badge} <b>{symbol_name} (15M Execution)</b>\n"
        f"• <b>4H Trend Bias:</b> {bias}\n"
        f"• <b>Confluence Zone:</b> {zone_label}\n"
        f"• <b>Candlestick Trigger:</b> {trigger['pattern']}\n"
        f"  <i>Confirmation Detail:</i> {trigger['detail']}\n\n"
        f"• <b>{entry_label}:</b> {format_price(entry)}\n"
        f"• <b>Stop Loss:</b> {format_price(sl)} (Risk: {format_price(risk)})\n"
        f"• <b>🎯 TP1 (1:{config.TP1_RR} — Scale {scale_pct}% & SL to BE):</b> {format_price(tp1)}\n"
        f"• <b>🎯 TP2 (1:{config.TP2_RR} — Final Target):</b> {format_price(tp2)}\n"
        f"• <i>Closed 15M Candle:</i> {candle_time}"
    )
    signals.append(alert_text)
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

                        if "scan 15m" in cmd or cmd in ["/scan", "scan"]:
                            send_telegram("🔍 <i>Scanning 15-Minute candles for Golden Fib & Candlestick triggers...</i>")
                            run_15m_cycle(is_manual=True)

                        elif "4h market structure" in cmd or cmd in ["/structure", "structure"]:
                            send_telegram("📊 <i>Compiling 4H pure market structure analysis across all pairs...</i>")
                            send_4h_market_update()

                        elif "active fib zones" in cmd or cmd in ["/fibs", "fibs"]:
                            fib_report = ["📐 <b>Active 4H Fibonacci Golden Zones (50%–61.8%)</b>\n━━━━━━━━━━━━━━━━━━━━"]
                            for name, ticker in config.SYMBOLS.items():
                                df4 = fetch_candles(ticker, "4h")
                                if not df4.empty:
                                    res = analyze_4h_bias(df4)
                                    f = res.get("fibs", {})
                                    if f:
                                        fib_report.append(
                                            f"<b>{name}:</b> {res['bias']}\n"
                                            f"• <i>50%–61.8% Zone:</i> {format_price(f['zone_bottom'])} – {format_price(f['zone_top'])}\n"
                                            f"• <i>Current Price:</i> {format_price(res['close'])}"
                                        )
                            send_telegram("\n\n".join(fib_report))

                        elif "macro news" in cmd or cmd in ["/news", "news"]:
                            try:
                                news_msg = fundamentals.fetch_macro_news(limit=5)
                                send_telegram(f"📰 <b>Latest Macro News:</b>\n{news_msg}")
                            except Exception as e:
                                send_telegram(f"❌ Error fetching macro news: {e}")

                        elif "status" in cmd or cmd in ["/status", "status"]:
                            next_close = get_next_4h_close_utc()
                            countdown = get_time_until_next_4h_close()
                            status_msg = (
                                f"<b>📊 Axiory Price Action Bot Status</b>\n\n"
                                f"• <b>State:</b> 🟢 Running 24/7\n"
                                f"• <b>Strategy:</b> Pure Price Action (Market Structure + Fibs)\n"
                                f"• <b>HTF Schedule:</b> Every 4 Hours on Candle Close\n"
                                f"• <b>LTF Scanner:</b> 15-Minute Candles (Every {config.SCAN_INTERVAL}s)\n"
                                f"• <b>Next 4H Candle Close:</b> {next_close.strftime('%H:%M UTC')} (in {countdown})\n"
                                f"• <b>Last 4H Dispatch:</b> {LAST_4H_DISPATCH_TIME}\n"
                                f"• <b>15M Cycles Completed:</b> {CYCLE_COUNTER}\n"
                                f"• <b>Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
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
    """Executes a 15-minute entry scan across all pairs."""
    global CYCLE_COUNTER
    CYCLE_COUNTER += 1

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] Cycle #{CYCLE_COUNTER}: Scanning 15m candles for {len(config.SYMBOLS)} pairs...")
    all_signals = []

    for name, ticker in config.SYMBOLS.items():
        try:
            # 1. Use cached 4H HTF structure (refreshed on 4H candle close)
            htf_analysis = HTF_CACHE.get(ticker)
            if not htf_analysis:
                df4 = fetch_candles(ticker, "4h")
                if not df4.empty:
                    htf_analysis = analyze_4h_bias(df4)
                    HTF_CACHE[ticker] = htf_analysis
                else:
                    htf_analysis = {}

            # 2. Scan 15m for entries
            sigs = scan_15m_entry(name, ticker, htf_analysis)
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
            f"• <b>Pairs Checked:</b> {len(config.SYMBOLS)} pairs\n"
            f"• <b>Result:</b> No Golden Fib or Candlestick triggers on recent closed 15m candles.\n"
            f"• <b>Next 4H Update:</b> In {countdown}"
        )
        send_telegram(manual_msg)


def main():
    global LAST_4H_SLOT
    parser = argparse.ArgumentParser(description="Axiory Price Action Scanner Bot & Telegram Controller")
    parser.add_argument("--test", action="store_true", help="Send menu and test message")
    parser.add_argument("--once", action="store_true", help="Run a single scan iteration and exit")
    args = parser.parse_args()

    if args.test:
        send_startup_banner()
        return

    print("=" * 65)
    print("  [>] AXIORY PRICE ACTION BOT & TELEGRAM CONTROLLER ACTIVE")
    print(f"  Pairs: {', '.join(config.SYMBOLS.keys())}")
    print(f"  Higher Timeframe (HTF): 4H (Pure Market Structure & Fibs)")
    print(f"  Execution Timeframe (LTF): 15m (Pin Bar / Engulfing Triggers)")
    print(f"  Risk / Reward: 1:{config.TP1_RR} (TP1) ➔ 1:{config.TP2_RR} (TP2)")
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
