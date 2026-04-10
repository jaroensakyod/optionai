from pathlib import Path

from datetime import UTC, datetime

from src.bot.desktop_dashboard import _chance_band_colors, _format_age, _format_clock, _format_updated_at, _load_selected_assets, _load_strategy_profiles, _pair_display_text, _pair_render_key, _parse_batch_size, load_dashboard_preferences, load_saved_username, save_dashboard_preferences, save_username_preference
from src.bot.iqoption_dashboard import BinaryPairStatus


def test_username_preference_round_trip(tmp_path: Path) -> None:
    prefs_path = tmp_path / "desktop_dashboard_prefs.json"

    save_username_preference(prefs_path, " user@example.com ")

    assert load_saved_username(prefs_path) == "user@example.com"


def test_dashboard_preferences_round_trip(tmp_path: Path) -> None:
    prefs_path = tmp_path / "desktop_dashboard_prefs.json"

    save_dashboard_preferences(
        prefs_path,
        {
            "last_username": "user@example.com",
            "login_account_mode": "REAL",
            "stake_amount": "2.5",
            "strategy_profiles": "LOW,HIGH",
            "timeframe_sec": "120",
            "batch_size": "ALL",
            "target_mode": "%",
        },
    )

    assert load_dashboard_preferences(prefs_path) == {
        "last_username": "user@example.com",
        "login_account_mode": "REAL",
        "stake_amount": "2.5",
        "strategy_profiles": "LOW,HIGH",
        "timeframe_sec": "120",
        "batch_size": "ALL",
        "target_mode": "%",
    }


def test_load_strategy_profiles_supports_legacy_and_csv_values() -> None:
    assert _load_strategy_profiles({"strategy_profiles": "LOW,HIGH"}) == ("LOW", "HIGH")
    assert _load_strategy_profiles({"strategy_profile": "MEDIUM"}) == ("MEDIUM",)


def test_load_selected_assets_parses_csv_value() -> None:
    assert _load_selected_assets({"selected_assets": "AUDCAD-OTC, AUDCHF-OTC"}) == ("AUDCAD-OTC", "AUDCHF-OTC")


def test_load_saved_username_returns_empty_on_missing_or_invalid_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", encoding="utf-8")

    assert load_saved_username(missing_path) == ""
    assert load_saved_username(invalid_path) == ""
    assert load_dashboard_preferences(missing_path) == {}
    assert load_dashboard_preferences(invalid_path) == {}


def test_chance_band_colors_cover_all_zones() -> None:
    assert _chance_band_colors("HIGH") == ("#dff3e4", "#1f6b35")
    assert _chance_band_colors("MEDIUM") == ("#fff0cc", "#8a5a00")
    assert _chance_band_colors("LOW") == ("#f8dddd", "#8a1f1f")


def test_format_updated_at_formats_iso_timestamp() -> None:
    assert _format_updated_at("2026-04-10T12:34:56+00:00")
    assert _format_updated_at("not-a-timestamp") == "not-a-timestamp"


def test_format_clock_formats_datetime() -> None:
    assert _format_clock(datetime(2026, 4, 10, 12, 34, 56, tzinfo=UTC))


def test_format_age_formats_seconds_minutes_and_hours() -> None:
    assert _format_age(45) == "45s"
    assert _format_age(125) == "2m 5s"
    assert _format_age(3660) == "1h 1m"


def test_parse_batch_size_supports_all_and_numeric_values() -> None:
    assert _parse_batch_size("ALL") == 0
    assert _parse_batch_size("2") == 2


def test_pair_display_text_includes_recommendation_suffix_only_when_present() -> None:
    pair = BinaryPairStatus(
        asset="AUDCAD-OTC",
        payout=0.84,
        is_open=True,
        is_supported=True,
        trade_count=3,
        win_rate_pct=66.67,
        net_pnl=1.25,
        opportunity_score_pct=58.4,
        opportunity_band="MEDIUM",
        opportunity_updated_at_utc="2026-04-10T12:34:56+00:00",
        is_recommended=True,
        recommendation_reason="high payout",
    )

    label = _pair_display_text(pair)

    assert "AUDCAD-OTC" in label
    assert "recommended:" not in label


def test_pair_render_key_changes_when_visual_pair_state_changes() -> None:
    base_pair = BinaryPairStatus(
        asset="AUDCAD-OTC",
        payout=0.84,
        is_open=True,
        is_supported=True,
        trade_count=3,
        win_rate_pct=66.67,
        net_pnl=1.25,
        opportunity_score_pct=58.4,
        opportunity_band="MEDIUM",
        opportunity_updated_at_utc="2026-04-10T12:34:56+00:00",
    )
    changed_pair = BinaryPairStatus(
        asset="AUDCAD-OTC",
        payout=0.84,
        is_open=False,
        is_supported=False,
        trade_count=3,
        win_rate_pct=66.67,
        net_pnl=1.25,
        opportunity_score_pct=58.4,
        opportunity_band="LOW",
        opportunity_updated_at_utc="2026-04-10T12:35:56+00:00",
    )

    assert _pair_render_key(base_pair) != _pair_render_key(changed_pair)


def test_pair_display_text_marks_unsupported_pairs() -> None:
    pair = BinaryPairStatus(
        asset="AUDCHF-OTC",
        payout=0.84,
        is_open=True,
        is_supported=False,
        trade_count=0,
        win_rate_pct=0.0,
        net_pnl=0.0,
        opportunity_score_pct=53.6,
        opportunity_band="MEDIUM",
        opportunity_updated_at_utc="2026-04-10T12:34:56+00:00",
    )

    assert "unsupported for chart lookup" in _pair_display_text(pair)