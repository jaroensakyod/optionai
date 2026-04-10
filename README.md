# OptionAI

OptionAI is a practice-mode trading research bot for IQ Option focused on guarded experimentation, deterministic journaling, and desktop-based monitoring. The project is designed so signal logic, broker execution, analytics, and session control stay separated and auditable.

This repository is for research and practice workflows. It is not set up as a live automated trading system.

## Current Status

Current verified state in this workspace:

- Full local test suite: `92 passed`
- Practice-mode IQ Option integration is implemented
- Desktop dashboard is implemented for bounded monitoring and session control
- Binary OTC pair selection, analytics, history clearing, and strategy-aware reporting are implemented
- Strategy engine supports multiple profiles and layered filters
- Live broker orders are not enabled by default from the dashboard start flow

Core repository priorities:

1. Keep broker integration isolated from signal logic.
2. Keep journaling and metrics deterministic and testable.
3. Keep AI proposal generation outside the live execution path.
4. Favor small, auditable practice-mode changes over broad automation.

## What The Project Does

### Runtime and execution

- Runs one-off cycles through `BotRunner`
- Runs repeated cycles through `BotScheduler`
- Supports multi-asset workflows through the session controller and campaign runner
- Enforces stale-data checks, duplicate-signal prevention, reconnect handling, and kill-switch behavior

### Journaling and analytics

- Stores strategy versions, orders, trades, tags, and runtime events in SQLite
- Uses the trade journal as the source of truth for metrics and summaries
- Exposes deterministic metrics by asset, session, and strategy grouping
- Persists runtime events to both JSONL and the journal database

### IQ Option practice integration

- Supports IQ Option market data and practice submission via optional dependencies
- Includes smoke-test and order-probe paths for bounded connectivity checks
- Handles temporarily unavailable pairs without silently logging fake results
- Keeps broker result polling separate from signal generation

### Desktop dashboard

- Login/logout for `PRACTICE` and `REAL` viewing modes
- `Start` remains restricted to `PRACTICE`
- Pair selector for supported OTC binary pairs
- Strategy selector with `LOW`, `MEDIUM`, and `HIGH` profiles
- Session controls for stake, timeframe, expiry, poll interval, profit target, and loss limit
- Summary metrics, open positions, recent binary trades, and session log
- Strategy analytics grouped by pair and session
- Clear-data action for binary history and session events

## Strategy Profiles And Filters

The strategy engine currently supports three profiles:

- `LOW`
- `MEDIUM`
- `HIGH`

Signals are still momentum-based, but now include layered filters commonly used in short-term trading:

- `EMA trend filter`
- `ADX filter`
- `ATR volatility filter`
- `Support/resistance distance filter`
- `Multi-timeframe alignment`

Profile intent:

- `LOW` is the strictest profile and filters the most setups
- `MEDIUM` balances selectivity and signal frequency
- `HIGH` is the most permissive profile and accepts more setups

## Safety Model

Important constraints in this repo:

- Treat the system as practice-mode first
- Do not assume live execution support exists
- Dashboard session start is blocked when the login mode is `REAL`
- Metrics are derived from journaled trades, not transient UI state
- `REJECTED` and `ERROR` outcomes are not counted as wins or losses unless explicitly modeled otherwise
- Strategy logic does not call broker APIs directly

## Project Layout

| Path | Purpose |
| --- | --- |
| `src/bot/` | Runtime, adapters, dashboard, signal engine, safety controls, and services |
| `tests/` | Automated regression coverage across runtime, adapters, dashboard, and analytics |
| `sql/001_initial_schema.sql` | SQLite schema bootstrap |
| `docs/implementation-status.md` | Implementation tracking |
| `docs/project-status-2026-04-09.md` | Dated project snapshot |
| `docs/runtime-update-2026-04-09.md` | Runtime notes and runbook material |
| `docs/trade-journal-schema.md` | Journal and metrics design |
| `logs/` | Sample runtime and backtest artifacts |
| `data/` | Local application data and preferences |

## Setup

### Requirements

- Python `3.11+`
- Windows or another environment compatible with the project dependencies
- A virtual environment is recommended
- IQ Option credentials only if you want the broker-backed practice path

### Install

Base development and test setup:

```powershell
python -m pip install -e .[dev]
```

IQ Option practice path:

```powershell
python -m pip install -e .[dev,iqoption]
```

Notes:

- The IQ Option dependency path uses the compatible GitHub fork of `iqoptionapi`
- `websocket-client==0.56.0` is pinned for compatibility with that fork

### Environment

1. Copy `.env.example` to `.env`
2. Keep `BOT_ACCOUNT_MODE=PRACTICE`
3. Add IQ Option credentials if you plan to use broker-backed practice mode

## Common Commands

### Run the full test suite

```powershell
python -m pytest -q
```

Latest verified result in this workspace:

```text
92 passed
```

### Start the desktop dashboard

```powershell
python -m src.bot.desktop_dashboard
```

### Run the IQ Option sanity check

```powershell
python -m src.bot.iqoption_sanity --env-file .env --asset EURUSD --instrument-type digital --timeframe-sec 60 --candle-limit 3
```

This verifies:

- optional dependency import
- credential presence
- bounded practice connectivity
- balance read
- candle fetch

### Run a local CSV-backed practice cycle

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

### Run an IQ Option practice smoke test through CLI

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

## Current Scope

Included now:

- Practice-mode runtime
- IQ Option-backed practice research flow
- CSV-backed local testing flow
- Desktop monitoring and bounded session control
- Deterministic journaling and metrics
- Strategy-aware analytics from the trade journal

Not included yet:

- Backtest ingestion into the same journal model
- AI proposal generation and approval workflow
- Production deployment workflow
- Live automated trading support

## Notes On Analytics And Reporting

Recent dashboard work added:

- strategy-aware trade tags
- pair support detection based on available actives
- analytics grouped by strategy and asset
- analytics grouped by strategy and session
- binary-history clearing from the desktop path
- safer handling of unavailable broker pairs and delayed close results

## Reference Documents

- `docs/implementation-status.md`
- `docs/project-status-2026-04-09.md`
- `docs/runtime-update-2026-04-09.md`
- `docs/trade-journal-schema.md`
- `docs/eurusd-otc-binary-run-2026-04-09.md`
