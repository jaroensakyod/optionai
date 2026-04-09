from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig, load_config
from .env import load_dotenv_file
from .iqoption_adapter import IQOptionAdapter, IQOptionAdapterError
from .iqoption_market_data import IQOptionMarketDataProvider
from .journal_service import JournalService
from .models import InstrumentType
from .practice_harness import PracticeIntegrationHarness, PracticeSmokeTestResult
from .runtime_logging import RuntimeEventLogger
from .trade_journal import TradeJournalRepository


_PLACEHOLDER_VALUES = {
    "your-email@example.com",
    "your-password",
}


@dataclass(frozen=True, slots=True)
class SanityCheckItem:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class IQOptionSanityResult:
    status: str
    checks: tuple[SanityCheckItem, ...]
    balance: float | None = None
    candle_count: int = 0
    reason: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded IQ Option dependency and credential checks.")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv file path.")
    parser.add_argument("--asset", default="EURUSD")
    parser.add_argument("--instrument-type", choices=("binary", "digital"), default="digital")
    parser.add_argument("--timeframe-sec", type=int, default=60)
    parser.add_argument("--candle-limit", type=int, default=3)
    return parser


def run_sanity_check(
    *,
    config: AppConfig,
    repository: TradeJournalRepository,
    journal_service: JournalService,
    asset: str,
    instrument_type: InstrumentType,
    timeframe_sec: int,
    candle_limit: int,
    broker_client_factory: Callable[[str, str], Any] | None = None,
    market_client_factory: Callable[[str, str], Any] | None = None,
) -> IQOptionSanityResult:
    checks: list[SanityCheckItem] = []

    dependency_check = _check_dependency()
    checks.append(dependency_check)
    if dependency_check.status != "ok":
        return IQOptionSanityResult(status="failed", checks=tuple(checks), reason="missing_dependency")

    credential_check = _check_credentials()
    checks.append(credential_check)
    if credential_check.status != "ok":
        return IQOptionSanityResult(status="failed", checks=tuple(checks), reason="invalid_credentials")

    try:
        market_data_provider = IQOptionMarketDataProvider.from_environment(config, client_factory=market_client_factory)
        broker_adapter = IQOptionAdapter.from_environment(
            config,
            repository,
            journal_service,
            client_factory=broker_client_factory,
        )
        logger = RuntimeEventLogger(repository, config.runtime_log_dir, component="iqoption_sanity")
        harness = PracticeIntegrationHarness(repository, market_data_provider, broker_adapter, event_logger=logger)
        smoke_result = harness.run_smoke_test(
            asset=asset,
            instrument_type=instrument_type,
            timeframe_sec=timeframe_sec,
            candle_limit=candle_limit,
        )
    except IQOptionAdapterError as exc:
        checks.append(SanityCheckItem(name="connectivity", status="failed", detail=str(exc)))
        return IQOptionSanityResult(status="failed", checks=tuple(checks), reason="connect_failed")

    checks.append(_smoke_result_to_check(smoke_result))
    if smoke_result.status != "passed":
        return IQOptionSanityResult(
            status="failed",
            checks=tuple(checks),
            balance=smoke_result.balance,
            candle_count=smoke_result.candle_count,
            reason=smoke_result.reason or "smoke_test_failed",
        )

    return IQOptionSanityResult(
        status="passed",
        checks=tuple(checks),
        balance=smoke_result.balance,
        candle_count=smoke_result.candle_count,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_dotenv_file(Path(args.env_file))
    root_dir = Path(__file__).resolve().parents[2]
    config = load_config(root_dir)
    repository = TradeJournalRepository.from_paths(root_dir / "data" / "trades.db", root_dir / "sql" / "001_initial_schema.sql")
    journal_service = JournalService(repository)

    try:
        result = run_sanity_check(
            config=config,
            repository=repository,
            journal_service=journal_service,
            asset=args.asset,
            instrument_type=InstrumentType(args.instrument_type),
            timeframe_sec=args.timeframe_sec,
            candle_limit=args.candle_limit,
        )
    finally:
        repository.close()

    print(_format_result(result))
    return 0 if result.status == "passed" else 1


def _check_dependency() -> SanityCheckItem:
    try:
        importlib.import_module("iqoptionapi.stable_api")
    except ImportError:
        return SanityCheckItem(
            name="dependency",
            status="failed",
            detail="Install optional IQ Option dependencies with 'python -m pip install -e .[iqoption]'.",
        )
    return SanityCheckItem(name="dependency", status="ok", detail="iqoptionapi.stable_api import succeeded.")


def _check_credentials() -> SanityCheckItem:
    import os

    email = (os.getenv("IQOPTION_EMAIL") or "").strip()
    password = (os.getenv("IQOPTION_PASSWORD") or "").strip()
    if not email or not password:
        return SanityCheckItem(name="credentials", status="failed", detail="Set IQOPTION_EMAIL and IQOPTION_PASSWORD before using the IQ Option path.")
    if email in _PLACEHOLDER_VALUES or password in _PLACEHOLDER_VALUES:
        return SanityCheckItem(name="credentials", status="failed", detail="Replace placeholder IQ Option credentials in .env before running the IQ Option path.")
    return SanityCheckItem(name="credentials", status="ok", detail="Credential environment variables are present.")


def _smoke_result_to_check(smoke_result: PracticeSmokeTestResult) -> SanityCheckItem:
    if smoke_result.status == "passed":
        return SanityCheckItem(
            name="connectivity",
            status="ok",
            detail=f"Connected in PRACTICE mode, balance={smoke_result.balance}, candle_count={smoke_result.candle_count}.",
        )
    return SanityCheckItem(
        name="connectivity",
        status="failed",
        detail=f"Smoke test failed with reason={smoke_result.reason}.",
    )


def _format_result(result: IQOptionSanityResult) -> str:
    parts = [f"status={result.status}"]
    for check in result.checks:
        parts.append(f"{check.name}={check.status}")
    if result.balance is not None:
        parts.append(f"balance={result.balance}")
    parts.append(f"candle_count={result.candle_count}")
    if result.reason is not None:
        parts.append(f"reason={result.reason}")
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())