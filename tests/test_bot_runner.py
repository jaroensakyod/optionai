from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.bot.bot_runner import BotRunResult, BotRunner, RunnerPlan
from src.bot.broker_adapter import PracticeBrokerAdapter
from src.bot.config import load_config
from src.bot.env import load_dotenv_file
from src.bot.iqoption_adapter import IQOptionOrderUnavailableError
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
    _write_bullish_csv(market_data_csv, assets=("EURUSD",), instrument_type="digital", include_volume=True)

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


def test_bot_runner_skips_when_same_asset_open_position_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("BOT_MAX_OPEN_POSITIONS", "1")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    _write_bullish_csv(market_data_csv, assets=("EURUSD",), instrument_type="digital")
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
    assert second_result == BotRunResult(status="skipped", reason="open_position_for_asset_exists")
    repository.close()


def test_bot_runner_allows_different_assets_to_open_at_same_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    monkeypatch.setenv("BOT_MAX_OPEN_POSITIONS", "1")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    _write_bullish_csv(market_data_csv, assets=("EURUSD", "GBPUSD"), instrument_type="digital")
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
    )
    first_plan = RunnerPlan(
        strategy_version_id="runner-v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
    )
    second_plan = RunnerPlan(
        strategy_version_id="runner-v1",
        asset="GBPUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
    )

    first_result = runner.run_once(first_plan, now_utc=datetime(2026, 4, 9, 8, 3, tzinfo=UTC))
    second_result = runner.run_once(second_plan, now_utc=datetime(2026, 4, 9, 8, 3, tzinfo=UTC))

    assert first_result.status == "submitted"
    assert second_result.status == "submitted"
    assert len(repository.list_trades(account_mode="PRACTICE")) == 2
    repository.close()


def test_bot_runner_skips_binary_trade_outside_entry_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    _write_bullish_csv(market_data_csv, assets=("GBPUSD",), instrument_type="binary")
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


def test_bot_runner_logs_detailed_momentum_no_signal_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)

    class ChoppyMarketDataProvider:
        def get_recent_candles(self, *, asset: str, instrument_type: InstrumentType, timeframe_sec: int, limit: int):
            candles = []
            current = 1.2000
            for index in range(limit):
                if index % 2 == 0:
                    next_close = current + 0.00012
                    candles.append(
                        type("CandleRow", (), {
                            "opened_at_utc": datetime(2026, 4, 9, 8, 3, tzinfo=UTC),
                            "asset": asset,
                            "instrument_type": instrument_type,
                            "timeframe_sec": timeframe_sec,
                            "open_price": current,
                            "high_price": current + 0.00022,
                            "low_price": current - 0.00018,
                            "close_price": next_close,
                        })
                    )
                else:
                    next_close = current - 0.00010
                    candles.append(
                        type("CandleRow", (), {
                            "opened_at_utc": datetime(2026, 4, 9, 8, 3, tzinfo=UTC),
                            "asset": asset,
                            "instrument_type": instrument_type,
                            "timeframe_sec": timeframe_sec,
                            "open_price": current,
                            "high_price": current + 0.00018,
                            "low_price": current - 0.00022,
                            "close_price": next_close,
                        })
                    )
                current = next_close
            return candles

    class FakeEventLogger:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def log(self, **kwargs) -> None:
            self.events.append(kwargs)

    event_logger = FakeEventLogger()
    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=ChoppyMarketDataProvider(),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=PracticeBrokerAdapter(config, repository, journal_service),
        event_logger=event_logger,
    )

    result = runner.run_once(
        RunnerPlan(
            strategy_version_id="runner-no-signal-v1",
            asset="GBPUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            stake_amount=1.0,
            expiry_sec=60,
        ),
        now_utc=datetime(2026, 4, 9, 8, 3, tzinfo=UTC),
    )

    assert result == BotRunResult(status="skipped", reason="pattern_not_aligned")
    assert event_logger.events[-1]["event_type"] == "no_signal"
    assert event_logger.events[-1]["details"] == {"asset": "GBPUSD", "reason": "pattern_not_aligned"}
    repository.close()




def test_bot_runner_skips_when_broker_reports_closed_pair(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    journal_service = JournalService(repository)
    market_data_csv = tmp_path / "candles.csv"
    _write_bullish_csv(market_data_csv, assets=("GBPUSD",), instrument_type="binary")

    class ClosedPairBrokerAdapter:
        def submit_order(self, *, signal_event, strategy_version_id: str, tags=None):
            raise IQOptionOrderUnavailableError(f"{signal_event.asset} is closed")

    runner = BotRunner(
        config=config,
        repository=repository,
        journal_service=journal_service,
        market_data_provider=CsvMarketDataProvider(market_data_csv),
        signal_engine=SimpleMomentumSignalEngine(),
        broker_adapter=ClosedPairBrokerAdapter(),
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

    assert result == BotRunResult(status="skipped", reason="market_closed_or_unavailable")
    assert repository.list_trades(account_mode="PRACTICE") == []
    repository.close()


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _write_bullish_csv(csv_path: Path, *, assets: tuple[str, ...], instrument_type: str, include_volume: bool = False) -> None:
    header = "opened_at_utc,asset,instrument_type,timeframe_sec,open_price,high_price,low_price,close_price"
    if include_volume:
        header += ",volume"
    rows = [header]
    base_start = 1.1000
    for asset_index, asset in enumerate(assets):
        open_price = base_start + (asset_index * 0.1000)
        for minute in range(12):
            opened_at = f"2026-04-09T08:{minute:02d}:00+00:00"
            high_price = open_price + 0.00065
            low_price = open_price - 0.00015
            close_price = open_price + 0.00050
            row = f"{opened_at},{asset},{instrument_type},60,{open_price:.4f},{high_price:.4f},{low_price:.4f},{close_price:.4f}"
            if include_volume:
                row += f",{10 + minute}"
            rows.append(row)
            open_price += 0.0004
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
