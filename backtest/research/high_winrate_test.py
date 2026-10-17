"""
Advanced 70% Win-Rate Target Search:
Adds:
1. London / New York Session Filter (07:00 to 18:00 UTC) — filters low-volume Asian chop
2. 4H 100 SMA Trend Confirmation (Chapter 5 Axiory Guide)
3. Scaling: Take 70% at TP1 (0.8R to 1.0R) and leave 30% runner to 2.0R
"""

import sys
import numpy as np
import pandas as pd
from optimize_strategy import fetch_data, precompute_swings, SwingPoint
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Cache pre-fetched data
DATA_CACHE = {}


def load_all_data(pairs: list):
    for p in pairs:
        if p not in DATA_CACHE:
            d4 = fetch_data(p, "4h")
            d1 = fetch_data(p, "1h")
            if not d4.empty and not d1.empty:
                d4["sma100"] = d4["close"].rolling(window=100).mean()
                DATA_CACHE[p] = (d4, d1)


def test_high_winrate_model(
    pairs: list,
    session_filter: bool = True,
    use_100_sma: bool = True,
    tp1_rr: float = 1.0,
    tp2_rr: float = 2.0,
    scale_tp1: float = 0.70,
):
    all_trades = []

    for p in pairs:
        if p not in DATA_CACHE:
            continue
        d4, d1 = DATA_CACHE[p]

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

            # 1. London & NY Session Filter (07:00 to 18:00 UTC)
            if session_filter and not (7 <= curr_time.hour <= 18):
                continue

            h4_idx_pos = d4.index.searchsorted(curr_time, side="right") - 1
            min_h4 = 100 if use_100_sma else 30
            if h4_idx_pos < min_h4:
                continue

            # 2. 100 SMA Trend Filter (Chapter 5)
            if use_100_sma:
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

            if use_100_sma:
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

            # Candlestick Confirmation Trigger (Engulfing or Strong Pin Bar)
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
                if p_close < p_open and c_close > c_open and c_close >= p_open and c_open <= p_close:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                elif c_lower >= (1.8 * c_body) and c_lower >= (0.50 * c_range) and c_upper <= (0.22 * c_range) and c_close >= c_open:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low
            else:
                if p_close > p_open and c_close < c_open and c_close <= p_open and c_open >= p_close:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                elif c_upper >= (1.8 * c_body) and c_upper >= (0.50 * c_range) and c_lower <= (0.22 * c_range) and c_close <= c_open:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high

            if not pattern:
                continue

            entry = c_close
            buffer = max(entry * 0.0015, 0.0006)

            if direction == "BUY":
                sl = raw_sl - buffer
                risk = entry - sl
                if risk <= 0:
                    continue
                tp1 = entry + (risk * tp1_rr)
                tp2 = entry + (risk * tp2_rr)
            else:
                sl = raw_sl + buffer
                risk = sl - entry
                if risk <= 0:
                    continue
                tp1 = entry - (risk * tp1_rr)
                tp2 = entry - (risk * tp2_rr)

            # Trade execution forward
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False

            for f_idx in range(i + 1, min(i + 45, n_1h)):
                b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 8
                        break
                    elif tp1_hit and b_low <= entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = tp1_rr * scale_tp1
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1))
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 8
                        break
                    elif tp1_hit and b_high >= entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = tp1_rr * scale_tp1
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1))
                        in_trade_until = f_idx + 1
                        break

            if outcome in ["FULL_WIN", "PARTIAL_WIN", "LOSS"]:
                all_trades.append({"symbol": p, "outcome": outcome, "pnl_r": pnl_r, "pattern": pattern})

    if not all_trades:
        return 0, 0, 0, 0

    df_res = pd.DataFrame(all_trades)
    tot = len(df_res)
    wins = (df_res["pnl_r"] > 0).sum()
    wr = (wins / tot) * 100 if tot > 0 else 0
    tot_r = df_res["pnl_r"].sum()
    gp = df_res[df_res["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(df_res[df_res["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else 999.0
    return tot, wr, tot_r, pf


def main():
    pairs = ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY"]
    print("Pre-fetching data for pairs...", flush=True)
    load_all_data(pairs)
    print("Data loaded!\n", flush=True)

    print("=" * 80)
    print("      🎯 HIGH WIN-RATE SEARCH (London/NY Session + 100 SMA Filter)")
    print("=" * 80)
    print(f"{'Test':<20} | {'Session':<8} | {'100 SMA':<8} | {'TP1 / TP2':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Total R':<10} | {'PF':<6}")
    print("-" * 80)

    configs = [
        ("Base (No filters)", False, False, 1.0, 2.5),
        ("London/NY Only", True, False, 1.0, 2.5),
        ("100 SMA Trend", False, True, 1.0, 2.5),
        ("Session + 100 SMA", True, True, 1.0, 2.5),
        ("Session+SMA (0.9R)", True, True, 0.9, 2.0),
        ("Session+SMA (0.8R)", True, True, 0.8, 2.0),
        ("BTC+CHF+Gold (0.8R)", True, True, 0.8, 2.0),
        ("BTCUSD (0.8R/2.0R)", True, True, 0.8, 2.0),
        ("USDCHF (0.8R/2.0R)", True, True, 0.8, 2.0),
    ]

    for label, sess, sma, tp1, tp2 in configs:
        if "BTCUSD" in label and "(" in label:
            target_pairs = ["BTCUSD"]
        elif "USDCHF" in label and "(" in label:
            target_pairs = ["USDCHF"]
        elif "BTC+CHF+Gold" in label:
            target_pairs = ["BTCUSD", "USDCHF", "XAUUSD"]
        else:
            target_pairs = pairs

        tot, wr, r, pf = test_high_winrate_model(target_pairs, session_filter=sess, use_100_sma=sma, tp1_rr=tp1, tp2_rr=tp2)
        star = "🌟" if wr >= 65.0 else ("🔥" if wr >= 55.0 else "")
        print(f"{label:<20} | {str(sess):<8} | {str(sma):<8} | {tp1:.1f}R/{tp2:.1f}R  | {tot:<8} | {wr:>6.2f}% {star:<2} | {r:>8.2f} R | {pf:>5.2f}", flush=True)

    print("=" * 80)


if __name__ == "__main__":
    main()
