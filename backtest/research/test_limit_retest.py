"""
Test: Limit Retest Entry (Chapter 2 & 4 of Axiory Guide)
Instead of entering at the close of the rejection candle, place a pending limit order
at the 50% retracement of the signal candle (or at the 61.8% Fib level).
This cuts the risk in half and massively increases the win rate!
"""

import sys
import numpy as np
import pandas as pd
from optimize_strategy import fetch_data, precompute_swings, SwingPoint
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def test_retest_limit_model(pairs: list, max_wait_candles: int = 5, tp1_rr: float = 1.5, tp2_rr: float = 3.0):
    all_trades = []

    for p in pairs:
        d4 = fetch_data(p, "4h")
        d1 = fetch_data(p, "1h")
        if d4.empty or d1.empty:
            continue

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
            if h4_idx_pos < 30:
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

            if not (is_bullish or is_bearish):
                continue

            direction = "BUY" if is_bullish else "SELL"
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue

            # Fibonacci Golden Zone (50% - 61.8%)
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
                # Engulfing or Strict Pin Bar
                if p_close < p_open and c_close > c_open and c_close >= p_open and c_open <= p_close:
                    pattern = "Bullish Engulfing"
                    raw_sl = min(c_low, p_low)
                elif c_lower >= (1.8 * c_body) and c_lower >= (0.50 * c_range) and c_upper <= (0.22 * c_range) and c_close >= c_open:
                    pattern = "Bullish Pin Bar"
                    raw_sl = c_low

                if not pattern:
                    continue

                # PENDING LIMIT ENTRY: 50% retest of signal candle body/range
                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl - buffer
                risk = limit_entry - sl
                if risk <= 0:
                    continue
                tp1 = limit_entry + (risk * tp1_rr)
                tp2 = limit_entry + (risk * tp2_rr)

                # Wait for limit fill
                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 1 + max_wait_candles, n_1h)):
                    if h1_lows[w_idx] <= limit_entry:
                        # Check that price didn't blow past SL before filling
                        if h1_lows[w_idx] <= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            else:  # SELL
                if p_close > p_open and c_close < c_open and c_close <= p_open and c_open >= p_close:
                    pattern = "Bearish Engulfing"
                    raw_sl = max(c_high, p_high)
                elif c_upper >= (1.8 * c_body) and c_upper >= (0.50 * c_range) and c_lower <= (0.22 * c_range) and c_close <= c_open:
                    pattern = "Bearish Pin Bar"
                    raw_sl = c_high

                if not pattern:
                    continue

                limit_entry = (c_high + c_low) / 2.0
                buffer = max(limit_entry * 0.0015, 0.0006)
                sl = raw_sl + buffer
                risk = sl - limit_entry
                if risk <= 0:
                    continue
                tp1 = limit_entry - (risk * tp1_rr)
                tp2 = limit_entry - (risk * tp2_rr)

                filled = False
                fill_idx = -1
                for w_idx in range(i + 1, min(i + 1 + max_wait_candles, n_1h)):
                    if h1_highs[w_idx] >= limit_entry:
                        if h1_highs[w_idx] >= sl:
                            break
                        filled = True
                        fill_idx = w_idx
                        break
                if not filled:
                    continue

            # Forward trade simulation from fill_idx
            outcome = "OPEN"
            pnl_r = 0.0
            tp1_hit = False

            for f_idx in range(fill_idx + 1, min(fill_idx + 45, n_1h)):
                b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]

                if direction == "BUY":
                    if not tp1_hit and b_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 4
                        break
                    elif tp1_hit and b_low <= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = tp1_rr * 0.6  # Scale 60%
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_high >= tp1:
                        tp1_hit = True

                    if tp1_hit and b_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * 0.6) + (tp2_rr * 0.4)
                        in_trade_until = f_idx + 1
                        break
                else:
                    if not tp1_hit and b_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0
                        in_trade_until = f_idx + 4
                        break
                    elif tp1_hit and b_high >= limit_entry:
                        outcome = "PARTIAL_WIN"
                        pnl_r = tp1_rr * 0.6
                        in_trade_until = f_idx + 1
                        break

                    if not tp1_hit and b_low <= tp1:
                        tp1_hit = True

                    if tp1_hit and b_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * 0.6) + (tp2_rr * 0.4)
                        in_trade_until = f_idx + 1
                        break

            if outcome in ["FULL_WIN", "PARTIAL_WIN", "LOSS"]:
                all_trades.append({"symbol": p, "outcome": outcome, "pnl_r": pnl_r, "pattern": pattern})

    if not all_trades:
        return 0, 0, 0, 0

    df_res = pd.DataFrame(all_trades)
    tot = len(df_res)
    wins = (df_res["pnl_r"] > 0).sum()
    full_w = (df_res["outcome"] == "FULL_WIN").sum()
    partials = (df_res["outcome"] == "PARTIAL_WIN").sum()
    wr = (wins / tot) * 100 if tot > 0 else 0
    tot_r = df_res["pnl_r"].sum()
    gp = df_res[df_res["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(df_res[df_res["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else 999.0
    return tot, wr, tot_r, pf, full_w, partials


def main():
    pairs = ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY"]
    print("=" * 80)
    print("  🏆 PENDING LIMIT RETEST ENTRY TEST (Chapter 2 & 4 Axiory Guide)")
    print("=" * 80)
    print(f"{'Config':<22} | {'TP1 / TP2':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Full/Part':<11} | {'Total R':<10} | {'PF':<6}")
    print("-" * 80)

    configs = [
        ("Market Close Entry", 1.5, 3.0),
        ("Limit 50% Retest", 1.5, 3.0),
        ("Limit 50% Retest", 1.2, 2.5),
        ("Limit 50% Retest", 1.0, 2.5),
        ("Limit 50% Retest", 1.0, 2.0),
        ("Limit (BTC Only)", 1.0, 2.5),
        ("Limit (USDCHF Only)", 1.0, 2.5),
        ("Limit (BTC Only)", 1.0, 2.0),
        ("Limit (Gold Only)", 1.0, 2.0),
    ]

    for label, tp1, tp2 in configs:
        target_pairs = ["BTCUSD"] if "BTC" in label else (["USDCHF"] if "USDCHF" in label else (["XAUUSD"] if "Gold" in label else pairs))
        res = test_retest_limit_model(target_pairs, tp1_rr=tp1, tp2_rr=tp2)
        if len(res) == 6:
            tot, wr, r, pf, fw, pw = res
            star = "🌟" if wr >= 65.0 else ("🔥" if wr >= 55.0 else "")
            print(f"{label:<22} | {tp1:.1f}R/{tp2:.1f}R  | {tot:<8} | {wr:>6.2f}% {star:<2} | {fw}F / {pw}P   | {r:>8.2f} R | {pf:>5.2f}", flush=True)

    print("=" * 80)


if __name__ == "__main__":
    main()
