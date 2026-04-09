from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class RiskLimits:
    max_daily_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    max_stake: float = 0.0
    max_open_positions: int = 1


@dataclass(frozen=True)
class AppConfig:
    app_mode: str
    database_path: Path
    runtime_log_dir: Path
    backtest_log_dir: Path
    risk_limits: RiskLimits


def load_config(base_dir: Path | None = None) -> AppConfig:
    root = base_dir or Path(__file__).resolve().parents[2]
    app_mode = os.getenv("BOT_ACCOUNT_MODE", "PRACTICE").upper()
    if app_mode != "PRACTICE":
        raise ValueError("MVP startup is restricted to PRACTICE mode.")

    risk_limits = RiskLimits(
        max_daily_loss=float(os.getenv("BOT_MAX_DAILY_LOSS", "100.0")),
        max_drawdown_pct=float(os.getenv("BOT_MAX_DRAWDOWN_PCT", "10.0")),
        max_stake=float(os.getenv("BOT_MAX_STAKE", "10.0")),
        max_open_positions=int(os.getenv("BOT_MAX_OPEN_POSITIONS", "1")),
    )

    return AppConfig(
        app_mode=app_mode,
        database_path=root / "data" / "trades.db",
        runtime_log_dir=root / "logs" / "runtime",
        backtest_log_dir=root / "logs" / "backtests",
        risk_limits=risk_limits,
    )
