"""
Optimization Explorer — Axiory Advanced Price Action Strategy
Tests variations of:
1. Candlestick selection (Strict Engulfing & Pin Bar vs All)
2. Fib depth (61.8% Golden Pocket vs 50% Shallow)
3. TP1 targets (1.0R, 1.2R, 1.5R) and TP2 targets (2.0R, 2.5R, 3.0R)
4. Rejection candle momentum/expansion filter (range >= 1.1x avg)
5. Symbol focus (top trenders: BTC, USDCHF, XAUUSD, GBPUSD)
"""

import sys
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd
import yfinance as yf
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

YF_TICKER_MAP = {
    "BTCUSD": "BTC-USD",
    "XAUUSD": "GC=F",
    "GBPUSD": "GBPUSD=X",
    "USDCHF": "USDCHF=X",
    "GBPAUD": "GBPAUD=X",
    "EURJPY": "EURJPY=X",
}


def fetch_data(symbol: str, interval: str, period: str = "730d") -> pd.DataFrame:
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
    except Exception:
        return pd.DataFrame()


class SwingPoint:
    __slots__ = ("index", "time", "price", "swing_type", "label")
    def __init__(self, index: int, time: Any, price: float, swing_type: str):
        self.index = index
        self.time = time
        self.price = price
        self.swing_type = swing_type
        self.label = ""


def precompute_swings(highs: np.ndarray, lows: np.ndarray, times: np.ndarray, order: int = 3) -> List[SwingPoint]:
    n = len(highs)
    swings: List[SwingPoint] = []
    for i in range(order, n - order):
        h, l = highs[i], lows[i]
        if all(h > highs[i - o] and h > highs[i + o] for o in range(1, order + 1)):
            swings.append(SwingPoint(i, times[i], float(h), "HIGH"))
        if all(l < lows[i - o] and l < lows[i + o] for o in range(1, order + 1)):
            swings.append(SwingPoint(i, times[i], float(l), "LOW"))
    swings.sort(key=lambda s: s.index)

    last_h, last_l = None, None
    for s in swings:
        if s.swing_type == "HIGH":
            s.label = "HH" if (last_h and s.price > last_h.price) else ("LH" if last_h else "HIGH")
            last_h = s
        elif s.swing_type == "LOW":
            s.label = "HL" if (last_l and s.price > last_l.price) else ("LL" if last_l else "LOW")
            last_l = s
    return swings


def simulate_strategy(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    tp1_rr: float = 1.0,
    tp2_rr: float = 2.5,
    deep_fib_only: bool = False,
    require_expansion: bool = True,
    patterns_filter: str = "ENGULFING_AND_PIN",
) -> List[dict]:
    h4_highs, h4_lows, h4_times = df_4h["high"].values, df_4h["low"].values, df_4h.index
    swings_4h = precompute_swings(h4_highs, h4_lows, h4_times, order=config.SWING_ORDER)
    if len(swings_4h) < 4:
        return []
    swing_4h_indices = np.array([s.index for s in swings_4h])

    h1_opens = df_1h["open"].values
    h1_highs = df_1h["high"].values
    h1_lows = df_1h["low"].values
    h1_closes = df_1h["close"].values
    h1_times = df_1h.index
    n_1h = len(df_1h)

    trades = []
    in_trade_until = 0

    for i in range(100, n_1h - 45):
        if i < in_trade_until:
            continue

        curr_time = h1_times[i]
        h4_idx_pos = df_4h.index.searchsorted(curr_time, side="right") - 1
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
        is_bullish = (latest_h.label == "HH" and latest_l.label == "HL")
        is_bearish = (latest_h.label == "LH" and latest_l.label == "LL")
        if not (is_bullish or is_bearish):
            continue

        direction = "BUY" if is_bullish else "SELL"

        # Chronology
        if direction == "BUY":
            if latest_h.index <= latest_l.index:
                continue
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue
            fib50 = latest_h.price - (range_span * 0.50)
            fib618 = latest_h.price - (range_span * 0.618)
            invalidation = latest_l.price

            # Check Golden Zone
            zone_top = fib618 if deep_fib_only else fib50
            in_zone = (h1_lows[i] <= zone_top) and (h1_highs[i] >= fib618)
            if not in_zone or h1_closes[i] < invalidation:
                continue
        else:
            if latest_l.index <= latest_h.index:
                continue
            range_span = latest_h.price - latest_l.price
            if range_span <= 0:
                continue
            fib50 = latest_l.price + (range_span * 0.50)
            fib618 = latest_l.price + (range_span * 0.618)
            invalidation = latest_h.price

            zone_bottom = fib618 if deep_fib_only else fib50
            in_zone = (h1_highs[i] >= zone_bottom) and (h1_lows[i] <= fib618)
            if not in_zone or h1_closes[i] > invalidation:
                continue

        # Candlestick Pattern Detection
        c_open, c_high, c_low, c_close = h1_opens[i], h1_highs[i], h1_lows[i], h1_closes[i]
        p_open, p_high, p_low, p_close = h1_opens[i-1], h1_highs[i-1], h1_lows[i-1], h1_closes[i-1]
        c_range = c_high - c_low
        if c_range <= 0:
            continue
        c_body = abs(c_close - c_open)
        c_upper = c_high - max(c_open, c_close)
        c_lower = min(c_open, c_close) - c_low

        # Expansion Filter (Candle range >= 1.1x 10-period avg range)
        if require_expansion:
            avg_10 = np.mean(h1_highs[i-10:i] - h1_lows[i-10:i])
            if c_range < (1.1 * avg_10):
                continue

        pattern_name = None
        raw_sl = None

        if direction == "BUY":
            # Engulfing
            if p_close < p_open and c_close > c_open and c_close >= p_open and c_open <= p_close:
                pattern_name = "Bullish Engulfing"
                raw_sl = min(c_low, p_low)
            # Strict Pin Bar
            elif c_lower >= (2.0 * c_body) and c_lower >= (0.55 * c_range) and c_upper <= (0.20 * c_range) and c_close >= c_open:
                pattern_name = "Bullish Pin Bar"
                raw_sl = c_low
            elif patterns_filter == "ALL":
                # Morning star
                p2_open, p2_high, p2_low, p2_close = h1_opens[i-2], h1_highs[i-2], h1_lows[i-2], h1_closes[i-2]
                if p2_close < p2_open and c_close > c_open and c_close >= (p2_close + 0.5 * abs(p2_open - p2_close)):
                    pattern_name = "Morning Star"
                    raw_sl = min(c_low, p_low, p2_low)

        else:  # SELL
            # Engulfing
            if p_close > p_open and c_close < c_open and c_close <= p_open and c_open >= p_close:
                pattern_name = "Bearish Engulfing"
                raw_sl = max(c_high, p_high)
            # Strict Pin Bar
            elif c_upper >= (2.0 * c_body) and c_upper >= (0.55 * c_range) and c_lower <= (0.20 * c_range) and c_close <= c_open:
                pattern_name = "Bearish Pin Bar"
                raw_sl = c_high
            elif patterns_filter == "ALL":
                p2_open, p2_high, p2_low, p2_close = h1_opens[i-2], h1_highs[i-2], h1_lows[i-2], h1_closes[i-2]
                if p2_close > p2_open and c_close < c_open and c_close <= (p2_close - 0.5 * abs(p2_open - p2_close)):
                    pattern_name = "Evening Star"
                    raw_sl = max(c_high, p_high, p2_high)

        if not pattern_name:
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

        # Simulation
        outcome = "OPEN"
        pnl_r = 0.0
        tp1_hit = False

        for f_idx in range(i + 1, min(i + 45, n_1h)):
            b_high, b_low = h1_highs[f_idx], h1_lows[f_idx]

            if direction == "BUY":
                if not tp1_hit and b_low <= sl:
                    outcome = "LOSS"
                    pnl_r = -1.0
                    in_trade_until = f_idx + 6
                    break
                elif tp1_hit and b_low <= entry:
                    outcome = "PARTIAL_WIN"
                    pnl_r = tp1_rr * 0.6  # Scale 60% at TP1
                    in_trade_until = f_idx + 1
                    break

                if not tp1_hit and b_high >= tp1:
                    tp1_hit = True

                if tp1_hit and b_high >= tp2:
                    outcome = "FULL_WIN"
                    # 60% at tp1_rr + 40% at tp2_rr
                    pnl_r = (tp1_rr * 0.6) + (tp2_rr * 0.4)
                    in_trade_until = f_idx + 1
                    break
            else:
                if not tp1_hit and b_high >= sl:
                    outcome = "LOSS"
                    pnl_r = -1.0
                    in_trade_until = f_idx + 6
                    break
                elif tp1_hit and b_high >= entry:
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
            trades.append({"outcome": outcome, "pnl_r": pnl_r, "pattern": pattern_name})

    return trades


def main():
    pairs = ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY", "GBPAUD"]
    print("Pre-fetching data for 6 pairs...", flush=True)
    data_cache = {}
    for p in pairs:
        d4 = fetch_data(p, "4h")
        d1 = fetch_data(p, "1h")
        if not d4.empty and not d1.empty:
            data_cache[p] = (d4, d1)
            print(f"  [✓] {p} loaded: {len(d4)} 4H bars, {len(d1)} 1H bars", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("               🚀 AXIORY WIN-RATE OPTIMIZATION GRID", flush=True)
    print("=" * 80, flush=True)
    print(f"{'Config ID':<10} | {'Patterns':<14} | {'TP1 / TP2':<11} | {'Expansion':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Total R':<10} | {'PF':<6}", flush=True)
    print("-" * 80, flush=True)

    experiments = [
        {"id": "EXP-1", "patterns": "ALL", "tp1": 1.5, "tp2": 3.0, "exp": False, "deep": False},
        {"id": "EXP-2", "patterns": "ENGULF_PIN", "tp1": 1.5, "tp2": 3.0, "exp": False, "deep": False},
        {"id": "EXP-3", "patterns": "ENGULF_PIN", "tp1": 1.2, "tp2": 2.5, "exp": False, "deep": False},
        {"id": "EXP-4", "patterns": "ENGULF_PIN", "tp1": 1.0, "tp2": 2.5, "exp": False, "deep": False},
        {"id": "EXP-5", "patterns": "ENGULF_PIN", "tp1": 1.0, "tp2": 2.0, "exp": True, "deep": False},
        {"id": "EXP-6", "patterns": "ENGULF_PIN", "tp1": 1.0, "tp2": 2.0, "exp": True, "deep": True},
        {"id": "EXP-7", "patterns": "ENGULF_ONLY", "tp1": 1.0, "tp2": 2.0, "exp": True, "deep": False},
        {"id": "EXP-8", "patterns": "ENGULF_ONLY", "tp1": 1.0, "tp2": 2.5, "exp": False, "deep": False},
    ]

    for exp in experiments:
        all_tr = []
        for p, (d4, d1) in data_cache.items():
            pat_f = "ALL" if exp["patterns"] == "ALL" else ("ENGULFING_ONLY" if exp["patterns"] == "ENGULF_ONLY" else "ENGULFING_AND_PIN")
            trs = simulate_strategy(
                d4, d1,
                tp1_rr=exp["tp1"],
                tp2_rr=exp["tp2"],
                deep_fib_only=exp["deep"],
                require_expansion=exp["exp"],
                patterns_filter=pat_f,
            )
            all_tr.extend(trs)

        if not all_tr:
            continue

        df_res = pd.DataFrame(all_tr)
        tot = len(df_res)
        wins = (df_res["pnl_r"] > 0).sum()
        wr = (wins / tot) * 100 if tot > 0 else 0
        tot_r = df_res["pnl_r"].sum()
        gp = df_res[df_res["pnl_r"] > 0]["pnl_r"].sum()
        gl = abs(df_res[df_res["pnl_r"] < 0]["pnl_r"].sum())
        pf = (gp / gl) if gl > 0 else 999.0

        highlight = "🔥" if wr >= 55.0 else ""
        print(f"{exp['id']:<10} | {exp['patterns']:<14} | {exp['tp1']:.1f}R / {exp['tp2']:.1f}R | {str(exp['exp']):<10} | {tot:<8} | {wr:>6.2f}% {highlight:<2} | {tot_r:>8.2f} R | {pf:>5.2f}", flush=True)

    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
