from datetime import UTC, datetime

from src.bot.market_data import Candle
from src.bot.models import InstrumentType, TradeDirection
from src.bot.signal_engine import BlitzMomentumSignalEngine, CompositeSignalEngine, RelaxedMomentumSignalEngine, SimpleMomentumSignalEngine, TrendFilterSettings, build_composite_signal_engine, build_signal_engine


def test_simple_momentum_signal_engine_accepts_aligned_bullish_bodies() -> None:
    engine = SimpleMomentumSignalEngine(confirmation_candles=3, minimum_total_move_pct=0.0001, minimum_body_ratio=0.3)
    candles = _bullish_sequence(12)

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
    candles = _bullish_sequence(12)
    candles[-3] = _candle(1.1038, 1.1042, 1.1030, 1.1032)

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
    candles = _bearish_sequence(12, start=1.1820, step=0.0005)

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
    candles = _bearish_sequence(12, start=1.1820, step=0.0005)
    candles[-2] = _candle(1.1765, 1.1769, 1.1761, 1.1764)
    candles[-1] = _candle(1.1764, 1.1768, 1.1760, 1.1763)

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
    candles = _bullish_sequence(12, start=1.1780, step=0.0002)
    candles[-2] = _candle(1.1800, 1.1804, 1.1799, 1.1802)
    candles[-1] = _candle(1.1802, 1.1806, 1.1801, 1.1804)

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
    candles = _bearish_sequence(12, start=1.1820, step=0.0004)

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


def test_build_signal_engine_maps_profiles_to_expected_engines() -> None:
    assert build_signal_engine("LOW").strategy_name == "simple-momentum"
    assert build_signal_engine("MEDIUM").strategy_name == "blitz-momentum"
    assert build_signal_engine("HIGH").strategy_name == "relaxed-momentum"


def test_relaxed_profile_accepts_setup_that_low_profile_filters_out() -> None:
    low_engine = build_signal_engine("LOW")
    high_engine = RelaxedMomentumSignalEngine(
        confirmation_candles=2,
        minimum_total_move_pct=0.00008,
        minimum_body_ratio_call=0.3,
        minimum_body_ratio_put=0.28,
        trend_filter=TrendFilterSettings(
            ema_period=4,
            adx_period=4,
            adx_threshold=12.0,
            atr_period=4,
            min_atr_pct=0.00005,
            max_atr_pct=0.003,
            sr_lookback=4,
            min_sr_distance_pct=0.00005,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=3,
        ),
    )
    candles = _bullish_sequence(12, start=1.1000, step=0.00015, body_size=0.00018)

    low_signal = low_engine.build_signal(
        strategy_version_id="low-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )
    high_signal = high_engine.build_signal(
        strategy_version_id="high-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert low_signal is None
    assert high_signal is not None
    assert high_signal.direction == TradeDirection.CALL


def test_composite_signal_engine_merges_matching_profiles_into_one_signal() -> None:
    engine = build_composite_signal_engine(("LOW", "HIGH"))
    candles = _bullish_sequence(12)

    signal = engine.build_signal(
        strategy_version_id="combo-v1",
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
    assert signal.is_filtered_out is False
    assert signal.indicator_snapshot["strategy_profiles"] == ["LOW", "HIGH"]


def test_composite_signal_engine_keeps_only_actual_contributing_profile() -> None:
    engine = CompositeSignalEngine(
        engines=(
            SimpleMomentumSignalEngine(minimum_total_move_pct=0.01),
            BlitzMomentumSignalEngine(minimum_body_ratio_call=0.55, minimum_body_ratio_put=0.45),
        ),
        strategy_profiles=("LOW", "MEDIUM"),
    )
    candles = _bearish_sequence(12, start=1.1820, step=0.0004)

    signal = engine.build_signal(
        strategy_version_id="combo-v3",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=30,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is False
    assert signal.indicator_snapshot["strategy_profiles"] == ["MEDIUM"]


def test_composite_signal_engine_filters_conflicting_profiles() -> None:
    class FakeEngine:
        def __init__(self, strategy_name: str, direction: TradeDirection):
            self.strategy_name = strategy_name
            self.required_candles = 1
            self.direction = direction

        def describe_parameters(self) -> dict[str, str]:
            return {"direction": self.direction.value}

        def build_signal(self, **kwargs):
            return kwargs["candles"] and type("Signal", (), {})

    class FakeCallEngine(FakeEngine):
        def build_signal(self, **kwargs):
            return SimpleMomentumSignalEngine().build_signal(
                strategy_version_id=kwargs["strategy_version_id"],
                asset=kwargs["asset"],
                instrument_type=kwargs["instrument_type"],
                timeframe_sec=kwargs["timeframe_sec"],
                stake_amount=kwargs["stake_amount"],
                expiry_sec=kwargs["expiry_sec"],
                candles=_bullish_sequence(12),
                signal_time_utc=kwargs["signal_time_utc"],
            )

    class FakePutEngine(FakeEngine):
        def build_signal(self, **kwargs):
            return BlitzMomentumSignalEngine().build_signal(
                strategy_version_id=kwargs["strategy_version_id"],
                asset=kwargs["asset"],
                instrument_type=kwargs["instrument_type"],
                timeframe_sec=kwargs["timeframe_sec"],
                stake_amount=kwargs["stake_amount"],
                expiry_sec=kwargs["expiry_sec"],
                candles=_bearish_sequence(12, start=1.1820, step=0.0005),
                signal_time_utc=kwargs["signal_time_utc"],
            )

    engine = CompositeSignalEngine(
        engines=(FakeCallEngine("call-engine", TradeDirection.CALL), FakePutEngine("put-engine", TradeDirection.PUT)),
        strategy_profiles=("LOW", "MEDIUM"),
    )
    candles = _bullish_sequence(12)

    signal = engine.build_signal(
        strategy_version_id="combo-v2",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is True
    assert signal.filter_reason == "conflicting_strategy_signals"


def test_signal_engine_rejects_when_price_is_below_ema_trend_filter() -> None:
    engine = RelaxedMomentumSignalEngine(
        trend_filter=TrendFilterSettings(
            ema_period=4,
            adx_period=4,
            adx_threshold=10.0,
            atr_period=4,
            min_atr_pct=0.00001,
            max_atr_pct=0.01,
            sr_lookback=4,
            min_sr_distance_pct=0.00001,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=2,
        )
    )
    candles = _bullish_sequence(12, start=1.2000, step=0.00005, body_size=0.0002)
    candles[-1] = _candle(1.2011, 1.2012, 1.2002, 1.2004)

    signal = engine.build_signal(
        strategy_version_id="ema-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_adx_is_below_threshold() -> None:
    engine = RelaxedMomentumSignalEngine(
        trend_filter=TrendFilterSettings(
            ema_period=3,
            adx_period=3,
            adx_threshold=40.0,
            atr_period=3,
            min_atr_pct=0.00001,
            max_atr_pct=0.01,
            sr_lookback=3,
            min_sr_distance_pct=0.00001,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=2,
        )
    )
    candles = _choppy_sequence(10)
    candles[-2] = _candle(1.2002, 1.2007, 1.2000, 1.2005)
    candles[-1] = _candle(1.2005, 1.2010, 1.2003, 1.2008)

    signal = engine.build_signal(
        strategy_version_id="adx-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_atr_regime_is_too_low() -> None:
    engine = RelaxedMomentumSignalEngine(
        trend_filter=TrendFilterSettings(
            ema_period=3,
            adx_period=3,
            adx_threshold=10.0,
            atr_period=3,
            min_atr_pct=0.001,
            max_atr_pct=0.01,
            sr_lookback=3,
            min_sr_distance_pct=0.00001,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=2,
        )
    )
    candles = _bullish_sequence(10, start=1.3000, step=0.00005, body_size=0.00005, wick_size=0.00003)

    signal = engine.build_signal(
        strategy_version_id="atr-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_resistance_is_too_close() -> None:
    engine = RelaxedMomentumSignalEngine(
        trend_filter=TrendFilterSettings(
            ema_period=3,
            adx_period=3,
            adx_threshold=10.0,
            atr_period=3,
            min_atr_pct=0.00001,
            max_atr_pct=0.01,
            sr_lookback=4,
            min_sr_distance_pct=0.001,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=2,
        )
    )
    candles = _bullish_sequence(10, start=1.1000, step=0.0002)
    candles[-5] = _candle(1.1010, 1.1030, 1.1008, 1.1024)
    candles[-1] = _candle(1.1022, 1.1027, 1.1020, 1.1026)

    signal = engine.build_signal(
        strategy_version_id="sr-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_higher_timeframe_is_not_aligned() -> None:
    engine = RelaxedMomentumSignalEngine(
        trend_filter=TrendFilterSettings(
            ema_period=3,
            adx_period=3,
            adx_threshold=10.0,
            atr_period=3,
            min_atr_pct=0.00001,
            max_atr_pct=0.01,
            sr_lookback=3,
            min_sr_distance_pct=0.00001,
            alignment_timeframe_multiplier=2,
            alignment_ema_period=2,
        )
    )
    candles = _bullish_sequence(12, start=1.2000, step=0.00015)
    candles[8] = _candle(1.2012, 1.2014, 1.2000, 1.2001)
    candles[9] = _candle(1.2001, 1.2003, 1.1992, 1.1994)

    signal = engine.build_signal(
        strategy_version_id="mtf-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=candles,
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


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


def _bullish_sequence(
    count: int,
    *,
    start: float = 1.1000,
    step: float = 0.0004,
    body_size: float = 0.0005,
    wick_size: float = 0.00015,
) -> list[Candle]:
    candles: list[Candle] = []
    open_price = start
    for _ in range(count):
        close_price = open_price + body_size
        candles.append(_candle(open_price, close_price + wick_size, open_price - wick_size, close_price))
        open_price += step
    return candles


def _bearish_sequence(
    count: int,
    *,
    start: float = 1.1800,
    step: float = 0.0004,
    body_size: float = 0.0005,
    wick_size: float = 0.00015,
) -> list[Candle]:
    candles: list[Candle] = []
    open_price = start
    for _ in range(count):
        close_price = open_price - body_size
        candles.append(_candle(open_price, open_price + wick_size, close_price - wick_size, close_price))
        open_price -= step
    return candles


def _choppy_sequence(count: int, *, start: float = 1.2000) -> list[Candle]:
    candles: list[Candle] = []
    current = start
    for index in range(count):
        if index % 2 == 0:
            next_close = current + 0.00012
            candles.append(_candle(current, current + 0.00022, current - 0.00018, next_close))
        else:
            next_close = current - 0.00010
            candles.append(_candle(current, current + 0.00018, current - 0.00022, next_close))
        current = next_close
    return candles