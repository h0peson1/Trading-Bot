"""
========================================================================================
Systematic Strategy Improvement Explorer for Axiory Advanced Price Action (XAU & EURJPY)
========================================================================================
Tests controlled, hypothesis-driven variations:
1. Session Timing Window: 07-14 UTC vs 07-15 UTC vs 07-16 UTC vs 07-18 UTC (Baseline)
2. Retest Fill Wait Expiry: 3, 4, 5 (Baseline), 6 bars
3. Target Architecture: TP1 at 0.9R vs 1.0R, Scale Ratio 65% (Baseline) vs 60% vs 70%
4. Trend Confirmation Strength: 100 SMA slope / alignment

Evaluates on:
- In-Sample (70%) vs Out-of-Sample (30%) chronological date split
- Profit Factor retention
- Expectancy retention
- Trade sample size preservation (must maintain statistical relevance)
- Max Drawdown reduction
========================================================================================
"""

import copy
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple

from backtest_advanced import (
    BacktestConfig,
    fetch_causal_data,
    simulate_pair,
    calculate_metrics,
)

TARGET_SYMBOLS = ("EURJPY", "XAUUSD")

def evaluate_configuration(name: str, config: BacktestConfig, datasets: Dict[str, Any]) -> Dict[str, Any]:
    all_trades = []
    for sym in TARGET_SYMBOLS:
        df_htf, df_ltf = datasets[sym]
        sym_trades, stats = simulate_pair(sym, df_htf, df_ltf, config=config)
        all_trades.extend(sym_trades)

    if not all_trades:
        return {"name": name, "n_trades": 0}

    all_trades.sort(key=lambda t: t["confirm_time"])
    df = pd.DataFrame(all_trades)
    t_min = df["confirm_time"].min()
    t_max = df["confirm_time"].max()
    cutoff = t_min + (t_max - t_min) * config.is_ratio

    is_trades = [t for t in all_trades if t["confirm_time"] < cutoff]
    oos_trades = [t for t in all_trades if t["confirm_time"] >= cutoff]

    full_m = calculate_metrics(all_trades, initial_balance=config.initial_balance, risk_pct=config.risk_pct)
    is_m = calculate_metrics(is_trades, initial_balance=config.initial_balance, risk_pct=config.risk_pct)
    oos_m = calculate_metrics(oos_trades, initial_balance=config.initial_balance, risk_pct=config.risk_pct)

    return {
        "name": name,
        "full": full_m,
        "is": is_m,
        "oos": oos_m,
    }


def main():
    print("=" * 105)
    print("  🔬 AXIORY ADVANCED STRATEGY SYSTEMATIC IMPROVEMENT EXPERIMENTATION (XAUUSD & EURJPY)")
    print("=" * 105)

    # Ingest data once to ensure identical data across all experiments
    datasets = {}
    for sym in TARGET_SYMBOLS:
        print(f"  [>] Ingesting causal data for {sym}...")
        df_htf, df_ltf = fetch_causal_data(sym, interval="1h", period="730d")
        datasets[sym] = (df_htf, df_ltf)

    baseline_cfg = BacktestConfig(
        symbols=TARGET_SYMBOLS,
        timeframe="1h",
        period="730d",
        swing_order=3,
        use_100_sma=True,
        session_filter=True,
        session_start_utc=7,
        session_end_utc=18,
        tp1_rr=0.9,
        tp2_rr=2.0,
        scale_tp1_ratio=0.65,
        max_fill_wait_bars=5,
        is_ratio=0.70,
    )

    experiments = []

    # 1. Baseline
    experiments.append(("1. Baseline (07-18 UTC, TP1=0.9R, wait=5)", baseline_cfg))

    # 2. Session Window Tests (Filtering out late-session low-liquidity chop)
    experiments.append(("2A. Session: 07-14 UTC (London + NY Morning)", baseline_cfg.with_override(session_end_utc=14)))
    experiments.append(("2B. Session: 07-15 UTC (Peak Overlap)", baseline_cfg.with_override(session_end_utc=15)))
    experiments.append(("2C. Session: 07-16 UTC (London Close)", baseline_cfg.with_override(session_end_utc=16)))
    experiments.append(("2D. Session: 08-16 UTC (European Morning to Close)", baseline_cfg.with_override(session_start_utc=8, session_end_utc=16)))

    # 3. Retest Fill Wait Expiry
    experiments.append(("3A. Wait Expiry: 3 bars (Fast retest only)", baseline_cfg.with_override(max_fill_wait_bars=3)))
    experiments.append(("3B. Wait Expiry: 4 bars", baseline_cfg.with_override(max_fill_wait_bars=4)))
    experiments.append(("3C. Wait Expiry: 6 bars (Patient retest)", baseline_cfg.with_override(max_fill_wait_bars=6)))

    # 4. Target Architecture Variations
    experiments.append(("4A. TP1=1.0R, TP2=2.0R, Scale 65%", baseline_cfg.with_override(tp1_rr=1.0)))
    experiments.append(("4B. TP1=0.9R, TP2=2.5R, Scale 65%", baseline_cfg.with_override(tp2_rr=2.5)))
    experiments.append(("4C. TP1=1.0R, TP2=2.5R, Scale 60%", baseline_cfg.with_override(tp1_rr=1.0, tp2_rr=2.5, scale_tp1_ratio=0.60)))
    experiments.append(("4D. TP1=0.8R, TP2=2.0R, Scale 70%", baseline_cfg.with_override(tp1_rr=0.8, scale_tp1_ratio=0.70)))

    # 5. Combined Synergies (Testing best session + wait expiry)
    experiments.append(("5A. Synergy: 07-15 UTC + Wait 4 bars", baseline_cfg.with_override(session_end_utc=15, max_fill_wait_bars=4)))
    experiments.append(("5B. Synergy: 07-15 UTC + TP1=1.0R", baseline_cfg.with_override(session_end_utc=15, tp1_rr=1.0)))
    experiments.append(("5C. Synergy: 07-15 UTC + TP1=1.0R + Wait 4", baseline_cfg.with_override(session_end_utc=15, tp1_rr=1.0, max_fill_wait_bars=4)))

    results = []
    print("\nRunning controlled parameter evaluations...\n")
    for name, cfg in experiments:
        res = evaluate_configuration(name, cfg, datasets)
        results.append(res)

    # Format Results Table
    header = f"{'Configuration':<45} | {'Trades':<7} | {'WinRate':<7} | {'Net R':<8} | {'PF':<5} | {'MaxDD%':<7} | {'IS NetR':<8} | {'IS PF':<5} | {'OOS NetR':<8} | {'OOS PF':<5} | {'OOS Exp':<7}"
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for r in results:
        full = r["full"]
        is_m = r["is"]
        oos_m = r["oos"]
        name = r["name"]
        print(f"{name:<45} | {full['n_trades']:>6}  | {full['win_rate']:>5.1f}% | {full['net_r']:>+7.2f}R | {full['profit_factor']:>4.2f} | {full['max_drawdown_pct']:>5.1f}% | {is_m['net_r']:>+7.2f}R | {is_m['profit_factor']:>4.2f} | {oos_m['net_r']:>+7.2f}R | {oos_m['profit_factor']:>4.2f} | {oos_m['expectancy_r']:>+6.2f}R")

    print("=" * len(header))


if __name__ == "__main__":
    main()
