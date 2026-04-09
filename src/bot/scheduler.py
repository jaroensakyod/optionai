from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Callable, Protocol

from .bot_runner import BotRunResult, BotRunner, RunnerPlan
from .runtime_logging import RuntimeEventLogger
from .safety import KillSwitch, ReconnectBackoffPolicy


class Reconnectable(Protocol):
    def reconnect_if_needed(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    poll_interval_sec: float = 5.0
    cycles: int = 1


class BotScheduler:
    def __init__(
        self,
        runner: BotRunner,
        *,
        reconnectables: list[Reconnectable] | None = None,
        kill_switch: KillSwitch | None = None,
        reconnect_backoff_policy: ReconnectBackoffPolicy | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        event_logger: RuntimeEventLogger | None = None,
    ):
        self._runner = runner
        self._reconnectables = reconnectables or []
        self._kill_switch = kill_switch
        self._reconnect_backoff_policy = reconnect_backoff_policy or ReconnectBackoffPolicy()
        self._sleep_fn = sleep_fn or time.sleep
        self._event_logger = event_logger

    def run(self, plan: RunnerPlan, config: SchedulerConfig) -> list[BotRunResult]:
        results: list[BotRunResult] = []
        for cycle_index in range(config.cycles):
            self._refresh_kill_switch()
            if self._kill_switch is not None and self._kill_switch.is_active:
                self._log_event("critical", "scheduler_stopped", "Scheduler stopped by kill switch.", {"reason": self._kill_switch.reason})
                results.append(BotRunResult(status="stopped", reason=self._kill_switch.reason))
                break

            try:
                result = self._runner.run_once(plan, now_utc=datetime.now(UTC))
            except Exception as exc:
                self._log_event("error", "scheduler_error", "Scheduler cycle raised an exception.", {"error_type": type(exc).__name__})
                if self._attempt_recovery():
                    self._log_event("warning", "scheduler_recovered", "Scheduler recovered after reconnect attempts.", {"error_type": type(exc).__name__})
                    results.append(BotRunResult(status="recovered", reason=type(exc).__name__))
                else:
                    if self._kill_switch is not None:
                        self._kill_switch.stop(f"recovery_failed:{type(exc).__name__}")
                    self._log_event("critical", "scheduler_recovery_failed", "Scheduler could not recover.", {"error_type": type(exc).__name__})
                    results.append(BotRunResult(status="error", reason=type(exc).__name__))
                    break
            else:
                results.append(result)

            if cycle_index < (config.cycles - 1):
                self._sleep_fn(config.poll_interval_sec)
        return results

    def _attempt_recovery(self) -> bool:
        if not self._reconnectables:
            return False
        for delay in self._reconnect_backoff_policy.delays():
            recovered = True
            for reconnectable in self._reconnectables:
                try:
                    reconnectable.reconnect_if_needed()
                except Exception:
                    recovered = False
                    break
            if recovered:
                return True
            self._sleep_fn(delay)
        return False

    def _refresh_kill_switch(self) -> None:
        if self._kill_switch is not None:
            self._kill_switch.refresh()

    def _log_event(self, severity: str, event_type: str, message: str, details: dict[str, str | None]) -> None:
        if self._event_logger is not None:
            self._event_logger.log(severity=severity, event_type=event_type, message=message, details=details)
