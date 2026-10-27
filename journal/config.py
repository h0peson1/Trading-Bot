"""
journal/config.py
Journal configuration management with environment variable priority and project fallbacks.
"""

import os
from typing import Optional
import config as project_config


def get_telegram_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token and token.strip():
        return token.strip()
    return getattr(project_config, "TELEGRAM_BOT_TOKEN", "").strip()


def get_telegram_channel_id() -> Optional[str]:
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    if channel_id and channel_id.strip():
        return channel_id.strip()
    cid = getattr(project_config, "TELEGRAM_CHANNEL_ID", None)
    if cid and str(cid).strip():
        return str(cid).strip()
    # Fallback to Admin Chat ID so journal reports & trade updates are always delivered
    admin_id = getattr(project_config, "ADMIN_CHAT_ID", getattr(project_config, "TELEGRAM_CHAT_ID", None))
    return str(admin_id).strip() if admin_id else None


JOURNAL_DB_PATH = os.getenv("JOURNAL_DB_PATH", "trading_journal.db")
JOURNAL_CHARTS_DIR = os.getenv("JOURNAL_CHARTS_DIR", "journal_charts")
JOURNAL_TIMEZONE = os.getenv("JOURNAL_TIMEZONE", "UTC")

# Scheduled Report Timing (UTC):
# 1. Friday evening after 10:00 PM UTC (Forex & Metals Market Close)
JOURNAL_FOREX_REPORT_DAY = int(os.getenv("JOURNAL_FOREX_REPORT_DAY", getattr(project_config, "JOURNAL_FOREX_REPORT_DAY", 4)))
JOURNAL_FOREX_REPORT_HOUR = int(os.getenv("JOURNAL_FOREX_REPORT_HOUR", getattr(project_config, "JOURNAL_FOREX_REPORT_HOUR", 22)))

# 2. Sunday night 11:00 PM UTC before Monday open (Bitcoin 24/7 Cycle Wrap-up)
JOURNAL_CRYPTO_REPORT_DAY = int(os.getenv("JOURNAL_CRYPTO_REPORT_DAY", getattr(project_config, "JOURNAL_CRYPTO_REPORT_DAY", 6)))
JOURNAL_CRYPTO_REPORT_HOUR = int(os.getenv("JOURNAL_CRYPTO_REPORT_HOUR", getattr(project_config, "JOURNAL_CRYPTO_REPORT_HOUR", 23)))

# Legacy / default fallback
JOURNAL_WEEKLY_REPORT_DAY = JOURNAL_CRYPTO_REPORT_DAY
JOURNAL_WEEKLY_REPORT_HOUR = JOURNAL_CRYPTO_REPORT_HOUR

# Interval for outcome monitoring scan in seconds
JOURNAL_OUTCOME_CHECK_INTERVAL = int(os.getenv("JOURNAL_OUTCOME_CHECK_INTERVAL", "300"))

# Maximum 15m bars to wait for pending limit order fill before marking NOT_FILLED_EXPIRED (~24 hours = 96 bars)
JOURNAL_MAX_PENDING_BARS = int(os.getenv("JOURNAL_MAX_PENDING_BARS", "96"))

# Maximum bars a filled position can remain open before being marked UNRESOLVED (~5 days = 480 bars)
JOURNAL_MAX_HOLDING_BARS = int(os.getenv("JOURNAL_MAX_HOLDING_BARS", "480"))
