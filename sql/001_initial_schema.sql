PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_version_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    code_ref TEXT,
    parameter_hash TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    change_reason TEXT,
    approved_by TEXT,
    approval_status TEXT NOT NULL CHECK (approval_status IN ('draft', 'approved', 'rejected', 'rolled_back'))
);

CREATE TABLE IF NOT EXISTS signal_events (
    signal_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    strategy_version_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('binary', 'digital')),
    timeframe_sec INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('call', 'put')),
    signal_strength REAL,
    entry_reason TEXT NOT NULL,
    indicator_snapshot_json TEXT,
    market_snapshot_json TEXT,
    session_label TEXT NOT NULL CHECK (session_label IN ('asia', 'london', 'new_york', 'overlap', 'off_session')),
    is_filtered_out INTEGER NOT NULL DEFAULT 0 CHECK (is_filtered_out IN (0, 1)),
    filter_reason TEXT,
    intended_amount REAL NOT NULL,
    intended_expiry_sec INTEGER NOT NULL,
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
);

CREATE TABLE IF NOT EXISTS broker_orders (
    broker_order_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    signal_id TEXT,
    submitted_at_utc TEXT NOT NULL,
    broker_name TEXT NOT NULL,
    account_mode TEXT NOT NULL CHECK (account_mode IN ('PRACTICE', 'REAL', 'REPLAY')),
    broker_order_id TEXT,
    broker_position_id TEXT,
    asset TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('call', 'put')),
    amount REAL NOT NULL,
    expiry_sec INTEGER NOT NULL,
    payout_snapshot REAL,
    submission_status TEXT NOT NULL CHECK (submission_status IN ('pending', 'submitted', 'rejected', 'cancelled', 'error')),
    submission_error_code TEXT,
    submission_error_message TEXT,
    raw_request_json TEXT,
    raw_response_json TEXT,
    FOREIGN KEY (signal_id) REFERENCES signal_events(signal_id)
);

CREATE TABLE IF NOT EXISTS trade_journal (
    trade_id TEXT PRIMARY KEY,
    signal_id TEXT,
    strategy_version_id TEXT NOT NULL,
    opened_at_utc TEXT NOT NULL,
    closed_at_utc TEXT,
    asset TEXT NOT NULL,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN ('binary', 'digital')),
    timeframe_sec INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('call', 'put')),
    amount REAL NOT NULL,
    expiry_sec INTEGER NOT NULL,
    entry_price REAL,
    exit_price REAL,
    payout_snapshot REAL,
    result TEXT CHECK (result IN ('WIN', 'LOSS', 'BREAKEVEN', 'CANCELLED', 'REJECTED', 'ERROR', 'EXPIRED_UNKNOWN')),
    profit_loss_abs REAL,
    profit_loss_pct_risk REAL,
    fees_abs REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    account_mode TEXT NOT NULL CHECK (account_mode IN ('PRACTICE', 'REAL', 'REPLAY')),
    broker_order_id TEXT,
    broker_position_id TEXT,
    close_reason TEXT,
    error_code TEXT,
    error_message TEXT,
    is_replay INTEGER NOT NULL DEFAULT 0 CHECK (is_replay IN (0, 1)),
    journal_version INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signal_events(signal_id),
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
);

CREATE TABLE IF NOT EXISTS trade_context_tags (
    trade_id TEXT NOT NULL,
    tag_key TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    PRIMARY KEY (trade_id, tag_key, tag_value),
    FOREIGN KEY (trade_id) REFERENCES trade_journal(trade_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at_utc TEXT NOT NULL,
    account_mode TEXT NOT NULL CHECK (account_mode IN ('PRACTICE', 'REAL', 'REPLAY')),
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    open_risk REAL NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS optimization_proposals (
    proposal_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('ai', 'human')),
    based_on_start_utc TEXT NOT NULL,
    based_on_end_utc TEXT NOT NULL,
    based_on_trade_count INTEGER NOT NULL,
    current_strategy_version_id TEXT NOT NULL,
    proposed_parameters_json TEXT NOT NULL,
    proposal_summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence_score REAL,
    expected_metric_delta_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'validated', 'approved', 'rejected', 'rolled_back')),
    FOREIGN KEY (current_strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
);

CREATE TABLE IF NOT EXISTS proposal_validations (
    validation_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    validation_type TEXT NOT NULL CHECK (validation_type IN ('backtest', 'replay', 'practice_run')),
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    dataset_ref TEXT,
    trade_count INTEGER,
    win_rate REAL,
    profit_factor REAL,
    max_drawdown_pct REAL,
    net_pnl REAL,
    result_status TEXT NOT NULL CHECK (result_status IN ('pending', 'passed', 'failed')),
    notes TEXT,
    FOREIGN KEY (proposal_id) REFERENCES optimization_proposals(proposal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approval_audit (
    audit_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    acted_at_utc TEXT NOT NULL,
    reason TEXT,
    before_json TEXT,
    after_json TEXT
);

CREATE TABLE IF NOT EXISTS system_events (
    event_id TEXT PRIMARY KEY,
    occurred_at_utc TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    component TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_events_created_asset ON signal_events(created_at_utc, asset);
CREATE INDEX IF NOT EXISTS idx_signal_events_strategy ON signal_events(strategy_version_id, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_broker_orders_trade_id ON broker_orders(trade_id);
CREATE INDEX IF NOT EXISTS idx_broker_orders_broker_order_id ON broker_orders(broker_order_id);
CREATE INDEX IF NOT EXISTS idx_trade_journal_closed_at ON trade_journal(closed_at_utc);
CREATE INDEX IF NOT EXISTS idx_trade_journal_asset_result ON trade_journal(asset, result);
CREATE INDEX IF NOT EXISTS idx_trade_journal_strategy_mode ON trade_journal(strategy_version_id, account_mode, closed_at_utc);
CREATE INDEX IF NOT EXISTS idx_trade_context_tags_trade_id ON trade_context_tags(trade_id);
CREATE INDEX IF NOT EXISTS idx_system_events_occurred_at ON system_events(occurred_at_utc, severity);
