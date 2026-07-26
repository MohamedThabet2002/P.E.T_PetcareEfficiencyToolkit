"""Tests for the PackageDialog (package CRUD + bundled item management)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QHeaderView, QLabel, QMessageBox
)

from src.ui.dialogs import package_dialog as package_dialog_module
from src.ui.dialogs.package_dialog import PackageDialog, _PackageItemDialog


@pytest.fixture(autouse=True)
def _no_modal_boxes(monkeypatch):
    """Keeps any dialog-level message box from blocking the offscreen run."""
    monkeypatch.setattr(package_dialog_module.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(package_dialog_module.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(package_dialog_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)


def _stub_item_dialog(monkeypatch, data):
    """Replaces the item picker so no modal exec() runs, returning fixed data."""

    class _Stub:
        def __init__(self, package_id, parent=None):
            self.package_id = package_id

        def exec(self):
            return QDialog.Accepted

        def get_data(self):
            return dict(data)

    monkeypatch.setattr(package_dialog_module, "_PackageItemDialog", _Stub)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def test_package_title_is_above_the_table_and_buttons_below(qapp, fresh_db):
    dialog = PackageDialog()

    top_frame = dialog.layout().itemAt(0).widget()
    top_layout = top_frame.layout()

    title = top_layout.itemAt(0).widget()
    assert isinstance(title, QLabel)
    assert "Package Details" in title.text()

    # Table comes second, the CRUD button row last.
    assert top_layout.itemAt(1).widget() is dialog.package_table
    button_row = top_layout.itemAt(2).layout()
    assert button_row.itemAt(0).widget() is dialog.add_btn
    assert button_row.itemAt(1).widget() is dialog.edit_btn
    assert button_row.itemAt(2).widget() is dialog.delete_btn


def test_item_buttons_sit_below_the_items_table(qapp, fresh_db):
    dialog = PackageDialog()

    bottom_frame = dialog.layout().itemAt(1).widget()
    bottom_layout = bottom_frame.layout()

    assert bottom_layout.itemAt(1).widget() is dialog.items_table
    button_row = bottom_layout.itemAt(2).layout()
    assert button_row.itemAt(0).widget() is dialog.add_item_btn
    assert button_row.itemAt(1).widget() is dialog.remove_item_btn


def test_columns_are_sized_to_their_headers(qapp, fresh_db):
    dialog = PackageDialog()

    for table in (dialog.package_table, dialog.items_table):
        header = table.horizontalHeader()
        metrics = QFontMetrics(table.font())
        last = table.columnCount() - 1
        for column in range(last):
            if table.isColumnHidden(column):
                continue
            assert header.sectionResizeMode(column) == QHeaderView.ResizeToContents
            label = table.horizontalHeaderItem(column).text()
            assert table.columnWidth(column) >= metrics.horizontalAdvance(label)
        assert header.minimumSectionSize() >= 100
        # The last column is sized by hand so it can stretch *and* overflow.
        assert header.sectionResizeMode(last) == QHeaderView.Interactive


def test_last_column_stretches_to_fill_the_table(qapp, fresh_db, repos, entity_factory):
    entity_factory["make_supply"](name="Amox", category="Medicine")
    repos["package"].add_package("Pack", "Short note", 50.0)
    package_id = repos["package"].get_all_packages()[0]["package_id"]
    repos["package"].add_package_item(
        int(package_id), supply_id=repos["supply"].resolve_supply_id("Amox", "Medicine"),
        quantity=1)

    dialog = PackageDialog()
    dialog.resize(1100, 500)
    dialog.show()
    dialog.package_table.setCurrentCell(0, 1)
    qapp.processEvents()

    for table in (dialog.package_table, dialog.items_table):
        last = table.columnCount() - 1
        others = sum(table.columnWidth(c) for c in range(last)
                     if not table.isColumnHidden(c))
        assert table.columnWidth(last) >= table.viewport().width() - others

    # A short description leaves nothing to read beyond the edge.
    assert not dialog.package_table.horizontalScrollBar().isVisible()
    assert dialog.package_table.horizontalScrollBar().maximum() == 0


def test_last_column_follows_a_dialog_resize(qapp, fresh_db, repos):
    repos["package"].add_package("Pack", "Short note", 50.0)

    dialog = PackageDialog()
    dialog.resize(1100, 500)
    dialog.show()
    qapp.processEvents()
    wide = dialog.package_table.columnWidth(3)

    dialog.resize(760, 500)
    qapp.processEvents()

    assert dialog.package_table.columnWidth(3) < wide
    assert dialog.package_table.columnWidth(3) + \
        sum(dialog.package_table.columnWidth(c) for c in (1, 2)) \
        >= dialog.package_table.viewport().width()


def test_both_tables_can_scroll_horizontally(qapp, fresh_db, repos, entity_factory):
    long_name = "Extended Spectrum Injectable Antibiotic Suspension 100ml"
    entity_factory["make_supply"](name=long_name, category="Medicine")
    supply_id = repos["supply"].resolve_supply_id(long_name, "Medicine")
    repos["package"].add_package(
        "Vaccine Pack",
        "A long description that is wider than the dialog itself so the horizontal "
        "scrollbar has to reveal the rest of it.",
        50.0,
    )
    package_id = repos["package"].get_all_packages()[0]["package_id"]
    repos["package"].add_package_item(int(package_id), supply_id=supply_id, quantity=1)

    dialog = PackageDialog()
    dialog.resize(700, 500)
    dialog.show()
    dialog.package_table.setCurrentCell(0, 1)  # loads the bundled items
    qapp.processEvents()

    for table in (dialog.package_table, dialog.items_table):
        assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
        # Content is wider than the viewport, so a scrollbar is needed on both.
        assert sum(table.columnWidth(c) for c in range(table.columnCount()) if not table.isColumnHidden(c)) \
            > table.viewport().width()
        assert table.horizontalScrollBar().isVisible()
        assert table.horizontalScrollBar().maximum() > 0

        scrollbar = table.horizontalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        qapp.processEvents()
        assert scrollbar.value() > 0


def test_description_is_the_last_package_column(qapp, fresh_db, repos):
    repos["package"].add_package("Vaccine Pack", "Shots for the whole litter", 50.0)
    dialog = PackageDialog()

    headers = [dialog.package_table.horizontalHeaderItem(i).text()
               for i in range(dialog.package_table.columnCount())]
    assert headers == ["Package ID", "Package Name", "Total Price ($)", "Description"]

    assert dialog.package_table.item(0, 3).text() == "Shots for the whole litter"
    assert dialog.package_table.item(0, 3).toolTip() == "Shots for the whole litter"


def test_blank_description_does_not_break_the_row(qapp, fresh_db, repos):
    repos["package"].add_package("No Notes Pack", "", 10.0)
    dialog = PackageDialog()

    assert dialog.package_table.rowCount() == 1
    assert dialog.package_table.item(0, 3).text() == ""


def test_edit_prefills_the_existing_description(qapp, fresh_db, repos, monkeypatch):
    package_id = repos["package"].add_package("Vaccine Pack", "Keep me", 50.0)
    captured = {}

    class _Stub:
        def __init__(self, parent=None, pkg_id=None, name="", description="", price=0.0):
            captured["description"] = description
            captured["name"] = name

        def exec(self):
            return QDialog.Accepted

        def get_data(self):
            return {"name": "Vaccine Pack", "description": "Keep me", "total_price": 50.0}

    monkeypatch.setattr(package_dialog_module, "_PackageEditDialog", _Stub)

    dialog = PackageDialog()
    dialog.package_table.setCurrentCell(0, 1)
    dialog._edit_package()

    assert captured["name"] == "Vaccine Pack"
    assert captured["description"] == "Keep me"
    assert repos["package"].get_all_packages()[0]["description"] == "Keep me"


def test_actions_column_becomes_a_details_column(qapp, fresh_db):
    dialog = PackageDialog()

    headers = [dialog.items_table.horizontalHeaderItem(i).text()
               for i in range(dialog.items_table.columnCount())]
    assert headers == ["Item Type", "Item Name", "Quantity", "Details"]


# ---------------------------------------------------------------------------
# Details column content
# ---------------------------------------------------------------------------
def test_details_column_shows_prices(qapp, fresh_db, repos, entity_factory):
    _, item_name = entity_factory["make_supply"](
        name="Amox", category="Medicine", buy_price=3.5, sell_price=8.25
    )
    package_id = repos["package"].add_package("Vaccine Pack", "", 50.0)
    supply_id = repos["supply"].resolve_supply_id("Amox", "Medicine")
    repos["package"].add_package_item(int(package_id), supply_id=supply_id, quantity=2)

    dialog = PackageDialog()
    dialog.package_table.setCurrentCell(0, 1)

    assert dialog.items_table.rowCount() == 1
    details = dialog.items_table.item(0, 3).text()
    assert "3.50" in details and "8.25" in details
    assert item_name in dialog.items_table.item(0, 1).text()


def test_details_column_falls_back_for_services(qapp, fresh_db, repos):
    package_id = repos["package"].add_package("Consult Pack", "", 30.0)
    service_id = repos["supply"].get_all_services()
    assert service_id
    from src.core.repositories import lookup_repo
    resolved = lookup_repo.get_service_id(service_id[0])
    repos["package"].add_package_item(int(package_id), service_id=resolved, quantity=1)

    dialog = PackageDialog()
    dialog.package_table.setCurrentCell(0, 1)

    assert dialog.items_table.rowCount() == 1
    assert dialog.items_table.item(0, 3).text()


# ---------------------------------------------------------------------------
# Item buttons
# ---------------------------------------------------------------------------
def test_add_item_button_persists_the_row(qapp, fresh_db, repos, entity_factory, monkeypatch):
    package_id = repos["package"].add_package("Health Pack", "", 40.0)
    _, item_name = entity_factory["make_supply"](name="Vitamin")
    supply_id = repos["supply"].resolve_supply_id("Vitamin")
    _stub_item_dialog(monkeypatch, {
        "item_type": "supply", "service_id": None,
        "supply_id": supply_id, "quantity": 3,
    })

    dialog = PackageDialog()
    assert dialog.add_item_btn.isEnabled() is False  # no package selected yet

    dialog.package_table.setCurrentCell(0, 1)
    assert dialog.add_item_btn.isEnabled() is True

    dialog._add_item()

    rows = repos["package"].get_package_items(int(package_id))
    assert len(rows) == 1
    assert rows[0]["supply_id"] == supply_id
    assert rows[0]["quantity"] == 3
    assert dialog.items_table.rowCount() == 1


def test_remove_item_button_follows_the_selection(qapp, fresh_db, repos, entity_factory):
    package_id = repos["package"].add_package("Health Pack", "", 40.0)
    _, item_name = entity_factory["make_supply"](name="Vitamin")
    supply_id = repos["supply"].resolve_supply_id("Vitamin")
    repos["package"].add_package_item(int(package_id), supply_id=supply_id, quantity=1)

    dialog = PackageDialog()
    dialog.package_table.setCurrentCell(0, 1)
    assert dialog.items_table.rowCount() == 1
    assert dialog.remove_item_btn.isEnabled() is False

    dialog.items_table.setCurrentCell(0, 1)
    assert dialog.remove_item_btn.isEnabled() is True

    dialog._remove_item()

    assert repos["package"].get_package_items(int(package_id)) == []
    assert dialog.items_table.rowCount() == 0
    assert dialog.remove_item_btn.isEnabled() is False


def test_item_picker_resolves_supply_ids_from_its_payload(qapp, fresh_db, entity_factory):
    """The combo shows 'Item (Category)'; the id must still resolve."""
    entity_factory["make_supply"](name="Amox", category="Medicine")
    dialog = _PackageItemDialog(1)
    dialog.type_combo.setCurrentIndex(1)
    index = dialog.item_combo.findText("Amox (Medicine)")
    assert index >= 0
    dialog.item_combo.setCurrentIndex(index)

    data = dialog.get_data()
    assert data["item_type"] == "supply"
    assert data["supply_id"] is not None
    assert data["quantity"] == 1


def test_item_picker_rejects_an_unresolvable_name(qapp, fresh_db, entity_factory):
    entity_factory["make_supply"](name="Amox", category="Medicine")
    dialog = _PackageItemDialog(1)
    dialog.type_combo.setCurrentIndex(1)
    dialog.item_combo.setCurrentIndex(-1)
    dialog.item_combo.setEditText("Does Not Exist")

    assert dialog.get_data() is None