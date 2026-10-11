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

# Timeframes to scan
# Note: yfinance supports: 15m, 30m, 1h, 4h, 1d (2h is NOT supported by yfinance)
TIMEFRAMES = ["15m", "1h", "4h", "1d"]

# How many candles to look back for liquidity sweeps
LOOKBACK_CANDLES = 60

# Risk-reward ratio shown in signals
RISK_REWARD = 3.0

# Check interval in seconds (300 = every 5 minutes)
CHECK_INTERVAL = 300

# Displacement rules
MIN_BODY_RATIO = 0.70          # Body must be at least 70% of candle range
DISPLACEMENT_COMPARE = 5       # Must be larger than recent N candles
MAX_DISPLACEMENT_CANDLES = 3   # 1–3 sharp candles

# Telegram message prefix
SIGNAL_PREFIX = "⚡ LDE Signal Alert"
