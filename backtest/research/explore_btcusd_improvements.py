"""
========================================================================================
Systematic Improvement Explorer for BTCUSD
========================================================================================
Tests targeted hypotheses to turn BTCUSD into a profitable, robust portfolio asset:
1. Directional Filtering: Long-Only (Bullish Impulse) vs Both Directions
2. Structural Stop Loss Buffer: Baseline 0.15% vs 0.30% vs 0.50% vs 0.80%
3. Fibonacci Zone Depth: 50% (Baseline) vs 55% vs 61.8% Golden Pocket
4. Target Architecture: TP1=0.9R / TP2=2.0R vs TP1=1.0R / TP2=2.5R vs TP1=1.2R / TP2=3.0R
5. Execution Timeframe: 1H vs 2H vs 4H
6. Session Window: 07-15 UTC vs 12-20 UTC (US ETF Hours) vs 24H
========================================================================================
"""

from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np
import yfinance as yf
from backtest_advanced import (
    BacktestConfig,
    fetch_causal_data,
    simulate_pair,
    calculate_metrics,
    detect_candlestick_pattern,
    PAIR_COSTS,
)
from optimize_strategy import precompute_swings

def simulate_btc_custom(
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    direction_filter: str = "BOTH",  # "BOTH", "BUY_ONLY", "SELL_ONLY"
    sl_buffer_pct: float = 0.0015,
    fib_min_depth: float = 0.50,    # 0.50 or 0.618
    tp1_rr: float = 0.9,
    tp2_rr: float = 2.0,
    scale_tp1: float = 0.65,
    session_start: int = 7,
    session_end: int = 15,
    use_session: bool = True,
    max_wait: int = 5,
) -> List[Dict[str, Any]]:
    symbol = "BTCUSD"
    costs = PAIR_COSTS["BTCUSD"]
    spread = costs["spread"]
    slippage = costs["slippage"]

    h4_highs, h4_lows, h4_closes = df_htf["high"].values, df_htf["low"].values, df_htf["close"].values
    h4_times = df_htf.index
    swings_4h = precompute_swings(h4_highs, h4_lows, h4_times, order=3)
    if len(swings_4h) < 4:
        return []
    swing_4h_indices = np.array([s.index for s in swings_4h])

    ltf_opens = df_ltf["open"].values
    ltf_highs = df_ltf["high"].values
    ltf_lows = df_ltf["low"].values
    ltf_closes = df_ltf["close"].values
    ltf_times = df_ltf.index
    n_ltf = len(df_ltf)

    bar_duration = ltf_times[1] - ltf_times[0] if len(ltf_times) >= 2 else pd.Timedelta(hours=1)
    h4_close_times = pd.DatetimeIndex(df_htf["close_time"])

    trades = []
    in_trade_until = 0

    for i in range(100, n_ltf - 1):
        if i < in_trade_until:
            continue

        candle_open_time = ltf_times[i]
        confirm_time = candle_open_time + bar_duration

        if use_session and (confirm_time.hour < session_start or confirm_time.hour > session_end):
            continue

        h4_idx_pos = int(h4_close_times.searchsorted(confirm_time, side="right")) - 1
        if h4_idx_pos < 100:
            continue

        sma_val = df_htf["sma100"].iloc[h4_idx_pos]
        if pd.isna(sma_val) or sma_val is None:
            continue

        cutoff_4h = h4_idx_pos - 3
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
        if direction_filter == "BUY_ONLY" and direction != "BUY":
            continue
        if direction_filter == "SELL_ONLY" and direction != "SELL":
            continue

        range_span = latest_h.price - latest_l.price
        if range_span <= 0:
            continue

        # Fibonacci Golden Zone
        if direction == "BUY":
            fib_top = latest_h.price - (range_span * fib_min_depth)
            fib_bot = latest_h.price - (range_span * 0.618)
            invalidation = latest_l.price
            in_zone = (ltf_lows[i] <= fib_top) and (ltf_highs[i] >= fib_bot)
            if not in_zone or ltf_closes[i] < invalidation:
                continue
        else:
            fib_top = latest_l.price + (range_span * fib_min_depth)
            fib_bot = latest_l.price + (range_span * 0.618)
            invalidation = latest_h.price
            in_zone = (ltf_highs[i] >= fib_top) and (ltf_lows[i] <= fib_bot)
            if not in_zone or ltf_closes[i] > invalidation:
                continue

        pattern, raw_sl = detect_candlestick_pattern(ltf_opens, ltf_highs, ltf_lows, ltf_closes, i, direction)
        if not pattern or raw_sl is None:
            continue

        limit_entry = (ltf_highs[i] + ltf_lows[i]) / 2.0
        buffer = max(limit_entry * sl_buffer_pct, 10.0)

        if direction == "BUY":
            sl = raw_sl - buffer
            risk_dist = limit_entry - sl
            if risk_dist <= 0:
                continue
            tp1 = limit_entry + (risk_dist * tp1_rr)
            tp2 = limit_entry + (risk_dist * tp2_rr)
        else:
            sl = raw_sl + buffer
            risk_dist = sl - limit_entry
            if risk_dist <= 0:
                continue
            tp1 = limit_entry - (risk_dist * tp1_rr)
            tp2 = limit_entry - (risk_dist * tp2_rr)

        # Pending Limit Fill Check
        filled = False
        fill_idx = -1
        actual_entry = None

        for w_idx in range(i + 1, min(i + max_wait + 1, n_ltf)):
            if direction == "BUY":
                ask_low = ltf_lows[w_idx] + (spread / 2.0)
                if ask_low <= limit_entry:
                    actual_entry = limit_entry + (spread / 2.0) + slippage
                    filled = True
                    fill_idx = w_idx
                    break
            else:
                bid_high = ltf_highs[w_idx] - (spread / 2.0)
                if bid_high >= limit_entry:
                    actual_entry = limit_entry - (spread / 2.0) - slippage
                    filled = True
                    fill_idx = w_idx
                    break

        if not filled:
            continue

        round_trip_cost = spread + (2.0 * slippage)
        friction_r = round_trip_cost / risk_dist

        outcome = "OPEN"
        pnl_r = 0.0
        exit_time = None
        exit_price = None
        be_level = limit_entry
        tp1_hit = False

        for f_idx in range(fill_idx, min(fill_idx + 120, n_ltf)):
            b_high, b_low = ltf_highs[f_idx], ltf_lows[f_idx]
            exit_time = ltf_times[f_idx]

            if direction == "BUY":
                bid_low = b_low - (spread / 2.0)
                bid_high = b_high - (spread / 2.0)

                if not tp1_hit:
                    if bid_low <= sl and bid_high >= tp1:
                        outcome = "LOSS"
                        pnl_r = -1.0 - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif bid_low <= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0 - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif bid_high >= tp1:
                        tp1_hit = True
                        if bid_low <= be_level:
                            outcome = "PARTIAL_WIN"
                            pnl_r = (tp1_rr * scale_tp1) - friction_r
                            in_trade_until = f_idx + 1
                            break
                        elif bid_high >= tp2:
                            outcome = "FULL_WIN"
                            pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1)) - friction_r
                            in_trade_until = f_idx + 1
                            break
                else:
                    if bid_low <= be_level:
                        outcome = "PARTIAL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif bid_high >= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1)) - friction_r
                        in_trade_until = f_idx + 1
                        break

            else:  # SELL
                ask_high = b_high + (spread / 2.0)
                ask_low = b_low + (spread / 2.0)

                if not tp1_hit:
                    if ask_high >= sl and ask_low <= tp1:
                        outcome = "LOSS"
                        pnl_r = -1.0 - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif ask_high >= sl:
                        outcome = "LOSS"
                        pnl_r = -1.0 - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif ask_low <= tp1:
                        tp1_hit = True
                        if ask_high >= be_level:
                            outcome = "PARTIAL_WIN"
                            pnl_r = (tp1_rr * scale_tp1) - friction_r
                            in_trade_until = f_idx + 1
                            break
                        elif ask_low <= tp2:
                            outcome = "FULL_WIN"
                            pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1)) - friction_r
                            in_trade_until = f_idx + 1
                            break
                else:
                    if ask_high >= be_level:
                        outcome = "PARTIAL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) - friction_r
                        in_trade_until = f_idx + 1
                        break
                    elif ask_low <= tp2:
                        outcome = "FULL_WIN"
                        pnl_r = (tp1_rr * scale_tp1) + (tp2_rr * (1.0 - scale_tp1)) - friction_r
                        in_trade_until = f_idx + 1
                        break

        if outcome in ["FULL_WIN", "PARTIAL_WIN", "LOSS"]:
            trades.append({
                "symbol": "BTCUSD",
                "confirm_time": confirm_time,
                "fill_time": ltf_times[fill_idx],
                "direction": direction,
                "pattern": pattern,
                "outcome": outcome,
                "pnl_r": round(pnl_r, 3),
                "friction_r": round(friction_r, 4),
                "exit_time": exit_time,
            })

    return trades


def run_experiment(name: str, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"name": name, "n": 0}
    df = pd.DataFrame(trades)
    df.sort_values("confirm_time", inplace=True)
    t_min = df["confirm_time"].min()
    t_max = df["confirm_time"].max()
    cutoff = t_min + (t_max - t_min) * 0.70

    is_trades = [t for t in trades if t["confirm_time"] < cutoff]
    oos_trades = [t for t in trades if t["confirm_time"] >= cutoff]

    full_m = calculate_metrics(trades)
    is_m = calculate_metrics(is_trades)
    oos_m = calculate_metrics(oos_trades)

    return {
        "name": name,
        "n": full_m["n_trades"],
        "wr": full_m["win_rate"],
        "net_r": full_m["net_r"],
        "pf": full_m["profit_factor"],
        "dd": full_m["max_drawdown_pct"],
        "is_net": is_m["net_r"],
        "is_pf": is_m["profit_factor"],
        "oos_net": oos_m["net_r"],
        "oos_pf": oos_m["profit_factor"],
        "oos_exp": oos_m["expectancy_r"],
    }


def main():
    print("=" * 115)
    print("  🔬 TESTING TARGETED IMPROVEMENTS FOR BTCUSD ON 1H/4H INTRADAY")
    print("=" * 115)

    df_htf, df_ltf = fetch_causal_data("BTCUSD", interval="1h", period="730d")

    exps = []

    # 1. Baseline
    t1 = simulate_btc_custom(df_htf, df_ltf, direction_filter="BOTH", session_start=7, session_end=15, sl_buffer_pct=0.0015)
    exps.append(run_experiment("1. Baseline (07-15 UTC, Both, buffer=0.15%)", t1))

    # 2. Long-Only (Bullish setups only)
    t2 = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", session_start=7, session_end=15, sl_buffer_pct=0.0015)
    exps.append(run_experiment("2. Long-Only (07-15 UTC, BUY only, buffer=0.15%)", t2))

    # 3. Buffer sizing variations on Long-Only
    for b_pct, label in [(0.003, "0.30%"), (0.005, "0.50%"), (0.008, "0.80%")]:
        t = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", session_start=7, session_end=15, sl_buffer_pct=b_pct)
        exps.append(run_experiment(f"3. Long-Only + SL Buffer {label}", t))

    # 4. Long-Only with 24H Continuous vs US ETF hours (12-20 UTC)
    t_24h = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", use_session=False, sl_buffer_pct=0.005)
    exps.append(run_experiment("4A. Long-Only + Buffer 0.50% (24-Hour Continuous)", t_24h))

    t_us = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", session_start=12, session_end=20, sl_buffer_pct=0.005)
    exps.append(run_experiment("4B. Long-Only + Buffer 0.50% (US ETF Hours 12-20 UTC)", t_us))

    # 5. Target Architecture (Wider targets for Crypto volatility)
    t_tp1 = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", sl_buffer_pct=0.005, tp1_rr=1.0, tp2_rr=2.5, session_start=7, session_end=15)
    exps.append(run_experiment("5A. Long-Only + Buffer 0.50% + TP1=1.0R/TP2=2.5R", t_tp1))

    t_tp2 = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", sl_buffer_pct=0.005, tp1_rr=1.2, tp2_rr=3.0, session_start=7, session_end=15)
    exps.append(run_experiment("5B. Long-Only + Buffer 0.50% + TP1=1.2R/TP2=3.0R", t_tp2))

    # 6. Deep Golden Pocket (55% or 60% pullback)
    t_fib = simulate_btc_custom(df_htf, df_ltf, direction_filter="BUY_ONLY", sl_buffer_pct=0.005, fib_min_depth=0.55, session_start=7, session_end=15)
    exps.append(run_experiment("6. Long-Only + Buffer 0.50% + Deep Fib (55%)", t_fib))

    # Print results
    header = f"{'Experiment':<52} | {'Trades':<6} | {'WR%':<6} | {'Net R':<8} | {'PF':<5} | {'MaxDD%':<7} | {'IS NetR':<8} | {'IS PF':<5} | {'OOS NetR':<8} | {'OOS PF':<5} | {'OOS Exp':<7}"
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for e in exps:
        print(f"{e['name']:<52} | {e['n']:>5}  | {e['wr']:>5.1f}% | {e['net_r']:>+7.2f}R | {e['pf']:>4.2f} | {e['dd']:>5.1f}% | {e['is_net']:>+7.2f}R | {e['is_pf']:>4.2f} | {e['oos_net']:>+7.2f}R | {e['oos_pf']:>4.2f} | {e['oos_exp']:>+6.2f}R")
    print("=" * len(header))

if __name__ == "__main__":
    main()
