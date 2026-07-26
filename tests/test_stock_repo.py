"""
Tests for the stock ledger invariants behind the Stock Batch dialog.

A batch is not just a row in `stocks`: it moves units in `supplies.current_stock`,
leaves a signed trail in `stock_movements` and posts its financial effect as an
expense receipt, so batch add/edit/delete can never silently desync the item.
"""

import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.stock_repo as stock_repo
import src.core.repositories.supply_repo as supply_repo
from PyQt5.QtSql import QSqlQuery


def _user(repos, name="BatchUser"):
    return int(repos["user"].add_user(name, "pw12345", "admin"))


def _live_stock(db, supply_id):
    q = QSqlQuery(db)
    q.prepare("SELECT current_stock FROM supplies WHERE supply_id = ?")
    q.addBindValue(supply_id)
    assert q.exec() and q.next()
    return int(q.value(0))


def _movements(db, supply_id=None):
    q = QSqlQuery(db)
    if supply_id is None:
        q.exec("SELECT movement_type, quantity, notes, user_id, receipt_id "
               "FROM stock_movements ORDER BY movement_id")
    else:
        q.prepare("SELECT movement_type, quantity, notes, user_id, receipt_id "
                  "FROM stock_movements WHERE supply_id = ? ORDER BY movement_id")
        q.addBindValue(supply_id)
        q.exec()
    return [{"type": q.value(0), "qty": int(q.value(1)), "notes": q.value(2),
             "user_id": q.value(3), "receipt_id": q.value(4)}
            for _ in iter(lambda: q.next(), False)]


def _expenses(db):
    q = QSqlQuery(db)
    q.exec("SELECT receipt_id, total_price, receipt_kind, receipt_code "
           "FROM receipts WHERE receipt_kind = 'expense' ORDER BY receipt_id")
    return [{"receipt_id": int(q.value(0)), "total": float(q.value(1)),
             "kind": q.value(2), "code": q.value(3)}
            for _ in iter(lambda: q.next(), False)]


def _other_lines(db, receipt_id):
    q = QSqlQuery(db)
    q.prepare("SELECT description, amount FROM receipt_other "
              "WHERE receipt_id = ? ORDER BY receipt_other_id")
    q.addBindValue(receipt_id)
    q.exec()
    return [{"description": q.value(0), "amount": float(q.value(1))}
            for _ in iter(lambda: q.next(), False)]


def _batch_receipt(db, batch_id):
    q = QSqlQuery(db)
    q.prepare("SELECT receipt_id FROM stocks WHERE batch_id = ?")
    q.addBindValue(batch_id)
    assert q.exec() and q.next()
    value = q.value(0)
    return int(value) if value is not None and value != "" else None


def _add_item(repos, quantity=10, buy=5.0, name=None):
    return int(supply_repo.add_supply(
        name or "Amoxicillin", "Medicine", "Antibiotics",
        purchase_date="2026-01-01", expiry_date="2027-01-01",
        buy_price=buy, sell_price=10.0, quantity=quantity)[0])


# ---------------------------------------------------------------------------
# add_stock_batch
# ---------------------------------------------------------------------------
class TestAddBatch:
    def test_add_batch_syncs_live_stock_and_batch_total(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        # add_supply seeds a batch of 10 and sets current_stock = 10.
        assert _live_stock(fresh_db, sid) == 10
        assert stock_repo.get_total_stock_for_supply(sid) == 10

        stock_repo.add_stock_batch(sid, None, "2026-02-01", 25)

        assert _live_stock(fresh_db, sid) == 35
        assert stock_repo.get_total_stock_for_supply(sid) == 35

    def test_add_batch_logs_a_purchase_movement(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 4)

        moves = _movements(fresh_db, sid)
        # One for the original add_supply purchase, one for this batch.
        assert [m["type"] for m in moves] == ["purchase", "purchase"]
        assert moves[-1]["qty"] == 4
        assert moves[-1]["receipt_id"] is None or int(moves[-1]["receipt_id"]) >= 0
        assert batch_id is not None

    def test_add_batch_prices_the_expense_receipt(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        before = len(_expenses(fresh_db))

        stock_repo.add_stock_batch(sid, None, "2026-02-01", 6)

        after = _expenses(fresh_db)
        assert len(after) == before + 1
        added = after[-1]
        assert abs(added["total"] - (6 * 5.0)) < 1e-6
        assert added["code"].startswith("EXPENSE")

        lines = _other_lines(fresh_db, added["receipt_id"])
        assert len(lines) == 1
        assert "Amoxicillin" in lines[0]["description"]
        assert "(Adjusted)" in lines[0]["description"]

    def test_add_batch_falls_back_to_the_item_buy_price(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=7.5)
        before = len(_expenses(fresh_db))

        # No batch-level price: value it at what the item costs.
        stock_repo.add_stock_batch(sid, None, "2026-02-01", 2, buy_price=None)

        after = _expenses(fresh_db)
        assert len(after) == before + 1
        assert abs(after[-1]["total"] - (2 * 7.5)) < 1e-6

    def test_add_batch_audits_the_acting_user(self, fresh_db, repos):
        uid = _user(repos)
        sid = _add_item(repos, quantity=10)

        stock_repo.add_stock_batch(sid, None, "2026-02-01", 6, user_id=uid)

        entries = [e for e in repos["audit"].get_recent_changes_with_details()
                   if e["table_name"] == "stocks"]
        assert len(entries) == 1
        assert entries[0]["user_id"] == uid
        assert any(d["new_value"] == "ADD" for d in entries[0]["details"])
        assert any(d["field_name"] == "quantity" for d in entries[0]["details"])

    def test_no_audit_entry_when_no_user_is_passed(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        stock_repo.add_stock_batch(sid, None, "2026-02-01", 6)
        assert not [e for e in repos["audit"].get_recent_changes_with_details()
                    if e["table_name"] == "stocks"]

    def test_add_batch_moves_no_stock_for_a_bad_supply(self, fresh_db, repos):
        assert stock_repo.add_stock_batch(9999, None, "2026-02-01", 5) is None
        assert _movements(fresh_db) == []


# ---------------------------------------------------------------------------
# update_stock_batch
# ---------------------------------------------------------------------------
class TestUpdateBatch:
    def test_correction_recomputes_stock_from_the_batches(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        assert _live_stock(fresh_db, sid) == 110

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 10)

        assert _live_stock(fresh_db, sid) == 20
        assert stock_repo.get_total_stock_for_supply(sid) == 20

    def test_correction_posts_a_signed_adjustment(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        before = _expenses(fresh_db)

        # 100 -> 10 means 90 units of stock we never really had: reverse 450.
        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 10)

        after = _expenses(fresh_db)
        # The correction is folded into the batch's own purchase receipt rather
        # than minting a second EXPENSE row for the same purchase.
        assert len(after) == len(before)
        assert after[-1]["receipt_id"] == before[-1]["receipt_id"]
        assert after[-1]["total"] < before[-1]["total"], \
            "a downward correction reverses cost"
        assert abs(after[-1]["total"] - (before[-1]["total"] - 90 * 5.0)) < 1e-6

        moves = _movements(fresh_db, sid)
        assert moves[-1]["type"] == "adjustment"
        assert moves[-1]["qty"] == -90
        assert "100 -> 10" in moves[-1]["notes"]

    def test_upward_correction_billed_as_extra_cost(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=4.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 5)
        before = _expenses(fresh_db)

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 8)

        after = _expenses(fresh_db)
        assert len(after) == len(before), "appended to the purchase receipt"
        assert abs(after[-1]["total"] - (before[-1]["total"] + 3 * 4.0)) < 1e-6
        assert _movements(fresh_db, sid)[-1]["qty"] == 3
        assert _live_stock(fresh_db, sid) == 18

    def test_price_only_edit_moves_no_stock_and_bills_nothing(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 20)
        moves_before = len(_movements(fresh_db))
        expenses_before = len(_expenses(fresh_db))

        assert stock_repo.update_stock_batch(batch_id, None, "2026-03-01", 20,
                                             notes="price corrected",
                                             buy_price=9.0) is True

        assert _live_stock(fresh_db, sid) == 30
        assert len(_movements(fresh_db)) == moves_before
        assert len(_expenses(fresh_db)) == expenses_before

    def test_correction_is_audited_with_field_diffs(self, fresh_db, repos):
        uid = _user(repos)
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 40)

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 15,
                                      user_id=uid)

        entries = [e for e in repos["audit"].get_recent_changes_with_details()
                   if e["table_name"] == "stocks" and e["record_id"] == batch_id]
        assert len(entries) == 1
        assert entries[0]["user_id"] == uid
        assert any(d["new_value"] == "UPDATE" for d in entries[0]["details"])
        qty_diff = [d for d in entries[0]["details"]
                    if d["field_name"] == "quantity"]
        assert qty_diff and qty_diff[0]["old_value"] == "40"
        assert qty_diff[0]["new_value"] == "15"

    def test_unknown_batch_still_reports_success_without_bookkeeping(
            self, fresh_db, repos):
        assert stock_repo.update_stock_batch(-1, None, "2026-01-01", 5, "x") is True
        assert _movements(fresh_db) == []
        assert _expenses(fresh_db) == []
        assert not [e for e in repos["audit"].get_recent_changes_with_details()
                    if e["table_name"] == "stocks"]


# ---------------------------------------------------------------------------
# delete_stock_batch
# ---------------------------------------------------------------------------
class TestDeleteBatch:
    def test_delete_pulls_the_units_off_the_shelf(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 25)
        assert _live_stock(fresh_db, sid) == 35

        stock_repo.delete_stock_batch(batch_id)

        assert _live_stock(fresh_db, sid) == 10
        assert stock_repo.get_total_stock_for_supply(sid) == 10

    def test_delete_reverses_the_batch_value(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 20)
        before = _expenses(fresh_db)

        stock_repo.delete_stock_batch(batch_id)

        after = _expenses(fresh_db)
        # The reversal lands on the purchase receipt, so buying 20 and then
        # dropping that batch nets the entry back out to zero.
        assert len(after) == len(before)
        assert after[-1]["receipt_id"] == before[-1]["receipt_id"]
        assert abs(after[-1]["total"] - (before[-1]["total"] - 20 * 5.0)) < 1e-6, \
            "dropping stock must reverse its cost in the profit reports"

        moves = _movements(fresh_db, sid)
        assert moves[-1]["type"] == "removal"
        assert moves[-1]["qty"] == -20

    def test_delete_is_audited(self, fresh_db, repos):
        uid = _user(repos)
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 25)

        stock_repo.delete_stock_batch(batch_id, user_id=uid)

        entries = [e for e in repos["audit"].get_recent_changes_with_details()
                   if e["table_name"] == "stocks" and e["record_id"] == batch_id]
        assert len(entries) == 1
        assert entries[0]["user_id"] == uid
        assert any(d["new_value"] == "DELETE" for d in entries[0]["details"])

    def test_audit_reads_as_a_stock_batch(self, fresh_db, repos):
        uid = _user(repos)
        sid = _add_item(repos, quantity=10)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 25)
        stock_repo.delete_stock_batch(batch_id, user_id=uid)

        entry = next(e for e in repos["audit"].get_recent_changes_with_details()
                     if e["table_name"] == "stocks")
        message = repos["audit"].format_audit_message(entry)
        assert "stock batch" in message

    def test_unknown_batch_delete_still_reports_success(self, fresh_db, repos):
        assert stock_repo.delete_stock_batch(-1) is True
        assert _movements(fresh_db) == []
        assert _expenses(fresh_db) == []

    def test_deleting_the_last_batch_leaves_the_item_at_zero(self, fresh_db, repos):
        sid = _add_item(repos, quantity=0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 7)
        assert _live_stock(fresh_db, sid) == 7

        stock_repo.delete_stock_batch(batch_id)

        assert _live_stock(fresh_db, sid) == 0
        assert stock_repo.get_total_stock_for_supply(sid) == 0


# ---------------------------------------------------------------------------
# Drift repair
# ---------------------------------------------------------------------------
class TestDriftRepair:
    def test_a_new_batch_repairs_a_previously_drifted_stock(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10)
        # Simulate the pre-fix drift: current_stock disagrees with the batches.
        q = QSqlQuery(fresh_db)
        q.prepare("UPDATE supplies SET current_stock = 999 WHERE supply_id = ?")
        q.addBindValue(sid)
        assert q.exec()

        stock_repo.add_stock_batch(sid, None, "2026-02-01", 5)

        assert _live_stock(fresh_db, sid) == 15, "recomputed, not incremented"
        assert stock_repo.get_total_stock_for_supply(sid) == 15

    def test_the_ledger_total_always_matches_live_stock(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=3.0)
        b1 = stock_repo.add_stock_batch(sid, None, "2026-02-01", 20)
        stock_repo.update_stock_batch(b1, None, "2026-02-01", 4)
        b2 = stock_repo.add_stock_batch(sid, None, "2026-03-01", 6)
        stock_repo.delete_stock_batch(b2)

        assert _live_stock(fresh_db, sid) == stock_repo.get_total_stock_for_supply(sid)
        assert _live_stock(fresh_db, sid) == 14


# ---------------------------------------------------------------------------
# Batch <-> receipt link (stocks.receipt_id)
# ---------------------------------------------------------------------------
class TestReceiptLink:
    """A batch stays attached to the expense receipt that recorded its purchase,
    so quantity corrections amend one ledger row instead of adding a new
    EXPENSE-### entry for every edit."""

    def test_add_stamps_the_receipt_it_creates(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 6)

        expenses = _expenses(fresh_db)
        assert len(expenses) == 1
        assert _batch_receipt(fresh_db, batch_id) == expenses[0]["receipt_id"]

    def test_two_edits_share_one_receipt(self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 60)
        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 50)
        stock_repo.delete_stock_batch(batch_id)

        expenses = _expenses(fresh_db)
        # One purchase plus three corrections: still exactly one ledger row,
        # and the corrections cancel the purchase back out.
        assert len(expenses) == 1
        assert abs(expenses[0]["total"]) < 1e-6

    def test_a_legacy_batch_adopts_the_receipt_from_its_first_correction(
            self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        # A row written before migration 023 has no link at all.
        q = QSqlQuery(fresh_db)
        q.prepare("UPDATE stocks SET receipt_id = NULL WHERE batch_id = ?")
        q.addBindValue(batch_id)
        assert q.exec()

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 90)
        expenses = _expenses(fresh_db)
        assert len(expenses) == 2, "no link yet, so the first correction stands alone"
        assert _batch_receipt(fresh_db, batch_id) == expenses[-1]["receipt_id"]

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 80)
        assert len(_expenses(fresh_db)) == 2, "and every later edit reuses it"

    def test_a_deleted_purchase_receipt_falls_back_to_a_new_one(
            self, fresh_db, repos):
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        # Removing the receipt clears the link (ON DELETE SET NULL).
        assert sales_repo.delete_receipt(_batch_receipt(fresh_db, batch_id))
        assert _batch_receipt(fresh_db, batch_id) is None

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 90)

        expenses = _expenses(fresh_db)
        assert len(expenses) == 1, "the correction must not vanish with the receipt"
        assert abs(expenses[0]["total"] - (-10 * 5.0)) < 1e-6

    def test_the_supplies_page_receipt_path_stamps_the_batch(self, fresh_db, repos):
        # The page creates the batch but bills it itself, so the batch is
        # unlinked until log_supply_purchase_expense writes the receipt.
        sid, expense = supply_repo.add_supply(
            "Amoxicillin", "Medicine", "Antibiotics",
            purchase_date="2026-01-01", expiry_date="2027-01-01",
            buy_price=4.0, sell_price=8.0, quantity=12, supplier="Acme")
        batch_id = expense["batch_id"]
        assert _batch_receipt(fresh_db, batch_id) is None

        receipt_id = sales_repo.log_supply_purchase_expense(**expense)

        assert receipt_id is not None
        assert _batch_receipt(fresh_db, batch_id) == receipt_id

        # ...so a later correction of that batch lands on the same receipt.
        stock_repo.update_stock_batch(batch_id, None, "2026-01-01", 10)
        expenses = _expenses(fresh_db)
        assert len(expenses) == 1
        assert abs(expenses[0]["total"] - (12 - 2) * 4.0) < 1e-6

    def test_batches_bought_together_share_one_receipt(self, fresh_db, repos):
        # This is the bulk-restock path: every line is billed onto one receipt
        # and each batch remembers which one it was.
        shared = None
        for name in ("Amoxicillin", "Ibuprofen"):
            _, expense = supply_repo.add_supply(
                name, "Medicine", "Antibiotics",
                purchase_date="2026-01-01", expiry_date="2027-01-01",
                buy_price=4.0, sell_price=8.0, quantity=12, supplier="Acme")
            shared = sales_repo.log_supply_purchase_expense(
                **expense, receipt_id=shared)
            assert _batch_receipt(fresh_db, expense["batch_id"]) == shared

        expenses = _expenses(fresh_db)
        assert len(expenses) == 1
        assert abs(expenses[0]["total"] - 2 * 12 * 4.0) < 1e-6


# ---------------------------------------------------------------------------
# Batch edits leave a revision trail on the receipt they amend
# ---------------------------------------------------------------------------
class TestBatchEditAdjustmentTrail:
    """Correcting a batch changes the purchase receipt, so the Receipt Details
    dialog must list it under Adjustments exactly like a hand edit."""

    def _adj_actions(self, repos, receipt_id=None):
        entries = [e for e in repos["audit"].get_recent_changes_with_details()
                   if e["table_name"] == "receipts"]
        out = []
        for e in entries:
            if any(d.get("new_value") == "ADJUST" for d in e["details"]):
                if receipt_id is None or e["record_id"] == receipt_id:
                    out.append(e)
        return out

    def test_quantity_edit_records_a_revision_row_on_the_batch_receipt(
            self, fresh_db, repos):
        from src.core.repositories.receipt_adjustment_repo import (
            get_adjustments_for_receipt)

        uid = _user(repos, "TrailUser")
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        receipt_id = _batch_receipt(fresh_db, batch_id)
        assert get_adjustments_for_receipt(receipt_id) == []

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 10,
                                      user_id=uid)

        rows = get_adjustments_for_receipt(receipt_id)
        assert len(rows) == 1
        assert abs(float(rows[0]["old_total"]) - 100 * 5.0) < 1e-6
        assert abs(float(rows[0]["new_total"]) - 10 * 5.0) < 1e-6
        assert rows[0]["adjusted_by"] == uid
        assert "Amoxicillin" in rows[0]["description"]
        assert "100 -> 10" in rows[0]["description"]
        details = rows[0]["details"]
        assert details[0]["item"] == "Quantity"
        assert details[0]["old_value"] == "100"
        assert details[0]["new_value"] == "10"

    def test_quantity_edit_records_an_adjust_audit(self, fresh_db, repos):
        uid = _user(repos, "AuditUser")
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        receipt_id = _batch_receipt(fresh_db, batch_id)

        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 40,
                                      user_id=uid)

        actions = self._adj_actions(repos, receipt_id)
        assert len(actions) == 1
        assert actions[0]["user_id"] == uid
        assert any(d["field_name"] == "total_price" for d in actions[0]["details"])

    def test_deleting_a_batch_records_the_reversal_as_an_adjustment(
            self, fresh_db, repos):
        from src.core.repositories.receipt_adjustment_repo import (
            get_adjustments_for_receipt)

        uid = _user(repos, "DeleteUser")
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 40)
        receipt_id = _batch_receipt(fresh_db, batch_id)

        assert stock_repo.delete_stock_batch(batch_id, user_id=uid) is True

        rows = get_adjustments_for_receipt(receipt_id)
        assert len(rows) == 1
        assert abs(float(rows[0]["old_total"]) - 40 * 5.0) < 1e-6
        assert abs(float(rows[0]["new_total"])) < 1e-6, "the purchase is reversed"
        assert rows[0]["details"][0] == {"item": "Quantity",
                                         "old_value": "40", "new_value": "0"}
        assert self._adj_actions(repos, receipt_id)

    def test_a_new_batch_stands_alone_and_writes_no_revision_row(
            self, fresh_db, repos):
        """Creating a receipt is not an edit of it - the trail only fills in
        when an *existing* receipt's total actually moves."""
        from src.core.repositories.receipt_adjustment_repo import (
            get_adjustments_for_receipt)

        uid = _user(repos, "AddUser")
        sid = _add_item(repos, quantity=10, buy=5.0)

        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 25,
                                              user_id=uid)

        receipt_id = _batch_receipt(fresh_db, batch_id)
        assert receipt_id is not None
        assert get_adjustments_for_receipt(receipt_id) == []
        assert self._adj_actions(repos) == []

    def test_a_price_only_edit_records_nothing(self, fresh_db, repos):
        """No money moved, so there is no revision to show."""
        from src.core.repositories.receipt_adjustment_repo import (
            get_adjustments_for_receipt)

        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 20)
        receipt_id = _batch_receipt(fresh_db, batch_id)

        stock_repo.update_stock_batch(batch_id, None, "2026-03-01", 20,
                                      buy_price=9.0, user_id=_user(repos))

        assert get_adjustments_for_receipt(receipt_id) == []

    def test_correction_refreshes_the_payment_status(self, fresh_db, repos):
        """A purchase that is no longer fully paid must stop claiming Paid."""
        from src.core.repositories.payment_repo import add_payment

        uid = _user(repos, "PayUser")
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        receipt_id = _batch_receipt(fresh_db, batch_id)
        assert add_payment(receipt_id, 500.0, "Cash") is not None
        assert sales_repo.get_receipt(receipt_id)["payment_status"] == "Paid"

        # 100 -> 200 doubles the bill while only 500 is settled: Partial now.
        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 200,
                                      user_id=uid)

        header = sales_repo.get_receipt(receipt_id)
        assert abs(float(header["total_price"]) - 1000.0) < 1e-6
        assert header["payment_status"] == "Partial"

    def test_an_overcorrected_purchase_shows_up_as_refund_due(
            self, fresh_db, repos):
        """The whole point of the Remainders entry: a settled purchase that a
        later correction has overpaid keeps nagging until the credit is paid back."""
        from src.core.repositories.payment_repo import add_payment

        uid = _user(repos, "RefundUser")
        sid = _add_item(repos, quantity=10, buy=5.0)
        batch_id = stock_repo.add_stock_batch(sid, None, "2026-02-01", 100)
        receipt_id = _batch_receipt(fresh_db, batch_id)
        assert add_payment(receipt_id, 500.0, "Cash") is not None
        assert not [n for n in repos["analytics"].get_notifications()
                    if n["type"] == "expense_balance"]

        # 100 -> 10 units: the bill drops to 50 while 500 was already paid.
        stock_repo.update_stock_batch(batch_id, None, "2026-02-01", 10,
                                      user_id=uid)

        balances = [n for n in repos["analytics"].get_notifications()
                    if n["type"] == "expense_balance"]
        assert len(balances) == 1
        assert balances[0]["title"] == "Refund Due"
        assert balances[0]["severity"] == "info"
        assert abs(balances[0]["balance"] - 450.0) < 1e-6

        # ...and it stays there until the credit is handed back.
        assert add_payment(receipt_id, -450.0, "Cash") is None, \
            "add_payment only takes positive amounts"

        from src.core.repositories.payment_repo import add_refund
        assert add_refund(receipt_id, 450.0, "Cash",
                          "credit from the batch correction",
                          audit_user_id=uid) is not None

        assert sales_repo.get_receipt(receipt_id)["payment_status"] == "Paid"
        assert not [n for n in repos["analytics"].get_notifications()
                    if n["type"] == "expense_balance"]
