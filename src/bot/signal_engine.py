from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import uuid4

from .market_data import Candle
from .models import InstrumentType, SessionLabel, SignalEvent, TradeDirection


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


@dataclass(frozen=True, slots=True)
class SimpleMomentumSignalEngine:
    confirmation_candles: int = 3
    minimum_total_move_pct: float = 0.0001
    minimum_body_ratio: float = 0.35

    @property
    def strategy_name(self) -> str:
        return "simple-momentum"

    @property
    def required_candles(self) -> int:
        return self.confirmation_candles

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "confirmation_candles": self.confirmation_candles,
            "minimum_total_move_pct": self.minimum_total_move_pct,
            "minimum_body_ratio": self.minimum_body_ratio,
        }

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
            entry_reason="three_candle_momentum",
            extra_snapshot={"pattern": "aligned_momentum"},
        )


@dataclass(frozen=True, slots=True)
class BlitzMomentumSignalEngine:
    confirmation_candles: int = 2
    minimum_total_move_pct: float = 0.00012
    minimum_body_ratio_call: float = 0.55
    minimum_body_ratio_put: float = 0.45

    @property
    def strategy_name(self) -> str:
        return "blitz-momentum"

    @property
    def required_candles(self) -> int:
        return self.confirmation_candles

    def describe_parameters(self) -> dict[str, Any]:
        return {
            "confirmation_candles": self.confirmation_candles,
            "minimum_total_move_pct": self.minimum_total_move_pct,
            "minimum_body_ratio_call": self.minimum_body_ratio_call,
            "minimum_body_ratio_put": self.minimum_body_ratio_put,
            "recommended_timeframe_sec": 30,
            "recommended_expiry_sec": 60,
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
            entry_reason="two_candle_blitz",
            extra_snapshot={"pattern": "aligned_momentum_blitz"},
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
