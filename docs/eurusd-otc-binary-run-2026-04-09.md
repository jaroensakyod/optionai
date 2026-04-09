# EURUSD-OTC Binary Practice Run 2026-04-09

## Scope

- Broker: IQ Option practice account
- Asset: `EURUSD-OTC`
- Instrument: `binary`
- Timeframe: `60s`
- Stake: `1.0`
- Expiry: `60s`

## What was executed

### 1. Connectivity smoke test

Smoke test passed against the real practice account.

Observed result:

```text
status=passed balance=10023.0 candle_count=3 reason=None
```

### 2. Explicit broker order probe

A direct practice order probe was submitted and closed successfully end-to-end.

Observed result:

```text
status=closed trade_id=trade-1a6114994dc74e25a44fe2a1de3d36fd result=LOSS profit_loss_abs=-1.0 reason=None
```

### 3. Strategy-path scheduler run before strategy refinement

One real scheduler cycle on `EURUSD-OTC` binary submitted a trade from the strategy path.

Observed result:

```text
status=submitted reason=None signal_id=signal-e2bd822758614e6c82739e90bd0191ba trade_id=trade-feefe5aed9014317be8b7c7be812c1f4
```

Resolved broker result:

```text
result=WIN
profit_loss_abs=0.85
close_reason=broker_poll
```

### 4. Multi-cycle scheduler run before strategy refinement

Three scheduler cycles were executed on `EURUSD-OTC` binary.

Observed outputs:

```text
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
status=submitted reason=None signal_id=signal-44706acbf92a488091705c0e728df178 trade_id=trade-9e8f215fbf5b4928943e4bdde46163b3
```

Resolved broker result for the submitted trade:

```text
result=LOSS
profit_loss_abs=-1.0
close_reason=broker_poll
```

## Recorded trade outcomes

Recent `EURUSD-OTC` binary trades recorded in the journal after the run sequence:

- `trade-9e8f215fbf5b4928943e4bdde46163b3` -> `LOSS`, `-1.0`
- `trade-feefe5aed9014317be8b7c7be812c1f4` -> `WIN`, `0.85`
- `trade-1a6114994dc74e25a44fe2a1de3d36fd` -> `LOSS`, `-1.0`

This is not enough sample size to claim edge or profitability.

## Errors and issues observed

### Library issue

The `stable_api` method `get_all_open_time()` raised a `KeyError: 'underlying'` in this environment when trying to inspect all markets.

Workaround used:

- fall back to `get_all_profit()` to enumerate OTC assets with binary payout data
- verify `EURUSD-OTC` payout and candles directly from the broker

### Strategy issue

The original strategy treated three rising or falling closes as enough for entry, even if one of the candles had a body in the opposite direction.

That produced weak signals for one-minute OTC binary conditions.

## Strategy change applied

The momentum strategy was tightened in `src/bot/signal_engine.py`:

- require candle bodies to align with the signal direction
- require a minimum body-to-range ratio
- keep the existing total-move filter

Rationale:

- avoid counting noisy close-to-close drift as real momentum
- reduce false entries where one candle contradicts the trade direction
- make OTC binary entries more selective

## Post-fix check

After the strategy refinement, a fresh one-cycle run on `EURUSD-OTC` binary returned:

```text
status=skipped reason=no_signal signal_id=None trade_id=None
```

Interpretation:

- the stricter filter rejected the current market structure
- this is expected behavior when the setup is weak
- it reduces trade frequency, not proof of profitability

### Post-fix multi-cycle check

Five additional scheduler cycles were executed on `EURUSD-OTC` binary after the strategy refinement.

Observed outputs:

```text
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
```

Interpretation:

- the refined filter substantially reduced entry frequency
- no new post-fix trade was opened during this sample window
- the filter is behaving conservatively rather than forcing low-quality entries

## Metrics from trades.db

### Asset-level metrics for `EURUSD-OTC`

Derived from the journal rows currently recorded for this asset:

- total trades: `3`
- wins: `1`
- losses: `2`
- win rate: `33.33%`
- gross profit: `0.85`
- gross loss: `2.0`
- net P/L: `-1.15`
- avg win: `0.85`
- avg loss: `1.0`
- payout ratio: `0.85`
- expectancy per trade: `-0.3833`
- profit factor: `0.425`

### Strategy-version metrics for `eurusd-otc-binary-v1`

- total trades: `2`
- wins: `1`
- losses: `1`
- win rate: `50.0%`
- net P/L: `-0.15`
- expectancy per trade: `-0.075`
- payout ratio: `0.85`

For a binary payout near `0.85`, the rough break-even win rate is:

```text
1 / (1 + 0.85) = 54.05%
```

That means the observed pre-fix strategy path is still below the approximate break-even threshold.

## Data-driven strategy decision

Based on the real sample gathered so far, the safest justified change was the one already applied:

- reject weak momentum where candle bodies do not align with the proposed direction
- reject candles whose bodies are too small relative to total range

No further parameter change is justified yet from the post-fix sample because:

- the post-fix run produced zero new trades
- the live sample size is still too small
- pushing for more entries now would be guesswork rather than data-driven tuning

## Validation after the fix

Full test suite result after the strategy change:

```text
44 passed
```

## 30-second blitz exploration

To reduce waiting time per setup, a new `blitz` signal-engine preset was added for `30s` candles.

Current blitz rules:

- use the last `2` candles
- require both candle bodies to align with the trade direction
- require body-to-range ratio of at least `0.55` on both candles
- require total move percent of at least `0.0002`
- keep broker expiry at `60s`

Important limitation:

- the current IQ Option adapter still submits expiries in whole minutes, so this is a `30s` signal engine with `60s` expiry, not a true `30s` expiry order path

### Live feed check for 30-second candles

The live practice feed accepted `30s` candle requests successfully.

Observed smoke result:

```text
status=passed balance=10021.85 candle_count=4 reason=None
```

### Live blitz scheduler run

Three live scheduler cycles were executed with:

- asset: `EURUSD-OTC`
- instrument: `binary`
- signal engine: `blitz`
- timeframe: `30s`
- expiry: `60s`

Observed outputs:

```text
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
status=skipped reason=no_signal signal_id=None trade_id=None
```

Interpretation:

- the live `30s` chart path works
- the current blitz thresholds are selective enough to avoid forcing entries in weak microstructure
- this run did not produce a real trade yet

## Blitz campaign retune and batch result

The original blitz thresholds were too selective for the observed live `30s` OTC tape during the later session window.

Live review of recent `30s` candles showed that a moderate relaxation produced materially more valid two-candle setups without dropping the directional-alignment rule.

Updated blitz defaults in `src/bot/signal_engine.py`:

- minimum body-to-range ratio: `0.40` (was `0.55`)
- minimum total move percent: `0.00012` (was `0.0002`)

Validation after the retune:

```text
13 passed
```

### Live multi-asset blitz batch after retune

Command shape used:

```text
strategy-version-id=otc-blitz-batch-20260409b
assets=EURUSD-OTC, GBPUSD-OTC
timeframe=30s
expiry=60s
target-closed-trades=4
checkpoint-trades=2
```

Observed result:

```text
campaign_status=completed campaign_id=otc-blitz-batch-20260409b-campaign closed_trades=4 reason=None
checkpoint=1 closed_trades=2 tranche_wins=2 tranche_losses=0 tranche_breakevens=0 tranche_net_pnl=1.7000 tranche_expectancy=0.8500 cumulative_net_pnl=1.7000 cumulative_profit_factor=0.0000
checkpoint=2 closed_trades=4 tranche_wins=2 tranche_losses=0 tranche_breakevens=0 tranche_net_pnl=1.7000 tranche_expectancy=0.8500 cumulative_net_pnl=3.4000 cumulative_profit_factor=0.0000
```

Recorded trade outcomes so far for `otc-blitz-batch-20260409b`:

- `GBPUSD-OTC` -> `WIN`, `+0.85`
- `GBPUSD-OTC` -> `WIN`, `+0.85`
- `GBPUSD-OTC` -> `WIN`, `+0.85`
- `GBPUSD-OTC` -> `WIN`, `+0.85`

Interpretation:

- the relaxed blitz thresholds converted from repeated `no_signal` into real fillable setups
- the profitable sample is still small, but it is the strongest live result recorded in this workspace so far
- during this batch window, the edge concentrated entirely in `GBPUSD-OTC`; `EURUSD-OTC` produced no qualifying entry

## Extended GBPUSD-OTC sample

The blitz configuration was then expanded on `GBPUSD-OTC` alone to gather a larger unchanged-configuration sample before any further tuning.

Observed result for `otc-blitz-batch-20260409c`:

```text
closed trades=50
wins=28
losses=21
breakevens=1
net_pnl=+2.80
```

Checkpoint profile:

- tranche 1: `6W 4L`, `+1.10`
- tranche 2: `7W 3L`, `+2.95`
- tranche 3: `4W 6L`, `-2.60`
- tranche 4: `7W 3L`, `+2.95`
- tranche 5: `4W 5L 1BE`, `-1.60`

This confirms the strategy stayed net profitable across the full 50-trade sample, but with meaningful volatility between tranches.

## Entry-timing defect and fix

Review of the recorded `opened_at_utc` timestamps showed multiple binary entries being submitted well after the start of the active minute, for example:

- `10:58:11+00:00`
- `10:59:51+00:00`

For IQ Option binary orders with `60s` expiry, that means the bot could be entering partway through the broker's minute bucket instead of effectively entering at the candle open.

This was treated as a runtime defect rather than a strategy parameter issue.

Fix applied in `src/bot/bot_runner.py`:

- binary trades with whole-minute expiries now skip unless current time is within the first `2` seconds of the minute
- skip reason: `awaiting_entry_window`

Validation status after the fix:

```text
18 passed
```

Interpretation:

- the 50-trade sample remains useful for diagnosing strategy behavior
- but future binary results should be cleaner because entries will no longer be allowed deep into the active minute bucket

### Snapshot after the blitz run

The latest fetched `30s` candles immediately after the run were mostly mixed or weak-body candles, for example:

```text
2026-04-09T07:14:30+00:00 open=1.176995 close=1.177045 body_ratio=0.1316
2026-04-09T07:15:00+00:00 open=1.177075 close=1.177115 body_ratio=0.2222
```

That explains why the engine returned `no_signal` at the time of inspection.

## Practical conclusion

- The system can now connect, fetch real practice data, submit real practice binary OTC orders, and close them into the journal.
- The strategy path has already submitted real `EURUSD-OTC` binary orders on its own.
- The current strategy is still experimental and cannot be claimed profitable from this sample.
- The latest refinement makes entries stricter and more defensible, but it does not guarantee profit.
- The next valid tuning step is to gather more post-fix trades, not to loosen the filter immediately.
