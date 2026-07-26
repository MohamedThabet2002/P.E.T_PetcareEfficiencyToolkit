"""Tests for src/core/repositories/appointment_repo.py"""

import pytest
from PyQt5.QtWidgets import QComboBox

from src.core.database import get_connection
from src.utils.i18n import tr
from PyQt5.QtSql import QSqlQuery


def _make_client(repos, name="Test Client"):
    return int(repos["client"].add_client(name, "0500000000"))


def _make_pet(repos, cid):
    return int(repos["pet"].add_pet("Rex", "Dog", "Labrador Retriever", "M", 24, 25.5, cid))


def _status_history_rows(db, appointment_id):
    q = QSqlQuery(db)
    q.prepare("SELECT status FROM appointment_status_history WHERE appointment_id = ? ORDER BY changed_at")
    q.addBindValue(appointment_id)
    rows = []
    if q.exec():
        while q.next():
            rows.append(q.value(0))
    return rows


def _make_followup(repos, pid, cid, status="Pending", followup_date="2030-06-10 09:00"):
    """Creates a follow-up on a fresh visit and returns (followup_id, visit_id)."""
    from src.core.repositories import followup_repo

    visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                             pet_id=pid, client_id=cid))
    fu_id = repos["followup"].add_followup(
        visit_id, followup_date,
        state_id=followup_repo.resolve_status_state_id(status), notes="check",
    )
    return int(fu_id), visit_id


def _followup_combo(dialog):
    """The status combo of the single follow-up row in the dialog."""
    rows = [r for r in range(dialog.table.rowCount())
            if dialog.table.cellWidget(r, 4) is not None
            and dialog.table.cellWidget(r, 4).property("row_kind") == "followup"]
    assert len(rows) == 1
    return dialog.table.cellWidget(rows[0], 4)


def _select_status(combo, status):
    target = combo.findText(status)
    assert target >= 0, f"status {status!r} is not offered by the combo"
    combo.setCurrentIndex(target)
    combo.activated[int].emit(target)


class TestUpdateAppointmentStatus:
    def test_updates_only_status_and_logs_history(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        assert repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                                    "Routine", cid, pid)
        appt = next(
            a for a in repos["appointment"].get_appointments()
            if a["pet_id"] == pid
        )
        appt_id = int(appt["appointment_id"])
        assert appt["status"] == "Pending"

        assert repos["appointment"].update_appointment_status(appt_id, "Completed", user_id=1) is True

        updated = next(
            a for a in repos["appointment"].get_appointments()
            if a["appointment_id"] == appt_id
        )
        assert updated["status"] == "Completed"
        assert _status_history_rows(fresh_db, appt_id) == ["Pending", "Completed"]

    def test_non_existent_appointment_is_noop(self, fresh_db, repos):
        # Mirrors existing update_appointment convention: a no-op UPDATE still
        # exec()s successfully on SQLite and logs nothing.
        assert repos["appointment"].update_appointment_status(999999, "Completed", user_id=1) is True
        assert _status_history_rows(fresh_db, 999999) == []

    def test_resolved_late_status_is_reflected(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment("2000-01-01 10:00", "Check-up", "Pending",
                                             "Routine", cid, pid)
        appt = next(
            a for a in repos["appointment"].get_appointments()
            if a["pet_id"] == pid
        )
        # Very old pending appointment resolves to "Canceled" for display.
        assert appt["status"] == "Canceled"


class TestAppointmentsDialog:
    def test_admin_sees_status_combos(self, fresh_db, repos, qapp):
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                             "Routine", cid, pid)

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            assert dialog.table.rowCount() == 1
            widget = dialog.table.cellWidget(0, 4)
            assert isinstance(widget, QComboBox)
            assert widget.currentText() == "Pending"
        finally:
            dialog.close()

    def test_staff_sees_plain_status_text(self, fresh_db, repos, qapp):
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                             "Routine", cid, pid)

        staff = {"user_id": 2, "username": "reception", "roles": ["staff"]}
        dialog = AppointmentsDialog(current_user=staff)
        try:
            assert dialog.table.rowCount() == 1
            assert dialog.table.cellWidget(0, 4) is None
        finally:
            dialog.close()

    def test_has_no_followup_column(self, fresh_db, repos, qapp):
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            assert dialog.table.columnCount() == 5
            headers = [dialog.table.horizontalHeaderItem(i).text()
                       for i in range(dialog.table.columnCount())]
            assert headers[-1] == "Status"
            assert "Follow-up" not in headers
        finally:
            dialog.close()

    def test_followup_row_status_updates_followups_table(self, fresh_db, repos, qapp):
        """Follow-up rows carry a followup_id; the combo must write to followups."""
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pid, client_id=cid))
        from src.core.repositories import lookup_repo

        state_ids = dict(lookup_repo.get_followup_statuses())
        fu_id = repos["followup"].add_followup(visit_id, "2030-06-10 09:00",
                                               state_id=state_ids["Pending"], notes="check")
        assert fu_id

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            rows = [r for r in range(dialog.table.rowCount())
                    if dialog.table.cellWidget(r, 4) is not None
                    and dialog.table.cellWidget(r, 4).property("row_kind") == "followup"]
            assert len(rows) == 1
            combo = dialog.table.cellWidget(rows[0], 4)
            assert combo is not None
            assert combo.currentText() == "Pending"
            target = combo.findText("Completed")
            assert target >= 0
            combo.setCurrentIndex(target)
            combo.activated[int].emit(target)
        finally:
            dialog.close()

        rows_after = repos["appointment"].get_appointments()
        fu_row = next(r for r in rows_after if r["row_type"] == "followup")
        assert fu_row["status"] == "Completed"
        # The appointment-status history table must not have been written to.
        assert _status_history_rows(fresh_db, int(fu_id)) == []

    def test_completed_followup_can_be_reopened(self, fresh_db, repos, qapp):
        """A completed follow-up must be switchable back to Pending."""
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog
        from src.core.repositories import followup_repo

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        _, visit_id = _make_followup(repos, pid, cid, status="Completed")

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            combo = _followup_combo(dialog)
            assert combo.currentText() == "Completed"
            _select_status(combo, "Pending")
        finally:
            dialog.close()

        fu_row = next(r for r in repos["appointment"].get_appointments()
                      if r["row_type"] == "followup")
        assert fu_row["status"] == "Pending"
        stored = followup_repo.get_followups_for_visit(visit_id)[0]
        assert stored["state_id"] == followup_repo.resolve_status_state_id("Pending")

    def test_completed_followup_can_be_canceled(self, fresh_db, repos, qapp):
        """Canceled must be a stored follow-up status, not only a derived one."""
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog
        from src.core.repositories import followup_repo

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        _, visit_id = _make_followup(repos, pid, cid, status="Completed")

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            _select_status(_followup_combo(dialog), "Canceled")
        finally:
            dialog.close()

        stored = followup_repo.get_followups_for_visit(visit_id)[0]
        assert stored["status"] == "Canceled"
        # Future date + explicit Canceled: the state is stored, not derived, so
        # the row no longer counts as an upcoming appointment.
        assert repos["appointment"].get_next_appointment_time() == tr("No appointments")
        fu_row = next(r for r in repos["appointment"].get_appointments()
                      if r["row_type"] == "followup")
        assert fu_row["status"] == "Canceled"

    def test_followup_combo_offers_every_status(self, fresh_db, repos, qapp):
        """Regression: a lookup missing Pending/Canceled must not freeze the combo."""
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog, STATUS_OPTIONS

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        _make_followup(repos, pid, cid, status="Completed")

        admin = {"user_id": 1, "username": "admin", "roles": ["admin"]}
        dialog = AppointmentsDialog(current_user=admin)
        try:
            combo = _followup_combo(dialog)
            offered = [combo.itemText(i) for i in range(combo.count())]
            for status in STATUS_OPTIONS:
                assert status in offered
        finally:
            dialog.close()


class TestResolveFollowupStatusStateId:
    def test_known_statuses_resolve_to_state_ids(self, fresh_db, repos):
        from src.core.repositories import followup_repo, lookup_repo

        states = dict(lookup_repo.get_followup_statuses())
        for value in ("Pending", "Completed", "Canceled"):
            assert value in states, f"{value} missing from the followup_status lookup"
            assert followup_repo.resolve_status_state_id(value) == states[value]

    def test_unknown_status_resolves_to_none(self, fresh_db, repos):
        from src.core.repositories import followup_repo

        assert followup_repo.resolve_status_state_id("Late") is None
        assert followup_repo.resolve_status_state_id("") is None
        assert followup_repo.resolve_status_state_id(None) is None

    def test_retired_statuses_are_refused_and_hidden(self, fresh_db, repos):
        """'Scheduled'/'Missed' are gone: never resolved, never offered."""
        from src.core.repositories import followup_repo, lookup_repo

        # Even where a legacy row still exists, it must not be offered ...
        insert = QSqlQuery(fresh_db)
        insert.exec("""
            INSERT INTO states_lookup (category_id, state_value)
            SELECT c.category_id, 'Missed' FROM categories_lookup c
            WHERE c.category_name = 'followup_status'
        """)
        offered = dict(lookup_repo.get_followup_statuses())
        assert set(offered) == {"Pending", "Completed", "Canceled"}
        # ... and a retired status must never resolve to a state id.
        assert followup_repo.resolve_status_state_id("Missed") is None
        assert followup_repo.resolve_status_state_id("Scheduled") is None

    def test_pending_stores_no_state_when_lookup_lacks_it(self, fresh_db, repos):
        """A database without a Pending row must still resolve Pending → NULL."""
        from src.core.repositories import followup_repo, lookup_repo

        cat = lookup_repo.get_states(category_name="followup_status")
        pending_id = dict((v, s) for s, v in cat).get("Pending")
        if pending_id is None:
            pytest.skip("followup_status lookup has no Pending state")
        drop = QSqlQuery(fresh_db)
        drop.prepare("DELETE FROM states_lookup WHERE state_id = ?")
        drop.addBindValue(pending_id)
        assert drop.exec()

        assert followup_repo.resolve_status_state_id("Pending") is None


class TestLateWindowSetting:
    """The auto-cancel window comes from settings, not a hardcoded 24 h."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, tmp_path, monkeypatch):
        from src.utils.settings_manager import SettingsManager

        monkeypatch.setattr(
            "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
        )
        SettingsManager._cache = None
        yield
        SettingsManager._cache = None

    @staticmethod
    def _ago(hours):
        from datetime import datetime, timedelta

        return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _row(repos, pid):
        return next(r for r in repos["appointment"].get_appointments()
                    if r["pet_id"] == pid)

    def test_default_window_keeps_a_recent_appointment_late(self, fresh_db, repos):
        from src.core import status_resolver

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment(self._ago(1), "Check-up", "Pending",
                                             "Routine", cid, pid)
        assert status_resolver.auto_cancel_hours() == 24
        assert self._row(repos, pid)["status"] == "Late"

    def test_shorter_window_cancels_the_same_row(self, fresh_db, repos):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment(self._ago(2), "Check-up", "Pending",
                                             "Routine", cid, pid)
        SettingsManager.set(status_resolver.SETTING_KEY, 1)
        assert self._row(repos, pid)["status"] == "Canceled"

    def test_longer_window_keeps_an_older_row_late(self, fresh_db, repos):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment(self._ago(6), "Check-up", "Pending",
                                             "Routine", cid, pid)
        SettingsManager.set(status_resolver.SETTING_KEY, 12)
        assert self._row(repos, pid)["status"] == "Late"

    def test_follow_ups_use_the_same_window(self, fresh_db, repos):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        _make_followup(repos, pid, cid, status="Pending", followup_date=self._ago(6))
        SettingsManager.set(status_resolver.SETTING_KEY, 12)
        row = next(r for r in repos["appointment"].get_appointments()
                   if r["row_type"] == "followup")
        assert row["status"] == "Late"

        SettingsManager.set(status_resolver.SETTING_KEY, 1)
        row = next(r for r in repos["appointment"].get_appointments()
                   if r["row_type"] == "followup")
        assert row["status"] == "Canceled"


class TestLateSearch:
    """A derived "Late" can never be matched by a SQL LIKE on status."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, tmp_path, monkeypatch):
        from src.utils.settings_manager import SettingsManager

        monkeypatch.setattr(
            "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
        )
        SettingsManager._cache = None
        yield
        SettingsManager._cache = None

    @staticmethod
    def _ago(hours):
        from datetime import datetime, timedelta

        return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    @pytest.fixture
    def seeded(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        repos["appointment"].add_appointment(self._ago(1), "Check-up", "Pending",
                                             "Routine", cid, pid)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Vaccination",
                                             "Pending", "", cid, pid)
        return cid, pid

    def test_status_search_returns_only_late_rows(self, fresh_db, repos, seeded):
        rows = repos["appointment"].get_appointments("late", "Status")
        assert rows, "a pending appointment inside the window must be found"
        assert {r["status"] for r in rows} == {"Late"}

    def test_the_probe_is_case_insensitive_and_trimmed(self, fresh_db, repos, seeded):
        assert len(repos["appointment"].get_appointments("LATE", "All")) == 1
        assert len(repos["appointment"].get_appointments(" Late ", "Status")) == 1

    def test_late_rows_are_found_for_follow_ups_too(self, fresh_db, repos, seeded):
        cid, pid = seeded
        _make_followup(repos, pid, cid, status="Pending", followup_date=self._ago(1))
        rows = repos["appointment"].get_appointments("late", "Status")
        assert any(r["row_type"] == "followup" and r["status"] == "Late"
                   for r in rows)

    def test_other_filter_fields_are_not_treated_as_a_status(
        self, fresh_db, repos, seeded
    ):
        assert repos["appointment"].get_appointments("late", "Date") == []
        assert repos["appointment"].get_appointments("late", "Service") == []

    def test_regular_searches_are_untouched(self, fresh_db, repos, seeded):
        rows = repos["appointment"].get_appointments("Vaccination", "Service")
        assert len(rows) == 1
        assert rows[0]["status"] == "Pending"


class TestNextAppointmentTimeIsStrictlyFuture:
    """The head of the schedule must roll on the moment its time arrives."""

    @staticmethod
    def _stamp(delta):
        from datetime import datetime

        return (datetime.now() + delta).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _future_appointment(repos, cid, pid, stamp, service="Check-up"):
        return repos["appointment"].add_appointment(
            stamp, service, "Pending", "", cid, pid)

    def test_an_appointment_is_not_next_anymore_once_its_time_is_here(
        self, fresh_db, repos
    ):
        from datetime import timedelta

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        self._future_appointment(repos, cid, pid, self._stamp(timedelta(0)))

        assert repos["appointment"].get_next_appointment_time() == tr("No appointments")

    def test_the_following_appointment_becomes_the_next_one(self, fresh_db, repos):
        from datetime import timedelta

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        expected = self._stamp(timedelta(days=1))
        self._future_appointment(repos, cid, pid, self._stamp(timedelta(0)))
        self._future_appointment(repos, cid, pid, expected, "Vaccination")

        assert repos["appointment"].get_next_appointment_time() == expected

    def test_a_future_follow_up_still_counts_as_next(self, fresh_db, repos):
        from datetime import timedelta

        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        expected = self._stamp(timedelta(days=1))
        _make_followup(repos, pid, cid, status="Pending", followup_date=expected)

        assert repos["appointment"].get_next_appointment_time() == expected

