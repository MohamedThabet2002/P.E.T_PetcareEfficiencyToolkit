"""
Tests for pet repository helpers used by the Pet Details dialog.
"""

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.audit_repo as audit_repo
import src.core.repositories.user_repo as user_repo
import src.core.repositories.pending_changes_repo as pending_changes_repo


def test_get_pet_details(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    details = pet_repo.get_pet_details(pid)
    assert details is not None
    assert details["pet_id"] == pid
    assert details["pet_name"] == "Rexy"
    assert details["species"] == "Dog"
    assert details["breed"] == "Lab"
    assert details["gender"] == "M"
    assert details["age_months"] == 30
    assert details["weight"] == 30.0
    assert details["client_id"] == cid
    assert details["owner_name"] == "Ali Hassan"
    assert details["owner_phone"] == "0500123456"
    assert details["created_at"]
    assert pet_repo.get_pet_details(999999) is None


def test_update_pet_preserves_notes_when_not_passed(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    assert pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 31, 31.5, cid, notes="shy with strangers")
    assert pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 32, 32.0, cid)
    details = pet_repo.get_pet_details(pid)
    assert details["notes"] == "shy with strangers"
    assert details["weight"] == 32.0
    assert details["age_months"] == 32


def test_update_pet_notes_changed(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    assert pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid, notes="first")
    assert pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid, notes="second")
    details = pet_repo.get_pet_details(pid)
    assert details["notes"] == "second"


def test_update_pet_notes_is_audited(fresh_db, repos):
    uid = int(user_repo.add_user("dr_y", "pw12345", "staff"))
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid, audit_user_id=uid)
    assert pet_repo.update_pet(
        pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid,
        notes="needs fluids", audit_user_id=uid,
    )

    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "pets" and r["record_id"] == pid]
    header_id = max(r["change_header_id"] for r in rows)
    details = audit_repo.get_change_details(header_id)
    fields = [(d["field_name"], d["new_value"]) for d in details]
    assert ("notes", "needs fluids") in fields


def test_pending_pet_update_applies_notes(fresh_db, repos):
    staff = int(user_repo.add_user("staff_l", "pw1", "staff"))
    admin = int(user_repo.add_user("admin_m", "pw2", "admin"))
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)

    payload = {
        "pet_name": "Rexy", "species": "Dog", "breed": "Lab", "gender": "M",
        "age_months": 31, "weight": 31.0, "client_id": cid, "notes": "approved note",
    }
    change_id = pending_changes_repo.submit_change(staff, "pets", pid, "UPDATE", payload)
    assert change_id
    assert pending_changes_repo.approve_change(change_id, admin)

    row = {"table_name": "pets", "record_id": pid, "operation": "UPDATE", "payload": payload}
    assert pending_changes_repo.apply_pending_change(row, reviewer_id=admin)

    details = pet_repo.get_pet_details(pid)
    assert details["notes"] == "approved note"
    assert details["age_months"] == 31
    assert details["weight"] == 31.0


def test_health_status_round_trips_and_preserves_when_not_passed(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    assert pet_repo.get_pet_details(pid)["health_status"] in (None, "")

    assert pet_repo.update_pet(
        pid, "Rexy", "Dog", "Lab", "M", 30, 30.0, cid, health_status="Diseased",
    )
    assert pet_repo.get_pet_details(pid)["health_status"] == "Diseased"

    # notes/health_status both preserve when the caller leaves them out
    assert pet_repo.update_pet(pid, "Rexy", "Dog", "Lab", "M", 31, 31.0, cid)
    details = pet_repo.get_pet_details(pid)
    assert details["health_status"] == "Diseased"
    assert details["age_months"] == 31


def test_pending_pet_update_applies_health_status(fresh_db, repos):
    staff = int(user_repo.add_user("staff_h", "pw1", "staff"))
    admin = int(user_repo.add_user("admin_h", "pw2", "admin"))
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)

    payload = {
        "pet_name": "Rexy", "species": "Dog", "breed": "Lab", "gender": "M",
        "age_months": 30, "weight": 30.0, "client_id": cid,
        "health_status": "Recovering",
    }
    change_id = pending_changes_repo.submit_change(staff, "pets", pid, "UPDATE", payload)
    assert change_id
    assert pending_changes_repo.approve_change(change_id, admin)

    row = {"table_name": "pets", "record_id": pid, "operation": "UPDATE", "payload": payload}
    assert pending_changes_repo.apply_pending_change(row, reviewer_id=admin)

    assert pet_repo.get_pet_details(pid)["health_status"] == "Recovering"