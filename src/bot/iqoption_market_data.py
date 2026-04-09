from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from os import getenv
from typing import Any, Callable
import time

from .config import AppConfig
from .iqoption_adapter import IQOptionAdapterError, IQOptionCredentials
from .market_data import Candle
from .models import InstrumentType


@dataclass(frozen=True)
class IQOptionMarketDataProvider:
    config: AppConfig
    credentials: IQOptionCredentials
    client_factory: Callable[[str, str], Any] | None = None

    def __post_init__(self) -> None:
        if self.config.app_mode != "PRACTICE":
            raise ValueError("IQOptionMarketDataProvider is restricted to PRACTICE mode during MVP.")
        object.__setattr__(self, "_client", None)

    @classmethod
    def from_environment(
        cls,
        config: AppConfig,
        client_factory: Callable[[str, str], Any] | None = None,
    ) -> IQOptionMarketDataProvider:
        email = getenv("IQOPTION_EMAIL")
        password = getenv("IQOPTION_PASSWORD")
        if not email or not password:
            raise IQOptionAdapterError("Missing IQOPTION_EMAIL or IQOPTION_PASSWORD in environment.")
        return cls(config=config, credentials=IQOptionCredentials(email=email, password=password), client_factory=client_factory)

    def connect(self) -> None:
        factory = self.client_factory or self._default_client_factory
        client = factory(self.credentials.email, self.credentials.password)
        status, reason = client.connect()
        if not status:
            raise IQOptionAdapterError(f"IQ Option market-data connect failed: {reason}")
        client.change_balance("PRACTICE")
        object.__setattr__(self, "_client", client)

    def reconnect_if_needed(self) -> bool:
        if self._client is None:
            self.connect()
            return True
        if self._client.check_connect():
            return True
        status, reason = self._client.connect()
        if not status:
            raise IQOptionAdapterError(f"IQ Option market-data reconnect failed: {reason}")
        self._client.change_balance("PRACTICE")
        return True

    def get_recent_candles(
        self,
        *,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        limit: int,
    ) -> list[Candle]:
        if limit <= 0:
            return []

        raw_candles = self._get_candles_with_retry(asset=asset, timeframe_sec=timeframe_sec, limit=limit)
        candles = [
            Candle(
                opened_at_utc=_to_datetime_utc(raw["from"]),
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                open_price=float(raw["open"]),
                high_price=float(raw["max"]),
                low_price=float(raw["min"]),
                close_price=float(raw["close"]),
                volume=float(raw["volume"]) if raw.get("volume") is not None else None,
            )
            for raw in raw_candles
        ]
        candles.sort(key=lambda candle: candle.opened_at_utc)
        return candles[-limit:]

    def _get_candles_with_retry(self, *, asset: str, timeframe_sec: int, limit: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(3):
            self.reconnect_if_needed()
            try:
                raw_candles = self._client.get_candles(asset, timeframe_sec, limit, time.time())
            except Exception as exc:
                last_error = exc
                logging.warning("IQ Option candle fetch failed for %s on attempt %s: %s", asset, attempt + 1, exc)
                self._force_reconnect()
                continue
            if raw_candles:
                return raw_candles

            logging.warning("IQ Option returned no candles for %s on attempt %s; reconnecting.", asset, attempt + 1)
            self._force_reconnect()

        if last_error is not None:
            raise IQOptionAdapterError(f"Unable to fetch candles for {asset} after reconnect attempts.") from last_error
        raise IQOptionAdapterError(f"Unable to fetch candles for {asset}: broker returned no candle data.")

    def _force_reconnect(self) -> None:
        object.__setattr__(self, "_client", None)
        self.connect()

    @staticmethod
    def _default_client_factory(email: str, password: str) -> Any:
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError as exc:  # pragma: no cover - depends on optional dependency
            raise IQOptionAdapterError(
                "iqoptionapi is not installed. Run 'python -m pip install -e .[iqoption]' before using IQOptionMarketDataProvider."
            ) from exc
        return IQ_Option(email, password)


def _to_datetime_utc(epoch_value: int | float) -> datetime:
    return datetime.fromtimestamp(float(epoch_value), tz=UTC)
