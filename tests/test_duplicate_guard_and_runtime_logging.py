from datetime import UTC, datetime
from pathlib import Path

from src.bot.bot_runner import BotRunResult, BotRunner, RunnerPlan
from src.bot.broker_adapter import PracticeBrokerAdapter
from src.bot.config import load_config
from src.bot.duplicate_guard import DuplicateSignalGuard
from src.bot.iqoption_adapter import IQOptionAdapter, IQOptionCredentials
from src.bot.iqoption_market_data import IQOptionMarketDataProvider
from src.bot.journal_service import JournalService
from src.bot.market_data import CsvMarketDataProvider
from src.bot.models import InstrumentType, StrategyVersion, TradeDirection
from src.bot.practice_harness import PracticeIntegrationHarness
from src.bot.runtime_logging import RuntimeEventLogger
from src.bot.safety import StaleMarketDataGuard
from src.bot.signal_engine import SimpleMomentumSignalEngine
from src.bot.trade_journal import TradeJournalRepository


class FakeIQFullClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.connected = False
        self.balance_mode = None

    def connect(self):
        self.connected = True
        return True, "success"

    def check_connect(self):
        return self.connected

    def change_balance(self, mode: str):
        self.balance_mode = mode

    def get_balance(self):
        return 3210.5

    def get_digital_payout(self, asset: str):
        return 82.0

    def get_all_profit(self):
        return {"EURUSD": {"turbo": 0.8}, "EURUSD-OTC": {"turbo": 0.8}}

    def buy_digital_spot_v2(self, asset: str, amount: float, action: str, duration: int):
        return True, 1001

    def buy(self, amount: float, asset: str, action: str, duration: int):
        return True, 1002

    def check_win_digital(self, broker_id: int):
        return False, None

    def check_win_v3(self, broker_id: int):
        return 0.8

    def get_candles(self, asset: str, timeframe_sec: int, limit: int, end_from_time: float):
        return [
            {"from": 1712649600, "open": 1.1, "max": 1.11, "min": 1.09, "close": 1.105, "volume": 10},
            {"from": 1712649660, "open": 1.105, "max": 1.12, "min": 1.10, "close": 1.115, "volume": 12},
            {"from": 1712649720, "open": 1.115, "max": 1.13, "min": 1.11, "close": 1.125, "volume": 14},
        ][:limit]


def test_duplicate_signal_guard_prevents_second_trade_and_logs_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("BOT_MAX_OPEN_POSITIONS", "2")
    now_utc = datetime.now(UTC)
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    csv_path = _write_candles(tmp_path)
    event_logger = RuntimeEventLogger(repository, tmp_path / "runtime_logs", component="runner")
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(csv_path),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
        stale_data_guard=StaleMarketDataGuard(max_data_age_sec=10**9),
        duplicate_signal_guard=DuplicateSignalGuard(repository, window_sec=10**9),
        event_logger=event_logger,
    )
    plan = RunnerPlan(
        strategy_version_id="dup-v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
    )

    first = runner.run_once(plan, now_utc=now_utc)
    second = runner.run_once(plan, now_utc=now_utc)

    events = repository.list_system_events(component="runner")
    assert first.status == "submitted"
    assert second == BotRunResult(status="skipped", reason="duplicate_signal")
    assert any(event.event_type == "duplicate_signal_prevented" for event in events)
    repository.close()


def test_runtime_event_logger_persists_jsonl_and_system_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    logger = RuntimeEventLogger(repository, config.runtime_log_dir, component="scheduler")

    logger.log(
        severity="warning",
        event_type="reconnect_attempt",
        message="Reconnect attempted.",
        details={"attempt": 1},
    )

    events = repository.list_system_events(component="scheduler")
    log_files = list(config.runtime_log_dir.glob("*-events.jsonl"))
    assert len(events) == 1
    assert events[0].event_type == "reconnect_attempt"
    assert len(log_files) == 1
    assert "reconnect_attempt" in log_files[0].read_text(encoding="utf-8")
    repository.close()


def test_practice_integration_harness_smoke_test_passes_with_fake_client(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    strategy = StrategyVersion(
        strategy_version_id="smoke-v1",
        created_at_utc=datetime(2026, 4, 9, 8, 0, tzinfo=UTC),
        strategy_name="smoke",
        parameter_hash="hash",
        parameters={"mode": "smoke"},
        created_by="test",
        approval_status="approved",
    )
    repository.save_strategy_version(strategy)
    client = FakeIQFullClient("user@example.com", "secret")
    broker_adapter = IQOptionAdapter(
        config=config,
        repository=repository,
        journal_service=journal_service,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )
    market_data_provider = IQOptionMarketDataProvider(
        config=config,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )
    broker_adapter.connect()
    market_data_provider.connect()
    logger = RuntimeEventLogger(repository, tmp_path / "runtime_logs", component="runner")
    harness = PracticeIntegrationHarness(repository, market_data_provider, broker_adapter, event_logger=logger)

    result = harness.run_smoke_test(
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        candle_limit=3,
    )

    events = repository.list_system_events(component="runner")
    assert result.status == "passed"
    assert result.balance == 3210.5
    assert result.candle_count == 3
    assert any(event.event_type == "practice_smoke_test_passed" for event in events)
    repository.close()


def test_practice_integration_harness_binary_order_probe_closes_trade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    client = FakeIQFullClient("user@example.com", "secret")
    broker_adapter = IQOptionAdapter(
        config=config,
        repository=repository,
        journal_service=journal_service,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )
    market_data_provider = IQOptionMarketDataProvider(
        config=config,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )
    broker_adapter.connect()
    market_data_provider.connect()
    logger = RuntimeEventLogger(repository, tmp_path / "runtime_logs", component="runner")
    harness = PracticeIntegrationHarness(repository, market_data_provider, broker_adapter, event_logger=logger)

    result = harness.run_order_probe(
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        direction=TradeDirection.CALL,
        timeframe_sec=60,
        amount=1.0,
        expiry_sec=60,
        wait_for_close=True,
        poll_interval_sec=0.01,
        timeout_sec=1.0,
    )

    events = repository.list_system_events(component="runner")
    assert result.status == "closed"
    assert result.result == "WIN"
    assert result.profit_loss_abs == 0.8
    assert any(event.event_type == "practice_order_probe_closed" for event in events)
    repository.close()


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _write_candles(tmp_path: Path) -> Path:
    csv_path = tmp_path / "candles.csv"
    csv_path.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price\n"
        "2026-04-09T08:00:00+00:00,EURUSD,digital,60,1.1000,1.1010,1.0995,1.1008\n"
        "2026-04-09T08:01:00+00:00,EURUSD,digital,60,1.1008,1.1020,1.1006,1.1017\n"
        "2026-04-09T08:02:00+00:00,EURUSD,digital,60,1.1017,1.1030,1.1015,1.1026\n",
        encoding="utf-8",
    )
    return csv_path