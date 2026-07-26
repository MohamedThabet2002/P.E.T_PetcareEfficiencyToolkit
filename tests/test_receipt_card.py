"""The shared receipt card (src/modules/receipt_card.py).

The Add Visit wizard's step-4 preview must be the very card the Receipt
Details dialog shows - built by one builder, not two - so these tests pin
the preview to the real card: same labels, same rows, same totals. The only
allowed differences are the things a pre-save preview cannot know (its
receipt number) and must not show (payment details - it is the client copy).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib

import pytest
from PyQt5.QtCore import QDateTime, Qt
from PyQt5.QtWidgets import QLabel, QTableWidget

import src.ui.dialogs.base_clinical_dialog as base_clinical_dialog
import src.ui.dialogs.visit_dialogs as visit_dialogs
import src.ui.pages.database_pages.receipts_page as receipts_page
from src.ui.dialogs.full_entry_dialog import AddFullEntryDialog
from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
from src.utils.settings_manager import SettingsManager
from src.config.constants import DEFAULT_CONSULT_FEE


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


@pytest.fixture
def wizard(qapp, fresh_db):
    """A ready-to-use Add Visit dialog on an isolated database.

    A package is seeded because ``_add_package_row`` opens a real (modal)
    information box when none exist, which access-violates pytest offscreen.
    """
    from src.core.repositories import package_repo
    package_repo.add_package("Vaccine Bundle", "Annual shots", 40.0)

    dlg = AddFullEntryDialog(current_user=_admin())
    yield dlg
    dlg.deleteLater()


def _signature(frame, receipt_id=None):
    """The card's content: (class, text) per label plus the item rows.

    ``receipt_id`` strips the receipt-number line - the wizard cannot know
    its number before the visit is saved, and the line is the only content
    a real card has that the preview is allowed to miss.
    """
    labels = []
    for lab in frame.findChildren(QLabel):
        text = lab.text()
        if receipt_id is not None and text.endswith(" #" + str(receipt_id)):
            continue
        labels.append((lab.property("class"), text))
    table = frame.findChild(QTableWidget, "receiptItems")
    rows = [
        [table.item(r, c).text() for c in range(table.columnCount())]
        for r in range(table.rowCount())
    ]
    return labels, rows


def _save_sample_visit(repos, entity_factory, cash_discount):
    """A visit whose receipt carries everything a receipt can carry."""
    fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
    cid = entity_factory["make_client"](name="Mohamed Ali", phone="0100000000")
    pid = entity_factory["make_pet"](cid, name="Rex")
    _, item_name = entity_factory["make_supply"](quantity=10)
    receipt_id = int(repos["visit"].add_visit(
        visit_date="2026-09-07 10:00",
        diagnosis="Checkup",
        consult=True,
        notes="",
        pet_id=pid,
        items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
        discount=cash_discount,
    ))
    return receipt_id, item_name, fee


def test_wizard_preview_is_the_receipt_details_client_card(qapp, fresh_db, repos,
                                                           entity_factory, wizard):
    """Same builder, same inputs -> the preview IS the Receipt Details card."""
    fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
    subtotal = fee + 10.0
    cash = round(subtotal * 0.10, 2)
    receipt_id, item_name, _ = _save_sample_visit(repos, entity_factory, cash)

    real = ReceiptInfoDialog(receipt_id, current_user=_admin())
    real_card = real._build_receipt_card(client=True)

    wizard.v_date.setDateTime(QDateTime(2026, 9, 7, 10, 0))
    wizard.owner_name.setText("Mohamed Ali")
    wizard.phone.setText("0100000000")
    wizard.pet_name.setText("Rex")
    wizard.consult.setChecked(True)
    wizard._add_supply_row()
    cat_cb, item_cb, qty_sb, price_sb = wizard._supply_rows[0]
    cat_cb.setCurrentText("Medicine")
    item_cb.setCurrentText(item_name)
    price_sb.setValue(10.0)
    wizard.discount_percent_spin.setValue(10.0)
    wizard._update_total()

    assert _signature(wizard.receipt_frame) == \
        _signature(real_card, receipt_id=receipt_id)

    real_card.setParent(None)
    real_card.deleteLater()
    real.close()


def test_wizard_card_is_the_client_copy_with_no_payment_details(qapp, fresh_db,
                                                                wizard):
    """The preview shows the thank-you footer, never a payment strip."""
    wizard.owner_name.setText("Noura Salem")
    wizard.phone.setText("0111111111")
    wizard.pet_name.setText("Mishi")
    wizard.consult.setChecked(True)
    wizard._update_total()

    texts = [l.text() for l in wizard.receipt_frame.findChildren(QLabel)]
    assert not any(t in ("Paid", "Partial", "Unpaid") for t in texts)
    assert not any(t.startswith("Paid:") for t in texts)
    assert any("Thank you" in t for t in texts)
    # No receipt number line pre-save: there is no number to print yet.
    assert not any(" #" in t for t in texts)


def test_receipts_page_builds_through_the_shared_builder(monkeypatch, qapp,
                                                         fresh_db, repos,
                                                         entity_factory):
    calls = []
    build = receipts_page.build_receipt_card

    def spy(*args, **kwargs):
        calls.append(kwargs.get("client"))
        return build(*args, **kwargs)

    monkeypatch.setattr(receipts_page, "build_receipt_card", spy)
    receipt_id, _, _ = _save_sample_visit(repos, entity_factory, 0.0)
    dlg = ReceiptInfoDialog(receipt_id, current_user=_admin())
    assert calls, "ReceiptInfoDialog must build its card via the shared builder"
    dlg.close()


def test_wizard_builds_through_the_shared_builder_as_the_client_copy(
        monkeypatch, qapp, fresh_db, wizard):
    calls = []
    build = base_clinical_dialog.build_receipt_card

    def spy(*args, **kwargs):
        calls.append(kwargs.get("client"))
        return build(*args, **kwargs)

    monkeypatch.setattr(base_clinical_dialog, "build_receipt_card", spy)
    wizard.consult.setChecked(True)
    wizard._update_total()
    assert calls, "the wizard preview must go through the shared builder"
    assert set(calls) == {True}


def test_receipt_details_dialog_shares_the_client_card(qapp, fresh_db, repos,
                                                       entity_factory,
                                                       monkeypatch):
    calls = []
    build = visit_dialogs.build_receipt_card

    def spy(*args, **kwargs):
        calls.append(kwargs.get("client"))
        return build(*args, **kwargs)

    monkeypatch.setattr(visit_dialogs, "build_receipt_card", spy)

    receipt_id, _, _ = _save_sample_visit(repos, entity_factory, 0.0)
    dlg = visit_dialogs.ReceiptDetailsDialog(receipt_id, "2026-01-01", "Owner")

    assert calls == [True], "ReceiptDetailsDialog must use the shared card"
    table = dlg.findChild(QTableWidget, "receiptItems")
    assert table is not None
    assert table.rowCount() == 2  # the supply line + the consultation line
    texts = [l.text() for l in dlg.findChildren(QLabel)]
    assert any("Thank you" in t for t in texts)
    assert not any(t in ("Paid", "Partial", "Unpaid") for t in texts)
    dlg.close()


def _content_height(table):
    """The exact height the item rows + header need (wrapped text included)."""
    return table.horizontalHeader().sizeHint().height() + sum(
        max(table.sizeHintForRow(r), table.rowHeight(r))
        for r in range(table.rowCount())
    )


def _long_card():
    from src.modules.receipt_card import build_receipt_card

    items = [{"name": "Item %d" % i, "quantity": 1, "unit_price": 10.0}
             for i in range(25)]
    return build_receipt_card(
        {"receipt_code": "VISIT-1", "receipt_date": "2026-01-01",
         "receipt_kind": "visit", "owner_name": "Owner", "pet_name": "Pet"},
        items, 0.0, 250.0, receipt_id=1, client=True,
    )


def test_receipt_items_table_is_pinned_and_never_scrolls(qapp):
    """A long receipt shows every line without an internal scrollbar."""
    card = _long_card()
    table = card.table
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert table.verticalScrollBar().maximum() == 0
    assert table.height() >= _content_height(table)
    # The card itself is tall enough to hold the pinned table - no clipping.
    assert card.frame.sizeHint().height() >= table.y() + table.height()


def test_client_print_grab_keeps_every_receipt_row(qapp):
    """What Print grabs reaches past the items table, so no row is cut off."""
    card = _long_card()
    frame = card.frame
    frame.layout().activate()
    frame.adjustSize()
    pix = frame.grab()
    assert pix.height() >= card.table.y() + card.table.height()


def test_wizard_receipt_never_scrolls_with_many_supplies(qapp, fresh_db,
                                                         entity_factory, wizard):
    """The step-4 preview hands its overflow to the page, not the card."""
    _, item_name = entity_factory["make_supply"](quantity=100)
    for _ in range(20):
        wizard._add_supply_row()
    for cat_cb, item_cb, qty_sb, price_sb in wizard._supply_rows:
        cat_cb.setCurrentText("Medicine")
        item_cb.setCurrentText(item_name)
        price_sb.setValue(10.0)
    wizard._update_total()

    table = wizard.receipt_items_table
    assert table.rowCount() == 20
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert table.verticalScrollBar().maximum() == 0
    assert table.height() >= _content_height(table)


def test_billing_step_never_paints_a_clipped_receipt(qapp, fresh_db,
                                                     entity_factory, wizard):
    """A long receipt is full height the instant its step is shown.

    Qt used to hand the surrounding scroll area the previous step's extent, so
    the card was momentarily squeezed to the old (short) height - painted
    clipped, with no scrollbar to reach the rest - until some later relayout.
    Switching steps must re-pin the scroll extent first, otherwise the user
    sees a receipt missing its lower lines.
    """
    wizard.show()
    qapp.processEvents()

    _, item_name = entity_factory["make_supply"](quantity=1000)
    for _ in range(40):
        wizard._add_supply_row()
    for cat_cb, item_cb, qty_sb, price_sb in wizard._supply_rows:
        cat_cb.setCurrentText("Medicine")
        item_cb.setCurrentText(item_name)
        price_sb.setValue(10.0)
    wizard._max_step = 3
    wizard._update_total()

    # Deliberately no processEvents(): the fix must not wait for a relayout.
    wizard._go_to_step(3)
    frame = wizard.receipt_frame
    assert frame.height() >= frame.minimumSizeHint().height()
    assert wizard.left_scroll.verticalScrollBar().maximum() > 0
    wizard.close()


def test_receipt_rows_are_repinned_to_their_real_height(qapp, fresh_db,
                                                        entity_factory, wizard):
    """A too-short table height (stale pre-layout estimate) is repaired.

    The row-height estimate used when a receipt is built can come out short
    once the card sits at its real, narrower width: the wrapped lines then
    need more room than the fixed height gives, and the last rows are clipped
    *inside* the table - no scrollbar (always off), reachable only by the
    mouse wheel (their hidden scrollbar answers it). When the billing step
    becomes current the table must be re-pinned to the header's true section
    heights, so every row fits again.
    """
    wizard.show()
    qapp.processEvents()
    _, item_name = entity_factory["make_supply"](quantity=1000)
    for _ in range(20):
        wizard._add_supply_row()
    for cat_cb, item_cb, qty_sb, price_sb in wizard._supply_rows:
        cat_cb.setCurrentText("Medicine")
        item_cb.setCurrentText(item_name)
        price_sb.setValue(10.0)
    wizard._max_step = 3
    wizard._update_total()

    table = wizard.receipt_items_table
    table.setFixedHeight(120)  # the old, too-small estimate
    wizard._go_to_step(3)

    real_content = sum(table.verticalHeader().sectionSize(r)
                       for r in range(table.rowCount()))
    assert table.height() >= table.horizontalHeader().height() + real_content
    last = table.item(table.rowCount() - 1, 0)
    assert table.visualItemRect(last).bottom() <= table.viewport().height()
    wizard.close()


def test_no_module_hand_rolls_a_receipt_card():
    """Every receipt surface renders through src/modules/receipt_card.py.

    The frame class, the items table and the client footer are what make all
    receipts share one shape - if a new dialog draws them by hand it would
    silently miss the next style change or feature, so this test keeps the
    wiring honest.
    """
    markers = (
        'setProperty("class", "receipt")',
        'setObjectName("receiptItems")',
        'tr("RECEIPT")',
        "Thank you for visiting us",
    )
    src_root = pathlib.Path(__file__).resolve().parents[1] / "src"
    violations = [
        "{}: {}".format(path.relative_to(src_root), marker)
        for path in sorted(src_root.rglob("*.py"))
        if path.name != "receipt_card.py"
        for marker in markers
        if marker in path.read_text(encoding="utf-8")
    ]
    assert not violations, (
        "build receipts through src/modules/receipt_card.py:\n"
        + "\n".join(violations)
    )
