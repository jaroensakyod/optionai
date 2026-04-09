import pytest

from datetime import UTC, datetime
from pathlib import Path

from src.bot.broker_adapter import PracticeBrokerAdapter
from src.bot.config import load_config
from src.bot.journal_service import JournalService
from src.bot.metrics_queries import MetricsQueryService
from src.bot.models import InstrumentType, SessionLabel, SignalEvent, StrategyVersion, TradeDirection, TradeResult
from src.bot.trade_journal import TradeJournalRepository


def test_practice_broker_adapter_and_metrics_queries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    database_path = tmp_path / "trades.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    repository = TradeJournalRepository.from_paths(database_path, schema_path)
    journal_service = JournalService(repository)
    metrics_service = MetricsQueryService(repository)
    adapter = PracticeBrokerAdapter(config, repository, journal_service)

    created_at = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
    strategy = StrategyVersion(
        strategy_version_id="v1",
        created_at_utc=created_at,
        strategy_name="demo-strategy",
        parameter_hash="abc123",
        parameters={"cooldown": 60, "min_payout": 0.8},
        created_by="user",
        approval_status="approved",
    )
    repository.save_strategy_version(strategy)

    signal_win = SignalEvent(
        signal_id="s-win",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        intended_amount=2.0,
        intended_expiry_sec=60,
        entry_reason="breakout",
        session_label=SessionLabel.LONDON,
    )
    signal_loss = SignalEvent(
        signal_id="s-loss",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="GBPUSD",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        direction=TradeDirection.PUT,
        intended_amount=1.0,
        intended_expiry_sec=60,
        entry_reason="reversal",
        session_label=SessionLabel.ASIA,
    )
    signal_rejected = SignalEvent(
        signal_id="s-rejected",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        intended_amount=1.0,
        intended_expiry_sec=60,
        entry_reason="low-liquidity-check",
        session_label=SessionLabel.OFF_SESSION,
    )

    trade_win = adapter.submit_order(
        signal_event=signal_win,
        strategy_version_id="v1",
        payout_snapshot=0.8,
        entry_price=1.0845,
        tags={"regime": "trend"},
    )
    trade_loss = adapter.submit_order(
        signal_event=signal_loss,
        strategy_version_id="v1",
        payout_snapshot=0.75,
        entry_price=1.2550,
        tags={"regime": "range"},
    )
    rejected_trade = adapter.reject_order(
        signal_event=signal_rejected,
        strategy_version_id="v1",
        error_code="MARKET_CLOSED",
        error_message="market unavailable",
        tags={"regime": "off_hours"},
    )

    closed_win = adapter.resolve_trade(trade_id=trade_win.trade_id, result=TradeResult.WIN, exit_price=1.0851)
    closed_loss = adapter.resolve_trade(trade_id=trade_loss.trade_id, result=TradeResult.LOSS, exit_price=1.2540)

    summary = metrics_service.summary(account_mode="PRACTICE")
    by_asset = {item.group_key: item.metrics for item in metrics_service.by_asset(account_mode="PRACTICE")}
    by_session = {item.group_key: item.metrics for item in metrics_service.by_session(account_mode="PRACTICE")}
    orders_for_win = repository.list_broker_orders(trade_win.trade_id)

    assert closed_win.profit_loss_abs == pytest.approx(1.6)
    assert closed_loss.profit_loss_abs == pytest.approx(-1.0)
    assert rejected_trade.result == TradeResult.REJECTED
    assert summary.total_trades == 2
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.net_pnl == pytest.approx(0.6)
    assert by_asset["EURUSD"].wins == 1
    assert by_asset["GBPUSD"].losses == 1
    assert by_session["london"].wins == 1
    assert by_session["asia"].losses == 1
    assert len(orders_for_win) == 1
    assert orders_for_win[0].submission_status == "submitted"

    repository.close()
