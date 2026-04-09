from pathlib import Path

from src.bot.config import load_config
from src.bot.iqoption_adapter import IQOptionCredentials
from src.bot.iqoption_market_data import IQOptionMarketDataProvider
from src.bot.iqoption_sanity import _format_result, main, run_sanity_check
from src.bot.journal_service import JournalService
from src.bot.models import InstrumentType
from src.bot.trade_journal import TradeJournalRepository


class FakeIQSanityClient:
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
        return 4321.0

    def get_candles(self, asset: str, timeframe_sec: int, limit: int, end_from_time: float):
        return [
            {"from": 1712649600, "open": 1.1, "max": 1.11, "min": 1.09, "close": 1.105, "volume": 10},
            {"from": 1712649660, "open": 1.105, "max": 1.12, "min": 1.10, "close": 1.115, "volume": 12},
            {"from": 1712649720, "open": 1.115, "max": 1.13, "min": 1.11, "close": 1.125, "volume": 14},
        ][:limit]

    def get_digital_payout(self, asset: str):
        return 82.0

    def get_all_profit(self):
        return {"EURUSD": {"turbo": 0.8}}


def test_run_sanity_check_fails_for_placeholder_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("IQOPTION_EMAIL", "your-email@example.com")
    monkeypatch.setenv("IQOPTION_PASSWORD", "your-password")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)

    result = run_sanity_check(
        config=config,
        repository=repository,
        journal_service=journal_service,
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        candle_limit=3,
    )

    assert result.status == "failed"
    assert result.reason == "invalid_credentials"
    assert result.checks[0].status == "ok"
    assert result.checks[1].name == "credentials"
    assert result.checks[1].status == "failed"
    repository.close()


def test_run_sanity_check_passes_with_fake_clients(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("IQOPTION_EMAIL", "user@example.com")
    monkeypatch.setenv("IQOPTION_PASSWORD", "secret")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    client = FakeIQSanityClient("user@example.com", "secret")

    result = run_sanity_check(
        config=config,
        repository=repository,
        journal_service=journal_service,
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        candle_limit=3,
        broker_client_factory=lambda email, password: client,
        market_client_factory=lambda email, password: client,
    )

    assert result.status == "passed"
    assert result.balance == 4321.0
    assert result.candle_count == 3
    assert [check.status for check in result.checks] == ["ok", "ok", "ok"]
    assert "balance=4321.0" in _format_result(result)
    repository.close()


def test_sanity_main_returns_non_zero_for_placeholder_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BOT_ACCOUNT_MODE=PRACTICE\nIQOPTION_EMAIL=your-email@example.com\nIQOPTION_PASSWORD=your-password\n",
        encoding="utf-8",
    )
    _write_schema_workspace(tmp_path)

    exit_code = main(["--env-file", str(env_path)])

    assert exit_code == 1


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _write_schema_workspace(tmp_path: Path) -> None:
    schema_source = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    schema_target = tmp_path / "sql" / "001_initial_schema.sql"
    schema_target.parent.mkdir(parents=True, exist_ok=True)
    schema_target.write_text(schema_source.read_text(encoding="utf-8"), encoding="utf-8")