import pandas as pd
from optimize_strategy import fetch_data, simulate_strategy

pairs = ["BTCUSD", "USDCHF", "XAUUSD", "GBPUSD", "EURJPY", "GBPAUD"]
print("=" * 80)
print("     📊 BREAKDOWN BY PAIR FOR EXP-4 (TP1=1.0R / TP2=2.5R)")
print("=" * 80)
print(f"{'Pair':<10} | {'Trades':<8} | {'Win %':<10} | {'Full Wins':<10} | {'Partials':<10} | {'Total R':<10} | {'PF':<6}")
print("-" * 80)

for p in pairs:
    d4 = fetch_data(p, "4h")
    d1 = fetch_data(p, "1h")
    if d4.empty or d1.empty:
        continue
    trs = simulate_strategy(d4, d1, tp1_rr=1.0, tp2_rr=2.5, patterns_filter="ENGULFING_AND_PIN", require_expansion=False)
    if not trs:
        continue
    df = pd.DataFrame(trs)
    tot = len(df)
    wins = (df["pnl_r"] > 0).sum()
    full_wins = (df["outcome"] == "FULL_WIN").sum()
    partials = (df["outcome"] == "PARTIAL_WIN").sum()
    wr = (wins / tot) * 100 if tot > 0 else 0
    tot_r = df["pnl_r"].sum()
    gp = df[df["pnl_r"] > 0]["pnl_r"].sum()
    gl = abs(df[df["pnl_r"] < 0]["pnl_r"].sum())
    pf = (gp / gl) if gl > 0 else 999.0

    print(f"{p:<10} | {tot:<8} | {wr:>6.2f}%   | {full_wins:<10} | {partials:<10} | {tot_r:>8.2f} R | {pf:>5.2f}")
print("=" * 80)
