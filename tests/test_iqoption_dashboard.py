from datetime import UTC, datetime
from pathlib import Path

from src.bot.config import load_config
from src.bot.iqoption_adapter import IQOptionCredentials
from src.bot.iqoption_dashboard import IQOptionDashboardService
from src.bot.models import InstrumentType, StrategyVersion, SystemEventRecord, TradeDirection, TradeJournalRecord, TradeResult
from src.bot.trade_journal import TradeJournalRepository


class FakeIQDashboardClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.connected = False
        self.balance_mode = None
        self.update_calls = 0

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
            "AUDCHF-OTC": {"turbo": 0.84, "binary": 0.84},
            "USDJPY-OTC": {"binary": 0.75},
            "USDJPY-OTC": {"binary": 0.75},
            "BTCUSD": {"turbo": 0.9},
        }

    def get_all_ACTIVES_OPCODE(self):
        return {
            "AUDCAD-OTC": 1,
            "USDJPY-OTC": 2,
        }

    def update_ACTIVES_OPCODE(self):
        self.update_calls += 1

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
    assert [pair.asset for pair in snapshot.binary_pairs] == ["AUDCAD-OTC", "USDJPY-OTC", "AUDCHF-OTC"]
    assert [pair.asset for pair in snapshot.recommended_pairs] == ["AUDCAD-OTC", "USDJPY-OTC"]
    assert snapshot.summary_metrics.total_trades == 2
    assert snapshot.summary_metrics.wins == 1
    assert snapshot.summary_metrics.losses == 1
    assert snapshot.selected_assets == ("AUDCAD-OTC", "USDJPY-OTC")
    assert snapshot.selected_asset_metrics.total_trades == 2
    assert snapshot.selected_asset_metrics.wins == 1
    assert len(snapshot.recent_trades) == 2
    assert {trade.asset for trade in snapshot.recent_trades} == {"AUDCAD-OTC", "USDJPY-OTC"}
    assert snapshot.recent_trades[0].strategy_display == "UNKNOWN"
    assert len(snapshot.open_positions) == 1
    assert snapshot.open_positions[0].asset == "AUDCAD-OTC"
    assert snapshot.block_reason == "AUDCAD-OTC already has open order (1/1)"
    assert client.update_calls == 1
    assert snapshot.binary_pairs[0].recommendation_reason is not None
    assert snapshot.binary_pairs[-1].is_supported is False
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

    assert [pair.asset for pair in pairs] == ["AUDCAD-OTC", "USDJPY-OTC", "AUDCHF-OTC"]
    assert all(pair.recommendation_reason is not None for pair in pairs[:2])
    assert pairs[-1].is_supported is False
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
    assert snapshot.selected_assets == ("AUDCAD-OTC", "USDJPY-OTC")
    repository.close()


def test_dashboard_service_builds_strategy_analytics_from_trade_tags(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    _seed_binary_trades(repository)
    repository.replace_trade_tags("binary-win", {"strategy_profiles": "LOW,MEDIUM", "strategy_names": "strict-ema-pullback,balanced-ema-pullback", "strategy_display": "LOW / strict-ema-pullback + MEDIUM / balanced-ema-pullback"})
    repository.replace_trade_tags("binary-loss", {"strategy_profiles": "HIGH", "strategy_names": "aggressive-ema-pullback", "strategy_display": "HIGH / aggressive-ema-pullback"})
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    service.connect()
    analytics = service.build_strategy_analytics_snapshot()

    assert any(row.strategy_display == "LOW / strict-ema-pullback" and row.group_value == "AUDCAD-OTC" and row.trades == 1 for row in analytics.by_asset)
    assert any(row.strategy_display == "MEDIUM / balanced-ema-pullback" and row.group_value == "AUDCAD-OTC" and row.trades == 1 for row in analytics.by_asset)
    assert any(row.strategy_display == "HIGH / aggressive-ema-pullback" and row.group_value == "UNKNOWN" and row.trades == 1 for row in analytics.by_session)
    assert all(not row.strategy_display.startswith("desktop-") for row in analytics.by_asset)
    repository.close()


def test_dashboard_service_formats_history_display_from_profile_and_engine_tags(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    _seed_binary_trades(repository)
    repository.replace_trade_tags(
        "binary-win",
        {
            "strategy_profile": "LOW",
            "strategy_profiles": "LOW",
            "strategy_name": "strict-ema-pullback",
            "strategy_names": "strict-ema-pullback",
        },
    )
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    snapshot = service.load_snapshot(selected_assets=("AUDCAD-OTC",))

    assert any(trade.strategy_display == "LOW / strict-ema-pullback" for trade in snapshot.recent_trades)
    repository.close()


def test_dashboard_service_can_clear_binary_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    _seed_binary_trades(repository)
    repository.save_system_event(
        SystemEventRecord(
            event_id="evt-clear-1",
            occurred_at_utc=datetime(2026, 4, 10, 1, 0, tzinfo=UTC),
            severity="info",
            component="desktop_session",
            event_type="entry_window_wait",
            message="waiting",
            details={"reason": "awaiting_entry_window"},
        )
    )
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    deleted = service.clear_binary_history()
    snapshot = service.load_snapshot(selected_assets=())

    assert deleted == 4
    assert snapshot.summary_metrics.total_trades == 0
    assert len(snapshot.recent_trades) == 0
    assert snapshot.block_reason == "-"
    repository.close()


def test_dashboard_service_filters_assets_missing_from_actives_opcode_map(tmp_path, monkeypatch) -> None:
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

    pairs = service.list_open_binary_pairs()

    assert [pair.asset for pair in pairs] == ["AUDCAD-OTC", "USDJPY-OTC", "AUDCHF-OTC"]
    unsupported_pair = next(pair for pair in pairs if pair.asset == "AUDCHF-OTC")
    assert unsupported_pair.is_supported is False
    repository.close()


def test_dashboard_service_load_snapshot_uses_single_trade_scan(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    repository = _build_repository(tmp_path)
    _seed_binary_trades(repository)

    class CountingRepository:
        def __init__(self, inner_repository):
            self._inner_repository = inner_repository
            self.list_trades_calls = 0

        def list_trades(self, *args, **kwargs):
            self.list_trades_calls += 1
            return self._inner_repository.list_trades(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner_repository, name)

    counting_repository = CountingRepository(repository)
    client = FakeIQDashboardClient("user@example.com", "secret")
    service = IQOptionDashboardService(
        config=config,
        repository=counting_repository,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: client,
    )

    snapshot = service.load_snapshot(selected_assets=("AUDCAD-OTC",))

    assert snapshot.summary_metrics.total_trades == 2
    assert counting_repository.list_trades_calls == 1
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
    repository.upsert_trade(
        TradeJournalRecord(
            trade_id="binary-open",
            signal_id=None,
            strategy_version_id="ui-v1",
            opened_at_utc=opened_at,
            closed_at_utc=None,
            asset="AUDCAD-OTC",
            instrument_type=InstrumentType.BINARY,
            timeframe_sec=60,
            direction=TradeDirection.CALL,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            broker_order_id="open-order-1",
            broker_position_id="open-position-1",
        )
    )