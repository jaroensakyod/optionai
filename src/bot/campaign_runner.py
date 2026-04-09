from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import time
from typing import Callable, Protocol

from .bot_runner import BotRunResult, BotRunner, RunnerPlan
from .iqoption_adapter import IQOptionAdapterError
from .models import GroupedMetricSnapshot, InstrumentType, MetricSnapshot, TradeJournalRecord, TradeResult
from .runtime_logging import RuntimeEventLogger
from .stats_service import build_metric_snapshot


class TradeResultPoller(Protocol):
    def poll_trade_result(self, trade_id: str) -> TradeJournalRecord | None: ...


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    strategy_version_id: str
    assets: tuple[str, ...]
    instrument_type: InstrumentType
    timeframe_sec: int
    stake_amount: float
    expiry_sec: int
    target_closed_trades: int
    checkpoint_trades: int = 0
    asset_scan_interval_sec: float = 0.0
    campaign_id: str | None = None
    created_by: str = "campaign-runner"
    approval_status: str = "approved"
    code_ref: str | None = None
    change_reason: str | None = "campaign-bootstrap"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CampaignCheckpoint:
    checkpoint_number: int
    closed_trades: int
    tranche_metrics: MetricSnapshot
    cumulative_metrics: MetricSnapshot
    tranche_asset_metrics: list[GroupedMetricSnapshot]


@dataclass(frozen=True, slots=True)
class CampaignRunResult:
    status: str
    campaign_id: str
    closed_trades: int
    checkpoints: list[CampaignCheckpoint]
    last_trade_id: str | None = None
    reason: str | None = None


class MultiAssetCampaignRunner:
    def __init__(
        self,
        runner: BotRunner,
        *,
        trade_result_poller: TradeResultPoller | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        event_logger: RuntimeEventLogger | None = None,
    ):
        self._runner = runner
        self._trade_result_poller = trade_result_poller or self._resolve_trade_result_poller(runner)
        self._sleep_fn = sleep_fn or time.sleep
        self._event_logger = event_logger

    def run(self, plan: CampaignPlan, *, poll_interval_sec: float) -> CampaignRunResult:
        if not plan.assets:
            raise ValueError("CampaignPlan requires at least one asset.")
        if plan.target_closed_trades <= 0:
            raise ValueError("CampaignPlan.target_closed_trades must be greater than zero.")
        if plan.checkpoint_trades < 0:
            raise ValueError("CampaignPlan.checkpoint_trades cannot be negative.")
        if plan.checkpoint_trades > 0 and plan.checkpoint_trades > plan.target_closed_trades:
            raise ValueError("CampaignPlan.checkpoint_trades cannot exceed target_closed_trades.")
        if plan.asset_scan_interval_sec < 0:
            raise ValueError("CampaignPlan.asset_scan_interval_sec cannot be negative.")
        if self._trade_result_poller is None:
            raise ValueError("MultiAssetCampaignRunner requires a broker adapter with poll_trade_result support.")

        campaign_id = plan.campaign_id or f"{plan.strategy_version_id}-campaign"
        closed_records: list[TradeJournalRecord] = []
        checkpoints: list[CampaignCheckpoint] = []
        next_asset_index = 0
        active_trade_id: str | None = None
        last_trade_id: str | None = None
        disabled_assets: set[str] = set()

        while len(closed_records) < plan.target_closed_trades:
            active_assets = tuple(asset for asset in plan.assets if asset not in disabled_assets)
            if not active_assets:
                return CampaignRunResult(
                    status="stopped",
                    campaign_id=campaign_id,
                    closed_trades=len(closed_records),
                    checkpoints=checkpoints,
                    last_trade_id=last_trade_id,
                    reason="no_supported_assets",
                )

            if active_trade_id is not None:
                closed_trade = self._trade_result_poller.poll_trade_result(active_trade_id)
                if closed_trade is None:
                    self._sleep_fn(poll_interval_sec)
                    continue
                last_trade_id = closed_trade.trade_id
                active_trade_id = None
                if closed_trade.result in _COUNTED_RESULTS:
                    closed_records.append(closed_trade)
                    checkpoint = self._build_checkpoint(plan, closed_records)
                    if checkpoint is not None:
                        checkpoints.append(checkpoint)
                        self._log_event(
                            "info",
                            "campaign_checkpoint",
                            "Campaign reached a checkpoint.",
                            {
                                "campaign_id": campaign_id,
                                "checkpoint_number": str(checkpoint.checkpoint_number),
                                "closed_trades": str(checkpoint.closed_trades),
                            },
                        )
                continue

            submitted = False
            for asset, asset_index in self._rotated_assets(active_assets, next_asset_index):
                try:
                    attempt_result = self._runner.run_once(self._build_runner_plan(plan, campaign_id, asset, len(closed_records)))
                except IQOptionAdapterError as exc:
                    if "Payout unavailable for asset" in str(exc):
                        disabled_assets.add(asset)
                        next_asset_index = 0 if not active_assets else asset_index % max(1, len(active_assets))
                        self._log_event(
                            "warning",
                            "campaign_asset_disabled",
                            "Campaign disabled an unsupported asset.",
                            {"campaign_id": campaign_id, "asset": asset, "reason": str(exc)},
                        )
                        continue
                    raise
                next_asset_index = (asset_index + 1) % len(active_assets)
                if attempt_result.status == "submitted":
                    active_trade_id = attempt_result.trade_id
                    last_trade_id = attempt_result.trade_id
                    submitted = True
                    break
                if attempt_result.status == "stopped":
                    return CampaignRunResult(
                        status="stopped",
                        campaign_id=campaign_id,
                        closed_trades=len(closed_records),
                        checkpoints=checkpoints,
                        last_trade_id=last_trade_id,
                        reason=attempt_result.reason,
                    )
                if plan.asset_scan_interval_sec > 0:
                    self._sleep_fn(plan.asset_scan_interval_sec)

            if not submitted:
                self._sleep_fn(poll_interval_sec)

        return CampaignRunResult(
            status="completed",
            campaign_id=campaign_id,
            closed_trades=len(closed_records),
            checkpoints=checkpoints,
            last_trade_id=last_trade_id,
        )

    @staticmethod
    def _resolve_trade_result_poller(runner: BotRunner) -> TradeResultPoller | None:
        broker_adapter = runner.broker_adapter
        if hasattr(broker_adapter, "poll_trade_result"):
            return broker_adapter
        return None

    @staticmethod
    def _rotated_assets(assets: tuple[str, ...], start_index: int):
        for offset in range(len(assets)):
            asset_index = (start_index + offset) % len(assets)
            yield assets[asset_index], asset_index

    def _build_runner_plan(self, plan: CampaignPlan, campaign_id: str, asset: str, closed_trades: int) -> RunnerPlan:
        tranche_number = self._tranche_number(closed_trades, plan.checkpoint_trades)
        return RunnerPlan(
            strategy_version_id=self._strategy_version_id(plan.strategy_version_id, tranche_number, plan.checkpoint_trades),
            asset=asset,
            instrument_type=plan.instrument_type,
            timeframe_sec=plan.timeframe_sec,
            stake_amount=plan.stake_amount,
            expiry_sec=plan.expiry_sec,
            created_by=plan.created_by,
            approval_status=plan.approval_status,
            code_ref=plan.code_ref,
            change_reason=plan.change_reason,
            tags={
                **plan.tags,
                "campaign_id": campaign_id,
                "campaign_tranche": str(tranche_number),
                "campaign_target_closed_trades": str(plan.target_closed_trades),
            },
        )

    def _build_checkpoint(
        self,
        plan: CampaignPlan,
        closed_records: list[TradeJournalRecord],
    ) -> CampaignCheckpoint | None:
        if plan.checkpoint_trades <= 0 or len(closed_records) % plan.checkpoint_trades != 0:
            return None

        checkpoint_number = len(closed_records) // plan.checkpoint_trades
        tranche_records = closed_records[-plan.checkpoint_trades :]
        return CampaignCheckpoint(
            checkpoint_number=checkpoint_number,
            closed_trades=len(closed_records),
            tranche_metrics=build_metric_snapshot(tranche_records),
            cumulative_metrics=build_metric_snapshot(closed_records),
            tranche_asset_metrics=self._build_asset_metrics(tranche_records),
        )

    @staticmethod
    def _build_asset_metrics(records: list[TradeJournalRecord]) -> list[GroupedMetricSnapshot]:
        grouped: dict[str, list[TradeJournalRecord]] = defaultdict(list)
        for record in records:
            grouped[record.asset].append(record)
        return [
            GroupedMetricSnapshot(group_key=asset, metrics=build_metric_snapshot(asset_records))
            for asset, asset_records in sorted(grouped.items())
        ]

    @staticmethod
    def _strategy_version_id(base_strategy_version_id: str, tranche_number: int, checkpoint_trades: int) -> str:
        if checkpoint_trades <= 0:
            return base_strategy_version_id
        return f"{base_strategy_version_id}-t{tranche_number:02d}"

    @staticmethod
    def _tranche_number(closed_trades: int, checkpoint_trades: int) -> int:
        if checkpoint_trades <= 0:
            return 1
        return (closed_trades // checkpoint_trades) + 1

    def _log_event(self, severity: str, event_type: str, message: str, details: dict[str, str]) -> None:
        if self._event_logger is not None:
            self._event_logger.log(severity=severity, event_type=event_type, message=message, details=details)


_COUNTED_RESULTS = {TradeResult.WIN, TradeResult.LOSS, TradeResult.BREAKEVEN}