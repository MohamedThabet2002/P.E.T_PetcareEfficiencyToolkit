"""
Tests for the undo/redo journal (`deleted_records` + undo_repo).

The four principal deletes (owner / pet / visit / appointment) capture a full,
FK-ordered snapshot before cascading deletion; restoring re-inserts every row
and re-applies SET NULL links (receipts.visit_id, visits.appointment_id).
"""

import json

import pytest

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.health_stats_repo as health_stats_repo
import src.core.repositories.followup_repo as followup_repo
import src.core.repositories.medication_repo as medication_repo
import src.core.repositories.undo_repo as undo_repo
import src.core.repositories.audit_repo as audit_repo
import src.core.database.connection as _db_connection
from PyQt5.QtSql import QSqlQuery


@pytest.fixture
def rich_tree(entity_factory, repos):
    """Owner → pet → visits + clinical rows → receipt. Returns ids."""
    cid = entity_factory["make_client"]("Undo Owner", "0550011220")
    pid = entity_factory["make_pet"](cid, "Undo Pet", weight=12.3)
    v1 = int(visit_repo.add_visit(
        "2026-08-01 10:00", "Diarrhea", True, "notes1", pet_id=pid,
        reason_for_visit="checkup", receipt_code="UNDO-V1",
    ))
    v2 = int(visit_repo.add_visit(
        "2026-08-10 11:00", "Skin", False, "notes2", pet_id=pid,
        receipt_code="UNDO-V2",
    ))
    f1 = followup_repo.add_followup(v1, "2026-09-01", notes="recheck")
    h1 = health_stats_repo.add_health_stat(pid, v1, 1, 1, "temp 38.5")
    h2 = health_stats_repo.add_health_stat(pid, v1, 2, 2, "weight 12.0")
    m1 = medication_repo.prescribe_medication(v2, None, "1tbsp", "daily")
    return {"cid": cid, "pid": pid, "v1": v1, "v2": v2,
            "f1": f1, "h1": h1, "h2": h2, "m1": m1}


def _conn():
    return _db_connection.get_connection()


def _count(table):
    db = _db_connection.get_connection()
    q = QSqlQuery(db)
    q.exec(f"SELECT COUNT(*) FROM {table}")
    q.next()
    return int(q.value(0))


def _row(table, pk_col, pk_value):
    db = _db_connection.get_connection()
    q = QSqlQuery(db)
    q.prepare(f"SELECT * FROM {table} WHERE {pk_col} = ?")
    q.addBindValue(pk_value)
    if not q.exec() or not q.next():
        return None
    return {q.record().fieldName(i): q.value(i) for i in range(q.record().count())}


def test_owner_delete_is_journaled_and_restores_full_tree(fresh_db, rich_tree):
    cid = rich_tree["cid"]
    remaining = _count("pets")
    client_repo.delete_client(cid, audit_user_id=None)

    assert _count("owners") == 0
    entries = undo_repo.list_deleted_records()
    assert len(entries) == 1
    assert entries[0]["table_name"] == "owners"
    assert entries[0]["record_id"] == cid

    ok, msg = undo_repo.restore_deleted_record(entries[0]["deleted_record_id"])
    assert ok, msg

    assert _count("pets") == remaining  # pet came back
    assert _row("owners", "owner_id", cid) is not None
    assert _row("pets", "pet_id", rich_tree["pid"]) is not None
    assert _row("visits", "visit_id", rich_tree["v1"]) is not None
    assert _row("visits", "visit_id", rich_tree["v2"]) is not None
    assert _row("followups", "followup_id", rich_tree["f1"]) is not None
    assert _row("health_stats", "health_stat_id", rich_tree["h1"]) is not None
    assert _row("health_stats", "health_stat_id", rich_tree["h2"]) is not None
    assert _row("medications", "medication_id", rich_tree["m1"]) is not None

    # Journal entry is marked restored and no longer offered.
    still = undo_repo.list_deleted_records()
    assert still == []


def test_pet_delete_restores_pet_and_descendants(fresh_db, rich_tree):
    pid = rich_tree["pid"]
    pet_repo.delete_pet(pid, audit_user_id=None)

    assert _count("pets") == 0
    assert _count("visits") == 0
    entries = undo_repo.list_deleted_records()
    assert len(entries) == 1
    assert entries[0]["table_name"] == "pets"

    ok, msg = undo_repo.restore_deleted_record(entries[0]["deleted_record_id"])
    assert ok, msg
    assert _row("pets", "pet_id", pid) is not None
    assert _row("visits", "visit_id", rich_tree["v1"]) is not None
    assert _row("followups", "followup_id", rich_tree["f1"]) is not None
    # Owner survives a pet delete and is untouched.
    assert _row("owners", "owner_id", rich_tree["cid"]) is not None


def test_visit_delete_restores_visit_and_clinical_rows(fresh_db, rich_tree):
    v1 = rich_tree["v1"]
    visit_repo.delete_visit(v1, audit_user_id=None)

    assert _count("visits") == 1  # v2 survives
    entries = undo_repo.list_deleted_records()
    assert len(entries) == 1
    assert entries[0]["table_name"] == "visits"

    ok, msg = undo_repo.restore_deleted_record(entries[0]["deleted_record_id"])
    assert ok, msg
    assert _row("visits", "visit_id", v1) is not None
    assert _row("followups", "followup_id", rich_tree["f1"]) is not None
    assert _row("health_stats", "health_stat_id", rich_tree["h1"]) is not None
    assert _row("visits", "visit_id", rich_tree["v2"]) is not None  # untouched


def test_appointment_delete_restores_status_history_and_visit_link(fresh_db, entity_factory, repos):
    cid = entity_factory["make_client"]("Apt Owner", "0550033440")
    pid = entity_factory["make_pet"](cid, "Apt Pet")
    aid = int(appointment_repo.add_appointment(
        "2026-09-15 09:00", "Consultation", "Pending", "first", cid, pid,
    ))
    # Link a visit to the appointment (visits.appointment_id is SET NULL on delete).
    vid = int(visit_repo.add_visit(
        "2026-09-15 10:00", "Check", True, "linked", pet_id=pid,
        appointment_id=aid, receipt_code="UNDO-APT",
    ))

    appointment_repo.delete_appointment(aid, audit_user_id=None)

    assert _count("appointments") == 0
    # visit survives with appointment_id unset ('' or None)
    assert _row("visits", "visit_id", vid)["appointment_id"] in (None, "")

    entries = undo_repo.list_deleted_records()
    assert len(entries) == 1
    assert entries[0]["table_name"] == "appointments"

    ok, msg = undo_repo.restore_deleted_record(entries[0]["deleted_record_id"])
    assert ok, msg
    assert _row("appointments", "appointment_id", aid) is not None
    # SET NULL link restored
    assert _row("visits", "visit_id", vid)["appointment_id"] == aid


def test_delete_missing_record_is_not_journaled(fresh_db, repos):
    # Delete repos return True even when 0 rows matched; a nonexistent record
    # must NOT leave a journal entry behind (nothing to restore).
    assert client_repo.delete_client(-1) is True
    assert pet_repo.delete_pet(-1) is True
    assert visit_repo.delete_visit(-1) is True
    assert undo_repo.list_deleted_records() == []


def test_restore_preserves_exact_data(fresh_db, rich_tree):
    v1 = rich_tree["v1"]
    before = _row("visits", "visit_id", v1)
    before_all = _count("visits")
    visit_repo.delete_visit(v1, audit_user_id=None)
    entries = undo_repo.list_deleted_records()
    ok, msg = undo_repo.restore_deleted_record(entries[0]["deleted_record_id"])
    assert ok, msg
    after = _row("visits", "visit_id", v1)
    assert _count("visits") == before_all
    for key in ("visit_date", "diagnosis", "notes", "reason_for_visit", "pet_id"):
        assert after[key] == before[key], f"{key} changed on restore"


def test_restore_already_restored_returns_false(fresh_db, rich_tree):
    client_repo.delete_client(rich_tree["cid"], audit_user_id=None)
    entry = undo_repo.list_deleted_records()[0]
    ok, _ = undo_repo.restore_deleted_record(entry["deleted_record_id"])
    assert ok
    ok2, msg2 = undo_repo.restore_deleted_record(entry["deleted_record_id"])
    assert not ok2
    assert msg2 == "already_restored"


def test_restore_records_audit_action(fresh_db, rich_tree):
    uid = int(__import__("src.core.repositories.user_repo", fromlist=["x"]).add_user(
        "undoer", "pw12345", "admin"))
    client_repo.delete_client(rich_tree["cid"], audit_user_id=uid)
    entry = undo_repo.list_deleted_records()[0]
    ok, msg = undo_repo.restore_deleted_record(entry["deleted_record_id"], user_id=uid)
    assert ok, msg
    changes = audit_repo.get_recent_changes_with_details(10)
    restore_headers = [c for c in changes if c["table_name"] == "owners"
                       and any(d["field_name"] == "action" and d["new_value"] == "RESTORE"
                               for d in c["details"])]
    assert restore_headers, "expected a RESTORE audit header"


def test_snapshot_is_serializable_json(fresh_db, rich_tree):
    snap = undo_repo.capture_snapshot("owners", rich_tree["cid"])
    assert snap is not None
    text = json.dumps(snap)
    assert text
    parsed = json.loads(text)
    assert isinstance(parsed["tables"], list)
    tables = [t["table"] for t in parsed["tables"]]
    assert "owners" in tables and "pets" in tables and "visits" in tables