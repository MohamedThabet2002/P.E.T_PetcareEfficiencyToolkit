"""
Tests for the audit logging of add / edit / delete / submit actions.

Every mutation performed by a logged-in user should produce an entry in the
change_header / change_detail tables so the Reports → Audit Log view shows who
did what. Pending-change submissions and admin-approved applies are also
recorded and attributed to the acting user.
"""

import src.core.repositories.client_repo as client_repo
import src.core.repositories.user_repo as user_repo
import src.core.repositories.audit_repo as audit_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.pending_changes_repo as pending_changes_repo


def _uid(repos, name, role="staff"):
    return int(user_repo.add_user(name, "pw12345", role))


def _recent(repos, table=None, user_id=None):
    rows = audit_repo.get_recent_changes(limit=500)
    if table:
        rows = [r for r in rows if r["table_name"] == table]
    if user_id is not None:
        rows = [r for r in rows if r["user_id"] == user_id]
    return rows


def test_record_action_writes_header_and_detail(fresh_db, repos):
    header_id = audit_repo.record_action(
        "UPDATE", "owners", 7,
        changes=[{"field_name": "owner_name", "old_value": "Old", "new_value": "New"}],
    )
    assert header_id is not None
    rows = _recent(repos, table="owners")
    assert any(r["record_id"] == 7 and r["change_header_id"] == header_id for r in rows)
    details = audit_repo.get_change_details(header_id)
    assert len(details) == 2
    assert details[0]["field_name"] == "action"
    assert details[0]["new_value"] == "UPDATE"
    assert details[1]["field_name"] == "owner_name"
    assert details[1]["new_value"] == "New"


def test_record_action_defaults_to_action_detail(fresh_db, repos):
    header_id = audit_repo.record_action("DELETE", "owners", 3, user_id=None)
    details = audit_repo.get_change_details(header_id)
    assert details[0]["field_name"] == "action"
    assert details[0]["new_value"] == "DELETE"


def test_owner_add_edit_delete_audited(fresh_db, repos):
    uid = _uid(repos, "dr_a")
    cid = client_repo.add_client("Lina", "0501", audit_user_id=uid)
    assert cid
    assert _recent(repos, "owners", uid)[0]["record_id"] == cid

    client_repo.update_client(cid, "Lina Smith", "0502", audit_user_id=uid)
    assert len(_recent(repos, "owners", uid)) == 2

    client_repo.delete_client(cid, audit_user_id=uid)
    assert len(_recent(repos, "owners", uid)) == 3
    assert _recent(repos, "owners", uid)[0]["record_id"] == cid


def test_pet_add_edit_delete_audited(fresh_db, repos):
    uid = _uid(repos, "dr_b")
    cid = client_repo.add_client("Bob", "0503")
    pid = pet_repo.add_pet("Rex", "Dog", "Lab", "M", 24, 25.5, cid, audit_user_id=uid)
    assert _recent(repos, "pets", uid) and _recent(repos, "pets", uid)[0]["record_id"] == pid

    pet_repo.update_pet_details(pid, 30, 30.0, audit_user_id=uid)
    pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid, audit_user_id=uid)
    pet_repo.delete_pet(pid, audit_user_id=uid)
    assert len(_recent(repos, "pets", uid)) == 4


def test_visit_add_edit_delete_audited(fresh_db, repos):
    uid = _uid(repos, "dr_c")
    cid = client_repo.add_client("Cara", "0504")
    pid = pet_repo.add_pet("Milo", "Cat", "", "F", 12, 4.0, cid)
    result = visit_repo.add_visit(
        "2026-01-05 10:00", "Checkup", 0, "routine", pet_id=pid, client_id=cid,
        audit_user_id=uid,
    )
    assert result
    assert _recent(repos, "visits", uid)[0]["record_id"] == int(result)

    visit_repo.update_visit(int(result), "Follow-up", "", "2026-01-05 10:00", 0, audit_user_id=uid)
    visit_repo.delete_visit(int(result), audit_user_id=uid)
    assert len(_recent(repos, "visits", uid)) == 3


def test_appointment_add_edit_delete_audited(fresh_db, repos):
    uid = _uid(repos, "dr_d")
    cid = client_repo.add_client("Dana", "0505")
    pid = pet_repo.add_pet("Nala", "Dog", "", "F", 10, 5.0, cid)
    ok = appointment_repo.add_appointment(
        "2026-02-01 09:00", "Consultation", "Pending", "", cid, pid, user_id=uid,
    )
    assert ok
    rows = _recent(repos, "appointments", uid)
    assert len(rows) == 1

    app_id = appointment_repo.get_appointments()[0]["appointment_id"]
    appointment_repo.update_appointment(
        app_id, "2026-02-01 10:00", "Vaccination", "Completed", "ok", cid, pid, user_id=uid,
    )
    appointment_repo.delete_appointment(app_id, audit_user_id=uid)
    assert len(_recent(repos, "appointments", uid)) == 3


def test_supply_add_edit_delete_audited(fresh_db, repos):
    uid = _uid(repos, "dr_e")
    sid, _ = supply_repo.add_supply(
        "Amoxicillin", "Medicine", "Antibiotics", quantity=10, audit_user_id=uid,
    )
    assert _recent(repos, "supplies", uid)[0]["record_id"] == sid

    supply_repo.update_supply(sid, "Amoxicillin", "Medicine", "Antibiotics",
                              "2026-01-01", "2027-01-01", 5.0, 10.0, 20, "Acme",
                              audit_user_id=uid)
    supply_repo.delete_supply(sid, audit_user_id=uid)
    assert len(_recent(repos, "supplies", uid)) == 3


def test_quick_purchase_receipt_audited(fresh_db, repos):
    uid = _uid(repos, "dr_f")
    sid, _ = supply_repo.add_supply(
        "Syringe Small", "Equipment", "Needles", quantity=10, sell_price=3.0,
    )
    assert sid
    cid = client_repo.add_client("Eve", "0506")
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        owner_id=cid,
        receipt_date_sql="2026-03-01 12:00",
        items=[{"item_name": "Syringe Small", "quantity": 2, "price": 3.0}],
        user_id=uid,
    )
    assert receipt_id
    rows = _recent(repos, "receipts", uid)
    assert rows and rows[0]["record_id"] == int(receipt_id)


def test_expense_and_receipt_delete_audited(fresh_db, repos):
    uid = _uid(repos, "staff_g")
    assert sales_repo.add_general_expense(
        "2026-03-02 09:00", "Utilities", "Electricity", 120.0, audit_user_id=uid,
    )
    rows = _recent(repos, "receipts", uid)
    assert rows and rows[0]["record_id"] > 0

    rid = rows[0]["record_id"]
    sales_repo.delete_receipt(rid, audit_user_id=uid)
    deletes = [r for r in _recent(repos, "receipts", uid) if r["record_id"] == rid]
    assert len(deletes) == 2


def test_pending_submit_audited(fresh_db, repos):
    staff = _uid(repos, "staff_h")
    admin = _uid(repos, "admin_i", "admin")
    cid = client_repo.add_client("Fay", "0507")
    pid = pending_changes_repo.submit_change(
        staff, "owners", cid, "UPDATE",
        {"owner_name": "Fay Two", "phone_number": "0508"},
    )
    assert pid
    rows = [r for r in _recent(repos, "owners", staff)]
    assert len(rows) == 1
    assert rows[0]["record_id"] == cid
    details = audit_repo.get_change_details(rows[0]["change_header_id"])
    field_map = {d["field_name"]: d["new_value"] for d in details}
    assert field_map.get("owner_name") == "Fay Two"


def test_approved_apply_audited_to_reviewer(fresh_db, repos):
    staff = _uid(repos, "staff_j")
    admin = _uid(repos, "admin_k", "admin")
    cid = client_repo.add_client("Gia", "0509")
    pid = pending_changes_repo.submit_change(
        staff, "owners", cid, "UPDATE", {"owner_name": "Gia New", "phone_number": "0510"},
    )
    assert pending_changes_repo.approve_change(pid, admin)
    row = {
        "table_name": "owners",
        "record_id": cid,
        "operation": "UPDATE",
        "payload": {"owner_name": "Gia New", "phone_number": "0510"},
    }
    assert pending_changes_repo.apply_pending_change(row, reviewer_id=admin)

    applied = [r for r in _recent(repos, "owners", admin)]
    assert len(applied) >= 1
    details = audit_repo.get_change_details(applied[0]["change_header_id"])
    assert any(d.get("field_name") not in ("", "action") for d in details)

    # The submitted change is still attributed to the staff member.
    assert len(_recent(repos, "owners", staff)) == 1


def test_audit_username_is_resolved(fresh_db, repos):
    uid = _uid(repos, "logger_user")
    client_repo.add_client("Hana", "0511", audit_user_id=uid)
    rows = [r for r in _recent(repos, "owners", uid)]
    assert rows and rows[0]["username"] == "logger_user"


def test_recent_changes_with_details_groups_fields(fresh_db, repos):
    uid = _uid(repos, "details_user")
    cid = client_repo.add_client("Iris", "0512", audit_user_id=uid)
    client_repo.update_client(
        cid, "Iris New", "0513", audit_user_id=uid,
    )
    rows = [
        r for r in audit_repo.get_recent_changes_with_details(limit=200)
        if r["table_name"] == "owners" and r["record_id"] == cid
    ]
    assert rows
    # The update entry must carry the field-level owner_name diff.
    assert any(
        {d["field_name"]: (d["old_value"], d["new_value"]) for d in r["details"]}
        .get("owner_name") == ("Iris", "Iris New")
        for r in rows
    )


def test_format_audit_message(fresh_db, repos):
    def _entry(**overrides):
        entry = {
            "username": "admin",
            "table_name": "owners",
            "record_id": 5,
            "details": [],
        }
        entry.update(overrides)
        return entry

    def _action_detail(action):
        return {"field_name": "action", "old_value": "", "new_value": action}

    # Add: just the marker; the created values are stored in details.
    assert audit_repo.format_audit_message(_entry(
        details=[_action_detail("ADD")],
    )) == "added"

    # Edit: field-level diffs read as 'edited <label> <field> from <old> to <new>'.
    message = audit_repo.format_audit_message(_entry(
        details=[_action_detail("UPDATE"),
                 {"field_name": "owner_name", "old_value": "mohamed", "new_value": "Mohamed"},
                 {"field_name": "phone_number", "old_value": "", "new_value": "0502"}],
    ))
    assert message == (
        "edited owner name from 'mohamed' to 'Mohamed', phone number to '0502'"
    )

    # Deleted records keep their data so they could be restored.
    deleted = audit_repo.format_audit_message(_entry(
        details=[_action_detail("DELETE"),
                 {"field_name": "owner_name", "old_value": "Mohamed", "new_value": ""},
                 {"field_name": "phone_number", "old_value": "01230231", "new_value": ""}],
    ))
    assert deleted == (
        "deleted owner name 'Mohamed' with phone number '01230231'"
    )

    # Submissions and reviews stay terse.
    assert audit_repo.format_audit_message(_entry(
        details=[_action_detail("SUBMIT_UPDATE")],
    )) == "submitted update"

    review = audit_repo.format_audit_message(_entry(
        table_name="pending_changes",
        record_id=9,
        details=[
            {"field_name": "status", "old_value": "pending", "new_value": "approved"},
            {"field_name": "review_notes", "old_value": "", "new_value": "Looks good"},
        ],
    ))
    assert review == "approved change request (id 9) (review notes: Looks good)"

    # Long messages truncate.
    long_entry = _entry(
        details=[_action_detail("UPDATE"),
                 {"field_name": "notes", "old_value": "", "new_value": "x" * 500}],
    )
    truncated = audit_repo.format_audit_message(long_entry, max_length=60)
    assert len(truncated) == 60 and truncated.endswith("\u2026")


def test_deleted_owner_keeps_name_and_phone(fresh_db, repos):
    uid = _uid(repos, "del_user")
    cid = client_repo.add_client("Mohamed", "01230231")
    client_repo.delete_client(cid, audit_user_id=uid)
    deletes = [r for r in _recent(repos, "owners", uid) if r["record_id"] == cid]
    assert deletes
    details = audit_repo.get_change_details(deletes[0]["change_header_id"])
    field_map = {d["field_name"]: d["old_value"] for d in details}
    assert field_map["owner_name"] == "Mohamed"
    assert field_map["phone_number"] == "01230231"