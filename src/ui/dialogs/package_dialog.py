"""
Package Dialog for the PET Application.
Allows CRUD operations on service packages that bundle services and supplies.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QSpinBox, QMessageBox, QHeaderView, QAbstractItemView,
    QGroupBox, QSplitter, QDialogButtonBox, QWidget, QFrame
)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon

import src.core.repositories.package_repo as package_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.lookup_repo as lookup_repo
from src.utils.i18n import tr


class PackageDialog(QDialog):
    """
    Dialog for managing service packages.
    Allows creating, editing, and viewing packages with their bundled items.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Service Packages Management"))
        self.setMinimumSize(780, 560)
        self._current_package_id = None
        self._packages_by_id = {}
        self._setup_ui()
        self._load_packages()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Top: Package list (title, table, then the CRUD buttons below it)
        top_frame = QFrame()
        top_layout = QVBoxLayout(top_frame)
        top_layout.setContentsMargins(0, 0, 0, 0)

        top_layout.addWidget(QLabel(f"<b>{tr('Package Details')}</b>"))

        # Package table
        self.package_table = QTableWidget()
        self.package_table.setColumnCount(4)
        self.package_table.setHorizontalHeaderLabels([
            tr("Package ID"), tr("Package Name"), tr("Total Price ($)"), tr("Description")
        ])
        self.package_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.package_table.setSelectionMode(QTableWidget.SingleSelection)
        self.package_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.package_table.hideColumn(0)
        self._configure_columns(self.package_table)
        self.package_table.itemSelectionChanged.connect(self._on_package_selected)
        top_layout.addWidget(self.package_table)

        # CRUD buttons row (below the table)
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton(tr("+ New Package"))
        self.add_btn.clicked.connect(self._add_package)
        self.edit_btn = QPushButton(tr("Edit Package"))
        self.edit_btn.clicked.connect(self._edit_package)
        self.delete_btn = QPushButton(tr("Delete Package"))
        self.delete_btn.clicked.connect(self._delete_package)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        top_layout.addLayout(btn_layout)

        main_layout.addWidget(top_frame)

        # Bottom: Package items table
        bottom_frame = QFrame()
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        items_header = QLabel(f"<b>{tr('Package Items')}</b>")
        bottom_layout.addWidget(items_header)

        self.items_table = QTableWidget()
        self.items_table.setColumnCount(4)
        self.items_table.setHorizontalHeaderLabels([
            tr("Item Type"), tr("Item Name"), tr("Quantity"), tr("Details")
        ])
        self.items_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.items_table.setSelectionMode(QTableWidget.SingleSelection)
        self.items_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._configure_columns(self.items_table)
        self.items_table.itemSelectionChanged.connect(self._on_item_selected)
        bottom_layout.addWidget(self.items_table)

        # Item CRUD buttons (below the table)
        item_btn_layout = QHBoxLayout()
        self.add_item_btn = QPushButton(tr("+ Add Item"))
        self.add_item_btn.clicked.connect(self._add_item)
        self.add_item_btn.setEnabled(False)
        self.remove_item_btn = QPushButton(tr("Remove Selected Item"))
        self.remove_item_btn.clicked.connect(self._remove_item)
        self.remove_item_btn.setEnabled(False)
        item_btn_layout.addWidget(self.add_item_btn)
        item_btn_layout.addWidget(self.remove_item_btn)
        item_btn_layout.addStretch()
        bottom_layout.addLayout(item_btn_layout)

        main_layout.addWidget(bottom_frame)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        main_layout.addLayout(close_layout)

    @staticmethod
    def _configure_columns(table):
        """Auto-sizes every column to its content; the last one is sized by hand."""
        header = table.horizontalHeader()
        last = table.columnCount() - 1
        for column in range(table.columnCount()):
            # Stretch-last-section alone would clamp a long description to the viewport,
            # so the final column is sized manually instead (see _fit_last_column).
            header.setSectionResizeMode(
                column,
                QHeaderView.Interactive if column == last else QHeaderView.ResizeToContents,
            )
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(100)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def _fit_last_column(self):
        """Stretches the final column to fill the table, but never below its content."""
        for table in (getattr(self, "package_table", None), getattr(self, "items_table", None)):
            if table is None:
                continue
            last = table.columnCount() - 1
            others = sum(table.columnWidth(c) for c in range(last)
                         if not table.isColumnHidden(c))
            target = max(table.sizeHintForColumn(last), table.viewport().width() - others)
            if target > 0:
                table.horizontalHeader().resizeSection(last, target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The tables are re-laid-out after this event, so refit once the new geometry
        # has actually reached them.
        QTimer.singleShot(0, self._fit_last_column)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_last_column)

    def _load_packages(self):
        """Loads all packages into the table."""
        packages = package_repo.get_all_packages()
        self.package_table.setRowCount(0)
        self._packages_by_id = {}

        for pkg in packages:
            row = self.package_table.rowCount()
            self.package_table.insertRow(row)
            self.package_table.setItem(row, 0, QTableWidgetItem(str(pkg["package_id"])))
            self.package_table.setItem(row, 1, QTableWidgetItem(pkg["package_name"]))
            price_item = QTableWidgetItem()
            price_item.setData(Qt.DisplayRole, pkg["total_price"])
            self.package_table.setItem(row, 2, price_item)
            description_item = QTableWidgetItem(pkg["description"] or "")
            description_item.setToolTip(pkg["description"] or "")
            self.package_table.setItem(row, 3, description_item)
            self._packages_by_id[pkg["package_id"]] = pkg

        self._fit_last_column()

    def _on_package_selected(self):
        """Loads items for the selected package."""
        row = self.package_table.currentRow()
        if row < 0:
            self.items_table.setRowCount(0)
            self.add_item_btn.setEnabled(False)
            self.remove_item_btn.setEnabled(False)
            return

        package_id = int(self.package_table.item(row, 0).text())
        self._current_package_id = package_id
        self.add_item_btn.setEnabled(True)
        self._load_package_items(package_id)

    def _load_package_items(self, package_id):
        """Loads items for a specific package."""
        items = package_repo.get_package_items(package_id)
        self.items_table.setRowCount(0)

        for item in items:
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)

            item_type = item["item_type"]
            item_name = item.get("service_name") or item.get("item_name") or tr("Unknown")
            quantity = item["quantity"]

            type_item = QTableWidgetItem(item_type.capitalize())
            # The package_item_id rides along in the type cell, it is not displayed.
            type_item.setData(Qt.UserRole, item["package_item_id"])
            self.items_table.setItem(row, 0, type_item)
            self.items_table.setItem(row, 1, QTableWidgetItem(item_name))
            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.DisplayRole, quantity)
            self.items_table.setItem(row, 2, qty_item)
            self.items_table.setItem(row, 3, QTableWidgetItem(self._item_details_text(item)))

        self.remove_item_btn.setEnabled(False)
        self._fit_last_column()

    @staticmethod
    def _item_details_text(item):
        """Builds the 'Details' cell text for a bundled item (prices)."""
        if item["item_type"] == "service":
            price = item.get("base_price")
            if price is None:
                return tr("Service")
            return f"{tr('Price')}: $ {float(price):,.2f}"

        parts = []
        for label, value in ((tr("Buy Price"), item.get("buy_price")),
                             (tr("Sell Price"), item.get("sell_price"))):
            if value is not None:
                parts.append(f"{label}: $ {float(value):,.2f}")
        if item.get("category"):
            parts.append(f"{tr('Category')}: {item['category']}")
        return "  |  ".join(parts) if parts else tr("Supply")

    def _on_item_selected(self):
        """Enables 'Remove Selected Item' only when an item row is selected."""
        self.remove_item_btn.setEnabled(
            self.items_table.currentRow() >= 0
            and self.items_table.item(self.items_table.currentRow(), 0) is not None
        )

    def _add_package(self):
        """Opens dialog to create a new package."""
        dialog = _PackageEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            pkg_id = package_repo.add_package(data["name"], data["description"], data["total_price"])
            if pkg_id:
                self._load_packages()
                QMessageBox.information(self, tr("Success"), tr("Package '{name}' created.").format(name=data["name"]))
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to create package."))

    def _edit_package(self):
        """Opens dialog to edit the selected package."""
        row = self.package_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a package to edit."))
            return

        package_id = int(self.package_table.item(row, 0).text())
        package_name = self.package_table.item(row, 1).text()
        total_price = float(self.package_table.item(row, 2).text() or 0)
        description = self._packages_by_id.get(package_id, {}).get("description") or ""

        dialog = _PackageEditDialog(self, package_id, package_name, description, total_price)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if package_repo.update_package(package_id, data["name"], data["description"], data["total_price"]):
                self._load_packages()
                QMessageBox.information(self, tr("Success"), tr("Package updated."))
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to update package."))

    def _delete_package(self):
        """Deletes the selected package after confirmation."""
        row = self.package_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a package to delete."))
            return

        package_id = int(self.package_table.item(row, 0).text())
        package_name = self.package_table.item(row, 1).text()

        reply = QMessageBox.question(
            self, tr("Confirm Delete"),
            tr("Delete package '{name}' and all its items?").format(name=package_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if package_repo.delete_package(package_id):
                self._current_package_id = None
                self.items_table.setRowCount(0)
                self.add_item_btn.setEnabled(False)
                self.remove_item_btn.setEnabled(False)
                self._load_packages()
                QMessageBox.information(self, tr("Success"), tr("Package deleted."))
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to delete package."))

    def _add_item(self):
        """Opens dialog to add an item to the selected package."""
        if not self._current_package_id:
            QMessageBox.information(
                self, tr("Selection Required"), tr("Please select a package first.")
            )
            return

        dialog = _PackageItemDialog(self._current_package_id, self)
        if dialog.exec() != QDialog.Accepted:
            return

        data = dialog.get_data()
        if not data:
            QMessageBox.critical(self, tr("Error"), tr("Failed to add item to package."))
            return

        package_item_id = package_repo.add_package_item(
            self._current_package_id,
            service_id=data["service_id"],
            supply_id=data["supply_id"],
            quantity=data["quantity"],
            item_type=data["item_type"],
        )
        if package_item_id:
            self._load_package_items(self._current_package_id)
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to add item to package."))

    def _remove_item(self):
        """Removes the selected item from the package."""
        row = self.items_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select an item to remove."))
            return

        package_item_id = self.items_table.item(row, 0).data(Qt.UserRole)
        if not package_item_id:
            return

        reply = QMessageBox.question(
            self, tr("Confirm Remove"),
            tr("Remove this item from the package?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if package_repo.remove_package_item(package_item_id):
                self._load_package_items(self._current_package_id)
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to remove item."))


class _PackageEditDialog(QDialog):
    """Internal dialog for creating/editing a package."""

    def __init__(self, parent=None, package_id=None, name="", description="", total_price=0.0):
        super().__init__(parent)
        self._package_id = package_id
        self.setWindowTitle(tr("Edit Package") if package_id else tr("New Package"))
        self.setMinimumWidth(440)
        self._setup_ui(name, description, total_price)

    def _setup_ui(self, name, description, total_price):
        layout = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(layout)
        root.addStretch(1)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText(tr("Package Name"))
        layout.addRow(tr("Package Name:"), self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText(tr("Optional description"))
        self.desc_edit.setMaximumHeight(80)
        if description:
            self.desc_edit.setPlainText(description)
        layout.addRow(tr("Description:"), self.desc_edit)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setMaximum(999999.99)
        self.price_spin.setPrefix("$ ")
        self.price_spin.setValue(total_price)
        layout.addRow(tr("Total Price:"), self.price_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, tr("Validation Error"), tr("Package name is required."))
            self.name_edit.setFocus()
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "total_price": self.price_spin.value()
        }


class _PackageItemDialog(QDialog):
    """Internal dialog for adding a service or supply item to a package."""

    def __init__(self, package_id, parent=None):
        super().__init__(parent)
        self._package_id = package_id
        self.setWindowTitle(tr("Add Item to Package"))
        self.setMinimumWidth(440)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(layout)
        root.addStretch(1)

        # Item type selection
        self.type_combo = QComboBox()
        self.type_combo.addItems([tr("Service"), tr("Supply")])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addRow(tr("Item Type:"), self.type_combo)

        # Item name selection (populated based on type)
        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QComboBox.NoInsert)
        layout.addRow(tr("Item:"), self.item_combo)

        # Quantity
        self.qty_spin = QSpinBox()
        self.qty_spin.setMinimum(1)
        self.qty_spin.setMaximum(9999)
        self.qty_spin.setValue(1)
        layout.addRow(tr("Quantity:"), self.qty_spin)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Load initial items
        self._on_type_changed()

    def _on_type_changed(self):
        """Loads items based on selected type."""
        self.item_combo.clear()
        if self.type_combo.currentIndex() == 0:
            # Service type
            services = supply_repo.get_all_services()
            for service_name in services:
                self.item_combo.addItem(service_name, ("service", service_name, None))
        else:
            # Supply type
            items = supply_repo.get_all_unique_item_names()
            for item_name, category, sub_category in items:
                display = f"{item_name} ({category})" if category else item_name
                self.item_combo.addItem(display, ("supply", item_name, category))

    def _validate(self):
        if not self.item_combo.currentText().strip():
            QMessageBox.warning(self, tr("Validation Error"), tr("Please select an item."))
            return
        self.accept()

    def get_data(self):
        """Returns item data for adding to the package."""
        item_type = "service" if self.type_combo.currentIndex() == 0 else "supply"
        quantity = self.qty_spin.value()

        # The combo shows "Item (Category)" for supplies, so resolve the ids from
        # the item payload rather than from the displayed text.
        payload = self.item_combo.currentData()
        if isinstance(payload, tuple) and len(payload) == 3:
            kind, name, category = payload
            item_type = kind
        else:
            name, category = self.item_combo.currentText().strip(), None

        if item_type == "service":
            service_id = lookup_repo.get_service_id(name)
            if not service_id:
                return None
            return {
                "item_type": "service",
                "service_id": service_id,
                "supply_id": None,
                "quantity": quantity
            }

        supply_id = supply_repo.resolve_supply_id(name, category)
        if not supply_id:
            return None
        return {
            "item_type": "supply",
            "service_id": None,
            "supply_id": supply_id,
            "quantity": quantity
        }
