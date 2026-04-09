from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from os import getenv
from typing import Any, Callable
from uuid import uuid4

from .config import AppConfig
from .journal_service import JournalService
from .models import BrokerOrderAttempt, InstrumentType, SignalEvent, TradeResult
from .trade_journal import TradeJournalRepository


class IQOptionAdapterError(RuntimeError):
    """Raised when the IQ Option adapter cannot complete an operation safely."""


@dataclass(frozen=True)
class IQOptionCredentials:
    email: str
    password: str


class IQOptionAdapter:
    def __init__(
        self,
        config: AppConfig,
        repository: TradeJournalRepository,
        journal_service: JournalService,
        credentials: IQOptionCredentials,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        if config.app_mode != "PRACTICE":
            raise ValueError("IQOptionAdapter is restricted to PRACTICE mode during MVP.")
        self._config = config
        self._repository = repository
        self._journal_service = journal_service
        self._credentials = credentials
        self._client_factory = client_factory or self._default_client_factory
        self._client: Any | None = None

    @classmethod
    def from_environment(
        cls,
        config: AppConfig,
        repository: TradeJournalRepository,
        journal_service: JournalService,
        client_factory: Callable[[str, str], Any] | None = None,
    ) -> IQOptionAdapter:
        email = getenv("IQOPTION_EMAIL")
        password = getenv("IQOPTION_PASSWORD")
        if not email or not password:
            raise IQOptionAdapterError("Missing IQOPTION_EMAIL or IQOPTION_PASSWORD in environment.")
        return cls(
            config=config,
            repository=repository,
            journal_service=journal_service,
            credentials=IQOptionCredentials(email=email, password=password),
            client_factory=client_factory,
        )

    def connect(self) -> None:
        client = self._client_factory(self._credentials.email, self._credentials.password)
        status, reason = client.connect()
        if not status:
            if reason == "2FA":
                raise IQOptionAdapterError("IQ Option 2FA is enabled and blocks unattended MVP automation.")
            raise IQOptionAdapterError(f"IQ Option connect failed: {reason}")
        self._client = client
        self._set_practice_mode()

    def is_connected(self) -> bool:
        return self._client is not None and bool(self._client.check_connect())

    def reconnect_if_needed(self) -> bool:
        if self._client is None:
            self.connect()
            return True
        if self._client.check_connect():
            return True
        status, reason = self._client.connect()
        if not status:
            raise IQOptionAdapterError(f"IQ Option reconnect failed: {reason}")
        self._set_practice_mode()
        return True

    def get_balance(self) -> float:
        self._require_connected()
        return float(self._client.get_balance())

    def get_payout(self, signal_event: SignalEvent) -> float:
        self._require_connected()
        if signal_event.instrument_type == InstrumentType.DIGITAL:
            return float(self._client.get_digital_payout(signal_event.asset)) / 100.0
        profits = self._client.get_all_profit()
        payout = profits.get(signal_event.asset, {}).get("turbo")
        if payout is None:
            raise IQOptionAdapterError(f"Payout unavailable for asset: {signal_event.asset}")
        return float(payout)

    def submit_order(
        self,
        *,
        signal_event: SignalEvent,
        strategy_version_id: str,
        tags: dict[str, str] | None = None,
    ):
        self.reconnect_if_needed()
        payout_snapshot = self.get_payout(signal_event)
        trade_id = f"trade-{uuid4().hex}"
        submitted_at = datetime.now(UTC)
        raw_request = {
            "asset": signal_event.asset,
            "direction": signal_event.direction.value,
            "amount": signal_event.intended_amount,
            "expiry_sec": signal_event.intended_expiry_sec,
            "instrument_type": signal_event.instrument_type.value,
        }

        if signal_event.instrument_type == InstrumentType.DIGITAL:
            status, broker_order_id = self._client.buy_digital_spot_v2(
                signal_event.asset,
                signal_event.intended_amount,
                signal_event.direction.value.upper(),
                self._expiry_to_minutes(signal_event.intended_expiry_sec),
            )
            broker_position_id = broker_order_id if status else None
        else:
            buy_response = self._client.buy(
                signal_event.intended_amount,
                signal_event.asset,
                signal_event.direction.value,
                self._expiry_to_minutes(signal_event.intended_expiry_sec),
            )
            status, broker_order_id = self._normalize_binary_buy_response(buy_response)
            broker_position_id = broker_order_id if status else None

        order_attempt = BrokerOrderAttempt(
            trade_id=trade_id,
            signal_id=signal_event.signal_id,
            submitted_at_utc=submitted_at,
            broker_name="iqoption",
            account_mode=self._config.app_mode,
            broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
            broker_position_id=str(broker_position_id) if broker_position_id is not None else None,
            asset=signal_event.asset,
            direction=signal_event.direction,
            amount=signal_event.intended_amount,
            expiry_sec=signal_event.intended_expiry_sec,
            payout_snapshot=payout_snapshot,
            submission_status="submitted" if status else "rejected",
            submission_error_code=None if status else "BUY_FAILED",
            submission_error_message=None if status else "broker returned unsuccessful buy response",
            raw_request_json=raw_request,
            raw_response_json={"status": status, "broker_order_id": broker_order_id},
        )

        if not status:
            return self._journal_service.reject_trade(
                trade_id=trade_id,
                signal_event=signal_event,
                strategy_version_id=strategy_version_id,
                account_mode=self._config.app_mode,
                error_code="BUY_FAILED",
                error_message="broker returned unsuccessful buy response",
                order_attempt=order_attempt,
                tags=tags,
            )

        return self._journal_service.open_trade(
            trade_id=trade_id,
            signal_event=signal_event,
            strategy_version_id=strategy_version_id,
            account_mode=self._config.app_mode,
            payout_snapshot=payout_snapshot,
            broker_order_id=str(broker_order_id),
            broker_position_id=str(broker_position_id),
            tags=tags,
            order_attempt=order_attempt,
        )

    def poll_trade_result(self, trade_id: str):
        self.reconnect_if_needed()
        trade = self._repository.get_trade(trade_id)
        if trade is None:
            raise IQOptionAdapterError(f"Unknown trade_id: {trade_id}")
        if trade.closed_at_utc is not None and trade.result is not None:
            return trade
        broker_id = trade.broker_position_id or trade.broker_order_id
        if broker_id is None:
            raise IQOptionAdapterError(f"Trade {trade_id} has no broker identifier recorded.")

        if trade.instrument_type == InstrumentType.DIGITAL:
            is_closed, pnl = self._client.check_win_digital(int(broker_id))
            if not is_closed:
                return None
            result = self._map_pnl_to_result(float(pnl))
            normalized = None if trade.amount == 0 else float(pnl) / trade.amount
            return self._journal_service.close_trade(
                trade_id=trade_id,
                result=result,
                profit_loss_abs=float(pnl),
                profit_loss_pct_risk=normalized,
                close_reason="broker_poll",
            )

        pnl = self._poll_binary_result(int(broker_id))
        if pnl is None:
            return None
        result = self._map_pnl_to_result(float(pnl))
        normalized = None if trade.amount == 0 else float(pnl) / trade.amount
        return self._journal_service.close_trade(
            trade_id=trade_id,
            result=result,
            profit_loss_abs=float(pnl),
            profit_loss_pct_risk=normalized,
            close_reason="broker_poll",
        )

    def _poll_binary_result(self, broker_id: int) -> float | None:
        for method_name in ("check_win_v4", "check_win_v3", "check_win_v2"):
            method = getattr(self._client, method_name, None)
            if method is None:
                continue
            value = method(broker_id)
            if value is not None:
                return float(value)
        return None

    def _set_practice_mode(self) -> None:
        self._require_connected()
        self._client.change_balance("PRACTICE")

    def _require_connected(self) -> None:
        if self._client is None:
            raise IQOptionAdapterError("IQ Option client is not connected.")

    @staticmethod
    def _default_client_factory(email: str, password: str) -> Any:
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError as exc:  # pragma: no cover - depends on optional dependency
            raise IQOptionAdapterError(
                "iqoptionapi is not installed. Run 'python -m pip install -e .[iqoption]' before using IQOptionAdapter."
            ) from exc
        return IQ_Option(email, password)

    @staticmethod
    def _normalize_binary_buy_response(buy_response: Any) -> tuple[bool, Any | None]:
        if isinstance(buy_response, tuple) and len(buy_response) == 2:
            status, broker_order_id = buy_response
            return bool(status), broker_order_id
        return bool(buy_response), buy_response

    @staticmethod
    def _expiry_to_minutes(expiry_sec: int) -> int:
        return max(1, expiry_sec // 60)

    @staticmethod
    def _map_pnl_to_result(profit_loss_abs: float) -> TradeResult:
        if profit_loss_abs > 0:
            return TradeResult.WIN
        if profit_loss_abs < 0:
            return TradeResult.LOSS
        return TradeResult.BREAKEVEN
