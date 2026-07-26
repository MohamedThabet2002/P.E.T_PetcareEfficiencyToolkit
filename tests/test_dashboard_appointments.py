"""Dashboard preview: overdue ("Late") appointments must stay visible.

A Late appointment/follow-up is still applicable until it passes the
auto-cancel window, so the dashboard's upcoming panel has to list it —
its SQL only ever returns future rows, hence the extra past query.
"""

from datetime import datetime, timedelta
import time

import pytest

from src.core.repositories import appointment_repo, client_repo, pet_repo, visit_repo, followup_repo
from src.ui.pages.dashboard_page import DashboardPage
from src.ui.themes.color_palettes import get_active_palette
from src.utils.settings_manager import SettingsManager


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
    )
    SettingsManager._cache = None
    yield
    SettingsManager._cache = None


ADMIN = {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _ago(hours):
    return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _soon(hours):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def page(qapp):
    widget = DashboardPage()
    widget.set_current_user(ADMIN)
    yield widget
    widget.deleteLater()


def _rows(page):
    table = page.upcoming_appointments_table
    return [
        tuple(table.item(r, c).text() for c in range(table.columnCount()))
        for r in range(table.rowCount())
    ]


class TestLateOnDashboard:
    def test_a_late_appointment_is_listed(self, page, fresh_db, repos):
        cid = int(client_repo.add_client("Late Owner", "0500000000"))
        pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
        appointment_repo.add_appointment(_ago(2), "Check-up", "Pending", "", cid, pid)
        appointment_repo.add_appointment(_soon(48), "Vaccination", "Pending", "",
                                         cid, pid)

        page._refresh_appointments()

        statuses = [row[4] for row in _rows(page)]
        assert "Late" in statuses
        # The upcoming slot still keeps the future appointment too.
        assert "Pending" in statuses

    def test_a_late_appointment_is_not_listed_twice(self, page, fresh_db, repos):
        cid = int(client_repo.add_client("Late Owner", "0500000000"))
        pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
        appointment_repo.add_appointment(_ago(2), "Check-up", "Pending", "", cid, pid)

        page._refresh_appointments()

        rows = _rows(page)
        assert rows, "the overdue appointment belongs on the panel"
        assert len(rows) == len(set(rows)), rows

    def test_a_late_appointment_is_painted_with_the_late_colour(
        self, page, fresh_db, repos
    ):
        cid = int(client_repo.add_client("Late Owner", "0500000000"))
        pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
        appointment_repo.add_appointment(_ago(2), "Check-up", "Pending", "", cid, pid)

        page._refresh_appointments()

        table = page.upcoming_appointments_table
        colour = None
        for r in range(table.rowCount()):
            if table.item(r, 4).text() == "Late":
                colour = table.item(r, 4).foreground().color().name()
                break
        assert colour is not None
        assert colour == get_active_palette().qcolor("state_late").name()

    def test_a_late_follow_up_is_listed(self, page, fresh_db, repos):
        cid = int(client_repo.add_client("Late Owner", "0500000000"))
        pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
        visit_id = int(visit_repo.add_visit(_ago(72), "Check-up", 0, "",
                                            pet_id=pid, client_id=cid))
        followup_repo.add_followup(
            visit_id, _ago(2),
            state_id=followup_repo.resolve_status_state_id("Pending"), notes="",
        )

        page._refresh_appointments()

        statuses = [row[4] for row in _rows(page)]
        assert "Late" in statuses

    def test_canceled_and_completed_rows_are_not_listed(
        self, page, fresh_db, repos
    ):
        cid = int(client_repo.add_client("Late Owner", "0500000000"))
        pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
        # Past far beyond the window -> resolves to Canceled.
        appointment_repo.add_appointment(_ago(500), "Check-up", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(_ago(6), "Grooming", "Completed", "",
                                         cid, pid)

        page._refresh_appointments()

        statuses = [row[4] for row in _rows(page)]
        assert "Late" not in statuses
        assert "Canceled" not in statuses


def _owner_pet(name="Preview Owner"):
    cid = int(client_repo.add_client(name, "0500000000"))
    pid = int(pet_repo.add_pet("Rex", "Dog", "Lab", "M", 12, 20.0, cid))
    return cid, pid


def _at(delta):
    """A stamp in the widget's minute precision (the repo/parser format)."""
    return (datetime.now() + delta).strftime("%Y-%m-%d %H:%M")


def _at_seconds(delta):
    """A stamp with seconds — the shape the spreadsheet importer stores."""
    return (datetime.now() + delta).strftime("%Y-%m-%d %H:%M:%S")


def _drain(qapp, predicate, tries=50):
    """Spins the event loop until `predicate()` holds (or the tries run out)."""
    for _ in range(tries):
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class TestFourRowPreview:
    """Today's Appointments: completed, closest Late, then two pending."""

    def test_the_table_holds_completed_late_and_two_pending_rows(
        self, page, fresh_db, repos
    ):
        cid, pid = _owner_pet()
        done = _ago(48)
        late_far = _ago(6)
        late_near = _ago(3)
        pend_a = _soon(2)
        pend_b = _soon(5)
        pend_c = _soon(9)
        appointment_repo.add_appointment(done, "Check-up", "Completed", "", cid, pid)
        appointment_repo.add_appointment(late_far, "Vaccination", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(late_near, "Grooming", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(pend_a, "Check-up", "Pending", "", cid, pid)
        appointment_repo.add_appointment(pend_b, "Vaccination", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(pend_c, "Grooming", "Pending", "", cid, pid)

        page._refresh_appointments()
        rows = _rows(page)

        assert [row[4] for row in rows] == ["Completed", "Late", "Pending", "Pending"]
        assert rows[0][0] == done
        # The Late row is the one nearest its auto-cancellation (earliest).
        assert rows[1][0] == late_far
        assert [rows[2][0], rows[3][0]] == [pend_a, pend_b]

    def test_an_empty_slot_is_skipped_rather_than_padded(
        self, page, fresh_db, repos
    ):
        cid, pid = _owner_pet()
        done = _ago(48)
        pend_a = _soon(2)
        pend_b = _soon(5)
        pend_c = _soon(9)
        appointment_repo.add_appointment(done, "Check-up", "Completed", "", cid, pid)
        appointment_repo.add_appointment(pend_a, "Check-up", "Pending", "", cid, pid)
        appointment_repo.add_appointment(pend_b, "Vaccination", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(pend_c, "Grooming", "Pending", "", cid, pid)

        page._refresh_appointments()
        rows = _rows(page)

        assert [row[4] for row in rows] == ["Completed", "Pending", "Pending"]
        assert rows[1][0] == pend_a

    def test_nothing_completed_leaves_two_pending_rows(self, page, fresh_db, repos):
        cid, pid = _owner_pet()
        appointment_repo.add_appointment(_soon(2), "Check-up", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(_soon(5), "Vaccination", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(_soon(9), "Grooming", "Pending", "", cid, pid)

        page._refresh_appointments()
        rows = _rows(page)

        assert [row[4] for row in rows] == ["Pending", "Pending"]
        # Rows are ordered soonest first.
        assert rows[0][0] < rows[1][0]


class TestNextClientCountdown:
    """The "Next Client Scheduled in" widget must roll on at 00:00:00."""

    @pytest.fixture
    def seeded(self, page, fresh_db, repos):
        cid, pid = _owner_pet()
        now_slot = _at(timedelta(0))
        later = _at(timedelta(days=1))
        appointment_repo.add_appointment(now_slot, "Check-up", "Pending", "",
                                         cid, pid)
        appointment_repo.add_appointment(later, "Vaccination", "Pending", "",
                                         cid, pid)
        page._refresh_next_appointment()
        return now_slot, later

    @staticmethod
    def _expire(page):
        """Pretend the countdown has just hit 00:00:00 on the current slot."""
        page._countdown_active = True
        page._next_appointment_dt = datetime.now()
        page._countdown_expired = False

    def test_hitting_zero_moves_on_to_the_next_client(self, page, seeded, qapp):
        _, later = seeded
        assert page._next_appointment_time_raw == later
        self._expire(page)
        refreshed = []
        page._refresh_appointments = lambda: refreshed.append(
            page._next_appointment_time_raw)

        page._update_countdown()
        assert _drain(qapp, lambda: refreshed), "the schedule never advanced"

        assert refreshed == [later]
        assert page.next_appointment_time_label.text() == later
        assert page._countdown_expired is False
        assert page.next_appointment_countdown_label.text() != "00:00:00"

    def test_hitting_zero_clears_the_widget_when_nothing_is_left(
        self, page, fresh_db, repos, qapp
    ):
        from src.utils.i18n import tr

        cid, pid = _owner_pet()
        appointment_repo.add_appointment(_at(timedelta(0)), "Check-up", "Pending",
                                         "", cid, pid)
        page._refresh_next_appointment()
        assert page._next_appointment_time_raw == tr("No appointments")
        self._expire(page)
        refreshed = []
        page._refresh_appointments = lambda: refreshed.append(
            page._next_appointment_time_raw)

        page._update_countdown()
        assert _drain(qapp, lambda: refreshed), "the schedule never advanced"

        assert refreshed == [tr("No appointments")]
        assert page._next_appointment_dt is None
        assert page._countdown_expired is False

    def test_a_running_countdown_does_not_refresh(self, page, seeded, qapp):
        _, later = seeded
        assert page._next_appointment_time_raw == later
        page._countdown_active = True
        refreshed = []
        page._refresh_appointments = lambda: refreshed.append(1)

        page._update_countdown()
        _drain(qapp, lambda: False, tries=10)

        assert refreshed == []
        assert page._countdown_expired is False
        assert page.next_appointment_countdown_label.text() != "00:00:00"

    def test_a_seconds_precision_stamp_still_counts_down(
        self, page, fresh_db, repos
    ):
        """Follow-ups stored with seconds (e.g. imported) must not blank the timer.

        `get_next_appointment_time` returns the raw stored string, so a stamp
        like ``2026-10-12 12:57:24`` has to parse — otherwise the widget shows
        the appointment time but never the live countdown.
        """
        cid, pid = _owner_pet()
        visit_id = int(visit_repo.add_visit(_ago(24), "Check-up", 0, "",
                                            pet_id=pid, client_id=cid))
        followup_repo.add_followup(
            visit_id, _at_seconds(timedelta(hours=3)),
            state_id=followup_repo.resolve_status_state_id("Pending"), notes="",
        )

        page._refresh_next_appointment()
        page._countdown_active = True
        page._update_countdown()

        assert page._next_appointment_dt is not None
        assert page.next_appointment_countdown_label.text() != ""

