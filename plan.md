# Implementation Plan

## Direction

Build the system in three coordinated layers:

1. VS Code + Copilot workflow for analysis and controlled code changes
2. Local Python bot/runtime for signals, broker execution, journaling, and safety controls
3. Guarded AI optimization loop for parameter proposals, validation, and approval

The current implementation starts from the data foundation because the trade journal and metrics layer is the shared base for runtime behavior, backtesting, and later AI analysis.

## MVP boundaries

Included in MVP:

- Practice-mode execution flow
- Signal generation boundary
- Broker adapter boundary
- Persistent trade journal
- Metrics and reporting base
- Proposal and approval schema
- Copilot repository instructions and prompts

Excluded from MVP:

- Unattended real-account trading
- Fully autonomous strategy rewrites
- Desktop GUI as a hard dependency
- Copilot embedded as runtime AI inside the app

## Immediate implementation sequence

1. Define SQLite schema and journal contracts
2. Define Python domain models aligned to the schema
3. Implement metrics derivation from trade journal records
4. Add broker adapter and safety controls behind explicit practice-mode gating
5. Add replay/backtest readers that reuse the same journal shape
6. Add proposal generation and approval workflow

## Current schema decisions

- Instrument scope: `binary` and `digital` options only for MVP
- Context depth: full context with indicator and market snapshots
- Metric basis: both absolute P/L and normalized performance
- Session labels: `asia`, `london`, `new_york`, `overlap`, `off_session`

## Files introduced now

- `docs/trade-journal-schema.md`
- `sql/001_initial_schema.sql`
- `src/bot/models.py`
- `src/bot/stats_service.py`
- `.github/copilot-instructions.md`

## Verification targets

1. The schema can represent a full trade lifecycle from signal to close.
2. Metrics can be computed from `trade_journal` without depending on live broker balances.
3. Copilot instructions keep code changes bounded to practice-mode-safe workflows.
