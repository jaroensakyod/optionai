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

STRATEGY_PROFILE_ORDER: tuple[StrategyProfile, ...] = ("LOW", "MEDIUM", "HIGH")

DEFAULT_STRATEGY_ID = "momentum.medium"


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    family: str
    family_label: str
    profile: StrategyProfile
    engine_name: str
    recommended_timeframe_sec: int
    recommended_expiry_sec: int

_STRATEGY_PROFILE_ENGINE_NAMES: dict[StrategyProfile, str] = {
    "LOW": "simple-momentum",
    "MEDIUM": "blitz-momentum",
    "HIGH": "relaxed-momentum",
}

_PRIMARY_STRATEGY_DEFINITIONS: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(
        strategy_id="momentum.low",
        family="momentum",
        family_label="Momentum",
        profile="LOW",
        engine_name="simple-momentum",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="momentum.medium",
        family="momentum",
        family_label="Momentum",
        profile="MEDIUM",
        engine_name="blitz-momentum",
        recommended_timeframe_sec=30,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="momentum.high",
        family="momentum",
        family_label="Momentum",
        profile="HIGH",
        engine_name="relaxed-momentum",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
)

_ADDITIONAL_STRATEGY_DEFINITIONS: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(
        strategy_id="trend-pullback.low",
        family="trend-pullback",
        family_label="Trend Pullback",
        profile="LOW",
        engine_name="strict-ema-pullback",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="trend-pullback.medium",
        family="trend-pullback",
        family_label="Trend Pullback",
        profile="MEDIUM",
        engine_name="balanced-ema-pullback",
        recommended_expiry_sec=60,
        recommended_timeframe_sec=60,
    ),
    StrategyDefinition(
        strategy_id="trend-pullback.high",
        family="trend-pullback",
        family_label="Trend Pullback",
        profile="HIGH",
        engine_name="aggressive-ema-pullback",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="mean-reversion.low",
        family="mean-reversion",
        family_label="Mean Reversion",
        profile="LOW",
        engine_name="bollinger-rsi-reversion",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="mean-reversion.medium",
        family="mean-reversion",
        family_label="Mean Reversion",
        profile="MEDIUM",
        engine_name="bollinger-rsi-reversion",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
    StrategyDefinition(
        strategy_id="mean-reversion.high",
        family="mean-reversion",
        family_label="Mean Reversion",
        profile="HIGH",
        engine_name="bollinger-rsi-reversion",
        recommended_timeframe_sec=60,
        recommended_expiry_sec=60,
    ),
)

_SUPPORTED_STRATEGY_DEFINITIONS: tuple[StrategyDefinition, ...] = (
    *_PRIMARY_STRATEGY_DEFINITIONS,
    *_ADDITIONAL_STRATEGY_DEFINITIONS,
)

STRATEGY_ID_ORDER: tuple[str, ...] = tuple(definition.strategy_id for definition in _SUPPORTED_STRATEGY_DEFINITIONS)

_STRATEGY_DEFINITION_BY_ID: dict[str, StrategyDefinition] = {
    definition.strategy_id: definition
    for definition in _SUPPORTED_STRATEGY_DEFINITIONS
}

_PRIMARY_STRATEGY_ID_BY_PROFILE: dict[StrategyProfile, str] = {
    definition.profile: definition.strategy_id
    for definition in _PRIMARY_STRATEGY_DEFINITIONS
}

_STRATEGY_ALIAS_MAP: dict[str, str] = {
    "low": "momentum.low",
    "medium": "momentum.medium",
    "high": "momentum.high",
    "momentum": "momentum.medium",
    "trend-pullback": "trend-pullback.medium",
    "strict-ema-pullback": "trend-pullback.low",
    "balanced-ema-pullback": "trend-pullback.medium",
    "aggressive-ema-pullback": "trend-pullback.high",
    "simple-momentum": "momentum.low",
    "blitz": "momentum.medium",
    "blitz-momentum": "momentum.medium",
    "relaxed-momentum": "momentum.high",
    "mean-reversion": "mean-reversion.medium",
    "bollinger-rsi-reversion": "mean-reversion.medium",
}


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
    if normalized in STRATEGY_PROFILE_ORDER:
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


def strategy_definition(strategy_id: str) -> StrategyDefinition:
    normalized_strategy_id = normalize_strategy_id(strategy_id)
    return _STRATEGY_DEFINITION_BY_ID[normalized_strategy_id]


def normalize_strategy_id(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in _STRATEGY_DEFINITION_BY_ID:
        return normalized
    aliased = _STRATEGY_ALIAS_MAP.get(normalized)
    if aliased is not None:
        return aliased
    raise ValueError(f"Unsupported strategy id: {value}")


def normalize_strategy_ids(values: Iterable[str] | str) -> tuple[str, ...]:
    if isinstance(values, str):
        raw_values = [segment.strip() for segment in values.split(",")]
    else:
        raw_values = [str(value).strip() for value in values]
    normalized: list[str] = []
    for raw_value in raw_values:
        if not raw_value:
            continue
        strategy_id = normalize_strategy_id(raw_value)
        if strategy_id not in normalized:
            normalized.append(strategy_id)
    if not normalized:
        raise ValueError("Select at least one strategy.")
    return tuple(normalized)


def format_strategy_ids(strategy_ids: Iterable[str]) -> str:
    return ",".join(normalize_strategy_ids(tuple(strategy_ids)))


def strategy_profile_to_id(profile: str) -> str:
    normalized_profile = normalize_strategy_profile(profile)
    return _PRIMARY_STRATEGY_ID_BY_PROFILE[normalized_profile]


def strategy_profiles_from_ids(strategy_ids: Iterable[str] | str) -> tuple[StrategyProfile, ...]:
    return tuple(strategy_definition(strategy_id).profile for strategy_id in normalize_strategy_ids(strategy_ids))


def strategy_family_label(strategy_id: str) -> str:
    return strategy_definition(strategy_id).family_label


def strategy_family_id(strategy_id: str) -> str:
    return strategy_definition(strategy_id).family


def strategy_engine_name_for_id(strategy_id: str) -> str:
    return strategy_definition(strategy_id).engine_name


def format_strategy_id_display(strategy_id: str) -> str:
    definition = strategy_definition(strategy_id)
    return f"{definition.family_label} {definition.profile} / {definition.engine_name}"


def format_strategy_id_group_displays(strategy_ids: Iterable[str] | str) -> tuple[str, ...]:
    return tuple(format_strategy_id_display(strategy_id) for strategy_id in normalize_strategy_ids(strategy_ids))


def format_strategy_id_set_display(strategy_ids: Iterable[str] | str) -> str:
    return " + ".join(format_strategy_id_group_displays(strategy_ids))


def format_strategy_option_label(strategy_id: str) -> str:
    return format_strategy_id_display(strategy_id)


def strategy_engine_name(profile: str) -> str:
    normalized_profile = normalize_strategy_profile(profile)
    return _STRATEGY_PROFILE_ENGINE_NAMES[normalized_profile]


def format_strategy_profile_display(profile: str, engine_name: str | None = None) -> str:
    normalized_profile = normalize_strategy_profile(profile)
    resolved_engine_name = (engine_name or strategy_engine_name(normalized_profile)).strip()
    return f"{normalized_profile} / {resolved_engine_name}"


def format_strategy_group_displays(
    profiles: Iterable[str] | str,
    strategy_names: Iterable[str] | str | None = None,
) -> tuple[str, ...]:
    normalized_profiles = normalize_strategy_profiles(profiles)
    if strategy_names is None:
        raw_names: list[str] = []
    elif isinstance(strategy_names, str):
        raw_names = [segment.strip() for segment in strategy_names.split(",")]
    else:
        raw_names = [str(value).strip() for value in strategy_names]
    displays: list[str] = []
    for index, profile in enumerate(normalized_profiles):
        engine_name = raw_names[index] if index < len(raw_names) and raw_names[index] else None
        displays.append(format_strategy_profile_display(profile, engine_name))
    return tuple(displays)


def format_strategy_display(
    profiles: Iterable[str] | str,
    strategy_names: Iterable[str] | str | None = None,
) -> str:
    return " + ".join(format_strategy_group_displays(profiles, strategy_names))


def format_strategy_profile_option_label(profile: str) -> str:
    return format_strategy_profile_display(profile)


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
class TrendPullbackSettings:
    fast_ema_period: int
    slow_ema_period: int
    adx_period: int
    min_adx: float
    atr_period: int
    min_atr_pct: float
    max_atr_pct: float
    min_trend_gap_pct: float
    max_pullback_touch_pct: float
    max_slow_ema_breach_pct: float
    min_confirmation_body_ratio: float


def default_trend_pullback_settings(profile: StrategyProfile) -> TrendPullbackSettings:
    if profile == "LOW":
        return TrendPullbackSettings(
            fast_ema_period=9,
            slow_ema_period=21,
            adx_period=5,
            min_adx=24.0,
            atr_period=5,
            min_atr_pct=0.00010,
            max_atr_pct=0.0018,
            min_trend_gap_pct=0.00016,
            max_pullback_touch_pct=0.00010,
            max_slow_ema_breach_pct=0.00005,
            min_confirmation_body_ratio=0.58,
        )
    if profile == "MEDIUM":
        return TrendPullbackSettings(
            fast_ema_period=8,
            slow_ema_period=18,
            adx_period=5,
            min_adx=20.0,
            atr_period=5,
            min_atr_pct=0.00008,
            max_atr_pct=0.0020,
            min_trend_gap_pct=0.00012,
            max_pullback_touch_pct=0.00014,
            max_slow_ema_breach_pct=0.00008,
            min_confirmation_body_ratio=0.50,
        )
    return TrendPullbackSettings(
        fast_ema_period=5,
        slow_ema_period=13,
        adx_period=4,
        min_adx=16.0,
        atr_period=4,
        min_atr_pct=0.00006,
        max_atr_pct=0.0024,
        min_trend_gap_pct=0.00008,
        max_pullback_touch_pct=0.00022,
        max_slow_ema_breach_pct=0.00014,
        min_confirmation_body_ratio=0.38,
    )


@dataclass(frozen=True, slots=True)
class TrendPullbackSignalEngine:
    strategy_id: str = "trend-pullback.medium"
    strategy_family: str = "trend-pullback"
    strategy_profile: StrategyProfile = "MEDIUM"
    pullback_settings: TrendPullbackSettings | None = None

    @property
    def strategy_name(self) -> str:
        return strategy_engine_name_for_id(self.strategy_id)

    @property
    def required_candles(self) -> int:
        return _required_candles_for_trend_pullback(self._settings())

    def describe_parameters(self) -> dict[str, Any]:
        settings = self._settings()
        return {
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_profile": self.strategy_profile,
            "fast_ema_period": settings.fast_ema_period,
            "slow_ema_period": settings.slow_ema_period,
            "adx_period": settings.adx_period,
            "min_adx": settings.min_adx,
            "atr_period": settings.atr_period,
            "min_atr_pct": settings.min_atr_pct,
            "max_atr_pct": settings.max_atr_pct,
            "min_trend_gap_pct": settings.min_trend_gap_pct,
            "max_pullback_touch_pct": settings.max_pullback_touch_pct,
            "max_slow_ema_breach_pct": settings.max_slow_ema_breach_pct,
            "min_confirmation_body_ratio": settings.min_confirmation_body_ratio,
            "recommended_timeframe_sec": 60,
            "recommended_expiry_sec": 60,
        }

    def _settings(self) -> TrendPullbackSettings:
        return self.pullback_settings or default_trend_pullback_settings(self.strategy_profile)

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
        return _build_trend_pullback_signal(
            strategy_id=self.strategy_id,
            strategy_family=self.strategy_family,
            strategy_profile=self.strategy_profile,
            strategy_name=self.strategy_name,
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            candles=candles,
            signal_time_utc=signal_time_utc,
            settings=self._settings(),
        )


@dataclass(frozen=True, slots=True)
class SimpleMomentumSignalEngine:
    strategy_id: str = "momentum.low"
    strategy_family: str = "momentum"
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
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_profile": self.strategy_profile,
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

    def diagnose_no_signal(
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
    ) -> str | None:
        return _evaluate_aligned_momentum_signal(
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
        ).no_signal_reason


@dataclass(frozen=True, slots=True)
class BlitzMomentumSignalEngine:
    strategy_id: str = "momentum.medium"
    strategy_family: str = "momentum"
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
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_profile": self.strategy_profile,
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

    def diagnose_no_signal(
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
    ) -> str | None:
        return _evaluate_aligned_momentum_signal(
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
        ).no_signal_reason


@dataclass(frozen=True, slots=True)
class RelaxedMomentumSignalEngine:
    strategy_id: str = "momentum.high"
    strategy_family: str = "momentum"
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
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_profile": self.strategy_profile,
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

    def diagnose_no_signal(
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
    ) -> str | None:
        return _evaluate_aligned_momentum_signal(
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
        ).no_signal_reason


@dataclass(frozen=True, slots=True)
class MeanReversionSettings:
    bollinger_period: int
    bollinger_stddev: float
    rsi_period: int
    rsi_oversold: float
    rsi_overbought: float
    stochastic_period: int
    stochastic_k_smoothing: int
    stochastic_d_period: int
    stochastic_oversold: float
    stochastic_overbought: float
    adx_period: int
    max_adx: float
    atr_period: int
    min_atr_pct: float
    max_atr_pct: float
    ema_period: int
    max_ema_slope_pct: float
    min_reversion_distance_pct: float
    min_wick_ratio: float
    min_body_recovery_ratio: float
    zscore_threshold: float


def default_mean_reversion_settings(profile: StrategyProfile) -> MeanReversionSettings:
    if profile == "LOW":
        return MeanReversionSettings(
            bollinger_period=20,
            bollinger_stddev=2.2,
            rsi_period=7,
            rsi_oversold=28.0,
            rsi_overbought=72.0,
            stochastic_period=14,
            stochastic_k_smoothing=3,
            stochastic_d_period=3,
            stochastic_oversold=18.0,
            stochastic_overbought=82.0,
            adx_period=5,
            max_adx=18.0,
            atr_period=5,
            min_atr_pct=0.00008,
            max_atr_pct=0.0014,
            ema_period=8,
            max_ema_slope_pct=0.00012,
            min_reversion_distance_pct=0.00012,
            min_wick_ratio=0.42,
            min_body_recovery_ratio=0.18,
            zscore_threshold=1.9,
        )
    if profile == "MEDIUM":
        return MeanReversionSettings(
            bollinger_period=20,
            bollinger_stddev=2.0,
            rsi_period=7,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            stochastic_period=14,
            stochastic_k_smoothing=3,
            stochastic_d_period=3,
            stochastic_oversold=20.0,
            stochastic_overbought=80.0,
            adx_period=5,
            max_adx=22.0,
            atr_period=5,
            min_atr_pct=0.00006,
            max_atr_pct=0.0018,
            ema_period=8,
            max_ema_slope_pct=0.00018,
            min_reversion_distance_pct=0.0001,
            min_wick_ratio=0.36,
            min_body_recovery_ratio=0.12,
            zscore_threshold=1.7,
        )
    return MeanReversionSettings(
        bollinger_period=18,
        bollinger_stddev=1.8,
        rsi_period=6,
        rsi_oversold=32.0,
        rsi_overbought=68.0,
        stochastic_period=12,
        stochastic_k_smoothing=3,
        stochastic_d_period=3,
        stochastic_oversold=24.0,
        stochastic_overbought=76.0,
        adx_period=4,
        max_adx=26.0,
        atr_period=4,
        min_atr_pct=0.00005,
        max_atr_pct=0.0022,
        ema_period=6,
        max_ema_slope_pct=0.00024,
        min_reversion_distance_pct=0.00008,
        min_wick_ratio=0.3,
        min_body_recovery_ratio=0.08,
        zscore_threshold=1.5,
    )


@dataclass(frozen=True, slots=True)
class MeanReversionSignalEngine:
    strategy_id: str = "mean-reversion.medium"
    strategy_family: str = "mean-reversion"
    strategy_profile: StrategyProfile = "MEDIUM"
    reversion_settings: MeanReversionSettings | None = None

    @property
    def strategy_name(self) -> str:
        return "bollinger-rsi-reversion"

    @property
    def required_candles(self) -> int:
        return _required_candles_for_mean_reversion(self._settings())

    def describe_parameters(self) -> dict[str, Any]:
        settings = self._settings()
        return {
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_profile": self.strategy_profile,
            "bollinger_period": settings.bollinger_period,
            "bollinger_stddev": settings.bollinger_stddev,
            "rsi_period": settings.rsi_period,
            "rsi_oversold": settings.rsi_oversold,
            "rsi_overbought": settings.rsi_overbought,
            "stochastic_period": settings.stochastic_period,
            "stochastic_k_smoothing": settings.stochastic_k_smoothing,
            "stochastic_d_period": settings.stochastic_d_period,
            "stochastic_oversold": settings.stochastic_oversold,
            "stochastic_overbought": settings.stochastic_overbought,
            "adx_period": settings.adx_period,
            "max_adx": settings.max_adx,
            "atr_period": settings.atr_period,
            "min_atr_pct": settings.min_atr_pct,
            "max_atr_pct": settings.max_atr_pct,
            "ema_period": settings.ema_period,
            "max_ema_slope_pct": settings.max_ema_slope_pct,
            "min_reversion_distance_pct": settings.min_reversion_distance_pct,
            "min_wick_ratio": settings.min_wick_ratio,
            "min_body_recovery_ratio": settings.min_body_recovery_ratio,
            "zscore_threshold": settings.zscore_threshold,
            "recommended_timeframe_sec": 60,
            "recommended_expiry_sec": 60,
        }

    def _settings(self) -> MeanReversionSettings:
        return self.reversion_settings or default_mean_reversion_settings(self.strategy_profile)

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
        return _build_mean_reversion_signal(
            strategy_id=self.strategy_id,
            strategy_family=self.strategy_family,
            strategy_profile=self.strategy_profile,
            strategy_name=self.strategy_name,
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            candles=candles,
            signal_time_utc=signal_time_utc,
            settings=self._settings(),
        )


def build_signal_engine(profile: str) -> SignalEngine:
    normalized_profile = normalize_strategy_profile(profile)
    return build_strategy_engine(strategy_profile_to_id(normalized_profile))


def build_strategy_engine(strategy_id: str) -> SignalEngine:
    normalized_strategy_id = normalize_strategy_id(strategy_id)
    definition = strategy_definition(normalized_strategy_id)
    if definition.family == "momentum":
        if definition.profile == "LOW":
            return SimpleMomentumSignalEngine(
                strategy_id=definition.strategy_id,
                strategy_profile=definition.profile,
                trend_filter=default_trend_filter_settings(definition.profile),
            )
        if definition.profile == "MEDIUM":
            return BlitzMomentumSignalEngine(
                strategy_id=definition.strategy_id,
                strategy_profile=definition.profile,
                trend_filter=default_trend_filter_settings(definition.profile),
            )
        return RelaxedMomentumSignalEngine(
            strategy_id=definition.strategy_id,
            strategy_profile=definition.profile,
            trend_filter=default_trend_filter_settings(definition.profile),
        )
    if definition.family == "trend-pullback":
        return TrendPullbackSignalEngine(
            strategy_id=definition.strategy_id,
            strategy_profile=definition.profile,
            pullback_settings=default_trend_pullback_settings(definition.profile),
        )
    if definition.family == "mean-reversion":
        return MeanReversionSignalEngine(
            strategy_id=definition.strategy_id,
            strategy_profile=definition.profile,
            reversion_settings=default_mean_reversion_settings(definition.profile),
        )
    raise ValueError(f"Unsupported strategy family: {definition.family}")


@dataclass(frozen=True, slots=True)
class CompositeSignalEngine:
    engines: tuple[SignalEngine, ...]
    strategy_profiles: tuple[StrategyProfile, ...]
    strategy_ids: tuple[str, ...] = ()

    @property
    def strategy_name(self) -> str:
        return "composite-strategy"

    @property
    def required_candles(self) -> int:
        return max(engine.required_candles for engine in self.engines)

    def describe_parameters(self) -> dict[str, Any]:
        resolved_ids = self._resolved_strategy_ids()
        return {
            "strategy_ids": list(resolved_ids),
            "strategy_profiles": list(self._resolved_strategy_profiles()),
            "engines": {
                strategy_id: engine.describe_parameters()
                for strategy_id, engine in zip(resolved_ids, self.engines)
            },
        }

    def trade_tags(self) -> dict[str, str]:
        resolved_ids = self._resolved_strategy_ids()
        resolved_profiles = self._resolved_strategy_profiles()
        strategy_names = [engine.strategy_name for engine in self.engines]
        strategy_families = [strategy_family_id(strategy_id) for strategy_id in resolved_ids]
        return {
            "strategy_id": resolved_ids[0],
            "strategy_ids": ",".join(resolved_ids),
            "strategy_family": strategy_families[0],
            "strategy_families": ",".join(strategy_families),
            "strategy_profile": resolved_profiles[0],
            "strategy_profiles": ",".join(resolved_profiles),
            "strategy_name": strategy_names[0],
            "strategy_names": ",".join(strategy_names),
            "strategy_display": format_strategy_id_set_display(resolved_ids),
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
        resolved_ids = self._resolved_strategy_ids()
        contributing_signals: list[tuple[str, StrategyProfile, SignalEngine, SignalEvent]] = []
        for strategy_id, profile, engine in zip(resolved_ids, self._resolved_strategy_profiles(), self.engines):
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
                contributing_signals.append((strategy_id, profile, engine, signal))
        if not contributing_signals:
            return None

        directions = {signal.direction for _, _, _, signal in contributing_signals}
        if len(directions) > 1:
            strategy_ids = [strategy_id for strategy_id, _, _, _ in contributing_signals]
            profiles = [profile for _, profile, _, _ in contributing_signals]
            names = [engine.strategy_name for _, _, engine, _ in contributing_signals]
            families = [strategy_family_id(strategy_id) for strategy_id in strategy_ids]
            return SignalEvent(
                signal_id=f"signal-{uuid4().hex}",
                created_at_utc=signal_time_utc,
                strategy_version_id=strategy_version_id,
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                direction=contributing_signals[0][3].direction,
                intended_amount=stake_amount,
                intended_expiry_sec=expiry_sec,
                entry_reason="conflicting_strategy_signals",
                session_label=contributing_signals[0][3].session_label,
                signal_strength=max(signal.signal_strength or 0.0 for _, _, _, signal in contributing_signals),
                indicator_snapshot={
                    "strategy_ids": strategy_ids,
                    "strategy_families": families,
                    "strategy_profiles": profiles,
                    "strategy_names": names,
                    "conflicting_directions": sorted(direction.value for direction in directions),
                },
                market_snapshot={"merged_signal": True},
                is_filtered_out=True,
                filter_reason="conflicting_strategy_signals",
            )

        primary_strategy_id, primary_profile, primary_engine, primary_signal = contributing_signals[0]
        merged_strategy_ids = [strategy_id for strategy_id, _, _, _ in contributing_signals]
        merged_profiles = [profile for _, profile, _, _ in contributing_signals]
        merged_names = [engine.strategy_name for _, _, engine, _ in contributing_signals]
        merged_families = [strategy_family_id(strategy_id) for strategy_id in merged_strategy_ids]
        merged_indicator_snapshot = {
            **primary_signal.indicator_snapshot,
            "strategy_ids": merged_strategy_ids,
            "strategy_families": merged_families,
            "strategy_profiles": merged_profiles,
            "strategy_names": merged_names,
            "strategy_entry_reasons": [signal.entry_reason for _, _, _, signal in contributing_signals],
            "supporting_signal_ids": [signal.signal_id for _, _, _, signal in contributing_signals],
            "supporting_signal_strengths": [signal.signal_strength for _, _, _, signal in contributing_signals],
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
            entry_reason=" + ".join(dict.fromkeys(signal.entry_reason for _, _, _, signal in contributing_signals)),
            session_label=primary_signal.session_label,
            signal_strength=max(signal.signal_strength or 0.0 for _, _, _, signal in contributing_signals),
            indicator_snapshot=merged_indicator_snapshot,
            market_snapshot=merged_market_snapshot,
        )

    def _resolved_strategy_profiles(self) -> tuple[StrategyProfile, ...]:
        if self.strategy_profiles:
            return self.strategy_profiles
        return strategy_profiles_from_ids(self._resolved_strategy_ids())

    def _resolved_strategy_ids(self) -> tuple[str, ...]:
        if self.strategy_ids:
            return self.strategy_ids
        return tuple(strategy_profile_to_id(profile) for profile in self.strategy_profiles)

    def diagnose_no_signal(
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
    ) -> str | None:
        reasons: list[tuple[str, str]] = []
        for strategy_id, engine in zip(self._resolved_strategy_ids(), self.engines):
            diagnose_no_signal = getattr(engine, "diagnose_no_signal", None)
            if not callable(diagnose_no_signal):
                continue
            reason = diagnose_no_signal(
                strategy_version_id=strategy_version_id,
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                stake_amount=stake_amount,
                expiry_sec=expiry_sec,
                candles=candles,
                signal_time_utc=signal_time_utc,
            )
            if reason:
                reasons.append((strategy_id, reason))
        if not reasons:
            return None
        distinct_reasons = {reason for _, reason in reasons}
        if len(distinct_reasons) == 1:
            return reasons[0][1]
        return "; ".join(f"{strategy_id}:{reason}" for strategy_id, reason in reasons)


@dataclass(frozen=True, slots=True)
class MomentumSignalEvaluation:
    signal: SignalEvent | None
    no_signal_reason: str | None = None


def build_composite_signal_engine(profiles: Iterable[str]) -> SignalEngine:
    normalized_profiles = normalize_strategy_profiles(tuple(profiles))
    if len(normalized_profiles) == 1:
        return build_signal_engine(normalized_profiles[0])
    return CompositeSignalEngine(
        engines=tuple(build_signal_engine(profile) for profile in normalized_profiles),
        strategy_profiles=normalized_profiles,
    )


def build_selected_signal_engine(strategy_ids: Iterable[str]) -> SignalEngine:
    normalized_strategy_ids = normalize_strategy_ids(tuple(strategy_ids))
    if len(normalized_strategy_ids) == 1:
        return build_strategy_engine(normalized_strategy_ids[0])
    return CompositeSignalEngine(
        engines=tuple(build_strategy_engine(strategy_id) for strategy_id in normalized_strategy_ids),
        strategy_profiles=strategy_profiles_from_ids(normalized_strategy_ids),
        strategy_ids=normalized_strategy_ids,
    )


def _required_candles_for_mean_reversion(settings: MeanReversionSettings) -> int:
    return max(
        settings.bollinger_period,
        settings.rsi_period + 6,
        settings.stochastic_period + settings.stochastic_k_smoothing + settings.stochastic_d_period + 2,
        (settings.adx_period * 2) + 1,
        settings.atr_period + 1,
        settings.ema_period + 2,
        30,
    )


def _required_candles_for_trend_pullback(settings: TrendPullbackSettings) -> int:
    return max(
        settings.slow_ema_period + 3,
        (settings.adx_period * 2) + 1,
        settings.atr_period + 1,
        24,
    )


def _build_trend_pullback_signal(
    *,
    strategy_id: str,
    strategy_family: str,
    strategy_profile: StrategyProfile,
    strategy_name: str,
    strategy_version_id: str,
    asset: str,
    instrument_type: InstrumentType,
    timeframe_sec: int,
    stake_amount: float,
    expiry_sec: int,
    candles: list[Candle],
    signal_time_utc: datetime,
    settings: TrendPullbackSettings,
) -> SignalEvent | None:
    required_candles = _required_candles_for_trend_pullback(settings)
    relevant_candles = candles[-required_candles:]
    if len(relevant_candles) < required_candles:
        return None

    close_prices = [candle.close_price for candle in relevant_candles]
    fast_ema_current = _ema(close_prices, settings.fast_ema_period)
    fast_ema_previous = _ema(close_prices[:-1], settings.fast_ema_period)
    slow_ema_current = _ema(close_prices, settings.slow_ema_period)
    slow_ema_previous = _ema(close_prices[:-1], settings.slow_ema_period)
    adx_value = _adx(relevant_candles, settings.adx_period)
    atr_value = _atr(relevant_candles, settings.atr_period)
    pullback_candle = relevant_candles[-2]
    confirmation_candle = relevant_candles[-1]
    confirmation_body_ratio = _body_ratio(confirmation_candle)
    current_close = confirmation_candle.close_price
    if (
        fast_ema_current is None
        or fast_ema_previous is None
        or slow_ema_current is None
        or slow_ema_previous is None
        or adx_value is None
        or atr_value is None
        or current_close <= 0
    ):
        return None

    atr_pct = atr_value / current_close
    if atr_pct < settings.min_atr_pct or atr_pct > settings.max_atr_pct:
        return None
    if adx_value < settings.min_adx:
        return None

    trend_gap_pct = abs(fast_ema_current - slow_ema_current) / current_close
    if trend_gap_pct < settings.min_trend_gap_pct:
        return None

    bullish_trend = (
        fast_ema_current > slow_ema_current
        and fast_ema_current > fast_ema_previous
        and slow_ema_current >= slow_ema_previous
    )
    bearish_trend = (
        fast_ema_current < slow_ema_current
        and fast_ema_current < fast_ema_previous
        and slow_ema_current <= slow_ema_previous
    )

    entry_triggers: list[str] = []
    direction: TradeDirection | None = None
    if bullish_trend:
        touched_fast_ema = pullback_candle.low_price <= fast_ema_current * (1.0 + settings.max_pullback_touch_pct)
        held_slow_ema = pullback_candle.close_price >= slow_ema_current * (1.0 - settings.max_slow_ema_breach_pct)
        bullish_confirmation = (
            confirmation_candle.close_price > confirmation_candle.open_price
            and confirmation_body_ratio >= settings.min_confirmation_body_ratio
            and confirmation_candle.close_price > pullback_candle.high_price
            and confirmation_candle.close_price > fast_ema_current
        )
        if touched_fast_ema:
            entry_triggers.append("fast_ema_support")
        if held_slow_ema:
            entry_triggers.append("slow_ema_support")
        if bullish_confirmation:
            entry_triggers.append("bullish_confirmation_candle")
        if touched_fast_ema and held_slow_ema and bullish_confirmation:
            direction = TradeDirection.CALL
    elif bearish_trend:
        touched_fast_ema = pullback_candle.high_price >= fast_ema_current * (1.0 - settings.max_pullback_touch_pct)
        held_slow_ema = pullback_candle.close_price <= slow_ema_current * (1.0 + settings.max_slow_ema_breach_pct)
        bearish_confirmation = (
            confirmation_candle.close_price < confirmation_candle.open_price
            and confirmation_body_ratio >= settings.min_confirmation_body_ratio
            and confirmation_candle.close_price < pullback_candle.low_price
            and confirmation_candle.close_price < fast_ema_current
        )
        if touched_fast_ema:
            entry_triggers.append("fast_ema_resistance")
        if held_slow_ema:
            entry_triggers.append("slow_ema_resistance")
        if bearish_confirmation:
            entry_triggers.append("bearish_confirmation_candle")
        if touched_fast_ema and held_slow_ema and bearish_confirmation:
            direction = TradeDirection.PUT
    else:
        return None

    if direction is None:
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
        entry_reason="ema_pullback_confirmation",
        session_label=_infer_session_label(signal_time_utc.hour),
        signal_strength=max(trend_gap_pct, confirmation_body_ratio),
        indicator_snapshot={
            "strategy_id": strategy_id,
            "strategy_family": strategy_family,
            "strategy_profile": strategy_profile,
            "strategy_name": strategy_name,
            "pattern": "ema_pullback_confirmation",
            "fast_ema": fast_ema_current,
            "slow_ema": slow_ema_current,
            "trend_gap_pct": trend_gap_pct,
            "adx_value": adx_value,
            "atr_value": atr_value,
            "atr_pct": atr_pct,
            "confirmation_body_ratio": confirmation_body_ratio,
            "pullback_open": pullback_candle.open_price,
            "pullback_high": pullback_candle.high_price,
            "pullback_low": pullback_candle.low_price,
            "pullback_close": pullback_candle.close_price,
            "entry_triggers": entry_triggers,
        },
        market_snapshot={
            "last_opened_at_utc": confirmation_candle.opened_at_utc.isoformat(),
        },
    )


def _build_mean_reversion_signal(
    *,
    strategy_id: str,
    strategy_family: str,
    strategy_profile: StrategyProfile,
    strategy_name: str,
    strategy_version_id: str,
    asset: str,
    instrument_type: InstrumentType,
    timeframe_sec: int,
    stake_amount: float,
    expiry_sec: int,
    candles: list[Candle],
    signal_time_utc: datetime,
    settings: MeanReversionSettings,
) -> SignalEvent | None:
    required_candles = _required_candles_for_mean_reversion(settings)
    relevant_candles = candles[-required_candles:]
    if len(relevant_candles) < required_candles:
        return None

    close_prices = [candle.close_price for candle in relevant_candles]
    current_candle = relevant_candles[-1]
    current_close = current_candle.close_price
    if current_close <= 0:
        return None

    bollinger = _bollinger_bands(close_prices, settings.bollinger_period, settings.bollinger_stddev)
    rsi_values = _rsi_values(close_prices, settings.rsi_period)
    stochastic = _stochastic_values(
        relevant_candles,
        settings.stochastic_period,
        settings.stochastic_k_smoothing,
        settings.stochastic_d_period,
    )
    adx_value = _adx(relevant_candles, settings.adx_period)
    atr_value = _atr(relevant_candles, settings.atr_period)
    ema_current = _ema(close_prices, settings.ema_period)
    ema_previous = _ema(close_prices[:-1], settings.ema_period) if len(close_prices) > settings.ema_period else None
    if bollinger is None or len(rsi_values) < 2 or stochastic is None or adx_value is None or atr_value is None or ema_current is None or ema_previous is None:
        return None

    basis, upper_band, lower_band, stddev = bollinger
    current_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]
    current_k, current_d, previous_k, previous_d = stochastic
    atr_pct = atr_value / current_close
    ema_slope_pct = abs(ema_current - ema_previous) / current_close
    price_zscore = 0.0 if stddev <= 0 else (current_close - basis) / stddev
    lower_wick_ratio, upper_wick_ratio, body_ratio = _wick_and_body_ratios(current_candle)
    reversion_distance_pct = abs(basis - current_close) / current_close
    filter_context = {
        "strategy_id": strategy_id,
        "strategy_family": strategy_family,
        "strategy_profile": strategy_profile,
        "regime": "range",
        "bollinger_basis": basis,
        "bollinger_upper": upper_band,
        "bollinger_lower": lower_band,
        "bollinger_stddev": stddev,
        "band_width_pct": 0.0 if basis == 0 else (upper_band - lower_band) / basis,
        "price_zscore": price_zscore,
        "rsi": current_rsi,
        "prev_rsi": previous_rsi,
        "stoch_k": current_k,
        "stoch_d": current_d,
        "prev_stoch_k": previous_k,
        "prev_stoch_d": previous_d,
        "adx_value": adx_value,
        "atr_value": atr_value,
        "atr_pct": atr_pct,
        "ema_value": ema_current,
        "ema_slope_pct": ema_slope_pct,
        "lower_wick_ratio": lower_wick_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "body_ratio": body_ratio,
        "reversion_distance_pct": reversion_distance_pct,
        "pattern": "bollinger_rsi_reversion",
    }

    extreme_direction: TradeDirection | None = None
    if current_close <= lower_band or price_zscore <= -settings.zscore_threshold:
        extreme_direction = TradeDirection.CALL
    elif current_close >= upper_band or price_zscore >= settings.zscore_threshold:
        extreme_direction = TradeDirection.PUT
    else:
        return None

    if adx_value > settings.max_adx:
        return _filtered_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=extreme_direction,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            signal_time_utc=signal_time_utc,
            filter_reason="trend_too_strong_for_reversion",
            entry_reason="bollinger_rsi_reversion",
            filter_context={**filter_context, "regime": "trend"},
        )
    if atr_pct < settings.min_atr_pct or atr_pct > settings.max_atr_pct:
        return _filtered_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=extreme_direction,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            signal_time_utc=signal_time_utc,
            filter_reason="volatility_out_of_bounds",
            entry_reason="bollinger_rsi_reversion",
            filter_context=filter_context,
        )
    if ema_slope_pct > settings.max_ema_slope_pct:
        return _filtered_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=extreme_direction,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            signal_time_utc=signal_time_utc,
            filter_reason="trend_too_strong_for_reversion",
            entry_reason="bollinger_rsi_reversion",
            filter_context={**filter_context, "regime": "trend"},
        )
    if reversion_distance_pct < settings.min_reversion_distance_pct:
        return _filtered_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=extreme_direction,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            signal_time_utc=signal_time_utc,
            filter_reason="insufficient_reversion_room",
            entry_reason="bollinger_rsi_reversion",
            filter_context=filter_context,
        )

    entry_triggers: list[str] = []
    failed_triggers: list[str] = []

    if extreme_direction == TradeDirection.CALL:
        rsi_trigger = current_rsi <= settings.rsi_oversold and current_rsi >= previous_rsi
        stochastic_trigger = current_k <= settings.stochastic_oversold and current_d <= settings.stochastic_oversold and current_k > current_d and previous_k <= previous_d
        rejection_trigger = lower_wick_ratio >= settings.min_wick_ratio and upper_wick_ratio < lower_wick_ratio and body_ratio >= settings.min_body_recovery_ratio and current_close > current_candle.open_price
    else:
        rsi_trigger = current_rsi >= settings.rsi_overbought and current_rsi <= previous_rsi
        stochastic_trigger = current_k >= settings.stochastic_overbought and current_d >= settings.stochastic_overbought and current_k < current_d and previous_k >= previous_d
        rejection_trigger = upper_wick_ratio >= settings.min_wick_ratio and lower_wick_ratio < upper_wick_ratio and body_ratio >= settings.min_body_recovery_ratio and current_close < current_candle.open_price

    if rsi_trigger:
        entry_triggers.append("rsi_extreme_reversal")
    else:
        failed_triggers.append("rsi_extreme_reversal")
    if stochastic_trigger:
        entry_triggers.append("stochastic_reversal")
    else:
        failed_triggers.append("stochastic_reversal")
    if rejection_trigger:
        entry_triggers.append("rejection_candle")
    else:
        failed_triggers.append("rejection_candle")

    filter_context = {
        **filter_context,
        "confirmation_mode": "any",
        "entry_triggers": entry_triggers,
        "failed_triggers": failed_triggers,
    }
    if not entry_triggers:
        return _filtered_signal(
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=extreme_direction,
            stake_amount=stake_amount,
            expiry_sec=expiry_sec,
            signal_time_utc=signal_time_utc,
            filter_reason="reversion_confirmation_missing",
            entry_reason="bollinger_rsi_reversion",
            filter_context=filter_context,
        )

    return SignalEvent(
        signal_id=f"signal-{uuid4().hex}",
        created_at_utc=signal_time_utc,
        strategy_version_id=strategy_version_id,
        asset=asset,
        instrument_type=instrument_type,
        timeframe_sec=timeframe_sec,
        direction=extreme_direction,
        intended_amount=stake_amount,
        intended_expiry_sec=expiry_sec,
        entry_reason="bollinger_rsi_reversion",
        session_label=_infer_session_label(signal_time_utc.hour),
        signal_strength=abs(price_zscore),
        indicator_snapshot=filter_context,
        market_snapshot={
            "last_opened_at_utc": current_candle.opened_at_utc.isoformat(),
            "reversion_target_price": basis,
        },
    )


def _filtered_signal(
    *,
    strategy_version_id: str,
    asset: str,
    instrument_type: InstrumentType,
    timeframe_sec: int,
    direction: TradeDirection,
    stake_amount: float,
    expiry_sec: int,
    signal_time_utc: datetime,
    filter_reason: str,
    entry_reason: str,
    filter_context: dict[str, Any],
) -> SignalEvent:
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
        indicator_snapshot=filter_context,
        market_snapshot={},
        is_filtered_out=True,
        filter_reason=filter_reason,
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
    return _evaluate_aligned_momentum_signal(
        strategy_version_id=strategy_version_id,
        asset=asset,
        instrument_type=instrument_type,
        timeframe_sec=timeframe_sec,
        stake_amount=stake_amount,
        expiry_sec=expiry_sec,
        candles=candles,
        signal_time_utc=signal_time_utc,
        required_candles=required_candles,
        minimum_total_move_pct=minimum_total_move_pct,
        minimum_body_ratio=minimum_body_ratio,
        minimum_body_ratio_call=minimum_body_ratio_call,
        minimum_body_ratio_put=minimum_body_ratio_put,
        trend_filter=trend_filter,
        entry_reason=entry_reason,
        extra_snapshot=extra_snapshot,
    ).signal


def _evaluate_aligned_momentum_signal(
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
) -> MomentumSignalEvaluation:
    relevant_candles = candles[-required_candles:]
    if len(relevant_candles) < required_candles:
        return MomentumSignalEvaluation(signal=None, no_signal_reason="insufficient_candle_history")

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
        return MomentumSignalEvaluation(signal=None, no_signal_reason="pattern_not_aligned")

    first_close = close_prices[0]
    last_close = close_prices[-1]
    if first_close == 0:
        return MomentumSignalEvaluation(signal=None, no_signal_reason="invalid_reference_price")
    total_move_pct = abs((last_close - first_close) / first_close)
    if total_move_pct < minimum_total_move_pct:
        return MomentumSignalEvaluation(signal=None, no_signal_reason="pattern_move_too_small")

    filter_context, filter_reason = _evaluate_filter_context(
        candles=candles,
        relevant_candles=relevant_candles,
        timeframe_sec=timeframe_sec,
        direction=direction,
        trend_filter=trend_filter,
    )
    if filter_context is None:
        return MomentumSignalEvaluation(signal=None, no_signal_reason=filter_reason or "filter_context_unavailable")

    return MomentumSignalEvaluation(
        signal=SignalEvent(
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
        ),
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


def _bollinger_bands(values: list[float], period: int, stddev_multiplier: float) -> tuple[float, float, float, float] | None:
    if period <= 1 or len(values) < period:
        return None
    window = values[-period:]
    basis = sum(window) / period
    variance = sum((value - basis) ** 2 for value in window) / period
    stddev = math.sqrt(variance)
    return basis, basis + (stddev * stddev_multiplier), basis - (stddev * stddev_multiplier), stddev


def _rsi_values(values: list[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period + 1:
        return []
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_series: list[float] = [_rsi_from_averages(avg_gain, avg_loss)]
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        rsi_series.append(_rsi_from_averages(avg_gain, avg_loss))
    return rsi_series


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss <= 0:
        return 100.0
    rs_value = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs_value))


def _stochastic_values(
    candles: list[Candle],
    period: int,
    k_smoothing: int,
    d_period: int,
) -> tuple[float, float, float, float] | None:
    if period <= 0 or k_smoothing <= 0 or d_period <= 0:
        return None
    required_candles = period + k_smoothing + d_period
    if len(candles) < required_candles:
        return None
    raw_k_values: list[float] = []
    for end_index in range(period, len(candles) + 1):
        window = candles[end_index - period : end_index]
        highest_high = max(candle.high_price for candle in window)
        lowest_low = min(candle.low_price for candle in window)
        denominator = highest_high - lowest_low
        if denominator <= 0:
            raw_k_values.append(50.0)
            continue
        raw_k_values.append(((window[-1].close_price - lowest_low) / denominator) * 100.0)
    smoothed_k_values = _simple_moving_average_series(raw_k_values, k_smoothing)
    d_values = _simple_moving_average_series(smoothed_k_values, d_period)
    if len(smoothed_k_values) < 2 or len(d_values) < 2:
        return None
    current_k = smoothed_k_values[-1]
    previous_k = smoothed_k_values[-2]
    current_d = d_values[-1]
    previous_d = d_values[-2]
    return current_k, current_d, previous_k, previous_d


def _simple_moving_average_series(values: list[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        return []
    series: list[float] = []
    for end_index in range(period, len(values) + 1):
        window = values[end_index - period : end_index]
        series.append(sum(window) / period)
    return series


def _wick_and_body_ratios(candle: Candle) -> tuple[float, float, float]:
    total_range = candle.high_price - candle.low_price
    if total_range <= 0:
        return 0.0, 0.0, 0.0
    upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
    lower_wick = min(candle.open_price, candle.close_price) - candle.low_price
    body = abs(candle.close_price - candle.open_price)
    return lower_wick / total_range, upper_wick / total_range, body / total_range


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
    filter_context, _ = _evaluate_filter_context(
        candles=candles,
        relevant_candles=relevant_candles,
        timeframe_sec=timeframe_sec,
        direction=direction,
        trend_filter=trend_filter,
    )
    return filter_context


def _evaluate_filter_context(
    *,
    candles: list[Candle],
    relevant_candles: list[Candle],
    timeframe_sec: int,
    direction: TradeDirection,
    trend_filter: TrendFilterSettings,
) -> tuple[dict[str, Any] | None, str | None]:
    if len(candles) < _required_candles_for_filters(len(relevant_candles), trend_filter):
        return None, "insufficient_filter_history"

    current_close = relevant_candles[-1].close_price
    ema_value = _ema([candle.close_price for candle in candles], trend_filter.ema_period)
    if ema_value is None:
        return None, "ema_unavailable"
    if direction == TradeDirection.CALL and current_close <= ema_value:
        return None, "ema_trend_mismatch"
    if direction == TradeDirection.PUT and current_close >= ema_value:
        return None, "ema_trend_mismatch"

    adx_value = _adx(candles, trend_filter.adx_period)
    if adx_value is None or adx_value < trend_filter.adx_threshold:
        return None, "adx_below_threshold"

    atr_value = _atr(candles, trend_filter.atr_period)
    if atr_value is None or current_close <= 0:
        return None, "atr_unavailable"
    atr_pct = atr_value / current_close
    if atr_pct < trend_filter.min_atr_pct or atr_pct > trend_filter.max_atr_pct:
        return None, "atr_out_of_bounds"

    sr_distance_pct = _support_resistance_distance_pct(
        candles=candles,
        lookback=trend_filter.sr_lookback,
        current_close=current_close,
        direction=direction,
    )
    if sr_distance_pct is None or sr_distance_pct < trend_filter.min_sr_distance_pct:
        return None, "support_resistance_too_close"

    aligned_candles = _aggregate_candles(candles, trend_filter.alignment_timeframe_multiplier)
    aligned_ema = _ema([candle.close_price for candle in aligned_candles], trend_filter.alignment_ema_period)
    if aligned_ema is None:
        return None, "alignment_unavailable"
    aligned_close = aligned_candles[-1].close_price
    alignment_timeframe_sec = timeframe_sec * max(trend_filter.alignment_timeframe_multiplier, 1)
    if direction == TradeDirection.CALL and aligned_close <= aligned_ema:
        return None, "alignment_mismatch"
    if direction == TradeDirection.PUT and aligned_close >= aligned_ema:
        return None, "alignment_mismatch"

    return {
        "ema_trend_value": ema_value,
        "adx_value": adx_value,
        "atr_value": atr_value,
        "atr_pct": atr_pct,
        "support_resistance_distance_pct": sr_distance_pct,
        "alignment_timeframe_sec": alignment_timeframe_sec,
        "alignment_close": aligned_close,
        "alignment_ema": aligned_ema,
    }, None


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
