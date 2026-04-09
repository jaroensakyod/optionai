# OptionAI

Practice-mode trading research bot for IQ Option with a local SQLite journal, deterministic metrics, bounded desktop monitoring, and explicit separation between signal logic and broker execution.

## Summary

This repository is a research workspace, not a production live-trading system.

Current validated state:

- Full local test suite: `44 passed`
- IQ Option dependency path is packaged in `.[iqoption]`
- IQ Option practice connectivity and smoke-test path are implemented
- Desktop dashboard is implemented for monitoring and bounded session control
- Live execution is intentionally blocked by default from the dashboard start path

Core design priorities:

1. Keep broker integration isolated from signal logic.
2. Keep journaling and metrics deterministic and testable.
3. Keep AI proposal generation outside the live execution path.
4. Favor auditable practice-mode workflows over automation depth.

## What Was Built

### Runtime foundation

- Single-cycle runtime via `BotRunner`
- Repeated-cycle scheduling via `BotScheduler`
- Multi-asset campaign execution via `campaign_runner.py`
- Duplicate-signal prevention, stale-data guard, reconnect handling, and kill-switch support

### Data and analytics

- SQLite-backed trade journal in `data/trades.db`
- Structured persistence for strategy versions, signals, broker attempts, trades, tags, and runtime events
- Deterministic summary metrics and grouped metrics from the journal
- Runtime JSONL plus database-backed event logging

### IQ Option support

- Optional packaged install path: `python -m pip install -e .[iqoption]`
- Broker adapter for practice-mode submission and trade-result polling
- Market-data provider for IQ Option candles and payout access
- Sanity preflight command to validate dependency import, credentials, and bounded connectivity

### Desktop dashboard

- Tkinter desktop window for binary OTC monitoring
- Login/logout with account-mode selector for viewing `PRACTICE` or `REAL` balances
- `Start` remains restricted to `PRACTICE`
- Multi-select OTC pair checklist with `All` and `Clear`
- Opportunity score per pair with `HIGH` / `MEDIUM` / `LOW` color zones
- Per-pair `updated at` refresh time
- Current active pair highlight while the session is checking conditions
- Configurable batch size from the UI: check `1` or `2` pairs per round
- Session controls for stake, timeframe, expiry, poll interval, profit target, and loss limit
- Recent trade history, summary metrics, and selected-pair metrics

## Current Scope

Included now:

- Practice-mode runtime
- IQ Option-backed practice research flow
- CSV-backed local testing flow
- Desktop monitoring and bounded session control
- Deterministic journaling and reporting

Not included yet:

- Backtest ingestion/replay pipeline
- AI proposal generation and approval workflow
- Production deployment workflow
- Live automated trading support

## Project Layout

| Path | Purpose |
| --- | --- |
| `src/bot/` | Runtime, adapters, safety controls, dashboard, and services |
| `tests/` | Regression coverage across runtime, adapters, metrics, and dashboard logic |
| `sql/001_initial_schema.sql` | SQLite schema bootstrap |
| `docs/implementation-status.md` | Ongoing done vs pending tracking |
| `docs/runtime-update-2026-04-09.md` | Detailed runbook and runtime notes |
| `docs/project-status-2026-04-09.md` | Dated project snapshot |
| `docs/trade-journal-schema.md` | Journal and metrics model |
| `docs/eurusd-otc-binary-run-2026-04-09.md` | Dated practice-run notes |

## Setup

### Requirements

- Python `3.11+`
- Windows or another environment that supports the project dependencies
- A virtual environment is recommended
- IQ Option credentials only if you want the broker-backed practice path

### Install

Base dev and test setup:

```powershell
python -m pip install -e .[dev]
```

IQ Option practice path:

```powershell
python -m pip install -e .[dev,iqoption]
```

Notes:

- The supported IQ Option dependency is the GitHub `stable_api` fork, not the stale PyPI release.
- `websocket-client==0.56.0` is pinned for compatibility with that fork.

### Configure environment

1. Copy `.env.example` to `.env`.
2. Keep `BOT_ACCOUNT_MODE=PRACTICE` for runtime safety.
3. Add IQ Option credentials if using the broker-backed path.

## Commands

### Run tests

```powershell
python -m pytest
```

Latest validated result in this workspace:

```text
44 passed
```

### IQ Option sanity check

```powershell
python -m src.bot.iqoption_sanity --env-file .env --asset EURUSD --instrument-type digital --timeframe-sec 60 --candle-limit 3
```

This verifies:

- optional dependency import
- credential presence
- bounded practice connectivity
- balance read
- candle fetch

### Desktop dashboard

```powershell
python -m src.bot.desktop_dashboard
```

Current dashboard behavior:

- shows OTC binary forex pairs derived from payout availability
- avoids the unstable IQ Option open-time thread path
- refreshes opportunity scores every 60 seconds
- highlights the pair or pair-batch currently being checked
- can check `1` or `2` pairs per round
- can display `REAL` or `PRACTICE` balance mode after login
- only allows session start in `PRACTICE`

### Local CSV-backed cycle

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
  --max-data-age-sec 315360000 \
  --cycles 1
```

### IQ Option practice smoke test through CLI

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

## Important Safety Notes

- This repo should be treated as practice-mode first.
- Dashboard `Start` is blocked when login mode is `REAL`.
- Journal data is the source of truth for metrics and session summaries.
- `REJECTED` and `ERROR` broker outcomes are not counted as wins or losses unless explicitly modeled otherwise.
- Strategy logic stays separate from broker APIs.

## Summary Of Work Completed In This Session

- Grounded and validated the repository state
- Added optional packaging for IQ Option dependencies in `pyproject.toml`
- Added bounded IQ Option sanity command
- Improved adapter import guidance and DB path creation
- Fixed rejected order-probe reporting
- Built OTC-focused Tkinter dashboard
- Added login/logout, mode viewing, pair selection, start/stop, and target controls
- Added current pair-checking state, active-row highlighting, and configurable `1` or `2` pair checking batches
- Added deterministic opportunity scoring with color-banded display and per-pair refresh timestamps
- Added preference persistence for dashboard settings
- Expanded test coverage for sanity checks, dashboard service, dashboard session control, and dashboard preferences

## Reference Documents

- `docs/implementation-status.md`
- `docs/runtime-update-2026-04-09.md`
- `docs/project-status-2026-04-09.md`
- `docs/trade-journal-schema.md`
- `docs/eurusd-otc-binary-run-2026-04-09.md`
