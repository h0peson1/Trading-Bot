# Trading Signal Bot Configuration
# Signal-only — no broker or MetaTrader required

TELEGRAM_BOT_TOKEN = "8837848491:AAHxFS89-WEezZc2CXoc3AojjtS2BCfymQA"
TELEGRAM_CHAT_ID = "8402561087"

# Twelve Data API key (paste your key here)
TWELVEDATA_API_KEY = "e498a1660bd547a0b0304ed25ecbcff6"

# Symbols to scan
# Twelve Data tickers used under the hood
SYMBOLS = {
    "BTCUSD": "BTC/USD",
    "XAUUSD": "XAU/USD",
    "GBPUSD": "GBP/USD",
    "USDCHF": "USD/CHF",
    "GBPAUD": "GBP/AUD",
    "EURJPY": "EUR/JPY",
}

# Timeframe Strategy:
# 4H: Higher Timeframe (HTF) market structure, trend bias, and 4-hour candle close updates
# 15m: Lower Timeframe (LTF) execution for taking trade entries
HTF_TIMEFRAME = "4h"
ENTRY_TIMEFRAME = "15min"
TIMEFRAMES = ["15min", "4h"]

# Twelve Data outputsize per timeframe (max data points to fetch)
TWELVEDATA_OUTPUTSIZE = {
    "15min": 200,     # ~50 hours of 15m candles
    "30min": 200,
    "1h": 200,
    "4h": 200,        # ~33 days of 4h candles
    "1day": 365,
}

# Update & Polling schedules
# UPDATE_INTERVAL_HOURS: Sends comprehensive market report after every 4H candle close
UPDATE_INTERVAL_HOURS = 4
# SCAN_INTERVAL: Frequency in seconds to check for new closed 15m candles (60s = 1 min)
SCAN_INTERVAL = 60
CHECK_INTERVAL = SCAN_INTERVAL

# Strategy Settings: Axiory Advanced Price Action (70% Target Model)
# Swing Detection: Order of candles on each side to confirm a swing high / low fractal
SWING_ORDER = 3

# Fibonacci Retracement Golden Zone
FIB_LEVEL_382 = 0.382
FIB_ENTRY_50 = 0.500
FIB_ENTRY_618 = 0.618

# Institutional Confluence Filters (Chapter 2, 4, 5 of Axiory Guide)
USE_100_SMA_FILTER = True          # 100 SMA macro trend alignment
ENTRY_MODE = "LIMIT_50_RETEST"     # Pending limit order at 50% of rejection candle

# Risk-Reward & Scaling Settings (Optimized for 65%–71% Win Rate)
TP1_RR = 0.9                       # High-probability primary target (scale 65% & SL to BE)
TP2_RR = 2.0                       # Secondary structural runner target
SCALE_TP1_RATIO = 0.65             # Bank 65% of position at TP1

# Telegram notification preferences
SEND_4H_BRIEFING = False           # Set True only if 4H market structure updates are desired (default False for signal-only)
SIGNAL_PREFIX = "📊 Axiory Price Action Alert"
