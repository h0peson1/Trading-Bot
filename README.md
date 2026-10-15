# LDE Signal Bot

Signal-only bot for **Liquidity Sweep -> Displacement -> Engulfing (LDE)** setups.
Sends real-time formatted HTML alerts to Telegram. Does **not** execute trades.

---

## 📊 Multi-Timeframe Strategy Architecture
- **Higher Timeframe (HTF): 4H (4-Hour Candle Close)**
  - Tracks higher-timeframe trend bias, 50 EMA, market structure, sweeps, and 4H Fair Value Gaps (FVGs).
  - Automatically compiles and dispatches a comprehensive multi-pair market update after every 4-hour candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
- **Execution Timeframe (LTF): 15m (15-Minute Entries)**
  - Continuously scans 15m candles in real-time.
  - Takes institutional entries: 15m Sweep ➔ Displacement ➔ Engulfing / 50% FVG Retest.
  - Cross-checks entries against 4H bias to flag `🔥 High Confluence (4H + 15M Aligned)` setups.
  - Sends immediate trade alerts with Entry, Stop Loss, TP1 (1:1.5R scale 50%), and TP2 (1:2.5R).

---

## ⚙️ Setup & Configuration

### 1. Telegram Bot Setup
1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram and copy your API Token.
2. Open Telegram and send `/start` or any message to your new bot.
3. Find your numeric Telegram Chat ID using [@userinfobot](https://t.me/userinfobot).
4. In [config.py](config.py), set:
   ```python
   TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
   TELEGRAM_CHAT_ID = "YOUR_NUMERIC_CHAT_ID"
   ```

### 2. Verify Bot Connectivity
Test your Telegram setup directly from the command line:
```bash
python signal_bot.py --test
```

### 3. Run the Bot & Mobile Controller
- **Run the full interactive bot:**
  ```bash
  python signal_bot.py
  ```
  *(Sends the 4H market update after every 4H candle close, monitors 15m candles for entry triggers, and maintains persistent phone buttons!)*

---

## 📱 Mobile Interactive Telegram Buttons
When running `signal_bot.py`, your Telegram chat will feature interactive inline buttons:
- 🔘 **[📊 Backtest Gold (Multi-TF)]**: Runs multi-year Gold backtests and replies with win rate & profit factor immediately.
- 🔘 **[⚡ Macro News Backtest]**: Tests Gold performance during high-impact US CPI, NFP & FOMC events.
- 🔘 **[🔍 Scan Market Now]**: Triggers an instant live market scan across all pairs.
- 🔘 **[ℹ️ Bot Status]**: Reports current uptime, active tickers, and lookback configuration.
- You can also send `/menu`, `/backtest`, or `/scan` directly as text commands!

---

## 🎯 Implemented LDE Rules & Upgrades
1. **Liquidity Sweep**: Detects when prior swing highs/lows are pierced and rejected within the lookback window.
2. **Displacement**: Requires 1–3 sharp candles with $\ge 70\%$ body-to-range ratio and volume/expansion exceeding baseline.
3. **Engulfing Confirmation**: Requires clear directional engulfing candle close.
4. **Closed-Candle Evaluation**: Signals only trigger on completed candles to prevent repainting.
5. **Deduplication Engine**: Prevents duplicate spam alerts for the same candle on higher timeframes (1H, 4H, 1D).
6. **Fair Value Gap (FVG)**: Automatically detects and displays 3-candle imbalances when present.
7. **Fibonacci Zone**: Highlights when entry falls into the 0.50–0.718 discount/premium zone.
8. **Trade Metrics**: Automatically calculates Entry, Stop Loss, and 1:3 Take Profit targets.
