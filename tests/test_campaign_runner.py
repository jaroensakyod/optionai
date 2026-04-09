from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from src.bot.bot_runner import BotRunResult
from src.bot.campaign_runner import CampaignPlan, MultiAssetCampaignRunner
from src.bot.cli import _validate_args
from src.bot.iqoption_adapter import IQOptionAdapterError
from src.bot.models import InstrumentType, TradeDirection, TradeJournalRecord, TradeResult


class FakeRunner:
    def __init__(self, results: list[BotRunResult]):
        self._results = list(results)
        self.plans = []

    def run_once(self, plan, *, now_utc=None):
        self.plans.append(plan)
        return self._results.pop(0)

    @property
    def broker_adapter(self):
        return object()


class FakePoller:
    def __init__(self, closed_trades: dict[str, TradeJournalRecord]):
        self.closed_trades = closed_trades
        self.calls: list[str] = []

    def poll_trade_result(self, trade_id: str):
        self.calls.append(trade_id)
        return self.closed_trades[trade_id]


class ErroringRunner(FakeRunner):
    def __init__(self, mapping):
        self.mapping = mapping
        self.plans = []

    def run_once(self, plan, *, now_utc=None):
        self.plans.append(plan)
        value = self.mapping[plan.asset].pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_multi_asset_campaign_runner_rotates_assets_and_emits_checkpoints() -> None:
    runner = FakeRunner(
        [
            BotRunResult(status="skipped", reason="no_signal"),
            BotRunResult(status="submitted", trade_id="trade-1"),
            BotRunResult(status="submitted", trade_id="trade-2"),
            BotRunResult(status="skipped", reason="no_signal"),
            BotRunResult(status="submitted", trade_id="trade-3"),
        ]
    )
    poller = FakePoller(
        {
            "trade-1": _closed_trade("trade-1", "GBPUSD-OTC", TradeResult.WIN, 0.8),
            "trade-2": _closed_trade("trade-2", "EURUSD-OTC", TradeResult.LOSS, -1.0),
            "trade-3": _closed_trade("trade-3", "EURUSD-OTC", TradeResult.BREAKEVEN, 0.0),
        }
    )
    sleep_calls: list[float] = []
    campaign_runner = MultiAssetCampaignRunner(runner, trade_result_poller=poller, sleep_fn=lambda value: sleep_calls.append(value))

    result = campaign_runner.run(
        CampaignPlan(
            strategy_version_id="binary-batch-v1",
            assets=("EURUSD-OTC", "GBPUSD-OTC"),
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
            target_closed_trades=3,
            checkpoint_trades=2,
        ),
        poll_interval_sec=5.0,
    )

    assert result.status == "completed"
    assert result.closed_trades == 3
    assert result.last_trade_id == "trade-3"
    assert [plan.asset for plan in runner.plans] == [
        "EURUSD-OTC",
        "GBPUSD-OTC",
        "EURUSD-OTC",
        "GBPUSD-OTC",
        "EURUSD-OTC",
    ]
    assert [plan.strategy_version_id for plan in runner.plans] == [
        "binary-batch-v1-t01",
        "binary-batch-v1-t01",
        "binary-batch-v1-t01",
        "binary-batch-v1-t02",
        "binary-batch-v1-t02",
    ]
    assert all("campaign_id" in plan.tags for plan in runner.plans)
    assert poller.calls == ["trade-1", "trade-2", "trade-3"]
    assert sleep_calls == []

    checkpoint = result.checkpoints[0]
    assert checkpoint.checkpoint_number == 1
    assert checkpoint.closed_trades == 2
    assert checkpoint.tranche_metrics.total_trades == 2
    assert checkpoint.tranche_metrics.wins == 1
    assert checkpoint.tranche_metrics.losses == 1
    assert checkpoint.tranche_metrics.net_pnl == pytest.approx(-0.2)
    assert checkpoint.cumulative_metrics.net_pnl == pytest.approx(-0.2)
    assert [item.group_key for item in checkpoint.tranche_asset_metrics] == ["EURUSD-OTC", "GBPUSD-OTC"]


def test_validate_args_requires_target_for_multiple_assets() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--placeholder")
    args = argparse.Namespace(
        market_data_source="iqoption",
        market_data_csv=None,
        broker="iqoption",
        expiry_sec=60,
        signal_engine="simple-momentum",
        timeframe_sec=60,
        target_closed_trades=0,
        checkpoint_trades=0,
        asset_scan_interval_sec=0.0,
        practice_smoke_test=False,
        practice_order_probe=False,
    )

    with pytest.raises(SystemExit):
        _validate_args(args, ["EURUSD-OTC", "GBPUSD-OTC"], parser)


def test_campaign_runner_disables_assets_with_unavailable_payout() -> None:
    runner = ErroringRunner(
        {
            "USDJPY-OTC": [IQOptionAdapterError("Payout unavailable for asset: USDJPY-OTC")],
            "EURUSD-OTC": [BotRunResult(status="submitted", trade_id="trade-1")],
        }
    )
    poller = FakePoller({"trade-1": _closed_trade("trade-1", "EURUSD-OTC", TradeResult.WIN, 0.85)})
    campaign_runner = MultiAssetCampaignRunner(runner, trade_result_poller=poller)

    result = campaign_runner.run(
        CampaignPlan(
            strategy_version_id="binary-batch-v1",
            assets=("USDJPY-OTC", "EURUSD-OTC"),
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
            target_closed_trades=1,
        ),
        poll_interval_sec=0.0,
    )

    assert result.status == "completed"
    assert result.closed_trades == 1
    assert [plan.asset for plan in runner.plans] == ["USDJPY-OTC", "EURUSD-OTC"]


def _closed_trade(trade_id: str, asset: str, result: TradeResult, profit_loss_abs: float) -> TradeJournalRecord:
    opened_at = datetime(2026, 4, 9, 12, 0, tzinfo=UTC)
    return TradeJournalRecord(
        trade_id=trade_id,
        signal_id=f"signal-{trade_id}",
        strategy_version_id="binary-batch-v1",
        opened_at_utc=opened_at,
        closed_at_utc=opened_at,
        asset=asset,
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        amount=1.0,
        expiry_sec=60,
        account_mode="PRACTICE",
        result=result,
        profit_loss_abs=profit_loss_abs,
    )