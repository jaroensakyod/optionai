from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from os import getenv
import tkinter as tk
from tkinter import messagebox, ttk

from .config import load_config
from .dashboard_session import DashboardSessionController, SessionRunConfig, SessionStateSnapshot, SessionStopTargets
from .env import load_dotenv_file
from .iqoption_dashboard import DashboardSnapshot, IQOptionDashboardService, OpenPositionRow
from .signal_engine import DEFAULT_STRATEGY_ID, STRATEGY_ID_ORDER, format_strategy_ids, format_strategy_option_label, normalize_strategy_ids, strategy_family_label, strategy_profiles_from_ids
from .trade_journal import TradeJournalRepository


@dataclass(frozen=True, slots=True)
class MetricCard:
    label: str
    value: str


class DashboardWindow:
    _AUTO_REFRESH_MS = 60_000
    _MAX_SESSION_LOG_ROWS = 200
    _SESSION_UPDATE_DEBOUNCE_MS = 120

    def __init__(self, root: tk.Tk, service: IQOptionDashboardService, session_controller: DashboardSessionController, prefs_path: Path, dotenv_path: Path):
        self._root = root
        self._service = service
        self._session_controller = session_controller
        self._prefs_path = prefs_path
        self._dotenv_path = dotenv_path
        self._selected_assets: tuple[str, ...] = ()
        self._summary_labels: dict[str, tk.StringVar] = {}
        self._latest_snapshot: DashboardSnapshot | None = None
        self._session_log_rows: list[tuple[str, str, str, str]] = []
        self._pending_session_snapshots: list[SessionStateSnapshot] = []
        self._is_logged_in = False
        self._show_password = False
        self._password_entry: ttk.Entry | None = None
        self._password_toggle_button: ttk.Button | None = None
        self._market_card: tk.Frame | None = None
        self._market_title_label: tk.Label | None = None
        self._market_value_label: tk.Label | None = None
        self._button_grid_positions: dict[ttk.Button, tuple[int, int]] = {}
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_frame: tk.Frame | None = None
        self._scroll_window_id: int | None = None
        self._auto_refresh_job: str | None = None
        self._session_log_tree: ttk.Treeview | None = None
        self._session_update_job: str | None = None
        self._analytics_window: tk.Toplevel | None = None
        self._analytics_asset_tree: ttk.Treeview | None = None
        self._analytics_session_tree: ttk.Treeview | None = None
        self._pair_selector_window: tk.Toplevel | None = None
        self._pair_selector_frame: tk.Frame | None = None
        self._pair_checks: dict[str, tk.BooleanVar] = {}
        self._pair_rows: dict[str, tk.Frame] = {}
        self._pair_labels: dict[str, tk.Checkbutton] = {}
        self._pair_status_labels: dict[str, tk.Label] = {}
        self._pair_chance_labels: dict[str, tk.Label] = {}
        self._pair_render_cache: dict[str, tuple[object, ...]] = {}
        self._history_render_cache: dict[str, tuple[object, ...]] = {}
        self._open_positions_render_cache: dict[str, tuple[object, ...]] = {}
        self._analytics_asset_render_cache: dict[str, tuple[object, ...]] = {}
        self._analytics_session_render_cache: dict[str, tuple[object, ...]] = {}

        preferences = load_dashboard_preferences(self._prefs_path)
        saved_username = preferences.get("last_username", "")
        self._selected_assets = _load_selected_assets(preferences)

        self._status_var = tk.StringVar(value="Click Login to connect.")
        self._balance_var = tk.StringVar(value="-")
        self._mode_var = tk.StringVar(value="IQ OPTION PRACTICE")
        self._market_var = tk.StringVar(value="CLOSED")
        self._connection_var = tk.StringVar(value="DISCONNECTED")
        self._asset_var = tk.StringVar(value="-")
        self._recommended_var = tk.StringVar(value="-")
        self._session_var = tk.StringVar(value="STOPPED")
        self._checking_var = tk.StringVar(value="-")
        self._open_positions_var = tk.StringVar(value="0")
        self._block_reason_var = tk.StringVar(value="-")

        self._stake_var = tk.StringVar(value=preferences.get("stake_amount", "1.0"))
        self._timeframe_var = tk.StringVar(value=preferences.get("timeframe_sec", "60"))
        self._expiry_var = tk.StringVar(value=preferences.get("expiry_sec", "60"))
        self._poll_var = tk.StringVar(value=preferences.get("poll_sec", "5"))
        self._target_mode_var = tk.StringVar(value=preferences.get("target_mode", "$"))
        self._batch_size_var = tk.StringVar(value=preferences.get("batch_size", "2"))
        strategy_ids = _load_strategy_ids(preferences)
        self._strategy_vars = {
            strategy_id: tk.BooleanVar(value=strategy_id in strategy_ids)
            for strategy_id in STRATEGY_ID_ORDER
        }
        self._login_mode_var = tk.StringVar(value=preferences.get("login_account_mode", "PRACTICE"))
        self._profit_target_var = tk.StringVar(value=preferences.get("profit_target", "5"))
        self._loss_limit_var = tk.StringVar(value=preferences.get("loss_limit", "5"))
        self._username_var = tk.StringVar(value=saved_username or getenv("IQOPTION_EMAIL", ""))
        self._password_var = tk.StringVar(value=getenv("IQOPTION_PASSWORD", ""))

        self._root.title("OptionAI OTC Desktop")
        self._root.geometry("1720x980")
        self._root.configure(bg="#f3efe6")

        style = ttk.Style(self._root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=8)

        self._float_validator = (self._root.register(_is_valid_float_input), "%P")
        self._int_validator = (self._root.register(_is_valid_int_input), "%P")

        self._build_layout()
        self._login_mode_var.trace_add("write", self._on_login_mode_changed)
        self._sync_button_visibility()
        self._schedule_auto_refresh()

    def _build_layout(self) -> None:
        header = tk.Frame(self._root, bg="#123524", padx=20, pady=18)
        header.pack(fill=tk.X)
        tk.Label(header, text="Binary OTC Desktop", bg="#123524", fg="#f6f3eb", font=("Segoe UI Semibold", 24)).pack(anchor="w")

        content_shell = tk.Frame(self._root, bg="#f3efe6")
        content_shell.pack(fill=tk.BOTH, expand=True)

        self._scroll_canvas = tk.Canvas(content_shell, bg="#f3efe6", bd=0, highlightthickness=0)
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(content_shell, orient="vertical", command=self._scroll_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)

        self._scroll_frame = tk.Frame(self._scroll_canvas, bg="#f3efe6", padx=20, pady=16)
        self._scroll_window_id = self._scroll_canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        self._scroll_frame.bind("<Configure>", self._on_scroll_frame_configure)
        self._scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure)
        self._root.bind_all("<MouseWheel>", self._on_mousewheel)

        top = tk.Frame(self._scroll_frame, bg="#f3efe6")
        top.pack(fill=tk.X)
        cards_row = tk.Frame(top, bg="#f3efe6")
        cards_row.pack(fill=tk.X)

        self._build_info_card(cards_row, "Balance", self._balance_var, width=96).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Mode", self._mode_var, width=220).pack(side=tk.LEFT, padx=(0, 12))
        self._build_market_card(cards_row, width=110).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Connection", self._connection_var, width=170).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Run State", self._session_var, width=130).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Open Positions", self._open_positions_var, width=140).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Block Reason", self._block_reason_var, width=300).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(cards_row, "Checking", self._checking_var, width=300).pack(side=tk.LEFT, padx=(0, 12))

        controls_row = tk.Frame(top, bg="#f3efe6")
        controls_row.pack(fill=tk.X, pady=(12, 0))
        secondary_cards = tk.Frame(top, bg="#f3efe6")
        secondary_cards.pack(fill=tk.X, pady=(12, 0))
        self._build_info_card(secondary_cards, "Scanning Assets", self._asset_var, width=500).pack(side=tk.LEFT, padx=(0, 12))
        self._build_info_card(secondary_cards, "Scanning Count", self._recommended_var, width=220).pack(side=tk.LEFT, padx=(0, 12))

        button_bar = controls_row
        button_bar.grid_columnconfigure(0, minsize=98)
        button_bar.grid_columnconfigure(1, minsize=98)
        button_bar.grid_columnconfigure(2, minsize=98)
        button_bar.grid_columnconfigure(3, minsize=98)
        button_bar.grid_columnconfigure(4, minsize=98)
        button_bar.grid_columnconfigure(5, minsize=98)
        self._login_button = ttk.Button(button_bar, text="Login", command=self.login)
        self._logout_button = ttk.Button(button_bar, text="Logout", command=self.logout)
        self._refresh_button = ttk.Button(button_bar, text="Refresh", command=self.refresh)
        self._pair_selector_button = ttk.Button(button_bar, text="Pair Selector", command=self.open_pair_selector_window)
        self._analytics_button = ttk.Button(button_bar, text="Analytics", command=self.open_analytics_window)
        self._reconcile_button = ttk.Button(button_bar, text="Reconcile", command=self.reconcile_stale_trades)
        self._force_close_button = ttk.Button(button_bar, text="Force Close", command=self.force_close_open_trades)
        self._start_button = ttk.Button(button_bar, text="Start", command=self.start_session)
        self._stop_button = ttk.Button(button_bar, text="Stop", command=self.stop_session)

        self._place_action_buttons()

        body = tk.Frame(self._scroll_frame, bg="#f3efe6", pady=8)
        body.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(body, bg="#f3efe6", width=760)
        left.pack(side=tk.LEFT, fill=tk.BOTH)
        left.pack_propagate(False)
        right = tk.Frame(body, bg="#f3efe6")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(18, 0))

        self._build_controls_panel(left)
        self._build_metrics_panel(left)
        self._build_open_positions_panel(right)
        self._build_session_log_panel(right)
        self._build_history_panel(right)

        tk.Label(self._root, textvariable=self._status_var, anchor="w", bg="#e2dccf", fg="#243027", padx=16, pady=8, font=("Segoe UI", 10)).pack(fill=tk.X, side=tk.BOTTOM)

    def _on_scroll_frame_configure(self, _event: tk.Event) -> None:
        if self._scroll_canvas is not None:
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_scroll_canvas_configure(self, event: tk.Event) -> None:
        if self._scroll_canvas is None or self._scroll_frame is None or self._scroll_window_id is None:
            return
        self._scroll_canvas.itemconfigure(self._scroll_window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self._scroll_canvas is None:
            return
        self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_info_card(self, parent: tk.Widget, title: str, value_var: tk.StringVar, *, width: int | None = None) -> tk.Frame:
        card = tk.Frame(parent, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1, padx=16, pady=12)
        if width is not None:
            card.configure(width=width)
        tk.Label(card, text=title, bg="#f8f5ee", fg="#6b705c", font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(card, textvariable=value_var, bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 15), wraplength=max((width or 220) - 24, 72), justify=tk.LEFT).pack(anchor="w", pady=(6, 0), fill=tk.X)
        return card

    def _build_market_card(self, parent: tk.Widget, *, width: int | None = None) -> tk.Frame:
        card = tk.Frame(parent, bg="#eef6ef", highlightbackground="#c9ddcb", highlightthickness=1, padx=16, pady=12)
        if width is not None:
            card.configure(width=width)
        self._market_card = card
        self._market_title_label = tk.Label(card, text="Market", bg="#eef6ef", fg="#4f6a52", font=("Segoe UI", 10))
        self._market_title_label.pack(anchor="w")
        self._market_value_label = tk.Label(card, textvariable=self._market_var, bg="#eef6ef", fg="#1f6b35", font=("Segoe UI Semibold", 15))
        self._market_value_label.pack(anchor="w", pady=(6, 0))
        self._apply_market_status_style(self._market_var.get())
        return card

    def _build_controls_panel(self, parent: tk.Widget) -> None:
        shell = tk.Frame(parent, bg="#f3efe6")
        shell.pack(fill=tk.X)
        login_card = tk.Frame(shell, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1, padx=14, pady=12)
        login_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 9))
        trading_card = tk.Frame(shell, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1, padx=14, pady=12)
        trading_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(9, 0))

        tk.Label(login_card, text="Login", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        self._add_text_entry(login_card, "Username", self._username_var)
        self._add_text_entry(login_card, "Password", self._password_var, mask=True)
        self._add_combobox_entry(login_card, "Login mode", self._login_mode_var, values=("PRACTICE", "REAL"), width=12)

        tk.Label(trading_card, text="Trading Controls", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        controls_grid = tk.Frame(trading_card, bg="#f8f5ee")
        controls_grid.pack(fill=tk.X)
        left_column = tk.Frame(controls_grid, bg="#f8f5ee")
        left_column.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
        right_column = tk.Frame(controls_grid, bg="#f8f5ee")
        right_column.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._add_labeled_entry(left_column, "Stake / ไม้", self._stake_var)
        self._add_labeled_entry(left_column, "Timeframe sec", self._timeframe_var)
        self._add_labeled_entry(left_column, "Expiry sec", self._expiry_var)
        self._add_labeled_entry(right_column, "Poll sec", self._poll_var)
        self._add_strategy_selector(right_column)
        self._add_combobox_entry(right_column, "Target mode", self._target_mode_var, values=("$", "%"), width=8)
        self._add_combobox_entry(right_column, "Check per round", self._batch_size_var, values=("1", "2", "ALL"), width=8)
        self._add_labeled_entry(left_column, "Profit target", self._profit_target_var)
        self._add_labeled_entry(right_column, "Loss limit", self._loss_limit_var)

    def _add_strategy_selector(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, bg="#f8f5ee")
        row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(row, text="Strategies", bg="#f8f5ee", fg="#38423c", font=("Segoe UI", 10)).pack(anchor="w")
        selector_row = tk.Frame(row, bg="#f8f5ee")
        selector_row.pack(fill=tk.X, anchor="w", pady=(4, 0))
        current_family_label = ""
        for strategy_id in STRATEGY_ID_ORDER:
            family_label = strategy_family_label(strategy_id)
            if family_label != current_family_label:
                current_family_label = family_label
                tk.Label(
                    selector_row,
                    text=family_label,
                    bg="#f8f5ee",
                    fg="#6b705c",
                    font=("Segoe UI Semibold", 9),
                ).pack(anchor="w", pady=(4 if selector_row.winfo_children() else 0, 0))
            tk.Checkbutton(
                selector_row,
                text=format_strategy_option_label(strategy_id),
                variable=self._strategy_vars[strategy_id],
                bg="#f8f5ee",
                activebackground="#f8f5ee",
                command=self._handle_strategy_selection_change,
            ).pack(anchor="w", pady=(0, 2))

    def _add_labeled_entry(self, parent: tk.Widget, label: str, variable: tk.StringVar) -> None:
        row = tk.Frame(parent, bg="#f8f5ee")
        row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(row, text=label, bg="#f8f5ee", fg="#38423c", font=("Segoe UI", 10)).pack(anchor="w")
        validatecommand = self._float_validator
        if label in {"Timeframe sec", "Expiry sec"}:
            validatecommand = self._int_validator
        ttk.Entry(row, textvariable=variable, width=18, validate="key", validatecommand=validatecommand).pack(anchor="w", pady=(4, 0))

    def _add_text_entry(self, parent: tk.Widget, label: str, variable: tk.StringVar, *, mask: bool = False) -> None:
        row = tk.Frame(parent, bg="#f8f5ee")
        row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(row, text=label, bg="#f8f5ee", fg="#38423c", font=("Segoe UI", 10)).pack(anchor="w")
        entry_row = tk.Frame(row, bg="#f8f5ee")
        entry_row.pack(anchor="w", pady=(4, 0))
        entry = ttk.Entry(entry_row, textvariable=variable, width=24, show="*" if mask else "")
        entry.pack(side=tk.LEFT)
        if mask:
            self._password_entry = entry
            self._password_toggle_button = ttk.Button(entry_row, text="Show", command=self.toggle_password_visibility)
            self._password_toggle_button.pack(side=tk.LEFT, padx=(8, 0))

    def _add_combobox_entry(self, parent: tk.Widget, label: str, variable: tk.StringVar, *, values: tuple[str, ...], width: int) -> None:
        row = tk.Frame(parent, bg="#f8f5ee")
        row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(row, text=label, bg="#f8f5ee", fg="#38423c", font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=width).pack(anchor="w", pady=(4, 0))

    def _build_metrics_panel(self, parent: tk.Widget) -> None:
        frame = tk.Frame(parent, bg="#f3efe6")
        frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        summary_frame = tk.Frame(frame, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1, padx=14, pady=12)
        summary_frame.pack(fill=tk.BOTH, expand=True)
        header = tk.Frame(summary_frame, bg="#f8f5ee")
        header.pack(fill=tk.X)
        tk.Label(header, text="Binary Summary", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(side=tk.LEFT, anchor="w")
        self._clear_data_button = ttk.Button(header, text="Clear Data", command=self.clear_binary_history)
        self._clear_data_button.pack(side=tk.RIGHT)
        self._summary_grid = tk.Frame(summary_frame, bg="#f8f5ee")
        self._summary_grid.pack(fill=tk.X, pady=(10, 0))

    def _build_history_panel(self, parent: tk.Widget) -> None:
        frame = tk.Frame(parent, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        tk.Label(frame, text="Recent Binary Trades", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=14, pady=(14, 8))

        columns = ("asset", "opened", "strategy", "direction", "result", "amount", "pnl", "payout")
        self._history_tree = ttk.Treeview(frame, columns=columns, show="headings", height=16)
        for key, title, width, anchor in (("asset", "Pair", 90, "w"), ("opened", "Opened", 180, "w"), ("strategy", "Strategy", 240, "w"), ("direction", "Direction", 80, "center"), ("result", "Result", 90, "center"), ("amount", "Amount", 80, "e"), ("pnl", "P/L", 80, "e"), ("payout", "Payout", 80, "e")):
            self._history_tree.heading(key, text=title)
            self._history_tree.column(key, width=width, anchor=anchor)
        self._history_tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def _build_open_positions_panel(self, parent: tk.Widget) -> None:
        frame = tk.Frame(parent, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        tk.Label(frame, text="Open Positions", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=14, pady=(14, 8))

        columns = ("asset", "opened", "age", "expiry", "status", "broker")
        self._open_positions_tree = ttk.Treeview(frame, columns=columns, show="headings", height=6)
        for key, title, width, anchor in (("asset", "Pair", 120, "w"), ("opened", "Opened", 170, "w"), ("age", "Age", 90, "center"), ("expiry", "Expiry", 90, "center"), ("status", "Status", 100, "center"), ("broker", "Broker Ref", 180, "w")):
            self._open_positions_tree.heading(key, text=title)
            self._open_positions_tree.column(key, width=width, anchor=anchor)
        self._open_positions_tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def _build_session_log_panel(self, parent: tk.Widget) -> None:
        frame = tk.Frame(parent, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        tk.Label(frame, text="Session Log", bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=14, pady=(14, 8))
        columns = ("time", "asset", "status", "reason")
        self._session_log_tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for key, title, width, anchor in (("time", "Time", 90, "w"), ("asset", "Pair", 180, "w"), ("status", "Status", 90, "center"), ("reason", "Reason", 220, "w")):
            self._session_log_tree.heading(key, text=title)
            self._session_log_tree.column(key, width=width, anchor=anchor)
        self._session_log_tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def login(self) -> None:
        try:
            self._service.update_credentials(email=self._username_var.get(), password=self._password_var.get())
            self._service.update_account_mode(self._login_mode_var.get())
            self._service.connect()
            self.persist_preferences()
            self._is_logged_in = True
            self._connection_var.set("CONNECTED")
            self._status_var.set("Logged in. Refreshing dashboard...")
            self._append_session_log(asset="-", status="login", reason=f"mode={self._service.selected_account_mode}")
            self._sync_button_visibility()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Login Error", f"{type(exc).__name__}: {exc}")
            self._is_logged_in = False
            self._connection_var.set("DISCONNECTED")
            self._sync_button_visibility()
            self._status_var.set(f"Login failed: {type(exc).__name__}")

    def logout(self) -> None:
        self.stop_session()
        self._service.disconnect()
        self._is_logged_in = False
        self._connection_var.set("DISCONNECTED")
        self._session_var.set("STOPPED")
        self._append_session_log(asset="-", status="logout", reason="manual")
        self._sync_button_visibility()
        self._status_var.set("Logged out.")

    def refresh(self) -> None:
        self._status_var.set("Refreshing dashboard...")
        self._root.update_idletasks()
        try:
            snapshot = self._service.load_snapshot(selected_assets=self._selected_assets)
        except Exception as exc:
            messagebox.showerror("Dashboard Error", f"{type(exc).__name__}: {exc}")
            self._is_logged_in = False
            self._connection_var.set("DISCONNECTED")
            self._sync_button_visibility()
            self._status_var.set(f"{type(exc).__name__}: {exc}")
            return
        self._apply_snapshot(snapshot)
        self._is_logged_in = self._service.is_connected()
        self._connection_var.set("CONNECTED" if self._service.is_connected() else "DISCONNECTED")
        self._sync_button_visibility()
        self._status_var.set(f"Loaded {len(snapshot.binary_pairs)} OTC pairs. Market={snapshot.market_status}. Opportunity scores refresh every 60s.")

    def reconcile_stale_trades(self) -> None:
        if not self._is_logged_in:
            self._status_var.set("Login before reconciling stale trades.")
            return
        self._status_var.set("Reconciling stale trades...")
        self._root.update_idletasks()
        try:
            summary = self._session_controller.reconcile_stale_trades()
        except Exception as exc:
            messagebox.showerror("Reconcile Error", f"{type(exc).__name__}: {exc}")
            self._status_var.set(f"Reconcile failed: {type(exc).__name__}")
            return
        reason = (
            f"inspected={summary.inspected_open_trades} | broker={summary.reconciled_from_broker} | "
            f"closed={summary.closed_as_expired_unknown} | poll_failures={summary.poll_failures}"
        )
        self._append_session_log(asset="-", status="reconcile", reason=reason)
        self.refresh()
        self._status_var.set(f"Reconcile complete. {reason}")

    def force_close_open_trades(self) -> None:
        selected_trade_ids = tuple(self._open_positions_tree.selection()) if hasattr(self, "_open_positions_tree") else ()
        close_scope = "selected open positions" if selected_trade_ids else "all open positions"
        if not messagebox.askyesno("Force Close", f"Force close {close_scope} in the local journal?"):
            return
        self._status_var.set("Force closing open trades...")
        self._root.update_idletasks()
        try:
            summary = self._session_controller.force_close_open_trades(selected_trade_ids or None)
        except Exception as exc:
            messagebox.showerror("Force Close Error", f"{type(exc).__name__}: {exc}")
            self._status_var.set(f"Force close failed: {type(exc).__name__}")
            return
        reason = f"closed={summary.closed_count}"
        self._append_session_log(asset="-", status="force_close", reason=reason)
        self.refresh()
        self._status_var.set(f"Force close complete. {reason}")

    def clear_binary_history(self) -> None:
        if not self._is_logged_in:
            self._status_var.set("Login before clearing binary history.")
            return
        if self._session_controller.is_running:
            self._status_var.set("Stop the session before clearing binary history.")
            return
        if not messagebox.askyesno("Clear Data", "Clear Binary Summary and Recent Binary Trades history for the current account mode?"):
            return
        deleted_trades = self._service.clear_binary_history()
        self._status_var.set(f"Clearing binary history... removed {deleted_trades} trade(s).")
        self.refresh()
        self._append_session_log(asset="-", status="clear_data", reason=f"deleted_trades={deleted_trades}")
        self._status_var.set(f"Binary history cleared. Removed {deleted_trades} trade(s).")

    def start_session(self) -> None:
        if self._session_controller.is_running:
            self._status_var.set("Session is already running.")
            return
        if self._service.selected_account_mode != "PRACTICE":
            messagebox.showerror("Start Error", "Live execution is disabled in this repo. Switch Login mode back to PRACTICE before starting.")
            return
        try:
            run_config = SessionRunConfig(
                assets=self._read_run_assets(),
                batch_size=_parse_batch_size(self._batch_size_var.get()),
                strategy_ids=self._read_strategy_ids(require_selection=True),
                stake_amount=float(self._stake_var.get()),
                timeframe_sec=int(self._timeframe_var.get()),
                expiry_sec=int(self._expiry_var.get()),
                poll_interval_sec=float(self._poll_var.get()),
                stop_targets=SessionStopTargets(mode=self._target_mode_var.get(), profit_target=float(self._profit_target_var.get()), loss_limit=float(self._loss_limit_var.get())),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return
        try:
            session_id = self._session_controller.start(run_config, on_update=self._handle_session_update)
        except Exception as exc:
            messagebox.showerror("Start Error", f"{type(exc).__name__}: {exc}")
            return
        self.persist_preferences()
        self._session_var.set("RUNNING")
        self._sync_button_visibility()
        self._status_var.set(f"Started session {session_id}")

    def stop_session(self) -> None:
        if self._session_controller.is_running:
            self._session_controller.stop()
            self._session_var.set("STOPPING")
            self._sync_button_visibility()
            self._status_var.set("Stopping session...")

    def _handle_session_update(self, snapshot: SessionStateSnapshot) -> None:
        self._pending_session_snapshots.append(snapshot)
        if len(self._pending_session_snapshots) > 200:
            self._pending_session_snapshots = self._pending_session_snapshots[-200:]
        if self._session_update_job is None:
            self._session_update_job = self._root.after(self._SESSION_UPDATE_DEBOUNCE_MS, self._flush_session_update)

    def _flush_session_update(self) -> None:
        self._session_update_job = None
        pending_snapshots = self._pending_session_snapshots
        self._pending_session_snapshots = []
        for snapshot in pending_snapshots:
            self._apply_session_update(snapshot)

    def _apply_session_update(self, snapshot: SessionStateSnapshot) -> None:
        self._session_var.set(snapshot.status.upper())
        self._checking_var.set(snapshot.current_asset or "-")
        self._sync_button_visibility()
        current_asset = snapshot.current_asset or "-"
        self._append_session_log(asset=current_asset, status=snapshot.last_run_status or snapshot.status, reason=snapshot.last_reason or "-")
        self._status_var.set(f"Session {snapshot.status} | checking={current_asset} | assets={', '.join(snapshot.selected_assets)} | winrate={snapshot.win_rate_pct:.2f}% | progress={snapshot.progress_value:.2f}{snapshot.progress_label} | reason={snapshot.last_reason}")
        if snapshot.status in {"stopped", "error"}:
            self._checking_var.set("-")
            self.refresh()

    def _apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self._latest_snapshot = snapshot
        self._selected_assets = snapshot.selected_assets
        self._balance_var.set(f"{snapshot.balance:.2f}")
        self._mode_var.set(_format_account_mode(snapshot.account_mode))
        self._market_var.set(snapshot.market_status)
        self._apply_market_status_style(snapshot.market_status)
        self._asset_var.set(_join_assets(snapshot.selected_assets))
        self._recommended_var.set(f"{len(snapshot.selected_assets)} pair(s)")
        self._open_positions_var.set(str(len(snapshot.open_positions)))
        self._block_reason_var.set(snapshot.block_reason)
        self._render_metric_cards(self._summary_grid, self._summary_labels, _summary_cards(snapshot.summary_metrics))
        self._render_open_positions_rows(snapshot.open_positions)
        self._render_history_rows(snapshot.recent_trades)
        self._refresh_analytics_if_open()
        if self._pair_selector_window is not None and self._pair_selector_window.winfo_exists():
            self._render_pair_selector_rows()

    def _handle_strategy_selection_change(self) -> None:
        if any(variable.get() for variable in self._strategy_vars.values()):
            return
        self._strategy_vars[DEFAULT_STRATEGY_ID].set(True)

    def _on_login_mode_changed(self, *_args) -> None:
        self._sync_button_visibility()
        if not self._is_logged_in:
            return
        try:
            self._service.update_account_mode(self._login_mode_var.get())
            self.persist_preferences()
            self.refresh()
            self._append_session_log(asset="-", status="mode_switch", reason=f"mode={self._service.selected_account_mode}")
        except Exception as exc:
            messagebox.showerror("Mode Switch Error", f"{type(exc).__name__}: {exc}")
            self._status_var.set(f"Mode switch failed: {type(exc).__name__}")

    def _append_session_log(self, *, asset: str, status: str, reason: str) -> None:
        normalized_asset = asset or "-"
        normalized_status = status or "-"
        normalized_reason = reason or "-"
        row = (_format_clock(datetime.now()), normalized_asset, normalized_status.upper(), normalized_reason)
        if self._session_log_rows and self._session_log_rows[-1] == row:
            return
        self._session_log_rows.append(row)
        if len(self._session_log_rows) > self._MAX_SESSION_LOG_ROWS:
            self._session_log_rows = self._session_log_rows[-self._MAX_SESSION_LOG_ROWS :]
        if self._session_log_tree is None:
            return
        self._session_log_tree.insert("", 0, values=row)
        children = self._session_log_tree.get_children()
        if len(children) > self._MAX_SESSION_LOG_ROWS:
            for row_id in children[self._MAX_SESSION_LOG_ROWS :]:
                self._session_log_tree.delete(row_id)

    def _render_session_log_rows(self) -> None:
        if self._session_log_tree is None:
            return
        for row_id in self._session_log_tree.get_children():
            self._session_log_tree.delete(row_id)
        for entry in reversed(self._session_log_rows):
            self._session_log_tree.insert("", tk.END, values=entry)

    def _schedule_auto_refresh(self) -> None:
        self._auto_refresh_job = self._root.after(self._AUTO_REFRESH_MS, self._auto_refresh_tick)

    def _auto_refresh_tick(self) -> None:
        self._auto_refresh_job = None
        if self._is_logged_in and not self._session_controller.is_running:
            try:
                self.refresh()
            except Exception:
                pass
        elif self._is_logged_in and self._latest_snapshot is not None:
            try:
                snapshot = self._service.load_snapshot(selected_assets=self._selected_assets)
                self._apply_snapshot(snapshot)
                self._status_var.set(f"Background refresh complete. Opportunity scores refreshed at 60s interval. Market={snapshot.market_status}.")
            except Exception:
                pass
        self._schedule_auto_refresh()

    def _sync_button_visibility(self) -> None:
        self._set_button_visibility(self._login_button, visible=not self._is_logged_in)
        self._set_button_visibility(self._logout_button, visible=self._is_logged_in)
        is_running = self._session_controller.is_running or self._session_var.get() == "STOPPING"
        self._set_button_visibility(self._start_button, visible=not is_running)
        self._set_button_visibility(self._stop_button, visible=is_running)
        enabled_state = tk.NORMAL if self._is_logged_in else tk.DISABLED
        self._refresh_button.configure(state=enabled_state)
        self._pair_selector_button.configure(state=enabled_state)
        self._analytics_button.configure(state=enabled_state)
        if hasattr(self, "_clear_data_button"):
            self._clear_data_button.configure(state=tk.NORMAL if self._is_logged_in and not is_running else tk.DISABLED)
        self._reconcile_button.configure(state=tk.NORMAL if not is_running else tk.DISABLED)
        self._force_close_button.configure(state=tk.NORMAL if not is_running else tk.DISABLED)
        start_enabled = self._is_logged_in and self._login_mode_var.get().upper() == "PRACTICE"
        self._start_button.configure(state=tk.NORMAL if start_enabled else tk.DISABLED)

    def toggle_password_visibility(self) -> None:
        if self._password_entry is None or self._password_toggle_button is None:
            return
        self._show_password = not self._show_password
        self._password_entry.configure(show="" if self._show_password else "*")
        self._password_toggle_button.configure(text="Hide" if self._show_password else "Show")

    def persist_preferences(self) -> None:
        save_dashboard_preferences(
            self._prefs_path,
            {
                "last_username": self._username_var.get(),
                "stake_amount": self._stake_var.get(),
                "timeframe_sec": self._timeframe_var.get(),
                "expiry_sec": self._expiry_var.get(),
                "poll_sec": self._poll_var.get(),
                "strategy_ids": format_strategy_ids(self._read_strategy_ids(require_selection=True)),
                "strategy_profiles": ",".join(strategy_profiles_from_ids(self._read_strategy_ids(require_selection=True))),
                "selected_assets": ",".join(self._selected_assets),
                "target_mode": self._target_mode_var.get(),
                "batch_size": self._batch_size_var.get(),
                "login_account_mode": self._login_mode_var.get(),
                "profit_target": self._profit_target_var.get(),
                "loss_limit": self._loss_limit_var.get(),
            },
        )

    def _apply_market_status_style(self, market_status: str) -> None:
        if self._market_card is None or self._market_title_label is None or self._market_value_label is None:
            return
        background, border, title_fg, value_fg = _market_card_colors(market_status)
        self._market_card.configure(bg=background, highlightbackground=border)
        self._market_title_label.configure(bg=background, fg=title_fg)
        self._market_value_label.configure(bg=background, fg=value_fg)

    def _set_button_visibility(self, button: ttk.Button, *, visible: bool) -> None:
        if visible:
            position = self._button_grid_positions.get(button)
            if position is None:
                return
            row, column = position
            button.grid(row=row, column=column, padx=4, pady=4, sticky="ew")
            return
        if button.winfo_manager() == "grid":
            button.grid_remove()

    def _place_action_buttons(self) -> None:
        button_specs = (
            (self._login_button, 0, 0),
            (self._logout_button, 0, 0),
            (self._refresh_button, 0, 1),
            (self._pair_selector_button, 0, 2),
            (self._analytics_button, 0, 3),
            (self._reconcile_button, 0, 4),
            (self._force_close_button, 0, 5),
            (self._start_button, 1, 0),
            (self._stop_button, 1, 0),
        )
        for button, row, column in button_specs:
            self._button_grid_positions[button] = (row, column)
            button.grid(row=row, column=column, padx=4, pady=4, sticky="ew")

        if not self._is_logged_in:
            self._logout_button.grid_remove()
        else:
            self._login_button.grid_remove()

        is_running = self._session_controller.is_running or self._session_var.get() == "STOPPING"
        if is_running:
            self._start_button.grid_remove()
        else:
            self._stop_button.grid_remove()

    def _read_run_assets(self) -> tuple[str, ...]:
        if self._selected_assets:
            return self._selected_assets
        if self._latest_snapshot is None:
            snapshot = self._service.load_snapshot(selected_assets=None)
            self._apply_snapshot(snapshot)
        assets = tuple(
            pair.asset
            for pair in (self._latest_snapshot.binary_pairs if self._latest_snapshot is not None else ())
            if pair.is_supported and pair.is_open
        )
        if not assets:
            raise ValueError("No supported OTC pairs are currently available.")
        return assets

    def _read_strategy_ids(self, *, require_selection: bool) -> tuple[str, ...]:
        selected = tuple(strategy_id for strategy_id, variable in self._strategy_vars.items() if variable.get())
        if require_selection and not selected:
            raise ValueError("Select at least one strategy.")
        return normalize_strategy_ids(selected)

    def _render_metric_cards(self, parent: tk.Widget, state: dict[str, tk.StringVar], cards: list[MetricCard]) -> None:
        card_labels = [card.label for card in cards]
        if tuple(state) != tuple(card_labels):
            for child in parent.winfo_children():
                child.destroy()
            state.clear()
            for index, card in enumerate(cards):
                slot = tk.Frame(parent, bg="#efe9dc", padx=10, pady=10)
                slot.grid(row=index // 4, column=index % 4, sticky="nsew", padx=6, pady=6)
                value_var = tk.StringVar(value=card.value)
                state[card.label] = value_var
                tk.Label(slot, text=card.label, bg="#efe9dc", fg="#6b705c", font=("Segoe UI", 9)).pack(anchor="w")
                tk.Label(slot, textvariable=value_var, bg="#efe9dc", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(4, 0))
            return
        for card in cards:
            state[card.label].set(card.value)

    def _render_history(self, snapshot: DashboardSnapshot) -> None:
        self._render_history_rows(snapshot.recent_trades)

    def _render_history_rows(self, trades) -> None:
        rows = [
            (
                trade.trade_id,
                (
                    trade.asset,
                    trade.opened_at_utc.replace("T", " ")[:19],
                    trade.strategy_display,
                    trade.direction.upper(),
                    trade.result,
                    f"{trade.amount:.2f}",
                    _format_money(trade.profit_loss_abs),
                    _format_pct(trade.payout_snapshot),
                ),
            )
            for trade in trades
        ]
        self._sync_tree_rows(self._history_tree, rows, self._history_render_cache)

    def open_analytics_window(self) -> None:
        if self._analytics_window is not None and self._analytics_window.winfo_exists():
            self._analytics_window.lift()
            self._refresh_analytics_if_open()
            return

        self._analytics_window = tk.Toplevel(self._root)
        self._analytics_window.title("Strategy Analytics")
        self._analytics_window.geometry("1180x760")
        self._analytics_window.configure(bg="#f3efe6")
        self._analytics_window.protocol("WM_DELETE_WINDOW", self._close_analytics_window)

        shell = tk.Frame(self._analytics_window, bg="#f3efe6", padx=18, pady=18)
        shell.pack(fill=tk.BOTH, expand=True)
        self._analytics_asset_tree = self._build_analytics_panel(shell, title="Strategy by Pair")
        self._analytics_session_tree = self._build_analytics_panel(shell, title="Strategy by Session")
        self._refresh_analytics_if_open()

    def _build_analytics_panel(self, parent: tk.Widget, *, title: str) -> ttk.Treeview:
        frame = tk.Frame(parent, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 14))
        tk.Label(frame, text=title, bg="#f8f5ee", fg="#1f2a1f", font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=14, pady=(14, 8))
        columns = ("strategy", "group", "trades", "wins", "losses", "win_rate", "net_pnl", "profit_factor")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        for key, label, width, anchor in (("strategy", "Strategy", 240, "w"), ("group", "Group", 140, "w"), ("trades", "Trades", 70, "e"), ("wins", "Wins", 70, "e"), ("losses", "Losses", 70, "e"), ("win_rate", "Win Rate", 90, "e"), ("net_pnl", "Net P/L", 90, "e"), ("profit_factor", "Profit Factor", 100, "e")):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor=anchor)
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        return tree

    def _refresh_analytics_if_open(self) -> None:
        if self._analytics_window is None or not self._analytics_window.winfo_exists():
            return
        analytics = self._service.build_strategy_analytics_snapshot()
        if self._analytics_asset_tree is not None:
            self._render_analytics_rows(self._analytics_asset_tree, analytics.by_asset)
        if self._analytics_session_tree is not None:
            self._render_analytics_rows(self._analytics_session_tree, analytics.by_session)

    def _render_analytics_rows(self, tree: ttk.Treeview, rows) -> None:
        cache = self._analytics_asset_render_cache if tree is self._analytics_asset_tree else self._analytics_session_render_cache
        tree_rows = [
            (
                f"{row.strategy_display}|{row.group_value}",
                (
                    row.strategy_display,
                    row.group_value,
                    row.trades,
                    row.wins,
                    row.losses,
                    f"{row.win_rate_pct:.2f}%",
                    f"{row.net_pnl:.2f}",
                    f"{row.profit_factor:.2f}",
                ),
            )
            for row in rows
        ]
        self._sync_tree_rows(tree, tree_rows, cache)

    def _close_analytics_window(self) -> None:
        if self._analytics_window is not None and self._analytics_window.winfo_exists():
            self._analytics_window.destroy()
        self._analytics_window = None
        self._analytics_asset_tree = None
        self._analytics_session_tree = None
        self._analytics_asset_render_cache.clear()
        self._analytics_session_render_cache.clear()

    def open_pair_selector_window(self) -> None:
        if self._latest_snapshot is None:
            self.refresh()
        if self._pair_selector_window is not None and self._pair_selector_window.winfo_exists():
            self._pair_selector_window.lift()
            self._render_pair_selector_rows()
            return

        window = tk.Toplevel(self._root)
        window.title("Pair Selector")
        window.geometry("940x760")
        window.configure(bg="#f3efe6")
        window.protocol("WM_DELETE_WINDOW", self._close_pair_selector_window)
        self._pair_selector_window = window

        shell = tk.Frame(window, bg="#f3efe6", padx=18, pady=18)
        shell.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(shell, bg="#f3efe6")
        header.pack(fill=tk.X, pady=(0, 10))
        tk.Label(header, text="Select Pairs", bg="#f3efe6", fg="#1f2a1f", font=("Segoe UI Semibold", 16)).pack(side=tk.LEFT)
        ttk.Button(header, text="All", command=self.select_all_pairs).pack(side=tk.RIGHT)
        ttk.Button(header, text="Clear", command=self.clear_all_pairs).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(header, text="Apply", command=self.apply_pair_selection).pack(side=tk.RIGHT, padx=(0, 8))

        frame = tk.Frame(shell, bg="#f8f5ee", highlightbackground="#d8cfbf", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(frame, bg="#f8f5ee", bd=0, highlightthickness=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)

        self._pair_selector_frame = tk.Frame(canvas, bg="#f8f5ee")
        canvas.create_window((0, 0), window=self._pair_selector_frame, anchor="nw")
        self._pair_selector_frame.grid_columnconfigure(0, weight=1)
        self._pair_selector_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        self._render_pair_selector_rows()

    def _render_pair_selector_rows(self) -> None:
        snapshot = self._latest_snapshot
        if snapshot is None or self._pair_selector_frame is None:
            return
        rendered_assets: set[str] = set()
        for index, pair in enumerate(snapshot.binary_pairs):
            rendered_assets.add(pair.asset)
            is_selected = pair.asset in snapshot.selected_assets
            self._upsert_pair_row(pair=pair, is_selected=is_selected, row_index=index)

        for asset in tuple(self._pair_rows):
            if asset in rendered_assets:
                continue
            row = self._pair_rows.pop(asset)
            row.destroy()
            self._pair_checks.pop(asset, None)
            self._pair_labels.pop(asset, None)
            self._pair_status_labels.pop(asset, None)
            self._pair_chance_labels.pop(asset, None)
            self._pair_render_cache.pop(asset, None)

    def _upsert_pair_row(self, *, pair, is_selected: bool, row_index: int) -> None:
        if self._pair_selector_frame is None:
            return
        render_key = _pair_render_key(pair)
        row = self._pair_rows.get(pair.asset)
        var = self._pair_checks.get(pair.asset)
        if row is None or var is None:
            var = tk.BooleanVar(value=is_selected)
            self._pair_checks[pair.asset] = var
            row = tk.Frame(self._pair_selector_frame, bg="#f8f5ee")
            self._pair_rows[pair.asset] = row
            status_label = tk.Label(row, font=("Segoe UI Semibold", 9), padx=8, pady=2)
            status_label.pack(side=tk.LEFT, padx=(0, 8))
            chance_label = tk.Label(row, font=("Segoe UI Semibold", 9), padx=8, pady=2)
            chance_label.pack(side=tk.LEFT, padx=(0, 8))
            checkbox = tk.Checkbutton(
                row,
                variable=var,
                bg="#f8f5ee",
                activebackground="#f8f5ee",
                anchor="w",
                justify=tk.LEFT,
                wraplength=620,
            )
            checkbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._pair_status_labels[pair.asset] = status_label
            self._pair_chance_labels[pair.asset] = chance_label
            self._pair_labels[pair.asset] = checkbox
            self._pair_render_cache[pair.asset] = ()
            row.grid(column=0, sticky="ew", padx=12, pady=4)
        if var.get() != is_selected:
            var.set(is_selected)

        if self._pair_render_cache.get(pair.asset) != render_key:
            status_text, status_bg, status_fg = _status_colors(pair.is_open, pair.is_supported)
            chance_bg, chance_fg = _chance_band_colors(pair.opportunity_band)
            checkbox = self._pair_labels[pair.asset]
            checkbox_fg = "#1f2a1f" if pair.is_supported else "#7c7c7c"
            self._pair_status_labels[pair.asset].configure(text=status_text, bg=status_bg, fg=status_fg)
            self._pair_chance_labels[pair.asset].configure(text=f"{pair.opportunity_band} {pair.opportunity_score_pct:.1f}%", bg=chance_bg, fg=chance_fg)
            checkbox.configure(
                text=_pair_display_text(pair),
                fg=checkbox_fg,
                activeforeground=checkbox_fg,
                state=tk.NORMAL if pair.is_supported else tk.DISABLED,
            )
            self._pair_render_cache[pair.asset] = render_key

        row.grid_configure(row=row_index)

    def select_all_pairs(self) -> None:
        supported_assets = {
            pair.asset
            for pair in (self._latest_snapshot.binary_pairs if self._latest_snapshot is not None else ())
            if pair.is_supported and pair.is_open
        }
        for asset, var in self._pair_checks.items():
            var.set(asset in supported_assets)

    def clear_all_pairs(self) -> None:
        for var in self._pair_checks.values():
            var.set(False)

    def apply_pair_selection(self) -> None:
        self._selected_assets = tuple(asset for asset, var in self._pair_checks.items() if var.get())
        try:
            snapshot = self._service.load_snapshot(selected_assets=self._selected_assets)
        except Exception as exc:
            messagebox.showerror("Pair Selector Error", f"{type(exc).__name__}: {exc}")
            return
        self._apply_snapshot(snapshot)
        if self._selected_assets:
            self._status_var.set(f"Pair selector applied. {len(self._selected_assets)} pair(s) selected.")
        else:
            self._status_var.set("Pair selector cleared. Scanning all supported OTC pairs.")

    def _close_pair_selector_window(self) -> None:
        if self._pair_selector_window is not None and self._pair_selector_window.winfo_exists():
            self._pair_selector_window.destroy()
        self._pair_selector_window = None
        self._pair_selector_frame = None

    def _render_open_positions_rows(self, open_positions: tuple[OpenPositionRow, ...]) -> None:
        rows = [
            (
                position.trade_id,
                (
                    position.asset,
                    position.opened_at_utc.replace("T", " ")[:19],
                    _format_age(position.age_sec),
                    f"{position.expiry_sec}s",
                    position.status,
                    position.broker_reference or "-",
                ),
            )
            for position in open_positions
        ]
        self._sync_tree_rows(self._open_positions_tree, rows, self._open_positions_render_cache)

    def _sync_tree_rows(
        self,
        tree: ttk.Treeview,
        rows: list[tuple[str, tuple[object, ...]]],
        cache: dict[str, tuple[object, ...]],
    ) -> None:
        expected_ids = [row_id for row_id, _values in rows]
        expected_id_set = set(expected_ids)
        for row_id in tuple(tree.get_children()):
            if row_id in expected_id_set:
                continue
            tree.delete(row_id)
            cache.pop(row_id, None)

        for index, (row_id, values) in enumerate(rows):
            if tree.exists(row_id):
                if cache.get(row_id) != values:
                    tree.item(row_id, values=values)
            else:
                tree.insert("", tk.END, iid=row_id, values=values)
            if tree.index(row_id) != index:
                tree.move(row_id, "", index)
            cache[row_id] = values


def _summary_cards(metrics) -> list[MetricCard]:
    total = metrics.total_trades
    win_rate = 0.0 if total == 0 else (metrics.wins / total) * 100.0
    return [
        MetricCard("Trades", str(total)),
        MetricCard("Wins", str(metrics.wins)),
        MetricCard("Losses", str(metrics.losses)),
        MetricCard("Win Rate", f"{win_rate:.2f}%"),
        MetricCard("Net P/L", f"{metrics.net_pnl:.2f}"),
        MetricCard("Avg Win", f"{metrics.avg_win:.2f}"),
        MetricCard("Avg Loss", f"{metrics.avg_loss:.2f}"),
        MetricCard("Profit Factor", f"{metrics.profit_factor:.2f}"),
    ]


def _pair_display_text(pair) -> str:
    support_suffix = "" if pair.is_supported else " | unsupported for chart lookup"
    return (
        f"{pair.asset} | payout {_format_pct(pair.payout)} | winrate {pair.win_rate_pct:.2f}%\n"
        f"trades {pair.trade_count} | updated {_format_updated_at(pair.opportunity_updated_at_utc)}{support_suffix}"
    )


def _pair_render_key(pair) -> tuple[object, ...]:
    return (
        pair.asset,
        pair.payout,
        pair.is_open,
        pair.is_supported,
        pair.trade_count,
        pair.win_rate_pct,
        pair.opportunity_score_pct,
        pair.opportunity_band,
        pair.opportunity_updated_at_utc,
        pair.is_recommended,
        pair.recommendation_reason,
    )


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


def _format_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _join_assets(assets: tuple[str, ...]) -> str:
    if not assets:
        return "-"
    return ", ".join(assets[:3]) + (" ..." if len(assets) > 3 else "")


def _format_account_mode(account_mode: str) -> str:
    if account_mode.upper() == "PRACTICE":
        return "IQ OPTION PRACTICE"
    return f"IQ OPTION {account_mode.upper()}"


def _status_colors(is_open: bool, is_supported: bool) -> tuple[str, str, str]:
    if is_open and is_supported:
        return "OPEN", "#dff3e4", "#1f6b35"
    if is_open:
        return "OPEN but unsupported", "#ececec", "#666666"
    return "CLOSED", "#f8dddd", "#8a1f1f"


def _market_card_colors(market_status: str) -> tuple[str, str, str, str]:
    if market_status.upper() == "OPEN":
        return "#eef6ef", "#c9ddcb", "#4f6a52", "#1f6b35"
    return "#f9ecec", "#e4c7c7", "#7a5555", "#8a1f1f"


def _chance_band_colors(opportunity_band: str) -> tuple[str, str]:
    normalized_band = opportunity_band.upper()
    if normalized_band == "HIGH":
        return "#dff3e4", "#1f6b35"
    if normalized_band == "MEDIUM":
        return "#fff0cc", "#8a5a00"
    return "#f8dddd", "#8a1f1f"


def _format_updated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%H:%M:%S")


def _format_clock(value: datetime) -> str:
    return value.astimezone().strftime("%H:%M:%S")


def _parse_batch_size(value: str) -> int:
    normalized = value.strip().upper()
    if normalized == "ALL":
        return 0
    return int(normalized)


def _format_age(age_sec: int) -> str:
    minutes, seconds = divmod(max(age_sec, 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def load_dashboard_preferences(prefs_path: Path) -> dict[str, str]:
    if not prefs_path.exists():
        return {}
    try:
        payload = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value.strip() for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)}


def load_saved_username(prefs_path: Path) -> str:
    return load_dashboard_preferences(prefs_path).get("last_username", "")


def save_dashboard_preferences(prefs_path: Path, payload: dict[str, str]) -> None:
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_payload = {key: value.strip() for key, value in payload.items() if isinstance(key, str) and isinstance(value, str)}
    prefs_path.write_text(json.dumps(normalized_payload, sort_keys=True, indent=2), encoding="utf-8")


def save_username_preference(prefs_path: Path, username: str) -> None:
    save_dashboard_preferences(prefs_path, {"last_username": username})


def _load_strategy_ids(preferences: dict[str, str]) -> tuple[str, ...]:
    stored_ids = preferences.get("strategy_ids")
    if stored_ids:
        return normalize_strategy_ids(stored_ids)

    stored_profiles = preferences.get("strategy_profiles")
    if stored_profiles:
        return normalize_strategy_ids(stored_profiles)

    legacy_profile = preferences.get("strategy_profile")
    if legacy_profile:
        return normalize_strategy_ids((legacy_profile,))

    return (DEFAULT_STRATEGY_ID,)


def _load_selected_assets(preferences: dict[str, str]) -> tuple[str, ...]:
    stored_assets = preferences.get("selected_assets", "")
    return tuple(asset.strip() for asset in stored_assets.split(",") if asset.strip())


def _is_valid_float_input(value: str) -> bool:
    if value == "":
        return True
    if value.count(".") > 1:
        return False
    allowed = set("0123456789.")
    return all(character in allowed for character in value)


def _is_valid_int_input(value: str) -> bool:
    if value == "":
        return True
    return value.isdigit()


def main() -> int:
    load_dotenv_file(Path(".env"))
    root_dir = Path(__file__).resolve().parents[2]
    config = load_config(root_dir)
    repository = TradeJournalRepository.from_paths(root_dir / "data" / "trades.db", root_dir / "sql" / "001_initial_schema.sql")
    service = IQOptionDashboardService.from_environment(config, repository)
    session_controller = DashboardSessionController(config, root_dir)
    prefs_path = root_dir / "data" / "desktop_dashboard_prefs.json"
    dotenv_path = root_dir / ".env"

    root = tk.Tk()

    def on_close() -> None:
        window.persist_preferences()
        session_controller.stop()
        service.disconnect()
        repository.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    window = DashboardWindow(root, service, session_controller, prefs_path, dotenv_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())