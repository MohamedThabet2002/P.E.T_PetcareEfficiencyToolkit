"""
Suppliers dialog for the PET Application.

Full supplier CRUD (add / rename / delete) with contact details (phone,
location, notes), moved out of the Settings page and then out of the Admin
page. It is now opened from the Supplies page corner buttons, next to Packages
and Reorder Overview.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFormLayout, QLineEdit, QPlainTextEdit, QDialogButtonBox,
    QMessageBox,
)

import src.core.repositories.supplier_repo as supplier_repo
from src.utils.i18n import tr


class _SupplierFormDialog(QDialog):
    """Small form used to add or edit a supplier and its contact details."""

    def __init__(self, parent=None, data=None, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or tr("Suppliers"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(70)

        form.addRow(tr("Supplier Name:"), self.name_edit)
        form.addRow(tr("Phone:"), self.phone_edit)
        form.addRow(tr("Location:"), self.location_edit)
        form.addRow(tr("Notes:"), self.notes_edit)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if data:
            self.name_edit.setText(data.get("supplier_name") or "")
            self.phone_edit.setText(data.get("phone") or "")
            self.location_edit.setText(data.get("location") or "")
            self.notes_edit.setPlainText(data.get("notes") or "")

    def values(self):
        """Returns the entered fields as stripped strings (empty = cleared)."""
        return {
            "name": self.name_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "location": self.location_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }


class SuppliersDialog(QDialog):
    """Lists the clinic's suppliers and lets the user add / edit / delete them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Suppliers"))
        self.setMinimumSize(480, 420)
        self._setup_ui()
        self.refresh_suppliers()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self._title = QLabel(tr("Suppliers"))
        self._title.setProperty("class", "dialog-title")
        layout.addWidget(self._title)

        self.supplier_list = QListWidget()
        layout.addWidget(self.supplier_list, 1)

        self._empty_label = QLabel(tr("No suppliers yet."))
        self._empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty_label)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton(tr("+ Supplier"))
        self.add_btn.clicked.connect(self.add_supplier)
        self.edit_btn = QPushButton(tr("Edit"))
        self.edit_btn.clicked.connect(self.edit_supplier)
        self.delete_btn = QPushButton(tr("- Supplier"))
        self.delete_btn.clicked.connect(self.delete_supplier)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------ Suppliers --

    def refresh_suppliers(self):
        """Reloads the supplier list from the repository."""
        self.supplier_list.clear()
        for supplier in supplier_repo.get_suppliers():
            text = f"{supplier['supplier_name']} (ID: {supplier['supplier_id']})"
            contact = "  ·  ".join(
                value for value in (supplier.get("phone"), supplier.get("location"))
                if value
            )
            if contact:
                text += f"  —  {contact}"
            if supplier.get("notes"):
                text += f"\n{tr('Notes:')} {supplier['notes']}"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, supplier["supplier_id"])
            tooltip = "\n".join(
                value for value in (
                    supplier.get("supplier_name"),
                    supplier.get("phone"),
                    supplier.get("location"),
                    supplier.get("notes"),
                ) if value
            )
            item.setToolTip(tooltip)
            self.supplier_list.addItem(item)
        self._empty_label.setVisible(self.supplier_list.count() == 0)

    def _prompt_supplier(self, title, data=None):
        """Opens the supplier form; returns the entered values or None."""
        dialog = _SupplierFormDialog(self, data=data, title=title)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.values()
        return None

    def add_supplier(self):
        """Prompts for supplier details and adds a new supplier."""
        values = self._prompt_supplier(tr("New Supplier"))
        if not values or not values["name"]:
            return
        added = supplier_repo.add_supplier(
            values["name"],
            values["phone"] or None,
            values["location"] or None,
            values["notes"] or None,
        )
        if added is not None:
            self.refresh_suppliers()
        else:
            QMessageBox.warning(self, tr("Suppliers"), tr("Failed to add supplier."))

    def edit_supplier(self):
        """Edits the selected supplier's details."""
        item = self.supplier_list.currentItem()
        if item is None:
            QMessageBox.information(self, tr("Suppliers"), tr("Please select a supplier to edit."))
            return
        supplier_id = item.data(Qt.UserRole)
        current = supplier_repo.get_supplier(supplier_id) or {}
        values = self._prompt_supplier(tr("Edit Supplier"), data=current)
        if not values or not values["name"]:
            return
        if supplier_repo.update_supplier(
            supplier_id,
            values["name"],
            values["phone"],
            values["location"],
            values["notes"],
        ):
            self.refresh_suppliers()
        else:
            QMessageBox.warning(self, tr("Suppliers"), tr("Failed to update supplier."))

    def delete_supplier(self):
        """Deletes the selected supplier after a confirmation prompt."""
        item = self.supplier_list.currentItem()
        if item is None:
            QMessageBox.information(self, tr("Suppliers"), tr("Please select a supplier to delete."))
            return
        supplier_id = item.data(Qt.UserRole)
        supplier_name = item.text().split(" (ID:")[0]
        reply = QMessageBox.question(self, tr("Delete Supplier"),
                                     tr("Delete supplier '{name}'?").format(name=supplier_name),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if supplier_repo.delete_supplier(supplier_id):
                self.refresh_suppliers()
            else:
                QMessageBox.warning(self, tr("Suppliers"), tr("Failed to delete supplier."))
