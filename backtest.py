"""
LDE Strategy Backtester — Institutional Limit Retest into FVG Engine
Workflow:
1. Liquidity Sweep: Price sweeps prior swing high/low and rejects.
2. Displacement: Sharp impulsive move leaving a Fair Value Gap (FVG).
3. Limit Retest Entry: Instead of chasing at the candle top, wait for price to pull back
   into the FVG / 50% discount equilibrium.
4. Scale-Out Management: TP1 at 1:1.5R (take 50% profit + move SL to BE), TP2 at 1:2.5R.
"""

import sys
import argparse
from datetime import datetime
import pandas as pd
import yfinance as yf
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fetch_historical_candles(ticker: str, interval: str, period: str = "1y") -> pd.DataFrame:
    interval_periods = {
        "15m": "1mo",
        "30m": "1mo",
        "1h": "6mo",
        "4h": "1y",
        "1d": "2y",
    }
    actual_period = interval_periods.get(interval, period)
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=actual_period, interval=interval, auto_adjust=True)
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={c: c.lower() for c in df.columns})
    required = ["open", "high", "low", "close"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    df = df[required].copy()
    df.dropna(inplace=True)
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    return df


def candle_body_ratio(row) -> float:
    body = abs(row["close"] - row["open"])
    total = row["high"] - row["low"]
    return body / total if total > 0 else 0.0


def backtest_pair_fvg_retest(
    symbol_name: str,
    ticker: str,
    timeframe: str,
    lookback: int = 50,
    max_retest_candles: int = 15,
    max_holding_candles: int = 60,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.5,
) -> pd.DataFrame:
    df = fetch_historical_candles(ticker, timeframe)
    min_required = lookback + 55
    if len(df) < min_required:
        return pd.DataFrame()

    trades = []
    in_trade_until = 0

    for i in range(lookback + 20, len(df) - max_retest_candles - 5):
        if i < in_trade_until:
            continue

        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]

        # Prior swing high / low across lookback
        prior_window = df.iloc[i - lookback : i - 2]
        prior_low = prior_window["low"].min()
        prior_high = prior_window["high"].max()

        # Displacement baseline
        compare = df.iloc[i - 8 : i - 2]
        avg_range = (compare["high"] - compare["low"]).mean()
        if avg_range == 0:
            continue

        # -------------------------------------------------------------
        # 1. Bullish Setup Detection: Sweep -> Displacement -> Bullish FVG
        # -------------------------------------------------------------
        # Bullish FVG occurs when c3['low'] > c1['high']
        is_bull_sweep = (c2["low"] < prior_low or c1["low"] < prior_low) and c3["close"] > prior_low
        is_bull_disp = (
            (c2["high"] - c2["low"] >= avg_range * 1.2)
            and candle_body_ratio(c2) >= 0.65
            and c2["close"] > c2["open"]
        ) or (
            (c3["high"] - c3["low"] >= avg_range * 1.2)
            and candle_body_ratio(c3) >= 0.65
            and c3["close"] > c3["open"]
        )
        has_bull_fvg = c3["low"] > c1["high"]

        # -------------------------------------------------------------
        # 2. Bearish Setup Detection: Sweep -> Displacement -> Bearish FVG
        # -------------------------------------------------------------
        # Bearish FVG occurs when c3['high'] < c1['low']
        is_bear_sweep = (c2["high"] > prior_high or c1["high"] > prior_high) and c3["close"] < prior_high
        is_bear_disp = (
            (c2["high"] - c2["low"] >= avg_range * 1.2)
            and candle_body_ratio(c2) >= 0.65
            and c2["close"] < c2["open"]
        ) or (
            (c3["high"] - c3["low"] >= avg_range * 1.2)
            and candle_body_ratio(c3) >= 0.65
            and c3["close"] < c3["open"]
        )
        has_bear_fvg = c3["high"] < c1["low"]

        direction = None
        limit_entry = None
        sl = None

        if is_bull_sweep and is_bull_disp and has_bull_fvg:
            direction = "BUY"
            # Retest level: 50% equilibrium into the FVG (c1['high'] to c3['low'])
            limit_entry = (c1["high"] + c3["low"]) / 2.0
            sl = min(c1["low"], c2["low"], c3["low"])
        elif is_bear_sweep and is_bear_disp and has_bear_fvg:
            direction = "SELL"
            # Retest level: 50% equilibrium into the FVG (c3['high'] to c1['low'])
            limit_entry = (c1["low"] + c3["high"]) / 2.0
            sl = max(c1["high"], c2["high"], c3["high"])

        if not direction:
            continue

        risk = abs(limit_entry - sl)
        if risk <= 0:
            continue

        tp1 = limit_entry + (risk * tp1_rr) if direction == "BUY" else limit_entry - (risk * tp1_rr)
        tp2 = limit_entry + (risk * tp2_rr) if direction == "BUY" else limit_entry - (risk * tp2_rr)

        # -------------------------------------------------------------
        # 3. Simulate Waiting for Retest Fill (Forward up to 15 candles)
        # -------------------------------------------------------------
        filled = False
        fill_idx = None

        for k in range(i + 1, min(i + 1 + max_retest_candles, len(df))):
            f_candle = df.iloc[k]
            if direction == "BUY":
                # Price invalidates if it violates SL before filling
                if f_candle["low"] <= sl:
                    break
                # Price pulls back and fills the limit order
                if f_candle["low"] <= limit_entry:
                    filled = True
                    fill_idx = k
                    break
            else:  # SELL
                if f_candle["high"] >= sl:
                    break
                if f_candle["high"] >= limit_entry:
                    filled = True
                    fill_idx = k
                    break

        if not filled:
            continue  # Order never filled; no risk taken!

        # -------------------------------------------------------------
        # 4. Simulate Trade Outcome from Fill Index
        # -------------------------------------------------------------
        current_sl = sl
        tp1_hit = False
        outcome = "OPEN"
        pnl_r = 0.0
        exit_time = df.index[fill_idx]
        candles_held = 0

        for m in range(fill_idx + 1, min(fill_idx + 1 + max_holding_candles, len(df))):
            c_fwd = df.iloc[m]
            candles_held += 1
            exit_time = df.index[m]

            if direction == "BUY":
                # Check TP1 hit -> scale out 50%, move SL to BE
                if not tp1_hit and c_fwd["high"] >= tp1:
                    tp1_hit = True
                    current_sl = limit_entry  # Break-Even

                # Check SL hit
                if c_fwd["low"] <= current_sl:
                    if tp1_hit:
                        outcome = "PARTIAL_WIN"
                        pnl_r = (0.5 * tp1_rr) + 0.0  # 50% at 1.5R, 50% at BE = +0.75R
                    else:
                        outcome = "LOSS"
                        pnl_r = -1.0
                    in_trade_until = m
                    break

                # Check TP2 hit (full target reached)
                if c_fwd["high"] >= tp2:
                    outcome = "FULL_WIN"
                    pnl_r = (0.5 * tp1_rr) + (0.5 * tp2_rr)  # 50% at 1.5R + 50% at 2.5R = +2.0R
                    in_trade_until = m
                    break

            else:  # SELL
                if not tp1_hit and c_fwd["low"] <= tp1:
                    tp1_hit = True
                    current_sl = limit_entry  # Break-Even

                if c_fwd["high"] >= current_sl:
                    if tp1_hit:
                        outcome = "PARTIAL_WIN"
                        pnl_r = (0.5 * tp1_rr) + 0.0
                    else:
                        outcome = "LOSS"
                        pnl_r = -1.0
                    in_trade_until = m
                    break

                if c_fwd["low"] <= tp2:
                    outcome = "FULL_WIN"
                    pnl_r = (0.5 * tp1_rr) + (0.5 * tp2_rr)
                    in_trade_until = m
                    break

        if outcome == "OPEN":
            # Timeout closing
            c_last = df.iloc[min(fill_idx + max_holding_candles, len(df) - 1)]
            final_pnl = ((c_last["close"] - limit_entry) / risk) if direction == "BUY" else ((limit_entry - c_last["close"]) / risk)
            outcome = "PARTIAL_WIN" if final_pnl > 0 else "LOSS"
            pnl_r = max(-1.0, min(tp2_rr, final_pnl))
            in_trade_until = min(fill_idx + max_holding_candles, len(df) - 1)

        trades.append({
            "symbol": symbol_name,
            "timeframe": timeframe,
            "signal_time": df.index[i],
            "fill_time": df.index[fill_idx],
            "exit_time": exit_time,
            "direction": direction,
            "entry": limit_entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "outcome": outcome,
            "pnl_r": pnl_r,
            "candles_held": candles_held,
        })

    return pd.DataFrame(trades)


def run_fvg_retest_backtest(pairs: list = None, timeframes: list = None):
    if pairs is None:
        pairs = list(config.SYMBOLS.keys())
    if timeframes is None:
        timeframes = ["1h", "4h"]

    print("=" * 70)
    print("  🚀 INSTITUTIONAL FVG RETEST BACKTEST ENGINE")
    print(f"  Pairs: {', '.join(pairs)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print("  Execution Mode: Limit Retest into Fair Value Gap (FVG 50%)")
    print("  Risk Management: Scale 50% at 1:1.5R (Move SL to BE) | Runner to 1:2.5R")
    print("=" * 70)

    all_trades = []
    for sym in pairs:
        ticker = config.SYMBOLS.get(sym, sym)
        for tf in timeframes:
            df_trades = backtest_pair_fvg_retest(sym, ticker, tf)
            if not df_trades.empty:
                all_trades.append(df_trades)

    if not all_trades:
        print("\nNo FVG retest trades qualified.")
        return

    combined = pd.concat(all_trades, ignore_index=True)
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

    print("\n" + "=" * 70)
    print("                📊 FVG RETEST PERFORMANCE SUMMARY")
    print("=" * 70)
    print(f"  Total Trades Filled:      {total_trades}")
    print(f"  Profitable Trades:        {total_profitable} ({full_wins} Full + {partial_wins} Partials)")
    print(f"  Losing Trades:            {losses}")
    print(f"  Overall Win Rate:         {win_rate:.2f}% 🔥")
    print(f"  Full Target Win Rate:     {full_win_rate:.2f}%")
    print(f"  Total Net Return:         +{total_r:.2f} R" if total_r >= 0 else f"  Total Net Return:         {total_r:.2f} R")
    print(f"  Profit Factor:            {pf:.2f}")
    print(f"  Max Drawdown:             {max_dd:.2f} R")
    print("=" * 70)

    print("\n📈 Performance Breakdown by Symbol:")
    print("-" * 70)
    print(f"{'Symbol':<10} | {'Trades':<8} | {'Win %':<8} | {'Total R':<10} | {'PF':<8}")
    print("-" * 70)
    for sym, group in combined.groupby("symbol"):
        st = len(group)
        sw = (group["pnl_r"] > 0).sum()
        swr = (sw / st) * 100 if st > 0 else 0
        sr = group["pnl_r"].sum()
        sgp = group[group["pnl_r"] > 0]["pnl_r"].sum()
        sgl = abs(group[group["pnl_r"] < 0]["pnl_r"].sum())
        spf = (sgp / sgl) if sgl > 0 else (999.0 if sgp > 0 else 0.0)
        print(f"{sym:<10} | {st:<8} | {swr:>6.1f}% | {sr:>8.2f} R | {spf:>6.2f}")

    print("\n⏰ Performance Breakdown by Timeframe:")
    print("-" * 70)
    print(f"{'Timeframe':<10} | {'Trades':<8} | {'Win %':<8} | {'Total R':<10} | {'PF':<8}")
    print("-" * 70)
    for tf, group in combined.groupby("timeframe"):
        tt = len(group)
        tw = (group["pnl_r"] > 0).sum()
        twr = (tw / tt) * 100 if tt > 0 else 0
        tr = group["pnl_r"].sum()
        tgp = group[group["pnl_r"] > 0]["pnl_r"].sum()
        tgl = abs(group[group["pnl_r"] < 0]["pnl_r"].sum())
        tpf = (tgp / tgl) if tgl > 0 else (999.0 if tgp > 0 else 0.0)
        print(f"{tf.upper():<10} | {tt:<8} | {twr:>6.1f}% | {tr:>8.2f} R | {tpf:>6.2f}")
    print("-" * 70)

    combined.to_csv("fvg_retest_results.csv", index=False)
    print("\n📁 Trade logs saved to: fvg_retest_results.csv\n")


def main():
    parser = argparse.ArgumentParser(description="Backtest FVG Retest Strategy")
    parser.add_argument("--symbols", nargs="+", help="Symbols to test")
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h"], help="Timeframes to test")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else list(config.SYMBOLS.keys())
    run_fvg_retest_backtest(pairs=symbols, timeframes=args.timeframes)


if __name__ == "__main__":
    main()
