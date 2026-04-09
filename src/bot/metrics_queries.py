from collections import defaultdict

from .models import GroupedMetricSnapshot
from .stats_service import build_metric_snapshot
from .trade_journal import TradeJournalRepository


class MetricsQueryService:
    def __init__(self, repository: TradeJournalRepository):
        self._repository = repository

    def summary(self, *, account_mode: str | None = None):
        return build_metric_snapshot(self._repository.list_trades(account_mode=account_mode))

    def by_asset(self, *, account_mode: str | None = None) -> list[GroupedMetricSnapshot]:
        grouped: dict[str, list] = defaultdict(list)
        for trade in self._repository.list_trades(account_mode=account_mode):
            grouped[trade.asset].append(trade)
        return self._build_grouped_metrics(grouped)

    def by_strategy_version(self, *, account_mode: str | None = None) -> list[GroupedMetricSnapshot]:
        grouped: dict[str, list] = defaultdict(list)
        for trade in self._repository.list_trades(account_mode=account_mode):
            grouped[trade.strategy_version_id].append(trade)
        return self._build_grouped_metrics(grouped)

    def by_session(self, *, account_mode: str | None = None) -> list[GroupedMetricSnapshot]:
        grouped: dict[str, list] = defaultdict(list)
        for context in self._repository.list_trade_contexts(account_mode=account_mode):
            key = context.session_label.value if context.session_label is not None else "unknown"
            grouped[key].append(context.trade)
        return self._build_grouped_metrics(grouped)

    @staticmethod
    def _build_grouped_metrics(grouped_records: dict[str, list]) -> list[GroupedMetricSnapshot]:
        return [
            GroupedMetricSnapshot(group_key=group_key, metrics=build_metric_snapshot(records))
            for group_key, records in sorted(grouped_records.items())
        ]
