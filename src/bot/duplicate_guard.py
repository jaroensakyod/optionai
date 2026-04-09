from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json

from .models import SignalEvent
from .trade_journal import TradeJournalRepository


@dataclass(frozen=True, slots=True)
class DuplicateCheckResult:
    prevented: bool
    fingerprint: str
    matched_trade_id: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateSignalGuard:
    repository: TradeJournalRepository
    window_sec: int = 120

    def check(self, *, signal_event: SignalEvent, account_mode: str, now_utc: datetime) -> DuplicateCheckResult:
        fingerprint = signal_fingerprint(signal_event)
        duplicate_trade = self.repository.find_recent_trade_by_fingerprint(
            account_mode=account_mode,
            asset=signal_event.asset,
            timeframe_sec=signal_event.timeframe_sec,
            expiry_sec=signal_event.intended_expiry_sec,
            fingerprint=fingerprint,
            opened_after_utc=now_utc - timedelta(seconds=self.window_sec),
        )
        if duplicate_trade is None:
            return DuplicateCheckResult(prevented=False, fingerprint=fingerprint)
        return DuplicateCheckResult(prevented=True, fingerprint=fingerprint, matched_trade_id=duplicate_trade.trade_id)


def signal_fingerprint(signal_event: SignalEvent) -> str:
    payload = {
        "asset": signal_event.asset,
        "instrument_type": signal_event.instrument_type.value,
        "timeframe_sec": signal_event.timeframe_sec,
        "direction": signal_event.direction.value,
        "entry_reason": signal_event.entry_reason,
        "intended_amount": signal_event.intended_amount,
        "intended_expiry_sec": signal_event.intended_expiry_sec,
        "indicator_snapshot": signal_event.indicator_snapshot,
        "market_snapshot": signal_event.market_snapshot,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
