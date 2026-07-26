"""
Tests for the Receipt Details dialog and the receipts ledger page.

Covers the receipts-overhaul behaviour: print of the receipt card, the
Print for Client gate (fully paid receipts only, no payment details),
the data_changed fan-out when money moves, and the ledger's filter/total
column contract (the filter must follow the column key, never its translation).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QMessageBox, QTableWidget

import src.core.repositories.sales_repo as sales_repo
import src.ui.pages.database_pages.receipts_page as receipts_page_mod
from src.ui.pages.database_pages.receipts_page import (
    RECEIPT_COLUMN_MAP,
    ReceiptInfoDialog,
    ReceiptsPage,
)


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _sale(repos, entity_factory, price=25.0, quantity=2, paid=False):
    cid = entity_factory["make_client"]()
    _, item_name = entity_factory["make_supply"](quantity=10)
    return int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": item_name, "quantity": quantity, "price": price}],
        paid=paid,
    ))


def test_filter_field_returns_the_column_key_not_the_label(qapp, fresh_db):
    """A translated (or edited) filter label must never change the column."""
    page = ReceiptsPage()
    combo = page.filters["Expenses"]

    assert page._filter_field() == "All"

    for i, (_, key, _) in enumerate(RECEIPT_COLUMN_MAP, start=1):
        combo.setCurrentIndex(i)
        assert page._filter_field() == key

    # Pretend the header is displayed in another language: the key still wins.
    total_idx = next(i for i, (_, key, _) in enumerate(RECEIPT_COLUMN_MAP, start=1)
                     if key == "total_price")
    combo.setItemText(total_idx, "المجموع")
    combo.setCurrentIndex(total_idx)
    assert page._filter_field() == "total_price"
    combo.setCurrentIndex(0)
    page.close()


def test_ledger_total_column_shows_the_receipt_total(qapp, fresh_db, repos, entity_factory):
    """'Total Price' must display what filtering on 'total_price' searches."""
    cid = entity_factory["make_client"]()
    _, a = entity_factory["make_supply"](quantity=10)
    _, b = entity_factory["make_supply"](quantity=10)
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": a, "quantity": 2, "price": 25.0},
         {"item_name": b, "quantity": 1, "price": 10.0}],
        paid=False,
    ))

    page = ReceiptsPage()
    page.refresh_receipts_table()
    table = page.tables["Expenses"]
    total_col = next(i for i, c in enumerate(RECEIPT_COLUMN_MAP)
                     if c[1] == "total_price")

    rows = [r for r in range(table.rowCount())
            if int(table.item(r, 0).data(Qt.DisplayRole)) == receipt_id]
    assert len(rows) == 2  # one row per line item
    for r in rows:
        assert abs(float(table.item(r, total_col).data(Qt.DisplayRole)) - 60.0) < 1e-6

    # Searching the value the column displays finds the receipt.
    hits = sales_repo.get_receipt_items("60", "Total Price")
    assert any(h["receipt_id"] == receipt_id for h in hits)
    page.close()


def test_receipt_changed_refreshes_the_ledger_and_fans_out(qapp, fresh_db, repos, entity_factory):
    """A payment made in the dialog must reach every page watching money."""
    _sale(repos, entity_factory)
    page = ReceiptsPage()
    seen = []
    page.data_changed.connect(lambda: seen.append(True))

    page._on_receipt_changed()

    assert seen, "ReceiptsPage.data_changed must be emitted"
    assert page.tables["Expenses"].rowCount() > 0
    page.close()


def test_opening_the_details_dialog_wires_the_fan_out(qapp, fresh_db, repos,
                                                      entity_factory, monkeypatch):
    _sale(repos, entity_factory)
    page = ReceiptsPage()
    page.refresh_receipts_table()

    captured = []
    monkeypatch.setattr(
        ReceiptInfoDialog, "exec",
        lambda self: (captured.append(self), 0)[1],
    )
    page._open_receipt_info(0, 0)
    assert captured, "the details dialog should have been constructed"

    seen = []
    page.data_changed.connect(lambda: seen.append(True))
    captured[0].data_changed.emit()
    assert seen, "ReceiptInfoDialog.data_changed must be wired to the page"
    page.close()


def test_receipt_dialog_renders_print_and_client_pixmaps(qapp, fresh_db, repos,
                                                         entity_factory):
    receipt_id = _sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    pix = dlg._render_receipt_pixmap()
    assert pix is not None and not pix.isNull()

    client_pix = dlg._render_client_receipt_pixmap()
    assert client_pix is not None and not client_pix.isNull()
    dlg.close()


def test_print_for_client_hosts_its_dialogs_on_the_given_parent(qapp, fresh_db, repos,
                                                                entity_factory, monkeypatch):
    """The wizard passes itself so the refusal message centres on it."""
    receipt_id = _sale(repos, entity_factory)  # Unpaid (paid=False)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    hosts = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, message, *a, **k: hosts.append(parent),
    )

    result = dlg.print_for_client(parent="wizard-host")

    assert result is False
    assert hosts == ["wizard-host"]
    dlg.close()


def test_receipt_dialog_has_print_and_client_buttons(qapp, fresh_db, repos, entity_factory):
    receipt_id = _sale(repos, entity_factory)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    btn_texts = [b.text() for b in dlg.findChildren(
        __import__("PyQt5.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert "Print" in btn_texts
    assert "Print for Client" in btn_texts
    assert "Export PDF" not in btn_texts
    dlg.close()


def test_receipt_meta_rows_run_date_type_owner_pet_phone(qapp, fresh_db, repos,
                                                         entity_factory):
    """The card lists Date, Type, Owner, Pet, Phone — pet name included."""
    cid = entity_factory["make_client"](name="Meta Owner", phone="0501112222")
    pid = entity_factory["make_pet"](cid, name="Buddy")
    _, item_name = entity_factory["make_supply"](quantity=10)
    receipt_id = int(repos["visit"].add_visit(
        visit_date="2026-09-07",
        diagnosis="Checkup",
        consult=True,
        notes="",
        pet_id=pid,
        items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
    ))
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    captions = [l.text() for l in dlg._receipt_frame.findChildren(QLabel)
                if l.property("class") == "receipt-meta-caption"]
    wanted = ["Date:", "Type:", "Owner:", "Pet:", "Phone:"]
    positions = [captions.index(c) for c in wanted]
    assert positions == sorted(positions), captions
    assert "Visit:" not in captions, captions

    values = [l.text() for l in dlg._receipt_frame.findChildren(QLabel)
              if l.property("class") == "receipt-meta-value"]
    assert "Buddy" in values
    assert "0501112222" in values
    dlg.close()


def test_client_receipt_card_omits_payment_details(qapp, fresh_db, repos, entity_factory):
    """The client copy is the Add Visit receipt: no status strip, no Paid line."""
    receipt_id = _sale(repos, entity_factory)  # Unpaid (paid=False)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    on_screen = dlg._receipt_frame

    frame = dlg._build_receipt_card(client=True)
    texts = [l.text() for l in frame.findChildren(QLabel)]

    assert not any(t in ("Paid", "Partial", "Unpaid") for t in texts)
    assert not any(t.startswith("Paid:") for t in texts)
    assert any("Thank you" in t for t in texts)
    # The throwaway card must not hijack the on-screen receipt.
    assert dlg._receipt_frame is on_screen
    frame.setParent(None)
    frame.deleteLater()
    dlg.close()


def test_print_for_client_is_blocked_until_the_receipt_is_paid(qapp, fresh_db, repos,
                                                               entity_factory, monkeypatch):
    receipt_id = _sale(repos, entity_factory)  # Unpaid (paid=False)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda parent, title, message, *a, **k: messages.append(message),
    )
    printed = []
    monkeypatch.setattr(receipts_page_mod, "QPrintDialog", lambda *a, **k: printed.append(a))

    dlg._print_for_client()

    assert messages, "the user must be told only fully paid receipts print for clients"
    assert "fully paid" in messages[0].lower()
    assert not printed, "an unpaid receipt must never reach the printer"
    dlg.close()


def test_print_for_client_prints_a_settled_receipt(qapp, fresh_db, repos,
                                                    entity_factory, monkeypatch):
    receipt_id = _sale(repos, entity_factory, paid=True)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    class _FakePrintDialog:
        def __init__(self, printer, parent=None):
            self.printer = printer

        def exec_(self):
            return 1  # QDialog.Accepted

    class _FakePrinter:
        # A real QPrinter pokes the Windows print/COM stack, which is not
        # initialised under the offscreen test platform.
        HighResolution = 1

        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(receipts_page_mod, "QPrintDialog", _FakePrintDialog)
    monkeypatch.setattr(receipts_page_mod, "QPrinter", _FakePrinter)
    painted = []
    monkeypatch.setattr(
        dlg, "_paint_pixmap_on_printer",
        lambda printer, pix: painted.append(pix),
    )

    dlg._print_for_client()

    assert painted and not painted[0].isNull()
    dlg.close()


def test_status_strip_uses_the_palette_color(qapp, fresh_db, repos, entity_factory):
    """The Paid/Partial/Unpaid strip must be theme-driven, not a fixed hex."""
    from src.ui.themes.color_palettes import get_active_palette

    receipt_id = _sale(repos, entity_factory)  # Unpaid (paid=False)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())

    labels = [l for l in dlg.findChildren(QLabel) if l.text() in ("Paid", "Partial", "Unpaid")]
    assert labels, "a status label should be rendered"
    expected = get_active_palette().qcolor("state_danger").name()
    assert expected in labels[0].styleSheet()
    dlg.close()


def test_ledger_search_falls_back_to_item_name_for_unknown_filter(qapp, fresh_db,
                                                                 repos, entity_factory):
    """An unknown filter string keeps the historical item_name behaviour."""
    import src.core.repositories.sales_repo as _sales
    _sale(repos, entity_factory)
    assert isinstance(_sales.get_receipt_items("Item", "Some Bogus Filter"), list)
