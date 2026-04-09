from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .market_data import Candle


class KillSwitch:
    def __init__(self):
        self._reason: str | None = None

    @property
    def is_active(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    def stop(self, reason: str) -> None:
        self._reason = reason

    def clear(self) -> None:
        self._reason = None

    def refresh(self) -> None:
        return None


class FileKillSwitch(KillSwitch):
    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def refresh(self) -> None:
        if self._path.exists():
            self.stop("kill_switch_file_detected")


@dataclass(frozen=True, slots=True)
class StaleMarketDataGuard:
    max_data_age_sec: int

    def check(self, candles: list[Candle], now_utc: datetime) -> str | None:
        if not candles:
            return "no_market_data"
        latest = candles[-1]
        age_seconds = (now_utc - latest.opened_at_utc).total_seconds()
        if age_seconds > self.max_data_age_sec:
            return "stale_market_data"
        return None


@dataclass(frozen=True, slots=True)
class ReconnectBackoffPolicy:
    max_attempts: int = 3
    base_delay_sec: float = 1.0
    multiplier: float = 2.0
    max_delay_sec: float = 30.0

    def delays(self) -> list[float]:
        if self.max_attempts <= 0:
            return []
        values: list[float] = []
        delay = self.base_delay_sec
        for _ in range(self.max_attempts):
            values.append(min(delay, self.max_delay_sec))
            delay *= self.multiplier
        return values
