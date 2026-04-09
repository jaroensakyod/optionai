from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.bot.bot_runner import BotRunResult, BotRunner, RunnerPlan
from src.bot.broker_adapter import PracticeBrokerAdapter
from src.bot.config import load_config
from src.bot.env import load_dotenv_file
from src.bot.journal_service import JournalService
from src.bot.market_data import CsvMarketDataProvider
from src.bot.models import InstrumentType
from src.bot.signal_engine import SimpleMomentumSignalEngine
from src.bot.trade_journal import TradeJournalRepository


def test_load_dotenv_file_reads_values_without_overriding(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BOT_ACCOUNT_MODE=PRACTICE\nBOT_MAX_STAKE=2.5\nCUSTOM_TOKEN='abc'\n", encoding="utf-8")
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")

    loaded = load_dotenv_file(env_path)

    assert loaded["BOT_MAX_STAKE"] == "2.5"
    assert loaded["CUSTOM_TOKEN"] == "abc"


def test_bot_runner_submits_trade_from_csv_market_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("BOT_MAX_STAKE", "10.0")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    market_data_csv.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price,volume\n"
        "2026-04-09T08:00:00+00:00,EURUSD,digital,60,1.1000,1.1010,1.0995,1.1008,10\n"
        "2026-04-09T08:01:00+00:00,EURUSD,digital,60,1.1008,1.1020,1.1006,1.1017,12\n"
        "2026-04-09T08:02:00+00:00,EURUSD,digital,60,1.1017,1.1030,1.1015,1.1026,14\n",
        encoding="utf-8",
    )

    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
    )

    result = runner.run_once(
        RunnerPlan(
            strategy_version_id="runner-v1",
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
            tags={"source": "test"},
        ),
        now_utc=datetime(2026, 4, 9, 8, 3, tzinfo=UTC),
    )

    trades = repository.list_trades(account_mode="PRACTICE")
    assert result.status == "submitted"
    assert result.signal_id is not None
    assert len(trades) == 1
    assert repository.get_trade_tags(trades[0].trade_id)["source"] == "test"
    repository.close()


def test_bot_runner_skips_when_open_position_limit_reached(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("BOT_MAX_OPEN_POSITIONS", "1")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    market_data_csv.write_text(
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
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
    )
    plan = RunnerPlan(
        strategy_version_id="runner-v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
    )

    first_result = runner.run_once(plan, now_utc=datetime(2026, 4, 9, 8, 3, tzinfo=UTC))
    second_result = runner.run_once(plan, now_utc=datetime(2026, 4, 9, 8, 4, tzinfo=UTC) + timedelta(minutes=1))

    assert first_result.status == "submitted"
    assert second_result == BotRunResult(status="skipped", reason="max_open_positions_reached")
    repository.close()


def test_bot_runner_skips_binary_trade_outside_entry_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    market_data_csv.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price\n"
        "2026-04-09T08:00:00+00:00,GBPUSD,binary,60,1.1000,1.1010,1.0995,1.1008\n"
        "2026-04-09T08:01:00+00:00,GBPUSD,binary,60,1.1008,1.1020,1.1006,1.1017\n"
        "2026-04-09T08:02:00+00:00,GBPUSD,binary,60,1.1017,1.1030,1.1015,1.1026\n",
        encoding="utf-8",
    )
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
    )

    result = runner.run_once(
        RunnerPlan(
            strategy_version_id="runner-binary-v1",
            asset="GBPUSD",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        now_utc=datetime(2026, 4, 9, 8, 3, 15, tzinfo=UTC),
    )

    assert result == BotRunResult(status="skipped", reason="awaiting_entry_window")
    assert repository.list_trades(account_mode="PRACTICE") == []
    repository.close()


def test_bot_runner_submits_binary_trade_at_entry_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    market_data_csv.write_text(
        "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price\n"
        "2026-04-09T08:00:00+00:00,GBPUSD,binary,60,1.1000,1.1010,1.0995,1.1008\n"
        "2026-04-09T08:01:00+00:00,GBPUSD,binary,60,1.1008,1.1020,1.1006,1.1017\n"
        "2026-04-09T08:02:00+00:00,GBPUSD,binary,60,1.1017,1.1030,1.1015,1.1026\n",
        encoding="utf-8",
    )
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
    )

    result = runner.run_once(
        RunnerPlan(
            strategy_version_id="runner-binary-v1",
            asset="GBPUSD",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        now_utc=datetime(2026, 4, 9, 8, 3, 1, tzinfo=UTC),
    )

    assert result.status == "submitted"
    assert len(repository.list_trades(account_mode="PRACTICE")) == 1
    repository.close()


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)
