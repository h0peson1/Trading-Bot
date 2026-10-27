"""
journal/service.py
Unified JournalService facade.
Coordinates database persistence, chart generation, Telegram channel publishing,
outcome monitoring, and weekly reports with complete non-blocking isolation.
"""

import logging
import threading
import time
from typing import Optional, Callable
import pandas as pd

from .models import SignalPayload, JournalEntry
from .db import JournalDatabase
from .config import JOURNAL_DB_PATH, JOURNAL_OUTCOME_CHECK_INTERVAL
from .charting import render_entry_chart
from .telegram_publisher import TelegramJournalPublisher
from .outcome_tracker import OutcomeTracker
from .weekly_reporter import WeeklyReporter

logger = logging.getLogger("journal.service")


class JournalService:
    """
    Main facade for the Trading Journal.
    Acts as a non-invasive, failsafe interface for signal recording.
    """

    def __init__(
        self,
        db_path: str = JOURNAL_DB_PATH,
        fetch_candles_fn: Optional[Callable[[str, str], pd.DataFrame]] = None,
        auto_start_background_tasks: bool = True,
    ):
        self.db = JournalDatabase(db_path=db_path)
        self.publisher = TelegramJournalPublisher()
        self.outcome_tracker = OutcomeTracker(
            db=self.db,
            publisher=self.publisher,
            fetch_candles_fn=fetch_candles_fn,
        )
        self.weekly_reporter = WeeklyReporter(
            db=self.db,
            publisher=self.publisher,
        )

        self._running = False
        self._bg_thread: Optional[threading.Thread] = None

        if auto_start_background_tasks:
            self.start_background_tasks()

    def start_background_tasks(self):
        """Starts a resilient background thread for outcome checking and weekly report scheduling."""
        if self._running:
            return
        self._running = True
        self._bg_thread = threading.Thread(
            target=self._background_loop,
            name="JournalBackgroundWorker",
            daemon=True,
        )
        self._bg_thread.start()
        logger.info("[Journal Service]: Background worker started.")

    def stop(self):
        """Gracefully halts background workers and publisher."""
        self._running = False
        self.publisher.stop()
        logger.info("[Journal Service]: Stopped.")

    def _background_loop(self):
        """Periodic background loop checking outcomes and weekly report schedules."""
        while self._running:
            try:
                # 1. Evaluate pending signal outcomes against fresh candles
                self.outcome_tracker.process_pending_outcomes()

                # 2. Check if weekly summary is scheduled
                self.weekly_reporter.check_and_publish_if_scheduled()

            except Exception as e:
                logger.error(f"[Journal Background Worker Exception]: {e}", exc_info=True)

            # Sleep configured interval in small slices for fast shutdown
            for _ in range(max(1, JOURNAL_OUTCOME_CHECK_INTERVAL // 5)):
                if not self._running:
                    break
                time.sleep(5)

    def record_signal(
        self,
        payload: SignalPayload,
        ohlc_df: Optional[pd.DataFrame] = None,
    ) -> Optional[JournalEntry]:
        """
        Records a newly generated signal into the persistent journal and publishes to Telegram.
        Guaranteed to NEVER raise an unhandled exception or block the caller.
        """
        try:
            # 1. Generate real OHLC entry chart if candle data is available
            chart_path = None
            if ohlc_df is not None and not ohlc_df.empty:
                try:
                    chart_path = render_entry_chart(
                        df=ohlc_df,
                        signal_id=payload.signal_id,
                        symbol=payload.symbol,
                        direction=payload.direction.value if hasattr(payload.direction, "value") else str(payload.direction),
                        entry_price=payload.entry_price,
                        stop_loss=payload.stop_loss,
                        take_profit_1=payload.take_profit_1,
                        take_profit_2=payload.take_profit_2,
                        signal_timestamp=payload.signal_timestamp,
                        timeframe=payload.execution_timeframe,
                    )
                except Exception as chart_err:
                    logger.error(f"[Journal Service]: Chart rendering failed: {chart_err}. Continuing with text.")

            # 2. Persist signal into SQLite journal ledger
            entry = self.db.insert_signal_payload(payload=payload, entry_chart_path=chart_path)

            # 3. Asynchronously enqueue Telegram channel publication
            def _delivery_callback(
                msg_id: Optional[int],
                status: str,
                send_started_at: Optional[str] = None,
                delivered_at: Optional[str] = None,
            ):
                self.db.update_telegram_delivery(
                    signal_id=entry.signal_id,
                    message_id=msg_id,
                    status=status,
                    send_started_at=send_started_at,
                    delivered_at=delivered_at,
                )

            self.publisher.enqueue(
                self.publisher.publish_signal_entry,
                entry,
                chart_path,
                _delivery_callback,
            )

            logger.info(f"[Journal Service]: Recorded signal {entry.signal_id} ({entry.symbol} {entry.direction}).")
            return entry

        except Exception as e:
            # Failsafe non-negotiable rule: a journal error must never interrupt the trading engine
            logger.critical(f"[Journal Service CRITICAL]: Failed to record signal: {e}", exc_info=True)
            return None

    def trigger_outcome_check(self):
        """Manually trigger outcome checks on pending signals."""
        self.outcome_tracker.process_pending_outcomes()

    def trigger_weekly_report(self, force: bool = False) -> bool:
        """Manually trigger publication of the weekly performance report."""
        return self.weekly_reporter.run_weekly_report_cycle(force=force)


# Singleton instance helper
_GLOBAL_JOURNAL_SERVICE: Optional[JournalService] = None


def get_journal_service(fetch_candles_fn: Optional[Callable[[str, str], pd.DataFrame]] = None) -> JournalService:
    global _GLOBAL_JOURNAL_SERVICE
    if _GLOBAL_JOURNAL_SERVICE is None:
        _GLOBAL_JOURNAL_SERVICE = JournalService(fetch_candles_fn=fetch_candles_fn)
    return _GLOBAL_JOURNAL_SERVICE
