# Runtime Update 2026-04-09

## Current readiness

The project is usable now in `PRACTICE` mode for local runs with CSV candle input.

It has also now passed a real IQ Option practice-account smoke test in this workspace.

What is working now:

- SQLite trade journal and metrics foundation
- Practice broker simulation flow
- IQ Option adapter boundary and IQ Option market-data boundary behind injectable clients
- One-cycle or multi-cycle CLI runner
- Duplicate signal prevention within a configurable time window
- Stale-data guard, reconnect backoff, and file kill switch
- Structured runtime event logging into `system_events` and JSONL files
- Practice smoke-test harness for IQ Option connectivity checks
- Practice order probe for direct broker execution validation

What has been validated locally:

- Full pytest suite passes
- Latest result: `44 passed`

## What you can use right now

### Dependency install for this repo

Install the base test and local-run dependencies with:

```powershell
python -m pip install -e .[dev]
```

Install the optional IQ Option path with:

```powershell
python -m pip install -e .[dev,iqoption]
```

Notes:

- the supported IQ Option dependency is the community `stable_api` fork from GitHub, not the outdated PyPI `iqoptionapi` release
- the extra pins `websocket-client==0.56.0` to match the upstream fork guidance

### Option 1: Run locally with CSV candles

This is the safest path because it does not require external broker connectivity.

1. Copy `.env.example` to `.env` and keep `BOT_ACCOUNT_MODE=PRACTICE`
2. Prepare a CSV file with columns:
   - `opened_at_utc`
   - `asset`
   - `instrument_type`
   - `timeframe_sec`
   - `open_price`
   - `high_price`
   - `low_price`
   - `close_price`
   - optional `volume`
3. Run the CLI:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
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

Expected output shape:

```text
status=submitted reason=None signal_id=... trade_id=...
```

Possible statuses:

- `submitted`
- `skipped`
- `stopped`
- `recovered`
- `error`

### Option 2: Run scheduler mode for repeated cycles

Use the same command but increase `--cycles` and optionally adjust:

- `--poll-interval-sec`
- `--duplicate-window-sec`
- `--max-data-age-sec`
- `--kill-switch-file`

Example:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --broker practice \
  --market-data-source csv \
  --market-data-csv logs/backtests/sample-candles.csv \
  --strategy-version-id demo-v1 \
  --asset EURUSD \
  --instrument-type digital \
  --timeframe-sec 60 \
  --stake 1.0 \
  --expiry-sec 60 \
  --cycles 10 \
  --poll-interval-sec 5 \
  --duplicate-window-sec 120 \
  --max-data-age-sec 120 \
  --kill-switch-file logs/runtime/STOP
```

If the kill-switch file exists, the scheduler stops on the next refresh.

### Option 3: Practice smoke test for IQ Option

This path is implemented and has now succeeded once in this workspace with a real practice account.

Current state:

- `stable_api` compatible `iqoptionapi` fork is declared as an optional repo dependency via `.[iqoption]`
- `.env` has been configured locally for this machine
- broker connectivity, balance read, and candle fetch succeeded in practice mode

Recommended preflight command:

```powershell
python -m src.bot.iqoption_sanity --env-file .env --asset EURUSD --instrument-type digital --timeframe-sec 60 --candle-limit 3
```

This returns a compact status line and exits non-zero if the dependency import is missing, credentials are still placeholders, or the bounded PRACTICE smoke check fails.

### Desktop monitoring window

There is now a local desktop dashboard for the bounded IQ Option practice path:

```powershell
python -m src.bot.desktop_dashboard
```

The window shows:

- current PRACTICE balance
- current account mode
- checklist selection across open binary forex pairs with payout snapshots
- recommended pairs based on payout and local binary win rate
- selected-pair-group and overall binary win rate
- login/logout controls for the PRACTICE session
- start/stop controls for a bounded desktop runner session
- stake, timeframe, expiry, poll interval, and `$`/`%` profit-loss targets
- recent binary trade history from `data/trades.db`

The pair list now comes from `get_all_profit()` instead of `get_all_open_time()`, which avoids the upstream `iqoptionapi` thread failure path that was throwing `KeyError: 'underlying'` during dashboard refresh.

Command shape:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --broker iqoption \
  --market-data-source iqoption \
  --strategy-version-id smoke-v1 \
  --asset EURUSD \
  --instrument-type digital \
  --timeframe-sec 60 \
  --practice-smoke-test \
  --smoke-test-candle-limit 3
```

Expected output shape:

```text
status=passed balance=... candle_count=3 reason=None
```

Latest observed result in this workspace:

```text
status=passed balance=... candle_count=3 reason=None
```

### Option 4: Scheduler mode with real IQ Option practice connectivity

This path is now runnable. A one-cycle test was executed in this workspace.

Command shape:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --env-file .env \
  --broker iqoption \
  --market-data-source iqoption \
  --strategy-version-id live-practice-v1 \
  --asset EURUSD \
  --instrument-type digital \
  --timeframe-sec 60 \
  --stake 1.0 \
  --expiry-sec 60 \
  --cycles 1 \
  --poll-interval-sec 1 \
  --duplicate-window-sec 120 \
  --max-data-age-sec 180
```

Latest observed result in this workspace:

```text
status=skipped reason=no_signal signal_id=None trade_id=None
```

This means the full runtime path started successfully, but the current momentum engine did not find an entry on that cycle, so no order was placed.

### Option 5: Real binary OTC practice order probe

This path now confirms direct broker execution without waiting for the strategy to emit a signal.

Command shape:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --env-file .env \
  --broker iqoption \
  --market-data-source iqoption \
  --strategy-version-id otc-binary-probe-v1 \
  --asset EURUSD-OTC \
  --instrument-type binary \
  --timeframe-sec 60 \
  --stake 1.0 \
  --expiry-sec 60 \
  --direction call \
  --practice-order-probe \
  --probe-wait-for-close \
  --probe-poll-interval-sec 2 \
  --probe-timeout-sec 180
```

Latest observed result in this workspace:

```text
status=closed trade_id=... result=LOSS profit_loss_abs=-1.0 reason=None
```

This is the first confirmed end-to-end real practice trade path in this workspace for `EURUSD-OTC` binary.

### Strategy-path EURUSD-OTC binary run

The strategy path has now also submitted real `EURUSD-OTC` binary practice trades from the scheduler, with mixed outcomes so far.

Detailed run log:

- see `docs/eurusd-otc-binary-run-2026-04-09.md`

### Option 6: Blitz mode for 30-second candles

There is now a faster strategy preset for `EURUSD-OTC` testing on live practice data:

- signal engine: `blitz`
- candle timeframe: `30s`
- recommended expiry: `60s`
- current logic: two aligned candles in the same direction plus a minimum total move filter
- current default thresholds after live tuning:
  - minimum body-to-range ratio: `0.40`
  - minimum total move percent: `0.00012`

Important limitation:

- the current IQ Option adapter only submits expiries in whole minutes, so `30s` entry candles are supported but `30s` broker expiry is not

Command shape:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --env-file .env \
  --broker iqoption \
  --market-data-source iqoption \
  --strategy-version-id eurusd-otc-blitz-v1 \
  --asset EURUSD-OTC \
  --instrument-type binary \
  --signal-engine blitz \
  --timeframe-sec 30 \
  --stake 1.0 \
  --expiry-sec 60 \
  --cycles 3 \
  --poll-interval-sec 35 \
  --duplicate-window-sec 1 \
  --max-data-age-sec 90
```

Latest observed live batch result in this workspace:

```text
campaign_status=completed campaign_id=otc-blitz-batch-20260409b-campaign closed_trades=4 reason=None
checkpoint=1 closed_trades=2 tranche_wins=2 tranche_losses=0 tranche_breakevens=0 tranche_net_pnl=1.7000 tranche_expectancy=0.8500 cumulative_net_pnl=1.7000 cumulative_profit_factor=0.0000
checkpoint=2 closed_trades=4 tranche_wins=2 tranche_losses=0 tranche_breakevens=0 tranche_net_pnl=1.7000 tranche_expectancy=0.8500 cumulative_net_pnl=3.4000 cumulative_profit_factor=0.0000
```

Observed asset concentration in that batch:

- `GBPUSD-OTC`: `4` trades, `4` wins, net P/L `+3.40`
- `EURUSD-OTC`: no qualifying entries during the same window

Extended live sample after that run:

- strategy id: `otc-blitz-batch-20260409c`
- asset: `GBPUSD-OTC`
- closed trades: `50`
- wins: `28`
- losses: `21`
- breakevens: `1`
- net P/L: `+2.80`

Important runtime fix applied after reviewing the 50-trade history:

- binary IQ Option entries are now blocked outside the first `2` seconds of a new minute
- this avoids submitting a nominal `60s` binary trade halfway through the broker's active minute bucket
- prior journal rows showed entries like `10:58:11` and `10:59:51`, which materially shortened effective holding time and distorted outcomes

### Option 7: Multi-asset binary campaign mode with 20-trade checkpoints

There is now a batch-testing mode for practice `binary` runs that rotates across multiple assets and waits for each trade to close before counting it toward the campaign target.

This is the safer path for a `100`-trade test because it keeps the existing max-open-position guard intact instead of stacking unresolved positions.

Recommended shape for `1m` binary testing:

```powershell
& "c:/Users/ASUS/Desktop/New folder (7)/.venv/Scripts/python.exe" -m src.bot.cli \
  --env-file .env \
  --broker iqoption \
  --market-data-source iqoption \
  --strategy-version-id otc-binary-batch-v1 \
  --asset EURUSD-OTC \
  --asset GBPUSD-OTC \
  --asset USDJPY-OTC \
  --instrument-type binary \
  --timeframe-sec 60 \
  --stake 1.0 \
  --expiry-sec 60 \
  --target-closed-trades 100 \
  --checkpoint-trades 20 \
  --poll-interval-sec 5 \
  --duplicate-window-sec 1 \
  --max-data-age-sec 180
```

Expected output shape:

```text
campaign_status=completed campaign_id=... closed_trades=100 reason=None
checkpoint=1 closed_trades=20 tranche_wins=... tranche_losses=... tranche_breakevens=... tranche_net_pnl=... tranche_expectancy=... cumulative_net_pnl=... cumulative_profit_factor=...
checkpoint_asset=1 asset=EURUSD-OTC trades=... wins=... losses=... breakevens=... net_pnl=...
```

Behavior notes:

- repeat `--asset` to build the asset rotation list
- `--target-closed-trades` enables campaign mode
- `--checkpoint-trades 20` emits tranche summaries every 20 resolved trades
- tranche runs are journaled under suffixed strategy ids such as `otc-binary-batch-v1-t01`, `-t02`, and so on for easier review and adjustment

## Files to check after a run

- Database: `data/trades.db`
- Runtime JSONL logs: `logs/runtime/*.jsonl`
- Code status summary: `docs/implementation-status.md`

## What is not finished yet

### Not yet production-ready

- 2FA is still treated as a blocking condition for unattended runs

### Missing operational depth

- No packaging or deployment workflow
- No backtest or replay ingestion pipeline
- No dashboards or summary queries over `system_events`
- No cross-process duplicate protection
- No proposal generation and approval workflow yet

## Recommended next action

If your goal is to confirm the bot is actually runnable end-to-end, the next practical step is:

1. inspect `data/trades.db` and `logs/runtime/*.jsonl` for the confirmed `EURUSD-OTC` binary practice probe
2. run repeated scheduler cycles on `EURUSD-OTC` binary until the strategy itself emits and resolves a real trade
3. compare scheduler-submitted trades against the direct probe path
4. only then consider widening strategy logic or automation depth
