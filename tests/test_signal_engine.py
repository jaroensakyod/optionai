from datetime import UTC, datetime

from src.bot.market_data import Candle
from src.bot.models import InstrumentType, TradeDirection
from src.bot.signal_engine import BlitzMomentumSignalEngine, SimpleMomentumSignalEngine


def test_simple_momentum_signal_engine_accepts_aligned_bullish_bodies() -> None:
    engine = SimpleMomentumSignalEngine(confirmation_candles=3, minimum_total_move_pct=0.0001, minimum_body_ratio=0.3)
    candles = [
        _candle(1.1000, 1.1010, 1.0998, 1.1008),
        _candle(1.1008, 1.1018, 1.1006, 1.1016),
        _candle(1.1016, 1.1026, 1.1014, 1.1024),
    ]

    signal = engine.build_signal(
        strategy_version_id="v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.CALL


def test_simple_momentum_signal_engine_rejects_mixed_body_direction() -> None:
    engine = SimpleMomentumSignalEngine(confirmation_candles=3, minimum_total_move_pct=0.0001, minimum_body_ratio=0.3)
    candles = [
        _candle(1.1008, 1.1010, 1.0998, 1.1000),
        _candle(1.1002, 1.1018, 1.1000, 1.1010),
        _candle(1.1010, 1.1026, 1.1009, 1.1020),
    ]

    signal = engine.build_signal(
        strategy_version_id="v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_blitz_momentum_signal_engine_accepts_two_strong_bearish_candles() -> None:
    engine = BlitzMomentumSignalEngine(
        confirmation_candles=2,
        minimum_total_move_pct=0.0002,
        minimum_body_ratio_call=0.55,
        minimum_body_ratio_put=0.45,
    )
    candles = [
        _candle(1.1784, 1.1785, 1.1779, 1.1780),
        _candle(1.1780, 1.1781, 1.1773, 1.1774),
    ]

    signal = engine.build_signal(
        strategy_version_id="blitz-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=30,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.PUT
    assert signal.entry_reason == "two_candle_blitz"


def test_blitz_momentum_signal_engine_rejects_weak_bodies() -> None:
    engine = BlitzMomentumSignalEngine(
        confirmation_candles=2,
        minimum_total_move_pct=0.0002,
        minimum_body_ratio_call=0.55,
        minimum_body_ratio_put=0.45,
    )
    candles = [
        _candle(1.1784, 1.1787, 1.1781, 1.1783),
        _candle(1.1783, 1.1785, 1.1779, 1.1782),
    ]

    signal = engine.build_signal(
        strategy_version_id="blitz-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=30,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_blitz_momentum_signal_engine_rejects_call_below_call_specific_body_ratio() -> None:
    engine = BlitzMomentumSignalEngine(
        confirmation_candles=2,
        minimum_total_move_pct=0.00012,
        minimum_body_ratio_call=0.55,
        minimum_body_ratio_put=0.45,
    )
    candles = [
        _candle(1.1780, 1.1784, 1.1779, 1.1782),
        _candle(1.1782, 1.1786, 1.1781, 1.1784),
    ]

    signal = engine.build_signal(
        strategy_version_id="blitz-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=30,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_blitz_momentum_signal_engine_accepts_put_with_relaxed_put_body_ratio() -> None:
    engine = BlitzMomentumSignalEngine(
        confirmation_candles=2,
        minimum_total_move_pct=0.00012,
        minimum_body_ratio_call=0.55,
        minimum_body_ratio_put=0.45,
    )
    candles = [
        _candle(1.1786, 1.1787, 1.1781, 1.1783),
        _candle(1.1783, 1.1784, 1.1778, 1.1780),
    ]

    signal = engine.build_signal(
        strategy_version_id="blitz-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=30,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.PUT


def _candle(open_price: float, high_price: float, low_price: float, close_price: float) -> Candle:
    return Candle(
        opened_at_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=None,
    )