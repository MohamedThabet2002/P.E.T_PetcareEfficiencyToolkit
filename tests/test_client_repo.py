"""
Tests for client/owner repository helpers used by the Owner Details dialog.
"""

import src.core.repositories.client_repo as client_repo
import src.core.repositories.audit_repo as audit_repo
import src.core.repositories.user_repo as user_repo


def test_get_owner_details(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    details = client_repo.get_owner_details(cid)
    assert details is not None
    assert details["client_id"] == cid
    assert details["owner_name"] == "Ali Hassan"
    assert details["phone_number"] == "0500123456"
    assert details["created_at"]
    assert client_repo.get_owner_details(999999) is None


def test_update_client_preserves_notes_when_not_passed(fresh_db, repos):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    client_repo.update_client(cid, "Ali Hassan", "0500123456", notes="Allergic to cats")
    client_repo.update_client(cid, "Ali Hassan Updated", "0500999999")
    details = client_repo.get_owner_details(cid)
    assert details["owner_name"] == "Ali Hassan Updated"
    assert details["phone_number"] == "0500999999"
    assert details["notes"] == "Allergic to cats"


def test_update_client_notes_is_audited(fresh_db, repos):
    uid = int(user_repo.add_user("dr_x", "pw12345", "staff"))
    cid = client_repo.add_client("Ali Hassan", "0500123456", audit_user_id=uid)
    assert client_repo.update_client(
        cid, "Ali Hassan", "0500123456", notes="new note", audit_user_id=uid
    )

    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "owners" and r["record_id"] == cid]
    header_id = max(r["change_header_id"] for r in rows)
    details = audit_repo.get_change_details(header_id)
    fields = [(d["field_name"], d["new_value"]) for d in details]
    assert ("notes", "new note") in fields


def test_update_client_does_not_edit_notes_for_pending_flow(fresh_db, repos):
    """Backward compatibility: update_client without `notes` must not touch it."""
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    client_repo.update_client(cid, "Ali Hassan", "0500123456", notes="keep me")
    client_repo.update_client(cid, "Ali Hassan", "0500777777")
    details = client_repo.get_owner_details(cid)
    assert details["notes"] == "keep me"
    assert details["phone_number"] == "0500777777"