from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time
from uuid import uuid4

from .iqoption_adapter import IQOptionAdapter, IQOptionOrderUnavailableError
from .iqoption_market_data import IQOptionMarketDataProvider
from .models import InstrumentType, SessionLabel, SignalEvent, StrategyVersion, TradeDirection, TradeResult
from .runtime_logging import RuntimeEventLogger
from .trade_journal import TradeJournalRepository


@dataclass(frozen=True, slots=True)
class PracticeSmokeTestResult:
    status: str
    balance: float | None = None
    candle_count: int = 0
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PracticeOrderProbeResult:
    status: str
    trade_id: str | None = None
    result: str | None = None
    profit_loss_abs: float | None = None
    reason: str | None = None


class PracticeIntegrationHarness:
    def __init__(
        self,
        repository: TradeJournalRepository,
        market_data_provider: IQOptionMarketDataProvider,
        broker_adapter: IQOptionAdapter,
        event_logger: RuntimeEventLogger | None = None,
    ):
        self._repository = repository
        self._market_data_provider = market_data_provider
        self._broker_adapter = broker_adapter
        self._event_logger = event_logger

    def run_smoke_test(self, *, asset: str, instrument_type: InstrumentType, timeframe_sec: int, candle_limit: int) -> PracticeSmokeTestResult:
        try:
            self._market_data_provider.reconnect_if_needed()
            self._broker_adapter.reconnect_if_needed()
            candles = self._market_data_provider.get_recent_candles(
                asset=asset,
                instrument_type=instrument_type,
                timeframe_sec=timeframe_sec,
                limit=candle_limit,
            )
            balance = self._broker_adapter.get_balance()
        except Exception as exc:
            if self._event_logger is not None:
                self._event_logger.log(
                    severity="error",
                    event_type="practice_smoke_test_failed",
                    message="Practice smoke test failed.",
                    details={"error_type": type(exc).__name__},
                )
            return PracticeSmokeTestResult(status="failed", reason=type(exc).__name__)

        if self._event_logger is not None:
            self._event_logger.log(
                severity="info",
                event_type="practice_smoke_test_passed",
                message="Practice smoke test completed.",
                details={"asset": asset, "candle_count": len(candles)},
            )
        return PracticeSmokeTestResult(status="passed", balance=balance, candle_count=len(candles))

    def run_order_probe(
        self,
        *,
        asset: str,
        instrument_type: InstrumentType,
        direction: TradeDirection,
        timeframe_sec: int,
        amount: float,
        expiry_sec: int,
        wait_for_close: bool,
        poll_interval_sec: float,
        timeout_sec: float,
    ) -> PracticeOrderProbeResult:
        self._market_data_provider.reconnect_if_needed()
        self._broker_adapter.reconnect_if_needed()
        now_utc = datetime.now(UTC)
        strategy_version_id = f"probe-{instrument_type.value}-{asset.lower()}"
        self._repository.save_strategy_version(
            StrategyVersion(
                strategy_version_id=strategy_version_id,
                created_at_utc=now_utc,
                strategy_name="practice-order-probe",
                parameter_hash=f"probe-{instrument_type.value}-{direction.value}-{expiry_sec}",
                parameters={
                    "asset": asset,
                    "instrument_type": instrument_type.value,
                    "direction": direction.value,
                    "amount": amount,
                    "expiry_sec": expiry_sec,
                },
                created_by="practice-harness",
                approval_status="approved",
                change_reason="manual-practice-order-probe",
            )
        )
        candles = self._market_data_provider.get_recent_candles(
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            limit=3,
        )
        signal_event = SignalEvent(
            signal_id=f"signal-{uuid4().hex}",
            created_at_utc=now_utc,
            strategy_version_id=strategy_version_id,
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            direction=direction,
            intended_amount=amount,
            intended_expiry_sec=expiry_sec,
            entry_reason="practice_order_probe",
            session_label=SessionLabel.OFF_SESSION,
            market_snapshot={
                "recent_candle_count": len(candles),
                "latest_candle_at_utc": candles[-1].opened_at_utc.isoformat() if candles else None,
            },
        )
        try:
            trade = self._broker_adapter.submit_order(
                signal_event=signal_event,
                strategy_version_id=strategy_version_id,
                tags={"probe": "practice_order", "signal_fingerprint": signal_event.signal_id},
            )
        except IQOptionOrderUnavailableError as exc:
            self._log(
                severity="warning",
                event_type="practice_order_probe_skipped",
                message="Practice order probe skipped because the broker reported the pair as unavailable.",
                details={"asset": asset, "instrument_type": instrument_type.value, "reason": str(exc)},
            )
            return PracticeOrderProbeResult(status="skipped", reason="market_closed_or_unavailable")
        self._log(
            severity="warning",
            event_type="practice_order_probe_submitted",
            message="Practice order probe submitted.",
            details={"trade_id": trade.trade_id, "asset": asset, "instrument_type": instrument_type.value},
        )

        if trade.result in {TradeResult.REJECTED, TradeResult.ERROR, TradeResult.CANCELLED}:
            self._log(
                severity="warning",
                event_type="practice_order_probe_rejected",
                message="Practice order probe was not accepted by the broker.",
                details={
                    "trade_id": trade.trade_id,
                    "result": trade.result.value if trade.result is not None else None,
                    "error_code": trade.error_code,
                },
            )
            return PracticeOrderProbeResult(
                status="rejected",
                trade_id=trade.trade_id,
                result=trade.result.value if trade.result is not None else None,
                profit_loss_abs=trade.profit_loss_abs,
                reason=trade.error_code or trade.error_message or "broker_rejected",
            )

        if not wait_for_close:
            return PracticeOrderProbeResult(status="submitted", trade_id=trade.trade_id)

        start_time = time.monotonic()
        while (time.monotonic() - start_time) <= timeout_sec:
            closed_trade = self._broker_adapter.poll_trade_result(trade.trade_id)
            if closed_trade is not None:
                self._log(
                    severity="info",
                    event_type="practice_order_probe_closed",
                    message="Practice order probe closed.",
                    details={
                        "trade_id": closed_trade.trade_id,
                        "result": closed_trade.result.value if closed_trade.result is not None else None,
                    },
                )
                return PracticeOrderProbeResult(
                    status="closed",
                    trade_id=closed_trade.trade_id,
                    result=closed_trade.result.value if closed_trade.result is not None else None,
                    profit_loss_abs=closed_trade.profit_loss_abs,
                )
            time.sleep(poll_interval_sec)

        self._log(
            severity="warning",
            event_type="practice_order_probe_timeout",
            message="Practice order probe timed out waiting for close.",
            details={"trade_id": trade.trade_id},
        )
        return PracticeOrderProbeResult(status="timeout", trade_id=trade.trade_id, reason="close_timeout")

    def _log(self, *, severity: str, event_type: str, message: str, details: dict) -> None:
        if self._event_logger is not None:
            self._event_logger.log(severity=severity, event_type=event_type, message=message, details=details)
