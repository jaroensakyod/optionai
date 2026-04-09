---
applyTo: "src/bot/**/*.py"
description: "Use when: modifying signal logic, risk controls, trade journaling, or metrics code in the trading bot runtime"
---

# Strategy And Runtime Rules

- Keep signal generation pure where possible; do not let strategy modules call broker APIs directly.
- Preserve practice-mode gating and risk limits.
- Do not introduce hidden side effects into metrics functions.
- Prefer explicit domain enums and typed fields for values used in reporting.
