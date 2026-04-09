from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class InstrumentType(StrEnum):
    BINARY = "binary"
    DIGITAL = "digital"


class TradeDirection(StrEnum):
    CALL = "call"
    PUT = "put"


class TradeResult(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    EXPIRED_UNKNOWN = "EXPIRED_UNKNOWN"


class SessionLabel(StrEnum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP = "overlap"
    OFF_SESSION = "off_session"


@dataclass(slots=True)
class StrategyVersion:
    strategy_version_id: str
    created_at_utc: datetime
    strategy_name: str
    parameter_hash: str
    parameters: dict[str, Any]
    created_by: str
    approval_status: str
    code_ref: str | None = None
    change_reason: str | None = None
    approved_by: str | None = None


@dataclass(slots=True)
class BrokerOrderAttempt:
    trade_id: str
    submitted_at_utc: datetime
    broker_name: str
    account_mode: str
    asset: str
    direction: TradeDirection
    amount: float
    expiry_sec: int
    submission_status: str
    signal_id: str | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    payout_snapshot: float | None = None
    submission_error_code: str | None = None
    submission_error_message: str | None = None
    raw_request_json: dict[str, Any] = field(default_factory=dict)
    raw_response_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SignalEvent:
    signal_id: str
    created_at_utc: datetime
    strategy_version_id: str
    asset: str
    instrument_type: InstrumentType
    timeframe_sec: int
    direction: TradeDirection
    intended_amount: float
    intended_expiry_sec: int
    entry_reason: str
    session_label: SessionLabel
    signal_strength: float | None = None
    indicator_snapshot: dict[str, Any] = field(default_factory=dict)
    market_snapshot: dict[str, Any] = field(default_factory=dict)
    is_filtered_out: bool = False
    filter_reason: str | None = None


@dataclass(slots=True)
class TradeJournalRecord:
    trade_id: str
    signal_id: str | None
    strategy_version_id: str
    opened_at_utc: datetime
    closed_at_utc: datetime | None
    asset: str
    instrument_type: InstrumentType
    timeframe_sec: int
    direction: TradeDirection
    amount: float
    expiry_sec: int
    account_mode: str
    result: TradeResult | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    payout_snapshot: float | None = None
    profit_loss_abs: float | None = None
    profit_loss_pct_risk: float | None = None
    fees_abs: float = 0.0
    duration_ms: int | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    close_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    is_replay: bool = False
    journal_version: int = 1
    created_at_utc: datetime | None = None
    updated_at_utc: datetime | None = None


@dataclass(slots=True)
class MetricSnapshot:
    total_trades: int
    wins: int
    losses: int
    breakevens: int
    gross_profit: float
    gross_loss: float
    net_pnl: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    expectancy_per_trade: float
    profit_factor: float
    longest_win_streak: int
    longest_loss_streak: int
    max_drawdown_abs: float
    max_drawdown_pct: float


@dataclass(slots=True)
class GroupedMetricSnapshot:
    group_key: str
    metrics: MetricSnapshot


@dataclass(slots=True)
class TradeContextRecord:
    trade: TradeJournalRecord
    session_label: SessionLabel | None


@dataclass(slots=True)
class SystemEventRecord:
    event_id: str
    occurred_at_utc: datetime
    severity: str
    component: str
    event_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
