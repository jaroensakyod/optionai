from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from .db import connect_sqlite, initialize_schema
from .models import (
    BrokerOrderAttempt,
    InstrumentType,
    SignalEvent,
    StrategyVersion,
    SessionLabel,
    SystemEventRecord,
    TradeContextRecord,
    TradeDirection,
    TradeJournalRecord,
    TradeResult,
)


def _to_iso8601(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _from_iso8601(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class TradeJournalRepository:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    @classmethod
    def from_paths(cls, database_path: Path, schema_path: Path) -> TradeJournalRepository:
        connection = connect_sqlite(database_path)
        initialize_schema(connection, schema_path)
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def save_strategy_version(self, strategy_version: StrategyVersion) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO strategy_versions (
                strategy_version_id,
                created_at_utc,
                strategy_name,
                code_ref,
                parameter_hash,
                parameters_json,
                created_by,
                change_reason,
                approved_by,
                approval_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_version.strategy_version_id,
                _to_iso8601(strategy_version.created_at_utc),
                strategy_version.strategy_name,
                strategy_version.code_ref,
                strategy_version.parameter_hash,
                json.dumps(strategy_version.parameters, sort_keys=True),
                strategy_version.created_by,
                strategy_version.change_reason,
                strategy_version.approved_by,
                strategy_version.approval_status,
            ),
        )
        self._connection.commit()

    def save_signal_event(self, signal_event: SignalEvent) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO signal_events (
                signal_id,
                created_at_utc,
                strategy_version_id,
                asset,
                instrument_type,
                timeframe_sec,
                direction,
                signal_strength,
                entry_reason,
                indicator_snapshot_json,
                market_snapshot_json,
                session_label,
                is_filtered_out,
                filter_reason,
                intended_amount,
                intended_expiry_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_event.signal_id,
                _to_iso8601(signal_event.created_at_utc),
                signal_event.strategy_version_id,
                signal_event.asset,
                signal_event.instrument_type.value,
                signal_event.timeframe_sec,
                signal_event.direction.value,
                signal_event.signal_strength,
                signal_event.entry_reason,
                json.dumps(signal_event.indicator_snapshot, sort_keys=True),
                json.dumps(signal_event.market_snapshot, sort_keys=True),
                signal_event.session_label.value,
                int(signal_event.is_filtered_out),
                signal_event.filter_reason,
                signal_event.intended_amount,
                signal_event.intended_expiry_sec,
            ),
        )
        self._connection.commit()

    def upsert_trade(self, trade: TradeJournalRecord) -> None:
        now = datetime.now(UTC)
        created_at = trade.created_at_utc or now
        updated_at = trade.updated_at_utc or now
        self._connection.execute(
            """
            INSERT INTO trade_journal (
                trade_id,
                signal_id,
                strategy_version_id,
                opened_at_utc,
                closed_at_utc,
                asset,
                instrument_type,
                timeframe_sec,
                direction,
                amount,
                expiry_sec,
                entry_price,
                exit_price,
                payout_snapshot,
                result,
                profit_loss_abs,
                profit_loss_pct_risk,
                fees_abs,
                duration_ms,
                account_mode,
                broker_order_id,
                broker_position_id,
                close_reason,
                error_code,
                error_message,
                is_replay,
                journal_version,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                signal_id = excluded.signal_id,
                strategy_version_id = excluded.strategy_version_id,
                opened_at_utc = excluded.opened_at_utc,
                closed_at_utc = excluded.closed_at_utc,
                asset = excluded.asset,
                instrument_type = excluded.instrument_type,
                timeframe_sec = excluded.timeframe_sec,
                direction = excluded.direction,
                amount = excluded.amount,
                expiry_sec = excluded.expiry_sec,
                entry_price = excluded.entry_price,
                exit_price = excluded.exit_price,
                payout_snapshot = excluded.payout_snapshot,
                result = excluded.result,
                profit_loss_abs = excluded.profit_loss_abs,
                profit_loss_pct_risk = excluded.profit_loss_pct_risk,
                fees_abs = excluded.fees_abs,
                duration_ms = excluded.duration_ms,
                account_mode = excluded.account_mode,
                broker_order_id = excluded.broker_order_id,
                broker_position_id = excluded.broker_position_id,
                close_reason = excluded.close_reason,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                is_replay = excluded.is_replay,
                journal_version = excluded.journal_version,
                updated_at_utc = excluded.updated_at_utc
            """,
            (
                trade.trade_id,
                trade.signal_id,
                trade.strategy_version_id,
                _to_iso8601(trade.opened_at_utc),
                _to_iso8601(trade.closed_at_utc),
                trade.asset,
                trade.instrument_type.value,
                trade.timeframe_sec,
                trade.direction.value,
                trade.amount,
                trade.expiry_sec,
                trade.entry_price,
                trade.exit_price,
                trade.payout_snapshot,
                trade.result.value if trade.result else None,
                trade.profit_loss_abs,
                trade.profit_loss_pct_risk,
                trade.fees_abs,
                trade.duration_ms,
                trade.account_mode,
                trade.broker_order_id,
                trade.broker_position_id,
                trade.close_reason,
                trade.error_code,
                trade.error_message,
                int(trade.is_replay),
                trade.journal_version,
                _to_iso8601(created_at),
                _to_iso8601(updated_at),
            ),
        )
        self._connection.commit()

    def replace_trade_tags(self, trade_id: str, tags: dict[str, str]) -> None:
        self._connection.execute("DELETE FROM trade_context_tags WHERE trade_id = ?", (trade_id,))
        self._connection.executemany(
            "INSERT INTO trade_context_tags (trade_id, tag_key, tag_value) VALUES (?, ?, ?)",
            [(trade_id, key, value) for key, value in tags.items()],
        )
        self._connection.commit()

    def save_broker_order(self, order_attempt: BrokerOrderAttempt) -> None:
        self._connection.execute(
            """
            INSERT INTO broker_orders (
                trade_id,
                signal_id,
                submitted_at_utc,
                broker_name,
                account_mode,
                broker_order_id,
                broker_position_id,
                asset,
                direction,
                amount,
                expiry_sec,
                payout_snapshot,
                submission_status,
                submission_error_code,
                submission_error_message,
                raw_request_json,
                raw_response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_attempt.trade_id,
                order_attempt.signal_id,
                _to_iso8601(order_attempt.submitted_at_utc),
                order_attempt.broker_name,
                order_attempt.account_mode,
                order_attempt.broker_order_id,
                order_attempt.broker_position_id,
                order_attempt.asset,
                order_attempt.direction.value,
                order_attempt.amount,
                order_attempt.expiry_sec,
                order_attempt.payout_snapshot,
                order_attempt.submission_status,
                order_attempt.submission_error_code,
                order_attempt.submission_error_message,
                json.dumps(order_attempt.raw_request_json, sort_keys=True),
                json.dumps(order_attempt.raw_response_json, sort_keys=True),
            ),
        )
        self._connection.commit()

    def get_trade(self, trade_id: str) -> TradeJournalRecord | None:
        row = self._connection.execute(
            "SELECT * FROM trade_journal WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_trade(row)

    def list_trades(self, *, account_mode: str | None = None) -> list[TradeJournalRecord]:
        query = "SELECT * FROM trade_journal"
        params: tuple[str, ...] = ()
        if account_mode is not None:
            query += " WHERE account_mode = ?"
            params = (account_mode,)
        query += " ORDER BY COALESCE(closed_at_utc, opened_at_utc) ASC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def list_trade_contexts(self, *, account_mode: str | None = None) -> list[TradeContextRecord]:
        query = """
            SELECT tj.*, se.session_label
            FROM trade_journal tj
            LEFT JOIN signal_events se ON se.signal_id = tj.signal_id
        """
        params: tuple[str, ...] = ()
        if account_mode is not None:
            query += " WHERE tj.account_mode = ?"
            params = (account_mode,)
        query += " ORDER BY COALESCE(tj.closed_at_utc, tj.opened_at_utc) ASC"
        rows = self._connection.execute(query, params).fetchall()
        return [
            TradeContextRecord(
                trade=self._row_to_trade(row),
                session_label=SessionLabel(row["session_label"]) if row["session_label"] else None,
            )
            for row in rows
        ]

    def list_broker_orders(self, trade_id: str) -> list[BrokerOrderAttempt]:
        rows = self._connection.execute(
            "SELECT * FROM broker_orders WHERE trade_id = ? ORDER BY broker_order_pk ASC",
            (trade_id,),
        ).fetchall()
        return [self._row_to_broker_order(row) for row in rows]

    def clear_binary_history(self, *, account_mode: str) -> int:
        deleted_trade_ids = [
            row["trade_id"]
            for row in self._connection.execute(
                "SELECT trade_id FROM trade_journal WHERE account_mode = ? AND instrument_type = ?",
                (account_mode, InstrumentType.BINARY.value),
            ).fetchall()
        ]
        if deleted_trade_ids:
            placeholders = ",".join("?" for _ in deleted_trade_ids)
            self._connection.execute(
                f"DELETE FROM broker_orders WHERE trade_id IN ({placeholders})",
                tuple(deleted_trade_ids),
            )
            self._connection.execute(
                f"DELETE FROM trade_context_tags WHERE trade_id IN ({placeholders})",
                tuple(deleted_trade_ids),
            )
            self._connection.execute(
                f"DELETE FROM trade_journal WHERE trade_id IN ({placeholders})",
                tuple(deleted_trade_ids),
            )
        self._connection.commit()
        return len(deleted_trade_ids)

    def clear_system_events(self, *, component: str | None = None) -> int:
        if component is None:
            cursor = self._connection.execute("DELETE FROM system_events")
        else:
            cursor = self._connection.execute("DELETE FROM system_events WHERE component = ?", (component,))
        self._connection.commit()
        return int(cursor.rowcount)

    def get_trade_tags(self, trade_id: str) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT tag_key, tag_value FROM trade_context_tags WHERE trade_id = ? ORDER BY tag_key",
            (trade_id,),
        ).fetchall()
        return {row["tag_key"]: row["tag_value"] for row in rows}

    def find_recent_trade_by_fingerprint(
        self,
        *,
        account_mode: str,
        asset: str,
        timeframe_sec: int,
        expiry_sec: int,
        fingerprint: str,
        opened_after_utc: datetime,
    ) -> TradeJournalRecord | None:
        row = self._connection.execute(
            """
            SELECT tj.*
            FROM trade_journal tj
            JOIN trade_context_tags tct ON tct.trade_id = tj.trade_id
            WHERE tj.account_mode = ?
              AND tj.asset = ?
              AND tj.timeframe_sec = ?
              AND tj.expiry_sec = ?
              AND tj.opened_at_utc >= ?
              AND tct.tag_key = 'signal_fingerprint'
              AND tct.tag_value = ?
            ORDER BY tj.opened_at_utc DESC
            LIMIT 1
            """,
            (
                account_mode,
                asset,
                timeframe_sec,
                expiry_sec,
                _to_iso8601(opened_after_utc),
                fingerprint,
            ),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_trade(row)

    def save_system_event(self, event: SystemEventRecord) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO system_events (
                event_id,
                occurred_at_utc,
                severity,
                component,
                event_type,
                message,
                details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                _to_iso8601(event.occurred_at_utc),
                event.severity,
                event.component,
                event.event_type,
                event.message,
                json.dumps(event.details, sort_keys=True),
            ),
        )
        self._connection.commit()

    def list_system_events(self, *, component: str | None = None) -> list[SystemEventRecord]:
        query = "SELECT * FROM system_events"
        params: tuple[str, ...] = ()
        if component is not None:
            query += " WHERE component = ?"
            params = (component,)
        query += " ORDER BY occurred_at_utc ASC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._row_to_system_event(row) for row in rows]

    @staticmethod
    def _row_to_broker_order(row: sqlite3.Row) -> BrokerOrderAttempt:
        return BrokerOrderAttempt(
            trade_id=row["trade_id"],
            signal_id=row["signal_id"],
            submitted_at_utc=_from_iso8601(row["submitted_at_utc"]),
            broker_name=row["broker_name"],
            account_mode=row["account_mode"],
            broker_order_id=row["broker_order_id"],
            broker_position_id=row["broker_position_id"],
            asset=row["asset"],
            direction=TradeDirection(row["direction"]),
            amount=row["amount"],
            expiry_sec=row["expiry_sec"],
            payout_snapshot=row["payout_snapshot"],
            submission_status=row["submission_status"],
            submission_error_code=row["submission_error_code"],
            submission_error_message=row["submission_error_message"],
            raw_request_json=json.loads(row["raw_request_json"] or "{}"),
            raw_response_json=json.loads(row["raw_response_json"] or "{}"),
        )

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> TradeJournalRecord:
        result_value = row["result"]
        return TradeJournalRecord(
            trade_id=row["trade_id"],
            signal_id=row["signal_id"],
            strategy_version_id=row["strategy_version_id"],
            opened_at_utc=_from_iso8601(row["opened_at_utc"]),
            closed_at_utc=_from_iso8601(row["closed_at_utc"]),
            asset=row["asset"],
            instrument_type=InstrumentType(row["instrument_type"]),
            timeframe_sec=row["timeframe_sec"],
            direction=TradeDirection(row["direction"]),
            amount=row["amount"],
            expiry_sec=row["expiry_sec"],
            account_mode=row["account_mode"],
            result=TradeResult(result_value) if result_value else None,
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            payout_snapshot=row["payout_snapshot"],
            profit_loss_abs=row["profit_loss_abs"],
            profit_loss_pct_risk=row["profit_loss_pct_risk"],
            fees_abs=row["fees_abs"],
            duration_ms=row["duration_ms"],
            broker_order_id=row["broker_order_id"],
            broker_position_id=row["broker_position_id"],
            close_reason=row["close_reason"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            is_replay=bool(row["is_replay"]),
            journal_version=row["journal_version"],
            created_at_utc=_from_iso8601(row["created_at_utc"]),
            updated_at_utc=_from_iso8601(row["updated_at_utc"]),
        )

    @staticmethod
    def _row_to_system_event(row: sqlite3.Row) -> SystemEventRecord:
        return SystemEventRecord(
            event_id=row["event_id"],
            occurred_at_utc=_from_iso8601(row["occurred_at_utc"]),
            severity=row["severity"],
            component=row["component"],
            event_type=row["event_type"],
            message=row["message"],
            details=json.loads(row["details_json"] or "{}"),
        )
