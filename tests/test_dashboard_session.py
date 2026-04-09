from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.bot import dashboard_session
from src.bot.bot_runner import BotRunResult
from src.bot.config import RiskLimits
from src.bot.dashboard_session import DashboardSessionController, SessionRunConfig, SessionStopTargets, build_session_snapshot, check_stop_threshold
from src.bot.market_data import Candle
from src.bot.models import InstrumentType, StrategyVersion, TradeDirection, TradeJournalRecord, TradeResult
from src.bot.trade_journal import TradeJournalRepository


def test_check_stop_threshold_uses_absolute_targets(tmp_path) -> None:
    repository = _build_repository(tmp_path)
    _seed_session_trade(repository, strategy_version_id="session-a", trade_id="session-a-1", profit_loss_abs=6.0)

    reason = check_stop_threshold(
        repository=repository,
        strategy_version_id="session-a",
        baseline_balance=100.0,
        targets=SessionStopTargets(mode="$", profit_target=5.0, loss_limit=5.0),
    )

    assert reason == "profit_target_reached"
    repository.close()


def test_check_stop_threshold_uses_percent_targets(tmp_path) -> None:
    repository = _build_repository(tmp_path)
    _seed_session_trade(repository, strategy_version_id="session-b", trade_id="session-b-1", profit_loss_abs=-3.0)

    reason = check_stop_threshold(
        repository=repository,
        strategy_version_id="session-b",
        baseline_balance=100.0,
        targets=SessionStopTargets(mode="%", profit_target=5.0, loss_limit=2.0),
    )

    assert reason == "loss_limit_reached"
    repository.close()


def test_build_session_snapshot_summarizes_closed_results(tmp_path) -> None:
    repository = _build_repository(tmp_path)
    _seed_session_trade(repository, strategy_version_id="session-c", trade_id="session-c-1", profit_loss_abs=0.8)
    _seed_session_trade(repository, strategy_version_id="session-c", trade_id="session-c-2", asset="GBPUSD", profit_loss_abs=-1.0)

    snapshot = build_session_snapshot(
        repository=repository,
        strategy_version_id="session-c",
        selected_assets=("EURUSD", "GBPUSD"),
        current_assets=("EURUSD",),
        current_asset="EURUSD",
        baseline_balance=100.0,
        status="running",
        last_reason=None,
        last_trade_id=None,
        target_mode="$",
    )

    assert snapshot.closed_trades == 2
    assert snapshot.current_assets == ("EURUSD",)
    assert snapshot.current_asset == "EURUSD"
    assert snapshot.wins == 1
    assert snapshot.losses == 1
    assert snapshot.net_pnl == pytest.approx(-0.2)
    repository.close()


def test_dashboard_session_checks_each_selected_asset_on_start(tmp_path, monkeypatch) -> None:
    root_dir = _build_runtime_root(tmp_path)
    observed_candle_assets: list[str] = []
    observed_signal_assets: list[str] = []

    class FakeMarketDataProvider:
        def connect(self) -> None:
            return None

        @classmethod
        def from_environment(cls, _config):
            return cls()

        def get_recent_candles(self, *, asset: str, instrument_type: InstrumentType, timeframe_sec: int, limit: int) -> list[Candle]:
            observed_candle_assets.append(asset)
            opened_at = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
            return [
                Candle(opened_at_utc=opened_at, asset=asset, instrument_type=instrument_type, timeframe_sec=timeframe_sec, open_price=1.0, high_price=1.1, low_price=0.9, close_price=1.0),
                Candle(opened_at_utc=opened_at, asset=asset, instrument_type=instrument_type, timeframe_sec=timeframe_sec, open_price=1.0, high_price=1.1, low_price=0.9, close_price=1.0),
                Candle(opened_at_utc=opened_at, asset=asset, instrument_type=instrument_type, timeframe_sec=timeframe_sec, open_price=1.0, high_price=1.1, low_price=0.9, close_price=1.0),
            ][:limit]

    class FakeBrokerAdapter:
        def connect(self) -> None:
            return None

        @classmethod
        def from_environment(cls, _config, _repository, _journal_service):
            return cls()

        def get_balance(self) -> float:
            return 100.0

        def poll_trade_result(self, _trade_id: str):
            return None

    class FakeSignalEngine:
        @property
        def strategy_name(self) -> str:
            return "fake-signal"

        @property
        def required_candles(self) -> int:
            return 3

        def describe_parameters(self) -> dict[str, float]:
            return {"required_candles": 3}

        def build_signal(self, **kwargs):
            observed_signal_assets.append(kwargs["asset"])
            if len(observed_signal_assets) >= 2:
                controller.stop()
            return None

    class FakeBotRunner:
        def __init__(self, **kwargs):
            self._market_data_provider = kwargs["market_data_provider"]
            self._signal_engine = kwargs["signal_engine"]

        def run_once(self, plan):
            candles = self._market_data_provider.get_recent_candles(
                asset=plan.asset,
                instrument_type=plan.instrument_type,
                timeframe_sec=plan.timeframe_sec,
                limit=self._signal_engine.required_candles,
            )
            self._signal_engine.build_signal(
                strategy_version_id=plan.strategy_version_id,
                asset=plan.asset,
                instrument_type=plan.instrument_type,
                timeframe_sec=plan.timeframe_sec,
                stake_amount=plan.stake_amount,
                expiry_sec=plan.expiry_sec,
                candles=candles,
                signal_time_utc=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
            )
            return BotRunResult(status="skipped", reason="no_signal")

    class FakeEventLogger:
        def __init__(self, *_args, **_kwargs):
            return None

        def log(self, **_kwargs) -> None:
            return None

    monkeypatch.setattr(dashboard_session, "IQOptionMarketDataProvider", FakeMarketDataProvider)
    monkeypatch.setattr(dashboard_session, "IQOptionAdapter", FakeBrokerAdapter)
    monkeypatch.setattr(dashboard_session, "SimpleMomentumSignalEngine", FakeSignalEngine)
    monkeypatch.setattr(dashboard_session, "BotRunner", FakeBotRunner)
    monkeypatch.setattr(dashboard_session, "RuntimeEventLogger", FakeEventLogger)
    monkeypatch.setattr(dashboard_session.time, "sleep", lambda _seconds: None)

    controller = DashboardSessionController(_load_test_config(tmp_path), root_dir)
    run_config = SessionRunConfig(
        assets=("AUDCAD-OTC", "AUDCHF-OTC", "AUDJPY-OTC"),
        batch_size=2,
        stake_amount=1.0,
        timeframe_sec=60,
        expiry_sec=60,
        poll_interval_sec=0.01,
        stop_targets=SessionStopTargets(mode="$", profit_target=0.0, loss_limit=0.0),
    )
    updates = []

    controller._run_session("session-start-check", run_config, updates.append)

    assert observed_candle_assets == ["AUDCAD-OTC", "AUDCHF-OTC"]
    assert observed_signal_assets == ["AUDCAD-OTC", "AUDCHF-OTC"]
    observed_update_assets = [snapshot.current_asset for snapshot in updates if snapshot.current_asset is not None]
    observed_update_batches = [snapshot.current_assets for snapshot in updates if snapshot.current_assets]
    assert observed_update_assets[0] == "AUDCAD-OTC + AUDCHF-OTC"
    assert observed_update_batches[0] == ("AUDCAD-OTC", "AUDCHF-OTC")
    assert "AUDJPY-OTC" not in observed_update_assets
    assert "AUDCHF-OTC" in observed_update_assets
    assert updates[-1].status == "stopped"


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _build_runtime_root(tmp_path: Path) -> Path:
    root_dir = tmp_path / "runtime-root"
    (root_dir / "sql").mkdir(parents=True)
    schema_source = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    (root_dir / "sql" / "001_initial_schema.sql").write_text(schema_source.read_text(encoding="utf-8"), encoding="utf-8")
    return root_dir


def _load_test_config(tmp_path: Path):
    return dashboard_session.AppConfig(
        app_mode="PRACTICE",
        database_path=tmp_path / "unused.db",
        runtime_log_dir=tmp_path / "runtime_logs",
        backtest_log_dir=tmp_path / "backtest_logs",
        risk_limits=RiskLimits(),
    )


def _seed_session_trade(
    repository: TradeJournalRepository,
    *,
    strategy_version_id: str,
    trade_id: str,
    profit_loss_abs: float,
    asset: str = "EURUSD",
) -> None:
    created_at = datetime(2026, 4, 9, 12, 0, tzinfo=UTC)
    repository.save_strategy_version(
        StrategyVersion(
            strategy_version_id=strategy_version_id,
            created_at_utc=created_at,
            strategy_name="desktop-session",
            parameter_hash=strategy_version_id,
            parameters={"surface": "desktop"},
            created_by="test",
            approval_status="approved",
        )
    )
    repository.upsert_trade(
        TradeJournalRecord(
            trade_id=trade_id,
            signal_id=None,
            strategy_version_id=strategy_version_id,
            opened_at_utc=created_at,
            closed_at_utc=created_at,
            asset=asset,
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            direction=TradeDirection.CALL,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.WIN if profit_loss_abs > 0 else TradeResult.LOSS,
            payout_snapshot=0.8,
            profit_loss_abs=profit_loss_abs,
            profit_loss_pct_risk=profit_loss_abs,
        )
    )