from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Callable
from uuid import uuid4

from .bot_runner import BotRunner, RunnerPlan
from .config import AppConfig
from .duplicate_guard import DuplicateSignalGuard
from .iqoption_adapter import IQOptionAdapter
from .iqoption_market_data import IQOptionMarketDataProvider
from .journal_service import JournalService
from .models import InstrumentType
from .runtime_logging import RuntimeEventLogger
from .safety import StaleMarketDataGuard
from .signal_engine import SimpleMomentumSignalEngine
from .trade_journal import TradeJournalRepository


@dataclass(frozen=True, slots=True)
class SessionStopTargets:
    mode: str
    profit_target: float
    loss_limit: float


@dataclass(frozen=True, slots=True)
class SessionRunConfig:
    assets: tuple[str, ...]
    batch_size: int
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
            signal_engine=SimpleMomentumSignalEngine(),
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
            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status=None, baseline_balance=baseline_balance, status="running", last_reason=None, last_trade_id=None, target_mode=run_config.stop_targets.mode))

            while not self._stop_event.is_set():
                for asset_batch in _chunk_assets(run_config.assets, run_config.batch_size):
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
                        on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(asset,), current_asset=asset, last_run_status=result.status, baseline_balance=baseline_balance, status="running", last_reason=result.reason, last_trade_id=result.trade_id, target_mode=run_config.stop_targets.mode))

                    for asset, result in batch_results:
                        if result.trade_id is None:
                            continue
                        while not self._stop_event.is_set():
                            closed_trade = broker_adapter.poll_trade_result(result.trade_id)
                            if closed_trade is not None:
                                break
                            time.sleep(run_config.poll_interval_sec)

                        threshold_reason = check_stop_threshold(repository=repository, strategy_version_id=session_id, baseline_balance=baseline_balance, targets=run_config.stop_targets)
                        if threshold_reason is not None:
                            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(asset,), current_asset=asset, last_run_status=result.status, baseline_balance=baseline_balance, status="stopped", last_reason=threshold_reason, last_trade_id=result.trade_id, target_mode=run_config.stop_targets.mode))
                            return

                    if batch_results:
                        last_asset, last_result = batch_results[-1]
                        threshold_reason = check_stop_threshold(repository=repository, strategy_version_id=session_id, baseline_balance=baseline_balance, targets=run_config.stop_targets)
                        if threshold_reason is not None:
                            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(last_asset,), current_asset=last_asset, last_run_status=last_result.status, baseline_balance=baseline_balance, status="stopped", last_reason=threshold_reason, last_trade_id=last_result.trade_id, target_mode=run_config.stop_targets.mode))
                            return

                    time.sleep(run_config.poll_interval_sec)

            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status="stopped", baseline_balance=baseline_balance, status="stopped", last_reason="manual_stop", last_trade_id=None, target_mode=run_config.stop_targets.mode))
        except Exception as exc:
            on_update(build_session_snapshot(repository=repository, strategy_version_id=session_id, selected_assets=run_config.assets, current_assets=(), current_asset=None, last_run_status="error", baseline_balance=baseline_balance, status="error", last_reason=type(exc).__name__, last_trade_id=None, target_mode=run_config.stop_targets.mode))
        finally:
            repository.close()


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
    normalized_batch_size = max(batch_size, 1)
    return tuple(tuple(assets[index : index + normalized_batch_size]) for index in range(0, len(assets), normalized_batch_size))