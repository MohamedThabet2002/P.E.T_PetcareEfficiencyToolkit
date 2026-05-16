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

from src.config import (
    TR_ALL_FILTER_OPTION, TR_OK, TR_CANCEL, TR_DATE, TR_CATEGORY,
    TR_NOTES, TR_ID, TR_ITEM_NAME, TR_QUANTITY, TR_UNIT_PRICE,
    TR_TOTAL_PRICE, TR_RECEIPT_ID, TR_TYPE_COL,
)
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.utils.i18n import tr
import src.core.repositories.sales_repo as sales_repo
from src.ui.base_page import BaseEntityPage

#============================== TRANSLATABLE STRINGS ===================================================#

# Expense Categories
TR_EXPENSE_UTILITIES = "Utilities"
TR_EXPENSE_RENT = "Rent"
TR_EXPENSE_SALARY = "Salary"
TR_EXPENSE_MAINTENANCE = "Maintenance"
TR_EXPENSE_TAX = "Tax"
TR_EXPENSE_OTHER = "Other"
TR_TYPE_SALE = "Sale"
TR_TYPE_EXPENSE = "Expense"
EXPENSE_CATEGORIES = [
    TR_EXPENSE_UTILITIES,
    TR_EXPENSE_RENT,
    TR_EXPENSE_SALARY,
    TR_EXPENSE_MAINTENANCE,
    TR_EXPENSE_TAX,
    TR_EXPENSE_OTHER,
]

# Sales & Expenses
TR_EXPENSES = "Expenses"
TR_ADD_EXPENSE_TITLE = "Add General Expense"
TR_DESCRIPTION_PLACEHOLDER = "e.g., Electricity Bill Jan"
TR_DATE_LABEL = "Date:"
TR_CATEGORY_LABEL = "Category*:"
TR_DESCRIPTION_LABEL = "Description*:"
TR_AMOUNT_LABEL = "Amount*:"
TR_NOTES_LABEL = "Notes:"
TR_INPUT_ERROR_HEADING = "Input Error"
TR_CATEGORY_DESC_REQUIRED_MSG = "Category and Description are required."
TR_SELECTION_REQUIRED_TITLE = "Selection Required"
TR_SELECT_ROW_DELETE_MSG = "Please select a row to delete."
TR_CONFIRM_DELETE_TITLE = "Confirm Delete"
TR_CONFIRM_DELETE_RECEIPT_MSG = (
    "Are you sure you want to delete receipt #{id} ({name})?\n"
    "This will remove it from financial records."
)

#=========================================== CONSTANTS ===================================================#

# RECEIPT_COLUMN_MAP uses TR_ constants for headers
RECEIPT_COLUMN_MAP = [
    (TR_ID, "id", 100),
    (TR_DATE, "receipt_date", 150),
    (TR_ITEM_NAME, "item_name", 180),
    (TR_CATEGORY, "item_type", 100),  # Already translated
    (TR_QUANTITY, "quantity", 100),
    (TR_UNIT_PRICE, "unit_price", 100),
    (TR_TOTAL_PRICE, "total_price", 150),
    (TR_TOTAL_PRICE, "total_amount", 120),
    (TR_RECEIPT_ID, "receipt_id", 100),
    (TR_TYPE_COL, "receipt_type", 100),
    (TR_NOTES, "notes", 200),
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
            name=TR_EXPENSES,
            headers=header_keys,
            filter_items=[tr(TR_ALL_FILTER_OPTION)] + header_keys,
            add_callback=self.add_expense_dialog,
            delete_callback=self.delete_selected_receipt,
            refresh_callback=self.refresh_receipts_table,
            col_widths=widths,
        )

        self.refresh_receipts_table()

        # Refresh row colors when theme changes
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)

        # Set default sort: Date column from last to first
        self.tables[TR_EXPENSES].sortByColumn(1, Qt.DescendingOrder)

    def retranslate_ui(self):
        """Updates the tab title, headers, and table data when language changes."""
        super().retranslate_ui()

        self.tabs.setTabText(0, tr(TR_EXPENSES))

        header_keys = [tr(col[0]) for col in RECEIPT_COLUMN_MAP]
        self.tables[TR_EXPENSES].setHorizontalHeaderLabels(header_keys)
        self.refresh_receipts_table()

    def refresh_receipts_table(self, text: str = ""):
        """Fetches data from the database and populates the table."""
        filter_field = self.filters[TR_EXPENSES].currentText()
        data = sales_repo.get_receipt_items(text, filter_field)

        table = self.tables[TR_EXPENSES]
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
                    is_expense = val == TR_TYPE_EXPENSE
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
        dialog.setWindowTitle(tr(TR_ADD_EXPENSE_TITLE))
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
        description.setPlaceholderText(tr(TR_DESCRIPTION_PLACEHOLDER))

        amount = QDoubleSpinBox()
        amount.setRange(0, 999999)
        amount.setSuffix(" $")

        notes = QLineEdit()

        form.addRow(tr(TR_DATE_LABEL), date_edit)
        form.addRow(tr(TR_CATEGORY_LABEL), category)
        form.addRow(tr(TR_DESCRIPTION_LABEL), description)
        form.addRow(tr(TR_AMOUNT_LABEL), amount)
        form.addRow(tr(TR_NOTES_LABEL), notes)

        buttons = QDialogButtonBox()
        buttons.addButton(tr(TR_OK), QDialogButtonBox.AcceptRole)
        buttons.addButton(tr(TR_CANCEL), QDialogButtonBox.RejectRole)
        form.addRow(buttons)

        def handle_accept():
            cat_text = category.currentText().strip()
            desc_text = description.text().strip().title()

            if not cat_text or not desc_text:
                QMessageBox.warning(
                    dialog,
                    tr(TR_INPUT_ERROR_HEADING),
                    tr(TR_CATEGORY_DESC_REQUIRED_MSG),
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
        table = self.tables[TR_EXPENSES]
        row = table.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                tr(TR_SELECTION_REQUIRED_TITLE),
                tr(TR_SELECT_ROW_DELETE_MSG),
            )
            return

        receipt_id = table.item(row, 8).text()
        item_name = table.item(row, 2).text()

        msg = tr(TR_CONFIRM_DELETE_RECEIPT_MSG).format(id=receipt_id, name=item_name)
        if QMessageBox.question(
            self,
            tr(TR_CONFIRM_DELETE_TITLE),
            msg,
        ) == QMessageBox.Yes:
            if sales_repo.delete_receipt(receipt_id):
                self.refresh_receipts_table()
                self.data_changed.emit()

