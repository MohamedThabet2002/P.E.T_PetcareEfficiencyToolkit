"""Tests for src/ui/pages/database_pages/visits_page.py (Appointments tab)."""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox

from src.core.repositories import pending_changes_repo


@pytest.fixture
def page(fresh_db, repos, qapp, monkeypatch):
    """An admin VisitsPage with the modal paths stubbed out."""
    from src.ui.pages.database_pages.visits_page import VisitsPage

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    page = VisitsPage()
    page.set_current_user({"user_id": 1, "username": "admin", "roles": ["admin"]})
    page.refresh_appointments()
    return page


def _row_of(page, kind, record_id):
    table = page.tables["Appointments"]
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if (item.data(Qt.UserRole) or "appointment") == kind \
                and item.data(Qt.DisplayRole) == record_id:
            return row
    raise AssertionError(f"{kind} row {record_id} not found")


@pytest.fixture
def stub_editor(monkeypatch):
    """Replaces FollowupEditDialog.exec with a scripted, non-modal run.

    The callback receives the dialog, may mutate its fields, and returns the
    dialog's result. Returns the list of editors it was called with.
    """
    from src.ui.dialogs.followup_dialog import FollowupEditDialog

    opened = []

    def install(result=QDialog.Accepted, mutate=None):
        def fake_exec(self):
            opened.append(self)
            if mutate:
                mutate(self)
            return result

        monkeypatch.setattr(FollowupEditDialog, "exec", fake_exec, raising=False)
        return opened

    return install


class TestAppointmentsRowKind:
    def test_row_kind_is_stashed_on_the_id_cell(self, page, repos, entity_factory):
        """The Appointments tab mixes both kinds under one hidden id column."""
        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                             "Routine", client_id, pet_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(visit_id, "2030-06-10 09:00",
                                                   state_id=None, notes="check"))
        page.refresh_appointments()

        table = page.tables["Appointments"]
        assert table.item(_row_of(page, "appointment", 1), 0).data(Qt.UserRole) == "appointment"
        assert table.item(_row_of(page, "followup", fu_id), 0).data(Qt.UserRole) == "followup"
        assert page._appointment_row_record(_row_of(page, "followup", fu_id)) == ("followup", fu_id)


class TestEditFollowupRow:
    def test_followup_row_saves_to_the_followups_table(
        self, page, repos, entity_factory, stub_editor
    ):
        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(
            visit_id, "2030-06-10 09:00",
            state_id=repos["followup"].resolve_status_state_id("Completed"),
            notes="original",
        ))
        page.refresh_appointments()

        opened = stub_editor(mutate=lambda d: d.notes_edit.setPlainText("edited"))
        page.on_row_double_clicked("Appointments", _row_of(page, "followup", fu_id))

        assert len(opened) == 1
        assert opened[0].windowTitle() == "Edit Follow-up"
        assert opened[0].date_edit.dateTime().toString("yyyy-MM-dd HH:mm") == "2030-06-10 09:00"
        assert opened[0].status_combo.currentText() == "Completed"

        stored = repos["followup"].get_followup(fu_id)
        assert stored["notes"] == "edited"
        assert stored["followup_date"] == "2030-06-10 09:00"

    def test_followup_row_never_writes_to_the_appointments_table(
        self, page, repos, entity_factory, stub_editor
    ):
        """An appointment_id equal to the followup_id must stay untouched."""
        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        # First appointment -> appointment_id 1; first follow-up -> followup_id 1.
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                             "keep me", client_id, pet_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(visit_id, "2030-06-10 09:00",
                                                   state_id=None, notes="original"))
        assert fu_id == 1
        page.refresh_appointments()

        stub_editor(mutate=lambda d: d.notes_edit.setPlainText("edited"))
        page.on_row_double_clicked("Appointments", _row_of(page, "followup", fu_id))

        assert repos["followup"].get_followup(fu_id)["notes"] == "edited"
        row = next(a for a in repos["appointment"].get_appointments()
                   if a["row_type"] == "appointment" and a["appointment_id"] == 1)
        assert row["notes"] == "keep me"
        assert row["appointment_date"] == "2030-06-01 10:00"

    def test_cancelled_editor_leaves_the_record_alone(
        self, page, repos, entity_factory, stub_editor
    ):
        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(visit_id, "2030-06-10 09:00",
                                                   state_id=None, notes="original"))
        page.refresh_appointments()

        stub_editor(result=QDialog.Rejected,
                    mutate=lambda d: d.notes_edit.setPlainText("edited"))
        page.on_row_double_clicked("Appointments", _row_of(page, "followup", fu_id))

        assert repos["followup"].get_followup(fu_id)["notes"] == "original"


class TestEditAppointmentRow:
    def test_appointment_row_still_edits_appointments(
        self, page, repos, entity_factory, stub_editor
    ):
        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Pending",
                                             "Routine", client_id, pet_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(visit_id, "2030-06-10 09:00",
                                                   state_id=None, notes="fu"))
        page.refresh_appointments()

        # Same numeric id as the follow-up: the appointment row must still win.
        assert fu_id == 1
        seen = {}
        page._edit_scheduled_appointment = lambda app_id: seen.setdefault("app_id", app_id)
        page.on_row_double_clicked("Appointments", _row_of(page, "appointment", 1))

        assert seen == {"app_id": 1}
        assert repos["followup"].get_followup(fu_id)["notes"] == "fu"


class TestFollowupPendingChangeWorkflow:
    def test_staff_edit_is_submitted_and_then_applied(
        self, fresh_db, repos, entity_factory, qapp, monkeypatch
    ):
        from src.ui.pages.database_pages.visits_page import VisitsPage

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

        client_id = entity_factory["make_client"]()
        pet_id = entity_factory["make_pet"](client_id)
        visit_id = int(repos["visit"].add_visit("2030-06-01 10:00", "Check-up", 0, "",
                                                 pet_id=pet_id, client_id=client_id))
        fu_id = int(repos["followup"].add_followup(
            visit_id, "2030-06-10 09:00",
            state_id=repos["followup"].resolve_status_state_id("Completed"),
            notes="original",
        ))

        page = VisitsPage()
        # user_id 1 is the seeded admin row, so pending_changes' FK holds; the
        # bare role list still resolves to the staff permission set.
        staff = {"user_id": 1, "username": "reception", "roles": ["staff"]}
        page.set_current_user(staff)
        page.refresh_appointments()

        from src.ui.dialogs.followup_dialog import FollowupEditDialog

        def fake_exec(self):
            self.status_combo.setCurrentIndex(self.status_combo.findText("Canceled"))
            self.notes_edit.setPlainText("requested by staff")
            return QDialog.Accepted

        monkeypatch.setattr(FollowupEditDialog, "exec", fake_exec, raising=False)
        page.on_row_double_clicked("Appointments", _row_of(page, "followup", fu_id))

        # Nothing written yet — the change waits for an admin.
        assert repos["followup"].get_followup(fu_id)["notes"] == "original"
        pending = [p for p in pending_changes_repo.get_pending()
                   if p["table_name"] == "followups" and p["record_id"] == fu_id]
        assert len(pending) == 1
        assert pending[0]["payload"]["notes"] == "requested by staff"

        assert pending_changes_repo.approve_change(pending[0]["pending_id"], 1, "ok")
        assert pending_changes_repo.apply_pending_change(pending[0], reviewer_id=1) is True

        stored = repos["followup"].get_followup(fu_id)
        assert stored["notes"] == "requested by staff"
        assert stored["status"] == "Canceled"


class TestLanguageStableFilters:
    """The filter combo shows a translated label but must hand the repository a
    stable, untranslated column key (see BaseEntityPage.filter_key)."""

    def test_filter_key_survives_a_language_switch(self, page, monkeypatch):
        import src.modules.base_page as base_page

        combo = page.filters["Visits"]
        english_key = combo.currentData()
        assert english_key  # raw key stored as item data

        # Simulate a translation: every visible label changes, the key does not.
        monkeypatch.setattr(base_page, "tr", lambda key: f"<ar>{key}</ar>")
        page.retranslate_ui()

        assert combo.currentText() == f"<ar>{english_key}</ar>"
        assert page.filter_key("Visits") == english_key
        assert page.filter_key("Visits") != combo.currentText()

    def test_selected_filter_is_preserved_across_a_language_switch(self, page, monkeypatch):
        import src.modules.base_page as base_page

        combo = page.filters["Visits"]
        combo.setCurrentIndex(1)
        chosen_key = combo.currentData()

        monkeypatch.setattr(base_page, "tr", lambda key: f"<ar>{key}</ar>")
        page.retranslate_ui()

        assert combo.currentData() == chosen_key
        assert page.filter_key("Visits") == chosen_key


class TestVisitRowUsesRepoData:
    """Opening a visit must use the authoritative repo row, not table cells.

    The Consult column is rendered Yes/No in the active language and the flag is
    receipt-driven; re-parsing the displayed cell text is fragile (and was
    outright wrong where the query didn't even select `consult`).
    """

    def test_visits_page_row_derives_consult_from_the_receipt(self, page, repos,
                                                              entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        out = {}
        repos["visit"].add_visit("2030-05-01 10:00", "Checkup", 1, "note",
                                 pet_id=pid, client_id=cid, ids_out=out)
        vid_consult = int(out["visit_id"])
        vid_plain = int(repos["visit"].add_visit("2030-05-02 10:00", "Vaccine", 0, "",
                                                 pet_id=pid, client_id=cid))
        page.refresh_visits()

        row = page._visit_row_from_table("Visits", 0, str(vid_consult))
        assert row is not None
        assert int(row["consult"]) == 1
        assert row["diagnosis"] == "Checkup"
        assert int(page._visit_row_from_table("Visits", 0, str(vid_plain))["consult"]) == 0
        assert page._visit_row_from_table("Visits", 0, "not-an-id") is None

    def test_my_visits_details_use_repo_data(self, fresh_db, repos, entity_factory,
                                             qapp, monkeypatch):
        import src.ui.pages.database_pages.my_visits_page as mvp

        captured = {}

        class FakeDialog:
            def __init__(self, data, parent=None, current_user=None):
                captured.update(data)

            def exec_(self):
                return 0

        monkeypatch.setattr(mvp, "VisitInfoDialog", FakeDialog)

        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        did = repos["user"].get_doctor_id({"user_id": 1})
        out = {}
        repos["visit"].add_visit("2030-05-03 10:00", "Checkup", 1, "note",
                                 pet_id=pid, client_id=cid, ids_out=out,
                                 doctor_id=did)
        vid = int(out["visit_id"])

        page = mvp.MyVisitsPage()
        page.set_current_user({"user_id": 1, "username": "admin", "roles": ["admin"]})

        target = next(r for r in range(page.table.rowCount())
                      if page.table.item(r, 0).text() == str(vid))
        page._open_visit_details(target)

        assert int(captured["consult"]) == 1
        assert captured["diagnosis"] == "Checkup"
        assert captured["owner_name"]
        assert captured["pet_name"]
