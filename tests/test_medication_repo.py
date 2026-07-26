"""
Tests for the medication repository's visit-grouped history helper.
"""

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.medication_repo as medication_repo


def _make_pet_with_supply(fresh_db):
    cid = client_repo.add_client("Ali Hassan", "0500123456")
    pid = pet_repo.add_pet("Rexy", "Dog", "Lab", "M", 30, 30.0, cid)
    sid, _ = supply_repo.add_supply(
        "Amoxicillin", "Medicine", "Antibiotics",
        purchase_date="2026-01-01", expiry_date="2027-01-01",
        buy_price=5.0, sell_price=10.0, quantity=10,
    )
    return cid, pid, sid


def test_get_medication_history_by_visit_groups_visits(fresh_db, repos):
    _, pid, sid = _make_pet_with_supply(fresh_db)
    v1 = visit_repo.add_visit("2026-01-05", "Cough", 0, "", pet_id=pid)
    v2 = visit_repo.add_visit("2026-02-10", "Fever", 0, "", pet_id=pid)
    medication_repo.prescribe_medication(v1, sid, "5ml", "twice daily")
    medication_repo.prescribe_medication(v1, sid, "10ml", "once daily")
    medication_repo.prescribe_medication(v2, sid, "5ml", "after food")

    rows = medication_repo.get_medication_history_by_visit(pid)

    assert len(rows) == 3
    # Newest visit first, medications ordered by id within a visit.
    assert [r["visit_id"] for r in rows] == [v2, v1, v1]
    assert [r["medication_id"] for r in rows[1:]] == sorted(r["medication_id"] for r in rows[1:])
    assert all(r["visit_date"] for r in rows)
    assert rows[0]["diagnosis"] == "Fever"
    assert rows[1]["diagnosis"] == "Cough"
    assert rows[1]["item_name"] == "Amoxicillin"
    assert rows[1]["dosage"] == "5ml"
    assert rows[1]["instructions"] == "twice daily"


def test_get_medication_history_by_visit_empty(fresh_db, repos):
    _, pid, _ = _make_pet_with_supply(fresh_db)
    assert medication_repo.get_medication_history_by_visit(pid) == []
    assert medication_repo.get_medication_history_by_visit(999999) == []