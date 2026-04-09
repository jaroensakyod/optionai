# Trading Bot Repository Instructions

## Operating constraints

- Treat this repository as practice-mode only unless the user explicitly changes scope.
- Never add logic that submits live broker orders by default.
- Prefer changes that improve observability, auditability, and rollback over automation depth.
- Use `trade_journal` as the source of truth for metrics and AI summaries.

## Implementation priorities

1. Keep broker integration isolated from signal logic.
2. Keep metrics derivation deterministic and testable.
3. Keep AI proposal generation outside the live execution path.
4. Favor small, auditable parameter changes over broad strategy rewrites.

## Code modification rules

- When changing metrics logic, preserve backward compatibility of existing journal fields where possible.
- When changing strategy behavior, update any related schema or documentation if the change affects analytics interpretation.
- When adding new fields, prefer explicit columns over JSON if the field will be queried often.

## Validation expectations

- For schema changes, ensure the journal can still reconstruct net P/L, streaks, and drawdown.
- For stats changes, verify behavior against `WIN`, `LOSS`, and `BREAKEVEN` cases first.
- Do not treat `REJECTED` or `ERROR` as trading wins or losses unless explicitly requested.
