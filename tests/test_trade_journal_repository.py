from pathlib import Path

from datetime import datetime, timedelta

from src.bot.models import (
    InstrumentType,
    SessionLabel,
    SignalEvent,
    StrategyVersion,
    TradeDirection,
    TradeJournalRecord,
    TradeResult,
)
from src.bot.trade_journal import TradeJournalRepository


def test_trade_repository_round_trip(tmp_path) -> None:
    database_path = tmp_path / "trades.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    repository = TradeJournalRepository.from_paths(database_path, schema_path)

    created_at = datetime(2026, 4, 9, 12, 0, 0)
    strategy = StrategyVersion(
        strategy_version_id="v1",
        created_at_utc=created_at,
        strategy_name="demo-strategy",
        parameter_hash="abc123",
        parameters={"cooldown": 60, "min_payout": 0.8},
        created_by="user",
        approval_status="approved",
    )
    signal = SignalEvent(
        signal_id="s1",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        intended_amount=1.0,
        intended_expiry_sec=60,
        entry_reason="breakout",
        session_label=SessionLabel.LONDON,
        indicator_snapshot={"rsi": 62.5},
        market_snapshot={"candle_close": 1.0845},
    )
    trade = TradeJournalRecord(
        trade_id="t1",
        signal_id="s1",
        strategy_version_id="v1",
        opened_at_utc=created_at,
        closed_at_utc=created_at + timedelta(minutes=1),
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        amount=1.0,
        expiry_sec=60,
        account_mode="PRACTICE",
        result=TradeResult.WIN,
        entry_price=1.0845,
        exit_price=1.0851,
        payout_snapshot=0.82,
        profit_loss_abs=0.82,
        profit_loss_pct_risk=0.82,
        close_reason="expiry",
    )

    repository.save_strategy_version(strategy)
    repository.save_signal_event(signal)
    repository.upsert_trade(trade)
    repository.replace_trade_tags("t1", {"regime": "trend", "bucket": "high_payout"})

    loaded_trade = repository.get_trade("t1")
    loaded_tags = repository.get_trade_tags("t1")
    practice_trades = repository.list_trades(account_mode="PRACTICE")

    assert loaded_trade is not None
    assert loaded_trade.trade_id == "t1"
    assert loaded_trade.result == TradeResult.WIN
    assert loaded_trade.instrument_type == InstrumentType.DIGITAL
    assert loaded_trade.profit_loss_abs == 0.82
    assert loaded_tags == {"bucket": "high_payout", "regime": "trend"}
    assert len(practice_trades) == 1

    repository.close()
