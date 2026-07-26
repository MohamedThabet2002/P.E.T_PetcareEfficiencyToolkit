"""Unit tests for RBAC permissions, roles, and pending changes workflow."""

import pytest
from PyQt5.QtSql import QSqlQuery

from src.core.permissions import can, get_role, get_roles, is_admin, is_doctor, is_staff
from src.core.repositories import pending_changes_repo
from src.core.repositories import appointment_repo
from src.ui.pages.database_pages.my_visits_page import MyVisitsPage
from src.ui.pages.database_pages.visits_page import VisitsPage
from src.ui.pages.reports_pages.reports_page import ReportsPage
from src.core.repositories import visit_repo


def test_rbac_roles_identification():
    admin_user = {"user_id": 1, "username": "admin", "roles": ["admin"]}
    doctor_user = {"user_id": 2, "username": "dr_smith", "roles": ["doctor"]}
    staff_user = {"user_id": 3, "username": "john_staff", "roles": ["staff"]}

    assert is_admin(admin_user) is True
    assert is_doctor(admin_user) is False

    assert is_doctor(doctor_user) is True
    assert is_admin(doctor_user) is False

    assert is_staff(staff_user) is True
    assert is_doctor(staff_user) is False


def test_rbac_permissions_can():
    admin = {"roles": ["admin"]}
    doctor = {"roles": ["doctor"]}
    staff = {"roles": ["staff"]}
    anonymous = None

    # Reports
    assert can(admin, "view_reports") is True
    assert can(doctor, "view_reports") is False
    assert can(staff, "view_reports") is False

    # Financials
    assert can(admin, "view_financials") is True
    assert can(doctor, "view_financials") is False

    # My Visits
    assert can(doctor, "view_visits") is True
    assert can(admin, "view_visits") is False

    # Write records
    assert can(admin, "edit_records") is True
    assert can(doctor, "edit_records") is False
    assert can(doctor, "request_change") is True
    assert can(staff, "request_change") is True

    # Anonymous
    assert can(anonymous, "view_dashboard") is False


def test_pending_changes_workflow(fresh_db):
    from src.core.repositories import audit_repo, user_repo
    user_id = user_repo.add_user("testdoctor", "password123", "doctor")
    assert user_id is not None

    table_name = "owners"
    record_id = 1
    operation = "UPDATE"
    payload = {"owner_name": "Updated Owner", "phone_number": "123456"}

    pending_id = pending_changes_repo.submit_change(user_id, table_name, record_id, operation, payload)
    assert pending_id is not None

    pending_items = pending_changes_repo.get_pending(status="pending")
    assert len(pending_items) >= 1
    item = next(p for p in pending_items if p["pending_id"] == pending_id)
    assert item["table_name"] == "owners"
    assert item["operation"] == "UPDATE"
    assert item["payload"]["owner_name"] == "Updated Owner"

    # Reject change
    res = pending_changes_repo.reject_change(pending_id, reviewer_id=1, notes="Rejected test")
    assert res is True

    rejected_items = pending_changes_repo.get_pending(status="rejected")
    assert any(p["pending_id"] == pending_id for p in rejected_items)
    changes = audit_repo.get_changes_for_record("pending_changes", pending_id)
    assert changes
    assert changes[0]["details"][0]["new_value"] == "rejected"


def test_pending_change_review_is_audited(fresh_db):
    from src.core.repositories import audit_repo, user_repo

    user_id = user_repo.add_user("auditdoctor", "password123", "doctor")
    reviewer_id = user_repo.add_user("auditadmin", "password123", "admin")
    pending_id = pending_changes_repo.submit_change(
        user_id, "owners", 1, "UPDATE", {"owner_name": "Audited"}
    )
    assert pending_id is not None

    assert pending_changes_repo.approve_change(pending_id, reviewer_id, "Looks good")
    changes = audit_repo.get_changes_for_record("pending_changes", pending_id)
    assert changes
    fields = {detail["field_name"]: detail for detail in changes[0]["details"]}
    assert fields["status"]["new_value"] == "approved"
    assert fields["review_notes"]["new_value"] == "Looks good"


def test_doctor_visit_page_does_not_fallback_to_all_visits(qapp, monkeypatch):
    page = MyVisitsPage()
    seen = []

    def fake_get_doctor_visits(doctor_id=None, text=None, filter_field="All"):
        seen.append(("doctor", doctor_id))
        return []

    def fake_get_visits(text=None, filter_field="All"):
        seen.append(("all", text, filter_field))
        return [{"visit_id": 999, "diagnosis": "fallback"}]

    monkeypatch.setattr(visit_repo, "get_doctor_visits", fake_get_doctor_visits)
    monkeypatch.setattr(visit_repo, "get_visits", fake_get_visits)

    page.set_current_user({"user_id": 42, "doctor_id": 42, "roles": ["doctor"]})
    assert seen == [("doctor", 42)]


def test_visits_page_uses_shared_tab_layout(qapp):
    page = VisitsPage()

    assert page.tabs.count() == 2
    assert page.table is page.tables["Visits"]
    assert page.quick_purchase_btn.text() == "Quick Purchase"
    assert page.tabs.tabText(1) == "Appointments"


def test_reports_categories_switch_visible_sections(qapp):
    page = ReportsPage()

    assert len(page.report_tabs) == 5

    # Overview: KPIs + trend charts only (every other section is owned elsewhere).
    page.tabs.setCurrentIndex(0)
    assert hasattr(page.overview_tab, "total_visits_value")
    assert hasattr(page.overview_tab, "low_stock_card_title") is False
    assert not hasattr(page.overview_tab, "visits_by_doctor_table")
    assert not hasattr(page.overview_tab, "revenue_by_category_table")
    assert not hasattr(page.overview_tab, "supply_usage_table")
    assert not hasattr(page.overview_tab, "diagnosis_table")
    assert not hasattr(page.overview_tab, "second_row_widget")
    assert not hasattr(page.overview_tab, "third_row_widget")

    # Financial: Revenue by Category only — no KPIs, no other tables.
    page.tabs.setCurrentIndex(1)
    assert page.financial_tab.second_row_widget.isHidden() is False
    assert hasattr(page.financial_tab, "revenue_by_category_table")
    assert not hasattr(page.financial_tab, "first_row_widget")
    assert not hasattr(page.financial_tab, "visits_by_doctor_table")
    assert not hasattr(page.financial_tab, "supply_usage_table")
    assert not hasattr(page.financial_tab, "diagnosis_table")

    # Patient: Visits by Doctor + Monthly Diagnoses + Clinical Activity only.
    page.tabs.setCurrentIndex(2)
    assert page.patient_tab.second_row_widget.isHidden() is False
    assert page.patient_tab.third_row_widget.isHidden() is False
    assert hasattr(page.patient_tab, "visits_by_doctor_table")
    assert hasattr(page.patient_tab, "diagnosis_table")
    assert not hasattr(page.patient_tab, "first_row_widget")
    assert not hasattr(page.patient_tab, "revenue_by_category_table")
    assert not hasattr(page.patient_tab, "supply_usage_table")
    assert not hasattr(page.patient_tab, "low_stock_value")
    assert page.clinical_table is not None

    # Supply: Supply Usage + low stock/expiring/top sellers + supply charts only.
    page.tabs.setCurrentIndex(3)
    assert page.supply_tab.second_row_widget.isHidden() is False
    assert page.supply_tab.third_row_widget.isHidden() is False
    assert hasattr(page.supply_tab, "supply_usage_table")
    assert hasattr(page.supply_tab, "low_stock_value")
    assert hasattr(page.supply_tab, "expiring_table")
    assert hasattr(page.supply_tab, "top_selling_table")
    assert not hasattr(page.supply_tab, "first_row_widget")
    assert not hasattr(page.supply_tab, "visits_by_doctor_table")
    assert not hasattr(page.supply_tab, "revenue_by_category_table")
    assert not hasattr(page.supply_tab, "diagnosis_table")

    # No page owns more than one copy of the shared analytics tables.
    for tab in page.report_tabs:
        for attr in ("visits_by_doctor_table", "revenue_by_category_table", "supply_usage_table"):
            owners = [t for t in page.report_tabs if hasattr(t, attr)]
            assert len(owners) <= 1, f"{attr} owned by {[type(t).__name__ for t in owners]}"

    # Audit shows the audit table only.
    page.tabs.setCurrentIndex(4)
    assert page.audit_tab.audit_table is not None
    assert not hasattr(page.audit_tab, "first_row_widget")
    assert not hasattr(page.audit_tab, "total_visits_value")
    assert not hasattr(page.audit_tab, "second_row_widget")


def test_reports_controls_follow_permissions(qapp):
    page = ReportsPage()
    page.set_current_user({"roles": ["staff"]})
    assert page.tabs.isEnabled() is False
    assert page.export_csv_btn.isEnabled() is False
    assert page.export_excel_btn.isEnabled() is False
    page.set_current_user({"roles": ["admin"]})
    assert page.tabs.isEnabled() is True


def test_patient_report_includes_doctor_followup_metrics(fresh_db, qapp, entity_factory):
    from PyQt5.QtSql import QSqlQuery
    from src.core.database import connection
    from src.core.repositories import analytics_repo

    connection_getter = lambda: fresh_db
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(connection, "get_connection", connection_getter)
    monkeypatch.setattr(analytics_repo, "get_connection", connection_getter)
    try:
        q = QSqlQuery(fresh_db)
        assert q.exec("INSERT INTO doctors (first_name, last_name) VALUES ('Ada', 'Lovelace')")
        doctor_id = q.lastInsertId()
        client_id = entity_factory["make_client"]("Report Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")
        assert q.exec(
            "INSERT INTO visits (pet_id, doctor_id, visit_date) VALUES (%s, %s, '2099-01-01')"
            % (pet_id, doctor_id)
        )
        visit_id = q.lastInsertId()
        assert q.exec(
            "INSERT INTO followups (visit_id, doctor_id, followup_date) VALUES (%s, %s, '2099-01-02')"
            % (visit_id, doctor_id)
        )
        page = ReportsPage()
        page.tabs.setCurrentIndex(2)
        assert page.clinical_table.rowCount() == 1
        assert page.clinical_table.item(0, 1).text() == "1"
        assert page.clinical_table.item(0, 2).text() == "1"
    finally:
        monkeypatch.undo()


def test_reports_audit_view_shows_empty_and_populated_states(fresh_db, qapp, monkeypatch):
    from src.core.repositories import audit_repo

    monkeypatch.setattr(audit_repo, "get_recent_changes_with_details", lambda limit=200: [])
    page = ReportsPage()
    page.tabs.setCurrentIndex(4)
    page._refresh_audit_report()
    assert page.audit_empty_label.isHidden() is False

    monkeypatch.setattr(audit_repo, "get_recent_changes_with_details", lambda limit=200: [{
        "change_header_id": 1,
        "username": "admin",
        "table_name": "visits",
        "record_id": 2,
        "changed_at": "2026-09-03 10:00",
        "details": [],
    }])
    page._refresh_audit_report()
    assert page.audit_empty_label.isHidden() is True
    assert page.audit_table.rowCount() == 1


def test_quick_purchase_dialog_uses_visitless_sales_flow(qapp, monkeypatch):
    from src.ui.pages.database_pages import visits_page

    captured = {}
    monkeypatch.setattr(
        visits_page.sales_repo,
        "create_sale_receipt_for_quick_purchase",
        lambda **kwargs: captured.update(kwargs) or 123,
    )
    dialog = visits_page.QuickPurchaseDialog()
    dialog.client_name_edit.setText("Quick Buyer")
    monkeypatch.setattr(dialog, "get_final_items", lambda: [{"item_name": "Gloves", "quantity": 1, "price": 5.0}])
    monkeypatch.setattr(visits_page.client_repo, "get_clients_by_name_exact", lambda name: [{"client_id": 8}])
    # The success box now constructs a QMessageBox with a Print button; stub it
    # out (a real modal exec_ access-violates pytest offscreen).
    monkeypatch.setattr(
        visits_page.QuickPurchaseDialog,
        "_show_success",
        lambda self, msg, receipt_id=None: None,
    )

    dialog.handle_accept()
    assert captured["owner_id"] == 8
    assert captured["items"][0]["item_name"] == "Gloves"


def test_dashboard_doctor_appointments_are_filtered(fresh_db, qapp, entity_factory):
    owner_id = entity_factory["make_client"]("Doctor Client")
    pet_id = entity_factory["make_pet"](owner_id, name="Patient 1")
    other_owner_id = entity_factory["make_client"]("Other Client")
    other_pet_id = entity_factory["make_pet"](other_owner_id, name="Patient 2")
    db = fresh_db

    q = QSqlQuery(db)
    q.prepare("INSERT INTO appointments (pet_id, doctor_id, appointment_date, status, notes) VALUES (?, ?, ?, ?, ?)")
    q.addBindValue(pet_id)
    q.addBindValue(7)
    q.addBindValue("2099-09-02 10:00:00")
    q.addBindValue("Pending")
    q.addBindValue("Doctor match")
    assert q.exec()

    q = QSqlQuery(db)
    q.prepare("INSERT INTO appointments (pet_id, doctor_id, appointment_date, status, notes) VALUES (?, ?, ?, ?, ?)")
    q.addBindValue(other_pet_id)
    q.addBindValue(99)
    q.addBindValue("2099-09-03 11:00:00")
    q.addBindValue("Pending")
    q.addBindValue("Other doctor")
    assert q.exec()

    results = appointment_repo.get_next_appointments(limit=10, as_table=True, doctor_id=7)
    assert len(results) == 1
    assert results[0][0] == "2099-09-02 10:00:00"
    assert results[0][2] == "Pending"
