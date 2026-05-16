"""Tests for src/core/status_resolver.py (the "Late" -> auto-cancel rule)."""

from datetime import datetime, timedelta

import pytest

from src.core import status_resolver
from src.config.constants import (
    AUTO_CANCEL_HOURS_MAX,
    AUTO_CANCEL_HOURS_MIN,
    DEFAULT_AUTO_CANCEL_HOURS,
)
from src.utils.settings_manager import SettingsManager


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Point SETTINGS_FILE at a temp file and reset the class cache."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(
        "src.utils.settings_manager.SETTINGS_FILE", settings_file
    )
    SettingsManager._cache = None
    yield settings_file
    SettingsManager._cache = None


def _stamp(delta):
    """A scheduled timestamp `delta` away from now, in the repo's SQL format."""
    return (datetime.now() + delta).strftime("%Y-%m-%d %H:%M:%S")


class TestAutoCancelHours:
    def test_default_is_the_historic_24_hours(self):
        assert status_resolver.auto_cancel_hours() == DEFAULT_AUTO_CANCEL_HOURS
        assert DEFAULT_AUTO_CANCEL_HOURS == 24

    def test_reads_the_setting(self):
        SettingsManager.set(status_resolver.SETTING_KEY, 2)
        assert status_resolver.auto_cancel_hours() == 2.0

    @pytest.mark.parametrize("value,expected", [
        (0, AUTO_CANCEL_HOURS_MIN),
        (-5, AUTO_CANCEL_HOURS_MIN),
        (0.5, AUTO_CANCEL_HOURS_MIN),
        (100000, AUTO_CANCEL_HOURS_MAX),
        (None, DEFAULT_AUTO_CANCEL_HOURS),
        ("abc", DEFAULT_AUTO_CANCEL_HOURS),
        (True, 1),          # bools are numeric, clamped into range
        (float("nan"), DEFAULT_AUTO_CANCEL_HOURS),
        (float("inf"), DEFAULT_AUTO_CANCEL_HOURS),
    ])
    def test_unusable_or_out_of_range_values_are_clamped(self, value, expected):
        SettingsManager.set(status_resolver.SETTING_KEY, value)
        assert status_resolver.auto_cancel_hours() == float(expected)

    def test_hand_edited_settings_file_is_survivable(self, _isolate_settings):
        _isolate_settings.write_text('{"auto_cancel_after_hours": "soon"}',
                                     encoding="utf-8")
        SettingsManager._cache = None
        assert status_resolver.auto_cancel_hours() == float(DEFAULT_AUTO_CANCEL_HOURS)


class TestResolveStatus:
    def test_explicit_statuses_are_never_overridden(self):
        long_past = _stamp(timedelta(days=-400))
        assert status_resolver.resolve_status("Completed", long_past) == "Completed"
        assert status_resolver.resolve_status("Canceled", long_past) == "Canceled"

    def test_future_schedule_is_pending(self):
        assert status_resolver.resolve_status(
            "Pending", _stamp(timedelta(minutes=30))
        ) == "Pending"

    def test_past_within_the_window_is_late(self):
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(hours=-1))) == "Late"

    def test_past_beyond_the_window_is_canceled(self):
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(hours=-48))) == "Canceled"

    def test_the_window_edge_counts_as_late(self):
        # A hair inside the window ...
        stamp = (datetime.now() - timedelta(hours=DEFAULT_AUTO_CANCEL_HOURS)
                 + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
        assert status_resolver.resolve_status("Pending", stamp) == "Late"
        # ... and a hair outside it.
        stamp = (datetime.now() - timedelta(hours=DEFAULT_AUTO_CANCEL_HOURS)
                 - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        assert status_resolver.resolve_status("Pending", stamp) == "Canceled"

    def test_seconds_precision_format_is_accepted(self):
        stamp = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        assert status_resolver.resolve_status("Pending", stamp) == "Late"

    def test_minute_precision_format_is_accepted(self):
        stamp = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        assert status_resolver.resolve_status("Pending", stamp) == "Late"

    @pytest.mark.parametrize("bad_date", [None, "", "  ", "not a date", 12345, object()])
    def test_unusable_dates_fall_back_to_the_stored_status(self, bad_date):
        assert status_resolver.resolve_status("Pending", bad_date) == "Pending"
        assert status_resolver.resolve_status("", bad_date) == "Pending"
        assert status_resolver.resolve_status(None, bad_date) == "Pending"

    def test_missing_date_keeps_an_explicit_status(self):
        assert status_resolver.resolve_status("Completed", "") == "Completed"


class TestConfigurableWindow:
    def test_shorter_window_cancels_sooner(self):
        SettingsManager.set(status_resolver.SETTING_KEY, 1)
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(hours=-2))) == "Canceled"
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(minutes=-30))) == "Late"

    def test_longer_window_keeps_records_late(self):
        SettingsManager.set(status_resolver.SETTING_KEY, 720)
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(hours=-48))) == "Late"
        assert status_resolver.resolve_status("Pending", _stamp(timedelta(days=-40))) == "Canceled"

    def test_change_applies_without_restarting(self):
        stamp = _stamp(timedelta(hours=-6))
        SettingsManager.set(status_resolver.SETTING_KEY, 3)
        assert status_resolver.resolve_status("Pending", stamp) == "Canceled"
        SettingsManager.set(status_resolver.SETTING_KEY, 24)
        assert status_resolver.resolve_status("Pending", stamp) == "Late"
