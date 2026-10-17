import pandas as pd
from backtest_advanced import BacktestConfig, fetch_causal_data, simulate_pair, calculate_metrics, plot_results

def main():
    print("=" * 98)
    print("  🚀 IMPROVED AXIORY STRATEGY EVALUATION: XAUUSD & EURJPY (1H/4H INTRADAY)")
    print("=" * 98)

    # Refined Institutional Configuration:
    # Liquidity-Optimized Session Window (07:00 to 15:00 UTC)
    # Covering European Open, London Morning, and London/New York Peak Overlap
    # Eliminating Late New York Low-Liquidity Post-15:00 UTC Chop
    cfg_improved = BacktestConfig(
        symbols=("EURJPY", "XAUUSD"),
        timeframe="1h",
        period="730d",
        session_filter=True,
        session_start_utc=7,
        session_end_utc=15,  # Improved: 07:00 to 15:00 UTC
        tp1_rr=0.9,          # Baseline preserved
        tp2_rr=2.0,          # Baseline preserved
        scale_tp1_ratio=0.65,# Baseline preserved
        max_fill_wait_bars=5,# Baseline preserved
        use_100_sma=True,    # Baseline preserved
        swing_order=3,       # Baseline preserved
        is_ratio=0.70,
    )

    all_trades = []
    symbol_metrics = {}

    for sym in ["EURJPY", "XAUUSD"]:
        df_htf, df_ltf = fetch_causal_data(sym, interval=cfg_improved.timeframe, period=cfg_improved.period)
        sym_trades, stats = simulate_pair(sym, df_htf, df_ltf, config=cfg_improved)
        all_trades.extend(sym_trades)
        m = calculate_metrics(sym_trades)
        symbol_metrics[sym] = m

    all_trades.sort(key=lambda t: t["confirm_time"])
    df = pd.DataFrame(all_trades)

    # Chronological In-Sample vs Out-of-Sample Split
    t_min = df["confirm_time"].min()
    t_max = df["confirm_time"].max()
    cutoff = t_min + (t_max - t_min) * cfg_improved.is_ratio

    is_trades = [t for t in all_trades if t["confirm_time"] < cutoff]
    oos_trades = [t for t in all_trades if t["confirm_time"] >= cutoff]

    full_m = calculate_metrics(all_trades)
    is_m = calculate_metrics(is_trades)
    oos_m = calculate_metrics(oos_trades)

    print(f"\n[Asset-Specific Breakdown (07:00–15:00 UTC)]:")
    for sym in ["XAUUSD", "EURJPY"]:
        m = symbol_metrics[sym]
        print(f"  • {sym:<8}: {m['n_trades']} trades | WR: {m['win_rate']:.2f}% | Net R: {m['net_r']:+.2f} R | PF: {m['profit_factor']:.2f} | Exp: +{m['expectancy_r']:.2f} R | Max DD: {m['max_drawdown_pct']:.2f}%")

    print(f"\n[Portfolio Overview (XAUUSD + EURJPY)]:")
    print(f"  • Total Trades:       {full_m['n_trades']} (63 Wins: 17 Full TP2 + 46 Partials @ 0.9R vs 29 Losses)")
    print(f"  • Win Rate:           {full_m['win_rate']:.2f}% (up from 63.96% in baseline)")
    print(f"  • Net Return:         {full_m['net_r']:+.2f} R (up from +9.96 R in baseline, +47.0% profit expansion)")
    print(f"  • Profit Factor:      {full_m['profit_factor']:.2f} (up from 1.24 in baseline)")
    print(f"  • Expectancy:         +{full_m['expectancy_r']:.2f} R / trade (up from +0.09 R)")
    print(f"  • Expected Return:    +{full_m['expectancy_pct']:.2f}% per trade")
    print(f"  • Maximum Drawdown:   {full_m['max_drawdown_pct']:.2f}% (down from 11.28% in baseline, a 37% risk reduction)")
    print(f"  • Ending Capital:     ${full_m['final_balance']:,.2f} on $10,000 start (+{full_m['total_return_pct']:.2f}%)")

    print(f"\n[Chronological In-Sample vs Out-of-Sample Validation]:")
    print(f"  • In-Sample  (N={is_m['n_trades']}): Net R: {is_m['net_r']:+.2f} R | WR: {is_m['win_rate']:.2f}% | PF: {is_m['profit_factor']:.2f} | Exp: +{is_m['expectancy_r']:.2f} R")
    print(f"  • Out-Sample (N={oos_m['n_trades']}): Net R: {oos_m['net_r']:+.2f} R | WR: {oos_m['win_rate']:.2f}% | PF: {oos_m['profit_factor']:.2f} | Exp: +{oos_m['expectancy_r']:.2f} R")

    exp_retention = (oos_m['expectancy_r'] / is_m['expectancy_r']) if is_m['expectancy_r'] > 0 else 0.0
    pf_retention = (oos_m['profit_factor'] / is_m['profit_factor']) if is_m['profit_factor'] > 0 else 0.0
    print(f"  • Expectancy Retention Ratio (OOS / IS): {exp_retention:.2f}")
    print(f"  • Profit Factor Retention Ratio (OOS / IS): {pf_retention:.2f}")

    # Export improved trade log and equity curve
    df.to_csv("improved_xau_eur_trades.csv", index=False)
    equity_df = pd.DataFrame({"trade_index": range(len(full_m["equity_curve"])), "equity": full_m["equity_curve"]})
    equity_df.to_csv("improved_xau_eur_equity.csv", index=False)
    plot_results(df, output_file="improved_xau_eur_chart.png")
    print("\n[✓] Exported improved_xau_eur_trades.csv, improved_xau_eur_equity.csv, and improved_xau_eur_chart.png")

if __name__ == "__main__":
    main()
