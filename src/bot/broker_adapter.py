from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .config import AppConfig
from .journal_service import JournalService
from .models import BrokerOrderAttempt, SignalEvent, TradeResult
from .trade_journal import TradeJournalRepository


class PracticeBrokerAdapter:
    def __init__(
        self,
        config: AppConfig,
        repository: TradeJournalRepository,
        journal_service: JournalService,
        broker_name: str = "practice-simulator",
    ):
        if config.app_mode != "PRACTICE":
            raise ValueError("PracticeBrokerAdapter only supports PRACTICE mode.")
        self._config = config
        self._repository = repository
        self._journal_service = journal_service
        self._broker_name = broker_name

    def submit_order(
        self,
        *,
        signal_event: SignalEvent,
        strategy_version_id: str,
        payout_snapshot: float | None = None,
        entry_price: float | None = None,
        tags: dict[str, str] | None = None,
    ):
        effective_payout = 0.8 if payout_snapshot is None else payout_snapshot
        trade_id = f"trade-{uuid4().hex}"
        broker_order_id = f"order-{uuid4().hex}"
        broker_position_id = f"position-{uuid4().hex}"
        order_attempt = BrokerOrderAttempt(
            trade_id=trade_id,
            signal_id=signal_event.signal_id,
            submitted_at_utc=datetime.now(UTC),
            broker_name=self._broker_name,
            account_mode=self._config.app_mode,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            asset=signal_event.asset,
            direction=signal_event.direction,
            amount=signal_event.intended_amount,
            expiry_sec=signal_event.intended_expiry_sec,
            payout_snapshot=effective_payout,
            submission_status="submitted",
            raw_request_json={
                "asset": signal_event.asset,
                "direction": signal_event.direction.value,
                "amount": signal_event.intended_amount,
            },
            raw_response_json={"accepted": True},
        )
        return self._journal_service.open_trade(
            trade_id=trade_id,
            signal_event=signal_event,
            strategy_version_id=strategy_version_id,
            account_mode=self._config.app_mode,
            payout_snapshot=effective_payout,
            entry_price=entry_price,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            tags=tags,
            order_attempt=order_attempt,
        )

    def reject_order(
        self,
        *,
        signal_event: SignalEvent,
        strategy_version_id: str,
        error_code: str,
        error_message: str,
        tags: dict[str, str] | None = None,
    ):
        trade_id = f"trade-{uuid4().hex}"
        order_attempt = BrokerOrderAttempt(
            trade_id=trade_id,
            signal_id=signal_event.signal_id,
            submitted_at_utc=datetime.now(UTC),
            broker_name=self._broker_name,
            account_mode=self._config.app_mode,
            asset=signal_event.asset,
            direction=signal_event.direction,
            amount=signal_event.intended_amount,
            expiry_sec=signal_event.intended_expiry_sec,
            submission_status="rejected",
            submission_error_code=error_code,
            submission_error_message=error_message,
            raw_request_json={"asset": signal_event.asset},
            raw_response_json={"accepted": False, "error_code": error_code},
        )
        return self._journal_service.reject_trade(
            trade_id=trade_id,
            signal_event=signal_event,
            strategy_version_id=strategy_version_id,
            account_mode=self._config.app_mode,
            error_code=error_code,
            error_message=error_message,
            order_attempt=order_attempt,
            tags=tags,
        )

    def resolve_trade(
        self,
        *,
        trade_id: str,
        result: TradeResult,
        exit_price: float | None = None,
        fees_abs: float = 0.0,
        close_reason: str = "expiry",
    ):
        trade = self._repository.get_trade(trade_id)
        if trade is None:
            raise ValueError(f"Unknown trade_id: {trade_id}")

        profit_loss_abs = self._calculate_profit_loss(trade.amount, trade.payout_snapshot, result, fees_abs)
        profit_loss_pct_risk = None if profit_loss_abs is None or trade.amount == 0 else profit_loss_abs / trade.amount
        return self._journal_service.close_trade(
            trade_id=trade_id,
            result=result,
            profit_loss_abs=profit_loss_abs,
            profit_loss_pct_risk=profit_loss_pct_risk,
            exit_price=exit_price,
            fees_abs=fees_abs,
            close_reason=close_reason,
        )

    @staticmethod
    def _calculate_profit_loss(
        amount: float,
        payout_snapshot: float | None,
        result: TradeResult,
        fees_abs: float,
    ) -> float | None:
        if result == TradeResult.WIN:
            payout = payout_snapshot or 0.0
            return (amount * payout) - fees_abs
        if result == TradeResult.LOSS:
            return (-amount) - fees_abs
        if result == TradeResult.BREAKEVEN:
            return -fees_abs
        return None
