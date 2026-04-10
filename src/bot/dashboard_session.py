from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
from pathlib import Path
import threading
import time
from typing import Callable
from uuid import uuid4

from .bot_runner import BotRunner, RunnerPlan
from .config import AppConfig
from .duplicate_guard import DuplicateSignalGuard
from .iqoption_adapter import IQOptionAdapter, IQOptionAdapterError
from .iqoption_market_data import IQOptionMarketDataProvider
from .journal_service import JournalService
from .models import InstrumentType, TradeResult
from .runtime_logging import RuntimeEventLogger
from .safety import StaleMarketDataGuard
from .signal_engine import build_composite_signal_engine, normalize_strategy_profiles
from .trade_journal import TradeJournalRepository


_STALE_TRADE_GRACE_SEC = 120
_MAX_ABNORMAL_OPEN_TRADE_SEC = 180
_TRADE_RESULT_GRACE_SEC = 15


@dataclass(frozen=True, slots=True)
class SessionStopTargets:
    mode: str
    profit_target: float
    loss_limit: float


@dataclass(frozen=True, slots=True)
class SessionRunConfig:
    assets: tuple[str, ...]
    batch_size: int
    strategy_profiles: tuple[str, ...]
    stake_amount: float
    timeframe_sec: int
    expiry_sec: int
    poll_interval_sec: float
    stop_targets: SessionStopTargets


@dataclass(frozen=True, slots=True)
class SessionStateSnapshot:
    session_id: str
    status: str
    selected_assets: tuple[str, ...]
    current_assets: tuple[str, ...]
    current_asset: str | None
    last_run_status: str | None
    closed_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    net_pnl: float
    progress_value: float
    progress_label: str
    last_reason: str | None = None
    last_trade_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    inspected_open_trades: int
    reconciled_from_broker: int
    closed_as_expired_unknown: int
    poll_failures: int


@dataclass(frozen=True, slots=True)
class ForceCloseSummary:
    closed_count: int


@dataclass(frozen=True, slots=True)
class PendingTradeResolution:
    asset: str
    trade_id: str
    status: str
    reason: str | None


class DashboardSessionController:
    def __init__(self, config: AppConfig, root_dir: Path):
        self._config = config
        self._root_dir = root_dir
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def start(self, run_config: SessionRunConfig, *, on_update: Callable[[SessionStateSnapshot], None]) -> str:
        if self.is_running:
            raise RuntimeError("A dashboard session is already running.")
        if not run_config.assets:
            raise ValueError("At least one asset must be selected.")
        self._stop_event.clear()
        session_id = f"desktop-{uuid4().hex[:10]}"
        self._worker = threading.Thread(
            target=self._run_session,
            name=f"dashboard-session-{session_id}",
            args=(session_id, run_config, on_update),
            daemon=True,
        )
        self._worker.start()
        return session_id

    def stop(self) -> None:
        self._stop_event.set()

    def reconcile_stale_trades(self) -> ReconcileSummary:
        repository = TradeJournalRepository.from_paths(self._root_dir / "data" / "trades.db", self._root_dir / "sql" / "001_initial_schema.sql")
        journal_service = JournalService(repository)
        broker_adapter = IQOptionAdapter.from_environment(self._config, repository, journal_service)
        event_logger = RuntimeEventLogger(repository, self._config.runtime_log_dir, component="desktop_session")
        try:
            broker_adapter.connect()
            return reconcile_open_practice_trades(
                repository=repository,
                journal_service=journal_service,
                broker_adapter=broker_adapter,
                event_logger=event_logger,
            )
        finally:
            repository.close()

    def force_close_open_trades(self, trade_ids: tuple[str, ...] | None = None) -> ForceCloseSummary:
        repository = TradeJournalRepository.from_paths(self._root_dir / "data" / "trades.db", self._root_dir / "sql" / "001_initial_schema.sql")
        journal_service = JournalService(repository)
        event_logger = RuntimeEventLogger(repository, self._config.runtime_log_dir, component="desktop_session")
        try:
            return force_close_open_practice_trades(
                repository=repository,
                journal_service=journal_service,
                event_logger=event_logger,
                trade_ids=trade_ids,
            )
        finally:
            repository.close()

    def _run_session(
        self,
        session_id: str,
        run_config: SessionRunConfig,
        on_update: Callable[[SessionStateSnapshot], None],
    ) -> None:
        repository = TradeJournalRepository.from_paths(self._root_dir / "data" / "trades.db", self._root_dir / "sql" / "001_initial_schema.sql")
        journal_service = JournalService(repository)
        market_data_provider = IQOptionMarketDataProvider.from_environment(self._config)
        broker_adapter = IQOptionAdapter.from_environment(self._config, repository, journal_service)
        event_logger = RuntimeEventLogger(repository, self._config.runtime_log_dir, component="desktop_session")
        duplicate_signal_guard = DuplicateSignalGuard(repository, window_sec=max(int(run_config.poll_interval_sec), 1))
        runner = BotRunner(
            config=self._config,
            repository=repository,
            journal_service=journal_service,
            market_data_provider=market_data_provider,
            signal_engine=build_composite_signal_engine(run_config.strategy_profiles),
            broker_adapter=broker_adapter,
            stale_data_guard=StaleMarketDataGuard(max_data_age_sec=max(run_config.timeframe_sec * 3, 180)),
            duplicate_signal_guard=duplicate_signal_guard,
            event_logger=event_logger,
        )

        baseline_balance = 0.0
        try:
            market_data_provider.connect()
            broker_adapter.connect()
            baseline_balance = broker_adapter.get_balance()
            effective_batch_size = _resolve_effective_batch_size(
                batch_size=run_config.batch_size,
                poll_interval_sec=run_config.poll_interval_sec,
            )
            reconcile_open_practice_trades(
                repository=repository,
                journal_service=journal_service,
                broker_adapter=broker_adapter,
                event_logger=event_logger,
            )
            pending_trades: dict[str, str] = {}
            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status=None, baseline_balance=baseline_balance, status="running", last_reason=None, last_trade_id=None, target_mode=run_config.stop_targets.mode))

            while not self._stop_event.is_set():
                _sleep_until_next_scan_window(
                    stop_event=self._stop_event,
                    timeframe_sec=run_config.timeframe_sec,
                    poll_interval_sec=run_config.poll_interval_sec,
                )
                if self._stop_event.is_set():
                    break

                resolved_trades = _poll_pending_session_trades(
                    repository=repository,
                    journal_service=journal_service,
                    broker_adapter=broker_adapter,
                    event_logger=event_logger,
                    pending_trades=pending_trades,
                )
                for resolved_trade in resolved_trades:
                    on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(resolved_trade.asset,), current_asset=resolved_trade.asset, last_run_status=resolved_trade.status, baseline_balance=baseline_balance, status="running", last_reason=resolved_trade.reason, last_trade_id=resolved_trade.trade_id, target_mode=run_config.stop_targets.mode))
                    threshold_reason = check_stop_threshold(repository=repository, strategy_version_id=session_id, baseline_balance=baseline_balance, targets=run_config.stop_targets)
                    if threshold_reason is not None:
                        on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(resolved_trade.asset,), current_asset=resolved_trade.asset, last_run_status=resolved_trade.status, baseline_balance=baseline_balance, status="stopped", last_reason=threshold_reason, last_trade_id=resolved_trade.trade_id, target_mode=run_config.stop_targets.mode))
                        return

                for asset_batch in _chunk_assets(run_config.assets, effective_batch_size):
                    if self._stop_event.is_set():
                        break

                    batch_label = " + ".join(asset_batch)
                    on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=asset_batch, current_asset=batch_label, last_run_status="checking", baseline_balance=baseline_balance, status="running", last_reason="checking_asset_batch", last_trade_id=None, target_mode=run_config.stop_targets.mode))

                    batch_results: list[tuple[str, object]] = []
                    for asset in asset_batch:
                        if self._stop_event.is_set():
                            break
                        result = runner.run_once(
                            RunnerPlan(
                                strategy_version_id=session_id,
                                asset=asset,
                                instrument_type=InstrumentType.BINARY,
                                timeframe_sec=run_config.timeframe_sec,
                                stake_amount=run_config.stake_amount,
                                expiry_sec=run_config.expiry_sec,
                                tags={"desktop_session": session_id},
                            )
                        )
                        batch_results.append((asset, result))
                        if result.trade_id is not None:
                            pending_trades[result.trade_id] = asset
                        on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(asset,), current_asset=asset, last_run_status=result.status, baseline_balance=baseline_balance, status="running", last_reason=result.reason, last_trade_id=result.trade_id, target_mode=run_config.stop_targets.mode))

                    if batch_results:
                        last_asset, last_result = batch_results[-1]
                        threshold_reason = check_stop_threshold(repository=repository, strategy_version_id=session_id, baseline_balance=baseline_balance, targets=run_config.stop_targets)
                        if threshold_reason is not None:
                            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(last_asset,), current_asset=last_asset, last_run_status=last_result.status, baseline_balance=baseline_balance, status="stopped", last_reason=threshold_reason, last_trade_id=last_result.trade_id, target_mode=run_config.stop_targets.mode))
                            return

            resolved_trades = _poll_pending_session_trades(
                repository=repository,
                journal_service=journal_service,
                broker_adapter=broker_adapter,
                event_logger=event_logger,
                pending_trades=pending_trades,
            )
            for resolved_trade in resolved_trades:
                on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(resolved_trade.asset,), current_asset=resolved_trade.asset, last_run_status=resolved_trade.status, baseline_balance=baseline_balance, status="running", last_reason=resolved_trade.reason, last_trade_id=resolved_trade.trade_id, target_mode=run_config.stop_targets.mode))
            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status="stopped", baseline_balance=baseline_balance, status="stopped", last_reason="manual_stop", last_trade_id=None, target_mode=run_config.stop_targets.mode))
        except Exception as exc:
            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status="error", baseline_balance=baseline_balance, status="error", last_reason=type(exc).__name__, last_trade_id=None, target_mode=run_config.stop_targets.mode))
        finally:
            repository.close()


def reconcile_open_practice_trades(
    *,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    broker_adapter: IQOptionAdapter,
    event_logger: RuntimeEventLogger,
    now_utc: datetime | None = None,
) -> ReconcileSummary:
    current_time = now_utc or datetime.now(UTC)
    inspected_open_trades = 0
    reconciled_from_broker = 0
    closed_as_expired_unknown = 0
    poll_failures = 0
    for trade in repository.list_trades(account_mode="PRACTICE"):
        if trade.closed_at_utc is not None:
            continue
        inspected_open_trades += 1

        age_sec = max((current_time - trade.opened_at_utc).total_seconds(), 0.0)
        stale_after_sec = min(max(trade.expiry_sec, 0) + _TRADE_RESULT_GRACE_SEC, _MAX_ABNORMAL_OPEN_TRADE_SEC)
        if age_sec < stale_after_sec:
            continue

        try:
            closed_trade = broker_adapter.poll_trade_result(trade.trade_id)
        except (IQOptionAdapterError, TypeError, ValueError) as exc:
            poll_failures += 1
            event_logger.log(
                severity="warning",
                event_type="stale_trade_poll_failed",
                message="Failed to poll an expired open trade during session reconciliation.",
                details={"trade_id": trade.trade_id, "asset": trade.asset, "reason": str(exc)},
            )
            closed_trade = None

        if closed_trade is not None:
            reconciled_from_broker += 1
            event_logger.log(
                severity="info",
                event_type="stale_trade_reconciled",
                message="Resolved an expired open trade from broker state during session reconciliation.",
                details={"trade_id": trade.trade_id, "asset": trade.asset, "result": closed_trade.result.value if closed_trade.result is not None else None},
            )
            continue

        journal_service.close_trade(
            trade_id=trade.trade_id,
            result=TradeResult.EXPIRED_UNKNOWN,
            profit_loss_abs=None,
            profit_loss_pct_risk=None,
            close_reason="stale_reconciliation",
            error_code="STALE_OPEN_TRADE",
            error_message="Trade remained open in the local journal past expiry and was closed during session reconciliation.",
        )
        closed_as_expired_unknown += 1
        event_logger.log(
            severity="warning",
            event_type="stale_trade_closed",
            message="Closed an expired open trade locally during session reconciliation.",
            details={"trade_id": trade.trade_id, "asset": trade.asset, "age_sec": age_sec},
        )
    return ReconcileSummary(
        inspected_open_trades=inspected_open_trades,
        reconciled_from_broker=reconciled_from_broker,
        closed_as_expired_unknown=closed_as_expired_unknown,
        poll_failures=poll_failures,
    )


def force_close_open_practice_trades(
    *,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    event_logger: RuntimeEventLogger,
    trade_ids: tuple[str, ...] | None = None,
    close_reason: str = "forced_dashboard_close",
    error_code: str = "FORCE_CLOSED",
    error_message: str = "Trade was force-closed from the desktop dashboard because no real broker order remained open.",
    event_type: str = "trade_force_closed",
    event_message: str = "Force-closed an open practice trade from the desktop dashboard.",
) -> ForceCloseSummary:
    requested_trade_ids = set(trade_ids or ())
    closed_count = 0
    for trade in repository.list_trades(account_mode="PRACTICE"):
        if trade.closed_at_utc is not None:
            continue
        if requested_trade_ids and trade.trade_id not in requested_trade_ids:
            continue
        journal_service.close_trade(
            trade_id=trade.trade_id,
            result=TradeResult.CANCELLED,
            profit_loss_abs=None,
            profit_loss_pct_risk=None,
            close_reason=close_reason,
            error_code=error_code,
            error_message=error_message,
        )
        closed_count += 1
        event_logger.log(
            severity="warning",
            event_type=event_type,
            message=event_message,
            details={"trade_id": trade.trade_id, "asset": trade.asset},
        )
    return ForceCloseSummary(closed_count=closed_count)


def _force_close_abnormally_open_trade(
    *,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    event_logger: RuntimeEventLogger,
    trade_id: str,
    now_utc: datetime | None = None,
) -> bool:
    trade = repository.get_trade(trade_id)
    if trade is None or trade.closed_at_utc is not None:
        return False
    current_time = now_utc or datetime.now(UTC)
    age_sec = max((current_time - trade.opened_at_utc).total_seconds(), 0.0)
    if age_sec < _MAX_ABNORMAL_OPEN_TRADE_SEC:
        return False
    summary = force_close_open_practice_trades(
        repository=repository,
        journal_service=journal_service,
        event_logger=event_logger,
        trade_ids=(trade_id,),
        close_reason="abnormal_open_timeout",
        error_code="OPEN_TIMEOUT",
        error_message="Trade remained open longer than three minutes and was closed locally during the dashboard session.",
        event_type="trade_auto_closed_timeout",
        event_message="Auto-closed a practice trade that remained open too long during the dashboard session.",
    )
    return summary.closed_count > 0


def _force_close_expired_trade(
    *,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    event_logger: RuntimeEventLogger,
    trade_id: str,
    now_utc: datetime | None = None,
    error_message: str | None = None,
) -> bool:
    trade = repository.get_trade(trade_id)
    if trade is None or trade.closed_at_utc is not None:
        return False
    current_time = now_utc or datetime.now(UTC)
    age_sec = max((current_time - trade.opened_at_utc).total_seconds(), 0.0)
    expiry_timeout_sec = max(trade.expiry_sec, 0) + _TRADE_RESULT_GRACE_SEC
    if age_sec < expiry_timeout_sec:
        return False
    summary = force_close_open_practice_trades(
        repository=repository,
        journal_service=journal_service,
        event_logger=event_logger,
        trade_ids=(trade_id,),
        close_reason="expiry_timeout",
        error_code="BROKER_RESULT_TIMEOUT",
        error_message=(
            error_message
            or "Trade reached expiry but no broker close result arrived in time during the dashboard session."
        ),
        event_type="trade_auto_closed_expiry_timeout",
        event_message="Auto-closed a practice trade after expiry because no broker close result arrived in time.",
    )
    return summary.closed_count > 0


def _poll_pending_session_trades(
    *,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    broker_adapter: IQOptionAdapter,
    event_logger: RuntimeEventLogger,
    pending_trades: dict[str, str],
) -> list[PendingTradeResolution]:
    resolved_trades: list[PendingTradeResolution] = []
    for trade_id, asset in tuple(pending_trades.items()):
        try:
            closed_trade = broker_adapter.poll_trade_result(trade_id)
        except (IQOptionAdapterError, TypeError, ValueError) as exc:
            event_logger.log(
                severity="warning",
                event_type="trade_result_poll_failed",
                message="Failed to poll an open trade during the dashboard session.",
                details={"trade_id": trade_id, "asset": asset, "reason": str(exc)},
            )
            if _force_close_expired_trade(
                repository=repository,
                journal_service=journal_service,
                event_logger=event_logger,
                trade_id=trade_id,
                error_message=(
                    "Trade reached expiry but broker polling kept failing during the dashboard session. "
                    f"Last poll error: {exc}"
                ),
            ):
                pending_trades.pop(trade_id, None)
                resolved_trades.append(PendingTradeResolution(asset=asset, trade_id=trade_id, status="closed", reason="BROKER_RESULT_TIMEOUT"))
                continue
            if _force_close_abnormally_open_trade(
                repository=repository,
                journal_service=journal_service,
                event_logger=event_logger,
                trade_id=trade_id,
            ):
                pending_trades.pop(trade_id, None)
                resolved_trades.append(PendingTradeResolution(asset=asset, trade_id=trade_id, status="closed", reason="OPEN_TIMEOUT"))
            continue

        if closed_trade is not None:
            pending_trades.pop(trade_id, None)
            resolved_trades.append(
                PendingTradeResolution(
                    asset=asset,
                    trade_id=trade_id,
                    status="closed",
                    reason=closed_trade.result.value if closed_trade.result is not None else closed_trade.close_reason,
                )
            )
            continue

        if _force_close_expired_trade(
            repository=repository,
            journal_service=journal_service,
            event_logger=event_logger,
            trade_id=trade_id,
        ):
            pending_trades.pop(trade_id, None)
            resolved_trades.append(PendingTradeResolution(asset=asset, trade_id=trade_id, status="closed", reason="BROKER_RESULT_TIMEOUT"))
            continue

        if _force_close_abnormally_open_trade(
            repository=repository,
            journal_service=journal_service,
            event_logger=event_logger,
            trade_id=trade_id,
        ):
            pending_trades.pop(trade_id, None)
            resolved_trades.append(PendingTradeResolution(asset=asset, trade_id=trade_id, status="closed", reason="OPEN_TIMEOUT"))

    return resolved_trades


def check_stop_threshold(
    *,
    repository: TradeJournalRepository,
    strategy_version_id: str,
    baseline_balance: float,
    targets: SessionStopTargets,
) -> str | None:
    trades = [
        trade
        for trade in repository.list_trades(account_mode="PRACTICE")
        if trade.strategy_version_id == strategy_version_id and trade.closed_at_utc is not None and trade.profit_loss_abs is not None
    ]
    net_pnl = sum(trade.profit_loss_abs or 0.0 for trade in trades)
    metric_value = net_pnl if targets.mode == "$" or baseline_balance == 0 else (net_pnl / baseline_balance) * 100.0
    if targets.profit_target > 0 and metric_value >= targets.profit_target:
        return "profit_target_reached"
    if targets.loss_limit > 0 and metric_value <= (-targets.loss_limit):
        return "loss_limit_reached"
    return None


def build_session_snapshot(
    *,
    repository: TradeJournalRepository,
    strategy_version_id: str,
    selected_assets: tuple[str, ...],
    current_assets: tuple[str, ...],
    current_asset: str | None,
    last_run_status: str | None,
    baseline_balance: float,
    status: str,
    last_reason: str | None,
    last_trade_id: str | None,
    target_mode: str,
) -> SessionStateSnapshot:
    trades = [
        trade
        for trade in repository.list_trades(account_mode="PRACTICE")
        if trade.strategy_version_id == strategy_version_id and trade.closed_at_utc is not None and trade.profit_loss_abs is not None
    ]
    wins = sum(1 for trade in trades if trade.result is not None and trade.result.value == "WIN")
    losses = sum(1 for trade in trades if trade.result is not None and trade.result.value == "LOSS")
    closed_trades = len(trades)
    net_pnl = sum(trade.profit_loss_abs or 0.0 for trade in trades)
    win_rate_pct = 0.0 if closed_trades == 0 else (wins / closed_trades) * 100.0
    progress_value = net_pnl if target_mode == "$" or baseline_balance == 0 else (net_pnl / baseline_balance) * 100.0
    progress_label = "$" if target_mode == "$" else "%"
    return SessionStateSnapshot(
        session_id=strategy_version_id,
        status=status,
        selected_assets=selected_assets,
        current_assets=current_assets,
        current_asset=current_asset,
        last_run_status=last_run_status,
        closed_trades=closed_trades,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate_pct,
        net_pnl=net_pnl,
        progress_value=progress_value,
        progress_label=progress_label,
        last_reason=last_reason,
        last_trade_id=last_trade_id,
    )


def _chunk_assets(assets: tuple[str, ...], batch_size: int) -> tuple[tuple[str, ...], ...]:
    if batch_size <= 0:
        return (assets,) if assets else ()
    normalized_batch_size = max(batch_size, 1)
    return tuple(tuple(assets[index : index + normalized_batch_size]) for index in range(0, len(assets), normalized_batch_size))


def _resolve_effective_batch_size(*, batch_size: int, poll_interval_sec: float) -> int:
    return batch_size


def _sleep_until_next_scan_window(
    *,
    stop_event: threading.Event,
    timeframe_sec: int,
    poll_interval_sec: float,
    now_utc: datetime | None = None,
) -> None:
    delay_sec = _seconds_until_next_scan_window(
        now_utc=now_utc or datetime.now(UTC),
        timeframe_sec=timeframe_sec,
        poll_interval_sec=poll_interval_sec,
    )
    if delay_sec <= 0:
        return
    stop_event.wait(delay_sec)


def _seconds_until_next_scan_window(*, now_utc: datetime, timeframe_sec: int, poll_interval_sec: float) -> float:
    normalized_timeframe_sec = max(int(timeframe_sec), 1)
    raw_poll_sec = float(poll_interval_sec)
    normalized_poll_sec = max(raw_poll_sec, 0.0) % normalized_timeframe_sec
    epoch_sec = now_utc.timestamp()
    timeframe_boundary_sec = math.floor(epoch_sec / normalized_timeframe_sec) * normalized_timeframe_sec
    target_time_utc = datetime.fromtimestamp(timeframe_boundary_sec, tz=UTC) + timedelta(seconds=normalized_poll_sec)
    if epoch_sec > target_time_utc.timestamp():
        target_time_utc += timedelta(seconds=normalized_timeframe_sec)
    return max((target_time_utc - now_utc).total_seconds(), 0.0)