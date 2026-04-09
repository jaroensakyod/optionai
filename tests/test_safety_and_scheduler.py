from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.bot.bot_runner import BotRunResult, BotRunner, RunnerPlan
from src.bot.broker_adapter import PracticeBrokerAdapter
from src.bot.config import load_config
from src.bot.iqoption_adapter import IQOptionCredentials
from src.bot.iqoption_market_data import IQOptionMarketDataProvider
from src.bot.journal_service import JournalService
from src.bot.market_data import Candle, CsvMarketDataProvider
from src.bot.models import InstrumentType
from src.bot.safety import FileKillSwitch, ReconnectBackoffPolicy, StaleMarketDataGuard
from src.bot.scheduler import BotScheduler, SchedulerConfig
from src.bot.signal_engine import SimpleMomentumSignalEngine
from src.bot.trade_journal import TradeJournalRepository


class FakeIQMarketClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.connected = False
        self.balance_mode = None
        self.candles = [
            {"from": 1712649600, "open": 1.1, "max": 1.11, "min": 1.09, "close": 1.105, "volume": 10},
            {"from": 1712649660, "open": 1.105, "max": 1.12, "min": 1.10, "close": 1.115, "volume": 12},
        ]

    def connect(self):
        self.connected = True
        return True, "success"

    def check_connect(self):
        return self.connected

    def change_balance(self, mode: str):
        self.balance_mode = mode

    def get_candles(self, asset: str, timeframe_sec: int, limit: int, end_from_time: float):
        return self.candles[:limit]


class FlakyIQMarketClient(FakeIQMarketClient):
    failure_emitted = False

    def __init__(self, email: str, password: str):
        super().__init__(email, password)
        self.fetch_calls = 0

    def get_candles(self, asset: str, timeframe_sec: int, limit: int, end_from_time: float):
        self.fetch_calls += 1
        if not FlakyIQMarketClient.failure_emitted:
            FlakyIQMarketClient.failure_emitted = True
            raise RuntimeError("need reconnect")
        return super().get_candles(asset, timeframe_sec, limit, end_from_time)


class FlakyReconnectable:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def reconnect_if_needed(self) -> bool:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("still down")
        return True


class ExplodingRunner:
    def __init__(self):
        self.calls = 0

    def run_once(self, plan, now_utc=None):
        self.calls += 1
        raise RuntimeError("boom")


def test_iqoption_market_data_provider_fetches_recent_candles(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    client = FakeIQMarketClient("user@example.com", "secret")
    provider = IQOptionMarketDataProvider(
        config=config,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    provider.connect()
    candles = provider.get_recent_candles(
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        limit=2,
    )

    assert client.balance_mode == "PRACTICE"
    assert len(candles) == 2
    assert candles[-1].close_price == 1.115


def test_iqoption_market_data_provider_retries_after_candle_fetch_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    clients: list[FlakyIQMarketClient] = []
    FlakyIQMarketClient.failure_emitted = False

    def build_client(email: str, password: str) -> FlakyIQMarketClient:
        client = FlakyIQMarketClient(email, password)
        clients.append(client)
        return client

    provider = IQOptionMarketDataProvider(
        config=config,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=build_client,
    )

    candles = provider.get_recent_candles(
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        limit=2,
    )

    assert len(clients) == 2
    assert clients[0].fetch_calls == 1
    assert candles[-1].close_price == 1.115


def test_stale_market_data_guard_skips_runner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    csv_path = tmp_path / "candles.csv"
    csv_path.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price\n"
        "2026-04-09T08:00:00+00:00,EURUSD,digital,60,1.1000,1.1010,1.0995,1.1008\n"
        "2026-04-09T08:01:00+00:00,EURUSD,digital,60,1.1008,1.1020,1.1006,1.1017\n"
        "2026-04-09T08:02:00+00:00,EURUSD,digital,60,1.1017,1.1030,1.1015,1.1026\n",
        encoding="utf-8",
    )
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(csv_path),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
        stale_data_guard=StaleMarketDataGuard(max_data_age_sec=30),
    )

    result = runner.run_once(
        RunnerPlan(
            strategy_version_id="stale-v1",
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        now_utc=datetime(2026, 4, 9, 8, 5, tzinfo=UTC),
    )

    assert result == BotRunResult(status="skipped", reason="stale_market_data")
    repository.close()


def test_scheduler_stops_when_kill_switch_file_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_provider = _build_fresh_csv_provider(tmp_path)
    kill_switch_path = tmp_path / "STOP"
    kill_switch = FileKillSwitch(kill_switch_path)
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=market_data_provider,
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
        stale_data_guard=StaleMarketDataGuard(max_data_age_sec=120),
        kill_switch=kill_switch,
    )

    def fake_sleep(_: float) -> None:
        kill_switch_path.write_text("stop", encoding="utf-8")

    scheduler = BotScheduler(runner, kill_switch=kill_switch, sleep_fn=fake_sleep)
    results = scheduler.run(
        RunnerPlan(
            strategy_version_id="sched-v1",
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        SchedulerConfig(cycles=3, poll_interval_sec=0.0),
    )

    assert results[0].status == "submitted"
    assert results[1] == BotRunResult(status="stopped", reason="kill_switch_file_detected")
    repository.close()


def test_reconnect_backoff_policy_and_scheduler_recovery() -> None:
    policy = ReconnectBackoffPolicy(max_attempts=3, base_delay_sec=1.0, multiplier=2.0, max_delay_sec=5.0)
    assert policy.delays() == [1.0, 2.0, 4.0]

    flaky = FlakyReconnectable(fail_times=1)
    sleep_calls: list[float] = []
    scheduler = BotScheduler(
        ExplodingRunner(),
        reconnectables=[flaky],
        reconnect_backoff_policy=ReconnectBackoffPolicy(max_attempts=2, base_delay_sec=0.5, multiplier=2.0),
        sleep_fn=lambda value: sleep_calls.append(value),
    )
    results = scheduler.run(
        RunnerPlan(
            strategy_version_id="recover-v1",
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        SchedulerConfig(cycles=1, poll_interval_sec=0.0),
    )

    assert results == [BotRunResult(status="recovered", reason="RuntimeError")]
    assert sleep_calls == [0.5]


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _build_fresh_csv_provider(tmp_path: Path) -> CsvMarketDataProvider:
    csv_path = tmp_path / "candles.csv"
    base_time = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2)
    csv_path.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price\n"
        f"{base_time.isoformat()},EURUSD,digital,60,1.1000,1.1010,1.0995,1.1008\n"
        f"{(base_time + timedelta(minutes=1)).isoformat()},EURUSD,digital,60,1.1008,1.1020,1.1006,1.1017\n"
        f"{(base_time + timedelta(minutes=2)).isoformat()},EURUSD,digital,60,1.1017,1.1030,1.1015,1.1026\n",
        encoding="utf-8",
    )
    return CsvMarketDataProvider(csv_path)
