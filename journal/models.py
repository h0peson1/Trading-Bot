"""
journal/models.py
Data models and enumerations for the trading journal.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class JournalStatus(str, Enum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_RECORDED = "SIGNAL_RECORDED"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    UNRESOLVED = "UNRESOLVED"


class OutcomeStatus(str, Enum):
    PENDING = "PENDING"
    NOT_FILLED_EXPIRED = "NOT_FILLED_EXPIRED"
    WIN_TP1 = "WIN_TP1"
    WIN_TP2 = "WIN_TP2"
    LOSS_SL = "LOSS_SL"
    BREAKEVEN = "BREAKEVEN"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class SignalPayload:
    """Raw signal payload emitted by the bot's signal detection logic."""
    symbol: str
    ticker: str
    direction: SignalDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    strategy_id: str = "Axiory Price Action"
    execution_timeframe: str = "15min"
    analysis_timeframe: str = "4h"
    signal_timestamp: Optional[datetime] = None
    candle_time: Optional[datetime] = None
    signal_generated_at: Optional[datetime] = None
    entry_mode: str = "LIMIT_50_RETEST"
    pattern: Optional[str] = None
    trend_bias: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_id: Optional[str] = None

    def __post_init__(self):
        # Coerce strings or pandas Timestamps to python datetime
        if isinstance(self.candle_time, str):
            self.candle_time = datetime.fromisoformat(self.candle_time.replace("Z", "+00:00"))
        elif hasattr(self.candle_time, "to_pydatetime"):
            self.candle_time = self.candle_time.to_pydatetime()

        if isinstance(self.signal_timestamp, str):
            self.signal_timestamp = datetime.fromisoformat(self.signal_timestamp.replace("Z", "+00:00"))
        elif hasattr(self.signal_timestamp, "to_pydatetime"):
            self.signal_timestamp = self.signal_timestamp.to_pydatetime()

        # 1. candle_time (timestamp of the confirmation candle)
        if self.candle_time is None and self.signal_timestamp is not None:
            self.candle_time = self.signal_timestamp
        elif self.candle_time is not None and self.signal_timestamp is None:
            self.signal_timestamp = self.candle_time
        elif self.candle_time is None and self.signal_timestamp is None:
            self.candle_time = datetime.now(timezone.utc)
            self.signal_timestamp = self.candle_time

        if self.candle_time.tzinfo is None:
            self.candle_time = self.candle_time.replace(tzinfo=timezone.utc)
        if self.signal_timestamp.tzinfo is None:
            self.signal_timestamp = self.signal_timestamp.replace(tzinfo=timezone.utc)

        # 2. signal_generated_at (when strategy actually generated the signal)
        if self.signal_generated_at is None:
            self.signal_generated_at = datetime.now(timezone.utc)
        elif self.signal_generated_at.tzinfo is None:
            self.signal_generated_at = self.signal_generated_at.replace(tzinfo=timezone.utc)

        if isinstance(self.direction, str):
            self.direction = SignalDirection(self.direction.upper())

        if not self.signal_id:
            date_prefix = self.signal_timestamp.strftime("%Y%m%d")
            clean_sym = self.symbol.replace("/", "").replace(":", "")
            rand_suffix = uuid.uuid4().hex[:6].upper()
            self.signal_id = f"SIG-{date_prefix}-{clean_sym}-{rand_suffix}"


@dataclass
class JournalEntry:
    """Persistent journal database entry representation."""
    signal_id: str
    signal_timestamp: str  # ISO 8601 string in UTC
    symbol: str
    ticker: str
    direction: str
    planned_entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    strategy_id: str
    execution_timeframe: str
    analysis_timeframe: str
    entry_mode: str
    signal_metadata_json: str
    journal_status: str
    outcome_status: str
    filled_timestamp: Optional[str] = None
    actual_fill_price: Optional[float] = None
    exit_timestamp: Optional[str] = None
    actual_exit_price: Optional[float] = None
    realized_r: Optional[float] = None
    entry_chart_path: Optional[str] = None
    exit_chart_path: Optional[str] = None
    telegram_message_id: Optional[int] = None
    telegram_delivery_status: str = "PENDING"
    error_message: Optional[str] = None
    # Four-point timestamp audit
    candle_time: Optional[str] = None
    signal_generated_at: Optional[str] = None
    telegram_send_started_at: Optional[str] = None
    telegram_delivered_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
