from pathlib import Path

from src.bot.desktop_dashboard import _chance_band_colors, _format_updated_at, load_dashboard_preferences, load_saved_username, save_dashboard_preferences, save_username_preference


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
            "batch_size": "1",
            "target_mode": "%",
        },
    )

    assert load_dashboard_preferences(prefs_path) == {
        "last_username": "user@example.com",
        "login_account_mode": "REAL",
        "stake_amount": "2.5",
        "timeframe_sec": "120",
        "batch_size": "1",
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