"""
Tests for the receipt editing dialogs (EditReceiptDialog / VisitAdjustDialog).

Covers the receipts-overhaul behaviour they own: a shared revision-trail row +
ADJUST audit whenever the total actually moves, cent-rounded discounts so the
preview matches the saved total, and the consult toggle on the visit dialog.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QDialog

import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.audit_repo as audit_repo
from src.core.repositories.receipt_adjustment_repo import get_adjustments_for_receipt
from src.ui.dialogs.edit_receipt_dialog import EditReceiptDialog
from src.ui.dialogs.visit_adjust_dialog import VisitAdjustDialog


def _user(repos):
    """A real user row - receipt_adjustments.adjusted_by is a foreign key."""
    uid = int(repos["user"].add_user("auditor", "pw12345", "admin"))
    return {"user_id": uid, "username": "auditor", "roles": ["admin"]}


def _sale(repos, entity_factory, price=25.0, quantity=1):
    cid = entity_factory["make_client"]()
    _, item_name = entity_factory["make_supply"](quantity=10)
    return int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": item_name, "quantity": quantity, "price": price}],
        paid=False,
    ))


def _adjust_actions():
    rows = audit_repo.get_recent_changes(limit=500)
    out = []
    for r in rows:
        if r["table_name"] != "receipts":
            continue
        details = audit_repo.get_change_details(r["change_header_id"])
        if details and details[0].get("new_value") == "ADJUST":
            out.append(r)
    return out


def test_discount_cash_is_cent_rounded(qapp, fresh_db, repos, entity_factory):
    """The preview number and the stored discount must be the same number."""
    receipt_id = _sale(repos, entity_factory, price=30.0, quantity=1)
    dlg = EditReceiptDialog(receipt_id, current_user=_user(repos))

    dlg.discount_spin.setValue(33.33)
    assert dlg._discount_cash(30.0) == 10.0  # not 9.999...
    dlg._handle_save()

    header = sales_repo.get_receipt(receipt_id)
    assert abs(float(header["discount"]) - 10.0) < 1e-6
    assert abs(float(header["total_price"]) - 20.0) < 1e-6
    # The rendered preview agrees with what was persisted.
    assert dlg.total_label.text().replace("$", "").replace(",", "").strip() in ("20.00", "20")
    dlg.close()


def test_saving_a_total_change_records_the_adjustment_and_audit(qapp, fresh_db, repos,
                                                                entity_factory):
    """Any edit that moves the money leaves a revision row + ADJUST audit."""
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)
    assert get_adjustments_for_receipt(receipt_id) == []

    dlg = EditReceiptDialog(receipt_id, current_user=_user(repos))
    dlg.discount_spin.setValue(10.0)
    dlg._handle_save()

    assert dlg.result() == QDialog.Accepted
    rows = get_adjustments_for_receipt(receipt_id)
    assert len(rows) == 1
    assert abs(float(rows[0]["old_total"]) - 40.0) < 1e-6
    assert abs(float(rows[0]["new_total"]) - 36.0) < 1e-6
    assert abs(float(rows[0]["delta"]) + 4.0) < 1e-6

    actions = _adjust_actions()
    assert actions and actions[-1]["record_id"] == receipt_id
    dlg.close()


def test_saving_without_changing_anything_records_no_adjustment(qapp, fresh_db, repos,
                                                                entity_factory):
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)
    dlg = EditReceiptDialog(receipt_id, current_user=_user(repos))

    dlg._handle_save()  # nothing edited

    assert dlg.result() == QDialog.Accepted
    assert get_adjustments_for_receipt(receipt_id) == []
    assert _adjust_actions() == []
    dlg.close()


def test_the_adjust_audit_is_attributed_to_the_user(qapp, fresh_db, repos, entity_factory):
    user_id = _user(repos)["user_id"]
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)

    dlg = EditReceiptDialog(receipt_id, current_user={"user_id": user_id,
                                                      "username": "auditor",
                                                      "roles": ["admin"]})
    dlg.discount_spin.setValue(25.0)
    dlg._handle_save()

    actions = _adjust_actions()
    assert actions and actions[-1]["user_id"] == user_id
    dlg.close()


def test_visit_adjust_hides_the_consultation_line(qapp, fresh_db, repos, entity_factory):
    """Consult is driven by the checkbox only, never by the item table."""
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)
    dlg = VisitAdjustDialog(None, receipt_id, current_user=_user(repos))

    names = [str(dlg.table.item(r, 1).text()) for r in range(dlg.table.rowCount())]
    assert all(n.lower() != "consultation" for n in names)
    assert dlg.consult_cb.isChecked() is False
    dlg.close()


def test_visit_adjust_consult_toggle_adds_the_line_and_the_trail(qapp, fresh_db, repos,
                                                                entity_factory):
    """Turning consult on bills it AND records the cumulative revision row."""
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)
    dlg = VisitAdjustDialog(None, receipt_id, current_user=_user(repos))
    dlg._consult_fee = 30.0

    dlg.consult_cb.setChecked(True)
    dlg._handle_save()

    assert dlg.result() == QDialog.Accepted
    assert sales_repo.has_consultation_service(receipt_id) is True

    header = sales_repo.get_receipt(receipt_id)
    assert abs(float(header["total_price"]) - 70.0) < 1e-6

    rows = get_adjustments_for_receipt(receipt_id)
    assert len(rows) == 1
    assert abs(float(rows[0]["delta"]) - 30.0) < 1e-6
    assert any("Consultation" in str(d.get("item", ""))
               for d in rows[0]["details"])
    assert _adjust_actions()
    dlg.close()


def _stock(repos, supply_id):
    for s in repos["supply"].search_supplies():
        if int(s["supply_id"]) == int(supply_id):
            return float(s["current_stock"])
    raise AssertionError("supply not found")


def test_visit_adjust_turning_consult_off_removes_the_line(qapp, fresh_db, repos,
                                                           entity_factory):
    receipt_id = _sale(repos, entity_factory, price=40.0, quantity=1)
    # Start with a consult line already billed (and the total up to date).
    assert sales_repo.reconcile_consultation(receipt_id, True, 25.0) is True
    sales_repo.recompute_receipt_total(receipt_id)
    assert abs(float(sales_repo.get_receipt(receipt_id)["total_price"]) - 65.0) < 1e-6

    dlg = VisitAdjustDialog(None, receipt_id, current_user=_user(repos))
    assert dlg.consult_cb.isChecked() is True

    dlg.consult_cb.setChecked(False)
    dlg._handle_save()

    assert dlg.result() == QDialog.Accepted
    assert sales_repo.has_consultation_service(receipt_id) is False
    header = sales_repo.get_receipt(receipt_id)
    assert abs(float(header["total_price"]) - 40.0) < 1e-6
    assert get_adjustments_for_receipt(receipt_id)
    dlg.close()


def test_zeroing_a_line_removes_it_instead_of_leaving_a_ghost(qapp, fresh_db, repos,
                                                             entity_factory):
    """A line edited down to quantity 0 is deleted, not stored as 0."""
    cid = entity_factory["make_client"]()
    supply_id, item_name = entity_factory["make_supply"](quantity=10)
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": item_name, "quantity": 2, "price": 20.0}],
        paid=False,
    ))
    assert _stock(repos, supply_id) == 8.0

    dlg = EditReceiptDialog(receipt_id, current_user=_user(repos))
    supply_editor = next(e for e in dlg._editors if e[0] == "Supply")
    supply_editor[3].setValue(0)  # editable lines allow 0
    dlg._handle_save()

    assert dlg.result() == QDialog.Accepted
    lines = [i for i in sales_repo.get_receipt_line_items(receipt_id)
             if i["line_type"] == "Supply"]
    assert lines == [], "no ghost 0-quantity line should remain"
    assert _stock(repos, supply_id) == 10.0, "the removed line's stock returns"
    dlg.close()


def test_visit_adjust_zeroing_a_line_removes_it(qapp, fresh_db, repos, entity_factory):
    """The visit-adjust dialog shares the zero-means-remove behaviour."""
    receipt_id = _sale(repos, entity_factory, price=20.0, quantity=2)
    dlg = VisitAdjustDialog(None, receipt_id, current_user=_user(repos))

    supply_editor = next(e for e in dlg._editors if e[0] == "Supply")
    supply_editor[3].setValue(0)
    dlg._handle_save()

    assert dlg.result() == QDialog.Accepted
    lines = [i for i in sales_repo.get_receipt_line_items(receipt_id)
             if i["line_type"] == "Supply"]
    assert lines == []
    dlg.close()
