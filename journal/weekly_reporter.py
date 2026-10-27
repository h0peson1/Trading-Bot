"""
journal/weekly_reporter.py
Weekly performance summary compiler, metric calculator, and deduplicated reporter.
Strictly separates signals from confirmed executions and excludes unresolved trades from statistics.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional

from .models import JournalEntry, OutcomeStatus
from .db import JournalDatabase
from .telegram_publisher import TelegramJournalPublisher
from .config import (
    JOURNAL_TIMEZONE,
    JOURNAL_WEEKLY_REPORT_DAY,
    JOURNAL_WEEKLY_REPORT_HOUR,
)

logger = logging.getLogger("journal.weekly")


def calculate_weekly_metrics(signals: List[JournalEntry]) -> Dict[str, Any]:
    """
    Computes rigorous trading journal metrics from recorded signals and verified outcomes.
    Never treats unresolved signals as wins or losses.
    """
    total_signals = len(signals)
    by_instrument: Dict[str, Dict[str, int]] = {}
    
    confirmed_executions = 0
    wins = 0
    losses = 0
    breakevens = 0
    expired = 0
    ambiguous = 0
    unresolved = 0
    
    realized_rs: List[float] = []
    winning_rs: List[float] = []
    losing_rs: List[float] = []

    for s in signals:
        # Instrument & direction counters
        sym = s.symbol
        if sym not in by_instrument:
            by_instrument[sym] = {"BUY": 0, "SELL": 0, "TOTAL": 0}
        dir_clean = s.direction.upper()
        by_instrument[sym][dir_clean] = by_instrument[sym].get(dir_clean, 0) + 1
        by_instrument[sym]["TOTAL"] += 1

        # Execution check
        if s.actual_fill_price is not None:
            confirmed_executions += 1

        # Outcome categorisation
        status = s.outcome_status
        if status in [OutcomeStatus.WIN_TP1.value, OutcomeStatus.WIN_TP2.value]:
            wins += 1
        elif status == OutcomeStatus.LOSS_SL.value:
            losses += 1
        elif status == OutcomeStatus.BREAKEVEN.value:
            breakevens += 1
        elif status == OutcomeStatus.NOT_FILLED_EXPIRED.value:
            expired += 1
        elif status == OutcomeStatus.AMBIGUOUS.value:
            ambiguous += 1
        else:
            unresolved += 1

        if s.realized_r is not None:
            r = float(s.realized_r)
            realized_rs.append(r)
            if r > 0:
                winning_rs.append(r)
            elif r < 0:
                losing_rs.append(abs(r))

    # Eligible outcome population for Win Rate
    eligible_outcomes = wins + losses + breakevens
    if eligible_outcomes > 0:
        win_rate = (wins / eligible_outcomes) * 100.0
        win_rate_str = f"{win_rate:.1f}% ({wins}/{eligible_outcomes} eligible closed outcomes)"
    else:
        win_rate_str = "N/A (No closed outcomes in reporting period)"

    # Net R and Profit Factor calculations
    if realized_rs:
        net_r = sum(realized_rs)
        net_r_str = f"{net_r:+.2f} R"
    else:
        net_r_str = "0.00 R (No realized trade data)"

    if winning_rs:
        avg_win_r_str = f"+{sum(winning_rs) / len(winning_rs):.2f} R"
    else:
        avg_win_r_str = "N/A"

    if losing_rs:
        avg_loss_r_str = f"-{sum(losing_rs) / len(losing_rs):.2f} R"
    else:
        avg_loss_r_str = "N/A"

    gross_profit = sum(winning_rs)
    gross_loss = sum(losing_rs)
    if gross_loss > 0:
        pf = gross_profit / gross_loss
        profit_factor_str = f"{pf:.2f}"
    elif gross_profit > 0 and gross_loss == 0:
        profit_factor_str = "Undefined (100% Win Rate / 0 Losses)"
    else:
        profit_factor_str = "N/A (Insufficient closed trade data)"

    return {
        "total_signals": total_signals,
        "by_instrument": by_instrument,
        "confirmed_executions": confirmed_executions,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "expired": expired,
        "ambiguous": ambiguous,
        "unresolved": unresolved,
        "eligible_outcomes": eligible_outcomes,
        "win_rate_str": win_rate_str,
        "net_r_str": net_r_str,
        "avg_win_r_str": avg_win_r_str,
        "avg_loss_r_str": avg_loss_r_str,
        "profit_factor_str": profit_factor_str,
    }


def get_reporting_week_bounds(dt: Optional[datetime] = None) -> Tuple[datetime, datetime, int, int, str]:
    """
    Returns (start_dt, end_dt, year, week_num, report_id) for the prior completed ISO week.
    Monday 00:00:00 UTC through Sunday 23:59:59.999999 UTC.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Calculate Monday of current week
    monday_current = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dt.weekday())
    # Monday of previous week
    start_dt = monday_current - timedelta(days=7)
    # End is Sunday of previous week at 23:59:59
    end_dt = monday_current - timedelta(seconds=1)

    year, week_num, _ = start_dt.isocalendar()
    report_id = f"REPORT-{year}-W{week_num:02d}"
    return start_dt, end_dt, year, week_num, report_id


def build_weekly_report_text(
    metrics: Dict[str, Any],
    period_start_str: str,
    period_end_str: str,
    tz_str: str,
    report_id: str,
    signals: List[JournalEntry],
) -> str:
    """Formats the weekly summary into an HTML Telegram publication."""
    lines = [
        f"📅 <b>WEEKLY TRADING JOURNAL AUDIT</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🆔 <b>Report ID:</b> <code>{report_id}</code>",
        f"🗓 <b>Period:</b> {period_start_str} to {period_end_str} ({tz_str})",
        f"",
        f"<b>1. Signal & Activity Volume:</b>",
        f"• <b>Total Signals Generated:</b> {metrics['total_signals']}",
        f"• <b>Confirmed Limit Fills:</b> {metrics['confirmed_executions']}",
        f"• <b>Expired (Unfilled Limits):</b> {metrics['expired']}",
        f"",
        f"<b>2. Instrument Breakdown:</b>",
    ]

    for sym, counts in metrics["by_instrument"].items():
        lines.append(f"• <b>{sym}:</b> {counts['TOTAL']} signals (BUY: {counts.get('BUY', 0)}, SELL: {counts.get('SELL', 0)})")

    lines.extend([
        f"",
        f"<b>3. Verified Trade Outcomes:</b>",
        f"• <b>Wins:</b> {metrics['wins']}",
        f"• <b>Losses:</b> {metrics['losses']}",
        f"• <b>Breakeven:</b> {metrics['breakevens']}",
        f"• <b>Ambiguous (Same-Candle SL/TP):</b> {metrics['ambiguous']}",
        f"• <b>Unresolved / Open:</b> {metrics['unresolved']}",
        f"",
        f"<b>4. Mathematical Performance:</b>",
        f"• <b>Win Rate:</b> {metrics['win_rate_str']}",
        f"• <b>Net Realized Expectancy:</b> <b>{metrics['net_r_str']}</b>",
        f"• <b>Average Win R:</b> {metrics['avg_win_r_str']}",
        f"• <b>Average Loss R:</b> {metrics['avg_loss_r_str']}",
        f"• <b>Profit Factor:</b> {metrics['profit_factor_str']}",
        f"",
        f"<b>5. Data Integrity & Audit Notes:</b>",
        f"• <i>Unresolved and unfulfilled pending signals are strictly excluded from win rate & profit calculations.</i>",
        f"• <i>All outcomes evaluated with tick/candle causality. No fabricated trade executions.</i>",
        f"• <i>Archived signals in period: {len(signals)} recorded in SQLite journal ledger.</i>",
    ])

    return "\n".join(lines)


class WeeklyReporter:
    """Orchestrates scheduled weekly report compilation and duplicate prevention."""

    def __init__(self, db: JournalDatabase, publisher: TelegramJournalPublisher):
        self.db = db
        self.publisher = publisher

    def run_weekly_report_cycle(self, target_dt: Optional[datetime] = None, force: bool = False) -> bool:
        """
        Compiles and dispatches the weekly performance summary if due and not yet sent.
        Guarantees that each weekly period is published only once logically.
        """
        start_dt, end_dt, year, week_num, report_id = get_reporting_week_bounds(target_dt)

        if not force and self.db.is_weekly_report_published(report_id):
            logger.info(f"[Weekly Reporter]: Report {report_id} already published. Skipping duplicate.")
            return False

        logger.info(f"[Weekly Reporter]: Compiling report {report_id} for {start_dt} to {end_dt}...")
        signals = self.db.get_signals_for_period(start_dt.isoformat(), end_dt.isoformat())
        metrics = calculate_weekly_metrics(signals)

        report_text = build_weekly_report_text(
            metrics=metrics,
            period_start_str=start_dt.strftime("%Y-%m-%d %H:%M UTC"),
            period_end_str=end_dt.strftime("%Y-%m-%d %H:%M UTC"),
            tz_str=JOURNAL_TIMEZONE,
            report_id=report_id,
            signals=signals,
        )

        # Dispatch to channel via publisher
        msg_id = self.publisher.publish_text(report_text)

        # Persist report to guarantee duplicate prevention across restarts
        self.db.record_weekly_report(
            report_id=report_id,
            year=year,
            week_number=week_num,
            period_start=start_dt.isoformat(),
            period_end=end_dt.isoformat(),
            timezone=JOURNAL_TIMEZONE,
            report_content=report_text,
            telegram_message_id=msg_id,
        )
        logger.info(f"[Weekly Reporter]: Report {report_id} published and recorded successfully.")
        return True

    def check_and_publish_if_scheduled(self, now: Optional[datetime] = None):
        """Checks if current time matches scheduled day and hour."""
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Check day of week and hour
        if now.weekday() == JOURNAL_WEEKLY_REPORT_DAY and now.hour == JOURNAL_WEEKLY_REPORT_HOUR:
            self.run_weekly_report_cycle(target_dt=now, force=False)
