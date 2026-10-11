"""
Gold Backtest Scheduled Worker
Monitors until 8:00 PM (20:00 local time) and dispatches the final comprehensive
multi-timeframe Gold backtest performance report directly to Telegram.
"""

import sys
import time
from datetime import datetime
import gold_backtest_telegram

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_HOUR = 20
TARGET_MINUTE = 0


def wait_until_target():
    now = datetime.now()
    target_today = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)

    if now < target_today:
        wait_seconds = (target_today - now).total_seconds()
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Waiting {int(wait_seconds)} seconds until 8:00 PM (20:00)...")
        time.sleep(wait_seconds)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 8:00 PM reached! Running final Gold backtest study...")
    report = gold_backtest_telegram.execute_gold_backtest_study()
    print("Delivering final report to Telegram...")
    success = gold_backtest_telegram.send_telegram(report)
    if success:
        print("✅ 8:00 PM Gold Report delivered to Telegram successfully!")
    else:
        print("❌ Delivery failed.")


if __name__ == "__main__":
    wait_until_target()
