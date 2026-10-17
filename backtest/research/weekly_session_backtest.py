"""
Comprehensive Backtester for the Trading Session: Monday Oct 12, 2026 to Friday Oct 16, 2026.
Covers:
- 1-Hour Axiory 70% Target Model (backtest.py)
- 15-Minute Live Signal Bot Strategy (signal_bot.py)
Across all 6 configured symbols: BTCUSD, XAUUSD, GBPUSD, USDCHF, GBPAUD, EURJPY.
"""

import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
import config
from optimize_strategy import precompute_swings, YF_TICKER_MAP

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

START_TIME = pd.Timestamp("2026-10-12 00:00:00", tz="UTC")
END_TIME = pd.Timestamp("2026-10-16 23:59:59", tz="UTC")

SYMBOLS = ["BTCUSD", "XAUUSD", "GBPUSD", "USDCHF", "GBPAUD", "EURJPY"]

def fetch_df(symbol: str, interval: str, period: str):
    yf_symbol = YF_TICKER_MAP.get(symbol, symbol)
    try:
        t = yf.Ticker(yf_symbol)
        df = t.history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={c: c.lower() for c in df.columns})
        df = df[["open", "high", "low", "close"]].dropna()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df
    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return pd.DataFrame()


def run_1h_session_backtest():
    print("\n" + "=" * 85)
    print("  🚀 [STRATEGY 1] 1-HOUR AXIORY 70% MODEL — WEEK SESSION (OCT 12 - 16, 2026)")
    print("=" * 85)
    
    trades = []
    
    for symbol in SYMBOLS:
        d4 = fetch_df(symbol, "4h", "180d")
        d1 = fetch_df(symbol, "1h", "60d")
        if d4.empty or d1.empty:
            continue
            
        d4["sma100"] = d4["close"].rolling(window=100).mean()
        h4_highs, h4_lows, h4_closes = d4["high"].values, d4["low"].values, d4["close"].values
        h4_times = d4.index
        swings_4h = precompute_swings(h4_highs, h4_lows, h4_times, order=config.SWING_ORDER)
        if len(swings_4h) < 4:
            continue
        swing_4h_indices = np.array([s.index for s in swings_4h])

        h1_opens = d1["open"].values
        h1_highs = d1["high"].values
        h1_lows = d1["low"].values
        h1_closes = d1["close"].values
        h1_times = d1.index
        n_1h = len(d1)

        in_trade_until = 0

        for i in range(100, n_1h - 1):
            curr_time = h1_times[i]
            # Restrict signal generation to this week's trading session:
            if curr_time < START_TIME or curr_time > END_TIME:
                continue
            if i < in_trade_until:
                continue

            h4_idx_pos = d4.index.searchsorted(curr_time, side="right") - 1
            if h4_idx_pos < 100:
                continue

            sma_val = d4["sma100"].iloc[h4_idx_pos]
            if pd.isna(sma_val):
                continue

            cutoff_4h = h4_idx_pos - config.SWING_ORDER
            valid_pos = np.searchsorted(swing_4h_indices, cutoff_4h, side="right")
            if valid_pos < 4:
                continue

            recent_swings = swings_4h[max(0, valid_pos - 8):valid_pos]
            h_swings = [s for s in recent_swings if s.swing_type == "HIGH"]
            l_swings = [s for s in recent_swings if s.swing_type == "LOW"]
            if len(h_swings) < 2 or len(l_swings) < 2:
                continue

            latest_h, latest_l = h_swings[-1], l_swings[-1]
            is_bullish = (latest_h.label == "HH" and latest_l.label == "HL" and latest_h.index > latest_l.index)
            is_bearish = (latest_h.label == "LH" and latest_l.label == "LL" and latest_l.index > latest_h.index)

            # 100 SMA Filter
            if is_bullish and h4_closes[h4_idx_pos] < sma_val:
                continue
            if is_bearish and h4_closes[h4_idx_pos] > sma_val:
                continue

            if not (is_bullish or is_bearish):
                continue

            direction = "BUY" if is_bullish else "SELL"
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue

            # Fibonacci Golden Zone check
            if direction == "BUY":
                fib50 = latest_h.price - (range_span * 0.50)
                fib618 = latest_h.price - (range_span * 0.618)
                invalidation = latest_l.price
                in_zone = (h1_lows[i] <= fib50) and (h1_highs[i] >= fib618)
                if not in_zone or h1_closes[i] < invalidation:
                    continue
            else:
                fib50 = latest_l.price + (range_span * 0.50)
                fib618 = latest_l.price + (range_span * 0.618)
                invalidation = latest_h.price
                in_zone = (h1_highs[i] >= fib50) and (h1_lows[i] <= fib618)
                if not in_zone or h1_closes[i] > invalidation:
                    continue

            # Candlestick Confirmation Trigger
            c_open, c_high, c_low, c_close = h1_opens[i], h1_highs[i], h1_lows[i], h1_closes[i]
            p_open, p_high, p_low, p_close = h1_opens[i-1], h1_highs[i-1], h1_lows[i-1], h1_closes[i-1]
            c_range = c_high - c_low
            if c_range <= 0:
                continue
            c_body = abs(c_close - c_open)
            c_upper = c_high - max(c_open, c_close)
            c_lower = min(c_open, c_close) - c_low

            pattern = None
            raw_sl = None

            if direction == "BUY":
                is_pin = (c_lower >= (2.0 * c_body) and c_lower >= (0.50 * c_range) and c_upper <= (0.25 * c_range) and c_close >= c_open)
                is_engulf = (p_close < p_open and c_close > c_open and c_close >= p_high and c_body >= (0.55 * c_range))
                if is_pin:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
                elif is_engulf:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl - buffer
                risk = limit_entry - sl
                if risk <= 0:
                    continue
                tp1 = limit_entry + (risk * config.TP1_RR)
                tp2 = limit_entry + (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 6, n_1h)):
                    if h1_lows[w_idx] <= limit_entry:
                        if h1_lows[w_idx] <= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            else:  # SELL
                is_pin = (c_upper >= (2.0 * c_body) and c_upper >= (0.50 * c_range) and c_lower <= (0.25 * c_range) and c_close <= c_open)
                is_engulf = (p_close > p_open and c_close < c_open and c_close <= p_low and c_body >= (0.55 * c_range))
                if is_pin:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high
                elif is_engulf:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl + buffer
                risk = sl - limit_entry
                if risk <= 0:
                    continue
                tp1 = limit_entry - (risk * config.TP1_RR)
                tp2 = limit_entry - (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 6, n_1h)):
                    if h1_highs[w_idx] >= limit_entry:
                        if h1_highs[w_idx] >= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            # Forward outcome tracking
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False
            exit_time = None
            exit_price = None

            for f_idx in range(fill_idx + 1, min(fill_idx + 60, n_1h)):
                b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]
                exit_time = h1_times[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break

            trades.append({
                "strategy": "1H_Axiory",
                "symbol": symbol,
                "time": curr_time,
                "direction": direction,
                "pattern": pattern,
                "entry": round(limit_entry, 4),
                "sl": round(sl, 4),
                "tp1": round(tp1, 4),
                "tp2": round(tp2, 4),
                "outcome": outcome,
                "pnl_r": round(pnl_r, 2),
                "exit_time": exit_time,
                "exit_price": round(exit_price, 4) if exit_price else None
            })

    return pd.DataFrame(trades)


def run_15m_session_backtest():
    print("\n" + "=" * 85)
    print("  🚀 [STRATEGY 2] 15-MINUTE BOT EXECUTION — WEEK SESSION (OCT 12 - 16, 2026)")
    print("=" * 85)
    
    trades = []
    
    for symbol in SYMBOLS:
        d4 = fetch_df(symbol, "4h", "180d")
        d15 = fetch_df(symbol, "15m", "30d")
        if d4.empty or d15.empty:
            continue
            
        d4["sma100"] = d4["close"].rolling(window=100).mean()
        h4_highs, h4_lows, h4_closes = d4["high"].values, d4["low"].values, d4["close"].values
        h4_times = d4.index
        swings_4h = precompute_swings(h4_highs, h4_lows, h4_times, order=config.SWING_ORDER)
        if len(swings_4h) < 4:
            continue
        swing_4h_indices = np.array([s.index for s in swings_4h])

        m15_opens = d15["open"].values
        m15_highs = d15["high"].values
        m15_lows = d15["low"].values
        m15_closes = d15["close"].values
        m15_times = d15.index
        n_15m = len(d15)

        in_trade_until = 0

        for i in range(100, n_15m - 1):
            curr_time = m15_times[i]
            if curr_time < START_TIME or curr_time > END_TIME:
                continue
            if i < in_trade_until:
                continue

            h4_idx_pos = d4.index.searchsorted(curr_time, side="right") - 1
            if h4_idx_pos < 100:
                continue

            sma_val = d4["sma100"].iloc[h4_idx_pos]
            if pd.isna(sma_val):
                continue

            cutoff_4h = h4_idx_pos - config.SWING_ORDER
            valid_pos = np.searchsorted(swing_4h_indices, cutoff_4h, side="right")
            if valid_pos < 4:
                continue

            recent_swings = swings_4h[max(0, valid_pos - 8):valid_pos]
            h_swings = [s for s in recent_swings if s.swing_type == "HIGH"]
            l_swings = [s for s in recent_swings if s.swing_type == "LOW"]
            if len(h_swings) < 2 or len(l_swings) < 2:
                continue

            latest_h, latest_l = h_swings[-1], l_swings[-1]
            is_bullish = (latest_h.label == "HH" and latest_l.label == "HL" and latest_h.index > latest_l.index)
            is_bearish = (latest_h.label == "LH" and latest_l.label == "LL" and latest_l.index > latest_h.index)

            # 100 SMA Filter
            if is_bullish and h4_closes[h4_idx_pos] < sma_val:
                continue
            if is_bearish and h4_closes[h4_idx_pos] > sma_val:
                continue

            if not (is_bullish or is_bearish):
                continue

            direction = "BUY" if is_bullish else "SELL"
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue

            # Fibonacci Golden Zone
            if direction == "BUY":
                fib50 = latest_h.price - (range_span * 0.50)
                fib618 = latest_h.price - (range_span * 0.618)
                invalidation = latest_l.price
                in_zone = (m15_lows[i] <= fib50) and (m15_highs[i] >= fib618)
                if not in_zone or m15_closes[i] < invalidation:
                    continue
            else:
                fib50 = latest_l.price + (range_span * 0.50)
                fib618 = latest_l.price + (range_span * 0.618)
                invalidation = latest_h.price
                in_zone = (m15_highs[i] >= fib50) and (m15_lows[i] <= fib618)
                if not in_zone or m15_closes[i] > invalidation:
                    continue

            # Candlestick pattern detection on 15m
            c_open, c_high, c_low, c_close = m15_opens[i], m15_highs[i], m15_lows[i], m15_closes[i]
            p_open, p_high, p_low, p_close = m15_opens[i-1], m15_highs[i-1], m15_lows[i-1], m15_closes[i-1]
            c_range = c_high - c_low
            if c_range <= 0:
                continue
            c_body = abs(c_close - c_open)
            c_upper = c_high - max(c_open, c_close)
            c_lower = min(c_open, c_close) - c_low

            pattern = None
            raw_sl = None

            if direction == "BUY":
                is_pin = (c_lower >= (2.0 * c_body) and c_lower >= (0.50 * c_range) and c_upper <= (0.25 * c_range) and c_close >= c_open)
                is_engulf = (p_close < p_open and c_close > c_open and c_close >= p_high and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
                elif is_engulf:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                elif i >= 2:
                    p2_open, p2_close = m15_opens[i-2], m15_closes[i-2]
                    if p2_close < p2_open and c_close > c_open and c_close >= (p2_close + 0.5 * abs(p2_open - p2_close)):
                        pattern = "Morning Star"
                        raw_sl = min(c_low, p_low, m15_lows[i-2])

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl - buffer
                risk = limit_entry - sl
                if risk <= 0:
                    continue
                tp1 = limit_entry + (risk * config.TP1_RR)
                tp2 = limit_entry + (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 8, n_15m)):
                    if m15_lows[w_idx] <= limit_entry:
                        if m15_lows[w_idx] <= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            else:  # SELL
                is_pin = (c_upper >= (2.0 * c_body) and c_upper >= (0.50 * c_range) and c_lower <= (0.25 * c_range) and c_close <= c_open)
                is_engulf = (p_close > p_open and c_close < c_open and c_close <= p_low and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high
                elif is_engulf:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                elif i >= 2:
                    p2_open, p2_close = m15_opens[i-2], m15_closes[i-2]
                    if p2_close > p2_open and c_close < c_open and c_close <= (p2_close - 0.5 * abs(p2_open - p2_close)):
                        pattern = "Evening Star"
                        raw_sl = max(c_high, p_high, m15_highs[i-2])

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl + buffer
                risk = sl - limit_entry
                if risk <= 0:
                    continue
                tp1 = limit_entry - (risk * config.TP1_RR)
                tp2 = limit_entry - (risk * config.TP2_RR)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 8, n_15m)):
                    if m15_highs[w_idx] >= limit_entry:
                        if m15_highs[w_idx] >= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            # Forward outcome
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False
            exit_time = None
            exit_price = None

            for f_idx in range(fill_idx + 1, min(fill_idx + 120, n_15m)):
                b_high, b_low = m15_highs[f_idx], m15_lows[f_idx]
                exit_time = m15_times[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        exit_price = sl
                        in_trade_until = f_idx + 1
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        exit_price = limit_entry
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        exit_price = tp2
                        in_trade_until = f_idx + 1
                        break

            trades.append({
                "strategy": "15M_Bot",
                "symbol": symbol,
                "time": curr_time,
                "direction": direction,
                "pattern": pattern,
                "entry": round(limit_entry, 4),
                "sl": round(sl, 4),
                "tp1": round(tp1, 4),
                "tp2": round(tp2, 4),
                "outcome": outcome,
                "pnl_r": round(pnl_r, 2),
                "exit_time": exit_time,
                "exit_price": round(exit_price, 4) if exit_price else None
            })

    return pd.DataFrame(trades)


def display_results(df: pd.DataFrame, title: str):
    print("\n" + "=" * 85)
    print(f"        📊 {title}")
    print("=" * 85)
    if df.empty:
        print("  No qualified trades were triggered during this week session.")
        return

    print(f"{'Time (UTC)':<17} | {'Pair':<7} | {'Dir':<4} | {'Pattern':<16} | {'Entry':<9} | {'SL':<9} | {'TP1':<9} | {'TP2':<9} | {'Outcome':<11} | {'PnL (R)'}")
    print("-" * 115)
    for _, r in df.iterrows():
        t_str = r['time'].strftime('%m-%d %H:%M')
        print(f"{t_str:<17} | {r['symbol']:<7} | {r['direction']:<4} | {r['pattern']:<16} | {r['entry']:<9} | {r['sl']:<9} | {r['tp1']:<9} | {r['tp2']:<9} | {r['outcome']:<11} | {r['pnl_r']:>+5.2f} R")
    print("-" * 115)

    total = len(df)
    full_wins = (df["outcome"] == "FULL_WIN").sum()
    partials = (df["outcome"] == "PARTIAL_WIN").sum()
    wins = full_wins + partials
    losses = (df["outcome"] == "LOSS").sum()
    open_t = (df["outcome"] == "OPEN").sum()
    wr = (wins / (total - open_t)) * 100 if (total - open_t) > 0 else 0.0
    tot_r = df["pnl_r"].sum()
    gp = df[df["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(df[df["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)

    print(f"\n  Total Trades:     {total}")
    print(f"  Wins:             {wins} ({full_wins} Full TP2, {partials} Partial TP1/BE)")
    print(f"  Losses:           {losses}")
    print(f"  Still Open:       {open_t}")
    print(f"  Win Rate:         {wr:.1f}%")
    print(f"  Total PnL:        {tot_r:+.2f} R")
    print(f"  Profit Factor:    {pf:.2f}")
    print("=" * 85)


if __name__ == "__main__":
    df_1h = run_1h_session_backtest()
    display_results(df_1h, "1-HOUR AXIORY MODEL PERFORMANCE (OCT 12 - 16, 2026)")

    df_15m = run_15m_session_backtest()
    display_results(df_15m, "15-MINUTE LIVE BOT PERFORMANCE (OCT 12 - 16, 2026)")

    # Save to CSV
    combined_session = pd.concat([df_1h, df_15m], ignore_index=True)
    if not combined_session.empty:
        combined_session.to_csv("weekly_backtest_oct12_oct16.csv", index=False)
        print("\nSaved detailed week trade records to: weekly_backtest_oct12_oct16.csv")
