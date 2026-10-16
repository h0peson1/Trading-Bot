"""
Axiory Advanced Price Action Strategy Backtester — 70% Win-Rate Target Engine
Based on: Axiory Advanced Price Action Guide (Chapters 2–9)

Institutional Enhancements:
1. True Multi-Timeframe Alignment (4H Market Structure ➔ 1H Execution)
2. 100 SMA Macro Trend Alignment (Chapter 5)
3. Chronological Impulse Verification (Peak > Low for Bullish, Low > High for Bearish)
4. Pending Limit 50% Retest Entry (Chapter 2 & 4)
5. Dynamic Volatility Buffer (0.15% of price)
6. Optimized Scaling: TP1 at 0.9R (Scale 65% & Move SL to BE) ➔ TP2 at 2.0R
"""

import sys
import argparse
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd
from optimize_strategy import fetch_data, precompute_swings, SwingPoint
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def run_axiory_mtf_backtest(pairs: list = None):
    if pairs is None:
        pairs = ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY"]

    print("=" * 80, flush=True)
    print("  🚀 AXIORY ADVANCED PRICE ACTION — 70% WIN-RATE BACKTEST ENGINE", flush=True)
    print(f"  Pairs: {', '.join(pairs)}", flush=True)
    print("  HTF Structure: 4H (HH/HL/LH/LL Swings + 100 SMA Macro Filter + 50%–61.8% Fibs)", flush=True)
    print("  LTF Execution: 1H (Engulfing & Strict Pin Bar Rejections)", flush=True)
    print("  Order Type: Pending Limit 50% Retest of Signal Candle", flush=True)
    print("  Risk Management: TP1 at 0.9R (Scale 65% & Move SL to BE) ➔ TP2 at 2.0R Target", flush=True)
    print("=" * 80, flush=True)

    all_trades = []

    for p in pairs:
        print(f"  [>] Backtesting {p}...", flush=True)
        d4 = fetch_data(p, "4h")
        d1 = fetch_data(p, "1h")
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

        for i in range(100, n_1h - 45):
            if i < in_trade_until:
                continue

            curr_time = h1_times[i]
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

                # Wait for fill within 5 candles
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

            # Forward trade simulation
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False

            for f_idx in range(fill_idx + 1, min(fill_idx + 45, n_1h)):
                b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 6
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 6
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = config.TP1_RR * config.SCALE_TP1_RATIO
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (config.TP1_RR * config.SCALE_TP1_RATIO) + (config.TP2_RR * (1.0 - config.SCALE_TP1_RATIO))
                        in_trade_until = f_idx + 1
                        break

            if outcome in ["FULL_WIN", "PARTIAL_WIN", "LOSS"]:
                all_trades.append({
                    "symbol": p,
                    "signal_time": h1_times[i],
                    "direction": direction,
                    "pattern": pattern,
                    "entry": round(limit_entry, 4),
                    "sl": round(sl, 4),
                    "tp1": round(tp1, 4),
                    "tp2": round(tp2, 4),
                    "outcome": outcome,
                    "pnl_r": round(pnl_r, 2),
                })

    if not all_trades:
        print("\nNo qualified trades found.", flush=True)
        return

    combined = pd.DataFrame(all_trades)
    total_trades = len(combined)
    full_wins = (combined["outcome"] == "FULL_WIN").sum()
    partial_wins = (combined["outcome"] == "PARTIAL_WIN").sum()
    total_profitable = full_wins + partial_wins
    losses = (combined["outcome"] == "LOSS").sum()

    win_rate = (total_profitable / total_trades) * 100 if total_trades > 0 else 0.0
    full_win_rate = (full_wins / total_trades) * 100 if total_trades > 0 else 0.0

    total_r = combined["pnl_r"].sum()
    gp = combined[combined["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(combined[combined["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)

    combined["cum_r"] = combined["pnl_r"].cumsum()
    combined["peak_r"] = combined["cum_r"].cummax()
    combined["drawdown_r"] = combined["peak_r"] - combined["cum_r"]
    max_dd = combined["drawdown_r"].max()

    print("\n" + "=" * 80, flush=True)
    print("        🏆 AXIORY 70% TARGET PERFORMANCE SUMMARY", flush=True)
    print("=" * 80, flush=True)
    print(f"  Total Confluence Trades:  {total_trades}", flush=True)
    print(f"  Profitable Trades:        {total_profitable} ({full_wins} Full 1:2R TP2 + {partial_wins} Partials/BE)", flush=True)
    print(f"  Losing Trades:            {losses}", flush=True)
    print(f"  Overall Win Rate:         {win_rate:.2f}% 🌟", flush=True)
    print(f"  Full Target (1:2R) Rate:  {full_win_rate:.2f}%", flush=True)
    print(f"  Total Net Return:         +{total_r:.2f} R" if total_r >= 0 else f"  Total Net Return:         {total_r:.2f} R", flush=True)
    print(f"  Profit Factor:            {pf:.2f} 🔥", flush=True)
    print(f"  Max Drawdown:             {max_dd:.2f} R", flush=True)
    print("=" * 80, flush=True)

    print("\n📈 Performance Breakdown by Symbol:", flush=True)
    print("-" * 80, flush=True)
    print(f"{'Symbol':<10} | {'Trades':<8} | {'Win %':<10} | {'Full Wins':<10} | {'Partials':<10} | {'Total R':<10} | {'PF':<6}", flush=True)
    print("-" * 80, flush=True)
    for sym, group in combined.groupby("symbol"):
        st = len(group)
        sw = (group["pnl_r"] > 0).sum()
        sfw = (group["outcome"] == "FULL_WIN").sum()
        spw = (group["outcome"] == "PARTIAL_WIN").sum()
        swr = (sw / st) * 100 if st > 0 else 0
        sr = group["pnl_r"].sum()
        sgp = group[group["pnl_r"] > 0]["pnl_r"].sum()
        sgl = abs(group[group["pnl_r"] < 0]["pnl_r"].sum())
        spf = (sgp / sgl) if sgl > 0 else (999.0 if sgp > 0 else 0.0)
        star = "🌟" if swr >= 65.0 else ("🔥" if swr >= 60.0 else "")
        print(f"{sym:<10} | {st:<8} | {swr:>6.2f}% {star:<2} | {sfw:<10} | {spw:<10} | {sr:>8.2f} R | {spf:>5.2f}", flush=True)

    print("-" * 80, flush=True)
    combined.to_csv("axiory_backtest_results.csv", index=False)
    print("\n📁 Upgraded trade log saved to: axiory_backtest_results.csv\n", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Axiory 70% Target Backtester")
    parser.add_argument("--symbols", nargs="+", help="Symbols to test")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY"]
    run_axiory_mtf_backtest(pairs=symbols)


if __name__ == "__main__":
    main()
