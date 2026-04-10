from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from .bot_runner import BotRunner, RunnerPlan
from .broker_adapter import PracticeBrokerAdapter
from .campaign_runner import CampaignPlan, MultiAssetCampaignRunner
from .config import load_config
from .duplicate_guard import DuplicateSignalGuard
from .env import load_dotenv_file
from .iqoption_adapter import IQOptionAdapter
from .iqoption_market_data import IQOptionMarketDataProvider
from .journal_service import JournalService
from .market_data import CsvMarketDataProvider
from .models import InstrumentType, TradeDirection
from .practice_harness import PracticeIntegrationHarness
from .runtime_logging import RuntimeEventLogger
from .safety import FileKillSwitch, ReconnectBackoffPolicy, StaleMarketDataGuard
from .scheduler import BotScheduler, SchedulerConfig
from .signal_engine import STRATEGY_ID_ORDER, build_selected_signal_engine, normalize_strategy_id


_SIGNAL_ENGINE_CHOICES = (
    *STRATEGY_ID_ORDER,
    "LOW",
    "MEDIUM",
    "HIGH",
    "trend-pullback",
    "strict-ema-pullback",
    "balanced-ema-pullback",
    "aggressive-ema-pullback",
    "simple-momentum",
    "blitz",
    "blitz-momentum",
    "relaxed-momentum",
    "mean-reversion",
    "bollinger-rsi-reversion",
)

DEFAULT_SIGNAL_ENGINE = "momentum.medium"
from .trade_journal import TradeJournalRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one or more practice-mode bot cycles.")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv file path.")
    parser.add_argument("--broker", choices=("practice", "iqoption"), default="practice")
    parser.add_argument("--market-data-source", choices=("csv", "iqoption"), default="csv")
    parser.add_argument("--market-data-csv")
    parser.add_argument("--strategy-version-id", required=True)
    parser.add_argument("--asset", action="append", dest="assets", help="Asset to trade. Repeat for multi-asset campaigns.")
    parser.add_argument("--instrument-type", choices=("binary", "digital"), required=True)
    parser.add_argument("--signal-engine", choices=_SIGNAL_ENGINE_CHOICES, default=DEFAULT_SIGNAL_ENGINE)
    parser.add_argument("--timeframe-sec", type=int, default=60)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--expiry-sec", type=int, default=60)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--target-closed-trades", type=int, default=0)
    parser.add_argument("--checkpoint-trades", type=int, default=0)
    parser.add_argument("--asset-scan-interval-sec", type=float, default=0.0)
    parser.add_argument("--poll-interval-sec", type=float, default=5.0)
    parser.add_argument("--kill-switch-file")
    parser.add_argument("--max-data-age-sec", type=int, default=120)
    parser.add_argument("--duplicate-window-sec", type=int, default=120)
    parser.add_argument("--practice-smoke-test", action="store_true")
    parser.add_argument("--smoke-test-candle-limit", type=int, default=3)
    parser.add_argument("--practice-order-probe", action="store_true")
    parser.add_argument("--direction", choices=("call", "put"), default="call")
    parser.add_argument("--probe-wait-for-close", action="store_true")
    parser.add_argument("--probe-timeout-sec", type=float, default=120.0)
    parser.add_argument("--probe-poll-interval-sec", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    assets = _resolve_assets(args, parser)
    primary_asset = assets[0]

    env_path = Path(args.env_file)
    load_dotenv_file(env_path)
    _validate_args(args, assets, parser)

    root_dir = Path(__file__).resolve().parents[2]
    config = load_config(root_dir)
    repository = TradeJournalRepository.from_paths(root_dir / "data" / "trades.db", root_dir / "sql" / "001_initial_schema.sql")
    journal_service = JournalService(repository)
    market_data_provider = _build_market_data_provider(args, config)
    signal_engine = _build_signal_engine(args.signal_engine)
    broker_adapter = _build_broker_adapter(args.broker, config, repository, journal_service)
    kill_switch = FileKillSwitch(Path(args.kill_switch_file)) if args.kill_switch_file else None
    runner_logger = RuntimeEventLogger(repository, config.runtime_log_dir, component="runner")
    scheduler_logger = RuntimeEventLogger(repository, config.runtime_log_dir, component="scheduler")
    duplicate_signal_guard = DuplicateSignalGuard(repository, window_sec=args.duplicate_window_sec)

    if args.practice_smoke_test or args.practice_order_probe:
        if not isinstance(market_data_provider, IQOptionMarketDataProvider) or not isinstance(broker_adapter, IQOptionAdapter):
            parser.error("practice harness options require --market-data-source=iqoption and --broker=iqoption")
        harness = PracticeIntegrationHarness(repository, market_data_provider, broker_adapter, event_logger=runner_logger)
        if args.practice_smoke_test:
            result = harness.run_smoke_test(
                asset=primary_asset,
                instrument_type=InstrumentType(args.instrument_type),
                timeframe_sec=args.timeframe_sec,
                candle_limit=args.smoke_test_candle_limit,
            )
            print(f"status={result.status} balance={result.balance} candle_count={result.candle_count} reason={result.reason}")
        else:
            result = harness.run_order_probe(
                asset=primary_asset,
                instrument_type=InstrumentType(args.instrument_type),
                direction=TradeDirection(args.direction),
                timeframe_sec=args.timeframe_sec,
                amount=args.stake,
                expiry_sec=args.expiry_sec,
                wait_for_close=args.probe_wait_for_close,
                poll_interval_sec=args.probe_poll_interval_sec,
                timeout_sec=args.probe_timeout_sec,
            )
            print(
                f"status={result.status} trade_id={result.trade_id} result={result.result} "
                f"profit_loss_abs={result.profit_loss_abs} reason={result.reason}"
            )
        repository.close()
        return 0

    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=market_data_provider,
        signal_engine=signal_engine,
        broker_adapter=broker_adapter,
        stale_data_guard=StaleMarketDataGuard(max_data_age_sec=args.max_data_age_sec),
        kill_switch=kill_switch,
        duplicate_signal_guard=duplicate_signal_guard,
        event_logger=runner_logger,
    )
    reconnectables = [component for component in (market_data_provider, broker_adapter) if hasattr(component, "reconnect_if_needed")]
    scheduler = BotScheduler(
        runner,
        reconnectables=reconnectables,
        kill_switch=kill_switch,
        reconnect_backoff_policy=ReconnectBackoffPolicy(),
        event_logger=scheduler_logger,
    )

    if args.target_closed_trades > 0:
        if not hasattr(broker_adapter, "poll_trade_result"):
            parser.error("--target-closed-trades requires a broker adapter with trade-result polling support")
        campaign_runner = MultiAssetCampaignRunner(runner, event_logger=runner_logger)
        campaign_result = campaign_runner.run(
            CampaignPlan(
                strategy_version_id=args.strategy_version_id,
                assets=tuple(assets),
                instrument_type=InstrumentType(args.instrument_type),
                timeframe_sec=args.timeframe_sec,
                stake_amount=args.stake,
                expiry_sec=args.expiry_sec,
                target_closed_trades=args.target_closed_trades,
                checkpoint_trades=args.checkpoint_trades,
                asset_scan_interval_sec=args.asset_scan_interval_sec,
                tags={"runner": "campaign_runner"},
            ),
            poll_interval_sec=args.poll_interval_sec,
        )
        print(
            f"campaign_status={campaign_result.status} campaign_id={campaign_result.campaign_id} "
            f"closed_trades={campaign_result.closed_trades} reason={campaign_result.reason}"
        )
        for checkpoint in campaign_result.checkpoints:
            tranche = checkpoint.tranche_metrics
            cumulative = checkpoint.cumulative_metrics
            print(
                f"checkpoint={checkpoint.checkpoint_number} closed_trades={checkpoint.closed_trades} "
                f"tranche_wins={tranche.wins} tranche_losses={tranche.losses} tranche_breakevens={tranche.breakevens} "
                f"tranche_net_pnl={tranche.net_pnl:.4f} tranche_expectancy={tranche.expectancy_per_trade:.4f} "
                f"cumulative_net_pnl={cumulative.net_pnl:.4f} cumulative_profit_factor={cumulative.profit_factor:.4f}"
            )
            for asset_metrics in checkpoint.tranche_asset_metrics:
                print(
                    f"checkpoint_asset={checkpoint.checkpoint_number} asset={asset_metrics.group_key} "
                    f"trades={asset_metrics.metrics.total_trades} wins={asset_metrics.metrics.wins} "
                    f"losses={asset_metrics.metrics.losses} breakevens={asset_metrics.metrics.breakevens} "
                    f"net_pnl={asset_metrics.metrics.net_pnl:.4f}"
                )
        repository.close()
        return 0

    results = scheduler.run(
        RunnerPlan(
            strategy_version_id=args.strategy_version_id,
            asset=primary_asset,
            instrument_type=InstrumentType(args.instrument_type),
            timeframe_sec=args.timeframe_sec,
            stake_amount=args.stake,
            expiry_sec=args.expiry_sec,
        ),
        SchedulerConfig(cycles=args.cycles, poll_interval_sec=args.poll_interval_sec),
    )
    for result in results:
        print(f"status={result.status} reason={result.reason} signal_id={result.signal_id} trade_id={result.trade_id}")
    repository.close()
    return 0


def _resolve_assets(args, parser: argparse.ArgumentParser) -> list[str]:
    assets = args.assets or []
    if not assets:
        parser.error("at least one --asset is required")
    return assets


def _validate_args(args, assets: list[str], parser: argparse.ArgumentParser) -> None:
    if args.market_data_source == "csv" and not args.market_data_csv:
        parser.error("--market-data-csv is required when --market-data-source=csv")
    if args.broker == "iqoption" and args.expiry_sec % 60 != 0:
        parser.error("--expiry-sec must be a whole minute when --broker=iqoption with the current adapter")
    if args.target_closed_trades < 0:
        parser.error("--target-closed-trades cannot be negative")
    if args.checkpoint_trades < 0:
        parser.error("--checkpoint-trades cannot be negative")
    if args.checkpoint_trades > 0 and args.target_closed_trades == 0:
        parser.error("--checkpoint-trades requires --target-closed-trades")
    if args.checkpoint_trades > args.target_closed_trades > 0:
        parser.error("--checkpoint-trades cannot exceed --target-closed-trades")
    if args.asset_scan_interval_sec < 0:
        parser.error("--asset-scan-interval-sec cannot be negative")
    if len(assets) > 1 and args.target_closed_trades == 0:
        parser.error("multiple --asset values require --target-closed-trades")
    if (args.practice_smoke_test or args.practice_order_probe) and len(assets) != 1:
        parser.error("practice harness options require exactly one --asset")


def _build_signal_engine(engine_name: str):
    return build_selected_signal_engine((normalize_strategy_id(engine_name),))


def _build_market_data_provider(args, config):
    if args.market_data_source == "iqoption":
        provider = IQOptionMarketDataProvider.from_environment(config)
        provider.connect()
        return provider
    return CsvMarketDataProvider(Path(args.market_data_csv))


def _build_broker_adapter(broker_name: str, config, repository, journal_service):
    if broker_name == "iqoption":
        adapter = IQOptionAdapter.from_environment(config, repository, journal_service)
        adapter.connect()
        return adapter
    return PracticeBrokerAdapter(config, repository, journal_service)


if __name__ == "__main__":
    raise SystemExit(main())
