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


class IQOptionOrderUnavailableError(IQOptionAdapterError):
    """Raised when an IQ Option asset cannot accept a new order right now."""


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
            raise IQOptionOrderUnavailableError(f"Payout unavailable for asset: {signal_event.asset}")
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
            raise IQOptionOrderUnavailableError(
                f"Broker rejected a new order for {signal_event.asset}; the pair is likely closed or temporarily unavailable."
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
        socket_value = self._poll_binary_result_from_socket(broker_id)
        if socket_value is not None:
            return socket_value

        async_order_value = self._poll_binary_result_from_async_order(broker_id)
        if async_order_value is not None:
            return async_order_value

        recent_closed_value = self._poll_binary_result_from_cached_recent_closed_options(broker_id)
        if recent_closed_value is not None:
            return recent_closed_value

        if getattr(self._client, "api", None) is None:
            for method_name in ("check_win_v4", "check_win_v3", "check_win_v2"):
                method = getattr(self._client, method_name, None)
                if method is None:
                    continue
                value = method(broker_id) if method_name != "check_win_v2" else method(broker_id, 0)
                normalized_value = self._normalize_binary_poll_value(value)
                if normalized_value is not None:
                    return normalized_value
        return None

    def _poll_binary_result_from_async_order(self, broker_id: int) -> float | None:
        get_async_order = getattr(self._client, "get_async_order", None)
        if not callable(get_async_order):
            return None
        try:
            async_order = get_async_order(broker_id)
        except Exception:
            return None
        if not isinstance(async_order, dict):
            return None
        option_closed = async_order.get("option-closed")
        if not isinstance(option_closed, dict):
            return None
        message = option_closed.get("msg")
        if not isinstance(message, dict):
            return None
        profit_amount = message.get("profit_amount")
        amount = message.get("amount")
        if profit_amount is None or amount is None:
            return None
        return float(profit_amount) - float(amount)

    def _poll_binary_result_from_socket(self, broker_id: int) -> float | None:
        api = getattr(self._client, "api", None)
        if api is None:
            return None
        socket_option_closed = getattr(api, "socket_option_closed", None)
        if not isinstance(socket_option_closed, dict):
            return None
        raw_value = socket_option_closed.get(broker_id)
        if raw_value is None:
            raw_value = socket_option_closed.get(str(broker_id))
        return self._normalize_binary_poll_value(raw_value)

    def _poll_binary_result_from_cached_recent_closed_options(self, broker_id: int) -> float | None:
        api = getattr(self._client, "api", None)
        if api is None:
            return None
        payload = getattr(api, "get_options_v2_data", None)
        if not isinstance(payload, dict):
            return None
        message = payload.get("msg")
        if not isinstance(message, dict):
            return None
        closed_options = message.get("closed_options")
        if not isinstance(closed_options, list):
            return None

        for option in closed_options:
            if not isinstance(option, dict):
                continue
            option_id = option.get("id")
            if isinstance(option_id, list) and option_id:
                option_id = option_id[0]
            if option_id in {broker_id, str(broker_id)}:
                return self._normalize_binary_poll_value((option.get("win"), self._profit_from_closed_option(option)))
        return None

    @classmethod
    def _normalize_binary_poll_value(cls, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, tuple) and len(value) >= 2:
            profit_loss = value[1]
            if profit_loss is None:
                return None
            return float(profit_loss)
        if isinstance(value, dict):
            message = value.get("msg")
            if isinstance(message, dict):
                return cls._profit_from_closed_option(message)
            result = value.get("result")
            if isinstance(result, dict):
                data = result.get("data")
                if isinstance(data, dict):
                    for option_payload in data.values():
                        if not isinstance(option_payload, dict):
                            continue
                        win = option_payload.get("win")
                        if win in (None, ""):
                            continue
                        profit = option_payload.get("profit")
                        deposit = option_payload.get("deposit")
                        if profit is None or deposit is None:
                            continue
                        return float(profit) - float(deposit)
        return None

    @staticmethod
    def _profit_from_closed_option(option_payload: dict[str, Any]) -> float | None:
        win_state = option_payload.get("win")
        if win_state in (None, ""):
            return None
        if win_state == "equal":
            return 0.0
        if win_state == "loose":
            stake = option_payload.get("sum")
            if stake is None:
                return None
            return float(stake) * -1.0
        win_amount = option_payload.get("win_amount")
        stake = option_payload.get("sum")
        if win_amount is None or stake is None:
            return None
        return float(win_amount) - float(stake)

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
