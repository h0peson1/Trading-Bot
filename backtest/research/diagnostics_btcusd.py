import pandas as pd
import numpy as np
from backtest_advanced import BacktestConfig, fetch_causal_data, simulate_pair, calculate_metrics

def main():
    print("=" * 90)
    print("  🔍 BTCUSD DEEP QUANTITATIVE DIAGNOSTIC AUDIT (1H/4H INTRADAY)")
    print("=" * 90)

    # 1. Fetch data
    df_htf, df_ltf = fetch_causal_data("BTCUSD", interval="1h", period="730d")
    print(f"Ingested BTCUSD: 1H bars={len(df_ltf)}, 4H bars={len(df_htf)}")

    # 2. Baseline run (with London/NY session filter 07-18 UTC)
    cfg_base = BacktestConfig(symbols=("BTCUSD",), timeframe="1h", period="730d", session_filter=True, session_start_utc=7, session_end_utc=18)
    t_base, s_base = simulate_pair("BTCUSD", df_htf, df_ltf, config=cfg_base)
    m_base = calculate_metrics(t_base)
    print(f"\n[Baseline 07-18 UTC]: N={m_base['n_trades']} | WR={m_base['win_rate']:.1f}% | Net R={m_base['net_r']:+.2f}R | PF={m_base['profit_factor']:.2f} | Exp={m_base['expectancy_r']:+.2f}R | MaxDD={m_base['max_drawdown_pct']:.1f}%")

    # 3. 24-Hour Continuous run (no session filter)
    cfg_24h = BacktestConfig(symbols=("BTCUSD",), timeframe="1h", period="730d", session_filter=False)
    t_24h, s_24h = simulate_pair("BTCUSD", df_htf, df_ltf, config=cfg_24h)
    m_24h = calculate_metrics(t_24h)
    print(f"[24-Hour Continuous]: N={m_24h['n_trades']} | WR={m_24h['win_rate']:.1f}% | Net R={m_24h['net_r']:+.2f}R | PF={m_24h['profit_factor']:.2f} | Exp={m_24h['expectancy_r']:+.2f}R | MaxDD={m_24h['max_drawdown_pct']:.1f}%")

    # Analyze by pattern on 24h trades
    df_all = pd.DataFrame(t_24h)
    print("\n--- BTCUSD PATTERN BREAKDOWN (24h) ---")
    for pat, g in df_all.groupby("pattern"):
        m = calculate_metrics(g.to_dict("records"))
        print(f"{pat:<20} | N={m['n_trades']:>2} | WR={m['win_rate']:>5.1f}% | Net R={m['net_r']:>+6.2f} R | PF={m['profit_factor']:>5.2f} | Exp={m['expectancy_r']:>+5.2f} R")

    print("\n--- BTCUSD DIRECTION BREAKDOWN (24h) ---")
    for d, g in df_all.groupby("direction"):
        m = calculate_metrics(g.to_dict("records"))
        print(f"{d:<10} | N={m['n_trades']:>2} | WR={m['win_rate']:>5.1f}% | Net R={m['net_r']:>+6.2f} R | PF={m['profit_factor']:>5.2f} | Exp={m['expectancy_r']:>+5.2f} R")

    print("\n--- BTCUSD BY ENTRY HOUR (UTC) ---")
    df_all['hour'] = pd.to_datetime(df_all['confirm_time']).dt.hour
    for h, g in df_all.groupby('hour'):
        m = calculate_metrics(g.to_dict('records'))
        print(f"Hour {h:>02}:00 UTC | N={m['n_trades']:>2} | WR={m['win_rate']:>5.1f}% | Net R={m['net_r']:>+6.2f} R | PF={m['profit_factor']:>5.2f} | Exp={m['expectancy_r']:>+5.2f} R")

if __name__ == "__main__":
    main()
