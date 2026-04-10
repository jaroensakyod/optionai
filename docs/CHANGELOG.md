# Changelog

All notable project milestones are summarized here at a high level.

## 2026-04-10

### Strategy and execution

- Added profile-aware momentum filtering with `LOW`, `MEDIUM`, and `HIGH` strategy modes.
- Added five layered trade filters: EMA trend, ADX strength, ATR volatility, support/resistance distance, and multi-timeframe alignment.
- Unified CLI and runtime strategy construction through shared signal-engine builders.
- Improved filtered-signal handling so rejected setups are logged cleanly without entering the broker path.

### Dashboard and session flow

- Restored `poll_interval_sec=0` behavior so zero means zero offset again.
- Expanded desktop session control around strategy-profile selection and bounded runtime behavior.
- Improved binary pair handling, supported-pair visibility, and strategy-aware reporting in the dashboard path.
- Added clearing flows for binary history and related runtime event data.

### IQ Option practice integration

- Hardened unavailable-market handling with explicit `IQOptionOrderUnavailableError` flows.
- Improved binary close-result polling with socket, cache, and normalization fallbacks.
- Kept practice-mode execution isolated from signal generation and journal logic.

### Tests and validation

- Expanded signal-engine coverage for all newly added filters and profile behavior.
- Refreshed older fixtures to satisfy increased candle-history requirements introduced by the filter stack.
- Verified the full local suite at `92 passed`.

### Documentation

- Rewrote the top-level README to match the current repository state.
- Added this changelog to capture the latest milestone in one place.

## 2026-04-09

### Foundation milestone

- Established the practice-mode runtime foundation for the bot.
- Added SQLite journaling, metrics queries, structured runtime logging, and safety controls.
- Added IQ Option practice boundaries for market data, smoke tests, and order probes.
- Added desktop dashboard monitoring and bounded session control.
- Validated early local and broker-backed practice paths.

Reference documents:

- `docs/project-status-2026-04-09.md`
- `docs/runtime-update-2026-04-09.md`
- `docs/implementation-status.md`