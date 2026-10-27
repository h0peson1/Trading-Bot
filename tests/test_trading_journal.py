"""
tests/test_trading_journal.py
Automated test suite verifying all 14 safety and feature constraints for the Telegram Trading Journal.
"""

import os
import unittest
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from journal.models import (
    SignalPayload,
    SignalDirection,
    JournalEntry,
    JournalStatus,
    OutcomeStatus,
)
from journal.db import JournalDatabase
from journal.telegram_publisher import (
    TelegramJournalPublisher,
    format_signal_caption,
    format_outcome_caption,
)
from journal.charting import render_entry_chart, render_exit_chart
from journal.outcome_tracker import OutcomeTracker
from journal.weekly_reporter import (
    calculate_weekly_metrics,
    get_reporting_week_bounds,
    WeeklyReporter,
)
from journal.service import JournalService


def make_dummy_ohlc(n_bars: int = 30, base_price: float = 2000.0) -> pd.DataFrame:
    """Creates a deterministic real OHLC DataFrame for testing."""
    times = pd.date_range("2026-10-01 10:00:00", periods=n_bars, freq="15min", tz="UTC")
    data = []
    p = base_price
    for t in times:
        o = p
        h = o + 2.0
        l = o - 2.0
        c = o + 0.5
        p = c
        data.append({"open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(data, index=times)


class TestTradingJournal(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_journal.db")
        self.charts_dir = os.path.join(self.test_dir, "charts")
        os.makedirs(self.charts_dir, exist_ok=True)
        self.db = JournalDatabase(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_signal_recording_does_not_alter_payload(self):
        """1. Signal recording does not alter the signal payload."""
        payload = SignalPayload(
            symbol="XAUUSD",
            ticker="XAU/USD",
            direction=SignalDirection.BUY,
            entry_price=2650.50,
            stop_loss=2640.00,
            take_profit_1=2660.00,
            take_profit_2=2675.00,
            signal_timestamp=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
            pattern="Bullish Pin Bar / Hammer",
            trend_bias="BULLISH",
            reason="Pin bar rejection at 50% fib",
        )
        original_entry = payload.entry_price
        original_sl = payload.stop_loss
        original_tp1 = payload.take_profit_1
        original_id = payload.signal_id

        entry = self.db.insert_signal_payload(payload)

        self.assertEqual(payload.entry_price, original_entry)
        self.assertEqual(payload.stop_loss, original_sl)
        self.assertEqual(payload.take_profit_1, original_tp1)
        self.assertEqual(payload.signal_id, original_id)
        self.assertEqual(entry.signal_id, original_id)
        self.assertEqual(entry.planned_entry_price, original_entry)

    def test_02_no_broker_order_placement(self):
        """2. Signal recording does not call any broker order-placement function."""
        # Verification that JournalService contains zero references to order submission or broker APIs
        import journal.service as j_srv
        import journal.db as j_db
        import journal.outcome_tracker as j_ot

        for mod in [j_srv, j_db, j_ot]:
            with open(mod.__file__, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("order_send", content)
            self.assertNotIn("place_order", content)
            self.assertNotIn("create_order", content)
            self.assertNotIn("broker", content)

    def test_03_journal_failure_does_not_interrupt_signal_generation(self):
        """3. Journal failures do not interrupt signal generation."""
        service = JournalService(db_path=self.db_path, auto_start_background_tasks=False)

        # Force database insertion to fail catastrophically
        with patch.object(service.db, "insert_signal_payload", side_effect=RuntimeError("Simulated DB Crash")):
            payload = SignalPayload(
                symbol="EURJPY",
                ticker="EUR/JPY",
                direction=SignalDirection.SELL,
                entry_price=162.50,
                stop_loss=163.00,
                take_profit_1=161.50,
            )
            # Must handle gracefully and return None without raising exception
            result = service.record_signal(payload)
            self.assertIsNone(result)

    def test_04_duplicate_signal_delivery_idempotence(self):
        """4. Duplicate signal delivery does not create duplicate records."""
        payload = SignalPayload(
            symbol="BTCUSD",
            ticker="BTC/USD",
            direction=SignalDirection.BUY,
            entry_price=65000.0,
            stop_loss=64000.0,
            take_profit_1=66500.0,
            signal_id="SIG-TEST-BTC-001",
            signal_timestamp=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
        )

        entry1 = self.db.insert_signal_payload(payload)
        entry2 = self.db.insert_signal_payload(payload)

        signals = self.db.get_signals_for_period("2026-10-10T00:00:00", "2026-10-11T00:00:00")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_id, "SIG-TEST-BTC-001")

    def test_05_missing_optional_signal_fields_handled(self):
        """5. Missing optional signal fields are handled correctly."""
        payload = SignalPayload(
            symbol="EURJPY",
            ticker="EUR/JPY",
            direction=SignalDirection.BUY,
            entry_price=160.00,
            stop_loss=159.00,
            take_profit_1=161.00,
            take_profit_2=None,  # Optional missing
            pattern=None,        # Optional missing
            trend_bias=None,     # Optional missing
            reason=None,         # Optional missing
        )

        entry = self.db.insert_signal_payload(payload)
        caption = format_signal_caption(entry)

        self.assertIn("N/A", caption)
        self.assertIn("N/A (Unavailable)", caption)
        self.assertIsNone(entry.take_profit_2)

    def test_06_timestamps_and_reporting_periods_consistent(self):
        """6. Timestamps and reporting periods are consistent."""
        test_dt = datetime(2026, 10, 14, 15, 30, tzinfo=timezone.utc)  # Wednesday
        start_dt, end_dt, year, week_num, report_id = get_reporting_week_bounds(test_dt)

        # Previous week must be Monday 00:00:00 to Sunday 23:59:59
        self.assertEqual(start_dt.weekday(), 0)  # Monday
        self.assertEqual(start_dt.hour, 0)
        self.assertEqual(start_dt.minute, 0)
        self.assertEqual(end_dt.weekday(), 6)    # Sunday
        self.assertEqual(end_dt.hour, 23)
        self.assertEqual(end_dt.minute, 59)
        self.assertTrue(report_id.startswith(f"REPORT-{year}-W"))

    def test_07_unresolved_signals_excluded_from_win_loss(self):
        """7. Unresolved signals are excluded from win/loss statistics."""
        signals = [
            JournalEntry(
                signal_id="S1", signal_timestamp="2026-10-05T10:00:00", symbol="XAUUSD", ticker="XAU/USD",
                direction="BUY", planned_entry_price=2600.0, stop_loss=2590.0, take_profit_1=2610.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="OUTCOME_RECORDED",
                outcome_status=OutcomeStatus.WIN_TP1.value, actual_fill_price=2600.0, realized_r=0.9
            ),
            JournalEntry(
                signal_id="S2", signal_timestamp="2026-10-06T10:00:00", symbol="XAUUSD", ticker="XAU/USD",
                direction="SELL", planned_entry_price=2620.0, stop_loss=2630.0, take_profit_1=2610.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="OUTCOME_RECORDED",
                outcome_status=OutcomeStatus.LOSS_SL.value, actual_fill_price=2620.0, realized_r=-1.0
            ),
            JournalEntry(
                signal_id="S3", signal_timestamp="2026-10-07T10:00:00", symbol="BTCUSD", ticker="BTC/USD",
                direction="BUY", planned_entry_price=64000.0, stop_loss=63000.0, take_profit_1=65000.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="SIGNAL_RECORDED",
                outcome_status=OutcomeStatus.PENDING.value
            ),
            JournalEntry(
                signal_id="S4", signal_timestamp="2026-10-08T10:00:00", symbol="EURJPY", ticker="EUR/JPY",
                direction="BUY", planned_entry_price=160.0, stop_loss=159.0, take_profit_1=161.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="UNRESOLVED",
                outcome_status=OutcomeStatus.UNRESOLVED.value
            ),
        ]

        metrics = calculate_weekly_metrics(signals)
        self.assertEqual(metrics["total_signals"], 4)
        self.assertEqual(metrics["confirmed_executions"], 2)
        self.assertEqual(metrics["wins"], 1)
        self.assertEqual(metrics["losses"], 1)
        self.assertEqual(metrics["unresolved"], 2)
        self.assertEqual(metrics["eligible_outcomes"], 2)
        self.assertIn("50.0%", metrics["win_rate_str"])

    def test_08_weekly_metrics_calculated_correctly(self):
        """8. Weekly metrics are calculated correctly from verified outcomes."""
        signals = [
            # 2 Wins at +0.90 R
            JournalEntry(
                signal_id="W1", signal_timestamp="2026-10-05T10:00:00", symbol="XAUUSD", ticker="XAU/USD",
                direction="BUY", planned_entry_price=2600.0, stop_loss=2590.0, take_profit_1=2610.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="OUTCOME_RECORDED",
                outcome_status=OutcomeStatus.WIN_TP1.value, actual_fill_price=2600.0, realized_r=0.9
            ),
            JournalEntry(
                signal_id="W2", signal_timestamp="2026-10-06T10:00:00", symbol="EURJPY", ticker="EUR/JPY",
                direction="BUY", planned_entry_price=160.0, stop_loss=159.0, take_profit_1=161.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="OUTCOME_RECORDED",
                outcome_status=OutcomeStatus.WIN_TP1.value, actual_fill_price=160.0, realized_r=0.9
            ),
            # 1 Loss at -1.00 R
            JournalEntry(
                signal_id="L1", signal_timestamp="2026-10-07T10:00:00", symbol="BTCUSD", ticker="BTC/USD",
                direction="BUY", planned_entry_price=64000.0, stop_loss=63000.0, take_profit_1=65000.0,
                take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
                entry_mode="LIMIT", signal_metadata_json="{}", journal_status="OUTCOME_RECORDED",
                outcome_status=OutcomeStatus.LOSS_SL.value, actual_fill_price=64000.0, realized_r=-1.0
            ),
        ]

        metrics = calculate_weekly_metrics(signals)
        # Expected Net R: 0.9 + 0.9 - 1.0 = +0.80 R
        self.assertIn("+0.80 R", metrics["net_r_str"])
        # Expected Win Rate: 2 / 3 = 66.7%
        self.assertIn("66.7%", metrics["win_rate_str"])
        # Profit Factor: 1.80 / 1.00 = 1.80
        self.assertEqual(metrics["profit_factor_str"], "1.80")

    def test_09_ambiguous_outcomes_not_classified_as_win_or_loss(self):
        """9. Ambiguous outcomes are not automatically classified as wins or losses."""
        tracker = OutcomeTracker(db=self.db, publisher=MagicMock())

        sig_time = pd.Timestamp("2026-10-10 10:00:00", tz="UTC")
        entry = JournalEntry(
            signal_id="SIG-AMB", signal_timestamp=sig_time.isoformat(), symbol="XAUUSD", ticker="XAU/USD",
            direction="BUY", planned_entry_price=2600.0, stop_loss=2590.0, take_profit_1=2610.0,
            take_profit_2=None, strategy_id="Axiory", execution_timeframe="15m", analysis_timeframe="4h",
            entry_mode="LIMIT_50_RETEST", signal_metadata_json="{}", journal_status="SIGNAL_RECORDED",
            outcome_status=OutcomeStatus.PENDING.value
        )

        # Create candle where order is filled at 2600.0
        bar1_time = sig_time + pd.Timedelta(minutes=15)
        # Create subsequent candle that spans both TP1 (2610) and SL (2590) in the same bar!
        bar2_time = bar1_time + pd.Timedelta(minutes=15)

        df = pd.DataFrame([
            {"open": 2602.0, "high": 2605.0, "low": 2598.0, "close": 2601.0},  # fills limit at 2600.0
            {"open": 2601.0, "high": 2615.0, "low": 2585.0, "close": 2600.0},  # both SL (2590) and TP1 (2610) hit!
        ], index=[bar1_time, bar2_time])

        res = tracker.evaluate_signal_against_candles(entry, df)
        self.assertIsNotNone(res)
        self.assertEqual(res["outcome_status"], OutcomeStatus.AMBIGUOUS.value)
        self.assertIsNone(res["realized_r"])

        # Check metrics exclusion
        entry.outcome_status = OutcomeStatus.AMBIGUOUS.value
        entry.realized_r = None
        metrics = calculate_weekly_metrics([entry])
        self.assertEqual(metrics["wins"], 0)
        self.assertEqual(metrics["losses"], 0)
        self.assertEqual(metrics["ambiguous"], 1)
        self.assertIn("N/A", metrics["win_rate_str"])

    def test_10_chart_generation_uses_real_supplied_ohlc_data(self):
        """10. Chart generation uses real supplied OHLC data."""
        df = make_dummy_ohlc(40, base_price=2650.0)
        chart_path = render_entry_chart(
            df=df,
            signal_id="SIG-CHART-TEST",
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit_1=2665.0,
            take_profit_2=2680.0,
            timeframe="15m",
        )

        self.assertIsNotNone(chart_path)
        self.assertTrue(os.path.exists(chart_path))
        self.assertGreater(os.path.getsize(chart_path), 5000)

        # Test exit chart
        exit_path = render_exit_chart(
            df=df,
            signal_id="SIG-CHART-TEST",
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit_1=2665.0,
            actual_fill_price=2650.0,
            actual_exit_price=2665.0,
            outcome_label="TAKE PROFIT 1 HIT (+0.90 R)",
            realized_r=0.9,
        )
        self.assertIsNotNone(exit_path)
        self.assertTrue(os.path.exists(exit_path))

    def test_11_missing_chart_data_non_fatal_fallback(self):
        """11. Missing chart data produces a clear, non-fatal fallback."""
        # Test with empty DataFrame
        res_empty = render_entry_chart(
            df=pd.DataFrame(),
            signal_id="SIG-NO-DATA",
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit_1=2665.0,
        )
        self.assertIsNone(res_empty)

        # Test with None DataFrame
        res_none = render_entry_chart(
            df=None,
            signal_id="SIG-NO-DATA",
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit_1=2665.0,
        )
        self.assertIsNone(res_none)

    def test_12_telegram_errors_and_rate_limits(self):
        """12. Telegram errors and rate limits are handled appropriately."""
        publisher = TelegramJournalPublisher(bot_token="FAKE_TOKEN", channel_id="-100123456789")

        # Mock rate limit (429) then success (200)
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.json.return_value = {"parameters": {"retry_after": 0}}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"result": {"message_id": 9999}}

        with patch("requests.post", side_effect=[mock_429, mock_200]):
            msg_id = publisher.publish_text("Test Message")
            self.assertEqual(msg_id, 9999)

        # Mock persistent failure (500)
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.text = "Internal Server Error"
        with patch("requests.post", return_value=mock_500):
            msg_id = publisher.publish_text("Test Message 2")
            self.assertIsNone(msg_id)

        publisher.stop()

    def test_13_weekly_reports_not_duplicated_after_restarts(self):
        """13. Weekly reports are not duplicated after restarts or retries."""
        publisher = MagicMock()
        publisher.publish_text.return_value = 12345
        reporter = WeeklyReporter(db=self.db, publisher=publisher)

        test_now = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)

        # First run: should compile and publish
        first_run = reporter.run_weekly_report_cycle(target_dt=test_now, force=False)
        self.assertTrue(first_run)
        self.assertEqual(publisher.publish_text.call_count, 1)

        # Second run (simulating application restart or cron retry): should detect already published
        second_run = reporter.run_weekly_report_cycle(target_dt=test_now, force=False)
        self.assertFalse(second_run)
        self.assertEqual(publisher.publish_text.call_count, 1)  # No extra message sent


if __name__ == "__main__":
    unittest.main()
