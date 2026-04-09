# Trade Journal And Metrics Schema

## Goals

The schema is designed to support four concerns with one source of truth:

1. Runtime execution observability
2. Strategy performance analytics
3. Backtest and replay comparability
4. AI proposal, validation, and approval history

## Storage model

SQLite is the primary store for MVP. Event-heavy logs and normalized trade rows are separated so operational debugging does not pollute analytics queries.

## Core entities

### `strategy_versions`

Immutable record of strategy code reference and parameter payload active at signal time.

### `signal_events`

Captures every signal candidate before broker execution. This is where indicator and market snapshots belong.

### `broker_orders`

Captures every execution attempt, retry, broker identifier, and raw request/response payload summary.

### `trade_journal`

One row per completed trade lifecycle. This is the primary analytics table.

### `trade_context_tags`

Flexible tag table for regime labels, experiments, or later AI annotations.

### `equity_snapshots`

Used to reconcile journal-derived equity with broker-reported state and to support drawdown reconstruction.

### `optimization_proposals`, `proposal_validations`, `approval_audit`

These tables store AI or human parameter proposals, validation evidence, and approval or rollback actions.

### `system_events`

Operational events such as reconnects, stale data detection, duplicate prevention, and kill-switch triggers.

## `trade_journal` minimum contract

Each trade must have:

- Stable internal `trade_id`
- Associated `signal_id` and `strategy_version_id`
- Open and close timestamps in UTC
- Asset, instrument, timeframe, direction, amount, and expiry
- Entry and exit prices when available
- Payout snapshot
- Final result enum
- Absolute P/L and normalized P/L per unit of risk
- Error summary for failures or uncertain closures

## Result semantics

Recommended enum values:

- `WIN`
- `LOSS`
- `BREAKEVEN`
- `CANCELLED`
- `REJECTED`
- `ERROR`
- `EXPIRED_UNKNOWN`

`REJECTED` and `ERROR` are operational outcomes by default and should not be counted as trading wins or losses unless explicitly requested.

## Metrics contract

Metrics should be derived from `trade_journal`, grouped at minimum by:

- `strategy_version_id`
- `account_mode`
- `asset`
- `timeframe_sec`
- `session_label`

### Core metrics

- `total_trades`
- `wins`
- `losses`
- `breakevens`
- `gross_profit`
- `gross_loss`
- `net_pnl`
- `avg_win`
- `avg_loss`
- `payoff_ratio`
- `expectancy_per_trade`
- `profit_factor`
- `max_drawdown_abs`
- `max_drawdown_pct`
- `longest_win_streak`
- `longest_loss_streak`

### Operational metrics

- `submit_success_rate`
- `execution_error_rate`
- `avg_order_latency_ms`
- `avg_resolution_latency_ms`
- `reconnect_count`
- `stale_data_event_count`
- `duplicate_order_prevented_count`

## Design rules

1. Store timestamps in UTC only.
2. Prefer explicit numeric columns for metrics-critical fields.
3. Keep large broker payloads out of `trade_journal` and inside `broker_orders`.
4. Keep practice, replay, and future real-money records separable with flags and account mode fields.
5. Partition every aggregate by strategy version to avoid cross-version contamination.
