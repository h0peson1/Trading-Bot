"""
Full-Year 2025 Backtester: Axiory Advanced Price Action Strategy
Covers: January 1, 2025 to December 31, 2025
Symbols: BTCUSD, XAUUSD, GBPUSD, USDCHF, GBPAUD, EURJPY
HTF: 4H Market Structure & 100 SMA Filter
LTF: 1H Candlestick Confirmation & Pending Limit 50% Retest Entry
Risk Management: TP1 at 0.9R (Scale 65% + Move SL to BE) -> TP2 at 2.0R Runner
"""

import sys
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import yfinance as yf
import config
from optimize_strategy import precompute_swings, YF_TICKER_MAP

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

START_2025 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
END_2025 = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")

SYMBOLS = ["BTCUSD", "XAUUSD", "GBPUSD", "USDCHF", "GBPAUD", "EURJPY"]

def fetch_1h_history(symbol: str) -> pd.DataFrame:
    yf_symbol = YF_TICKER_MAP.get(symbol, symbol)
    # Fetch from late 2024 to early 2026 to ensure warm-up and forward trade completion
    try:
        t = yf.Ticker(yf_symbol)
        df = t.history(start="2024-11-01", end="2026-01-15", interval="1h", auto_adjust=True)
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
        print(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    d4 = df_1h.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last"
    }).dropna()
    d4["sma100"] = d4["close"].rolling(window=100).mean()
    return d4


def run_full_year_backtest():
    print("=" * 88)
    print("  🚀 AXIORY ADVANCED PRICE ACTION — FULL YEAR 2025 BACKTEST")
    print("  Period: 2025-01-01 00:00 UTC to 2025-12-31 23:59 UTC")
    print("  Universe: BTCUSD, XAUUSD, GBPUSD, USDCHF, GBPAUD, EURJPY")
    print("  Rules: 4H HH/HL/LH/LL + 100 SMA + Fib 50-61.8% + 50% Limit Retest + TP1/TP2 Scaling")
    print("=" * 88, flush=True)

    all_trades = []

    for sym in SYMBOLS:
        print(f"  [>] Loading data & simulating {sym} for 2025...", flush=True)
        d1 = fetch_1h_history(sym)
        if d1.empty or len(d1) < 500:
            print(f"      [!] Insufficient data for {sym}", flush=True)
            continue
        
        d4 = resample_4h(d1)
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
            # Restrict entries strictly within year 2025:
            if curr_time < START_2025 or curr_time > END_2025:
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

            # 100 SMA Trend Filter
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

            # Fibonacci Golden Zone Retracement
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

            # Candlestick Confirmation
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
                is_engulf = (p_close < p_open and c_close > c_open and c_close >= p_high and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
                elif is_engulf:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                elif i >= 2:
                    p2_open, p2_close = h1_opens[i-2], h1_closes[i-2]
                    if p2_close < p2_open and c_close > c_open and c_close >= (p2_close + 0.5 * abs(p2_open - p2_close)):
                        pattern = "Morning Star"
                        raw_sl = min(c_low, p_low, h1_lows[i-2])

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

                # Wait for limit retest fill within 5 candles
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
                is_engulf = (p_close > p_open and c_close < c_open and c_close <= p_low and c_body >= (0.50 * c_range))
                if is_pin:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high
                elif is_engulf:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                elif i >= 2:
                    p2_open, p2_close = h1_opens[i-2], h1_closes[i-2]
                    if p2_close > p2_open and c_close < c_open and c_close <= (p2_close - 0.5 * abs(p2_open - p2_close)):
                        pattern = "Evening Star"
                        raw_sl = max(c_high, p_high, h1_highs[i-2])

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

            # Forward trade outcome tracking (up to 60 candles)
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

            all_trades.append({
                "symbol": sym,
                "entry_time": curr_time,
                "month": curr_time.strftime("%Y-%m"),
                "direction": direction,
                "pattern": pattern,
                "entry": round(limit_entry, 5),
                "sl": round(sl, 5),
                "tp1": round(tp1, 5),
                "tp2": round(tp2, 5),
                "outcome": outcome,
                "pnl_r": round(pnl_r, 2),
                "exit_time": exit_time,
                "exit_price": round(exit_price, 5) if exit_price else None
            })

    if not all_trades:
        print("\nNo trades found for 2025.")
        return pd.DataFrame()

    df = pd.DataFrame(all_trades)
    df.to_csv("backtest_2025_results.csv", index=False)
    print(f"\n[✓] Backtest completed. {len(df)} trades saved to backtest_2025_results.csv")
    return df


def analyze_results(df: pd.DataFrame):
    if df.empty:
        return

    total_trades = len(df)
    full_wins = (df["outcome"] == "FULL_WIN").sum()
    partial_wins = (df["outcome"] == "PARTIAL_WIN").sum()
    total_profitable = full_wins + partial_wins
    losses = (df["outcome"] == "LOSS").sum()
    still_open = (df["outcome"] == "OPEN").sum()
    
    closed_trades = total_trades - still_open
    win_rate = (total_profitable / closed_trades) * 100 if closed_trades > 0 else 0.0
    full_win_rate = (full_wins / closed_trades) * 100 if closed_trades > 0 else 0.0

    total_r = df["pnl_r"].sum()
    gp = df[df["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(df[df["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)

    # Max Drawdown
    df_closed = df[df["outcome"].isin(["FULL_WIN", "PARTIAL_WIN", "LOSS"])].copy()
    df_closed["cum_r"] = df_closed["pnl_r"].cumsum()
    df_closed["peak_r"] = df_closed["cum_r"].cummax()
    df_closed["drawdown_r"] = df_closed["peak_r"] - df_closed["cum_r"]
    max_dd = df_closed["drawdown_r"].max() if not df_closed.empty else 0.0

    print("\n" + "=" * 88)
    print("           🏆 2025 FULL YEAR PERFORMANCE SUMMARY (ALL 6 PAIRS)")
    print("=" * 88)
    print(f"  Total Setups Evaluated:    {total_trades}")
    print(f"  Profitable Trades:         {total_profitable} ({full_wins} Full 1:2R TP2 + {partial_wins} Partials/BE)")
    print(f"  Losing Trades:             {losses}")
    print(f"  Overall Win Rate:          {win_rate:.2f}% 🌟")
    print(f"  Full Target (1:2R) Rate:   {full_win_rate:.2f}%")
    print(f"  Total Net Return:          +{total_r:.2f} R" if total_r >= 0 else f"  Total Net Return:          {total_r:.2f} R")
    print(f"  Profit Factor:             {pf:.2f} 🔥")
    print(f"  Max Drawdown:              {max_dd:.2f} R")
    print("=" * 88)

    print("\n📈 PERFORMANCE BREAKDOWN BY ASSET / PAIR (2025):")
    print("-" * 88)
    print(f"{'Symbol':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Full Wins':<10} | {'Partials':<10} | {'Losses':<8} | {'Net Return':<12} | {'PF':<6}")
    print("-" * 88)
    for sym, group in df.groupby("symbol"):
        st = len(group)
        sfw = (group["outcome"] == "FULL_WIN").sum()
        spw = (group["outcome"] == "PARTIAL_WIN").sum()
        sw = sfw + spw
        sl = (group["outcome"] == "LOSS").sum()
        swr = (sw / st) * 100 if st > 0 else 0.0
        sr = group["pnl_r"].sum()
        sgp = group[group["pnl_r"] > 0]["pnl_r"].sum()
        sgl = abs(group[group["pnl_r"] < 0]["pnl_r"].sum())
        spf = (sgp / sgl) if sgl > 0 else (999.0 if sgp > 0 else 0.0)
        star = "🌟" if swr >= 65.0 else ("🔥" if swr >= 55.0 else "")
        print(f"{sym:<10} | {st:<8} | {swr:>6.2f}% {star:<2} | {sfw:<10} | {spw:<10} | {sl:<8} | {sr:>+8.2f} R   | {spf:>5.2f}")
    print("-" * 88)

    print("\n📅 MONTH-BY-MONTH BREAKDOWN (2025):")
    print("-" * 88)
    print(f"{'Month':<10} | {'Trades':<8} | {'Wins':<8} | {'Losses':<8} | {'Win Rate':<10} | {'Monthly PnL (R)':<16} | {'Running PnL (R)'}")
    print("-" * 88)
    monthly = df.groupby("month")
    running_pnl = 0.0
    for m, group in monthly:
        mt = len(group)
        mw = (group["pnl_r"] > 0).sum()
        ml = (group["outcome"] == "LOSS").sum()
        mwr = (mw / mt) * 100 if mt > 0 else 0.0
        mpnl = group["pnl_r"].sum()
        running_pnl += mpnl
        status_icon = "🟢" if mpnl > 0 else ("🔴" if mpnl < 0 else "⚪")
        print(f"{m:<10} | {mt:<8} | {mw:<8} | {ml:<8} | {mwr:>6.1f}%    | {mpnl:>+8.2f} R {status_icon}   | {running_pnl:>+8.2f} R")
    print("-" * 88)


if __name__ == "__main__":
    results_df = run_full_year_backtest()
    if not results_df.empty:
        analyze_results(results_df)
