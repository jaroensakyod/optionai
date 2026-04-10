from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import math
import json
from typing import Any, Iterable, Literal, Protocol
from uuid import uuid4

from .market_data import Candle
from .models import InstrumentType, SessionLabel, SignalEvent, TradeDirection


StrategyProfile = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True, slots=True)
class TrendFilterSettings:
    ema_period: int
    adx_period: int
    adx_threshold: float
    atr_period: int
    min_atr_pct: float
    max_atr_pct: float
    sr_lookback: int
    min_sr_distance_pct: float
    alignment_timeframe_multiplier: int
    alignment_ema_period: int


class SignalEngine(Protocol):
    @property
    def strategy_name(self) -> str: ...

    @property
    def required_candles(self) -> int: ...

    def describe_parameters(self) -> dict[str, Any]: ...

    def build_signal(
        self,
        *,
        strategy_version_id: str,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        stake_amount: float,
        expiry_sec: int,
        candles: list[Candle],
        signal_time_utc: datetime,
    ) -> SignalEvent | None: ...


def normalize_strategy_profile(value: str) -> StrategyProfile:
    normalized = value.strip().upper()
    if normalized in {"LOW", "MEDIUM", "HIGH"}:
        return normalized
    raise ValueError("Strategy profile must be LOW, MEDIUM, or HIGH.")


def normalize_strategy_profiles(values: Iterable[str] | str) -> tuple[StrategyProfile, ...]:
    if isinstance(values, str):
        raw_values = [segment.strip() for segment in values.split(",")]
    else:
        raw_values = [str(value).strip() for value in values]
    normalized: list[StrategyProfile] = []
    for raw_value in raw_values:
        if not raw_value:
            continue
        profile = normalize_strategy_profile(raw_value)
        if profile not in normalized:
            normalized.append(profile)
    if not normalized:
        raise ValueError("Select at least one strategy profile.")
    return tuple(normalized)


def format_strategy_profiles(profiles: Iterable[str]) -> str:
    return ",".join(normalize_strategy_profiles(tuple(profiles)))


def default_trend_filter_settings(profile: StrategyProfile) -> TrendFilterSettings:
    if profile == "LOW":
        return TrendFilterSettings(
            ema_period=5,
            adx_period=5,
            adx_threshold=30.0,
            atr_period=5,
            min_atr_pct=0.00018,
            max_atr_pct=0.0014,
            sr_lookback=6,
            min_sr_distance_pct=0.00030,
            alignment_timeframe_multiplier=3,
            alignment_ema_period=4,
        )
    if profile == "MEDIUM":
        return TrendFilterSettings(
            ema_period=5,
            adx_period=5,
            adx_threshold=24.0,
            atr_period=5,
            min_atr_pct=0.00012,
            max_atr_pct=0.0018,
            sr_lookback=5,
            min_sr_distance_pct=0.00018,
            alignment_timeframe_multiplier=3,
            alignment_ema_period=4,
        )
    return TrendFilterSettings(
        ema_period=4,
        adx_period=4,
        adx_threshold=18.0,
        atr_period=4,
        min_atr_pct=0.00008,
        max_atr_pct=0.0022,
        sr_lookback=4,
        min_sr_distance_pct=0.00010,
        alignment_timeframe_multiplier=2,
        alignment_ema_period=3,
    )


@dataclass(frozen=True, slots=True)
class SimpleMomentumSignalEngine:
    strategy_profile: StrategyProfile = "LOW"
    confirmation_candles: int = 3
    minimum_total_move_pct: float = 0.0001
    minimum_body_ratio: float = 0.35
    trend_filter: TrendFilterSettings | None = None

    @property
    def strategy_name(self) -> str:
        return "simple-momentum"

    @property
    def required_candles(self) -> int:
        return _required_candles_for_filters(self.confirmation_candles, self._trend_filter_settings())

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "confirmation_candles": self.confirmation_candles,
            "minimum_total_move_pct": self.minimum_total_move_pct,
            "minimum_body_ratio": self.minimum_body_ratio,
            "trend_filter": _serialize_trend_filter_settings(self._trend_filter_settings()),
        }

    def _trend_filter_settings(self) -> TrendFilterSettings:
        return self.trend_filter or default_trend_filter_settings(self.strategy_profile)

    def parameter_hash(self) -> str:
        payload = json.dumps(self.describe_parameters(), sort_keys=True).encode("utf-8")
        return sha256(payload).hexdigest()

    def build_signal(
        self,
        *,
        strategy_version_id: str,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        stake_amount: float,
        expiry_sec: int,
        candles: list[Candle],
        signal_time_utc: datetime,
    ) -> SignalEvent | None:
        return _build_aligned_momentum_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            candles=candles,
            signal_time_utc=signal_time_utc,
            required_candles=self.required_candles,
            minimum_total_move_pct=self.minimum_total_move_pct,
            minimum_body_ratio=self.minimum_body_ratio,
            trend_filter=self._trend_filter_settings(),
            entry_reason="three_candle_momentum",
            extra_snapshot={"pattern": "aligned_momentum"},
        )


@dataclass(frozen=True, slots=True)
class BlitzMomentumSignalEngine:
    strategy_profile: StrategyProfile = "MEDIUM"
    confirmation_candles: int = 2
    minimum_total_move_pct: float = 0.00012
    minimum_body_ratio_call: float = 0.55
    minimum_body_ratio_put: float = 0.45
    trend_filter: TrendFilterSettings | None = None

    @property
    def strategy_name(self) -> str:
        return "blitz-momentum"

    @property
    def required_candles(self) -> int:
        return _required_candles_for_filters(self.confirmation_candles, self._trend_filter_settings())

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "confirmation_candles": self.confirmation_candles,
            "minimum_total_move_pct": self.minimum_total_move_pct,
            "minimum_body_ratio_call": self.minimum_body_ratio_call,
            "minimum_body_ratio_put": self.minimum_body_ratio_put,
            "recommended_timeframe_sec": 30,
            "recommended_expiry_sec": 60,
            "trend_filter": _serialize_trend_filter_settings(self._trend_filter_settings()),
        }

    def _trend_filter_settings(self) -> TrendFilterSettings:
        return self.trend_filter or default_trend_filter_settings(self.strategy_profile)

    def build_signal(
        self,
        *,
        strategy_version_id: str,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        stake_amount: float,
        expiry_sec: int,
        candles: list[Candle],
        signal_time_utc: datetime,
    ) -> SignalEvent | None:
        return _build_aligned_momentum_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            candles=candles,
            signal_time_utc=signal_time_utc,
            required_candles=self.required_candles,
            minimum_total_move_pct=self.minimum_total_move_pct,
            minimum_body_ratio_call=self.minimum_body_ratio_call,
            minimum_body_ratio_put=self.minimum_body_ratio_put,
            trend_filter=self._trend_filter_settings(),
            entry_reason="two_candle_blitz",
            extra_snapshot={"pattern": "aligned_momentum_blitz"},
        )


@dataclass(frozen=True, slots=True)
class RelaxedMomentumSignalEngine:
    strategy_profile: StrategyProfile = "HIGH"
    confirmation_candles: int = 2
    minimum_total_move_pct: float = 0.00008
    minimum_body_ratio_call: float = 0.3
    minimum_body_ratio_put: float = 0.28
    trend_filter: TrendFilterSettings | None = None

    @property
    def strategy_name(self) -> str:
        return "relaxed-momentum"

    @property
    def required_candles(self) -> int:
        return _required_candles_for_filters(self.confirmation_candles, self._trend_filter_settings())

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "confirmation_candles": self.confirmation_candles,
            "minimum_total_move_pct": self.minimum_total_move_pct,
            "minimum_body_ratio_call": self.minimum_body_ratio_call,
            "minimum_body_ratio_put": self.minimum_body_ratio_put,
            "recommended_timeframe_sec": 60,
            "recommended_expiry_sec": 60,
            "trend_filter": _serialize_trend_filter_settings(self._trend_filter_settings()),
        }

    def _trend_filter_settings(self) -> TrendFilterSettings:
        return self.trend_filter or default_trend_filter_settings(self.strategy_profile)

    def build_signal(
        self,
        *,
        strategy_version_id: str,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        stake_amount: float,
        expiry_sec: int,
        candles: list[Candle],
        signal_time_utc: datetime,
    ) -> SignalEvent | None:
        return _build_aligned_momentum_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            candles=candles,
            signal_time_utc=signal_time_utc,
            required_candles=self.required_candles,
            minimum_total_move_pct=self.minimum_total_move_pct,
            minimum_body_ratio_call=self.minimum_body_ratio_call,
            minimum_body_ratio_put=self.minimum_body_ratio_put,
            trend_filter=self._trend_filter_settings(),
            entry_reason="two_candle_relaxed",
            extra_snapshot={"pattern": "aligned_momentum_relaxed"},
        )


def build_signal_engine(profile: str) -> SignalEngine:
    normalized_profile = normalize_strategy_profile(profile)
    if normalized_profile == "LOW":
        return SimpleMomentumSignalEngine(
            strategy_profile="LOW",
            confirmation_candles=3,
            minimum_total_move_pct=0.00014,
            minimum_body_ratio=0.45,
            trend_filter=default_trend_filter_settings("LOW"),
        )
    if normalized_profile == "MEDIUM":
        return BlitzMomentumSignalEngine(
            strategy_profile="MEDIUM",
            confirmation_candles=2,
            minimum_total_move_pct=0.00012,
            minimum_body_ratio_call=0.55,
            minimum_body_ratio_put=0.45,
            trend_filter=default_trend_filter_settings("MEDIUM"),
        )
    return RelaxedMomentumSignalEngine(
        strategy_profile="HIGH",
        confirmation_candles=2,
        minimum_total_move_pct=0.00008,
        minimum_body_ratio_call=0.3,
        minimum_body_ratio_put=0.28,
        trend_filter=default_trend_filter_settings("HIGH"),
    )


@dataclass(frozen=True, slots=True)
class CompositeSignalEngine:
    engines: tuple[SignalEngine, ...]
    strategy_profiles: tuple[StrategyProfile, ...]

    @property
    def strategy_name(self) -> str:
        return "composite-momentum"

    @property
    def required_candles(self) -> int:
        return max(engine.required_candles for engine in self.engines)

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "strategy_profiles": list(self.strategy_profiles),
            "engines": {
                profile: engine.describe_parameters()
                for profile, engine in zip(self.strategy_profiles, self.engines)
            },
        }

    def trade_tags(self) -> dict[str, str]:
        strategy_names = [engine.strategy_name for engine in self.engines]
        return {
            "strategy_profile": self.strategy_profiles[0],
            "strategy_profiles": ",".join(self.strategy_profiles),
            "strategy_name": strategy_names[0],
            "strategy_names": ",".join(strategy_names),
            "strategy_display": " + ".join(self.strategy_profiles),
        }

    def build_signal(
        self,
        *,
        strategy_version_id: str,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        stake_amount: float,
        expiry_sec: int,
        candles: list[Candle],
        signal_time_utc: datetime,
    ) -> SignalEvent | None:
        contributing_signals: list[tuple[StrategyProfile, SignalEngine, SignalEvent]] = []
        for profile, engine in zip(self.strategy_profiles, self.engines):
            signal = engine.build_signal(
                strategy_version_id=strategy_version_id,
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                stake_amount=stake_amount,
                expiry_sec=expiry_sec,
                candles=candles,
                signal_time_utc=signal_time_utc,
            )
            if signal is not None:
                contributing_signals.append((profile, engine, signal))
        if not contributing_signals:
            return None

        directions = {signal.direction for _, _, signal in contributing_signals}
        if len(directions) > 1:
            profiles = [profile for profile, _, _ in contributing_signals]
            names = [engine.strategy_name for _, engine, _ in contributing_signals]
            return SignalEvent(
                signal_id=f"signal-{uuid4().hex}",
                created_at_utc=signal_time_utc,
                strategy_version_id=strategy_version_id,
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                direction=contributing_signals[0][2].direction,
                intended_amount=stake_amount,
                intended_expiry_sec=expiry_sec,
                entry_reason="conflicting_strategy_signals",
                session_label=contributing_signals[0][2].session_label,
                signal_strength=max(signal.signal_strength or 0.0 for _, _, signal in contributing_signals),
                indicator_snapshot={
                    "strategy_profiles": profiles,
                    "strategy_names": names,
                    "conflicting_directions": sorted(direction.value for direction in directions),
                },
                market_snapshot={"merged_signal": True},
                is_filtered_out=True,
                filter_reason="conflicting_strategy_signals",
            )

        primary_profile, primary_engine, primary_signal = contributing_signals[0]
        merged_profiles = [profile for profile, _, _ in contributing_signals]
        merged_names = [engine.strategy_name for _, engine, _ in contributing_signals]
        merged_indicator_snapshot = {
            **primary_signal.indicator_snapshot,
            "strategy_profiles": merged_profiles,
            "strategy_names": merged_names,
            "strategy_entry_reasons": [signal.entry_reason for _, _, signal in contributing_signals],
            "supporting_signal_ids": [signal.signal_id for _, _, signal in contributing_signals],
            "supporting_signal_strengths": [signal.signal_strength for _, _, signal in contributing_signals],
        }
        merged_market_snapshot = {
            **primary_signal.market_snapshot,
            "merged_signal": len(contributing_signals) > 1,
        }
        return SignalEvent(
            signal_id=f"signal-{uuid4().hex}",
            created_at_utc=primary_signal.created_at_utc,
            strategy_version_id=strategy_version_id,
            asset=primary_signal.asset,
            instrument_type=primary_signal.instrument_type,
            timeframe_sec=primary_signal.timeframe_sec,
            direction=primary_signal.direction,
            intended_amount=primary_signal.intended_amount,
            intended_expiry_sec=primary_signal.intended_expiry_sec,
            entry_reason=" + ".join(dict.fromkeys(signal.entry_reason for _, _, signal in contributing_signals)),
            session_label=primary_signal.session_label,
            signal_strength=max(signal.signal_strength or 0.0 for _, _, signal in contributing_signals),
            indicator_snapshot=merged_indicator_snapshot,
            market_snapshot=merged_market_snapshot,
        )


def build_composite_signal_engine(profiles: Iterable[str]) -> SignalEngine:
    normalized_profiles = normalize_strategy_profiles(tuple(profiles))
    if len(normalized_profiles) == 1:
        return build_signal_engine(normalized_profiles[0])
    return CompositeSignalEngine(
        engines=tuple(build_signal_engine(profile) for profile in normalized_profiles),
        strategy_profiles=normalized_profiles,
    )


def _infer_session_label(hour_utc: int) -> SessionLabel:
    if 0 <= hour_utc < 7:
        return SessionLabel.ASIA
    if 7 <= hour_utc < 12:
        return SessionLabel.LONDON
    if 12 <= hour_utc < 16:
        return SessionLabel.OVERLAP
    if 16 <= hour_utc < 21:
        return SessionLabel.NEW_YORK
    return SessionLabel.OFF_SESSION


def _build_aligned_momentum_signal(
    *,
    strategy_version_id: str,
    asset: str,
    instrument_type: InstrumentType,
    timeframe_sec: int,
    stake_amount: float,
    expiry_sec: int,
    candles: list[Candle],
    signal_time_utc: datetime,
    required_candles: int,
    minimum_total_move_pct: float,
    minimum_body_ratio: float | None = None,
    minimum_body_ratio_call: float | None = None,
    minimum_body_ratio_put: float | None = None,
    trend_filter: TrendFilterSettings,
    entry_reason: str,
    extra_snapshot: dict[str, Any],
) -> SignalEvent | None:
    relevant_candles = candles[-required_candles:]
    if len(relevant_candles) < required_candles:
        return None

    close_prices = [candle.close_price for candle in relevant_candles]
    body_ratios = [_body_ratio(candle) for candle in relevant_candles]
    bullish_bodies = all(candle.close_price > candle.open_price for candle in relevant_candles)
    bearish_bodies = all(candle.close_price < candle.open_price for candle in relevant_candles)

    if minimum_body_ratio is not None:
        minimum_body_ratio_call = minimum_body_ratio
        minimum_body_ratio_put = minimum_body_ratio
    if minimum_body_ratio_call is None or minimum_body_ratio_put is None:
        raise ValueError("Momentum signal thresholds must be provided.")

    if (
        all(left < right for left, right in zip(close_prices, close_prices[1:]))
        and bullish_bodies
        and all(body_ratio >= minimum_body_ratio_call for body_ratio in body_ratios)
    ):
        direction = TradeDirection.CALL
    elif (
        all(left > right for left, right in zip(close_prices, close_prices[1:]))
        and bearish_bodies
        and all(body_ratio >= minimum_body_ratio_put for body_ratio in body_ratios)
    ):
        direction = TradeDirection.PUT
    else:
        return None

    first_close = close_prices[0]
    last_close = close_prices[-1]
    if first_close == 0:
        return None
    total_move_pct = abs((last_close - first_close) / first_close)
    if total_move_pct < minimum_total_move_pct:
        return None

    filter_context = _build_filter_context(
        candles=candles,
        relevant_candles=relevant_candles,
        timeframe_sec=timeframe_sec,
        direction=direction,
        trend_filter=trend_filter,
    )
    if filter_context is None:
        return None

    return SignalEvent(
        signal_id=f"signal-{uuid4().hex}",
        created_at_utc=signal_time_utc,
        strategy_version_id=strategy_version_id,
        asset=asset,
        instrument_type=instrument_type,
        timeframe_sec=timeframe_sec,
        direction=direction,
        intended_amount=stake_amount,
        intended_expiry_sec=expiry_sec,
        entry_reason=entry_reason,
        session_label=_infer_session_label(signal_time_utc.hour),
        signal_strength=total_move_pct,
        indicator_snapshot={
            "close_prices": close_prices,
            "body_ratios": body_ratios,
            "total_move_pct": total_move_pct,
            **filter_context,
            **extra_snapshot,
        },
        market_snapshot={
            "last_opened_at_utc": relevant_candles[-1].opened_at_utc.isoformat(),
        },
    )


def _body_ratio(candle: Candle) -> float:
    total_range = candle.high_price - candle.low_price
    if total_range <= 0:
        return 0.0
    return abs(candle.close_price - candle.open_price) / total_range


def _serialize_trend_filter_settings(settings: TrendFilterSettings) -> dict[str, Any]:
    return {
        "ema_period": settings.ema_period,
        "adx_period": settings.adx_period,
        "adx_threshold": settings.adx_threshold,
        "atr_period": settings.atr_period,
        "min_atr_pct": settings.min_atr_pct,
        "max_atr_pct": settings.max_atr_pct,
        "sr_lookback": settings.sr_lookback,
        "min_sr_distance_pct": settings.min_sr_distance_pct,
        "alignment_timeframe_multiplier": settings.alignment_timeframe_multiplier,
        "alignment_ema_period": settings.alignment_ema_period,
    }


def _required_candles_for_filters(confirmation_candles: int, trend_filter: TrendFilterSettings) -> int:
    base_window = max(
        confirmation_candles,
        trend_filter.ema_period,
        (trend_filter.adx_period * 2) + 1,
        trend_filter.atr_period + 1,
        trend_filter.sr_lookback + 1,
    )
    alignment_base = max(trend_filter.alignment_ema_period, 2) * max(trend_filter.alignment_timeframe_multiplier, 1)
    return max(base_window, alignment_base)


def _build_filter_context(
    *,
    candles: list[Candle],
    relevant_candles: list[Candle],
    timeframe_sec: int,
    direction: TradeDirection,
    trend_filter: TrendFilterSettings,
) -> dict[str, Any] | None:
    if len(candles) < _required_candles_for_filters(len(relevant_candles), trend_filter):
        return None

    current_close = relevant_candles[-1].close_price
    ema_value = _ema([candle.close_price for candle in candles], trend_filter.ema_period)
    if ema_value is None:
        return None
    if direction == TradeDirection.CALL and current_close <= ema_value:
        return None
    if direction == TradeDirection.PUT and current_close >= ema_value:
        return None

    adx_value = _adx(candles, trend_filter.adx_period)
    if adx_value is None or adx_value < trend_filter.adx_threshold:
        return None

    atr_value = _atr(candles, trend_filter.atr_period)
    if atr_value is None or current_close <= 0:
        return None
    atr_pct = atr_value / current_close
    if atr_pct < trend_filter.min_atr_pct or atr_pct > trend_filter.max_atr_pct:
        return None

    sr_distance_pct = _support_resistance_distance_pct(
        candles=candles,
        lookback=trend_filter.sr_lookback,
        current_close=current_close,
        direction=direction,
    )
    if sr_distance_pct is None or sr_distance_pct < trend_filter.min_sr_distance_pct:
        return None

    aligned_candles = _aggregate_candles(candles, trend_filter.alignment_timeframe_multiplier)
    aligned_ema = _ema([candle.close_price for candle in aligned_candles], trend_filter.alignment_ema_period)
    if aligned_ema is None:
        return None
    aligned_close = aligned_candles[-1].close_price
    alignment_timeframe_sec = timeframe_sec * max(trend_filter.alignment_timeframe_multiplier, 1)
    if direction == TradeDirection.CALL and aligned_close <= aligned_ema:
        return None
    if direction == TradeDirection.PUT and aligned_close >= aligned_ema:
        return None

    return {
        "ema_trend_value": ema_value,
        "adx_value": adx_value,
        "atr_value": atr_value,
        "atr_pct": atr_pct,
        "support_resistance_distance_pct": sr_distance_pct,
        "alignment_timeframe_sec": alignment_timeframe_sec,
        "alignment_close": aligned_close,
        "alignment_ema": aligned_ema,
    }


def _ema(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema_value = sum(values[:period]) / period
    for value in values[period:]:
        ema_value = ((value - ema_value) * multiplier) + ema_value
    return ema_value


def _true_range(current: Candle, previous_close: float) -> float:
    return max(
        current.high_price - current.low_price,
        abs(current.high_price - previous_close),
        abs(current.low_price - previous_close),
    )


def _atr(candles: list[Candle], period: int) -> float | None:
    if period <= 0 or len(candles) < period + 1:
        return None
    true_ranges = [_true_range(current, previous.close_price) for previous, current in zip(candles, candles[1:])]
    if len(true_ranges) < period:
        return None
    atr_value = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        atr_value = ((atr_value * (period - 1)) + true_range) / period
    return atr_value


def _adx(candles: list[Candle], period: int) -> float | None:
    if period <= 0 or len(candles) < (period * 2) + 1:
        return None

    true_ranges: list[float] = []
    plus_dm_values: list[float] = []
    minus_dm_values: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        up_move = current.high_price - previous.high_price
        down_move = previous.low_price - current.low_price
        plus_dm_values.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm_values.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(_true_range(current, previous.close_price))

    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dm_values[:period])
    smoothed_minus_dm = sum(minus_dm_values[:period])
    dx_values: list[float] = []
    for index in range(period, len(true_ranges)):
        if index > period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[index]
            smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dm_values[index]
            smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dm_values[index]
        if smoothed_tr <= 0:
            dx_values.append(0.0)
            continue
        plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr)
        minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr)
        denominator = plus_di + minus_di
        if denominator <= 0:
            dx_values.append(0.0)
            continue
        dx_values.append(100.0 * abs(plus_di - minus_di) / denominator)

    if len(dx_values) < period:
        return None
    adx_value = sum(dx_values[:period]) / period
    for value in dx_values[period:]:
        adx_value = ((adx_value * (period - 1)) + value) / period
    return adx_value


def _support_resistance_distance_pct(
    *,
    candles: list[Candle],
    lookback: int,
    current_close: float,
    direction: TradeDirection,
) -> float | None:
    if lookback <= 0 or current_close <= 0 or len(candles) < lookback + 1:
        return None
    lookback_candles = candles[-(lookback + 1) : -1]
    if not lookback_candles:
        return None
    if direction == TradeDirection.CALL:
        reference = max(candle.high_price for candle in lookback_candles)
        if current_close >= reference:
            return 1.0
        return max(reference - current_close, 0.0) / current_close
    reference = min(candle.low_price for candle in lookback_candles)
    if current_close <= reference:
        return 1.0
    return max(current_close - reference, 0.0) / current_close


def _aggregate_candles(candles: list[Candle], multiplier: int) -> list[Candle]:
    normalized_multiplier = max(multiplier, 1)
    if normalized_multiplier == 1:
        return list(candles)
    complete_count = len(candles) // normalized_multiplier
    if complete_count <= 0:
        return []
    aggregated: list[Candle] = []
    for index in range(complete_count):
        chunk = candles[index * normalized_multiplier : (index + 1) * normalized_multiplier]
        if len(chunk) < normalized_multiplier:
            continue
        aggregated.append(
            Candle(
                opened_at_utc=chunk[0].opened_at_utc,
                asset=chunk[-1].asset,
                instrument_type=chunk[-1].instrument_type,
                timeframe_sec=chunk[-1].timeframe_sec * normalized_multiplier,
                open_price=chunk[0].open_price,
                high_price=max(candle.high_price for candle in chunk),
                low_price=min(candle.low_price for candle in chunk),
                close_price=chunk[-1].close_price,
                volume=sum((candle.volume or 0.0) for candle in chunk) if any(candle.volume is not None for candle in chunk) else None,
            )
        )
    return aggregated
