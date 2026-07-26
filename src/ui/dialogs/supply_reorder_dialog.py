"""
Supply Reorder Dialog for the PET Application.
Full-view dialog showing low-stock and expiring-soon supplies with actionable details.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QAbstractItemView, QLabel,
    QTabWidget, QWidget, QSpinBox, QFormLayout, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush

import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.stock_repo as stock_repo
from src.ui.dialogs.stock_batch_dialog import StockBatchDialog, _batch_details
from src.ui.themes.color_palettes import get_active_palette
from src.utils.i18n import tr


class SupplyReorderDialog(QDialog):
    """Full-view dialog for supply reorder and expiry monitoring."""

    # Columns that take up whatever width is left over in each table.
    LOW_STOCK_ITEM_COLUMN = 0
    EXPIRING_BATCH_COLUMN = 0
    EXPIRING_ITEM_COLUMN = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Supply Reorder Overview"))
        self.setMinimumSize(860, 580)
        self._setup_ui()
        self._load_data()

    @staticmethod
    def _fit_columns(table, stretch_column):
        """Sizes every column to its text and gives *stretch_column* the remainder."""
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            header.setSectionResizeMode(
                col,
                QHeaderView.Stretch if col == stretch_column
                else QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()

        # --- Low Stock Tab ---
        low_stock_widget = QWidget()
        ls_layout = QVBoxLayout(low_stock_widget)
        self.low_stock_table = QTableWidget()
        self.low_stock_table.setColumnCount(6)
        self.low_stock_table.setHorizontalHeaderLabels([
            tr("Item"), tr("Category"), tr("Sub-Category"),
            tr("Stock"), tr("Reorder Level"), tr("Status")
        ])
        self._fit_columns(self.low_stock_table, self.LOW_STOCK_ITEM_COLUMN)
        self.low_stock_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.low_stock_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.low_stock_table.setAlternatingRowColors(True)
        self.low_stock_table.cellClicked.connect(self._on_low_stock_clicked)
        ls_layout.addWidget(self.low_stock_table)

        ls_btns = QHBoxLayout()
        set_reorder_btn = QPushButton(tr("Set Reorder Level"))
        set_reorder_btn.clicked.connect(self._set_reorder_level)
        ls_btns.addWidget(set_reorder_btn)
        ls_btns.addStretch()
        ls_layout.addLayout(ls_btns)
        self.tabs.addTab(low_stock_widget, tr("Low Stock"))

        # --- Expiring Soon Tab ---
        expiring_widget = QWidget()
        exp_layout = QVBoxLayout(expiring_widget)
        self.expiring_table = QTableWidget()
        self.expiring_table.setColumnCount(8)
        self.expiring_table.setHorizontalHeaderLabels([
            tr("Batch ID"), tr("Item"), tr("Category"), tr("Sub-Category"),
            tr("Quantity"), tr("Purchase Date"), tr("Expiry Date"),
            tr("Days Left")
        ])
        self._fit_columns(self.expiring_table, self.EXPIRING_ITEM_COLUMN)
        self.expiring_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.expiring_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.expiring_table.setAlternatingRowColors(True)
        self.expiring_table.cellClicked.connect(self._on_expiring_clicked)
        exp_layout.addWidget(self.expiring_table)
        self.tabs.addTab(expiring_widget, tr("Expiring Soon"))

        layout.addWidget(self.tabs)

        # Close
        footer = QHBoxLayout()
        footer.addStretch()
        refresh_btn = QPushButton(tr("Refresh"))
        refresh_btn.clicked.connect(self._load_data)
        footer.addWidget(refresh_btn)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _load_data(self):
        self._load_low_stock()
        self._load_expiring()

    def _load_low_stock(self):
        palette = get_active_palette()
        items = supply_repo.search_supplies()
        reorder_levels = supply_repo.get_all_reorder_levels()
        total_qtys = supply_repo.get_total_quantities_by_item()

        low_items = []
        for item in items:
            name = item["item_name"]
            qty = total_qtys.get(name, 0)
            reorder = reorder_levels.get(name, 0)
            if qty == 0 or (reorder > 0 and qty <= reorder):
                low_items.append({**item, "total_stock": qty, "reorder_level": reorder})

        self.low_stock_table.setRowCount(0)
        for item in low_items:
            row = self.low_stock_table.rowCount()
            self.low_stock_table.insertRow(row)
            item_cell = QTableWidgetItem(item["item_name"])
            item_cell.setData(Qt.UserRole, item["supply_id"])
            item_cell.setToolTip(tr("View stock batches"))
            self._style_as_link(item_cell)
            self.low_stock_table.setItem(row, 0, item_cell)
            self.low_stock_table.setItem(row, 1, QTableWidgetItem(item.get("category") or ""))
            self.low_stock_table.setItem(row, 2, QTableWidgetItem(item.get("sub_category") or ""))

            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.DisplayRole, item["total_stock"])
            qty_item.setTextAlignment(Qt.AlignCenter)
            if item["total_stock"] == 0:
                qty_item.setForeground(QColor(palette.qcolor("state_danger")))
            elif item["total_stock"] <= item["reorder_level"]:
                qty_item.setForeground(QColor(palette.qcolor("state_warning")))
            self.low_stock_table.setItem(row, 3, qty_item)

            reorder_item = QTableWidgetItem()
            reorder_item.setData(Qt.DisplayRole, item["reorder_level"])
            reorder_item.setTextAlignment(Qt.AlignCenter)
            self.low_stock_table.setItem(row, 4, reorder_item)

            status = "Out of Stock" if item["total_stock"] == 0 else "Low Stock"
            status_item = QTableWidgetItem(tr(status))
            status_item.setTextAlignment(Qt.AlignCenter)
            self.low_stock_table.setItem(row, 5, status_item)

    def _load_expiring(self):
        palette = get_active_palette()
        expiring = stock_repo.get_expiring_batches()

        self.expiring_table.setRowCount(0)
        for batch in expiring:
            row = self.expiring_table.rowCount()
            self.expiring_table.insertRow(row)

            batch_item = QTableWidgetItem()
            batch_item.setData(Qt.DisplayRole, batch["batch_id"])
            batch_item.setData(Qt.UserRole, batch["batch_id"])
            batch_item.setToolTip(tr("View batch details"))
            batch_item.setTextAlignment(Qt.AlignCenter)
            self._style_as_link(batch_item)
            self.expiring_table.setItem(row, 0, batch_item)

            name_item = QTableWidgetItem(batch["item_name"] or "")
            name_item.setData(Qt.UserRole, batch["supply_id"])
            name_item.setToolTip(tr("View stock batches"))
            self._style_as_link(name_item)
            self.expiring_table.setItem(row, 1, name_item)
            self.expiring_table.setItem(row, 2, QTableWidgetItem(batch.get("category") or ""))
            self.expiring_table.setItem(row, 3, QTableWidgetItem(batch.get("sub_category") or ""))

            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.DisplayRole, batch["quantity"])
            qty_item.setTextAlignment(Qt.AlignCenter)
            if batch["quantity"] < 5:
                qty_item.setForeground(QColor(palette.qcolor("state_danger")))
            self.expiring_table.setItem(row, 4, qty_item)

            self.expiring_table.setItem(row, 5, QTableWidgetItem(batch.get("purchase_date") or ""))
            self.expiring_table.setItem(row, 6, QTableWidgetItem(batch.get("expiry_date") or ""))

            days_item = QTableWidgetItem()
            days_item.setData(Qt.DisplayRole, batch["days_left"])
            days_item.setTextAlignment(Qt.AlignCenter)
            if batch["days_left"] <= 7:
                days_item.setForeground(QColor(palette.qcolor("state_danger")))
            elif batch["days_left"] <= 30:
                days_item.setForeground(QColor(palette.qcolor("state_warning")))
            self.expiring_table.setItem(row, 7, days_item)

    def _set_reorder_level(self):
        row = self.low_stock_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select an item to set the reorder level."))
            return
        item_name = self.low_stock_table.item(row, 0).text()
        current_level = self.low_stock_table.item(row, 4).text()

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Set Reorder Level — {item}").format(item=item_name))
        form = QFormLayout()
        root = QVBoxLayout(dialog)
        root.addLayout(form)
        root.addStretch(1)
        spin = QSpinBox()
        spin.setRange(0, 99999)
        spin.setValue(int(current_level) if current_level else 0)
        form.addRow(tr("Reorder Level:"), spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            supply_repo.set_reorder_level(item_name, spin.value())
            self._load_low_stock()

    # --- Clickable cells ---------------------------------------------------
    @staticmethod
    def _style_as_link(item):
        """Renders a cell like the item-name / batch-id links elsewhere."""
        font = item.font()
        font.setUnderline(True)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(get_active_palette().qcolor("brand_500")))

    def _item_row(self, supply_id):
        """Returns the item's supply row, or None when it no longer exists."""
        return next((i for i in supply_repo.search_supplies()
                     if i["supply_id"] == supply_id), None)

    def _open_stock_batches(self, supply_id, item_name):
        """Opens the stock batches dialog for the clicked item."""
        dialog = StockBatchDialog(supply_id, item_name, self)
        # A batch added / edited / deleted here moves the quantities this dialog
        # shows, so both tabs are re-read while the dialog is still open.
        dialog.batches_changed.connect(self._load_data)
        dialog.exec_()

    def _on_low_stock_clicked(self, row, col):
        """An item name opens its stock batches."""
        if col != self.LOW_STOCK_ITEM_COLUMN:
            return
        item = self.low_stock_table.item(row, self.LOW_STOCK_ITEM_COLUMN)
        supply_id = item.data(Qt.UserRole) if item is not None else None
        if supply_id is None:
            return
        self._open_stock_batches(supply_id, item.text())

    def _on_expiring_clicked(self, row, col):
        """A batch number opens that batch's details; an item name its batches."""
        if col == self.EXPIRING_ITEM_COLUMN:
            item = self.expiring_table.item(row, self.EXPIRING_ITEM_COLUMN)
            supply_id = item.data(Qt.UserRole) if item is not None else None
            if supply_id is not None:
                self._open_stock_batches(supply_id, item.text())
            return
        if col != self.EXPIRING_BATCH_COLUMN:
            return
        self._open_batch_details(row)

    def _open_batch_details(self, row):
        """Shows the details of the clicked batch, not of the item as a whole."""
        from src.ui.dialogs.info_dialogs import SupplyInfoDialog

        name_cell = self.expiring_table.item(row, self.EXPIRING_ITEM_COLUMN)
        cell = self.expiring_table.item(row, self.EXPIRING_BATCH_COLUMN)
        batch_id = cell.data(Qt.UserRole) if cell is not None else None
        batch = stock_repo.get_stock_batch(batch_id) if batch_id is not None else None
        if batch is None:
            QMessageBox.warning(self, tr("Item Details"),
                                tr("Selected batch not found."))
            return
        item = self._item_row(batch["supply_id"])
        if item is None:
            QMessageBox.warning(self, tr("Item Details"),
                                tr("Selected item not found."))
            return
        # A batch with no expiry of its own shows the item default in its row,
        # so the details dialog has to show the very same date.
        batch = dict(batch)
        if not batch.get("expiry_date"):
            batch["expiry_date"] = item.get("expiry_date")
        SupplyInfoDialog(_batch_details(item, batch), parent=self).exec_()
