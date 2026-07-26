"""
Financial Ledger module for the PET Application.
Provides a specialized view for managing sales receipts and logging general clinic expenses.
"""

from PyQt5.QtWidgets import (
    QTableWidgetItem, QMessageBox, QDialog, QFormLayout, QListView,
    QDateEdit, QComboBox, QLineEdit, QDoubleSpinBox,
    QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QDate

from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.utils.i18n import tr
import src.core.repositories.sales_repo as sales_repo
from src.ui.base_page import BaseEntityPage

#=========================================== CONSTANTS ===================================================#

# Expense Categories
EXPENSE_CATEGORIES = [
    "Utilities",
    "Rent",
    "Salary",
    "Maintenance",
    "Tax",
    "Other",
]

# RECEIPT_COLUMN_MAP uses English strings for headers
RECEIPT_COLUMN_MAP = [
    ("ID", "id", 100),
    ("Date", "receipt_date", 150),
    ("Item Name", "item_name", 180),
    ("Category", "item_type", 100),
    ("Quantity", "quantity", 100),
    ("Unit Price", "unit_price", 100),
    ("Total Price", "total_price", 150),
    ("Total Price", "total_amount", 120),
    ("Receipt ID", "receipt_id", 100),
    ("Type", "receipt_type", 100),
    ("Notes", "notes", 200),
]

#============================================== CODE =====================================================#


class ReceiptsPage(BaseEntityPage):
    """A page to display receipt records from the database."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Dynamically creates the receipts tab using BaseEntityPage logic."""
        header_keys = [tr(col[0]) for col in RECEIPT_COLUMN_MAP]
        widths = [col[2] for col in RECEIPT_COLUMN_MAP]

        self.create_tab(
            name="Expenses",
            headers=header_keys,
            filter_items=[tr("All")] + header_keys,
            add_callback=self.add_expense_dialog,
            delete_callback=self.delete_selected_receipt,
            refresh_callback=self.refresh_receipts_table,
            col_widths=widths,
        )

        self.refresh_receipts_table()

        # Refresh row colors when theme changes
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)

        # Set default sort: Date column from last to first
        self.tables["Expenses"].sortByColumn(1, Qt.DescendingOrder)

    def retranslate_ui(self):
        """Updates the tab title, headers, and table data when language changes."""
        super().retranslate_ui()

        self.tabs.setTabText(0, tr("Expenses"))

        header_keys = [tr(col[0]) for col in RECEIPT_COLUMN_MAP]
        self.tables["Expenses"].setHorizontalHeaderLabels(header_keys)
        self.refresh_receipts_table()

    def refresh_receipts_table(self, text: str = ""):
        """Fetches data from the database and populates the table."""
        filter_field = self.filters["Expenses"].currentText()
        data = sales_repo.get_receipt_items(text, filter_field)

        table = self.tables["Expenses"]
        palette = get_active_palette()

        table.setSortingEnabled(False)
        table.setRowCount(0)

        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)

            for col, (_, key, _) in enumerate(RECEIPT_COLUMN_MAP):
                item = QTableWidgetItem()
                val = row_data[key]

                if key == "receipt_type":
                    is_expense = val == "Expense"
                    item.setText(tr(val))
                    color = (
                        palette.qcolor("state_danger")
                        if is_expense
                        else palette.qcolor("state_success")
                    )
                    item.setForeground(color)
                elif isinstance(val, (int, float)):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")

                table.setItem(row, col, item)

        table.setSortingEnabled(True)

    def add_expense_dialog(self):
        """Opens a dialog to record a general business expense."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add General Expense"))
        dialog.setFixedWidth(400)

        form = QFormLayout(dialog)

        date_edit = QDateEdit(QDate.currentDate())
        date_edit.setCalendarPopup(True)

        category = QComboBox()
        category.addItems([tr(cat) for cat in EXPENSE_CATEGORIES])
        category.setView(QListView())
        category.view().window().setAttribute(Qt.WA_TranslucentBackground)
        category.view().window().setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        category.setEditable(True)

        description = QLineEdit()
        description.setPlaceholderText(tr("e.g., Electricity Bill Jan"))

        amount = QDoubleSpinBox()
        amount.setRange(0, 999999)
        amount.setSuffix(" $")

        notes = QLineEdit()

        form.addRow(tr("Date:"), date_edit)
        form.addRow(tr("Category*:"), category)
        form.addRow(tr("Description*:"), description)
        form.addRow(tr("Amount*:"), amount)
        form.addRow(tr("Notes:"), notes)

        buttons = QDialogButtonBox()
        buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        form.addRow(buttons)

        def handle_accept():
            cat_text = category.currentText().strip()
            desc_text = description.text().strip().title()

            if not cat_text or not desc_text:
                QMessageBox.warning(
                    dialog,
                    tr("Input Error"),
                    tr("Category and Description are required."),
                )
                return

            if sales_repo.add_general_expense(
                date_edit.date().toString(Qt.ISODate),
                cat_text,
                desc_text,
                amount.value(),
                notes.text().strip(),
            ):
                self.refresh_receipts_table()
                self.data_changed.emit()
                dialog.accept()

        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def delete_selected_receipt(self):
        """Deletes the selected receipt from the ledger."""
        table = self.tables["Expenses"]
        row = table.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                tr("Selection Required"),
                tr("Please select a row to delete."),
            )
            return

        receipt_id = table.item(row, 8).text()
        item_name = table.item(row, 2).text()

        msg = tr("Are you sure you want to delete receipt #{id} ({name})?\n"
    "This will remove it from financial records.").format(id=receipt_id, name=item_name)
        if QMessageBox.question(
            self,
            tr("Confirm Delete"),
            msg,
        ) == QMessageBox.Yes:
            if sales_repo.delete_receipt(receipt_id):
                self.refresh_receipts_table()
                self.data_changed.emit()

