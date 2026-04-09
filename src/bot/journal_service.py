from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from .models import BrokerOrderAttempt, SignalEvent, TradeJournalRecord, TradeResult
from .trade_journal import TradeJournalRepository


class JournalService:
    def __init__(self, repository: TradeJournalRepository):
        self._repository = repository

    def register_signal(self, signal_event: SignalEvent) -> None:
        self._repository.save_signal_event(signal_event)

    def open_trade(
        self,
        *,
        trade_id: str,
        signal_event: SignalEvent,
        strategy_version_id: str,
        account_mode: str,
        amount: float | None = None,
        expiry_sec: int | None = None,
        payout_snapshot: float | None = None,
        entry_price: float | None = None,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        tags: dict[str, str] | None = None,
        order_attempt: BrokerOrderAttempt | None = None,
    ) -> TradeJournalRecord:
        self.register_signal(signal_event)
        now = datetime.now(UTC)
        trade = TradeJournalRecord(
            trade_id=trade_id,
            signal_id=signal_event.signal_id,
            strategy_version_id=strategy_version_id,
            opened_at_utc=now,
            closed_at_utc=None,
            asset=signal_event.asset,
            instrument_type=signal_event.instrument_type,
            timeframe_sec=signal_event.timeframe_sec,
            direction=signal_event.direction,
            amount=amount if amount is not None else signal_event.intended_amount,
            expiry_sec=expiry_sec if expiry_sec is not None else signal_event.intended_expiry_sec,
            account_mode=account_mode,
            entry_price=entry_price,
            payout_snapshot=payout_snapshot,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            created_at_utc=now,
            updated_at_utc=now,
        )
        self._repository.upsert_trade(trade)
        if tags:
            self._repository.replace_trade_tags(trade_id, tags)
        if order_attempt is not None:
            self._repository.save_broker_order(order_attempt)
        return trade

    def reject_trade(
        self,
        *,
        trade_id: str,
        signal_event: SignalEvent,
        strategy_version_id: str,
        account_mode: str,
        error_code: str,
        error_message: str,
        order_attempt: BrokerOrderAttempt,
        tags: dict[str, str] | None = None,
    ) -> TradeJournalRecord:
        trade = self.open_trade(
            trade_id=trade_id,
            signal_event=signal_event,
            strategy_version_id=strategy_version_id,
            account_mode=account_mode,
            order_attempt=order_attempt,
            tags=tags,
        )
        return self.close_trade(
            trade_id=trade.trade_id,
            result=TradeResult.REJECTED,
            profit_loss_abs=None,
            profit_loss_pct_risk=None,
            close_reason="broker_rejected",
            error_code=error_code,
            error_message=error_message,
        )

    def close_trade(
        self,
        *,
        trade_id: str,
        result: TradeResult,
        profit_loss_abs: float | None,
        profit_loss_pct_risk: float | None,
        exit_price: float | None = None,
        fees_abs: float = 0.0,
        close_reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> TradeJournalRecord:
        existing_trade = self._repository.get_trade(trade_id)
        if existing_trade is None:
            raise ValueError(f"Unknown trade_id: {trade_id}")

        closed_at = datetime.now(UTC)
        duration_ms = int((closed_at - existing_trade.opened_at_utc).total_seconds() * 1000)
        updated_trade = replace(
            existing_trade,
            closed_at_utc=closed_at,
            result=result,
            profit_loss_abs=profit_loss_abs,
            profit_loss_pct_risk=profit_loss_pct_risk,
            exit_price=exit_price,
            fees_abs=fees_abs,
            duration_ms=duration_ms,
            close_reason=close_reason,
            error_code=error_code,
            error_message=error_message,
            updated_at_utc=closed_at,
        )
        self._repository.upsert_trade(updated_trade)
        return updated_trade
