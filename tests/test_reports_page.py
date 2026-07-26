"""Tests for the ReportsPage period navigator, Save Report and History panel."""

import pytest
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import QMessageBox

import src.ui.pages.reports_pages.reports_page as reports_page_mod
from src.core.repositories import report_archive_repo, visit_repo
from src.ui.pages.reports_pages.reports_page import (
    ReportsPage, _month_bounds, _fmt,
)
from src.utils.settings_manager import SettingsManager

ADMIN = {"user_id": 1, "username": "admin", "roles": ["admin"]}


@pytest.fixture(autouse=True)
def _silence_boxes(monkeypatch):
    """Stubs modal QMessageBox calls (offscreen exec would access-violate)."""
    calls = {"info": [], "question": []}

    def _info(*args, **kwargs):
        calls["info"].append(args)
        return QMessageBox.Ok

    def _question(*args, **kwargs):
        calls["question"].append(args)
        return QMessageBox.Yes

    for name, fn in (("information", _info), ("warning", _info),
                     ("critical", _info), ("question", _question)):
        monkeypatch.setattr(reports_page_mod.QMessageBox, name, staticmethod(fn))
    return calls


def _make_page():
    # Skip the daily auto-checkpoint by default so unrelated tests see an empty
    # history (set the checkpoint marker to yesterday = already done).
    SettingsManager.set("last_report_checkpoint", _fmt(QDate.currentDate().addDays(-1)))
    page = ReportsPage()
    page.set_current_user(ADMIN)
    return page


def _seed_visit(entity_factory, day_str, owner="Owner A"):
    client_id = entity_factory["make_client"](owner)
    pet_id = entity_factory["make_pet"](client_id, name="Rex")
    visit_repo.add_visit(day_str, "checkup", False, "", pet_id=pet_id)


def _history_children(page):
    return list(page._history_child_items())


class TestCompactHeader:
    def test_calendar_lives_in_a_popup_not_the_pinned_header(self, fresh_db, qapp):
        page = _make_page()
        assert page.calendar.parentWidget() is page._calendar_popup
        assert page._calendar_popup.isVisible() is False
        assert page.header_widget.sizeHint().height() <= 180

    def test_custom_granularity_opens_the_calendar_popup(self, fresh_db, qapp):
        page = _make_page()
        page.show()
        page._on_granularity_changed("Custom")
        assert page._calendar_popup.isVisible() is True
        page._on_calendar_clicked(QDate.currentDate())
        assert page._custom_pending is not None
        assert page._calendar_popup.isVisible() is True
        page._on_calendar_clicked(QDate.currentDate().addDays(3))
        assert page._custom_range is not None
        assert page._calendar_popup.isVisible() is False


class TestCalendarIsANavigator:
    def test_clicking_a_day_shows_live_data_not_a_saved_report(
        self, fresh_db, qapp, entity_factory
    ):
        page = _make_page()
        past = QDate.currentDate().addDays(-5)
        past_str = _fmt(past)

        _seed_visit(entity_factory, past_str)
        page._selected_date = past
        page.refresh_data()
        page._save_current_report()               # snapshot for that window (1 visit)

        _seed_visit(entity_factory, past_str, owner="Owner B")  # live now has 2

        page._on_calendar_clicked(past)
        assert page._viewing_archive is None
        assert page.archive_banner_frame.isHidden() is True
        assert page.overview_tab.total_visits_value.text() == "2"

    def test_granularity_switch_leaves_an_open_snapshot(
        self, fresh_db, qapp, entity_factory
    ):
        page = _make_page()
        past = QDate.currentDate().addDays(-4)
        _seed_visit(entity_factory, _fmt(past))
        page._selected_date = past
        page.refresh_data()
        page._save_current_report()

        child = _history_children(page)[0]
        page._open_history_item(child)
        assert page._viewing_archive is not None

        page._on_granularity_changed("Week")
        assert page._viewing_archive is None
        assert page.archive_banner_frame.isHidden() is True


class TestSaveReport:
    def test_save_adds_a_history_entry(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        _seed_visit(entity_factory, QDate.currentDate().toString("yyyy-MM-dd"))
        page.refresh_data()
        assert _history_children(page) == []

        page._save_current_report()
        assert len(_history_children(page)) == 1
        assert page._viewing_archive is None
        assert report_archive_repo.list_archives()[0]["generated_by"] == "admin"

    def test_saving_creates_separate_entries(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        _seed_visit(entity_factory, QDate.currentDate().toString("yyyy-MM-dd"))
        page.refresh_data()
        page._save_current_report()
        page._save_current_report()
        assert len(_history_children(page)) == 2

    def test_audit_report_cannot_be_saved(self, fresh_db, qapp, _silence_boxes):
        page = _make_page()
        page.tabs.setCurrentIndex(4)  # Audit Log
        page._save_current_report()
        assert _history_children(page) == []
        assert _silence_boxes["info"], "expected an information message"


class TestOpenSavedReportAndBackToLive:
    def test_open_then_back_to_live(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        _seed_visit(entity_factory, today)
        page.refresh_data()
        page._save_current_report()

        _seed_visit(entity_factory, today, owner="Owner B")

        child = _history_children(page)[0]
        page._open_history_item(child)
        assert page._viewing_archive is not None
        assert page.archive_banner_frame.isHidden() is False
        assert page.overview_tab.total_visits_value.text() == "1"

        page.back_to_live_btn.click()
        assert page._viewing_archive is None
        assert page.overview_tab.total_visits_value.text() == "2"

    def test_open_switches_to_the_snapshots_tab(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        _seed_visit(entity_factory, today)
        page.tabs.setCurrentIndex(1)  # Financial Report
        page.refresh_data()
        page._save_current_report()

        page.tabs.setCurrentIndex(0)  # move away from Financial
        child = _history_children(page)[0]
        page._open_history_item(child)
        assert page.tabs.currentIndex() == 1


class TestHistorySearchAndDelete:
    def test_search_filters_the_tree(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        _seed_visit(entity_factory, QDate.currentDate().toString("yyyy-MM-dd"))
        page.refresh_data()
        page._save_current_report()          # Overview Analytics
        page.tabs.setCurrentIndex(1)         # Financial Report
        page.refresh_data()
        page._save_current_report()
        assert len(_history_children(page)) == 2

        page.history_search.setText("Financial")
        filtered = _history_children(page)
        assert len(filtered) == 1

        page.history_search.setText("")
        assert len(_history_children(page)) == 2

    def test_delete_removes_the_selected_snapshot(self, fresh_db, qapp, entity_factory):
        page = _make_page()
        _seed_visit(entity_factory, QDate.currentDate().toString("yyyy-MM-dd"))
        page.refresh_data()
        page._save_current_report()

        child = _history_children(page)[0]
        child.setSelected(True)
        page._delete_history_item()
        assert _history_children(page) == []


class TestPresetsNudgeGranularity:
    def test_preset_sets_a_custom_calendar_window(self, fresh_db, qapp):
        page = _make_page()
        page._apply_preset("this_month")
        start, end = page._granularity_range()
        expected_start, expected_end = _month_bounds(QDate.currentDate())
        assert start == _fmt(expected_start)
        assert end == _fmt(expected_end)
        assert page._granularity == "Custom"
        assert page.report_range_label.text() == f"{start} — {end}"

    def test_quarter_granularity_is_a_rolling_quarter(self, fresh_db, qapp):
        page = _make_page()
        page._selected_date = QDate(2026, 6, 15)
        page._on_granularity_changed("Quarter")
        start, end = page._granularity_range()
        assert end == "2026-06-15"
        assert start == "2026-03-15"

    def test_nudge_shifts_a_day_window(self, fresh_db, qapp):
        page = _make_page()
        page._selected_date = QDate(2026, 6, 15)
        page._nudge(-1)
        assert page._selected_date == QDate(2026, 6, 14)
        page._nudge(1)
        assert page._selected_date == QDate(2026, 6, 15)

    def test_nudge_shifts_a_preset_window_by_its_length(self, fresh_db, qapp):
        page = _make_page()
        page._apply_preset("this_month")
        start, end = page._granularity_range()
        page._nudge(-1)
        new_start, new_end = page._granularity_range()
        length = QDate.fromString(start, "yyyy-MM-dd").daysTo(
            QDate.fromString(end, "yyyy-MM-dd")) + 1
        shift = QDate.fromString(start, "yyyy-MM-dd").daysTo(
            QDate.fromString(new_start, "yyyy-MM-dd"))
        assert shift == -length


class TestDailyCheckpoint:
    def test_first_refresh_saves_a_snapshot_per_category(self, fresh_db, qapp):
        page = ReportsPage()
        page.set_current_user(ADMIN)
        page.refresh_data()

        children = _history_children(page)
        assert len(children) == 4  # overview, financial, client, supply (no audit)

        kinds = sorted(
            report_archive_repo.get_archive(
                child.data(0, Qt.UserRole))["report_kind"]
            for child in children
        )
        assert kinds == sorted(reports_page_mod.REPORT_KIND_KEYS[:-1])

        yesterday = _fmt(QDate.currentDate().addDays(-1))
        for child in children:
            row = report_archive_repo.get_archive(child.data(0, Qt.UserRole))
            assert row["period_type"] == "Day"
            assert (row["period_start"], row["period_end"]) == (yesterday, yesterday)
            assert row["generated_by"] == "admin"

    def test_checkpoint_runs_once_per_day(self, fresh_db, qapp):
        page = ReportsPage()
        page.set_current_user(ADMIN)
        page.refresh_data()
        assert len(_history_children(page)) == 4

        SettingsManager._cache = None  # drop the cached marker (simulate a new read)
        page.refresh_data()
        page.refresh_data()
        assert len(_history_children(page)) == 4

    def test_new_day_runs_the_checkpoint_again(self, fresh_db, qapp):
        page = ReportsPage()
        page.set_current_user(ADMIN)
        page.refresh_data()
        assert len(_history_children(page)) == 4

        # A different checkpoint target (yesterday changed) triggers a new set.
        SettingsManager.set("last_report_checkpoint", "2000-01-01")
        page.refresh_data()
        assert len(_history_children(page)) == 8

    def test_no_user_skips_the_checkpoint(self, fresh_db, qapp):
        SettingsManager.set("last_report_checkpoint", "")
        page = ReportsPage()
        page.set_current_user(None)
        page.refresh_data()
        assert _history_children(page) == []
        assert report_archive_repo.list_archives() == []
        assert SettingsManager.get("last_report_checkpoint") == ""


def test_report_workspace_stylesheet_classes_exist():
    from pathlib import Path

    qss = (Path(__file__).resolve().parent.parent / "assets" / "style.qss").read_text(encoding="utf-8")
    for cls in ("reports-history-panel", "reports-history-tree", "reports-history-search",
                "reports-preset-chip", "reports-nudge", "reports-history-action",
                "reports-period-trigger", "reports-calendar-popup"):
        assert f'[class="{cls}"]' in qss, cls


def test_report_workspace_i18n_keys_exist_in_english_and_arabic():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "assets" / "translations.json").read_text(encoding="utf-8")
    )
    for key in ("Save Report", "Report History", "This Month", "Year to Date", "Quarter",
                "Compare", "Difference", "Search reports…", "Open", "Select dates"):
        assert key in data["en"], key
        assert key in data["ar"], key
        assert data["ar"][key] != key, key
