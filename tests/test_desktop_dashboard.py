from pathlib import Path

from datetime import UTC, datetime

from src.bot.desktop_dashboard import _chance_band_colors, _format_age, _format_clock, _format_updated_at, _parse_batch_size, load_dashboard_preferences, load_saved_username, save_dashboard_preferences, save_username_preference


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
            "timeframe_sec": "120",
            "batch_size": "ALL",
            "target_mode": "%",
        },
    )

    assert load_dashboard_preferences(prefs_path) == {
        "last_username": "user@example.com",
        "login_account_mode": "REAL",
        "stake_amount": "2.5",
        "timeframe_sec": "120",
        "batch_size": "ALL",
        "target_mode": "%",
    }


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