import pytest

from datetime import datetime, timedelta

from src.bot.models import InstrumentType, TradeDirection, TradeJournalRecord, TradeResult
from src.bot.stats_service import build_metric_snapshot


def test_build_metric_snapshot_counts_closed_trade_outcomes() -> None:
    opened_at = datetime(2026, 4, 9, 0, 0, 0)
    records = [
        TradeJournalRecord(
            trade_id="t1",
            signal_id="s1",
            strategy_version_id="v1",
            opened_at_utc=opened_at,
            closed_at_utc=opened_at + timedelta(minutes=1),
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            direction=TradeDirection.CALL,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.WIN,
            profit_loss_abs=0.8,
        ),
        TradeJournalRecord(
            trade_id="t2",
            signal_id="s2",
            strategy_version_id="v1",
            opened_at_utc=opened_at + timedelta(minutes=2),
            closed_at_utc=opened_at + timedelta(minutes=3),
            asset="EURUSD",
            instrument_type=InstrumentType.DIGITAL,
            timeframe_sec=60,
            direction=TradeDirection.PUT,
            amount=1.0,
            expiry_sec=60,
            account_mode="PRACTICE",
            result=TradeResult.LOSS,
            profit_loss_abs=-1.0,
        ),
    ]

    snapshot = build_metric_snapshot(records)

    assert snapshot.total_trades == 2
    assert snapshot.wins == 1
    assert snapshot.losses == 1
    assert snapshot.net_pnl == pytest.approx(-0.2)

