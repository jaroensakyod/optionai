---
applyTo: "logs/**/*.csv"
description: "Use when: analyzing trading CSV logs, reviewing backtest outputs, or comparing journal exports to metrics summaries"
---

# Trading Log Analysis Rules

- Use UTC timestamps as the reference timeline.
- Prefer metrics derived from closed trades only.
- Treat rejected or errored orders as operational issues unless the user explicitly asks to include them in performance metrics.
- Flag these conditions when found:
  - loss streak >= 5
  - max drawdown > 10%
  - profit factor < 1.0
  - frequent missing close results
