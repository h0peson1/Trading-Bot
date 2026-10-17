# Trading Signal Bot Configuration
# Signal-only — no broker or MetaTrader required

TELEGRAM_BOT_TOKEN = "8837848491:AAHxFS89-WEezZc2CXoc3AojjtS2BCfymQA"
TELEGRAM_CHAT_ID = "8402561087"   # Admin chat ID (full interactive chat + control)
ADMIN_CHAT_ID = TELEGRAM_CHAT_ID

# Twelve Data API key (paste your key here)
TWELVEDATA_API_KEY = "e498a1660bd547a0b0304ed25ecbcff6"

# Top 3 High-Probability Strategy Universe (Audited & Backtested)
# Strictly limited to the 3 profitable assets with positive mathematical expectancy
SYMBOLS = {
    "XAUUSD": "XAU/USD",  # Gold (Core Alpha Engine: +10.22 R, 73.5% WR, 1.76 PF)
    "EURJPY": "EUR/JPY",  # Forex Cross (Steady Trend Diversifier: +4.42 R, 62.8% WR, 1.26 PF)
    "BTCUSD": "BTC/USD",  # Crypto (Macro Bull Trend Driver: +6.43 R, 60.6% WR, 1.47 PF)
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

# SCAN_INTERVAL: 300 seconds (5 minutes)
# Quota Math (Target ~500 requests/day on Twelve Data Basic 800 plan):
# - Peak hours (07:00-15:00 UTC, 8 hrs): 3 pairs x 12 scans/hr x 8 hrs = 288 calls
# - Off-peak hours (16 hrs): 1 pair (BTC 24/7) x 12 scans/hr x 16 hrs = 192 calls
# - 4H Candle Structure cache (6 times/day for 3 pairs) = 18 calls
# Total = 288 + 192 + 18 = 498 calls/day (Leaves 302 credits buffer for manual commands)
SCAN_INTERVAL = 300
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

# Peak Session Timing Window (UTC) — Result of Granular Backtesting Audit:
# London Open (07:00 UTC) to London / New York Overlap (15:00 UTC).
# Eliminates late New York (post-15:00 UTC) low-volume mean-reverting chop and wide spreads.
SESSION_START_UTC = 7              # 07:00 UTC (London Open)
SESSION_END_UTC = 15               # 15:00 UTC (London / NY Peak Overlap Cutoff)
ENABLE_SESSION_FILTER = True       # Enforce peak hours on Gold (XAUUSD) and Forex (EURJPY)

# Asset-Specific Volatility & Market Physics Adaptations (From Backtest Audit)
BTC_LONG_ONLY = True               # Trade only BUY setups on BTCUSD (aligned with secular macro bull)
BTC_SL_BUFFER_PCT = 0.005          # 0.50% buffer to absorb crypto wick volatility
BTC_24H_TRADING = True             # Bitcoin operates 24/7 continuous crypto market

# Telegram notification preferences
SEND_4H_BRIEFING = False           # Set True only if 4H market structure updates are desired (default False for signal-only)
SIGNAL_PREFIX = "📊 Axiory Price Action Alert"

# Optional Gemini API Key for open-ended conversational AI chat (free from https://aistudio.google.com/)
GEMINI_API_KEY = "AIzaSyCK4yoQgncrtIzPepPjg3B54euIwmJmPdg"
