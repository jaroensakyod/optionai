from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from .config import AppConfig
from .duplicate_guard import DuplicateSignalGuard
from .iqoption_adapter import IQOptionOrderUnavailableError
from .journal_service import JournalService
from .market_data import MarketDataProvider
from .models import InstrumentType, StrategyVersion, TradeJournalRecord
from .runtime_logging import RuntimeEventLogger
from .safety import KillSwitch, StaleMarketDataGuard
from .signal_engine import SignalEngine
from .trade_journal import TradeJournalRepository


_BINARY_ENTRY_WINDOW_SEC = 2


class BrokerSubmitter(Protocol):
    def submit_order(
        self,
        *,
        signal_event,
        strategy_version_id: str,
        tags: dict[str, str] | None = None,
    ) -> TradeJournalRecord: ...


@dataclass(frozen=True, slots=True)
class RunnerPlan:
    strategy_version_id: str
    asset: str
    instrument_type: InstrumentType
    timeframe_sec: int
    stake_amount: float
    expiry_sec: int
    created_by: str = "bot-runner"
    approval_status: str = "approved"
    code_ref: str | None = None
    change_reason: str | None = "runner-bootstrap"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BotRunResult:
    status: str
    reason: str | None = None
    signal_id: str | None = None
    trade_id: str | None = None


class BotRunner:
    def __init__(
        self,
        config: AppConfig,
        repository: TradeJournalRepository,
        journal_service: JournalService,
        market_data_provider: MarketDataProvider,
        signal_engine: SignalEngine,
        broker_adapter: BrokerSubmitter,
        stale_data_guard: StaleMarketDataGuard | None = None,
        kill_switch: KillSwitch | None = None,
        duplicate_signal_guard: DuplicateSignalGuard | None = None,
        event_logger: RuntimeEventLogger | None = None,
    ):
        self._config = config
        self._repository = repository
        self._journal_service = journal_service
        self._market_data_provider = market_data_provider
        self._signal_engine = signal_engine
        self._broker_adapter = broker_adapter
        self._stale_data_guard = stale_data_guard
        self._kill_switch = kill_switch
        self._duplicate_signal_guard = duplicate_signal_guard
        self._event_logger = event_logger

    def run_once(self, plan: RunnerPlan, *, now_utc: datetime | None = None) -> BotRunResult:
        current_time = now_utc or datetime.now(UTC)

        if self._kill_switch is not None and self._kill_switch.is_active:
            self._log_event("warning", "run_stopped", "Runner stopped by kill switch.", {"reason": self._kill_switch.reason})
            return BotRunResult(status="stopped", reason=self._kill_switch.reason or "kill_switch_active")

        limit_reason = self._validate_limits(plan, current_time.date())
        if limit_reason is not None:
            self._log_event("warning", "run_skipped", "Runner skipped due to limits.", {"reason": limit_reason})
            return BotRunResult(status="skipped", reason=limit_reason)

        timing_reason = self._validate_entry_timing(plan, current_time)
        if timing_reason is not None:
            self._log_event(
                "info",
                "entry_window_wait",
                "Runner skipped while waiting for the binary entry window.",
                {"reason": timing_reason, "asset": plan.asset},
            )
            return BotRunResult(status="skipped", reason=timing_reason)

        candles = self._market_data_provider.get_recent_candles(
            asset=plan.asset,
            instrument_type=plan.instrument_type,
            timeframe_sec=plan.timeframe_sec,
            limit=self._signal_engine.required_candles,
        )
        if self._stale_data_guard is not None:
            stale_reason = self._stale_data_guard.check(candles, current_time)
            if stale_reason is not None:
                self._log_event("warning", "stale_market_data", "Runner skipped due to stale market data.", {"reason": stale_reason})
                return BotRunResult(status="skipped", reason=stale_reason)
        signal_event = self._signal_engine.build_signal(
            strategy_version_id=plan.strategy_version_id,
            asset=plan.asset,
            instrument_type=plan.instrument_type,
            timeframe_sec=plan.timeframe_sec,
            stake_amount=plan.stake_amount,
            expiry_sec=plan.expiry_sec,
            candles=candles,
            signal_time_utc=current_time,
        )
        if signal_event is None:
            self._log_event("info", "no_signal", "Runner found no signal.", {"asset": plan.asset})
            return BotRunResult(status="skipped", reason="no_signal")
        if signal_event.is_filtered_out:
            filter_reason = signal_event.filter_reason or "signal_filtered"
            self._log_event(
                "info",
                "signal_filtered",
                "Runner skipped a filtered signal.",
                {"asset": plan.asset, "reason": filter_reason},
            )
            return BotRunResult(status="skipped", reason=filter_reason)

        if self._duplicate_signal_guard is not None:
            duplicate_check = self._duplicate_signal_guard.check(
                signal_event=signal_event,
                account_mode=self._config.app_mode,
                now_utc=current_time,
            )
            if duplicate_check.prevented:
                self._log_event(
                    "warning",
                    "duplicate_signal_prevented",
                    "Runner prevented a duplicate signal.",
                    {
                        "matched_trade_id": duplicate_check.matched_trade_id,
                        "fingerprint": duplicate_check.fingerprint,
                    },
                )
                return BotRunResult(status="skipped", reason="duplicate_signal")
            duplicate_fingerprint = duplicate_check.fingerprint
        else:
            duplicate_fingerprint = None

        self._ensure_strategy_version(plan, current_time)
        tags = {"runner": "bot_runner", **self._strategy_trade_tags(signal_event), **plan.tags}
        if duplicate_fingerprint is not None:
            tags["signal_fingerprint"] = duplicate_fingerprint
        try:
            trade = self._broker_adapter.submit_order(
                signal_event=signal_event,
                strategy_version_id=plan.strategy_version_id,
                tags=tags,
            )
        except IQOptionOrderUnavailableError as exc:
            self._log_event(
                "info",
                "market_unavailable",
                "Runner skipped because the broker reported the asset as unavailable for a new order.",
                {"asset": signal_event.asset, "reason": str(exc)},
            )
            return BotRunResult(status="skipped", reason="market_closed_or_unavailable")
        self._log_event(
            "info",
            "trade_submitted",
            "Runner submitted a trade.",
            {"trade_id": trade.trade_id, "signal_id": signal_event.signal_id, "asset": signal_event.asset},
        )
        return BotRunResult(
            status="submitted",
            reason=trade.result.value if trade.result is not None else None,
            signal_id=signal_event.signal_id,
            trade_id=trade.trade_id,
        )

    @property
    def market_data_provider(self) -> MarketDataProvider:
        return self._market_data_provider

    @property
    def broker_adapter(self) -> BrokerSubmitter:
        return self._broker_adapter

    def _log_event(self, severity: str, event_type: str, message: str, details: dict[str, Any]) -> None:
        if self._event_logger is not None:
            self._event_logger.log(severity=severity, event_type=event_type, message=message, details=details)

    def _ensure_strategy_version(self, plan: RunnerPlan, now_utc: datetime) -> None:
        parameters = {
            **self._signal_engine.describe_parameters(),
            "asset": plan.asset,
            "instrument_type": plan.instrument_type.value,
            "timeframe_sec": plan.timeframe_sec,
            "stake_amount": plan.stake_amount,
            "expiry_sec": plan.expiry_sec,
        }
        strategy_version = StrategyVersion(
            strategy_version_id=plan.strategy_version_id,
            created_at_utc=now_utc,
            strategy_name=self._signal_engine.strategy_name,
            parameter_hash=_parameter_hash(parameters),
            parameters=parameters,
            created_by=plan.created_by,
            approval_status=plan.approval_status,
            code_ref=plan.code_ref,
            change_reason=plan.change_reason,
        )
        self._repository.save_strategy_version(strategy_version)

    def _strategy_trade_tags(self, signal_event) -> dict[str, str]:
        indicator_snapshot = getattr(signal_event, "indicator_snapshot", {}) or {}
        contributing_profiles = [str(profile) for profile in indicator_snapshot.get("strategy_profiles", ()) if str(profile)]
        contributing_names = [str(name) for name in indicator_snapshot.get("strategy_names", ()) if str(name)]
        if contributing_profiles:
            tags = {
                "strategy_profile": contributing_profiles[0],
                "strategy_profiles": ",".join(contributing_profiles),
                "strategy_display": " + ".join(contributing_profiles),
            }
            if contributing_names:
                tags["strategy_name"] = contributing_names[0]
                tags["strategy_names"] = ",".join(contributing_names)
            return tags

        trade_tags = getattr(self._signal_engine, "trade_tags", None)
        if callable(trade_tags):
            return {str(key): str(value) for key, value in trade_tags().items()}

        strategy_profile = getattr(self._signal_engine, "strategy_profile", None)
        strategy_name = getattr(self._signal_engine, "strategy_name", None)
        tags: dict[str, str] = {}
        if isinstance(strategy_profile, str) and strategy_profile:
            tags["strategy_profile"] = strategy_profile
            tags["strategy_profiles"] = strategy_profile
            tags["strategy_display"] = strategy_profile
        if isinstance(strategy_name, str) and strategy_name:
            tags["strategy_name"] = strategy_name
            tags["strategy_names"] = strategy_name
        return tags

    def _validate_limits(self, plan: RunnerPlan, today_utc: date) -> str | None:
        limits = self._config.risk_limits
        if plan.stake_amount > limits.max_stake:
            return "max_stake_exceeded"

        if limits.max_open_positions > 0:
            open_positions_for_asset = sum(
                1
                for trade in self._repository.list_trades(account_mode=self._config.app_mode)
                if trade.closed_at_utc is None
                and trade.asset == plan.asset
                and trade.instrument_type == plan.instrument_type
            )
            if open_positions_for_asset >= limits.max_open_positions:
                return "open_position_for_asset_exists"

        if limits.max_daily_loss > 0 and self._realized_daily_pnl(today_utc) <= (-limits.max_daily_loss):
            return "max_daily_loss_reached"
        return None

    def _realized_daily_pnl(self, today_utc: date) -> float:
        realized = 0.0
        for trade in self._repository.list_trades(account_mode=self._config.app_mode):
            if trade.closed_at_utc is None or trade.profit_loss_abs is None:
                continue
            if trade.closed_at_utc.date() != today_utc:
                continue
            realized += trade.profit_loss_abs
        return realized

    @staticmethod
    def _validate_entry_timing(plan: RunnerPlan, current_time: datetime) -> str | None:
        if plan.instrument_type != InstrumentType.BINARY:
            return None
        if plan.expiry_sec % 60 != 0:
            return None
        if current_time.second >= _BINARY_ENTRY_WINDOW_SEC:
            return "awaiting_entry_window"
        return None


def _parameter_hash(parameters: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = json.dumps(parameters, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
