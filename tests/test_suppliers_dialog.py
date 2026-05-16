"""Tests for the SuppliersDialog (supplier CRUD opened from the Supplies page)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from src.ui.dialogs import suppliers_dialog as suppliers_dialog_module
from src.ui.dialogs.suppliers_dialog import SuppliersDialog


def test_dialog_lists_repo_rows(qapp, fresh_db, repos):
    repos["supplier"].add_supplier("Vet Supply Co")

    dialog = SuppliersDialog()

    assert dialog.supplier_list.count() == 1
    item = dialog.supplier_list.item(0)
    assert item.text().startswith("Vet Supply Co (ID: ")
    assert item.data(Qt.UserRole) is not None


def test_dialog_refresh_picks_up_suppliers_added_elsewhere(qapp, fresh_db, repos):
    """Suppliers created by the inventory dialogs appear on the next open."""
    dialog = SuppliersDialog()
    assert dialog.supplier_list.count() == 0

    repos["supplier"].add_supplier("Cairo Animal Care")
    assert dialog.supplier_list.count() == 0  # stale until refreshed

    dialog.refresh_suppliers()
    assert dialog.supplier_list.count() == 1
    assert dialog.supplier_list.item(0).text().startswith("Cairo Animal Care (ID: ")


def test_supplier_add_edit_delete_use_the_repo(qapp, fresh_db, repos, monkeypatch):
    supplier_repo = repos["supplier"]
    dialog = SuppliersDialog()
    assert dialog.supplier_list.count() == 0

    # --- add ---
    monkeypatch.setattr(dialog, "_prompt_supplier",
                        lambda *a, **k: {"name": "Acme", "phone": "0100",
                                         "location": "Cairo", "notes": "VIP"})
    dialog.add_supplier()
    added = supplier_repo.get_suppliers()
    assert [s["supplier_name"] for s in added] == ["Acme"]
    assert added[0]["phone"] == "0100"
    assert added[0]["location"] == "Cairo"
    assert added[0]["notes"] == "VIP"
    assert dialog.supplier_list.count() == 1

    # --- edit ---
    dialog.supplier_list.setCurrentRow(0)
    monkeypatch.setattr(dialog, "_prompt_supplier",
                        lambda *a, **k: {"name": "Acme Plus", "phone": "",
                                         "location": "Giza", "notes": ""})
    dialog.edit_supplier()
    edited = supplier_repo.get_suppliers()
    assert [s["supplier_name"] for s in edited] == ["Acme Plus"]
    assert edited[0]["phone"] == ""
    assert edited[0]["location"] == "Giza"
    assert edited[0]["notes"] == ""

    # --- delete (confirmed) ---
    dialog.supplier_list.setCurrentRow(0)
    monkeypatch.setattr(suppliers_dialog_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    dialog.delete_supplier()
    assert supplier_repo.get_suppliers() == []
    assert dialog.supplier_list.count() == 0


def test_delete_is_abandoned_when_declined(qapp, fresh_db, repos, monkeypatch):
    supplier_repo = repos["supplier"]
    supplier_repo.add_supplier("Acme")

    dialog = SuppliersDialog()
    dialog.supplier_list.setCurrentRow(0)
    monkeypatch.setattr(suppliers_dialog_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.No)
    dialog.delete_supplier()

    assert [s["supplier_name"] for s in supplier_repo.get_suppliers()] == ["Acme"]


def test_supplier_actions_need_a_selection(qapp, fresh_db, repos, monkeypatch):
    shown = []
    monkeypatch.setattr(suppliers_dialog_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2]))

    dialog = SuppliersDialog()
    dialog.edit_supplier()
    dialog.delete_supplier()

    assert shown == ["Please select a supplier to edit.",
                     "Please select a supplier to delete."]


def test_empty_state_label_tracks_the_list(qapp, fresh_db, repos):
    dialog = SuppliersDialog()
    assert dialog._empty_label.isVisibleTo(dialog) is True

    repos["supplier"].add_supplier("Acme")
    dialog.refresh_suppliers()
    assert dialog._empty_label.isVisibleTo(dialog) is False


def test_supplies_page_opens_the_dialog_from_its_corner_button(qapp, fresh_db, repos, monkeypatch):
    """The corner ``Suppliers`` button on the Supplies page opens the dialog."""
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    page = SuppliesPage()
    page.set_current_user({"user_id": 1, "username": "admin", "roles": ["admin"]})
    assert page.suppliers_btn.text() == " Suppliers "

    opened = {}
    monkeypatch.setattr(
        "src.ui.dialogs.suppliers_dialog.SuppliersDialog.exec_",
        lambda self: opened.setdefault("parent", self.parent()),
    )
    page._open_suppliers_dialog()

    assert opened == {"parent": page}


def test_suppliers_button_follows_the_supplies_permission(qapp, fresh_db, repos):
    """Staff without ``add_supplies`` cannot manage suppliers."""
    from src.ui.pages.database_pages.supplies_page import SuppliesPage

    page = SuppliesPage()
    page.set_current_user({"user_id": 2, "username": "staff", "roles": ["staff"]})

    assert page.suppliers_btn.isHidden() is True