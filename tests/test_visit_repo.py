"""
Tests for visit repository helpers used by the Owner Details dialog.
"""

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo


def test_get_recent_visits_for_client(fresh_db, repos):
    cid = client_repo.add_client("Sara", "0501")
    pid1 = pet_repo.add_pet("Bella", "Dog", "Poodle", "F", 12, 4.0, cid)
    cid2 = client_repo.add_client("Omar", "0502")
    pid2 = pet_repo.add_pet("Max", "Cat", "Siamese", "M", 24, 5.0, cid2)

    v1 = visit_repo.add_visit("2026-01-01", "Vaccination", 1, "first", pet_id=pid1)
    v2 = visit_repo.add_visit("2026-02-01", "Checkup", 0, "second", pet_id=pid1)
    visit_repo.add_visit("2026-03-01", "Other", 0, "", pet_id=pid2)  # other owner

    rows = visit_repo.get_recent_visits_for_client(cid, limit=4)
    assert [int(r["visit_id"]) for r in rows] == [int(v2), int(v1)]
    assert rows[0]["pet_name"] == "Bella"
    assert rows[0]["diagnosis"] == "Checkup"
    assert rows[1]["is_consult"] == 1

    limited = visit_repo.get_recent_visits_for_client(cid, limit=1)
    assert len(limited) == 1
    assert int(limited[0]["visit_id"]) == int(v2)


def test_get_recent_visits_returns_empty_for_no_history(fresh_db, repos):
    cid = client_repo.add_client("NoVisits", "0503")
    assert visit_repo.get_recent_visits_for_client(cid, limit=4) == []


def test_get_recent_visits_for_pet(fresh_db, repos):
    cid = client_repo.add_client("Sara", "0501")
    pid1 = pet_repo.add_pet("Bella", "Dog", "Poodle", "F", 12, 4.0, cid)
    pid2 = pet_repo.add_pet("Max", "Cat", "Siamese", "M", 24, 5.0, cid)

    v1 = visit_repo.add_visit("2026-01-01", "Vaccination", 1, "first", pet_id=pid1)
    v2 = visit_repo.add_visit("2026-02-01", "Checkup", 0, "second", pet_id=pid1)
    visit_repo.add_visit("2026-03-01", "Other", 0, "", pet_id=pid2)  # other pet

    rows = visit_repo.get_recent_visits_for_pet(pid1, limit=4)
    assert [int(r["visit_id"]) for r in rows] == [int(v2), int(v1)]
    assert rows[0]["pet_name"] == "Bella"
    assert rows[0]["diagnosis"] == "Checkup"
    assert rows[1]["is_consult"] == 1

    limited = visit_repo.get_recent_visits_for_pet(pid1, limit=1)
    assert len(limited) == 1
    assert int(limited[0]["visit_id"]) == int(v2)

    assert visit_repo.get_recent_visits_for_pet(999999, limit=4) == []


def test_get_visit_stats_for_pet(fresh_db, repos):
    cid = client_repo.add_client("Sara", "0501")
    pid1 = pet_repo.add_pet("Bella", "Dog", "Poodle", "F", 12, 4.0, cid)
    pid2 = pet_repo.add_pet("Max", "Cat", "Siamese", "M", 24, 5.0, cid)

    # Consult visit generates a receipt (total = consult fee), so avg_spend > 0.
    visit_repo.add_visit("2026-01-01", "Vaccination", 1, "first", pet_id=pid1)
    visit_repo.add_visit("2026-02-01", "Checkup", 0, "second", pet_id=pid1)
    visit_repo.add_visit("2026-03-01", "Other", 0, "", pet_id=pid2)

    stats = visit_repo.get_visit_stats_for_pet(pid1)
    assert stats["visit_count"] == 2
    assert stats["last_visit_date"] == "2026-02-01"
    assert float(stats["avg_spend"]) > 0

    only_other = visit_repo.get_visit_stats_for_pet(pid2)
    assert only_other["visit_count"] == 1
    assert float(only_other["avg_spend"]) == 0.0

    assert visit_repo.get_visit_stats_for_pet(999999) == {
        "visit_count": 0, "avg_spend": 0.0, "last_visit_date": "",
    }


def test_billable_visits_get_unique_receipt_codes(fresh_db, repos):
    """Regression: add_visit hardcoded receipt_code='Sale', so the UNIQUE
    receipts.receipt_code rejected every billable visit after the first and the
    visit was stored without its receipt (and its billing)."""
    from PyQt5.QtSql import QSqlQuery

    cid = client_repo.add_client("Multi", "0599")
    pid = pet_repo.add_pet("Bella", "Dog", "Poodle", "F", 12, 4.0, cid)

    visit_ids = [
        visit_repo.add_visit("2026-0%d-01" % (i + 1), "Checkup", 1, "", pet_id=pid)
        for i in range(4)
    ]
    assert all(visit_ids), visit_ids

    q = QSqlQuery(fresh_db)
    assert q.exec("SELECT receipt_code, receipt_kind FROM receipts")
    rows = []
    while q.next():
        rows.append((q.value(0), q.value(1)))

    assert len(rows) == 4, rows
    codes = [r[0] for r in rows]
    assert len(set(codes)) == 4, codes
    assert all(c.startswith("VISIT-") for c in codes), codes
    assert all(kind == "visit" for _, kind in rows), rows


def _consult_fee():
    from src.config.constants import DEFAULT_CONSULT_FEE
    from src.utils.settings_manager import SettingsManager
    return float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))


def test_add_visit_records_what_was_paid(fresh_db, repos):
    """A paid amount handed over at the counter lands on the visit receipt."""
    from PyQt5.QtSql import QSqlQuery

    cid = client_repo.add_client("Aya", "0599")
    pid = pet_repo.add_pet("Max", "Cat", "", "F", 12, 4.0, cid)
    fee = _consult_fee()

    receipt = visit_repo.add_visit(
        "2026-09-01", "Checkup", 1, "", pet_id=pid, paid_amount=5.0,
    )
    assert receipt is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT total_price, payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt)
    assert q.exec() and q.next()
    assert abs(float(q.value(0)) - fee) < 1e-6
    assert q.value(1) == "Partial"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 5.0) < 1e-6


def test_add_visit_without_a_paid_amount_stays_unpaid(fresh_db, repos):
    """No paid amount means the visit receipt is simply recorded as Unpaid."""
    from PyQt5.QtSql import QSqlQuery

    cid = client_repo.add_client("Aya", "0599")
    pid = pet_repo.add_pet("Max", "Cat", "", "F", 12, 4.0, cid)

    receipt = visit_repo.add_visit("2026-09-01", "Checkup", 1, "", pet_id=pid)
    assert receipt is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt)
    assert q.exec() and q.next()
    assert q.value(0) == "Unpaid"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COUNT(*) FROM payments")
    assert q2.next() and q2.value(0) == 0


def test_add_visit_records_the_chosen_payment_method(fresh_db, repos):
    """The method picked at the counter lands on the payment row."""
    from PyQt5.QtSql import QSqlQuery

    cid = client_repo.add_client("Aya", "0599")
    pid = pet_repo.add_pet("Max", "Cat", "", "F", 12, 4.0, cid)

    receipt = visit_repo.add_visit(
        "2026-09-01", "Checkup", 1, "", pet_id=pid,
        paid_amount=5.0, payment_method="Card",
    )
    assert receipt is not None

    q = QSqlQuery(fresh_db)
    q.exec("SELECT payment_method FROM payments")
    assert q.next() and q.value(0) == "Card"
    assert not q.next()


def test_add_visit_stock_matches_item_category(fresh_db, repos, entity_factory):
    """Stock is checked and deducted per (item_name, category).

    Two supplies may share a name across categories; summing by name alone let a
    sale advertise the combined stock and then drain one row negative.
    """
    from PyQt5.QtSql import QSqlQuery

    cid = client_repo.add_client("Aya", "0599")
    pid = pet_repo.add_pet("Max", "Cat", "", "F", 12, 4.0, cid)
    med_sid, name = entity_factory["make_supply"](quantity=3, category="Medicine")
    eq_sid, _ = entity_factory["make_supply"](quantity=5, name=name, category="Equipment")

    # Medicine only holds 3: a sale of 4 must fail even though the combined
    # stock (3 + 5) would have covered it.
    result = visit_repo.add_visit(
        "2026-09-01", "Checkup", 0, "", pet_id=pid,
        items=[{"item_name": name, "category": "Medicine", "quantity": 4, "price": 10.0}],
    )
    assert isinstance(result, str) and result.startswith("STOCK_ERROR"), result

    def _stock(sid):
        q = QSqlQuery(fresh_db)
        q.prepare("SELECT current_stock FROM supplies WHERE supply_id = ?")
        q.addBindValue(sid)
        assert q.exec() and q.next()
        return q.value(0)

    # A sale within the Medicine row drains only that row.
    receipt = visit_repo.add_visit(
        "2026-09-02", "Checkup", 0, "", pet_id=pid,
        items=[{"item_name": name, "category": "Medicine", "quantity": 3, "price": 10.0}],
    )
    assert receipt is not None
    assert _stock(med_sid) == 0
    assert _stock(eq_sid) == 5


def test_get_doctor_visits_exposes_consult_from_the_receipt(fresh_db, repos):
    """`consult` is receipt-driven, so the list must derive it (0/1).

    The old query omitted it entirely, leaving the Consult column blank and the
    Visit Details dialog always opening with consult unchecked.
    """
    cid = client_repo.add_client("Lina", "0509")
    pid = pet_repo.add_pet("Milo", "Cat", "Persian", "M", 12, 4.0, cid)

    out = {}
    visit_repo.add_visit("2026-04-01", "Checkup", 1, "", pet_id=pid, ids_out=out)
    vid_consult = int(out["visit_id"])
    vid_plain = int(visit_repo.add_visit("2026-04-02", "Vaccination", 0, "", pet_id=pid))

    rows = {int(r["visit_id"]): r for r in visit_repo.get_doctor_visits()}
    assert int(rows[vid_consult]["consult"]) == 1
    assert int(rows[vid_plain]["consult"]) == 0
