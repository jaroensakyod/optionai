from datetime import UTC, datetime
from pathlib import Path

from src.bot.config import load_config
from src.bot.iqoption_adapter import IQOptionAdapter, IQOptionCredentials
from src.bot.journal_service import JournalService
from src.bot.models import InstrumentType, SessionLabel, SignalEvent, StrategyVersion, TradeDirection, TradeResult
from src.bot.trade_journal import TradeJournalRepository


class FakeIQOptionClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.connected = False
        self.balance_mode = None
        self.binary_results: dict[int, float | None] = {}
        self.digital_results: dict[int, tuple[bool, float | None]] = {}

    def connect(self):
        self.connected = True
        return True, "success"

    def check_connect(self):
        return self.connected

    def change_balance(self, mode: str):
        self.balance_mode = mode

    def get_balance(self):
        return 10000.0

    def get_digital_payout(self, asset: str):
        return 82.0

    def get_all_profit(self):
        return {"GBPUSD": {"turbo": 0.75}}

    def buy_digital_spot_v2(self, asset: str, amount: float, action: str, duration: int):
        return True, 101

    def buy(self, amount: float, asset: str, action: str, duration: int):
        return True, 202

    def check_win_digital(self, broker_id: int):
        return self.digital_results.get(broker_id, (False, None))

    def check_win_v4(self, broker_id: int):
        return self.binary_results.get(broker_id)


def test_iqoption_adapter_submit_and_poll(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ACCOUNT_MODE", "PRACTICE")
    config = load_config(tmp_path)
    database_path = tmp_path / "trades.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    repository = TradeJournalRepository.from_paths(database_path, schema_path)
    journal_service = JournalService(repository)
    fake_client = FakeIQOptionClient("user@example.com", "secret")
    adapter = IQOptionAdapter(
        config=config,
        repository=repository,
        journal_service=journal_service,
        credentials=IQOptionCredentials(email="user@example.com", password="secret"),
        client_factory=lambda email, password: fake_client,
    )

    created_at = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
    strategy = StrategyVersion(
        strategy_version_id="v1",
        created_at_utc=created_at,
        strategy_name="demo-strategy",
        parameter_hash="abc123",
        parameters={"cooldown": 60},
        created_by="user",
        approval_status="approved",
    )
    repository.save_strategy_version(strategy)

    digital_signal = SignalEvent(
        signal_id="s-digital",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="EURUSD",
        instrument_type=InstrumentType.DIGITAL,
        timeframe_sec=60,
        direction=TradeDirection.CALL,
        intended_amount=1.0,
        intended_expiry_sec=60,
        entry_reason="breakout",
        session_label=SessionLabel.LONDON,
    )
    binary_signal = SignalEvent(
        signal_id="s-binary",
        created_at_utc=created_at,
        strategy_version_id="v1",
        asset="GBPUSD",
        instrument_type=InstrumentType.BINARY,
        timeframe_sec=60,
        direction=TradeDirection.PUT,
        intended_amount=2.0,
        intended_expiry_sec=60,
        entry_reason="reversal",
        session_label=SessionLabel.ASIA,
    )

    adapter.connect()

    open_digital = adapter.submit_order(signal_event=digital_signal, strategy_version_id="v1", tags={"case": "digital"})
    open_binary = adapter.submit_order(signal_event=binary_signal, strategy_version_id="v1", tags={"case": "binary"})

    fake_client.digital_results[101] = (True, 0.82)
    fake_client.binary_results[202] = -2.0

    closed_digital = adapter.poll_trade_result(open_digital.trade_id)
    closed_binary = adapter.poll_trade_result(open_binary.trade_id)

    assert fake_client.balance_mode == "PRACTICE"
    assert closed_digital is not None
    assert closed_binary is not None
    assert closed_digital.result == TradeResult.WIN
    assert closed_binary.result == TradeResult.LOSS
    assert closed_digital.profit_loss_abs == 0.82
    assert closed_binary.profit_loss_abs == -2.0
    assert len(repository.list_broker_orders(open_digital.trade_id)) == 1
    assert len(repository.list_broker_orders(open_binary.trade_id)) == 1

    repository.close()
