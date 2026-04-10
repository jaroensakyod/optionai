# OptionAI

OptionAI is a practice-mode IQ Option research bot built for controlled strategy testing, deterministic trade journaling, and desktop monitoring.

It is structured so signal logic, broker execution, analytics, and session controls stay separate, testable, and auditable.

## Why This Project Is Strong

- Practice-first runtime with guarded broker integration
- Desktop dashboard for bounded sessions and pair selection
- SQLite trade journal as the source of truth for analytics
- Profile-based signal engine with layered market filters
- Regression-tested codebase with `92 passed` locally

## Current Feature Set

### Trading runtime

- One-shot and scheduled cycle execution
- Duplicate-signal protection, stale-data checks, reconnect backoff, and kill switch support
- IQ Option practice smoke-test and order-probe paths

### Strategy layer

- `LOW`, `MEDIUM`, and `HIGH` strategy profiles
- EMA trend, ADX, ATR, support/resistance distance, and multi-timeframe alignment filters
- Strategy-aware signal filtering before broker submission

### Dashboard and analytics

- Desktop dashboard for practice sessions
- Supported OTC pair selection and strategy profile control
- Recent trade history, session logs, open positions, and grouped analytics
- Binary history and runtime-event clearing tools

## Tech Stack

- Python 3.11+
- SQLite
- Pytest
- Tkinter desktop UI
- Optional IQ Option `stable_api` compatible integration

## Quick Start

Install base dependencies:

```powershell
python -m pip install -e .[dev]
```

Start the desktop dashboard:

```powershell
python -m src.bot.desktop_dashboard
```

Run the full test suite:

```powershell
python -m pytest -q
```

## Scope

This repository is intentionally practice-only by default. It is designed for research, observability, and iterative strategy work, not unattended live trading.

## More Detail

- `docs/CHANGELOG.md`
- `docs/implementation-status.md`
- `docs/project-status-2026-04-09.md`
- `docs/runtime-update-2026-04-09.md`
- `docs/trade-journal-schema.md`
