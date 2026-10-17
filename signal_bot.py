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

import os
import sys
import json
import time
import threading
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd
import requests
import yfinance as yf
import config
import fundamentals
import bot_chat

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
SUBSCRIBERS_FILE = "subscribers.json"


def is_admin(chat_id: Any) -> bool:
    """Checks whether the given chat_id belongs to the bot administrator."""
    admin_id = str(getattr(config, "ADMIN_CHAT_ID", getattr(config, "TELEGRAM_CHAT_ID", ""))).strip()
    return str(chat_id).strip() == admin_id


def load_subscribers() -> set:
    """Load persistent set of subscriber chat IDs from file."""
    subs = set()
    admin_id = str(getattr(config, "ADMIN_CHAT_ID", getattr(config, "TELEGRAM_CHAT_ID", ""))).strip()
    if admin_id:
        subs.add(admin_id)
    try:
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for cid in data:
                        if cid:
                            subs.add(str(cid).strip())
    except Exception as e:
        print(f"[Subscriber Load Error]: {e}")
    return subs


def save_subscriber(chat_id: Any):
    """Register a new subscriber account to receive trade signals."""
    if not chat_id:
        return
    cid_str = str(chat_id).strip()
    subs = load_subscribers()
    if cid_str not in subs:
        subs.add(cid_str)
        try:
            with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(subs), f, indent=2)
            print(f"[+] New subscriber registered: {cid_str} (Total: {len(subs)})")
        except Exception as e:
            print(f"[Subscriber Save Error]: {e}")


def remove_subscriber(chat_id: Any):
    """Remove a subscriber if they blocked the bot (HTTP 403)."""
    if not chat_id or is_admin(chat_id):
        return
    cid_str = str(chat_id).strip()
    subs = load_subscribers()
    if cid_str in subs:
        subs.remove(cid_str)
        try:
            with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(subs), f, indent=2)
            print(f"[-] Removed inactive subscriber: {cid_str}")
        except Exception as e:
            print(f"[Subscriber Remove Error]: {e}")


def get_persistent_keyboard() -> dict:
    """Returns persistent phone reply keyboard at bottom of screen."""
    return {
        "keyboard": [
            [
                {"text": "🔍 Scan for Signals"},
                {"text": "ℹ️ Bot Status"},
            ],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send_telegram(message: str, with_keyboard: bool = False, chat_id: Optional[Any] = None) -> bool:
    """
    Send HTML formatted message to Telegram.
    - If chat_id is specified: sends privately to that specific user/admin.
    - If chat_id is None: broadcasts the signal to ALL registered subscriber accounts!
    """
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("[Telegram preview]:", message)
        return False

    if chat_id:
        targets = [str(chat_id).strip()]
    else:
        targets = list(load_subscribers())
        if not targets and config.TELEGRAM_CHAT_ID:
            targets = [str(config.TELEGRAM_CHAT_ID).strip()]

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

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

    overall_success = True
    for target in targets:
        for idx, chunk in enumerate(chunks):
            payload = {
                "chat_id": target,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            # Only attach control keyboard if recipient is the admin
            if with_keyboard and idx == len(chunks) - 1 and is_admin(target):
                payload["reply_markup"] = get_persistent_keyboard()

            try:
                r = requests.post(url, json=payload, timeout=20)
                if r.status_code == 403:
                    remove_subscriber(target)
                elif r.status_code != 200:
                    overall_success = False
            except Exception as e:
                print(f"[Telegram Send Error to {target}]: {e}")
                overall_success = False

    return overall_success


def send_startup_banner(target_chat_id: Optional[Any] = None):
    """Send clean startup confirmation."""
    msg = (
        f"🟢 <b>Trading Signal Bot Active</b>\n\n"
        f"• <b>Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
        f"• <b>Signal Format:</b> Entry, TP, SL, and Reason for trade\n\n"
        f"<i>Signals will be sent here automatically when entry setups trigger.</i>"
    )
    return send_telegram(msg, with_keyboard=True, chat_id=target_chat_id)


# ---------------------------------------------------------------------------
# Data Fetching & Caching (Twelve Data API with Rate Limiting)
# ---------------------------------------------------------------------------
HTF_CACHE: Dict[str, dict] = {}
LAST_API_CALL_TIME = 0.0


# Fallback Ticker Mapping for Yahoo Finance
YF_FALLBACK_MAP = {
    "BTC/USD": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "XAU/USD": "GC=F",
    "XAUUSD": "GC=F",
    "EUR/JPY": "EURJPY=X",
    "EURJPY": "EURJPY=X",
}


def fetch_candles_fallback(ticker: str, interval: str) -> pd.DataFrame:
    """
    Automatic backup candle fetcher using Yahoo Finance.
    Activates seamlessly when Twelve Data API credits are exhausted for the day.
    """
    yf_symbol = YF_FALLBACK_MAP.get(ticker, ticker)
    try:
        t = yf.Ticker(yf_symbol)
        if interval == "4h":
            # Synthesize 4H bars from 1H bars
            df1 = t.history(period="60d", interval="1h", auto_adjust=True)
            if df1 is None or df1.empty:
                return pd.DataFrame()
            df1 = df1.rename(columns={c: c.lower() for c in df1.columns})
            df4 = df1.resample("4h").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last"
            }).dropna()
            if df4.index.tz is None:
                df4.index = df4.index.tz_localize("UTC")
            else:
                df4.index = df4.index.tz_convert("UTC")
            return df4[["open", "high", "low", "close"]]
        else:
            yf_int = "15m" if interval == "15min" else ("1h" if interval == "1h" else "1d")
            period = "5d" if yf_int == "15m" else "60d"
            df = t.history(period=period, interval=yf_int, auto_adjust=True)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={c: c.lower() for c in df.columns})
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            return df[["open", "high", "low", "close"]].dropna()
    except Exception as e:
        print(f"  [!] Fallback error fetching {ticker} via Yahoo Finance: {e}")
        return pd.DataFrame()


def fetch_candles(ticker: str, interval: str) -> pd.DataFrame:
    """Fetch recent historical candles from Twelve Data, with instant automatic fallback."""
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
    twelve_data_exhausted = False

    for attempt in range(2):
        try:
            LAST_API_CALL_TIME = time.time()
            resp = requests.get(
                "https://api.twelvedata.com/time_series",
                params=params,
                timeout=30,
            )
            if resp.status_code == 429:
                twelve_data_exhausted = True
                break
            resp.raise_for_status()
            data = resp.json()
            if data and (data.get("code") == 429 or "run out of api credits" in str(data).lower()):
                twelve_data_exhausted = True
                break
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
            else:
                twelve_data_exhausted = True

    # If Twelve Data daily limit is reached or errored, switch to backup data provider
    if twelve_data_exhausted or not data or data.get("status") == "error" or "values" not in data:
        if getattr(config, "FALLBACK_TO_YFINANCE_ON_429", True):
            print(f"  [↻] Twelve Data limit reached. Seamlessly fetching {ticker} ({interval}) via Yahoo Finance backup...")
            return fetch_candles_fallback(ticker, interval)
        return pd.DataFrame()

    df = pd.DataFrame(data["values"])
    if df.empty:
        if getattr(config, "FALLBACK_TO_YFINANCE_ON_429", True):
            return fetch_candles_fallback(ticker, interval)
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
def send_4h_market_update(is_startup: bool = False, target_chat_id: Optional[Any] = None):
    """Compiles and sends the 4H market structure overview."""
    global LAST_4H_DISPATCH_TIME
    now_utc = datetime.now(timezone.utc)
    LAST_4H_DISPATCH_TIME = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        f"📊 <b>4-HOUR MARKET STRUCTURE UPDATE</b>\n"
        f"<i>Time: {now_utc.strftime('%H:%M UTC')}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    ]

    for name, ticker in config.SYMBOLS.items():
        try:
            df4 = fetch_candles(ticker, "4h")
            if df4.empty:
                continue
            res = analyze_4h_bias(df4)
            HTF_CACHE[ticker] = res  # Cache 4H analysis
            sign = "+" if res["change_pct"] >= 0 else ""

            block = (
                f"<b>{name}:</b> {format_price(res['close'])} ({sign}{res['change_pct']:.2f}%) | <b>{res['bias']}</b>\n"
                f"• <b>Market Structure:</b> {res['explanation']}"
            )
            blocks.append(block)
        except Exception as e:
            print(f"Error compiling 4H update for {name}: {e}")

    countdown = get_time_until_next_4h_close()
    blocks.append(f"━━━━━━━━━━━━━━━━━━━━\n⏳ <b>Next 4H Candle Close:</b> In {countdown}")
    full_msg = "\n\n".join(blocks)
    send_telegram(full_msg, with_keyboard=True, chat_id=target_chat_id)


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

    # 1. Peak Session Timing Filter (London Open to London/NY Overlap: 07:00–15:00 UTC)
    # Check BEFORE fetching candles to avoid consuming Twelve Data API credits during off-peak hours!
    if getattr(config, "ENABLE_SESSION_FILTER", True):
        is_crypto = (symbol_name == "BTCUSD" and getattr(config, "BTC_24H_TRADING", True))
        if not is_crypto:
            now_utc = datetime.now(timezone.utc)
            if now_utc.hour < config.SESSION_START_UTC or now_utc.hour > config.SESSION_END_UTC:
                return signals

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

    # 2. Asset-Specific Direction Filter: Bitcoin Long-Only (aligned with macro bull trend from backtest)
    if symbol_name == "BTCUSD" and getattr(config, "BTC_LONG_ONLY", True):
        if alert_direction != "BUY":
            return signals

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

    # 3. Dynamic Volatility Buffer (0.15% for Gold/FX, 0.50% for Crypto to absorb noise wicks)
    if symbol_name == "BTCUSD":
        buffer = max(entry * getattr(config, "BTC_SL_BUFFER_PCT", 0.005), 10.0)
    else:
        buffer = max(entry * 0.0015, 0.0006)

    if alert_direction == "BUY":
        sl = sl - buffer
        risk = abs(entry - sl)
        tp1 = entry + (risk * config.TP1_RR)
        tp2 = entry + (risk * config.TP2_RR)
        badge = "🟢 <b>BUY</b>"
    else:
        sl = sl + buffer
        risk = abs(sl - entry)
        tp1 = entry - (risk * config.TP1_RR)
        tp2 = entry - (risk * config.TP2_RR)
        badge = "🔴 <b>SELL</b>"

    bias_clean = bias.replace("🟢", "").replace("🔴", "").replace("⚪", "").strip()
    reason = f"{trigger['pattern']} confirmation aligning with {bias_clean} trend"

    tp_text = format_price(tp1)
    if getattr(config, "TP2_RR", None):
        tp_text += f" (TP2: {format_price(tp2)})"

    alert_text = (
        f"{badge} <b>{symbol_name}</b>\n\n"
        f"• <b>Entry:</b> {format_price(entry)}\n"
        f"• <b>TP:</b> {tp_text}\n"
        f"• <b>SL:</b> {format_price(sl)}\n"
        f"• <b>Reason for trade:</b> {reason}"
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
                        if not text:
                            continue

                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        sender_name = msg.get("from", {}).get("first_name") or msg.get("chat", {}).get("first_name", "trader")
                        cmd = text.lower()

                        # Ensure this account is saved as a subscriber to receive all trade signals
                        save_subscriber(chat_id)

                        # Differentiate between administrator and general subscribers
                        if is_admin(chat_id):
                            if "scan" in cmd:
                                send_telegram("🔍 <i>Scanning for trade entries...</i>", chat_id=chat_id)
                                run_15m_cycle(is_manual=True, request_chat_id=chat_id)

                            elif "structure" in cmd:
                                send_telegram("📊 <i>Compiling 4H market structure...</i>", chat_id=chat_id)
                                send_4h_market_update(target_chat_id=chat_id)

                            elif "news" in cmd:
                                try:
                                    news_msg = fundamentals.fetch_macro_news(limit=5)
                                    send_telegram(f"📰 <b>Latest Macro News:</b>\n{news_msg}", chat_id=chat_id)
                                except Exception as e:
                                    send_telegram(f"❌ Error fetching macro news: {e}", chat_id=chat_id)

                            elif "status" in cmd:
                                subs_count = len(load_subscribers())
                                status_msg = (
                                    f"<b>📊 Bot Status: Active 🟢</b>\n\n"
                                    f"• <b>Monitored Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
                                    f"• <b>Subscribers Receiving Signals:</b> {subs_count}\n"
                                    f"• <b>Scanner:</b> 15-Minute candles (every {config.SCAN_INTERVAL}s)\n"
                                    f"• <b>Format:</b> Clean Signals (Entry, TP, SL, Reason)\n"
                                    f"• <b>Cycles Completed:</b> {CYCLE_COUNTER}"
                                )
                                send_telegram(status_msg, chat_id=chat_id, with_keyboard=True)

                            elif cmd in ["/start", "/menu", "menu", "help"]:
                                send_startup_banner(target_chat_id=chat_id)

                            else:
                                # Full interactive conversation & Gemini AI chat (Admin only)
                                reply = bot_chat.get_chat_response(text, user_name=sender_name)
                                send_telegram(reply, chat_id=chat_id, with_keyboard=True)

                        else:
                            # General subscriber (signals only, no direct chat)
                            if cmd in ["/start", "start", "/help", "help", "/menu", "menu"]:
                                welcome_msg = (
                                    f"👋 <b>Welcome, {sender_name}!</b>\n\n"
                                    f"✅ <b>You are now subscribed to receive live trading signals.</b>\n\n"
                                    f"• <b>Monitored Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
                                    f"• <b>Signal Details:</b> Entry, TP, SL, and Reason for trade\n\n"
                                    f"<i>Whenever a high-probability trade triggers, you will receive the alert directly here automatically! 📈</i>"
                                )
                                send_telegram(welcome_msg, chat_id=chat_id)
                            else:
                                notice_msg = (
                                    f"🔒 <i>Hi {sender_name}, direct conversation is reserved for the bot administrator.\n\n"
                                    f"Don't worry—you are actively subscribed and will automatically receive every trade signal alert as soon as it triggers! 🎯</i>"
                                )
                                send_telegram(notice_msg, chat_id=chat_id)

        except Exception:
            time.sleep(2)

        time.sleep(1)


# ---------------------------------------------------------------------------
# Scanner Execution Loop
# ---------------------------------------------------------------------------
def run_15m_cycle(is_manual: bool = False, request_chat_id: Optional[Any] = None):
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
            send_telegram(sig)  # Broadcasts to all subscribers!
        print(f"[{now_str}] 🚨 Broadcasted {len(all_signals)} 15M entry alert(s) to all subscribers!")
    elif is_manual and request_chat_id:
        now_utc = datetime.now(timezone.utc)
        in_peak = (config.SESSION_START_UTC <= now_utc.hour <= config.SESSION_END_UTC)
        session_info = (
            "🟢 Peak Hours Active (07:00–15:00 UTC)"
            if in_peak
            else f"🌙 Outside Peak Hours (Current: {now_utc.strftime('%H:%M')} UTC | Peak: 07:00–15:00 UTC for Gold/FX)"
        )
        manual_msg = (
            f"🔍 <b>Scan Complete:</b> No active trade entries found.\n\n"
            f"• <b>Universe:</b> {', '.join(config.SYMBOLS.keys())}\n"
            f"• <b>Timing:</b> {session_info}\n"
            f"• <i>BTCUSD monitored 24/7 (Long-Only); XAUUSD & EURJPY monitored during peak volume (07:00–15:00 UTC).</i>"
        )
        send_telegram(manual_msg, chat_id=request_chat_id)


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

    # Cache initial 4H market overview in background
    LAST_4H_SLOT = get_current_4h_slot_key()
    print("  [>] Caching initial 4H market structure in background...")
    for name, ticker in config.SYMBOLS.items():
        try:
            df4 = fetch_candles(ticker, "4h")
            if not df4.empty:
                HTF_CACHE[ticker] = analyze_4h_bias(df4)
        except Exception as e:
            print(f"Error caching 4H for {name}: {e}")

    if getattr(config, "SEND_4H_BRIEFING", False):
        send_4h_market_update(is_startup=True)

    if args.once:
        run_15m_cycle(is_manual=True)
        return

    while True:
        try:
            # 1. Check if a 4-hour candle has closed
            current_slot = get_current_4h_slot_key()
            if current_slot != LAST_4H_SLOT:
                print(f"\n[>] 4-Hour Candle Close detected for slot {current_slot}! Updating 4H cache...")
                for name, ticker in config.SYMBOLS.items():
                    try:
                        df4 = fetch_candles(ticker, "4h")
                        if not df4.empty:
                            HTF_CACHE[ticker] = analyze_4h_bias(df4)
                    except Exception as e:
                        print(f"Error caching 4H for {name}: {e}")
                LAST_4H_SLOT = current_slot
                if getattr(config, "SEND_4H_BRIEFING", False):
                    send_4h_market_update()

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
