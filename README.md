# OptionAI

OptionAI is a practice-mode IQ Option research bot built for controlled strategy testing, deterministic trade journaling, and desktop monitoring.

It is structured so signal logic, broker execution, analytics, and session controls stay separate, testable, and auditable.

## Why This Project Is Strong

- Practice-first runtime with guarded broker integration
- Desktop dashboard for bounded sessions and pair selection
- SQLite trade journal as the source of truth for analytics
- Strategy catalog with momentum, trend-pullback, and mean-reversion engines
- Regression-tested codebase with focused dashboard and signal-engine coverage

## Current Feature Set

### Trading runtime

- One-shot and scheduled cycle execution
- Duplicate-signal protection, stale-data checks, reconnect backoff, and kill switch support
- IQ Option practice smoke-test and order-probe paths
- Binary result polling from multiple broker data paths, including async order state
- Detailed no-signal and session-error reasons written to the runtime event log

### Strategy layer

- Momentum-first `LOW`, `MEDIUM`, and `HIGH` defaults with explicit `momentum.*`, `trend-pullback.*`, and `mean-reversion.*` strategy IDs
- Composite multi-strategy selection with conflict handling and per-strategy tagging
- Momentum diagnostics that explain whether a setup failed at pattern, EMA alignment, ADX, ATR, support/resistance, or higher-timeframe alignment
- EMA trend, ADX, ATR, support/resistance distance, and multi-timeframe alignment filters across the supported strategy families
- Strategy-aware signal filtering before broker submission

### Dashboard and analytics

- Desktop dashboard for practice sessions
- Supported OTC pair selection and explicit strategy-family control from the UI
- Rotating asset batches per scan window to reduce mass entry-window skips on large selections
- Recent trade history, session logs, open positions, and grouped analytics with strategy-aware labels
- Binary history and runtime-event clearing tools

## Recent Runtime Updates

- Restored momentum as the default strategy family while preserving direct access to trend-pullback and mean-reversion engines
- Added richer session logging so dashboard errors surface as `ErrorType: message` instead of only the exception class
- Improved composite-strategy conflict handling to avoid runtime attribute errors during mixed-strategy sessions
- Reduced redundant dashboard trade scans and improved strategy display formatting in history and analytics views

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
