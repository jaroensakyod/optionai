from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from .models import SystemEventRecord
from .trade_journal import TradeJournalRepository


class RuntimeEventLogger:
    def __init__(self, repository: TradeJournalRepository, log_dir: Path, component: str):
        self._repository = repository
        self._log_dir = log_dir
        self._component = component

    def log(self, *, severity: str, event_type: str, message: str, details: dict | None = None) -> SystemEventRecord:
        event = SystemEventRecord(
            event_id=f"event-{uuid4().hex}",
            occurred_at_utc=datetime.now(UTC),
            severity=severity,
            component=self._component,
            event_type=event_type,
            message=message,
            details=details or {},
        )
        self._repository.save_system_event(event)
        self._write_jsonl(event)
        return event

    def _write_jsonl(self, event: SystemEventRecord) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{event.occurred_at_utc.date().isoformat()}-events.jsonl"
        payload = {
            "event_id": event.event_id,
            "occurred_at_utc": event.occurred_at_utc.isoformat(),
            "severity": event.severity,
            "component": event.component,
            "event_type": event.event_type,
            "message": event.message,
            "details": event.details,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
