import pandas as pd
from backtest_advanced import BacktestConfig, fetch_causal_data, simulate_pair, calculate_metrics

cfg = BacktestConfig(symbols=('EURJPY', 'XAUUSD'), timeframe='1h')
trades = []
for sym in ['EURJPY', 'XAUUSD']:
    df_htf, df_ltf = fetch_causal_data(sym, interval='1h', period='730d')
    t_list, stats = simulate_pair(sym, df_htf, df_ltf, config=cfg)
    trades.extend(t_list)

df = pd.DataFrame(trades)
print(f"Total baseline trades on EURJPY + XAUUSD: {len(df)}")
m = calculate_metrics(trades)
print(f"Baseline Net R: {m['net_r']:+.2f} R, WR: {m['win_rate']:.2f}%, PF: {m['profit_factor']:.2f}, Expectancy: +{m['expectancy_r']:.2f} R, Max DD: {m['max_drawdown_pct']:.2f}%\n")

# In-Sample vs Out-of-Sample baseline
df.sort_values("confirm_time", inplace=True)
t_min, t_max = df["confirm_time"].min(), df["confirm_time"].max()
cutoff = t_min + (t_max - t_min) * 0.70
is_trades = [t for t in trades if t["confirm_time"] < cutoff]
oos_trades = [t for t in trades if t["confirm_time"] >= cutoff]
is_m = calculate_metrics(is_trades)
oos_m = calculate_metrics(oos_trades)
print(f"Baseline In-Sample  (N={is_m['n_trades']}): Net R: {is_m['net_r']:+.2f} R, WR: {is_m['win_rate']:.2f}%, PF: {is_m['profit_factor']:.2f}, Exp: +{is_m['expectancy_r']:.2f} R")
print(f"Baseline Out-Sample (N={oos_m['n_trades']}): Net R: {oos_m['net_r']:+.2f} R, WR: {oos_m['win_rate']:.2f}%, PF: {oos_m['profit_factor']:.2f}, Exp: +{oos_m['expectancy_r']:.2f} R\n")

print("--- BY PATTERN ---")
for pat, g in df.groupby("pattern"):
    gm = calculate_metrics(g.to_dict("records"))
    print(f"{pat:<20} | N={gm['n_trades']:>2} | WR={gm['win_rate']:>5.1f}% | Net R={gm['net_r']:>+6.2f} R | PF={gm['profit_factor']:>5.2f} | Exp={gm['expectancy_r']:>+5.2f} R")

print("\n--- BY DIRECTION ---")
for d, g in df.groupby("direction"):
    gm = calculate_metrics(g.to_dict("records"))
    print(f"{d:<10} | N={gm['n_trades']:>2} | WR={gm['win_rate']:>5.1f}% | Net R={gm['net_r']:>+6.2f} R | PF={gm['profit_factor']:>5.2f} | Exp={gm['expectancy_r']:>+5.2f} R")

print("\n--- BY ENTRY HOUR (UTC) ---")
df['hour'] = pd.to_datetime(df['confirm_time']).dt.hour
for h, g in df.groupby('hour'):
    gm = calculate_metrics(g.to_dict('records'))
    print(f"Hour {h:>02}:00 UTC | N={gm['n_trades']:>2} | WR={gm['win_rate']:>5.1f}% | Net R={gm['net_r']:>+6.2f} R | PF={gm['profit_factor']:>5.2f} | Exp={gm['expectancy_r']:>+5.2f} R")
