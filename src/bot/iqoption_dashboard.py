from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from os import getenv
import re
from typing import Any, Callable

from .config import AppConfig
from .iqoption_adapter import IQOptionAdapterError, IQOptionCredentials
from .models import InstrumentType, MetricSnapshot, SessionLabel, TradeContextRecord, TradeJournalRecord
from .stats_service import build_metric_snapshot
from .trade_journal import TradeJournalRepository


_FOREX_BINARY_ASSET_PATTERN = re.compile(r"^[A-Z]{6}(?:-OTC)?$")
_FOREX_CURRENCY_CODES = {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"}


@dataclass(frozen=True, slots=True)
class BinaryPairStatus:
    asset: str
    payout: float | None
    is_open: bool
    is_supported: bool
    trade_count: int
    win_rate_pct: float
    net_pnl: float
    opportunity_score_pct: float
    opportunity_band: str
    opportunity_updated_at_utc: str
    is_recommended: bool = False
    recommendation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TradeHistoryRow:
    trade_id: str
    asset: str
    opened_at_utc: str
    closed_at_utc: str | None
    direction: str
    result: str
    amount: float
    profit_loss_abs: float | None
    payout_snapshot: float | None
    strategy_display: str


@dataclass(frozen=True, slots=True)
class OpenPositionRow:
    trade_id: str
    asset: str
    opened_at_utc: str
    age_sec: int
    expiry_sec: int
    broker_reference: str | None
    status: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    account_mode: str
    balance: float
    market_status: str
    binary_pairs: tuple[BinaryPairStatus, ...]
    recommended_pairs: tuple[BinaryPairStatus, ...]
    selected_assets: tuple[str, ...]
    summary_metrics: MetricSnapshot
    selected_asset_metrics: MetricSnapshot
    recent_trades: tuple[TradeHistoryRow, ...]
    open_positions: tuple[OpenPositionRow, ...]
    block_reason: str


@dataclass(frozen=True, slots=True)
class StrategyAnalyticsRow:
    strategy_display: str
    group_value: str
    trades: int
    wins: int
    losses: int
    win_rate_pct: float
    net_pnl: float
    profit_factor: float


@dataclass(frozen=True, slots=True)
class StrategyAnalyticsSnapshot:
    by_asset: tuple[StrategyAnalyticsRow, ...]
    by_session: tuple[StrategyAnalyticsRow, ...]


@dataclass(frozen=True, slots=True)
class LocalSelectionView:
    selected_assets: tuple[str, ...]
    selected_asset_metrics: MetricSnapshot
    recent_trades: tuple[TradeHistoryRow, ...]


class IQOptionDashboardService:
    def __init__(
        self,
        config: AppConfig,
        repository: TradeJournalRepository,
        credentials: IQOptionCredentials,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        if config.app_mode != "PRACTICE":
            raise ValueError("IQOptionDashboardService is restricted to PRACTICE mode during MVP.")
        self._config = config
        self._repository = repository
        self._credentials = credentials
        self._client_factory = client_factory or self._default_client_factory
        self._client: Any | None = None
        self._selected_account_mode = "PRACTICE"
        self._actives_refreshed = False

    @classmethod
    def from_environment(
        cls,
        config: AppConfig,
        repository: TradeJournalRepository,
        client_factory: Callable[[str, str], Any] | None = None,
    ) -> IQOptionDashboardService:
        email = getenv("IQOPTION_EMAIL")
        password = getenv("IQOPTION_PASSWORD")
        if not email or not password:
            raise IQOptionAdapterError("Missing IQOPTION_EMAIL or IQOPTION_PASSWORD in environment.")
        return cls(
            config=config,
            repository=repository,
            credentials=IQOptionCredentials(email=email, password=password),
            client_factory=client_factory,
        )

    def connect(self) -> None:
        client = self._client_factory(self._credentials.email, self._credentials.password)
        status, reason = client.connect()
        if not status:
            if reason == "2FA":
                raise IQOptionAdapterError("IQ Option 2FA is enabled and blocks unattended MVP automation.")
            raise IQOptionAdapterError(f"IQ Option dashboard connect failed: {reason}")
        client.change_balance(self._selected_account_mode)
        self._client = client
        self._actives_refreshed = False

    @property
    def selected_account_mode(self) -> str:
        return self._selected_account_mode

    def update_account_mode(self, account_mode: str) -> None:
        normalized_mode = _normalize_account_mode(account_mode)
        self._selected_account_mode = normalized_mode
        if self._client is not None:
            self._client.change_balance(normalized_mode)

    def update_credentials(self, *, email: str, password: str) -> None:
        normalized_email = email.strip()
        normalized_password = password.strip()
        if not normalized_email or not normalized_password:
            raise IQOptionAdapterError("Username and password are required for login.")
        self.disconnect()
        self._credentials = IQOptionCredentials(email=normalized_email, password=normalized_password)

    def disconnect(self) -> None:
        if self._client is None:
            return
        logout = getattr(self._client, "logout", None)
        if callable(logout):
            try:
                logout()
            except Exception:
                pass
        self._client = None
        self._actives_refreshed = False

    def is_connected(self) -> bool:
        return self._client is not None and bool(self._client.check_connect())

    def reconnect_if_needed(self) -> bool:
        if self._client is None:
            self.connect()
            return True
        if self._client.check_connect():
            return True
        status, reason = self._client.connect()
        if not status:
            raise IQOptionAdapterError(f"IQ Option dashboard reconnect failed: {reason}")
        self._client.change_balance(self._selected_account_mode)
        self._actives_refreshed = False
        return True

    def load_snapshot(self, *, selected_assets: tuple[str, ...] | None = None, history_limit: int = 20) -> DashboardSnapshot:
        self.reconnect_if_needed()
        binary_pairs = self.list_open_binary_pairs()
        selected = _normalize_selected_assets(selected_assets, binary_pairs)
        binary_trades = self._list_binary_trades(selected_assets=None)
        selected_binary_trades = self._list_binary_trades(selected_assets=selected)
        closed_selected_binary_trades = [trade for trade in selected_binary_trades if trade.closed_at_utc is not None]
        open_positions = self._list_open_positions()
        recommended_pairs = tuple(pair for pair in binary_pairs if pair.is_recommended)[:3]
        return DashboardSnapshot(
            account_mode=self._selected_account_mode,
            balance=float(self._client.get_balance()),
            market_status="OPEN" if binary_pairs else "CLOSED",
            binary_pairs=binary_pairs,
            recommended_pairs=recommended_pairs,
            selected_assets=selected,
            summary_metrics=build_metric_snapshot(binary_trades),
            selected_asset_metrics=build_metric_snapshot(selected_binary_trades),
            recent_trades=tuple(self._build_trade_history_rows(closed_selected_binary_trades[-history_limit:])),
            open_positions=open_positions,
            block_reason=self._build_block_reason(open_positions),
        )

    def build_strategy_analytics_snapshot(self) -> StrategyAnalyticsSnapshot:
        trade_contexts = [
            context
            for context in self._repository.list_trade_contexts(account_mode=self._selected_account_mode)
            if context.trade.instrument_type == InstrumentType.BINARY
            and _is_otc_asset(context.trade.asset)
            and context.trade.closed_at_utc is not None
        ]
        return StrategyAnalyticsSnapshot(
            by_asset=tuple(self._build_strategy_analytics_rows(trade_contexts, group_by="asset")),
            by_session=tuple(self._build_strategy_analytics_rows(trade_contexts, group_by="session")),
        )

    def clear_binary_history(self) -> int:
        deleted_trades = self._repository.clear_binary_history(account_mode=self._selected_account_mode)
        self._repository.clear_system_events(component="desktop_session")
        return deleted_trades

    def list_open_binary_pairs(self) -> tuple[BinaryPairStatus, ...]:
        self.reconnect_if_needed()
        refreshed_at = datetime.now(UTC)
        profits = self._safe_get_all_profit()
        supported_assets = self._supported_binary_assets()
        metrics_by_asset = self._build_metrics_by_asset()
        statuses: list[BinaryPairStatus] = []

        for asset in sorted(profits):
            if not _is_supported_binary_forex_pair(asset) or not _is_otc_asset(asset):
                continue
            payout = _extract_payout(profits, asset)
            if payout is None:
                continue
            statuses.append(
                self._build_pair_status(
                    asset=asset,
                    payout=payout,
                    metrics_by_asset=metrics_by_asset,
                    refreshed_at=refreshed_at,
                    is_supported=supported_assets is None or asset in supported_assets,
                )
            )

        ranked = sorted(statuses, key=_pair_sort_key)
        recommended_assets = {pair.asset for pair in ranked if pair.is_supported and pair.is_open}
        recommended_assets = set(list(recommended_assets)[:3])
        return tuple(
            BinaryPairStatus(
                asset=pair.asset,
                payout=pair.payout,
                is_open=pair.is_open,
                is_supported=pair.is_supported,
                trade_count=pair.trade_count,
                win_rate_pct=pair.win_rate_pct,
                net_pnl=pair.net_pnl,
                opportunity_score_pct=pair.opportunity_score_pct,
                opportunity_band=pair.opportunity_band,
                opportunity_updated_at_utc=pair.opportunity_updated_at_utc,
                is_recommended=pair.asset in recommended_assets,
                recommendation_reason=_recommendation_reason(pair) if pair.asset in recommended_assets else None,
            )
            for pair in ranked
        )

    def build_local_selection_view(self, *, selected_assets: tuple[str, ...], history_limit: int = 20) -> LocalSelectionView:
        selected_binary_trades = self._list_binary_trades(selected_assets=selected_assets)
        closed_selected_binary_trades = [trade for trade in selected_binary_trades if trade.closed_at_utc is not None]
        return LocalSelectionView(
            selected_assets=selected_assets,
            selected_asset_metrics=build_metric_snapshot(selected_binary_trades),
            recent_trades=tuple(self._build_trade_history_rows(closed_selected_binary_trades[-history_limit:])),
        )

    def _list_binary_trades(self, *, selected_assets: tuple[str, ...] | None) -> list[TradeJournalRecord]:
        trades = [
            trade
            for trade in self._repository.list_trades(account_mode=self._selected_account_mode)
            if trade.instrument_type == InstrumentType.BINARY and _is_otc_asset(trade.asset)
        ]
        if selected_assets:
            selected_set = set(selected_assets)
            trades = [trade for trade in trades if trade.asset in selected_set]
        return trades

    def _build_metrics_by_asset(self) -> dict[str, MetricSnapshot]:
        assets = sorted({trade.asset for trade in self._list_binary_trades(selected_assets=None)})
        return {
            asset: build_metric_snapshot(self._list_binary_trades(selected_assets=(asset,)))
            for asset in assets
        }

    def _list_open_positions(self) -> tuple[OpenPositionRow, ...]:
        now_utc = datetime.now(UTC)
        open_trades = [
            trade
            for trade in self._repository.list_trades(account_mode=self._selected_account_mode)
            if trade.instrument_type == InstrumentType.BINARY and trade.closed_at_utc is None
        ]
        rows = [
            OpenPositionRow(
                trade_id=trade.trade_id,
                asset=trade.asset,
                opened_at_utc=trade.opened_at_utc.isoformat(),
                age_sec=max(int((now_utc - trade.opened_at_utc).total_seconds()), 0),
                expiry_sec=trade.expiry_sec,
                broker_reference=trade.broker_position_id or trade.broker_order_id,
                status="OPEN",
            )
            for trade in open_trades
        ]
        return tuple(sorted(rows, key=lambda row: row.opened_at_utc, reverse=True))

    def _build_block_reason(self, open_positions: tuple[OpenPositionRow, ...]) -> str:
        if self._config.risk_limits.max_open_positions > 0:
            open_counts_by_asset: dict[str, int] = {}
            for position in open_positions:
                open_counts_by_asset[position.asset] = open_counts_by_asset.get(position.asset, 0) + 1
            blocking_asset = next(
                (
                    asset
                    for asset, count in sorted(open_counts_by_asset.items())
                    if count >= self._config.risk_limits.max_open_positions
                ),
                None,
            )
            if blocking_asset is not None:
                blocking_count = open_counts_by_asset[blocking_asset]
                return (
                    f"{blocking_asset} already has open order ({blocking_count}/{self._config.risk_limits.max_open_positions})"
                )
        for event in reversed(self._repository.list_system_events(component="desktop_session")):
            reason = event.details.get("reason")
            if event.event_type == "run_skipped" and isinstance(reason, str) and reason:
                return reason
            if event.event_type == "stale_market_data" and isinstance(reason, str) and reason:
                return reason
            if event.event_type in {"duplicate_signal_prevented", "no_signal", "entry_window_wait"}:
                if isinstance(reason, str) and reason:
                    return reason
                return event.event_type
        return "-"

    def _build_pair_status(
        self,
        *,
        asset: str,
        payout: float | None,
        metrics_by_asset: dict[str, MetricSnapshot],
        refreshed_at: datetime,
        is_supported: bool,
    ) -> BinaryPairStatus:
        metrics = metrics_by_asset.get(asset) or build_metric_snapshot([])
        total_trades = metrics.total_trades
        win_rate_pct = 0.0 if total_trades == 0 else (metrics.wins / total_trades) * 100.0
        opportunity_score_pct = _estimate_opportunity_score(metrics=metrics, payout=payout)
        return BinaryPairStatus(
            asset=asset,
            payout=payout,
            is_open=True,
            is_supported=is_supported,
            trade_count=total_trades,
            win_rate_pct=win_rate_pct,
            net_pnl=metrics.net_pnl,
            opportunity_score_pct=opportunity_score_pct,
            opportunity_band=_opportunity_band(opportunity_score_pct),
            opportunity_updated_at_utc=refreshed_at.isoformat(),
        )

    def _build_trade_history_rows(self, trades: list[TradeJournalRecord]) -> list[TradeHistoryRow]:
        rows: list[TradeHistoryRow] = []
        for trade in reversed(trades):
            rows.append(
                TradeHistoryRow(
                    trade_id=trade.trade_id,
                    asset=trade.asset,
                    opened_at_utc=trade.opened_at_utc.isoformat(),
                    closed_at_utc=trade.closed_at_utc.isoformat() if trade.closed_at_utc is not None else None,
                    direction=trade.direction.value,
                    result=trade.result.value if trade.result is not None else "OPEN",
                    amount=trade.amount,
                    profit_loss_abs=trade.profit_loss_abs,
                    payout_snapshot=trade.payout_snapshot,
                    strategy_display=self._strategy_display_for_trade(trade),
                )
            )
        return rows

    def _strategy_display_for_trade(self, trade: TradeJournalRecord) -> str:
        tags = self._repository.get_trade_tags(trade.trade_id)
        display = tags.get("strategy_display")
        if display:
            return display
        profiles = [profile for profile in tags.get("strategy_profiles", "").split(",") if profile]
        if profiles:
            return " + ".join(profiles)
        fallback_profile = tags.get("strategy_profile")
        if fallback_profile:
            return fallback_profile
        return "UNKNOWN"

    def _build_strategy_analytics_rows(
        self,
        trade_contexts: list[TradeContextRecord],
        *,
        group_by: str,
    ) -> list[StrategyAnalyticsRow]:
        grouped: dict[tuple[str, str], list[TradeJournalRecord]] = {}
        for context in trade_contexts:
            strategy_displays = self._strategy_groups_for_trade(context.trade)
            if group_by == "asset":
                group_value = context.trade.asset
            else:
                group_value = _format_session_label(context.session_label)
            for strategy_display in strategy_displays:
                grouped.setdefault((strategy_display, group_value), []).append(context.trade)
        rows: list[StrategyAnalyticsRow] = []
        for (strategy_display, group_value), trades in grouped.items():
            metrics = build_metric_snapshot(trades)
            total_trades = metrics.total_trades
            if total_trades <= 0:
                continue
            win_rate_pct = 0.0 if total_trades == 0 else (metrics.wins / total_trades) * 100.0
            rows.append(
                StrategyAnalyticsRow(
                    strategy_display=strategy_display,
                    group_value=group_value,
                    trades=total_trades,
                    wins=metrics.wins,
                    losses=metrics.losses,
                    win_rate_pct=win_rate_pct,
                    net_pnl=metrics.net_pnl,
                    profit_factor=metrics.profit_factor,
                )
            )
        return sorted(rows, key=lambda row: (-row.net_pnl, -row.win_rate_pct, row.strategy_display, row.group_value))

    def _strategy_groups_for_trade(self, trade: TradeJournalRecord) -> tuple[str, ...]:
        tags = self._repository.get_trade_tags(trade.trade_id)
        profiles = tuple(profile for profile in tags.get("strategy_profiles", "").split(",") if profile)
        if profiles:
            return profiles
        profile = tags.get("strategy_profile")
        if profile:
            return (profile,)
        display = tags.get("strategy_display")
        if display:
            return (display,)
        return ()

    def _safe_get_all_profit(self) -> dict[str, dict[str, float | None]]:
        profits = self._client.get_all_profit()
        if not isinstance(profits, dict):
            return {}
        return profits

    def _supported_binary_assets(self) -> set[str] | None:
        getter = getattr(self._client, "get_all_ACTIVES_OPCODE", None)
        if not callable(getter):
            getter = getattr(self._client, "get_ALL_Binary_ACTIVES_OPCODE", None)
        if not callable(getter):
            return None
        if not self._actives_refreshed:
            updater = getattr(self._client, "update_ACTIVES_OPCODE", None)
            if callable(updater):
                try:
                    updater()
                except Exception:
                    pass
            self._actives_refreshed = True
        try:
            payload = getter()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        supported_assets = {asset for asset in payload if isinstance(asset, str)}
        return supported_assets or None

    @staticmethod
    def _default_client_factory(email: str, password: str) -> Any:
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError as exc:  # pragma: no cover - depends on optional dependency
            raise IQOptionAdapterError(
                "iqoptionapi is not installed. Run 'python -m pip install -e .[iqoption]' before using IQOptionDashboardService."
            ) from exc
        return IQ_Option(email, password)


def _is_supported_binary_forex_pair(asset: str) -> bool:
    if not _FOREX_BINARY_ASSET_PATTERN.fullmatch(asset):
        return False
    base_asset = asset.removesuffix("-OTC")
    base_currency = base_asset[:3]
    quote_currency = base_asset[3:]
    return base_currency in _FOREX_CURRENCY_CODES and quote_currency in _FOREX_CURRENCY_CODES


def _extract_payout(profits: dict[str, dict[str, float | None]], asset: str) -> float | None:
    payload = profits.get(asset, {})
    for key in ("binary", "turbo"):
        value = payload.get(key)
        if value is not None:
            return float(value)
    return None


def _is_otc_asset(asset: str) -> bool:
    return asset.endswith("-OTC")


def _pair_sort_key(pair: BinaryPairStatus) -> tuple[float, float, float, float, str]:
    payout_score = pair.payout or 0.0
    unsupported_rank = 1.0 if not pair.is_supported else 0.0
    return (unsupported_rank, -payout_score, -pair.win_rate_pct, -pair.trade_count, pair.asset)


def _recommendation_reason(pair: BinaryPairStatus) -> str:
    if pair.trade_count > 0 and pair.win_rate_pct >= 50.0 and (pair.payout or 0.0) >= 0.75:
        return "high payout + solid local win rate"
    if (pair.payout or 0.0) >= 0.8:
        return "high payout"
    if pair.trade_count > 0 and pair.win_rate_pct >= 50.0:
        return "strong local win rate"
    return "top available payout"


def _estimate_opportunity_score(*, metrics: MetricSnapshot, payout: float | None) -> float:
    prior_trades = 6.0
    normalized_payout = payout or 0.75
    payout_signal = min(max((normalized_payout - 0.7) / 0.2, 0.0), 1.0)
    prior_win_rate_pct = 48.0 + (payout_signal * 8.0)
    smoothed_win_rate_pct = (
        (metrics.wins + ((prior_win_rate_pct / 100.0) * prior_trades))
        / (metrics.total_trades + prior_trades)
    ) * 100.0
    profit_factor_bonus = min(max(metrics.profit_factor - 1.0, 0.0) * 6.0, 10.0)
    drawdown_penalty = min(metrics.max_drawdown_pct * 100.0 * 0.25, 8.0)
    streak_penalty = min(max(metrics.longest_loss_streak - 1, 0) * 1.5, 6.0)
    return round(min(max(smoothed_win_rate_pct + profit_factor_bonus - drawdown_penalty - streak_penalty, 5.0), 95.0), 1)


def _opportunity_band(opportunity_score_pct: float) -> str:
    if opportunity_score_pct >= 65.0:
        return "HIGH"
    if opportunity_score_pct >= 45.0:
        return "MEDIUM"
    return "LOW"


def _normalize_selected_assets(selected_assets: tuple[str, ...] | None, binary_pairs: tuple[BinaryPairStatus, ...]) -> tuple[str, ...]:
    open_assets = {pair.asset for pair in binary_pairs if pair.is_supported}
    requested = tuple(asset for asset in (selected_assets or ()) if asset in open_assets)
    if requested:
        return requested
    return tuple(sorted(open_assets))


def _format_session_label(session_label: SessionLabel | None) -> str:
    if session_label is None:
        return "UNKNOWN"
    return session_label.value.upper()


def _normalize_account_mode(account_mode: str) -> str:
    normalized_mode = account_mode.strip().upper()
    if normalized_mode not in {"PRACTICE", "REAL"}:
        raise IQOptionAdapterError("Account mode must be PRACTICE or REAL.")
    return normalized_mode