# Copilot-Assisted IQ Option Research Bot

A guarded Python research bot for IQ Option practice-mode experimentation.

This repository is built around three priorities:

1. Keep live broker behavior isolated from signal logic.
2. Keep journaling and metrics deterministic.
3. Keep AI-assisted tuning outside the execution path.

## Status

| Area | Current state |
| --- | --- |
| Runtime foundation | Ready for local `PRACTICE` mode runs |
| Trade journal | SQLite-backed and wired into the runtime |
| Metrics | Queryable from journal data |
| IQ Option boundary | Connected and validated in practice mode |
| Tests | `27 passed` |
| AI proposal workflow | Not implemented yet |
| Live trading | Intentionally out of scope by default |

## What This Project Does

- Runs a guarded trading research loop in `PRACTICE` mode.
- Separates market data, signal generation, broker execution, journaling, and metrics.
- Records trade lifecycle data into SQLite so performance analysis does not depend on broker UI state.
- Supports CSV-based local runs and IQ Option-backed practice runs.
- Preserves an audit trail through journal rows, grouped metrics, and runtime events.

## What Has Already Been Built

### Runtime and execution

- Practice broker adapter and IQ Option adapter boundaries.
- One-cycle runner and repeated scheduler loop.
- Multi-asset campaign runner for checkpointed practice batches.
- Duplicate-signal protection, stale-data guard, reconnect backoff, and file kill switch.

### Data and analytics

- SQLite schema for trade journaling and reporting.
- Journal repository and lifecycle service for signal, open, reject, and close events.
- Metrics query service and metric snapshot utilities.
- Structured runtime event logging to SQLite and local JSONL.

### Validation and documentation

- Automated tests across runtime, adapters, journaling, metrics, and safety controls.
- Practice smoke test and direct order probe paths.
- Implementation notes, runtime update logs, and a dated project status snapshot.

## Current Results

- Local pytest status: `27 passed`
- IQ Option practice smoke test: passed
- Real `EURUSD-OTC` practice order probe: completed end-to-end
- Strategy-path scheduler and batch runs: exercised successfully in practice mode

Important constraint:

This repository should still be treated as a research workspace, not a production live-trading system.

## Project Layout

| Path | Purpose |
| --- | --- |
| `plan.md` | High-level implementation sequence |
| `docs/implementation-status.md` | Detailed done vs pending tracking |
| `docs/project-status-2026-04-09.md` | Short project snapshot: what was done, what remains, and current results |
| `docs/runtime-update-2026-04-09.md` | Practical runbook and runtime readiness notes |
| `docs/trade-journal-schema.md` | Journal and metrics model |
| `docs/eurusd-otc-binary-run-2026-04-09.md` | Dated live practice run notes |
| `sql/001_initial_schema.sql` | Initial SQLite schema |
| `src/bot/` | Bot runtime, adapters, safety controls, and services |
| `tests/` | Automated regression coverage |

## Quick Start

### Requirements

- Python `3.11+`
- A local virtual environment
- IQ Option credentials only if you want to use the practice broker path

### Configure the environment

1. Copy `.env.example` to `.env`.
2. Keep `BOT_ACCOUNT_MODE=PRACTICE`.
3. Fill in IQ Option credentials only for practice-mode testing.

### Run the tests

```powershell
python -m pytest
```

### Run one local CSV-backed cycle

```powershell
python -m src.bot.cli \
	--broker practice \
	--market-data-source csv \
	--market-data-csv logs/backtests/sample-candles.csv \
	--strategy-version-id demo-v1 \
	--asset EURUSD \
	--instrument-type digital \
	--timeframe-sec 60 \
	--stake 1.0 \
	--expiry-sec 60 \
	--cycles 1
```

### Run an IQ Option practice smoke test

```powershell
python -m src.bot.cli \
	--broker iqoption \
	--market-data-source iqoption \
	--strategy-version-id smoke-v1 \
	--asset EURUSD \
	--instrument-type digital \
	--timeframe-sec 60 \
	--practice-smoke-test \
	--smoke-test-candle-limit 3
```

For more command variants, see `docs/runtime-update-2026-04-09.md`.

## Safety Model

- Practice mode is the default operating assumption.
- Signal generation remains separate from broker execution.
- Runtime safety checks can stop or skip work before submission.
- Journal and metrics data are treated as the source of truth for analysis.
- AI-generated tuning is intended to stay outside the direct live execution path.

## What Is Still Missing

- Replay and backtest ingestion pipeline.
- AI proposal generation and approval workflow.
- Deployment and packaging workflow.
- Larger live practice sample for strategy confidence.

## Reference Documents

- `docs/implementation-status.md`
- `docs/project-status-2026-04-09.md`
- `docs/runtime-update-2026-04-09.md`
- `docs/trade-journal-schema.md`
- `docs/eurusd-otc-binary-run-2026-04-09.md`

## Operating Note

The IQ Option integration in this repository is for bounded local research and practice-mode validation. Any move beyond that should be treated as a separate scope with stricter operational controls.
