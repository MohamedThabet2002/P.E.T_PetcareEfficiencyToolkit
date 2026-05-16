"""Tests for the inventory navigation: item name -> stock batches -> item details."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta

from PyQt5.QtCore import QDate, Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QMessageBox, QPushButton

from src.utils.i18n import tr
from src.ui.dialogs.info_dialogs import SupplyInfoDialog
from src.ui.dialogs.stock_batch_dialog import (
    BATCH_ID_COLUMN, RECEIPT_ID_COLUMN, StockBatchDialog,
)
from src.ui.themes.color_palettes import get_active_palette


def _admin_user(user_id=1):
    return {"user_id": user_id, "username": "admin", "roles": ["admin"]}


def _make_item(repos, name="Navigation Bandage", supplier="VetSupply Co"):
    supply_repo = repos["supply"]
    sid, _ = supply_repo.add_supply(
        name, "Medicine", "Antibiotics", purchase_date="2026-01-10",
        expiry_date="2027-01-10", buy_price=5.0, sell_price=10.0,
        quantity=10, supplier=supplier,
    )
    supply_repo.update_supply_stock(
        sid, 15, purchase_date="2026-04-10", supplier="Cairo Animal Care")
    return sid


def _expiring_item(repos, name="Reorder Expiry Vaccine", days_left=10, quantity=4):
    """An item whose (inherited) batch expiry falls inside the 90-day window."""
    supply_repo = repos["supply"]
    expiry = (date.today() + timedelta(days=days_left)).isoformat()
    sid, _ = supply_repo.add_supply(
        name, "Medicine", "Vaccines", purchase_date=date.today().isoformat(),
        expiry_date=expiry, buy_price=5.0, sell_price=10.0, quantity=quantity,
    )
    return sid, expiry


class _FakeStockBatchDialog(QDialog):
    """Stand-in for StockBatchDialog that only records how it was opened."""

    opened = []
    batches_changed = pyqtSignal()

    def __init__(self, supply_id, supply_name, parent=None, current_user=None):
        super().__init__(parent)
        _FakeStockBatchDialog.opened.append((supply_id, supply_name))

    def exec_(self):
        return 0


def _patch_batch_dialog(monkeypatch):
    _FakeStockBatchDialog.opened = []
    monkeypatch.setattr(
        "src.ui.dialogs.supply_reorder_dialog.StockBatchDialog",
        _FakeStockBatchDialog)
    return _FakeStockBatchDialog.opened


class _FakeBatchEditDialog:
    """Stand-in for _BatchEditDialog that returns a canned payload."""

    payload = {}
    captured = {}

    def __init__(self, *args, **kwargs):
        type(self).captured = kwargs

    def exec_(self):
        return 1  # QDialog.Accepted

    def get_data(self):
        return dict(self.payload)


def _patch_batch_editor(monkeypatch, **payload):
    from src.ui.dialogs import stock_batch_dialog as sbd

    fake = type("FakeEdit", (_FakeBatchEditDialog,), {"payload": payload})
    monkeypatch.setattr(sbd, "_BatchEditDialog", fake)
    return fake


def test_batch_id_is_rendered_as_a_blue_link(qapp, fresh_db, repos):
    sid = _make_item(repos)
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())

    cell = dialog.batch_table.item(0, BATCH_ID_COLUMN)
    assert cell is not None
    assert cell.font().underline() and cell.font().bold()
    assert cell.foreground().color() == get_active_palette().qcolor("brand_500")
    assert cell.toolTip()


def test_batch_id_click_opens_read_only_batch_details(qapp, fresh_db, repos, monkeypatch):
    """Clicking a batch number opens that batch's details, not the item's."""
    sid = _make_item(repos)
    batch_dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())

    opened = []
    monkeypatch.setattr(
        SupplyInfoDialog, "exec_", lambda self: opened.append(dict(self._data)) or 0)

    # Row 0 is the newest batch (2026-04-10 from Cairo Animal Care).
    batch_dialog.batch_table.cellClicked.emit(0, BATCH_ID_COLUMN)
    assert len(opened) == 1
    assert opened[0]["supply_id"] == sid
    assert opened[0]["item_name"] == "Navigation Bandage"
    assert opened[0]["batch_id"]
    assert opened[0]["supplier"] == "Cairo Animal Care"
    assert opened[0]["purchase_date"] == "2026-04-10"

    # Each batch opens its own values.
    batch_dialog.batch_table.cellClicked.emit(1, BATCH_ID_COLUMN)
    assert len(opened) == 2
    assert opened[1]["batch_id"] != opened[0]["batch_id"]
    assert opened[1]["supplier"] == "VetSupply Co"
    assert opened[1]["purchase_date"] == "2026-01-10"

    # Clicks outside the batch number column do nothing.
    batch_dialog.batch_table.cellClicked.emit(0, 2)
    assert len(opened) == 2


def test_receipt_id_column_links_a_billed_batch_to_its_receipt(qapp, fresh_db, repos):
    """The batch's purchase receipt is reachable straight from the batch table."""
    sid = _make_item(repos)
    repos["stock"].add_stock_batch(sid, None, "2026-05-05", 25, user_id=1)
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())

    row = next(r for r in range(dialog.batch_table.rowCount())
               if dialog.batch_table.item(r, RECEIPT_ID_COLUMN).text())
    cell = dialog.batch_table.item(row, RECEIPT_ID_COLUMN)
    assert cell.data(Qt.UserRole) is not None
    assert cell.font().underline() and cell.font().bold()
    assert cell.foreground().color() == get_active_palette().qcolor("brand_500")
    assert cell.toolTip()


def test_receipt_id_click_opens_the_receipt_details(qapp, fresh_db, repos, monkeypatch):
    sid = _make_item(repos)
    # The batches of _make_item carry no receipt: mint one that does.
    repos["stock"].add_stock_batch(sid, None, "2026-05-05", 25, user_id=1)
    receipt_id = next(b["receipt_id"] for b in repos["stock"].get_stock_batches(sid)
                      if b["purchase_date"] == "2026-05-05")
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())
    row = next(r for r in range(dialog.batch_table.rowCount())
               if dialog.batch_table.item(r, RECEIPT_ID_COLUMN).data(Qt.UserRole) == receipt_id)

    opened = []
    monkeypatch.setattr(
        "src.ui.pages.database_pages.receipts_page.ReceiptInfoDialog.exec_",
        lambda self: opened.append(self.receipt_id) or 0)

    dialog.batch_table.cellClicked.emit(row, RECEIPT_ID_COLUMN)
    assert opened == [receipt_id]

    # The batch-id cell still opens the batch details, not the receipt.
    monkeypatch.setattr(
        SupplyInfoDialog, "exec_", lambda self: opened.append("batch") or 0)
    dialog.batch_table.cellClicked.emit(row, BATCH_ID_COLUMN)
    assert opened == [receipt_id, "batch"]


def test_a_batch_without_a_receipt_shows_an_empty_cell(qapp, fresh_db, repos,
                                                       monkeypatch):
    """Legacy batches (or ones whose receipt was deleted) are not links."""
    sid = _make_item(repos)
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())

    assert dialog.batch_table.rowCount() >= 2
    for r in range(dialog.batch_table.rowCount()):
        cell = dialog.batch_table.item(r, RECEIPT_ID_COLUMN)
        assert cell.text() == ""
        assert cell.data(Qt.UserRole) is None
        assert not cell.font().underline()

    opened = []
    monkeypatch.setattr(
        "src.ui.pages.database_pages.receipts_page.ReceiptInfoDialog.exec_",
        lambda self: opened.append(self.receipt_id) or 0)
    dialog.batch_table.cellClicked.emit(0, RECEIPT_ID_COLUMN)
    assert opened == []


def test_batches_of_one_item_keep_their_own_expiry_and_price(qapp, fresh_db, repos, monkeypatch):
    """Two batches of the same item edit independently."""
    sid = _make_item(repos)
    stock_repo = repos["stock"]
    newest = next(b for b in stock_repo.get_stock_batches(sid)
                  if b["purchase_date"] == "2026-04-10")
    oldest = next(b for b in stock_repo.get_stock_batches(sid)
                  if b["purchase_date"] == "2026-01-10")
    assert newest["buy_price"] == 5.0  # inherited from the item

    stock_repo.update_stock_batch(newest["batch_id"], newest["supplier_id"],
                                  newest["purchase_date"], 5, "",
                                  expiry_date="2027-02-02", buy_price=7.5)
    stock_repo.update_stock_batch(oldest["batch_id"], oldest["supplier_id"],
                                  oldest["purchase_date"], 10, "",
                                  expiry_date="2028-03-03", buy_price=4.0)

    by_date = {b["purchase_date"]: b for b in stock_repo.get_stock_batches(sid)}
    assert by_date["2026-04-10"]["expiry_date"] == "2027-02-02"
    assert by_date["2026-04-10"]["buy_price"] == 7.5
    assert by_date["2026-01-10"]["expiry_date"] == "2028-03-03"
    assert by_date["2026-01-10"]["buy_price"] == 4.0

    # The details dialog of each batch renders its own values.
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())
    opened = []
    monkeypatch.setattr(
        SupplyInfoDialog, "exec_", lambda self: opened.append(dict(self._data)) or 0)
    dialog.batch_table.cellClicked.emit(0, BATCH_ID_COLUMN)
    dialog.batch_table.cellClicked.emit(1, BATCH_ID_COLUMN)
    assert [d["expiry_date"] for d in opened] == ["2027-02-02", "2028-03-03"]
    assert [d["buy_price"] for d in opened] == [7.5, 4.0]
    assert [d["batch_quantity"] for d in opened] == [5, 10]


def test_item_details_has_no_edit_button(qapp, fresh_db, repos):
    sid = _make_item(repos)
    data = next(r for r in repos["supply"].search_supplies() if r["supply_id"] == sid)
    dialog = SupplyInfoDialog(data)

    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "OK" in labels
    assert "Edit" not in labels
    assert "Save" not in labels


def test_batch_dialog_shows_empty_state_without_batches(qapp, fresh_db, repos):
    """Items with no stock batches get a message instead of a bare empty table."""
    sid, _ = repos["supply"].add_supply("Thermometer", "Tools", "Diagnostics", quantity=0)
    dialog = StockBatchDialog(sid, "Thermometer", current_user=_admin_user())

    assert dialog.batch_table.rowCount() == 0
    assert dialog._empty_label.isHidden() is False  # message is shown...
    assert "No stock batches" in dialog._empty_label.text()

    # As soon as a batch exists the message goes away.
    repos["supply"].update_supply_stock(sid, 3, purchase_date="2026-06-01")
    dialog._refresh_batches()
    assert dialog.batch_table.rowCount() == 1
    assert dialog._empty_label.isHidden() is True


def test_batch_edit_saves_expiry_date_and_buy_price_on_the_batch(qapp, fresh_db, repos, monkeypatch):
    """The Edit flow writes the expiry date and buy price on the batch itself."""
    sid = _make_item(repos)
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())
    dialog.batch_table.selectRow(0)

    fake = _patch_batch_editor(
        monkeypatch,
        supplier_id=None, purchase_date="2026-06-01", quantity=4, notes="restock",
        expiry_date="2030-05-04", buy_price=9.25,
    )
    dialog._edit_batch()

    assert fake.captured["expiry_date"] == "2027-01-10"  # the batch's own value
    assert fake.captured["buy_price"] == 5.0

    batch = next(b for b in repos["stock"].get_stock_batches(sid)
                 if b["purchase_date"] == "2026-06-01")
    assert batch["quantity"] == 4
    assert batch["notes"] == "restock"
    assert batch["expiry_date"] == "2030-05-04"
    assert batch["buy_price"] == 9.25

    # The item keeps its own values; the batch no longer overwrites them.
    row = next(r for r in repos["supply"].search_supplies() if r["supply_id"] == sid)
    assert row["expiry_date"] == "2027-01-10"
    assert row["buy_price"] == 5.0


def test_add_batch_stores_its_own_expiry_and_price(qapp, fresh_db, repos, monkeypatch):
    """A new batch keeps the values entered in the Add dialog."""
    sid = _make_item(repos)
    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())

    fake = _patch_batch_editor(
        monkeypatch,
        supplier_id=None, purchase_date="2026-07-07", quantity=3, notes="",
        expiry_date=None, buy_price=12.0,
    )
    dialog._add_batch()
    assert fake.captured["buy_price"] == 5.0  # prefilled from the item

    batch = next(b for b in repos["stock"].get_stock_batches(sid)
                 if b["purchase_date"] == "2026-07-07")
    assert batch["expiry_date"] is None
    assert batch["buy_price"] == 12.0


def test_batch_dialog_passes_its_user_to_every_stock_write(qapp, fresh_db, repos,
                                                          monkeypatch):
    """Add, Edit and Delete all attribute the stock change to the dialog's user."""
    uid = int(repos["user"].add_user("StockClerk", "pw12345", "admin"))
    sid = _make_item(repos)
    dialog = StockBatchDialog(sid, "Navigation Bandage",
                              current_user=_admin_user(user_id=uid))
    stock_repo = repos["stock"]

    seen = {}
    for name in ("add_stock_batch", "update_stock_batch", "delete_stock_batch"):
        original = getattr(stock_repo, name)

        def spy(*args, _name=name, _original=original, **kwargs):
            seen[_name] = kwargs.get("user_id")
            return _original(*args, **kwargs)

        monkeypatch.setattr(stock_repo, name, spy)

    _patch_batch_editor(
        monkeypatch,
        supplier_id=None, purchase_date="2026-08-01", quantity=4, notes="",
        expiry_date=None, buy_price=5.0,
    )
    dialog._add_batch()

    dialog.batch_table.selectRow(0)
    _patch_batch_editor(
        monkeypatch,
        supplier_id=None, purchase_date="2026-08-01", quantity=9, notes="",
        expiry_date=None, buy_price=5.0,
    )
    dialog._edit_batch()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialog.batch_table.selectRow(0)
    dialog._delete_batch()

    assert seen == {
        "add_stock_batch": uid,
        "update_stock_batch": uid,
        "delete_stock_batch": uid,
    }

    entries = [e for e in repos["audit"].get_recent_changes_with_details()
               if e["table_name"] == "stocks"]
    assert len(entries) == 3, "one audit entry per batch change"
    assert {e["user_id"] for e in entries} == {uid}


def test_batch_edit_does_not_invent_an_expiry_date(qapp, fresh_db, repos, monkeypatch):
    """A batch with no expiry stays without one instead of inheriting the item's."""
    supply_repo = repos["supply"]
    sid, _ = supply_repo.add_supply("No Expiry Item", "Medicine", "Antibiotics", quantity=5)
    dialog = StockBatchDialog(sid, "No Expiry Item", current_user=_admin_user())
    dialog.batch_table.selectRow(0)

    _patch_batch_editor(
        monkeypatch,
        supplier_id=None, purchase_date="2026-06-02", quantity=5, notes="",
        expiry_date=None, buy_price=0.0,
    )
    dialog._edit_batch()

    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert not row["expiry_date"]
    batch = next(b for b in repos["stock"].get_stock_batches(sid))
    assert batch["expiry_date"] is None


def test_batch_edit_dialog_prefills_expiry_and_buy_price(qapp, fresh_db, repos):
    """Opening the batch editor shows that batch's stored expiry date and price."""
    from src.ui.dialogs.stock_batch_dialog import NO_EXPIRY_DATE, _BatchEditDialog

    sid = _make_item(repos)
    batch = next(b for b in repos["stock"].get_stock_batches(sid)
                 if b["purchase_date"] == "2026-04-10")

    editor = _BatchEditDialog(None, "Edit Stock Batch", supply_id=sid,
                              expiry_date=batch["expiry_date"],
                              buy_price=batch["buy_price"])
    assert editor.expiry_edit.date() == QDate(2027, 1, 10)
    assert editor.buy_price_spin.value() == 5.0
    data = editor.get_data()
    assert data["expiry_date"] == "2027-01-10"
    assert data["buy_price"] == 5.0

    editor.expiry_edit.setDate(QDate(2029, 12, 31))
    assert editor.get_data()["expiry_date"] == "2029-12-31"
    editor.buy_price_spin.setValue(8.5)
    assert editor.get_data()["buy_price"] == 8.5

    # Batches without an expiry show the "no expiry" sentinel instead of a date.
    blank = _BatchEditDialog(None, "Edit Stock Batch", supply_id=sid,
                             expiry_date=None, buy_price=None)
    assert blank.expiry_edit.date() == NO_EXPIRY_DATE
    assert blank.expiry_edit.specialValueText() == tr("No expiry")
    assert blank.get_data()["expiry_date"] is None
    assert blank.get_data()["buy_price"] == 0.0

    # Adding a batch carries the same fields.
    add_editor = _BatchEditDialog(None, "Add Stock Batch", supply_id=sid, buy_price=5.0)
    assert add_editor.get_data()["expiry_date"] is None
    assert add_editor.get_data()["buy_price"] == 5.0


def test_batch_edit_dialog_places_expiry_and_price_under_purchase_date(qapp, fresh_db, repos):
    """Expiry date and buy price sit directly under Purchase Date in the editor."""
    from PyQt5.QtWidgets import QFormLayout

    from src.ui.dialogs.stock_batch_dialog import _BatchEditDialog

    editor = _BatchEditDialog(None, "Edit Stock Batch", supply_id=1,
                              expiry_date="2027-01-10", buy_price=5.0)
    form = editor.findChild(QFormLayout)

    assert form.labelForField(editor.expiry_edit).text() == tr("Expiry Date:")
    assert form.labelForField(editor.buy_price_spin).text() == tr("Buy Price:")
    assert form.labelForField(editor.date_edit).text() == tr("Purchase Date:")

    # Purchase Date is followed by Expiry Date, then Buy Price.
    fields = []
    for i in range(form.count()):
        item = form.itemAt(i, QFormLayout.FieldRole)
        if item is not None and item.widget() is not None:
            fields.append(item.widget())
    assert fields.index(editor.expiry_edit) == fields.index(editor.date_edit) + 1
    assert fields.index(editor.buy_price_spin) == fields.index(editor.expiry_edit) + 1


def test_batch_table_shows_expiry_and_buy_price_per_batch(qapp, fresh_db, repos):
    """The batch table lists each batch's own expiry date and buy price."""
    from src.ui.dialogs.stock_batch_dialog import STOCK_BATCH_COLUMNS

    keys = [key for _, key, _ in STOCK_BATCH_COLUMNS]
    assert keys.index("expiry_date") == keys.index("purchase_date") + 1
    assert keys.index("buy_price") == keys.index("expiry_date") + 1

    stock_repo = repos["stock"]
    sid = _make_item(repos)
    newest = next(b for b in stock_repo.get_stock_batches(sid)
                  if b["purchase_date"] == "2026-04-10")
    stock_repo.update_stock_batch(newest["batch_id"], newest["supplier_id"],
                                  newest["purchase_date"], 5, "",
                                  expiry_date="2027-09-09", buy_price=6.5)

    dialog = StockBatchDialog(sid, "Navigation Bandage", current_user=_admin_user())
    row = next(r for r in range(dialog.batch_table.rowCount())
               if dialog.batch_table.item(r, BATCH_ID_COLUMN).text() == str(newest["batch_id"]))
    assert dialog.batch_table.item(row, keys.index("expiry_date")).text() == "2027-09-09"
    assert dialog.batch_table.item(row, keys.index("buy_price")).text() == "6.5"


def test_supplies_page_quantity_column_shows_the_batch_total(qapp, fresh_db, repos):
    """The item table's Quantity is the sum of the batches, not the live stock."""
    from src.ui.pages.database_pages.supplies_page import (
        SUPPLY_COLUMN_MAP, SuppliesPage)

    sid = _make_item(repos)  # batches of 10 and 5
    repos["supply"].update_supply_quantity(sid, 4)  # stock after sales

    quantity_key = next(key for _, key, _ in SUPPLY_COLUMN_MAP if key == "batch_quantity")
    column = [key for _, key, _ in SUPPLY_COLUMN_MAP].index(quantity_key)

    page = SuppliesPage()
    page.set_current_user(_admin_user())
    page.refresh_category_table("Medicine", "")
    table = page.tables["Medicine"]
    row = next(r for r in range(table.rowCount())
               if table.item(r, 0).text() == str(sid))
    assert table.item(row, column).text() == "15"
    assert table.horizontalHeaderItem(column).text() == tr("Quantity")


def test_batches_notify_the_supplies_page_after_every_change(qapp, fresh_db, repos,
                                                             monkeypatch):
    """Adding or deleting a batch refreshes the page table right away."""
    from src.ui.dialogs import stock_batch_dialog as sbd
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    sid = _make_item(repos)  # batches of 10 and 5
    page = SuppliesPage()
    page.set_current_user(_admin_user())

    opened = []
    monkeypatch.setattr(
        StockBatchDialog, "exec_", lambda self: opened.append(self) or 0)

    page.refresh_category_table("Medicine", "")
    table = page.tables["Medicine"]
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == str(sid))
    page.on_link_clicked("Medicine", row, 1, "Navigation Bandage")
    dialog = opened[-1]
    assert page.tables["Medicine"] is table  # the same widget, refreshed in place

    def page_quantity():
        index = next(r for r in range(table.rowCount())
                     if table.item(r, 0).text() == str(sid))
        return table.item(index, 3).text()

    assert page_quantity() == "15"

    # Add a batch -> the page shows the new total without reopening anything.
    fake = type("FakeEdit", (_FakeBatchEditDialog,), {"payload": {
        "supplier_id": None, "purchase_date": "2026-08-08", "quantity": 5,
        "notes": "", "expiry_date": None, "buy_price": 5.0}})
    monkeypatch.setattr(sbd, "_BatchEditDialog", fake)
    dialog._add_batch()
    assert page_quantity() == "20"

    # Delete it -> the page goes back down.
    _answer(monkeypatch, QMessageBox.Yes)
    dialog.batch_table.selectRow(0)
    dialog._delete_batch()
    assert page_quantity() == "15"


def test_reorder_item_names_open_the_stock_batches(qapp, fresh_db, repos, monkeypatch):
    """Both tabs turn the item name into a link to that item's stock batches."""
    from src.ui.dialogs import supply_reorder_dialog as srd

    low_sid = _make_item(repos)  # batches of 10 and 5
    repos["supply"].set_reorder_level("Navigation Bandage", 20)
    exp_sid, _ = _expiring_item(repos)

    dialog = srd.SupplyReorderDialog()
    low_table, exp_table = dialog.low_stock_table, dialog.expiring_table

    low_row = next(r for r in range(low_table.rowCount())
                   if low_table.item(r, 0).text() == "Navigation Bandage")
    exp_row = next(r for r in range(exp_table.rowCount())
                   if exp_table.item(r, 1).text() == "Reorder Expiry Vaccine")

    for cell, supply_id in ((low_table.item(low_row, 0), low_sid),
                            (exp_table.item(exp_row, 1), exp_sid)):
        assert cell.font().underline() and cell.font().bold()
        assert cell.data(Qt.UserRole) == supply_id
        assert cell.toolTip() == tr("View stock batches")

    opened = _patch_batch_dialog(monkeypatch)
    low_table.cellClicked.emit(low_row, 0)
    exp_table.cellClicked.emit(exp_row, 1)
    assert opened == [(low_sid, "Navigation Bandage"), (exp_sid, "Reorder Expiry Vaccine")]

    # Clicks outside the item name column do nothing.
    low_table.cellClicked.emit(low_row, 3)
    exp_table.cellClicked.emit(exp_row, 4)
    assert len(opened) == 2


def test_reorder_expiring_batch_id_opens_that_batch_details(qapp, fresh_db, repos,
                                                           monkeypatch):
    """The batch number opens the details of that batch, matching its own row."""
    from src.ui.dialogs import supply_reorder_dialog as srd

    sid, expiry = _expiring_item(repos)
    batch = repos["stock"].get_stock_batches(sid)[0]

    dialog = srd.SupplyReorderDialog()
    table = dialog.expiring_table
    row = next(r for r in range(table.rowCount())
               if table.item(r, 1).text() == "Reorder Expiry Vaccine")

    cell = table.item(row, 0)
    assert cell.text() == str(batch["batch_id"])
    assert cell.font().underline()
    assert cell.data(Qt.UserRole) == batch["batch_id"]
    assert cell.toolTip() == tr("View batch details")

    opened = []
    monkeypatch.setattr(
        SupplyInfoDialog, "exec_", lambda self: opened.append(dict(self._data)) or 0)

    table.cellClicked.emit(row, 0)
    assert len(opened) == 1
    details = opened[0]
    assert details["batch_id"] == batch["batch_id"]
    assert details["supply_id"] == sid
    # The details describe the very same batch the row is about.
    assert details["batch_quantity"] == 4
    assert table.item(row, 4).text() == "4"
    assert details["expiry_date"] == table.item(row, 6).text() == expiry

    # Clicking the item name opens its batches instead (already covered above);
    # any other column does nothing.
    table.cellClicked.emit(row, 3)
    assert len(opened) == 1


def test_reorder_batches_are_reloaded_after_a_batch_change(qapp, fresh_db, repos,
                                                          monkeypatch):
    """Editing a batch from the reorder dialog refreshes both tabs in place."""
    from src.ui.dialogs import supply_reorder_dialog as srd

    sid, _ = _expiring_item(repos, quantity=4)
    dialog = srd.SupplyReorderDialog()
    assert dialog.expiring_table.rowCount() == 1

    # The real dialog is used here: only its modal loop is short-circuited.
    opened = []
    monkeypatch.setattr(StockBatchDialog, "exec_", lambda self: opened.append(self) or 0)
    dialog._open_stock_batches(sid, "Reorder Expiry Vaccine")
    batch_dialog = opened[-1]
    assert batch_dialog.supply_id == sid

    # Pushing the expiry out of the window drops the row without reopening.
    batch = repos["stock"].get_stock_batches(sid)[0]
    repos["stock"].update_stock_batch(
        batch["batch_id"], batch["supplier_id"], batch["purchase_date"], 4, "",
        expiry_date=(date.today() + timedelta(days=400)).isoformat())
    batch_dialog.batches_changed.emit()
    assert dialog.expiring_table.rowCount() == 0


def test_supplies_page_has_no_view_stock_batches_button(qapp, fresh_db, repos):
    """Batch history is reached from the item name link, not a page button."""
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    page = SuppliesPage()
    page.set_current_user(_admin_user())

    assert not hasattr(page, "stock_batches_btn")
    assert not hasattr(page, "open_stock_batches_dialog")
    # The remaining corner buttons are untouched.
    assert page.packages_btn.text() == tr(" Packages ")
    assert page.reorder_btn.text() == tr(" Reorder Overview ")
    assert page.suppliers_btn.text() == tr(" Suppliers ")


def _answer(monkeypatch, reply):
    from PyQt5.QtWidgets import QMessageBox

    asked = []

    def fake_question(parent, title, text, buttons=None, default=None):
        asked.append(text)
        return reply

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    return asked


def test_known_supplier_name_is_accepted_without_asking(qapp, fresh_db, repos, monkeypatch):
    """Picking/typing a listed supplier never triggers the confirmation."""
    from PyQt5.QtWidgets import QComboBox

    from src.ui.pages.database_pages.supplies_page import resolve_supplier_name

    repos["supplier"].add_supplier("VetSupply Co")
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems([s["supplier_name"] for s in repos["supplier"].get_suppliers()])
    combo.setEditText("vetsupply co")  # different casing

    asked = _answer(monkeypatch, None)
    name, ok = resolve_supplier_name(combo)

    assert ok is True
    assert name == "VetSupply Co"  # stored spelling wins
    assert combo.currentText() == "VetSupply Co"
    assert asked == []
    assert len(repos["supplier"].get_suppliers()) == 1


def test_blank_supplier_stays_optional(qapp, fresh_db, repos, monkeypatch):
    from PyQt5.QtWidgets import QComboBox

    from src.ui.pages.database_pages.supplies_page import resolve_supplier_name

    combo = QComboBox()
    combo.setEditable(True)
    asked = _answer(monkeypatch, None)

    assert resolve_supplier_name(combo) == (None, True)
    assert asked == []


def test_typed_supplier_is_created_after_confirmation(qapp, fresh_db, repos, monkeypatch):
    """Confirming the prompt adds the supplier to the list used by Admin."""
    from PyQt5.QtWidgets import QComboBox, QMessageBox

    from src.ui.pages.database_pages.supplies_page import resolve_supplier_name

    repos["supplier"].add_supplier("VetSupply Co")
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["VetSupply Co"])
    combo.setEditText("Cairo Animal Care")

    asked = _answer(monkeypatch, QMessageBox.Yes)
    name, ok = resolve_supplier_name(combo)

    assert ok is True
    assert name == "Cairo Animal Care"
    assert combo.currentText() == "Cairo Animal Care"
    assert len(asked) == 1
    assert "Cairo Animal Care" in asked[0]

    listed = sorted(s["supplier_name"] for s in repos["supplier"].get_suppliers())
    assert listed == ["Cairo Animal Care", "VetSupply Co"]


def test_declining_the_prompt_aborts_the_save(qapp, fresh_db, repos, monkeypatch):
    """No supplier is created and the caller is told to abort."""
    from PyQt5.QtWidgets import QComboBox, QMessageBox

    from src.ui.pages.database_pages.supplies_page import resolve_supplier_name

    combo = QComboBox()
    combo.setEditable(True)
    combo.setEditText("Cairo Animal Care")
    _answer(monkeypatch, QMessageBox.No)

    name, ok = resolve_supplier_name(combo)

    assert ok is False
    assert name is None
    assert repos["supplier"].get_suppliers() == []


def test_bulk_purchase_confirms_unknown_supplier_before_saving(qapp, fresh_db, repos, monkeypatch):
    """The dashboard bulk dialog asks before storing a brand new supplier."""
    from PyQt5.QtWidgets import QMessageBox

    from src.ui.pages.database_pages.supplies_page import (
        BulkPurchaseDialog, process_bulk_purchase_items)

    repos["supplier"].add_supplier("VetSupply Co")

    # Declining keeps the dialog open and records nothing.
    _answer(monkeypatch, QMessageBox.No)
    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Bandage Roll")
    dialog.supplier.setEditText("Cairo Animal Care")
    dialog._handle_accept()
    assert dialog.result() == 0
    assert [s["supplier_name"] for s in repos["supplier"].get_suppliers()] == ["VetSupply Co"]

    # Confirming closes the dialog and the supplier is now a listed supplier.
    _answer(monkeypatch, QMessageBox.Yes)
    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Bandage Roll")
    dialog.supplier.setEditText("Cairo Animal Care")
    dialog._handle_accept()
    assert dialog.result() != 0 or dialog.isVisible() is False

    listed = sorted(s["supplier_name"] for s in repos["supplier"].get_suppliers())
    assert listed == ["Cairo Animal Care", "VetSupply Co"]

    items = dialog.get_data()
    assert items[0]["supplier"] == "Cairo Animal Care"

    # The supplier name resolves on the item's latest batch.
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    assert process_bulk_purchase_items(None, items) == 1
    row = next(r for r in repos["supply"].search_supplies() if r["item_name"] == "Bandage Roll")
    assert row["supplier"] == "Cairo Animal Care"


def test_bulk_purchase_discount_updates_total(qapp, fresh_db):
    """The percentage discount spin lowers the bulk purchase total live."""
    from src.ui.pages.database_pages.supplies_page import BulkPurchaseDialog

    dialog = BulkPurchaseDialog()
    cat, sub, name, buy, sell, qty = dialog._rows[0]
    buy.setValue(4.0)
    qty.setValue(5)
    # Subtotal 20, 10% discount -> 18, 2 cash off.
    dialog.discount_percent_spin.setValue(10)
    assert "18.00" in dialog.total_label.text()
    assert dialog.discount_cash() == 2.0


def test_bulk_purchase_amount_paid_defaults_to_total(qapp, fresh_db):
    """The amount paid follows the discounted total until edited."""
    from src.ui.pages.database_pages.supplies_page import BulkPurchaseDialog

    dialog = BulkPurchaseDialog()
    cat, sub, name, buy, sell, qty = dialog._rows[0]
    buy.setValue(4.0)
    qty.setValue(5)
    assert dialog.amount_paid_spin.value() == 20.0
    dialog.discount_percent_spin.setValue(10)
    assert dialog.amount_paid_spin.value() == 18.0


def test_bulk_purchase_applies_discount_to_shared_receipt(qapp, fresh_db, repos, monkeypatch):
    """The cash discount is folded into the shared expense receipt header."""
    from PyQt5.QtSql import QSqlQuery

    from src.ui.pages.database_pages.supplies_page import (
        BulkPurchaseDialog, process_bulk_purchase_items)

    repos["supplier"].add_supplier("Acme")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Gauze Roll")
    dialog._rows[0][3].setValue(4.0)   # buy price
    dialog._rows[0][5].setValue(5)     # quantity -> 20 subtotal
    items = dialog.get_data()

    assert process_bulk_purchase_items(None, items, discount=2.0) == 1

    q = QSqlQuery(fresh_db)
    q.exec("SELECT total_price, discount, receipt_kind FROM receipts")
    rows = []
    while q.next():
        rows.append((float(q.value(0)), float(q.value(1)), q.value(2)))
    assert len(rows) == 1
    total, discount, kind = rows[0]
    assert kind == "expense"
    assert abs(total - 18.0) < 1e-6
    assert abs(discount - 2.0) < 1e-6


def test_bulk_purchase_records_what_was_paid(qapp, fresh_db, repos, monkeypatch):
    """A paid amount is recorded against the shared expense receipt right away."""
    from PyQt5.QtSql import QSqlQuery

    from src.ui.pages.database_pages.supplies_page import (
        BulkPurchaseDialog, process_bulk_purchase_items)

    repos["supplier"].add_supplier("Acme")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Gauze Roll")
    dialog._rows[0][3].setValue(4.0)   # buy price
    dialog._rows[0][5].setValue(5)     # quantity -> 20 subtotal
    items = dialog.get_data()

    # 20 subtotal, 2 cash discount -> 18 total, 15 handed over.
    assert process_bulk_purchase_items(None, items, discount=2.0, paid_amount=15.0) == 1

    q = QSqlQuery(fresh_db)
    q.exec("SELECT receipt_id, total_price, payment_status FROM receipts")
    assert q.next()
    receipt_id, total, status = q.value(0), float(q.value(1)), q.value(2)
    assert not q.next()
    assert abs(total - 18.0) < 1e-6
    assert status == "Partial"

    q2 = QSqlQuery(fresh_db)
    q2.prepare("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE receipt_id = ?")
    q2.addBindValue(receipt_id)
    assert q2.exec() and q2.next()
    assert abs(float(q2.value(0)) - 15.0) < 1e-6


def test_bulk_purchase_records_the_chosen_payment_method(qapp, fresh_db, repos, monkeypatch):
    """The method picked in the dialog lands on the shared expense receipt payment."""
    from PyQt5.QtSql import QSqlQuery

    from src.ui.pages.database_pages.supplies_page import (
        BulkPurchaseDialog, process_bulk_purchase_items)

    repos["supplier"].add_supplier("Acme")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Gauze Roll")
    dialog._rows[0][3].setValue(4.0)
    dialog._rows[0][5].setValue(5)
    items = dialog.get_data()

    assert process_bulk_purchase_items(
        None, items, paid_amount=10.0, payment_method="Bank Transfer") == 1

    q = QSqlQuery(fresh_db)
    q.exec("SELECT payment_method FROM payments")
    assert q.next() and q.value(0) == "Bank Transfer"
    assert not q.next()


def test_bulk_purchase_paid_amount_is_clamped_to_total(qapp, fresh_db, repos, monkeypatch):
    """Paying more than the purchase settles it in full instead of overpaying."""
    from PyQt5.QtSql import QSqlQuery

    from src.ui.pages.database_pages.supplies_page import (
        BulkPurchaseDialog, process_bulk_purchase_items)

    repos["supplier"].add_supplier("Acme")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dialog = BulkPurchaseDialog()
    dialog._rows[0][2].setEditText("Gauze Roll")
    dialog._rows[0][3].setValue(4.0)
    dialog._rows[0][5].setValue(5)
    items = dialog.get_data()

    assert process_bulk_purchase_items(None, items, paid_amount=99.0) == 1

    q = QSqlQuery(fresh_db)
    q.exec("SELECT total_price, payment_status FROM receipts")
    assert q.next()
    total = float(q.value(0))
    status = q.value(1)
    assert abs(total - 20.0) < 1e-6
    assert status == "Paid"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 20.0) < 1e-6


def test_refresh_all_tabs_rebuilds_when_categories_changed(qapp, fresh_db, repos):
    """A category created/removed after the page was built gets/loses its tab.

    Regression: refresh_all_tabs() iterated the DB categories and raised
    KeyError ('meds') on any category that had no tab yet (added via
    Settings > Custom Lists or an import after the page was constructed).
    """
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    page = SuppliesPage()
    page.set_current_user(_admin_user())

    repos["supply"].add_category("meds")
    page.refresh_all_tabs()  # must not raise KeyError
    assert "meds" in page.tables
    assert "meds" in page.filters

    repos["supply"].delete_category("meds")
    page.refresh_all_tabs()
    assert "meds" not in page.tables
    assert "meds" not in page.filters


def test_refresh_all_tabs_refreshes_in_place_when_categories_are_unchanged(qapp, fresh_db, repos, monkeypatch):
    """With no category change the existing tables are refreshed, not rebuilt."""
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    repos["supply"].add_category("Medicine")
    page = SuppliesPage()
    page.set_current_user(_admin_user())
    table = page.tables["Medicine"]

    rebuilt = []
    monkeypatch.setattr(page, "rebuild_tabs", lambda: rebuilt.append(True))
    page.refresh_all_tabs()

    assert rebuilt == []
    assert page.tables["Medicine"] is table


def test_edit_dialog_moves_an_item_to_another_category(qapp, fresh_db, repos, monkeypatch):
    """The edit dialog carries a Category field; picking one reloads the sub-categories."""
    from PyQt5.QtWidgets import (
        QComboBox, QDialog as _QDialog, QDialogButtonBox, QMessageBox,
    )

    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    opened = []
    monkeypatch.setattr(_QDialog, "exec", lambda self: opened.append(self) or 0)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    sid = _make_item(repos)  # Medicine / Antibiotics
    repos["supply"].add_category("Medicine")
    repos["supply"].add_category("Equipment")

    page = SuppliesPage()
    page.set_current_user(_admin_user())
    page.refresh_category_table("Medicine", "")
    table = page.tables["Medicine"]
    row = next(r for r in range(table.rowCount())
               if table.item(r, 0).text() == str(sid))

    page.edit_supply_dialog("Medicine", row)
    dialog = opened[-1]
    combos = dialog.findChildren(QComboBox)
    assert len(combos) == 2, "a Category field now sits above the Sub-Category one"
    category_combo, sub_combo = combos
    assert category_combo.currentText() == "Medicine"
    assert sub_combo.currentText() == "Antibiotics"

    category_combo.setCurrentIndex(category_combo.findText("Equipment"))
    # Equipment has no sub-category mapping, and the old category's
    # sub-category must not be carried over.
    assert [sub_combo.itemText(i) for i in range(sub_combo.count())] == ["Other"]
    assert sub_combo.currentText() == "Other"

    dialog.findChild(QDialogButtonBox).buttons()[0].click()  # OK

    item = next(r for r in repos["supply"].search_supplies() if r["supply_id"] == sid)
    assert (item["category"], item["sub_category"]) == ("Equipment", "Other")
    # The page follows the item to its new tab instead of dropping it silently.
    assert page._tab_configs[page.tabs.currentIndex()]["name_key"] == "Equipment"
    assert all(page.tables["Medicine"].item(r, 0).text() != str(sid)
               for r in range(page.tables["Medicine"].rowCount()))
    dialog.close()