"""
journal/db.py
SQLite database persistence layer for the trading journal.
Ensures thread-safety, schema integrity, and historical durability across restarts.
"""

import os
import sqlite3
import threading
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .models import JournalEntry, JournalStatus, OutcomeStatus, SignalPayload


DEFAULT_DB_PATH = "trading_journal.db"


class JournalDatabase:
    """Thread-safe SQLite database manager for the trading journal."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for concurrency and durability
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self):
        """Initializes tables, constraints, and indexes."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS journal_signals (
                        signal_id TEXT PRIMARY KEY,
                        signal_timestamp TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        planned_entry_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        take_profit_1 REAL NOT NULL,
                        take_profit_2 REAL,
                        strategy_id TEXT NOT NULL,
                        execution_timeframe TEXT NOT NULL,
                        analysis_timeframe TEXT NOT NULL,
                        entry_mode TEXT NOT NULL,
                        signal_metadata_json TEXT NOT NULL,
                        journal_status TEXT NOT NULL,
                        outcome_status TEXT NOT NULL,
                        filled_timestamp TEXT,
                        actual_fill_price REAL,
                        exit_timestamp TEXT,
                        actual_exit_price REAL,
                        realized_r REAL,
                        entry_chart_path TEXT,
                        exit_chart_path TEXT,
                        telegram_message_id INTEGER,
                        telegram_delivery_status TEXT DEFAULT 'PENDING',
                        error_message TEXT,
                        candle_time TEXT,
                        signal_generated_at TEXT,
                        telegram_send_started_at TEXT,
                        telegram_delivered_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                # Automatic schema migrations for existing databases
                for col in [
                    "candle_time",
                    "signal_generated_at",
                    "telegram_send_started_at",
                    "telegram_delivered_at",
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE journal_signals ADD COLUMN {col} TEXT;")
                    except sqlite3.OperationalError:
                        pass

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts 
                    ON journal_signals (symbol, signal_timestamp);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_signals_journal_status 
                    ON journal_signals (journal_status);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_signals_outcome_status 
                    ON journal_signals (outcome_status);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_signals_timestamp 
                    ON journal_signals (signal_timestamp);
                """)

                # Table to prevent duplicate weekly reports
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS journal_weekly_reports (
                        report_id TEXT PRIMARY KEY,
                        year INTEGER NOT NULL,
                        week_number INTEGER NOT NULL,
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        report_content TEXT NOT NULL,
                        telegram_message_id INTEGER,
                        published_at TEXT NOT NULL
                    );
                """)

                conn.commit()
            finally:
                conn.close()

    def insert_signal_payload(
        self,
        payload: SignalPayload,
        entry_chart_path: Optional[str] = None
    ) -> JournalEntry:
        """
        Inserts a new SignalPayload into the journal database as SIGNAL_RECORDED.
        Returns the created JournalEntry.
        Guarantees idempotency (returns existing if already present).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        sig_ts = payload.signal_timestamp.isoformat() if payload.signal_timestamp else now_iso
        candle_ts = payload.candle_time.isoformat() if payload.candle_time else sig_ts
        gen_ts = payload.signal_generated_at.isoformat() if payload.signal_generated_at else now_iso

        metadata_dict = {
            "pattern": payload.pattern,
            "trend_bias": payload.trend_bias,
            "reason": payload.reason,
            **payload.metadata,
        }
        metadata_json = json.dumps(metadata_dict, default=str)

        entry = JournalEntry(
            signal_id=payload.signal_id,
            signal_timestamp=sig_ts,
            symbol=payload.symbol,
            ticker=payload.ticker,
            direction=payload.direction.value if hasattr(payload.direction, "value") else str(payload.direction),
            planned_entry_price=float(payload.entry_price),
            stop_loss=float(payload.stop_loss),
            take_profit_1=float(payload.take_profit_1),
            take_profit_2=float(payload.take_profit_2) if payload.take_profit_2 is not None else None,
            strategy_id=payload.strategy_id,
            execution_timeframe=payload.execution_timeframe,
            analysis_timeframe=payload.analysis_timeframe,
            entry_mode=payload.entry_mode,
            signal_metadata_json=metadata_json,
            journal_status=JournalStatus.SIGNAL_RECORDED.value,
            outcome_status=OutcomeStatus.PENDING.value,
            entry_chart_path=entry_chart_path,
            candle_time=candle_ts,
            signal_generated_at=gen_ts,
            created_at=now_iso,
            updated_at=now_iso,
        )

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO journal_signals (
                        signal_id, signal_timestamp, symbol, ticker, direction,
                        planned_entry_price, stop_loss, take_profit_1, take_profit_2,
                        strategy_id, execution_timeframe, analysis_timeframe, entry_mode,
                        signal_metadata_json, journal_status, outcome_status,
                        entry_chart_path, telegram_delivery_status, candle_time, signal_generated_at,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, 'PENDING', ?, ?,
                        ?, ?
                    );
                """, (
                    entry.signal_id,
                    entry.signal_timestamp,
                    entry.symbol,
                    entry.ticker,
                    entry.direction,
                    entry.planned_entry_price,
                    entry.stop_loss,
                    entry.take_profit_1,
                    entry.take_profit_2,
                    entry.strategy_id,
                    entry.execution_timeframe,
                    entry.analysis_timeframe,
                    entry.entry_mode,
                    entry.signal_metadata_json,
                    entry.journal_status,
                    entry.outcome_status,
                    entry.entry_chart_path,
                    entry.candle_time,
                    entry.signal_generated_at,
                    entry.created_at,
                    entry.updated_at,
                ))
                conn.commit()
            finally:
                conn.close()

        return entry

    def update_telegram_delivery(
        self,
        signal_id: str,
        message_id: Optional[int],
        status: str,
        error_message: Optional[str] = None,
        send_started_at: Optional[str] = None,
        delivered_at: Optional[str] = None,
    ):
        """Updates Telegram message delivery status, channel message ID, and delivery timestamps."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE journal_signals
                    SET telegram_message_id = COALESCE(?, telegram_message_id),
                        telegram_delivery_status = ?,
                        error_message = ?,
                        telegram_send_started_at = COALESCE(?, telegram_send_started_at),
                        telegram_delivered_at = COALESCE(?, telegram_delivered_at),
                        updated_at = ?
                    WHERE signal_id = ?;
                """, (message_id, status, error_message, send_started_at, delivered_at, now_iso, signal_id))
                conn.commit()
            finally:
                conn.close()

    def update_outcome(
        self,
        signal_id: str,
        outcome_status: str,
        journal_status: str,
        filled_timestamp: Optional[str] = None,
        actual_fill_price: Optional[float] = None,
        exit_timestamp: Optional[str] = None,
        actual_exit_price: Optional[float] = None,
        realized_r: Optional[float] = None,
        exit_chart_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Updates the trade lifecycle and resolved outcome for a signal."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE journal_signals
                    SET outcome_status = ?,
                        journal_status = ?,
                        filled_timestamp = COALESCE(?, filled_timestamp),
                        actual_fill_price = COALESCE(?, actual_fill_price),
                        exit_timestamp = COALESCE(?, exit_timestamp),
                        actual_exit_price = COALESCE(?, actual_exit_price),
                        realized_r = COALESCE(?, realized_r),
                        exit_chart_path = COALESCE(?, exit_chart_path),
                        error_message = COALESCE(?, error_message),
                        updated_at = ?
                    WHERE signal_id = ?;
                """, (
                    outcome_status,
                    journal_status,
                    filled_timestamp,
                    actual_fill_price,
                    exit_timestamp,
                    actual_exit_price,
                    realized_r,
                    exit_chart_path,
                    error_message,
                    now_iso,
                    signal_id,
                ))
                conn.commit()
            finally:
                conn.close()

    def get_signal(self, signal_id: str) -> Optional[JournalEntry]:
        """Fetches a single journal signal entry by signal_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM journal_signals WHERE signal_id = ?;", (signal_id,))
                row = cursor.fetchone()
                if row:
                    return JournalEntry(**dict(row))
                return None
            finally:
                conn.close()

    def get_pending_signals(self) -> List[JournalEntry]:
        """Fetches all signals whose outcomes are currently pending."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM journal_signals
                    WHERE outcome_status = ?
                    ORDER BY signal_timestamp ASC;
                """, (OutcomeStatus.PENDING.value,))
                rows = cursor.fetchall()
                return [JournalEntry(**dict(r)) for r in rows]
            finally:
                conn.close()

    def get_signals_for_period(self, start_iso: str, end_iso: str) -> List[JournalEntry]:
        """Returns all signals within the timestamp interval [start_iso, end_iso)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM journal_signals
                    WHERE signal_timestamp >= ? AND signal_timestamp < ?
                    ORDER BY signal_timestamp ASC;
                """, (start_iso, end_iso))
                rows = cursor.fetchall()
                return [JournalEntry(**dict(r)) for r in rows]
            finally:
                conn.close()

    def is_weekly_report_published(self, report_id: str) -> bool:
        """Checks if a report with report_id (e.g., 'REPORT-2026-W42') has already been recorded."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM journal_weekly_reports WHERE report_id = ?;", (report_id,))
                return cursor.fetchone() is not None
            finally:
                conn.close()

    def record_weekly_report(
        self,
        report_id: str,
        year: int,
        week_number: int,
        period_start: str,
        period_end: str,
        report_tz: str = "UTC",
        report_content: str = "",
        telegram_message_id: Optional[int] = None,
        **kwargs
    ):
        """Records a published weekly report to guarantee duplicate prevention."""
        tz_val = kwargs.get("timezone", report_tz)
        content_val = kwargs.get("content", report_content)
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO journal_weekly_reports (
                        report_id, year, week_number, period_start, period_end,
                        timezone, report_content, telegram_message_id, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    report_id,
                    year,
                    week_number,
                    period_start,
                    period_end,
                    tz_val,
                    content_val,
                    telegram_message_id,
                    now_iso,
                ))
                conn.commit()
            finally:
                conn.close()
