"""
journal/outcome_tracker.py
Passive outcome monitoring service.
Evaluates subsequent market data against pending journal signals without altering trading strategy.
Guarantees non-ambiguity and never fabricates results.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any, List
import pandas as pd

from .models import JournalEntry, JournalStatus, OutcomeStatus
from .db import JournalDatabase
from .charting import render_exit_chart
from .telegram_publisher import TelegramJournalPublisher
from .config import JOURNAL_MAX_PENDING_BARS, JOURNAL_MAX_HOLDING_BARS
import config as project_config

logger = logging.getLogger("journal.outcome")


class OutcomeTracker:
    """
    Monitors market candles to track whether pending limit orders filled,
    and whether active positions reached TP1, TP2, or SL.
    """

    def __init__(
        self,
        db: JournalDatabase,
        publisher: TelegramJournalPublisher,
        fetch_candles_fn: Optional[Callable[[str, str], pd.DataFrame]] = None,
    ):
        self.db = db
        self.publisher = publisher
        self.fetch_candles_fn = fetch_candles_fn

    def evaluate_signal_against_candles(
        self,
        entry: JournalEntry,
        df: pd.DataFrame
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates a single JournalEntry against recent closed 15m candles.
        Returns a dict of updates if outcome resolved, or None if still pending.
        """
        if df is None or df.empty:
            return None

        # Clean column names
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        sig_time = pd.to_datetime(entry.signal_timestamp, utc=True)
        # Ensure df index is tz-aware UTC
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Slice candles strictly after signal creation
        post_signal_df = df[df.index > sig_time]
        if post_signal_df.empty:
            return None

        is_buy = entry.direction.upper() == "BUY"
        planned_entry = entry.planned_entry_price
        sl = entry.stop_loss
        tp1 = entry.take_profit_1
        tp2 = entry.take_profit_2

        # Step 1: Check Fill status if not yet filled
        fill_time_str = entry.filled_timestamp
        fill_price = entry.actual_fill_price

        if fill_price is None:
            filled = False
            for bar_idx, (bar_time, bar) in enumerate(post_signal_df.iterrows()):
                if bar_idx >= JOURNAL_MAX_PENDING_BARS:
                    # Pending limit order expired without being touched
                    return {
                        "outcome_status": OutcomeStatus.NOT_FILLED_EXPIRED.value,
                        "journal_status": JournalStatus.EXPIRED.value,
                        "filled_timestamp": None,
                        "actual_fill_price": None,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": planned_entry,
                        "realized_r": 0.0,
                        "outcome_label": "ORDER EXPIRED (NOT FILLED)",
                    }

                if is_buy and bar["low"] <= planned_entry:
                    filled = True
                    fill_time_str = bar_time.isoformat()
                    fill_price = planned_entry
                    break
                elif not is_buy and bar["high"] >= planned_entry:
                    filled = True
                    fill_time_str = bar_time.isoformat()
                    fill_price = planned_entry
                    break

            if not filled:
                # Still waiting for limit fill
                return None

            # Mark order as filled and continue to check for TP/SL on subsequent bars
            self.db.update_outcome(
                signal_id=entry.signal_id,
                outcome_status=OutcomeStatus.PENDING.value,
                journal_status=JournalStatus.OUTCOME_PENDING.value,
                filled_timestamp=fill_time_str,
                actual_fill_price=fill_price,
            )

        # Step 2: Order is filled. Now evaluate subsequent bars for TP / SL
        fill_dt = pd.to_datetime(fill_time_str, utc=True)
        post_fill_df = post_signal_df[post_signal_df.index >= fill_dt]

        if post_fill_df.empty:
            return None

        # Calculate initial risk unit
        risk_per_unit = abs(fill_price - sl)
        if risk_per_unit <= 0:
            risk_per_unit = fill_price * 0.001

        tp1_r = getattr(project_config, "TP1_RR", 0.9)

        for bar_idx, (bar_time, bar) in enumerate(post_fill_df.iterrows()):
            if bar_idx >= JOURNAL_MAX_HOLDING_BARS:
                return {
                    "outcome_status": OutcomeStatus.UNRESOLVED.value,
                    "journal_status": JournalStatus.UNRESOLVED.value,
                    "filled_timestamp": fill_time_str,
                    "actual_fill_price": fill_price,
                    "exit_timestamp": bar_time.isoformat(),
                    "actual_exit_price": bar["close"],
                    "realized_r": None,
                    "outcome_label": "UNRESOLVED (MAX HOLD TIME)",
                }

            b_high = bar["high"]
            b_low = bar["low"]

            if is_buy:
                hit_tp1 = b_high >= tp1
                hit_sl = b_low <= sl

                # Rule: Ambiguous same-candle conflict
                if hit_tp1 and hit_sl:
                    return {
                        "outcome_status": OutcomeStatus.AMBIGUOUS.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": sl,
                        "realized_r": None,
                        "outcome_label": "AMBIGUOUS (SAME-CANDLE TP1 & SL)",
                    }

                if hit_sl:
                    return {
                        "outcome_status": OutcomeStatus.LOSS_SL.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": sl,
                        "realized_r": -1.0,
                        "outcome_label": "STOP LOSS HIT (-1.00 R)",
                    }

                if hit_tp1:
                    return {
                        "outcome_status": OutcomeStatus.WIN_TP1.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": tp1,
                        "realized_r": tp1_r,
                        "outcome_label": f"TAKE PROFIT 1 HIT (+{tp1_r:.2f} R)",
                    }

            else:  # SELL
                hit_tp1 = b_low <= tp1
                hit_sl = b_high >= sl

                # Rule: Ambiguous same-candle conflict
                if hit_tp1 and hit_sl:
                    return {
                        "outcome_status": OutcomeStatus.AMBIGUOUS.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": sl,
                        "realized_r": None,
                        "outcome_label": "AMBIGUOUS (SAME-CANDLE TP1 & SL)",
                    }

                if hit_sl:
                    return {
                        "outcome_status": OutcomeStatus.LOSS_SL.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": sl,
                        "realized_r": -1.0,
                        "outcome_label": "STOP LOSS HIT (-1.00 R)",
                    }

                if hit_tp1:
                    return {
                        "outcome_status": OutcomeStatus.WIN_TP1.value,
                        "journal_status": JournalStatus.OUTCOME_RECORDED.value,
                        "filled_timestamp": fill_time_str,
                        "actual_fill_price": fill_price,
                        "exit_timestamp": bar_time.isoformat(),
                        "actual_exit_price": tp1,
                        "realized_r": tp1_r,
                        "outcome_label": f"TAKE PROFIT 1 HIT (+{tp1_r:.2f} R)",
                    }

        return None

    def process_pending_outcomes(self):
        """Iterates through pending journal signals and verifies outcomes."""
        pending_signals = self.db.get_pending_signals()
        if not pending_signals:
            return

        if not self.fetch_candles_fn:
            logger.debug("[Outcome Tracker]: No candle fetch function provided. Skipping check.")
            return

        for entry in pending_signals:
            try:
                # Fetch recent execution timeframe candles
                df = self.fetch_candles_fn(entry.ticker, entry.execution_timeframe)
                if df is None or df.empty:
                    continue

                res = self.evaluate_signal_against_candles(entry, df)
                if res is None:
                    continue

                exit_chart_path = None
                try:
                    exit_chart_path = render_exit_chart(
                        df=df,
                        signal_id=entry.signal_id,
                        symbol=entry.symbol,
                        direction=entry.direction,
                        entry_price=entry.planned_entry_price,
                        stop_loss=entry.stop_loss,
                        take_profit_1=entry.take_profit_1,
                        actual_fill_price=res["actual_fill_price"],
                        actual_exit_price=res["actual_exit_price"],
                        outcome_label=res["outcome_label"],
                        realized_r=res["realized_r"],
                        timeframe=entry.execution_timeframe,
                    )
                except Exception as chart_err:
                    logger.error(f"[Outcome Exit Chart Error]: {chart_err}")

                # Update database
                self.db.update_outcome(
                    signal_id=entry.signal_id,
                    outcome_status=res["outcome_status"],
                    journal_status=res["journal_status"],
                    filled_timestamp=res["filled_timestamp"],
                    actual_fill_price=res["actual_fill_price"],
                    exit_timestamp=res["exit_timestamp"],
                    actual_exit_price=res["actual_exit_price"],
                    realized_r=res["realized_r"],
                    exit_chart_path=exit_chart_path,
                )

                # Fetch updated entry and publish update to Telegram channel
                updated_entry = self.db.get_signal(entry.signal_id)
                if updated_entry:
                    self.publisher.enqueue(
                        self.publisher.publish_outcome_entry,
                        updated_entry,
                        exit_chart_path,
                    )

            except Exception as e:
                logger.error(f"[Outcome Tracker Exception on {entry.signal_id}]: {e}", exc_info=True)
