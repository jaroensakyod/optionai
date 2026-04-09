from collections.abc import Iterable

from .models import MetricSnapshot, TradeJournalRecord, TradeResult


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _compute_streaks(records: list[TradeJournalRecord]) -> tuple[int, int]:
    longest_win = 0
    longest_loss = 0
    current_win = 0
    current_loss = 0

    for record in sorted(records, key=lambda item: item.closed_at_utc or item.opened_at_utc):
        if record.result == TradeResult.WIN:
            current_win += 1
            current_loss = 0
        elif record.result == TradeResult.LOSS:
            current_loss += 1
            current_win = 0
        else:
            current_win = 0
            current_loss = 0

        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)

    return longest_win, longest_loss


def _compute_drawdown(records: list[TradeJournalRecord]) -> tuple[float, float]:
    running_equity = 0.0
    peak_equity = 0.0
    max_drawdown_abs = 0.0
    max_drawdown_pct = 0.0

    for record in sorted(records, key=lambda item: item.closed_at_utc or item.opened_at_utc):
        running_equity += record.profit_loss_abs or 0.0
        peak_equity = max(peak_equity, running_equity)
        drawdown_abs = peak_equity - running_equity
        max_drawdown_abs = max(max_drawdown_abs, drawdown_abs)
        if peak_equity > 0:
            max_drawdown_pct = max(max_drawdown_pct, drawdown_abs / peak_equity)

    return max_drawdown_abs, max_drawdown_pct


def build_metric_snapshot(records: Iterable[TradeJournalRecord]) -> MetricSnapshot:
    closed_records = [
        record
        for record in records
        if record.result in {TradeResult.WIN, TradeResult.LOSS, TradeResult.BREAKEVEN}
    ]

    wins = [record for record in closed_records if record.result == TradeResult.WIN]
    losses = [record for record in closed_records if record.result == TradeResult.LOSS]
    breakevens = [record for record in closed_records if record.result == TradeResult.BREAKEVEN]

    gross_profit = sum(max(record.profit_loss_abs or 0.0, 0.0) for record in wins)
    gross_loss = abs(sum(min(record.profit_loss_abs or 0.0, 0.0) for record in losses))
    net_pnl = sum(record.profit_loss_abs or 0.0 for record in closed_records)

    avg_win = _safe_divide(gross_profit, len(wins))
    avg_loss = _safe_divide(gross_loss, len(losses))
    payoff_ratio = _safe_divide(avg_win, avg_loss)
    expectancy = _safe_divide(net_pnl, len(closed_records))
    profit_factor = _safe_divide(gross_profit, gross_loss)
    longest_win_streak, longest_loss_streak = _compute_streaks(closed_records)
    max_drawdown_abs, max_drawdown_pct = _compute_drawdown(closed_records)

    return MetricSnapshot(
        total_trades=len(closed_records),
        wins=len(wins),
        losses=len(losses),
        breakevens=len(breakevens),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        expectancy_per_trade=expectancy,
        profit_factor=profit_factor,
        longest_win_streak=longest_win_streak,
        longest_loss_streak=longest_loss_streak,
        max_drawdown_abs=max_drawdown_abs,
        max_drawdown_pct=max_drawdown_pct,
    )
