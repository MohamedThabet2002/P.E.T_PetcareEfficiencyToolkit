"""
Stock Batch Dialog for the PET Application.
Allows viewing, adding, editing, and deleting stock batches for a selected supply item.
"""

import logging
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QDateEdit, QSpinBox,
    QDoubleSpinBox, QDialogButtonBox, QMessageBox, QComboBox, QGroupBox,
    QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QDate, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush

from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette
import src.core.repositories.stock_repo as stock_repo
import src.core.repositories.supplier_repo as supplier_repo
import src.core.repositories.supply_repo as supply_repo

logger = logging.getLogger(__name__)

STOCK_BATCH_COLUMNS = [
    ("Batch ID", "batch_id", 80),
    ("Receipt ID", "receipt_id", 110),
    ("Purchase Date", "purchase_date", 130),
    ("Expiry Date", "expiry_date", 130),
    ("Buy Price", "buy_price", 100),
    ("Quantity", "quantity", 90),
    ("Supplier", "supplier_name", 200),
    ("Notes", "notes", 300),
]

BATCH_ID_COLUMN = 0
RECEIPT_ID_COLUMN = 1

# Sentinel value of the batch editor's date field: the batch has no expiry date.
NO_EXPIRY_DATE = QDate(1900, 1, 1)


class StockBatchDialog(QDialog):
    """Dialog for managing stock batches for a single supply item.

    Each batch carries its own expiry date and buy price, so clicking a batch
    number opens the details of that batch (not of the item as a whole), and
    clicking its Receipt ID opens the expense receipt it was bought on.
    Emits `batches_changed` after every add / edit / delete so the opens page can
    refresh its quantities while the dialog is still open.
    """

    batches_changed = pyqtSignal()

    def __init__(self, supply_id, supply_name, parent=None, current_user=None):
        super().__init__(parent)
        self.supply_id = supply_id
        self.supply_name = supply_name
        self._current_user = current_user
        self.setWindowTitle(tr("Stock Batches - {name}").format(name=supply_name))
        self.setMinimumSize(880, 620)
        self._setup_ui()
        self._refresh_batches()

    def _on_batches_changed(self):
        """Reloads the table and tells the opener that the quantities moved."""
        self._refresh_batches()
        self.batches_changed.emit()

    @property
    def _user_id(self):
        """The user to credit with the stock movements / audit entries."""
        return (self._current_user or {}).get("user_id")

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info label
        info_label = QLabel(tr("Managing stock batches for: <b>{name}</b>").format(name=self.supply_name))
        layout.addWidget(info_label)

        # Batch table
        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(len(STOCK_BATCH_COLUMNS))
        for col, (header, _, width) in enumerate(STOCK_BATCH_COLUMNS):
            self.batch_table.setHorizontalHeaderItem(col, QTableWidgetItem(tr(header)))
            self.batch_table.setColumnWidth(col, width)
        self._configure_columns()
        self.batch_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.batch_table.setSelectionMode(QTableWidget.SingleSelection)
        self.batch_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.batch_table)
        self.batch_table.cellClicked.connect(self._on_cell_clicked)

        # Shown instead of a bare empty table for items with no batches yet.
        self._empty_label = QLabel(tr("No stock batches recorded yet."))
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        # Buttons
        btn_layout = QHBoxLayout()
        add_btn = QPushButton(tr("+ Add Batch"))
        edit_btn = QPushButton(tr("Edit"))
        delete_btn = QPushButton(tr("- Delete"))
        refresh_btn = QPushButton(tr("Refresh"))
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()

        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        add_btn.clicked.connect(self._add_batch)
        edit_btn.clicked.connect(self._edit_batch)
        delete_btn.clicked.connect(self._delete_batch)
        refresh_btn.clicked.connect(self._refresh_batches)

    def _configure_columns(self):
        """Sizes every column to its content so no text is clipped.

        The Notes column is sized by hand (see `_fit_last_column`): stretching it
        would clamp long notes to the viewport instead of widening the table.
        """
        header = self.batch_table.horizontalHeader()
        last = len(STOCK_BATCH_COLUMNS) - 1
        for col in range(last + 1):
            header.setSectionResizeMode(
                col, QHeaderView.Interactive if col == last else QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)
        self.batch_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.batch_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def _fit_last_column(self):
        """Stretches the Notes column to fill the table, but never below its text."""
        last = len(STOCK_BATCH_COLUMNS) - 1
        others = sum(self.batch_table.columnWidth(c) for c in range(last)
                     if not self.batch_table.isColumnHidden(c))
        target = max(self.batch_table.sizeHintForColumn(last),
                     self.batch_table.viewport().width() - others)
        if target > 0:
            self.batch_table.horizontalHeader().resizeSection(last, target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_last_column)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_last_column)

    def _refresh_batches(self):
        """Reloads the batch table from the database."""
        self.batch_table.setRowCount(0)
        batches = stock_repo.get_stock_batches(self.supply_id)
        for batch in batches:
            row = self.batch_table.rowCount()
            self.batch_table.insertRow(row)
            for col, (_, key, _) in enumerate(STOCK_BATCH_COLUMNS):
                val = batch.get(key)
                item = QTableWidgetItem()
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")
                # Store batch_id in first column's UserRole and style it as a link
                if col == BATCH_ID_COLUMN:
                    item.setData(Qt.UserRole, batch.get("batch_id"))
                    item.setToolTip(tr("View batch details"))
                    self._style_as_link(item)
                elif col == RECEIPT_ID_COLUMN:
                    # The receipt this batch was bought on (None when the batch
                    # predates the link or its receipt was deleted).
                    receipt_id = batch.get("receipt_id")
                    if receipt_id:
                        item.setData(Qt.UserRole, receipt_id)
                        item.setToolTip(tr("View receipt"))
                        self._style_as_link(item)
                    else:
                        item.setToolTip(tr("No receipt linked to this batch"))
                self.batch_table.setItem(row, col, item)

        self._empty_label.setVisible(not batches)
        self._fit_last_column()

    @staticmethod
    def _style_as_link(item):
        """Renders a cell like the item-name links on the supplies page."""
        font = item.font()
        font.setUnderline(True)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(get_active_palette().qcolor("brand_500")))

    def _item_row(self):
        """Returns the item's supply row, or None when it no longer exists."""
        return next((i for i in supply_repo.search_supplies()
                     if i["supply_id"] == self.supply_id), None)

    def _on_cell_clicked(self, row, col):
        """Opens the batch details or the linked receipt, depending on the cell."""
        if col == BATCH_ID_COLUMN:
            self._open_batch_details(row)
        elif col == RECEIPT_ID_COLUMN:
            self._open_receipt_details(row)

    def _open_receipt_details(self, row):
        """Opens the expense receipt this batch was bought on.

        Local import: the receipt page pulls in the whole pages package, and a
        batch dialog must not drag that in at import time.
        """
        cell = self.batch_table.item(row, RECEIPT_ID_COLUMN)
        receipt_id = cell.data(Qt.UserRole) if cell is not None else None
        if not receipt_id:
            return
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        ReceiptInfoDialog(receipt_id, parent=self,
                          current_user=self._current_user).exec_()

    def _open_batch_details(self, row):
        """Shows the details of one batch, not of the item as a whole."""
        from src.ui.dialogs.info_dialogs import SupplyInfoDialog

        cell = self.batch_table.item(row, BATCH_ID_COLUMN)
        batch_id = cell.data(Qt.UserRole) if cell is not None else None
        batch = stock_repo.get_stock_batch(batch_id) if batch_id is not None else None
        if batch is None:
            QMessageBox.warning(self, tr("Item Details"), tr("Selected batch not found."))
            return
        item = self._item_row()
        if item is None:
            QMessageBox.warning(self, tr("Item Details"), tr("Selected item not found."))
            return
        SupplyInfoDialog(_batch_details(item, batch), parent=self.parent()).exec_()

    def _get_selected_batch_id(self):
        """Returns the batch_id of the currently selected row, or None."""
        row = self.batch_table.currentRow()
        if row < 0:
            return None
        item = self.batch_table.item(row, BATCH_ID_COLUMN)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _add_batch(self):
        """Opens a dialog to add a new stock batch."""
        dialog = _BatchEditDialog(
            self, tr("Add Stock Batch"), supply_id=self.supply_id,
            buy_price=(self._item_row() or {}).get("buy_price"),
        )
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            result = stock_repo.add_stock_batch(
                supply_id=self.supply_id,
                supplier_id=data["supplier_id"],
                purchase_date=data["purchase_date"],
                quantity=data["quantity"],
                notes=data["notes"],
                expiry_date=data["expiry_date"],
                buy_price=data["buy_price"],
                user_id=self._user_id,
            )
            if result is not None:
                self._on_batches_changed()
            else:
                QMessageBox.warning(self, tr("Stock Batches"), tr("Failed to add stock batch."))

    def _edit_batch(self):
        """Opens a dialog to edit the selected stock batch."""
        batch_id = self._get_selected_batch_id()
        if batch_id is None:
            QMessageBox.information(self, tr("Stock Batches"), tr("Please select a batch to edit."))
            return

        # Find the batch data from the table
        batches = stock_repo.get_stock_batches(self.supply_id)
        batch_data = None
        for b in batches:
            if b["batch_id"] == batch_id:
                batch_data = b
                break

        if batch_data is None:
            QMessageBox.warning(self, tr("Stock Batches"), tr("Selected batch not found."))
            return

        # A batch with no price of its own falls back to the item's price.
        buy_price = batch_data.get("buy_price")
        if buy_price is None:
            buy_price = (self._item_row() or {}).get("buy_price")

        dialog = _BatchEditDialog(
            self, tr("Edit Stock Batch"),
            supply_id=self.supply_id,
            supplier_id=batch_data.get("supplier_id"),
            purchase_date=batch_data.get("purchase_date"),
            expiry_date=batch_data.get("expiry_date"),
            buy_price=buy_price,
            quantity=batch_data.get("quantity"),
            notes=batch_data.get("notes", ""),
        )
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if stock_repo.update_stock_batch(
                batch_id=batch_id,
                supplier_id=data["supplier_id"],
                purchase_date=data["purchase_date"],
                quantity=data["quantity"],
                notes=data["notes"],
                expiry_date=data["expiry_date"],
                buy_price=data["buy_price"],
                user_id=self._user_id,
            ):
                self._on_batches_changed()
            else:
                QMessageBox.warning(self, tr("Stock Batches"), tr("Failed to update stock batch."))

    def _delete_batch(self):
        """Deletes the selected stock batch after confirmation."""
        batch_id = self._get_selected_batch_id()
        if batch_id is None:
            QMessageBox.information(self, tr("Stock Batches"), tr("Please select a batch to delete."))
            return

        reply = QMessageBox.question(
            self, tr("Delete Batch"),
            tr("Are you sure you want to delete this stock batch?"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if stock_repo.delete_stock_batch(batch_id, user_id=self._user_id):
                self._on_batches_changed()
            else:
                QMessageBox.warning(self, tr("Stock Batches"), tr("Failed to delete stock batch."))


def _batch_details(item, batch):
    """Merges an item row and one batch row for the read-only details dialog.

    Batch-level values (quantity, expiry, buy price, supplier, notes) win, so two
    batches of the same item render differently.
    """
    data = dict(item)
    buy_price = batch.get("buy_price")
    data.update({
        "batch_id": batch.get("batch_id"),
        "purchase_date": batch.get("purchase_date"),
        "expiry_date": batch.get("expiry_date"),
        "buy_price": (item.get("buy_price") or 0.0) if buy_price is None else buy_price,
        "batch_quantity": batch.get("quantity"),
        "supplier": batch.get("supplier_name"),
        "notes": batch.get("notes"),
    })
    return data


class _BatchEditDialog(QDialog):
    """Internal dialog for adding/editing a single stock batch.

    Expiry date and buy price belong to the batch being edited, so both fields
    are always shown: the same item can be bought twice at different prices and
    expire on different dates.
    """

    def __init__(self, parent, title, supply_id=None, supplier_id=None,
                 purchase_date=None, expiry_date=None, buy_price=None,
                 quantity=0, notes=""):
        super().__init__(parent)
        self.supply_id = supply_id
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self._setup_ui(supplier_id, purchase_date, expiry_date, buy_price, quantity, notes)

    def _setup_ui(self, supplier_id, purchase_date, expiry_date=None, buy_price=None,
                  quantity=0, notes=""):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Supplier combo
        self.supplier_combo = QComboBox()
        suppliers = supplier_repo.get_suppliers()
        self.supplier_combo.addItem(tr("-- No Supplier --"), None)
        selected_idx = 0
        for i, s in enumerate(suppliers):
            self.supplier_combo.addItem(s["supplier_name"], s["supplier_id"])
            if supplier_id is not None and s["supplier_id"] == supplier_id:
                selected_idx = i + 1
        self.supplier_combo.setCurrentIndex(selected_idx)
        form.addRow(tr("Supplier:"), self.supplier_combo)

        # Purchase date
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        if purchase_date:
            try:
                if isinstance(purchase_date, str):
                    dt = datetime.strptime(purchase_date[:10], "%Y-%m-%d")
                    self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
                else:
                    self.date_edit.setDate(QDate.fromString(str(purchase_date)[:10], "yyyy-MM-dd"))
            except (ValueError, TypeError):
                self.date_edit.setDate(QDate.currentDate())
        else:
            self.date_edit.setDate(QDate.currentDate())
        form.addRow(tr("Purchase Date:"), self.date_edit)

        # Expiry date of this batch; the minimum date means "no expiry".
        self.expiry_edit = QDateEdit()
        self.expiry_edit.setCalendarPopup(True)
        self.expiry_edit.setDisplayFormat("yyyy-MM-dd")
        self.expiry_edit.setMinimumDate(NO_EXPIRY_DATE)
        self.expiry_edit.setSpecialValueText(tr("No expiry"))
        parsed = QDate.fromString(str(expiry_date or "")[:10], "yyyy-MM-dd")
        self.expiry_edit.setDate(
            parsed if parsed.isValid() and parsed >= NO_EXPIRY_DATE else NO_EXPIRY_DATE)
        form.addRow(tr("Expiry Date:"), self.expiry_edit)

        # Price paid for this batch
        self.buy_price_spin = QDoubleSpinBox()
        self.buy_price_spin.setMaximum(99999.99)
        self.buy_price_spin.setDecimals(2)
        self.buy_price_spin.setSuffix(" $")
        self.buy_price_spin.setValue(float(buy_price or 0))
        form.addRow(tr("Buy Price:"), self.buy_price_spin)

        # Quantity
        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 999999)
        self.quantity_spin.setValue(quantity if quantity > 0 else 1)
        form.addRow(tr("Quantity:"), self.quantity_spin)

        # Notes
        self.notes_edit = QLineEdit()
        self.notes_edit.setText(notes)
        self.notes_edit.setPlaceholderText(tr("Optional notes..."))
        form.addRow(tr("Notes:"), self.notes_edit)

        layout.addLayout(form)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_data(self):
        """Returns the form data as a dict."""
        expiry = self.expiry_edit.date()
        return {
            "supplier_id": self.supplier_combo.currentData(),
            "purchase_date": self.date_edit.date().toString("yyyy-MM-dd"),
            # The minimum date is the "no expiry" sentinel, stored as NULL.
            "expiry_date": (None if expiry == NO_EXPIRY_DATE
                            else expiry.toString("yyyy-MM-dd")),
            "buy_price": round(float(self.buy_price_spin.value()), 2),
            "quantity": self.quantity_spin.value(),
            "notes": self.notes_edit.text().strip(),
        }
