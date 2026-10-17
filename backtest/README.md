# 📊 Institutional Backtesting Suite (Axiory Advanced Price Action)

This directory houses the audited quantitative backtesting engine, automated regression test suite, research scripts, reports, and performance results for the Axiory Price Action Strategy.

---

## 📁 Directory Structure

```
backtest/
├── backtest_advanced.py     # Authoritative production backtesting engine (3-asset audited model)
├── test_axiory_engine.py    # 17-test regression & integration test suite (100% passing)
├── README.md                # This guide
├── reports/                 # Comprehensive quantitative audit & strategy performance reports
│   ├── ADVANCED_BACKTEST_BREAKDOWN.md
│   ├── STRATEGY_IMPROVEMENT_REPORT.md
│   ├── BACKTEST_2022_2026_REPORT.md
│   ├── PROFITABLE_PAIRS_5YR_REPORT.md
│   └── BACKTEST_REPORT.md
├── results/                 # Exported trade ledgers, equity curves, and performance charts
│   ├── advanced_backtest_chart.png
│   ├── advanced_backtest_equity.csv
│   ├── advanced_backtest_trades.csv
│   ├── improved_3asset_chart.png
│   ├── improved_3asset_equity.csv
│   ├── improved_3asset_trades.csv
│   └── ... (historical run ledgers)
└── research/                # Diagnostic scripts, historical iterations, and baseline backups
    ├── diagnostics_btcusd.py
    ├── diagnostics_xau_eur.py
    ├── explore_btcusd_improvements.py
    ├── test_3asset_portfolio.py
    ├── baseline_backup/
    └── backup_pre_critical_fixes/
```

---

## 🚀 Running the Production Backtest

To run the complete 3-asset backtest with chronological in-sample/out-of-sample validation and Monte Carlo simulations:

```bash
# From within the backtest/ folder:
python backtest_advanced.py

# With single-parameter sensitivity stress testing:
python backtest_advanced.py --sensitivity
```

### Key Parameters Configured in `backtest_advanced.py`:
- **Universe:** `XAUUSD` (Gold), `EURJPY` (Forex Cross), `BTCUSD` (Bitcoin)
- **Timeframe:** 1H execution with causal 4H higher-timeframe structure
- **Sessions:** 
  - `XAUUSD` & `EURJPY`: 07:00–15:00 UTC (London Open through London/NY overlap)
  - `BTCUSD`: 24/7 continuous scanning, Long-Only (`BUY_ONLY`), and 0.50% SL buffer
- **Risk Architecture:** 0.9R TP1 (bank 65% + stop to breakeven), 2.0R TP2 runner

---

## 🧪 Running the Automated Test Suite

To run all 17 causal execution, state machine, and accounting tests:

```bash
python test_axiory_engine.py
```
*(All 17 integration tests pass in ~0.05s with zero external dependencies).*

---

## 📈 Performance Summary (125 Trades, 2024–2026)

- **Portfolio Win Rate:** **66.40%** (83 Wins vs 42 Losses)
- **Net Return:** **+21.07 R** (+35.54% account growth on $10,000 balance)
- **Profit Factor:** **1.48**
- **Maximum Drawdown:** **8.18%** (safe under standard 10% prop-firm limits)
- **Out-of-Sample Retention:** **203% Expectancy Retention Ratio** on unseen 2026 data
- **Asset Breakdown:**
  - `XAUUSD`: **+10.22 R** | 73.5% WR | 1.76 PF
  - `BTCUSD`: **+6.43 R** | 60.6% WR | 1.47 PF
  - `EURJPY`: **+4.42 R** | 62.8% WR | 1.26 PF
