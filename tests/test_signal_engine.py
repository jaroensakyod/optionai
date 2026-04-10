from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.bot.market_data import Candle
from src.bot.models import InstrumentType, TradeDirection
from src.bot.signal_engine import CompositeSignalEngine, MeanReversionSignalEngine, SimpleMomentumSignalEngine, TrendPullbackSignalEngine, build_selected_signal_engine, build_signal_engine, build_strategy_engine, default_mean_reversion_settings, default_trend_filter_settings, default_trend_pullback_settings


def test_trend_pullback_signal_engine_accepts_bullish_ema_support_bounce() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.45,
        )
    )

    signal = engine.build_signal(
        strategy_version_id="v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.CALL
    assert signal.entry_reason == "ema_pullback_confirmation"
    assert "fast_ema_support" in signal.indicator_snapshot["entry_triggers"]


def test_trend_pullback_signal_engine_accepts_bearish_ema_resistance_rejection() -> None:
    engine = TrendPullbackSignalEngine(
        strategy_profile="HIGH",
        strategy_id="trend-pullback.high",
        pullback_settings=replace(
            default_trend_pullback_settings("HIGH"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.35,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_put_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.PUT
    assert "bearish_confirmation_candle" in signal.indicator_snapshot["entry_triggers"]


def test_trend_pullback_signal_engine_requires_confirmation_candle() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.62,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="tp-no-confirm",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(weak_confirmation=True),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_trend_pullback_signal_engine_high_profile_accepts_weaker_confirmation_than_low_profile() -> None:
    low_engine = TrendPullbackSignalEngine(
        strategy_profile="LOW",
        strategy_id="trend-pullback.low",
        pullback_settings=replace(
            default_trend_pullback_settings("LOW"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.62,
        ),
    )
    high_engine = TrendPullbackSignalEngine(
        strategy_profile="HIGH",
        strategy_id="trend-pullback.high",
        pullback_settings=replace(
            default_trend_pullback_settings("HIGH"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.34,
        ),
    )

    low_signal = low_engine.build_signal(
        strategy_version_id="tp-low",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(weak_confirmation=True),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )
    high_signal = high_engine.build_signal(
        strategy_version_id="tp-high",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(weak_confirmation=True),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert low_signal is None
    assert high_signal is not None
    assert high_signal.direction == TradeDirection.CALL


def test_build_signal_engine_maps_profiles_to_expected_engines() -> None:
    assert build_signal_engine("LOW").strategy_name == "simple-momentum"
    assert build_signal_engine("MEDIUM").strategy_name == "blitz-momentum"
    assert build_signal_engine("HIGH").strategy_name == "relaxed-momentum"


def test_build_strategy_engine_maps_strategy_ids_to_expected_engines() -> None:
    assert build_strategy_engine("momentum.low").strategy_name == "simple-momentum"
    assert build_strategy_engine("momentum.medium").strategy_name == "blitz-momentum"
    assert build_strategy_engine("momentum.high").strategy_name == "relaxed-momentum"
    assert build_strategy_engine("trend-pullback.low").strategy_name == "strict-ema-pullback"
    assert build_strategy_engine("trend-pullback.medium").strategy_name == "balanced-ema-pullback"
    assert build_strategy_engine("trend-pullback.high").strategy_name == "aggressive-ema-pullback"
    assert build_strategy_engine("mean-reversion.medium").strategy_name == "bollinger-rsi-reversion"


def test_composite_signal_engine_merges_matching_profiles_into_one_signal() -> None:
    engine = build_selected_signal_engine(("trend-pullback.low", "trend-pullback.high"))

    signal = engine.build_signal(
        strategy_version_id="combo-v1",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.direction == TradeDirection.CALL
    assert signal.is_filtered_out is False
    assert signal.indicator_snapshot["strategy_ids"] == ["trend-pullback.low", "trend-pullback.high"]
    assert signal.indicator_snapshot["strategy_profiles"] == ["LOW", "HIGH"]


def test_composite_signal_engine_keeps_only_actual_contributing_profile() -> None:
    engine = CompositeSignalEngine(
        engines=(
            TrendPullbackSignalEngine(
                strategy_profile="LOW",
                strategy_id="trend-pullback.low",
                pullback_settings=replace(
                    default_trend_pullback_settings("LOW"),
                    min_adx=10.0,
                    min_confirmation_body_ratio=0.62,
                ),
            ),
            TrendPullbackSignalEngine(
                strategy_profile="MEDIUM",
                strategy_id="trend-pullback.medium",
                pullback_settings=replace(
                    default_trend_pullback_settings("MEDIUM"),
                    min_adx=10.0,
                    min_confirmation_body_ratio=0.34,
                ),
            ),
        ),
        strategy_profiles=("LOW", "MEDIUM"),
        strategy_ids=("trend-pullback.low", "trend-pullback.medium"),
    )

    signal = engine.build_signal(
        strategy_version_id="combo-v3",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(weak_confirmation=True),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is False
    assert signal.indicator_snapshot["strategy_ids"] == ["trend-pullback.medium"]
    assert signal.indicator_snapshot["strategy_profiles"] == ["MEDIUM"]


def test_composite_signal_engine_filters_conflicting_profiles() -> None:
    class FakeEngine:
        def __init__(self, strategy_name: str, direction: TradeDirection):
            self.strategy_name = strategy_name
            self.required_candles = 1
            self._direction = direction

        def describe_parameters(self) -> dict[str, str]:
            return {"direction": self._direction.value}

        def build_signal(self, **kwargs):
            return kwargs["candles"] and type("Signal", (), {})

    class FakeCallEngine(FakeEngine):
        def build_signal(self, **kwargs):
            return TrendPullbackSignalEngine(
                pullback_settings=replace(
                    default_trend_pullback_settings("MEDIUM"),
                    min_adx=10.0,
                    min_confirmation_body_ratio=0.45,
                )
            ).build_signal(
                strategy_version_id=kwargs["strategy_version_id"],
                asset=kwargs["asset"],
                instrument_type=kwargs["instrument_type"],
                timeframe_sec=kwargs["timeframe_sec"],
                stake_amount=kwargs["stake_amount"],
                expiry_sec=kwargs["expiry_sec"],
                candles=_trend_pullback_call_setup(),
                signal_time_utc=kwargs["signal_time_utc"],
            )

    class FakePutEngine(FakeEngine):
        def build_signal(self, **kwargs):
            return TrendPullbackSignalEngine(
                strategy_profile="HIGH",
                strategy_id="trend-pullback.high",
                pullback_settings=replace(
                    default_trend_pullback_settings("HIGH"),
                    min_adx=10.0,
                    min_confirmation_body_ratio=0.35,
                ),
            ).build_signal(
                strategy_version_id=kwargs["strategy_version_id"],
                asset=kwargs["asset"],
                instrument_type=kwargs["instrument_type"],
                timeframe_sec=kwargs["timeframe_sec"],
                stake_amount=kwargs["stake_amount"],
                expiry_sec=kwargs["expiry_sec"],
                candles=_trend_pullback_put_setup(),
                signal_time_utc=kwargs["signal_time_utc"],
            )

    engine = CompositeSignalEngine(
        engines=(FakeCallEngine("call-engine", TradeDirection.CALL), FakePutEngine("put-engine", TradeDirection.PUT)),
        strategy_profiles=("LOW", "MEDIUM"),
        strategy_ids=("trend-pullback.low", "trend-pullback.medium"),
    )

    signal = engine.build_signal(
        strategy_version_id="combo-v2",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is True
    assert signal.filter_reason == "conflicting_strategy_signals"


def test_momentum_engine_diagnoses_pattern_failures() -> None:
    engine = SimpleMomentumSignalEngine()

    reason = engine.diagnose_no_signal(
        strategy_version_id="mom-pattern",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_choppy_sequence(engine.required_candles),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert reason == "pattern_not_aligned"


def test_momentum_engine_diagnoses_adx_filter_failures() -> None:
    engine = SimpleMomentumSignalEngine(
        trend_filter=replace(default_trend_filter_settings("LOW"), adx_threshold=200.0)
    )

    reason = engine.diagnose_no_signal(
        strategy_version_id="mom-adx",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_bullish_sequence(engine.required_candles),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert reason == "adx_below_threshold"


def test_composite_momentum_engine_reports_profile_specific_no_signal_reasons() -> None:
    engine = build_selected_signal_engine(("momentum.low", "momentum.medium", "momentum.high"))

    reason = engine.diagnose_no_signal(
        strategy_version_id="mom-composite",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_choppy_sequence(engine.required_candles),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert reason == "pattern_not_aligned"


def test_mean_reversion_signal_engine_accepts_range_reversal_call() -> None:
    settings = replace(
        default_mean_reversion_settings("MEDIUM"),
        max_adx=100.0,
        max_ema_slope_pct=1.0,
        min_body_recovery_ratio=0.03,
        stochastic_oversold=25.0,
        rsi_oversold=40.0,
    )
    engine = MeanReversionSignalEngine(reversion_settings=settings)

    signal = engine.build_signal(
        strategy_version_id="mr-call",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_mean_reversion_call_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 29, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is False
    assert signal.direction == TradeDirection.CALL
    assert signal.entry_reason == "bollinger_rsi_reversion"
    assert signal.indicator_snapshot["confirmation_mode"] == "any"
    assert signal.indicator_snapshot["entry_triggers"]
    assert "stochastic_reversal" in signal.indicator_snapshot["entry_triggers"]


def test_mean_reversion_signal_engine_rejects_trending_regime() -> None:
    settings = replace(
        default_mean_reversion_settings("MEDIUM"),
        max_adx=10.0,
        max_ema_slope_pct=1.0,
        min_body_recovery_ratio=0.03,
        stochastic_oversold=25.0,
        rsi_oversold=40.0,
    )
    engine = MeanReversionSignalEngine(reversion_settings=settings)

    signal = engine.build_signal(
        strategy_version_id="mr-trend-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_mean_reversion_call_setup(),
        signal_time_utc=datetime(2026, 4, 9, 7, 29, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is True
    assert signal.filter_reason == "trend_too_strong_for_reversion"


def test_mean_reversion_signal_engine_can_enter_when_any_confirmation_matches() -> None:
    settings = replace(
        default_mean_reversion_settings("MEDIUM"),
        max_adx=100.0,
        max_ema_slope_pct=1.0,
        min_body_recovery_ratio=0.03,
        stochastic_oversold=25.0,
        rsi_oversold=40.0,
    )
    engine = MeanReversionSignalEngine(reversion_settings=settings)

    signal = engine.build_signal(
        strategy_version_id="mr-any-confirmation",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_mean_reversion_call_setup(confirm_rejection=False),
        signal_time_utc=datetime(2026, 4, 9, 7, 29, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is False
    assert "rejection_candle" not in signal.indicator_snapshot["entry_triggers"]
    assert signal.indicator_snapshot["entry_triggers"]


def test_mean_reversion_signal_engine_filters_when_all_confirmations_miss() -> None:
    settings = replace(
        default_mean_reversion_settings("MEDIUM"),
        max_adx=100.0,
        max_ema_slope_pct=1.0,
        min_body_recovery_ratio=0.03,
        stochastic_oversold=5.0,
        rsi_oversold=5.0,
    )
    engine = MeanReversionSignalEngine(reversion_settings=settings)

    signal = engine.build_signal(
        strategy_version_id="mr-no-confirmation",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_mean_reversion_call_setup(confirm_rejection=False),
        signal_time_utc=datetime(2026, 4, 9, 7, 29, tzinfo=UTC),
    )

    assert signal is not None
    assert signal.is_filtered_out is True
    assert signal.filter_reason == "reversion_confirmation_missing"
    assert signal.indicator_snapshot["entry_triggers"] == []


def test_signal_engine_rejects_when_price_is_below_ema_trend_filter() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=10.0,
            min_confirmation_body_ratio=0.45,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="ema-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(close_back_below_fast_ema=True),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_adx_is_below_threshold() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=40.0,
            min_confirmation_body_ratio=0.45,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="adx-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_choppy_sequence(24),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_atr_regime_is_too_low() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=10.0,
            min_atr_pct=0.001,
            min_confirmation_body_ratio=0.45,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="atr-filter",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_bullish_sequence(24, start=1.3000, step=0.00003, body_size=0.00003, wick_size=0.00002),
        signal_time_utc=datetime(2026, 4, 9, 7, 0, tzinfo=UTC),
    )

    assert signal is None


def test_signal_engine_rejects_when_slow_ema_support_breaks() -> None:
    engine = TrendPullbackSignalEngine(
        pullback_settings=replace(
            default_trend_pullback_settings("MEDIUM"),
            min_adx=10.0,
            max_slow_ema_breach_pct=0.0,
            min_confirmation_body_ratio=0.45,
        ),
    )

    signal = engine.build_signal(
        strategy_version_id="slow-ema-break",
        asset="EURUSD-OTC",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        stake_amount=1.0,
        expiry_sec=60,
        candles=_trend_pullback_call_setup(break_slow_ema_support=True),
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


def _mean_reversion_call_setup(*, confirm_rejection: bool = True) -> list[Candle]:
    start = datetime(2026, 4, 9, 7, 0, tzinfo=UTC)
    candles: list[Candle] = []
    base = 1.2000
    for index in range(24):
        drift = ((index % 4) - 1.5) * 0.00003
        open_price = base + drift
        close_price = base - (drift / 2)
        candles.append(
            Candle(
                opened_at_utc=start + timedelta(minutes=index),
                asset="EURUSD-OTC",
                instrument_type=InstrumentType.BINARY,
                timeframe_sec=60,
                open_price=open_price,
                high_price=max(open_price, close_price) + 0.00008,
                low_price=min(open_price, close_price) - 0.00008,
                close_price=close_price,
                volume=None,
            )
        )

    reversal_tail = [
        (1.1999, 1.2000, 1.1994, 1.1995),
        (1.1995, 1.1996, 1.1989, 1.1990),
        (1.1990, 1.1991, 1.1984, 1.1986),
        (1.1986, 1.1987, 1.1980, 1.1982),
        (1.1982, 1.1984, 1.1975, 1.1977),
        (1.1978, 1.1982, 1.1969, 1.1979) if confirm_rejection else (1.1978, 1.1982, 1.1976, 1.1979),
    ]
    for offset, (open_price, high_price, low_price, close_price) in enumerate(reversal_tail, start=24):
        candles.append(
            Candle(
                opened_at_utc=start + timedelta(minutes=offset),
                asset="EURUSD-OTC",
                instrument_type=InstrumentType.BINARY,
                timeframe_sec=60,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=None,
            )
        )
    return candles


def _trend_pullback_call_setup(
    *,
    weak_confirmation: bool = False,
    close_back_below_fast_ema: bool = False,
    break_slow_ema_support: bool = False,
) -> list[Candle]:
    candles = _bullish_sequence(24, start=1.1000, step=0.00022, body_size=0.00022, wick_size=0.00006)
    candles[-2] = _candle(1.1056, 1.1057, 1.1044, 1.1048)
    if break_slow_ema_support:
        candles[-2] = _candle(1.1056, 1.1057, 1.1024, 1.1026)
    if weak_confirmation:
        candles[-1] = _candle(1.1048, 1.1066, 1.1047, 1.1058)
    else:
        candles[-1] = _candle(1.1048, 1.1062, 1.1047, 1.1060)
    if close_back_below_fast_ema:
        candles[-1] = _candle(1.1048, 1.1056, 1.1042, 1.1049)
    return candles


def _trend_pullback_put_setup() -> list[Candle]:
    candles = _bearish_sequence(24, start=1.1800, step=0.00022, body_size=0.00022, wick_size=0.00006)
    candles[-2] = _candle(1.1744, 1.1756, 1.1742, 1.1751)
    candles[-1] = _candle(1.1751, 1.1752, 1.1738, 1.1739)
    return candles