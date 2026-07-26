"""Tests for the professional ReceiptInfoDialog (receipt card, payments, adjustments)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QFrame, QLabel, QPushButton, QTableWidget

from src.core.repositories.payment_repo import (
    add_payment, update_payment, delete_payment, get_total_paid,
)
from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
import src.core.repositories.sales_repo as sales_repo


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _make_sale(repos, entity_factory, owner="Receipt Owner"):
    cid = repos["client"].add_client(owner, "0500000000")
    _, item_name = entity_factory["make_supply"](quantity=10)
    # paid=False: these tests exercise the payment UI, which needs an
    # unsettled receipt (quick purchases settle in full by default).
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-06",
        [{"item_name": item_name, "quantity": 2, "price": 25.0}],
        paid=False,
    ))
    return receipt_id


def test_receipt_info_dialog_layout(qapp, fresh_db, repos, entity_factory):
    receipt_id = _make_sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    receipt_cards = [w for w in dlg.findChildren(QFrame) if w.property("class") == "receipt"]
    assert len(receipt_cards) == 1

    items_table = dlg.findChild(QTableWidget, "receiptItems")
    assert items_table is not None
    assert items_table.rowCount() == 1

    texts = " | ".join(l.text() for l in dlg.findChildren(QLabel))
    assert "No payments recorded yet." in texts
    assert "Receipt Owner" in texts

    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Edit Receipt" in btn_texts
    assert "Add Payment" in btn_texts
    assert "Edit Payment" in btn_texts
    assert "Delete Payment" in btn_texts
    assert "OK" in btn_texts

    # Receipt balance is the full amount (50.00) since nothing was paid.
    paid_label = next((l.text() for l in dlg.findChildren(QLabel)
                       if "Balance:" in l.text()), "")
    assert "50.00" in paid_label
    dlg.close()


def test_receipt_info_dialog_hides_write_actions_without_permission(qapp, fresh_db, repos, entity_factory):
    receipt_id = _make_sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=None)

    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Edit Receipt" not in btn_texts
    assert "Add Payment" not in btn_texts
    assert "Edit Payment" not in btn_texts
    assert "Delete Payment" not in btn_texts
    assert "OK" in btn_texts
    dlg.close()


def test_receipt_info_dialog_shows_payments_and_adjustments(qapp, fresh_db, repos, entity_factory):
    receipt_id = _make_sale(repos, entity_factory)
    add_payment(receipt_id, 20.0, "Cash", "deposit")

    from src.core.repositories.receipt_adjustment_repo import add_adjustment
    add_adjustment(
        receipt_id, None, None, "Removed supply item",
        50.0, 30.0,
        [{"item": "supply", "old_value": 25.0, "new_value": 0.0}],
    )

    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    texts = " | ".join(l.text() for l in dlg.findChildren(QLabel))
    assert "Adjustments" in texts
    assert "Adjusted Total: $ 30.00" in texts

    assert dlg._pay_table is not None
    assert dlg._pay_table.rowCount() == 1
    dlg.close()


def test_zero_total_receipt_reads_as_paid(qapp, fresh_db, repos, entity_factory):
    """A 0.00 receipt owes nothing, so the status strip must not say Unpaid."""
    cid = repos["client"].add_client("Zero Owner", "0500000000")
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-06",
        [{"item_name": "Free Sample", "quantity": 2, "price": 0.0}],
    ))
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    labels = [l.text() for l in dlg.findChildren(QLabel)]
    assert "Unpaid" not in labels
    assert "Paid" in labels
    paid_label = next((t for t in labels if "Balance:" in t), "")
    assert "0.00" in paid_label
    dlg.close()


def test_payment_add_edit_delete_and_status(fresh_db, repos, entity_factory):
    receipt_id = _make_sale(repos, entity_factory)

    pid = add_payment(receipt_id, 30.0, "Card", "first")
    assert pid is not None
    assert abs(get_total_paid(receipt_id) - 30.0) < 1e-6

    # Editing only the amount keeps the method/notes untouched.
    assert update_payment(pid, amount=40.0)
    from src.core.repositories.payment_repo import get_payments_for_receipt
    row = get_payments_for_receipt(receipt_id)[0]
    assert abs(float(row["amount"]) - 40.0) < 1e-6
    assert row["payment_method"] == "Card"
    assert row["notes"] == "first"

    # Multi-field edit.
    assert update_payment(pid, amount=35.0, payment_method="Cash", notes="corrected")
    row = get_payments_for_receipt(receipt_id)[0]
    assert abs(float(row["amount"]) - 35.0) < 1e-6
    assert row["payment_method"] == "Cash"
    assert row["notes"] == "corrected"

    # Pay the rest and delete; totals follow.
    add_payment(receipt_id, 15.0, "Cash", "rest")
    assert abs(get_total_paid(receipt_id) - 50.0) < 1e-6
    assert delete_payment(pid)
    assert abs(get_total_paid(receipt_id) - 15.0) < 1e-6

    assert update_payment(999999, amount=5.0) is False


# ---------------------------------------------------------------------------
# Refunds: an overpaid receipt (usually after a batch correction shrank the
# bill) has to be visible and settleable from this dialog.
# ---------------------------------------------------------------------------
def _overpaid_sale(repos, entity_factory):
    """A 50.00 receipt that was settled with 80.00: a 30.00 credit."""
    receipt_id = _make_sale(repos, entity_factory)
    assert add_payment(receipt_id, 80.0, "Cash") is not None
    return receipt_id


def test_credit_replaces_add_payment_with_record_refund(qapp, fresh_db, repos,
                                                       entity_factory):
    receipt_id = _overpaid_sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Record Refund" in btn_texts
    assert "Add Payment" not in btn_texts, "nothing is owed, so no Add Payment"

    labels = [l.text() for l in dlg.findChildren(QLabel)]
    credit_label = next((t for t in labels if "Credit:" in t), "")
    assert "30.00" in credit_label
    assert "Balance:" not in credit_label
    dlg.close()


def test_record_refund_is_hidden_without_permission(qapp, fresh_db, repos,
                                                    entity_factory):
    receipt_id = _overpaid_sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=None)

    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Record Refund" not in btn_texts
    assert "Edit Payment" not in btn_texts
    dlg.close()


def test_recording_a_refund_settles_the_credit(qapp, fresh_db, repos,
                                               entity_factory, monkeypatch):
    from PyQt5.QtWidgets import QDialog as _QDialog, QMessageBox
    monkeypatch.setattr(_QDialog, "exec", lambda self: _QDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    receipt_id = _overpaid_sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    assert abs(dlg.balance - (-30.0)) < 1e-6

    dlg._record_refund()

    from src.core.repositories.payment_repo import get_payments_for_receipt, get_receipt_balance
    assert abs(get_receipt_balance(receipt_id)) < 1e-6
    refunds = [p for p in get_payments_for_receipt(receipt_id)
               if float(p["amount"]) < 0]
    assert len(refunds) == 1
    assert abs(float(refunds[0]["amount"]) - (-30.0)) < 1e-6
    # The dialog re-renders itself: no credit left, so the button is gone
    # (the old toolbar is unparented by _clear, so it is not findable here).
    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Record Refund" not in btn_texts
    assert btn_texts.count("Edit Payment") == 1, "rebuild must not duplicate the toolbar"
    assert sales_repo.get_receipt(receipt_id)["payment_status"] == "Paid"
    dlg.close()


def test_a_refund_row_cannot_be_edited_into_a_payment(qapp, fresh_db, repos,
                                                      entity_factory, monkeypatch):
    from src.core.repositories.payment_repo import add_refund
    from PyQt5.QtWidgets import QMessageBox

    receipt_id = _overpaid_sale(repos, entity_factory)
    assert add_refund(receipt_id, 30.0, "Cash") is not None
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    refund_row = next(i for i, p in enumerate(dlg.payments)
                      if float(p["amount"]) < 0)
    dlg._pay_table.selectRow(refund_row)

    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2])))
    dlg._edit_payment()

    assert shown and "refund" in shown[0].lower()
    # The refund is untouched: the edit dialog never opened (no QMessageBox.warning).
    from src.core.repositories.payment_repo import get_payments_for_receipt
    rows = [p for p in get_payments_for_receipt(receipt_id) if float(p["amount"]) < 0]
    assert len(rows) == 1
    assert abs(float(rows[0]["amount"]) - (-30.0)) < 1e-6
    dlg.close()
