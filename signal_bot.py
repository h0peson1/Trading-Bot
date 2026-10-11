"""
LDE Signal Bot & Live Telegram Controller
Features:
- Pinned Persistent Keyboard on Telegram (not attached to single messages)
- Scheduled heartbeat pulse updates every 5 minutes directly to Telegram
- Live continuous LDE scanning across configured pairs and timeframes
- Instant phone command execution for:
    * 📊 Backtest Gold (Multi-TF)
    * ⚡ Macro News Backtest
    * 🔍 Scan Market Now
    * ℹ️ Bot Status
"""

import sys
import time
import threading
import argparse
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Telegram API Helpers with Persistent Keyboard
# ---------------------------------------------------------------------------
def get_persistent_keyboard():
    """
    Returns a persistent phone reply keyboard located at the bottom of the user's screen.
    Independent of individual messages.
    """
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
            ]
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send_telegram(message: str, with_keyboard: bool = False) -> bool:
    """Send HTML formatted message to Telegram."""
    if (
        not config.TELEGRAM_BOT_TOKEN
        or config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE"
        or not config.TELEGRAM_CHAT_ID
        or config.TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE"
    ):
        print("[Telegram preview]:", message)
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if with_keyboard:
        payload["reply_markup"] = get_persistent_keyboard()

    try:
        r = requests.post(url, json=payload, timeout=25)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[Telegram Send Error]: {e}")
        return False


def send_startup_banner():
    """Send bot active notification and establish persistent keyboard on phone."""
    msg = (
        f"🟢 <b>LDE TRADING BOT IS LIVE!</b>\n\n"
        f"• <b>Status:</b> Actively scanning in background\n"
        f"• <b>Pulse Updates:</b> Every 5 minutes\n"
        f"• <b>Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
        f"• <b>Timeframes:</b> {', '.join(config.TIMEFRAMES)}\n\n"
        f"📱 <i>Your control buttons are now pinned at the bottom of your keyboard below! Tap any button anytime from your phone.</i>"
    )
    return send_telegram(msg, with_keyboard=True)


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

                        # Normalize
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
                            # Fetch latest macro news headlines and send to user (does NOT trigger macro backtest)
                            try:
                                news_msg = fundamentals.fetch_macro_news(limit=5)
                                send_telegram(f"📰 <b>Latest Macro News:</b>\n{news_msg}")
                            except Exception as e:
                                send_telegram(f"❌ Error fetching macro news: {e}")

                        elif "macro backtest" in cmd or cmd in ["/macrobt", "/macro"]:
                            # Run macro backtest only
                            send_telegram("⏳ <i>Running 10-Year Gold Macro Backtest under CPI, NFP & FOMC news events...</i>")
                            try:
                                import gold_1000_news_backtest
                                gold_1000_news_backtest.compile_and_send_macro_report()
                            except Exception as ex:
                                send_telegram(f"❌ Error during Macro backtest: {ex}")

                        elif "scan market" in cmd or cmd in ["/scan", "scan"]:
                            send_telegram("🔍 <i>Scanning all configured pairs right now...</i>")
                            run_scanner_cycle(is_manual=True)

                        elif "status" in cmd or cmd in ["/status", "status"]:
                            uptime_msg = (
                                f"<b>📊 LDE Bot Live Status</b>\n\n"
                                f"• <b>Bot State:</b> 🟢 Running 24/7\n"
                                f"• <b>Scanned Cycles Completed:</b> {CYCLE_COUNTER}\n"
                                f"• <b>Heartbeat Interval:</b> Every {config.CHECK_INTERVAL // 60} minutes\n"
                                f"• <b>Pairs:</b> {', '.join(config.SYMBOLS.keys())}\n"
                                f"• <b>Timeframes:</b> {', '.join(config.TIMEFRAMES)}\n"
                                f"• <b>Current Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            )
                            send_telegram(uptime_msg)

                        elif cmd in ["/start", "/menu", "menu", "help"]:
                            send_startup_banner()

        except Exception as e:
            time.sleep(2)

        time.sleep(1)


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------
def fetch_candles(ticker: str, interval: str) -> pd.DataFrame:
    period_map = {
        "15m": "30d",
        "30m": "30d",
        "1h": "60d",
        "4h": "60d",
        "1d": "1y",
    }
    period = period_map.get(interval, "60d")

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
# LDE Strategy Logic
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


def find_liquidity_sweep(df: pd.DataFrame, direction: str, lookback: int = 50) -> bool:
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
        return f" | <b>FVG Active:</b> {c1['high']:.4f}–{c3['low']:.4f} (+{gap_size:.4f})"
    elif direction == "sell" and c3["high"] < c1["low"]:
        gap_size = c1["low"] - c3["high"]
        return f" | <b>FVG Active:</b> {c3['high']:.4f}–{c1['low']:.4f} (-{gap_size:.4f})"

    return ""


def fib_zone_mention(df: pd.DataFrame, direction: str) -> str:
    if len(df) < 20:
        return ""

    swing = df.iloc[-25:]
    high = swing["high"].max()
    low = swing["low"].min()
    diff = high - low
    if diff == 0:
        return ""

    price = df.iloc[-1]["close"]
    if direction == "buy":
        fib50 = high - (0.50 * diff)
        fib718 = high - (0.718 * diff)
        zone_min, zone_max = min(fib50, fib718), max(fib50, fib718)
        if zone_min <= price <= zone_max:
            return f" | <b>Fib Zone:</b> 0.50–0.718 ({zone_min:.4f}–{zone_max:.4f})"
    else:
        fib50 = low + (0.50 * diff)
        fib718 = low + (0.718 * diff)
        zone_min, zone_max = min(fib50, fib718), max(fib50, fib718)
        if zone_min <= price <= zone_max:
            return f" | <b>Fib Zone:</b> 0.50–0.718 ({zone_min:.4f}–{zone_max:.4f})"

    return ""


def format_price(val: float) -> str:
    if val >= 1000:
        return f"{val:.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    else:
        return f"{val:.6f}"


# ---------------------------------------------------------------------------
# Scanner Cycle Execution
# ---------------------------------------------------------------------------
def scan_symbol(symbol_name: str, ticker: str) -> list:
    signals = []

    for tf in config.TIMEFRAMES:
        df = fetch_candles(ticker, tf)
        if df.empty or len(df) < (config.LOOKBACK_CANDLES + 5):
            continue

        curr = df.iloc[-2]
        prev = df.iloc[-3]
        candle_time = str(curr.name)
        eval_df = df.iloc[:-1]

        # 1. Bullish Setup
        if (
            find_liquidity_sweep(eval_df, "buy", lookback=config.LOOKBACK_CANDLES)
            and has_displacement(eval_df, "buy")
            and is_bullish_engulfing(prev, curr)
        ):
            alert_key = (symbol_name, tf, candle_time, "BUY")
            if alert_key not in RECENT_ALERTS:
                RECENT_ALERTS.add(alert_key)
                fib = fib_zone_mention(eval_df, "buy")
                fvg = detect_fvg(eval_df, "buy")

                c1 = eval_df.iloc[-3]
                c3 = eval_df.iloc[-1]
                has_fvg = c3["low"] > c1["high"]
                if has_fvg:
                    entry = (c1["high"] + c3["low"]) / 2.0
                    entry_type = "Limit Entry (50% FVG Retest)"
                else:
                    entry = curr["close"]
                    entry_type = "Market Close Entry"

                sl = min(c1["low"], prev["low"], curr["low"])
                risk = abs(entry - sl)
                tp1 = entry + (risk * 1.5)
                tp2 = entry + (risk * 2.5)

                signals.append(
                    f"🟢 <b>BUY {symbol_name} ({tf.upper()})</b>{fib}{fvg}\n"
                    f"• <b>Strategy:</b> Sweep ➔ Displacement ➔ Retest\n"
                    f"• <b>{entry_type}:</b> {format_price(entry)}\n"
                    f"• <b>Stop Loss:</b> {format_price(sl)}\n"
                    f"• <b>🎯 TP1 (1:1.5 - Take 50% & SL to BE):</b> {format_price(tp1)}\n"
                    f"• <b>🎯 TP2 (1:2.5 - Final Target):</b> {format_price(tp2)}\n"
                    f"• <i>Closed Candle Time:</i> {candle_time}"
                )

        # 2. Bearish Setup
        if (
            find_liquidity_sweep(eval_df, "sell", lookback=config.LOOKBACK_CANDLES)
            and has_displacement(eval_df, "sell")
            and is_bearish_engulfing(prev, curr)
        ):
            alert_key = (symbol_name, tf, candle_time, "SELL")
            if alert_key not in RECENT_ALERTS:
                RECENT_ALERTS.add(alert_key)
                fib = fib_zone_mention(eval_df, "sell")
                fvg = detect_fvg(eval_df, "sell")

                c1 = eval_df.iloc[-3]
                c3 = eval_df.iloc[-1]
                has_fvg = c3["high"] < c1["low"]
                if has_fvg:
                    entry = (c1["low"] + c3["high"]) / 2.0
                    entry_type = "Limit Entry (50% FVG Retest)"
                else:
                    entry = curr["close"]
                    entry_type = "Market Close Entry"

                sl = max(c1["high"], prev["high"], curr["high"])
                risk = abs(sl - entry)
                tp1 = entry - (risk * 1.5)
                tp2 = entry - (risk * 2.5)

                signals.append(
                    f"🔴 <b>SELL {symbol_name} ({tf.upper()})</b>{fib}{fvg}\n"
                    f"• <b>Strategy:</b> Sweep ➔ Displacement ➔ Retest\n"
                    f"• <b>{entry_type}:</b> {format_price(entry)}\n"
                    f"• <b>Stop Loss:</b> {format_price(sl)}\n"
                    f"• <b>🎯 TP1 (1:1.5 - Take 50% & SL to BE):</b> {format_price(tp1)}\n"
                    f"• <b>🎯 TP2 (1:2.5 - Final Target):</b> {format_price(tp2)}\n"
                    f"• <i>Closed Candle Time:</i> {candle_time}"
                )

    if len(RECENT_ALERTS) > 1000:
        RECENT_ALERTS.clear()

    return signals


def run_scanner_cycle(is_manual: bool = False):
    """Run a single scan iteration across all symbols and send updates."""
    global CYCLE_COUNTER
    CYCLE_COUNTER += 1

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] Cycle #{CYCLE_COUNTER}: Scanning {len(config.SYMBOLS)} pairs...")
    all_signals = []

    for name, ticker in config.SYMBOLS.items():
        try:
            sigs = scan_symbol(name, ticker)
            if sigs:
                all_signals.extend(sigs)
        except Exception as e:
            print(f"Error scanning {name} ({ticker}): {e}")

    if all_signals:
        header = f"<b>{config.SIGNAL_PREFIX}</b>\n\n"
        message = header + "\n\n".join(all_signals)
        send_telegram(message)
        print(f"[{now_str}] 🚨 Sent {len(all_signals)} signal(s)!")
    else:
        print(f"[{now_str}] No active setups in cycle #{CYCLE_COUNTER}.")
        # Send heartbeat pulse update to Telegram every 5 minutes so user knows bot is live
        pulse_msg = (
            f"⏱ <b>5-Min Live Heartbeat Update (Cycle #{CYCLE_COUNTER})</b>\n\n"
            f"• <b>Status:</b> 🟢 Live & Scanning\n"
            f"• <b>Pairs Monitored:</b> {len(config.SYMBOLS)} pairs ({', '.join(config.SYMBOLS.keys())})\n"
            f"• <b>Timeframes:</b> {', '.join(config.TIMEFRAMES)}\n"
            f"• <b>Market Condition:</b> No trigger criteria reached in this 5-min candle.\n"
            f"• <b>Time:</b> {datetime.now().strftime('%H:%M:%S UTC')}"
        )
        send_telegram(pulse_msg)


def main():
    parser = argparse.ArgumentParser(description="LDE Signal Scanner Bot & Interactive Controller")
    parser.add_argument("--test", action="store_true", help="Send menu and test message")
    parser.add_argument("--once", action="store_true", help="Run a single scan iteration and exit")
    args = parser.parse_args()

    if args.test:
        send_startup_banner()
        return

    print("=" * 60)
    print("  [>] LDE SIGNAL BOT & TELEGRAM CONTROLLER ACTIVE")
    print(f"  Pairs: {', '.join(config.SYMBOLS.keys())}")
    print(f"  Timeframes: {', '.join(config.TIMEFRAMES)}")
    print("  Persistent Mobile Control Keyboard: ENABLED")
    print(f"  Heartbeat Update Frequency: Every {config.CHECK_INTERVAL // 60} minutes")
    print("=" * 60)

    # Start Telegram Listener Thread for mobile button interactions
    listener_thread = threading.Thread(target=handle_telegram_updates, daemon=True)
    listener_thread.start()
    print("  [✓] Interactive Telegram Button Listener running.")

    # Send startup welcome banner with persistent keyboard to user's Telegram
    send_startup_banner()

    if args.once:
        run_scanner_cycle(is_manual=True)
        return

    while True:
        try:
            run_scanner_cycle()
        except KeyboardInterrupt:
            print("\nBot stopped by user.")
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected cycle error: {e}")

        time.sleep(config.CHECK_INTERVAL)


if __name__ == "__main__":
    main()
