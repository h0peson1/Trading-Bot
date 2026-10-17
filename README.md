# Axiory Advanced Price Action Signal Bot

Signal-only Telegram bot built on the **Axiory Advanced Price Action Guide**.
Sends real-time formatted HTML alerts to Telegram based on **pure market structure**, **Fibonacci retracements**, and **candlestick rejection confirmation**. Does **not** execute trades.

---

## 📊 Strategy Architecture

- **Higher Timeframe (HTF): 4H (4-Hour Candle Close)**
  - **Pure Market Structure:** Tracks Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), Lower Lows (LL) — *no lagging indicators*.
  - **Fibonacci Golden Zone:** Calculates 50.0% – 61.8% discount/premium retracement levels for the active impulse leg.
  - **Break of Structure (BOS):** Detects early trend reversals when price closes beyond the prior swing structural level.
  - **Trendline 3rd-Point:** Projects multi-point trendline support and resistance.
  - Automatically dispatches a comprehensive multi-pair market update after every 4-hour candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).

- **Execution Timeframe (LTF): 15m (15-Minute Rejection Entries)**
  - Continuously monitors 15m candles in real-time.
  - Verifies price is actively testing the **4H 50%–61.8% Golden Zone** or **Trendline**.
  - Requires completed candlestick confirmation from Chapter 9 Cheat Sheet:
    - **Bullish / Bearish Pin Bar** (Hammer / Shooting Star with long wick $\ge 50\%$)
    - **Bullish / Bearish Engulfing**
    - **Morning Star / Evening Star** (3-candle reversal)
  - Dispatches trade alerts with Entry, Stop Loss (beyond wick), TP1 (1:1.5R scale 50% & BE), and TP2 (1:3.0R target).

---

## ⚙️ Setup & Configuration

### 1. Twelve Data API Setup
1. Sign up at [twelvedata.com](https://twelvedata.com/) and copy your API key.
2. In [config.py](config.py), set:
   ```python
   TWELVEDATA_API_KEY = "YOUR_API_KEY"
   ```

### 2. Telegram Bot Setup
1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram and copy your API Token.
2. Open Telegram and send `/start` or any message to your new bot.
3. Find your numeric Telegram Chat ID using [@userinfobot](https://t.me/userinfobot).
4. In [config.py](config.py), set:
   ```python
   TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
   TELEGRAM_CHAT_ID = "YOUR_NUMERIC_CHAT_ID"
   ```

### 3. Verify Bot Connectivity
Test your Telegram setup directly from the command line:
```bash
python signal_bot.py --test
```

### 4. Run the Bot & Mobile Controller
- **Run the full interactive bot:**
  ```bash
  python signal_bot.py
  ```

---

## 📱 Mobile Interactive Telegram Buttons
When running `signal_bot.py`, your Telegram chat will feature interactive reply buttons:
- 🔘 **[🔍 Scan 15M Entries]**: Triggers an instant live market scan across all pairs for Fib & Candlestick triggers.
- 🔘 **[📊 4H Market Structure]**: Dispatches a full breakdown of HH/HL/LH/LL swings and trend bias.
- 🔘 **[📐 Active Fib Zones]**: Lists the active 50%–61.8% Golden Zone levels for every pair.
- 🔘 **[📰 Macro News]**: Fetches the latest high-impact economic news headlines.
- 🔘 **[ℹ️ Bot Status]**: Reports uptime, pairs, next 4H candle close countdown.
- Text commands supported: `/menu`, `/scan`, `/structure`, `/fibs`, `/news`, `/status`.

---

## 🎯 Implemented Price Action Rules
1. **Fractal Extrema:** Swings detected using N-bar peak & trough detection on closed candles.
2. **Chronological Structure:** Classifies each swing into HH, HL, LH, LL to confirm structural trend.
3. **Golden Pocket Retracement:** 50.0% and 61.8% Fibonacci zones calculated from active swing leg.
4. **Candlestick Rejections:** Pin Bars (Hammer/Shooting Star), Engulfing, and Morning/Evening Stars.
5. **No Lagging Indicators:** Pure price action derived strictly from OHLC candle prices.
6. **Risk Management:** Strict 1:1.5R (TP1) and 1:3.0R (TP2) targets with Stop Loss set past the wick.

---

## 🔬 Institutional Backtesting Suite (`backtest/`)

All backtesting engines, test suites, reports, and performance data are housed in the dedicated [`backtest/`](backtest/) directory:

- **Engine:** [`backtest/backtest_advanced.py`](backtest/backtest_advanced.py) — 3-asset audited production engine (`XAUUSD`, `BTCUSD`, `EURJPY`).
- **Test Suite:** [`backtest/test_axiory_engine.py`](backtest/test_axiory_engine.py) — 17 automated regression/integration tests (**17/17 Passing**).
- **Reports:** [`backtest/reports/`](backtest/reports/) — In-depth breakdown reports including [`ADVANCED_BACKTEST_BREAKDOWN.md`](backtest/reports/ADVANCED_BACKTEST_BREAKDOWN.md).
- **Results:** [`backtest/results/`](backtest/results/) — Full trade ledgers, equity curves, and performance charts.

### Quick Commands

```bash
# Run the 3-asset production backtest
python backtest/backtest_advanced.py

# Run with parameter sensitivity stress testing
python backtest/backtest_advanced.py --sensitivity

# Run the 17-test regression suite
python backtest/test_axiory_engine.py
```

### Verified Multi-Asset Performance (2024–2026)
- **Portfolio Win Rate:** **66.40%** (83 Wins vs 42 Losses)
- **Net Return:** **+21.07 R** (+35.54% account growth on $10,000 balance)
- **Profit Factor:** **1.48** | **Max Drawdown:** **8.18%**
- **Expectancy Retention (Out-of-Sample):** **203%** on unseen 2026 data
- Detailed guide: [backtest/README.md](backtest/README.md)
