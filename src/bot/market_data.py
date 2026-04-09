from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
from pathlib import Path
from typing import Protocol

from .models import InstrumentType


@dataclass(frozen=True, slots=True)
class Candle:
    opened_at_utc: datetime
    asset: str
    instrument_type: InstrumentType
    timeframe_sec: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None = None


class MarketDataProvider(Protocol):
    def get_recent_candles(
        self,
        *,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        limit: int,
    ) -> list[Candle]: ...


class CsvMarketDataProvider:
    def __init__(self, csv_path: Path):
        self._csv_path = csv_path

    def get_recent_candles(
        self,
        *,
        asset: str,
        instrument_type: InstrumentType,
        timeframe_sec: int,
        limit: int,
    ) -> list[Candle]:
        matches: list[Candle] = []
        with self._csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("asset") != asset:
                    continue
                if row.get("instrument_type") != instrument_type.value:
                    continue
                if int(row.get("timeframe_sec", 0)) != timeframe_sec:
                    continue
                matches.append(
                    Candle(
                        opened_at_utc=datetime.fromisoformat(row["opened_at_utc"]),
                        asset=row["asset"],
                        instrument_type=InstrumentType(row["instrument_type"]),
                        timeframe_sec=int(row["timeframe_sec"]),
                        open_price=float(row["open_price"]),
                        high_price=float(row["high_price"]),
                        low_price=float(row["low_price"]),
                        close_price=float(row["close_price"]),
                        volume=_parse_optional_float(row.get("volume")),
                    )
                )
        matches.sort(key=lambda candle: candle.opened_at_utc)
        if limit <= 0:
            return []
        return matches[-limit:]


def _parse_optional_float(raw_value: str | None) -> float | None:
    if raw_value in (None, ""):
        return None
    return float(raw_value)
