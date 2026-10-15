# Trading Signal Bot Configuration
# Signal-only — no broker or MetaTrader required

TELEGRAM_BOT_TOKEN = "8837848491:AAHxFS89-WEezZc2CXoc3AojjtS2BCfymQA"
TELEGRAM_CHAT_ID = "8402561087"

# Symbols to scan
# yfinance tickers used under the hood
SYMBOLS = {
    "BTCUSD": "BTC-USD",
    "XAUUSD": "GC=F",          # Gold futures (very close to XAUUSD)
    "GBPUSD": "GBPUSD=X",
    "USDCHF": "USDCHF=X",
    "GBPAUD": "GBPAUD=X",
    "EURJPY": "EURJPY=X",
}

# Timeframe Strategy:
# 4H: Higher Timeframe (HTF) market structure, trend bias, and 4-hour candle close updates
# 15m: Lower Timeframe (LTF) execution for taking trade entries
HTF_TIMEFRAME = "4h"
ENTRY_TIMEFRAME = "15m"
TIMEFRAMES = ["15m", "4h"]

# Update & Polling schedules
# UPDATE_INTERVAL_HOURS: Sends comprehensive market report after every 4H candle close
UPDATE_INTERVAL_HOURS = 4
# SCAN_INTERVAL: Frequency in seconds to check for new closed 15m candles (60s = 1 min)
SCAN_INTERVAL = 60
CHECK_INTERVAL = SCAN_INTERVAL

# Strategy lookback & risk-reward settings
LOOKBACK_CANDLES = 60
RISK_REWARD = 3.0

# Displacement rules
MIN_BODY_RATIO = 0.70          # Body must be at least 70% of candle range
DISPLACEMENT_COMPARE = 5       # Must be larger than recent N candles
MAX_DISPLACEMENT_CANDLES = 3   # 1–3 sharp candles

# Telegram message prefix
SIGNAL_PREFIX = "⚡ LDE Signal Alert"
