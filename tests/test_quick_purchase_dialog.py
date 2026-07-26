import pytest
from PyQt5.QtCore import QDateTime
from PyQt5.QtSql import QSqlQuery
from PyQt5.QtWidgets import QMessageBox

from src.config.constants import DATE_TIME_FORMAT_UI
from src.core.repositories import package_repo
from src.ui.dialogs import quick_purchase_dialog as qpd


@pytest.fixture
def silent_dialog(fresh_db, qapp, monkeypatch):
    """QuickPurchaseDialog with the modal message boxes neutralized.

    ``fresh_db`` is requested first so the dialog's supply combos are built
    against the test database. The success confirmation is a constructed box
    with a Print button (no longer a static call), so it is stood in for by
    a subclass whose ``exec_`` records the display without ever opening -
    a real modal ``exec_`` access-violates pytest offscreen.
    """
    shown = []
    monkeypatch.setattr(qpd.QMessageBox, "information", lambda *a, **k: shown.append("info"))
    monkeypatch.setattr(qpd.QMessageBox, "warning", lambda *a, **k: shown.append("warning"))
    monkeypatch.setattr(qpd.QMessageBox, "critical", lambda *a, **k: shown.append("critical"))

    class _SilentBox(qpd.QMessageBox):
        def exec_(self):
            shown.append("info")
            return 0

    monkeypatch.setattr(qpd, "QMessageBox", _SilentBox)
    dialog = qpd.QuickPurchaseDialog()
    yield dialog, shown


def _receipt_codes(db):
    q = QSqlQuery(db)
    q.exec("SELECT receipt_code FROM receipts")
    codes = []
    while q.next():
        codes.append(q.value(0))
    return codes


def test_two_quick_purchases_both_record(silent_dialog, fresh_db, entity_factory, monkeypatch):
    """Regression: the second purchase used to fail with "Failed to record purchase."

    ``receipts.receipt_code`` is UNIQUE and the flow hardcoded ``'Sale'``, so
    every quick purchase after the very first one hit the constraint.
    """
    dialog, shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    monkeypatch.setattr(
        dialog, "get_final_items",
        lambda: [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )

    for day in ("2026-09-01 10:00", "2026-09-02 11:00"):
        dialog.client_name_edit.setText("Quick Buyer")
        dialog.date_edit.setDateTime(
            QDateTime.fromString(day, DATE_TIME_FORMAT_UI)
        )
        dialog.handle_accept()

    assert shown == ["info", "info"], shown
    codes = _receipt_codes(fresh_db)
    assert len(codes) == 2, codes
    assert len(set(codes)) == 2, codes

    # Both purchases are settled at the counter, so they are Paid with no
    # outstanding balance.
    q = QSqlQuery(fresh_db)
    q.exec("SELECT receipt_id, payment_status, total_price FROM receipts ORDER BY receipt_id")
    rows = []
    while q.next():
        rows.append((q.value(0), q.value(1), float(q.value(2))))
    assert [r[1] for r in rows] == ["Paid", "Paid"], rows
    assert all(abs(r[2] - 20.0) < 1e-6 for r in rows), rows

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 40.0) < 1e-6

    # Stock was deducted for both purchases.
    q = QSqlQuery(fresh_db)
    q.prepare("SELECT current_stock FROM supplies WHERE item_name = ?")
    q.addBindValue(item_name)
    assert q.exec() and q.next()
    assert q.value(0) == 20 - 4


def test_quick_purchase_shows_stock_error(silent_dialog, fresh_db, entity_factory, monkeypatch):
    """Insufficient stock warns with the item name instead of a generic failure."""
    dialog, shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=1)
    monkeypatch.setattr(
        dialog, "get_final_items",
        lambda: [{"item_name": item_name, "quantity": 5, "price": 10.0}],
    )

    dialog.client_name_edit.setText("Quick Buyer")
    dialog.handle_accept()

    assert shown == ["warning"], shown
    assert _receipt_codes(fresh_db) == []


def test_quick_purchase_without_items_creates_no_client(silent_dialog, fresh_db, monkeypatch):
    """An empty basket is rejected before any owner row is written."""
    dialog, shown = silent_dialog
    monkeypatch.setattr(dialog, "get_final_items", lambda: [])
    monkeypatch.setattr(dialog, "get_final_packages", lambda: [])

    dialog.client_name_edit.setText("Ghost Buyer")
    dialog.handle_accept()

    assert shown == ["warning"], shown
    q = QSqlQuery(fresh_db)
    q.exec("SELECT COUNT(*) FROM owners")
    assert q.next() and q.value(0) == 0


def test_quick_purchase_records_packages(silent_dialog, fresh_db, entity_factory, monkeypatch):
    """Packages can be sold at the counter, on their own or alongside supplies."""
    dialog, shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    pkg_id = int(package_repo.add_package("Vaccine Bundle", "Annual shots", 40.0))
    monkeypatch.setattr(
        dialog, "get_final_items",
        lambda: [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )
    monkeypatch.setattr(
        dialog, "get_final_packages",
        lambda: [{
            "package_id": pkg_id,
            "package_name": "Vaccine Bundle",
            "total_price": 40.0,
            "quantity": 2,
        }],
    )

    dialog.client_name_edit.setText("Package Buyer")
    dialog.handle_accept()

    assert shown == ["info"], shown

    q = QSqlQuery(fresh_db)
    q.exec("SELECT receipt_id, total_price, payment_status FROM receipts")
    assert q.next()
    receipt_id, total, status = q.value(0), float(q.value(1)), q.value(2)
    # Supplies (2 x 10) + packages (2 x 40)
    assert abs(total - 100.0) < 1e-6
    assert status == "Paid"
    assert not q.next()

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT package_id, quantity FROM receipt_packages WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert (q.value(0), q.value(1)) == (pkg_id, 2)

    # The package total is part of the settled amount, not left outstanding.
    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 100.0) < 1e-6


def test_quick_purchase_with_only_packages(silent_dialog, fresh_db, monkeypatch):
    """A package-only basket is a valid purchase (no supply rows required)."""
    dialog, shown = silent_dialog
    pkg_id = int(package_repo.add_package("Consult Pack", "", 75.0))
    monkeypatch.setattr(dialog, "get_final_items", lambda: [])
    monkeypatch.setattr(
        dialog, "get_final_packages",
        lambda: [{
            "package_id": pkg_id,
            "package_name": "Consult Pack",
            "total_price": 75.0,
            "quantity": 1,
        }],
    )

    dialog.client_name_edit.setText("Package Only")
    dialog.handle_accept()

    assert shown == ["info"], shown
    q = QSqlQuery(fresh_db)
    q.exec("SELECT COUNT(*) FROM receipt_packages")
    assert q.next() and q.value(0) == 1


def test_quick_purchase_packages_update_estimated_total(silent_dialog, monkeypatch):
    """The estimated total counts package rows like supply rows."""
    dialog, _shown = silent_dialog
    pkg_id = int(package_repo.add_package("Health Check", "", 30.0))

    dialog._add_package_row()
    dialog._package_rows[-1][0].setCurrentIndex(
        dialog._package_rows[-1][0].findData(
            next(p for p in package_repo.get_all_packages() if p["package_id"] == pkg_id)
        )
    )
    dialog._package_rows[-1][1].setValue(3)

    assert "90.00" in dialog.total_label.text()


def test_quick_purchase_discount_updates_estimated_total(silent_dialog, entity_factory):
    """The percentage discount spin lowers the estimated total live."""
    dialog, _shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    dialog._add_supply_row()
    _cat_cb, item_cb, qty_sb, price_sb = dialog._supply_rows[-1]
    item_cb.setEditText(item_name)
    qty_sb.setValue(3)
    price_sb.setValue(10.0)
    # Subtotal 30, 10% discount -> 27, 3 cash off.
    dialog.discount_percent_spin.setValue(10)
    assert "27.00" in dialog.total_label.text()
    assert dialog._purchase_discount == pytest.approx(3.0)


def test_quick_purchase_passes_discount_to_repo(silent_dialog, entity_factory, monkeypatch):
    """The percentage is converted to cash and forwarded to the receipt writer."""
    dialog, shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(qpd.sales_repo, "create_sale_receipt_for_quick_purchase", fake_create)
    # The real basket validation needs at least one item; the receipt writer is faked.
    monkeypatch.setattr(
        dialog, "get_final_items",
        lambda: [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )
    dialog._add_supply_row()
    _cat_cb, item_cb, qty_sb, price_sb = dialog._supply_rows[-1]
    item_cb.setEditText(item_name)
    qty_sb.setValue(2)
    price_sb.setValue(10.0)
    dialog.client_name_edit.setText("Quick Buyer")
    dialog.discount_percent_spin.setValue(10)
    dialog.handle_accept()

    assert shown == ["info"], shown
    assert captured["discount"] == pytest.approx(2.0)


def test_quick_purchase_amount_paid_defaults_to_total(silent_dialog, entity_factory):
    """The amount paid follows the total (discount included) until edited."""
    dialog, _shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    dialog._add_supply_row()
    _cat_cb, item_cb, qty_sb, price_sb = dialog._supply_rows[-1]
    item_cb.setEditText(item_name)
    qty_sb.setValue(2)
    price_sb.setValue(10.0)
    assert dialog.amount_paid_spin.value() == pytest.approx(20.0)
    dialog.discount_percent_spin.setValue(10)
    assert dialog.amount_paid_spin.value() == pytest.approx(18.0)


def test_quick_purchase_custom_paid_amount_passed_to_repo(silent_dialog, entity_factory,
                                                          monkeypatch):
    """Editing the paid amount records exactly what was given, not the total."""
    dialog, _shown = silent_dialog
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(qpd.sales_repo, "create_sale_receipt_for_quick_purchase", fake_create)
    dialog._add_supply_row()
    _cat_cb, item_cb, qty_sb, price_sb = dialog._supply_rows[-1]
    item_cb.setEditText(item_name)
    qty_sb.setValue(2)
    price_sb.setValue(10.0)
    dialog.client_name_edit.setText("Quick Buyer")
    dialog.amount_paid_spin.setValue(7.5)   # a partial payment
    dialog.handle_accept()

    assert captured["paid_amount"] == pytest.approx(7.5)
    assert captured["discount"] == pytest.approx(0.0)


def test_quick_purchase_payment_method_defaults_to_cash(silent_dialog):
    """The method combo defaults to Cash and maps to the stored English value."""
    dialog, _shown = silent_dialog
    assert dialog.pay_method_combo.currentIndex() == 0
    assert dialog.payment_method() == "Cash"
    dialog.pay_method_combo.setCurrentIndex(3)
    assert dialog.payment_method() == "Other"

class TestSuccessPrint:
    """The sale confirmation offers Print, which hands the receipt over the
    same way Print for Client does (the client copy)."""

    def _spy_box(self, monkeypatch, clicked=None):
        """Records the success box; ``clicked`` is "Print", "ok" (the standard
        button) or None (no click)."""
        captured = {}

        class SpyMessageBox(QMessageBox):
            def exec_(self):
                captured["box"] = self
                return 0

            def clickedButton(self):
                if clicked is None:
                    return None
                if clicked == "ok":
                    return self.button(QMessageBox.Ok)
                return next(
                    (b for b in self.buttons() if b.text() == clicked), None)

        monkeypatch.setattr("src.ui.dialogs.quick_purchase_dialog.QMessageBox",
                            SpyMessageBox)
        return captured

    def test_success_box_has_ok_and_print(self, silent_dialog, monkeypatch):
        dialog, _shown = silent_dialog
        printed = []
        monkeypatch.setattr(dialog, "_print_receipt",
                            lambda receipt_id: printed.append(receipt_id))
        captured = self._spy_box(monkeypatch, clicked="ok")

        dialog._show_success("Purchase recorded. Receipt ID: #7", receipt_id=7)

        box = captured["box"]
        # the built-in OK button + a custom Print button
        assert box.standardButtons() == QMessageBox.Ok
        assert len(box.buttons()) == 2
        assert any(b.text() == "Print" for b in box.buttons())
        assert printed == []   # closing with OK never prints

    def test_print_button_hands_the_receipt_to_print_for_client(
            self, silent_dialog, entity_factory, monkeypatch):
        dialog, _shown = silent_dialog
        _sid, item_name = entity_factory["make_supply"](quantity=20)
        monkeypatch.setattr(
            qpd.sales_repo, "create_sale_receipt_for_quick_purchase",
            lambda **kwargs: 42)
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        printed = []
        monkeypatch.setattr(
            ReceiptInfoDialog, "print_for_client",
            lambda self, parent=None: printed.append((self.receipt_id, parent))
            or True)
        self._spy_box(monkeypatch, clicked="Print")

        dialog._add_supply_row()
        _cat_cb, item_cb, qty_sb, price_sb = dialog._supply_rows[-1]
        item_cb.setEditText(item_name)
        qty_sb.setValue(2)
        price_sb.setValue(10.0)
        dialog.client_name_edit.setText("Print Buyer")
        dialog.handle_accept()

        assert printed == [(42, dialog)]

    def test_print_receipt_builds_the_dialog_on_this_parent(
            self, silent_dialog, monkeypatch):
        dialog, _shown = silent_dialog
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        printed = []
        monkeypatch.setattr(
            ReceiptInfoDialog, "print_for_client",
            lambda self, parent=None: printed.append(
                (self.receipt_id, self.parent())) or True)

        dialog._print_receipt(42)

        assert printed == [(42, dialog)]
