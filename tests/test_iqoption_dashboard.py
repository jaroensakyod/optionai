from datetime import UTC, datetime
from pathlib import Path

from src.bot.config import load_config
from src.bot.iqoption_adapter import IQOptionCredentials
from src.bot.iqoption_dashboard import IQOptionDashboardService
from src.bot.models import InstrumentType, StrategyVersion, TradeDirection, TradeJournalRecord, TradeResult
from src.bot.trade_journal import TradeJournalRepository


class FakeIQDashboardClient:
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
        return 150.25

    def get_all_profit(self):
        return {
            "EURUSD": {"turbo": 0.82, "binary": 0.8},
            "AUDCAD-OTC": {"turbo": 0.84, "binary": 0.84},
            "USDJPY-OTC": {"binary": 0.75},
            "USDJPY-OTC": {"binary": 0.75},
            "BTCUSD": {"turbo": 0.9},
        }

    def get_all_open_time(self):
        return {
            "binary": {
                "EURUSD": {"open": True},
                "USDJPY-OTC": {"open": True},
                "BTCUSD": {"open": True},
            },
            "turbo": {
                "GBPUSD": {"open": True},
                "EURJPY": {"open": False},
            },
        }


class BrokenOpenTimeClient(FakeIQDashboardClient):
    def get_all_open_time(self):
        raise KeyError("underlying")


def test_dashboard_service_loads_open_binary_pairs_and_binary_metrics(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    _seed_binary_trades(repository)
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    snapshot = service.load_snapshot(selected_assets=("AUDCAD-OTC", "USDJPY-OTC"))

    assert client.balance_mode == "PRACTICE"
    assert snapshot.balance == 150.25
    assert snapshot.market_status == "OPEN"
    assert [pair.asset for pair in snapshot.binary_pairs] == ["AUDCAD-OTC", "USDJPY-OTC"]
    assert [pair.asset for pair in snapshot.recommended_pairs] == ["AUDCAD-OTC", "USDJPY-OTC"]
    assert snapshot.summary_metrics.total_trades == 2
    assert snapshot.summary_metrics.wins == 1
    assert snapshot.summary_metrics.losses == 1
    assert snapshot.selected_assets == ("AUDCAD-OTC", "USDJPY-OTC")
    assert snapshot.selected_asset_metrics.total_trades == 2
    assert snapshot.selected_asset_metrics.wins == 1
    assert len(snapshot.recent_trades) == 2
    assert {trade.asset for trade in snapshot.recent_trades} == {"AUDCAD-OTC", "USDJPY-OTC"}
    assert snapshot.binary_pairs[0].recommendation_reason is not None
    assert snapshot.binary_pairs[0].opportunity_score_pct > snapshot.binary_pairs[1].opportunity_score_pct
    assert 0.0 <= snapshot.binary_pairs[0].opportunity_score_pct <= 100.0
    assert snapshot.binary_pairs[0].opportunity_band in {"HIGH", "MEDIUM", "LOW"}
    assert snapshot.binary_pairs[0].opportunity_updated_at_utc
    repository.close()


def test_dashboard_service_falls_back_to_profit_listing_when_open_time_breaks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    client = BrokenOpenTimeClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    pairs = service.list_open_binary_pairs()

    assert [pair.asset for pair in pairs] == ["AUDCAD-OTC", "USDJPY-OTC"]
    assert all(pair.recommendation_reason is not None for pair in pairs)
    assert all(0.0 <= pair.opportunity_score_pct <= 100.0 for pair in pairs)
    assert all(pair.opportunity_band in {"HIGH", "MEDIUM", "LOW"} for pair in pairs)
    assert all(pair.opportunity_updated_at_utc for pair in pairs)
    repository.close()


def test_dashboard_service_can_switch_login_account_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    service.update_account_mode("REAL")
    service.connect()
    snapshot = service.load_snapshot(selected_assets=())

    assert client.balance_mode == "REAL"
    assert snapshot.account_mode == "REAL"
    repository.close()


def _build_repository(tmp_path: Path) -> TradeJournalRepository:
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    return TradeJournalRepository.from_paths(tmp_path / "trades.db", schema_path)


def _seed_binary_trades(repository: TradeJournalRepository) -> None:
    opened_at = datetime(2026, 4, 9, 12, 0, tzinfo=UTC)
    repository.save_strategy_version(
        StrategyVersion(
            strategy_version_id="ui-v1",
            created_at_utc=datetime.now(UTC),
            strategy_name="dashboard-ui",
            parameter_hash="dashboard-ui-v1",
            parameters={"surface": "desktop"},
            created_by="test",
            approval_status="approved",
        )
    )
    repository.upsert_trade(
        TradeJournalRecord(
            trade_id="binary-win",
            signal_id=None,
            strategy_version_id="ui-v1",
            opened_at_utc=opened_at,
            closed_at_utc=opened_at,
            asset="AUDCAD-OTC",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            direction=TradeDirection.CALL,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.WIN,
            payout_snapshot=0.84,
            profit_loss_abs=0.84,
            profit_loss_pct_risk=0.84,
        )
    )
    repository.upsert_trade(
        TradeJournalRecord(
            trade_id="binary-loss",
            signal_id=None,
            strategy_version_id="ui-v1",
            opened_at_utc=opened_at,
            closed_at_utc=opened_at,
            asset="USDJPY-OTC",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            direction=TradeDirection.PUT,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.LOSS,
            payout_snapshot=0.75,
            profit_loss_abs=-1.0,
            profit_loss_pct_risk=-1.0,
        )
    )
    repository.upsert_trade(
        TradeJournalRecord(
            trade_id="binary-ignored-non-otc",
            signal_id=None,
            strategy_version_id="ui-v1",
            opened_at_utc=opened_at,
            closed_at_utc=opened_at,
            asset="EURUSD",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            direction=TradeDirection.CALL,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.WIN,
            payout_snapshot=0.8,
            profit_loss_abs=0.8,
            profit_loss_pct_risk=0.8,
        )
    )