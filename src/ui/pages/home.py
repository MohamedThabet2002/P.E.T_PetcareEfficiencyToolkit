"""Dashboard module for the PET Application.
Provides a consolidated 'Visit Records' view aggregating data across Clients, Pets, and Visits.

HomePage is intentionally implemented as a *single, non-tabbed* page.
It does NOT depend on BaseEntityPage.create_tab(), so changes to BaseEntityPage cannot affect Home.
"""

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSize, QDateTime
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QWidget, QDialog, QDialogButtonBox, QDateTimeEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QTableWidget, QListView, QTableWidgetItem, QPushButton, QLineEdit, QComboBox,
    QMessageBox, QAbstractItemView, QSizePolicy
)

from src.core.repositories import client_repo
import src.core.repositories.visit_repo as visit_repo
from src.config import ICONS_DIR, DATE_TIME_FORMAT_UI
from src.ui.dialogs.clinical_dialogs import AddFullEntryDialog, EditVisitDialog, SupplyReceiptMixin
from src.utils.formatters import format_age
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.ui.base_page import (
    SEARCH_DEBOUNCE_MS,
    CLEAR_ICON_SIZE,
    CLEAR_BUTTON_SIZE,
    CLEAR_ICON,
)

#=========================================== CONSTANTS ===================================================#

QUICK_PURCHASE_DIALOG_WINDOW_SIZE = (800, 600)

# (Header Name, Database Key, Initial Width)
HOME_COLUMN_MAP = [
    ("Visit ID", "visit_id", 0),
    ("Client ID", "owner_id", 0),
    ("Owner Name", "owner_full_name", 180),
    ("Phone Number", "phone_number", 150),
    ("Pet Name", "pet_name", 100),
    ("Species", "species_name", 80),
    ("Breed", "breed_name", 120),
    ("Gender", "gender", 80),
    ("Age", "age_in_months", 120),
    ("Weight", "weight_in_kg", 80),
    ("Date", "visit_date", 140),
    ("Diagnosis", "diagnosis", 140),
    ("Consult", "notes", 90),
    ("Notes", "notes", 400),
    ("Receipt ID", "receipt_id", 100),
]

QUICK_PURCHASE_DIALOG_WINDOW_MIN_SIZE = (800, 600)

#=========================================== CODE ===================================================#

class HomePage(QWidget):
    """Non-tabbed Home page.
    
    Displays visit records and provides quick actions (add/edit/delete, quick purchase).
    """
    
    data_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_ui()
        
        # Default sort: Visit Date (index 10) from last to first
        self.table.setSortingEnabled(False)
        self.table.sortByColumn(10, Qt.DescendingOrder)
        self.table.setSortingEnabled(True)
        
        self.refresh_home_table("")
        # Ensure table colors update on theme change
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)
    
    def _setup_ui(self):
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._apply_search)
        self._pending_search_text = ""
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 10, 0, 0)
        main_layout.setSpacing(8)
        
        # --- Toolbar Section ---
        controls = QHBoxLayout()
        controls.setSpacing(0)
        
        self.add_btn = QPushButton(f"{tr('Add')} {tr('Visit Records')}")
        
        self.quick_purchase_btn = QPushButton(tr("Quick Purchase"))
        self.quick_purchase_btn.setObjectName("quick_purchase_btn")
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(f"{tr('Search')} {tr('Visit Records')}...")
        self.search_bar.setProperty("action", "search")
        
        self.search_clear_btn = QPushButton()
        self.search_clear_btn.setProperty("action", "clear")
        self.search_clear_btn.setIcon(QIcon(str(ICONS_DIR / CLEAR_ICON)))
        self.search_clear_btn.setFixedSize(QSize(CLEAR_BUTTON_SIZE[0], CLEAR_BUTTON_SIZE[1]))
        self.search_clear_btn.setIconSize(QSize(CLEAR_ICON_SIZE[0], CLEAR_ICON_SIZE[1]))
        self.search_clear_btn.clicked.connect(self.search_bar.clear)
        
        self.filter_combo = QComboBox()
        self.filter_combo.setProperty("action", "filter")
        self.filter_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.filter_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.filter_combo.setEditable(True)
        self.filter_combo.setView(QListView())
        self.filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.filter_combo.lineEdit().setReadOnly(True)
        self.filter_combo.lineEdit().setTextMargins(-2, 0, -6, 0)
        
        self.filter_combo.addItems([tr("All")] + [tr(h[0]) for h in HOME_COLUMN_MAP])
        
        self.delete_btn = QPushButton(tr("Delete Selected"))
        
        controls.addWidget(self.add_btn)
        controls.addWidget(self.quick_purchase_btn)
        controls.addWidget(self.search_bar)
        
        controls.addWidget(self.search_clear_btn)
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.delete_btn)
        
        main_layout.addLayout(controls)
        
        # --- Table Section ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(HOME_COLUMN_MAP))
        
        headers = [h[0] for h in HOME_COLUMN_MAP]
        self.table.setHorizontalHeaderLabels(headers)
        
        # Hide columns 0 and 1 (visit_id, client_id)
        self.table.hideColumn(0)
        self.table.hideColumn(1)
        
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        
        for i, (_, __, width) in enumerate(HOME_COLUMN_MAP):
            if width:
                self.table.setColumnWidth(i, width)
        
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        
        main_layout.addWidget(self.table)
        
        # --- Signal wiring ---
        self.add_btn.clicked.connect(self.add_record_dialog)
        self.quick_purchase_btn.clicked.connect(self.open_quick_purchase_dialog)
        self.delete_btn.clicked.connect(self.delete_selected_record)
        
        self.search_bar.textChanged.connect(
            lambda text: self._trigger_debounce(text)
        )
        self.filter_combo.currentIndexChanged.connect(
            lambda: self.refresh_home_table(self.search_bar.text())
        )
        
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
    
    def _trigger_debounce(self, text: str):
        self._pending_search_text = text
        self._debounce_timer.stop()
        self._debounce_timer.start(SEARCH_DEBOUNCE_MS)
    
    def _apply_search(self):
        self.refresh_home_table(self._pending_search_text)
    
    def _current_filter_field(self) -> str:
        # BaseEntityPage: filter_combo holds translated display strings.
        # Home must pass the same filter display to visit_repo.get_home_clients.
        return self.filter_combo.currentText()
    
    def refresh_home_table(self, text: str = ""):
        table = self.table
        filter_field = self._current_filter_field()
        
        data = visit_repo.get_home_clients(text, filter_field)
        palette = get_active_palette()
        
        table.setSortingEnabled(False)
        table.setRowCount(0)
        
        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)
            
            for col, (_, key, _) in enumerate(HOME_COLUMN_MAP):
                item = QTableWidgetItem()
                val = row_data.get(key)
                
                if key == "age_in_months":
                    item.setText(format_age(val))
                elif key == "species_name":
                    item.setText(str(val) if val is not None else "")
                elif key == "breed_name":
                    item.setText(str(val) if val is not None else "")
                elif isinstance(val, (int, float)):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")
                
                table.setItem(row, col, item)
        
        table.setSortingEnabled(True)
    
    def retranslate_ui(self):
        # Keep signature consistent with other pages.
        self.add_btn.setText(f"{tr('Add')} {tr('Visit Records')}")
        self.quick_purchase_btn.setText(tr("Quick Purchase"))
        self.search_bar.setPlaceholderText(f"{tr('Search')} {tr('Visit Records')}...")
        self.delete_btn.setText(tr("Delete Selected"))
        
        # Refresh filter options (translated)
        current_text = self.filter_combo.currentText()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItems([tr("All")] + [tr(h[0]) for h in HOME_COLUMN_MAP])
        # Best-effort: keep current text if possible
        idx = self.filter_combo.findText(current_text)
        if idx >= 0:
            self.filter_combo.setCurrentIndex(idx)
        self.filter_combo.blockSignals(False)
        
# Refresh header labels
        self.table.setHorizontalHeaderLabels([tr(h[0]) for h in HOME_COLUMN_MAP])
        
        # Refresh table data with current search text
        self.refresh_home_table(self.search_bar.text())
    
    def _on_table_double_clicked(self, row: int, column: int):
        # Since it's Home, double-click behaves like editing the visit.
        self._edit_visit_from_home(row)
    
    def _edit_visit_from_home(self, row: int):
        # Column indices from HOME_COLUMN_MAP: Visit ID(0), Diagnosis(11), Notes(12)
        visit_item = self.table.item(row, 0)
        if not visit_item:
            return
        
        visit_id = visit_item.data(Qt.DisplayRole)
        date_str = self.table.item(row, 10).text()
        curr_diag = self.table.item(row, 11).text()
        curr_notes = self.table.item(row, 12).text() if self.table.columnCount() > 12 else ""
        
        # In the new schema, is_consult is handled via receipt_services
        dialog = EditVisitDialog(visit_id, date_str, curr_diag, False, curr_notes, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_home_table(self.search_bar.text())
            self.data_changed.emit()
    
    def open_quick_purchase_dialog(self):
        dialog = QuickPurchaseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_home_table(self.search_bar.text())
            self.data_changed.emit()
    
    def add_record_dialog(self):
        dialog = AddFullEntryDialog(self)
        
        if dialog.exec() == QDialog.Accepted:
            self.refresh_home_table(self.search_bar.text())
            self.data_changed.emit()
    
    def delete_selected_record(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, tr("Selection Required"), tr("Please select a row to delete."))
            return
        
        visit_item = self.table.item(row, 0)
        if not visit_item:
            QMessageBox.information(self, tr("No Visit"), tr("This row has no clinical visit to delete."))
            return
        
        visit_id = visit_item.text()
        if not visit_id:
            QMessageBox.information(self, tr("No Visit"), tr("This row has no clinical visit to delete."))
            return
        
        owner = self.table.item(row, 2).text()
        pet = self.table.item(row, 4).text()
        date = self.table.item(row, 10).text()
        
        msg = tr("Are you sure you want to delete the visit for '{pet}' ({owner}) on {date}?").format(pet=pet, owner=owner, date=date)
        if QMessageBox.question(self, tr("Confirm Delete"), msg) == QMessageBox.Yes:
            if visit_repo.delete_visit(visit_id):
                self.refresh_home_table(self.search_bar.text())
                self.data_changed.emit()

class QuickPurchaseDialog(QDialog, SupplyReceiptMixin):
    def _update_total(self):
        """Calculates and updates the estimated total cost for the quick purchase."""
        total = 0.0

        if hasattr(self, "_supply_rows"):
            for _cat_cb, item_cb, qty_sb, price_sb in self._supply_rows:
                if item_cb.currentText():
                    total += float(qty_sb.value()) * float(price_sb.value())
        
        if hasattr(self, "total_label"):
            self.total_label.setText(tr("<b>Estimated Total: ${total:,.2f}</b>").format(total=total))

    def __init__(self, parent=None):

        super().__init__(parent)
        self.setWindowTitle(tr("Quick Purchase"))
        self.setMinimumSize(*QUICK_PURCHASE_DIALOG_WINDOW_MIN_SIZE)

        root = QVBoxLayout(self)

        # Date
        top = QHBoxLayout()
        self.date_edit = QDateTimeEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat(DATE_TIME_FORMAT_UI)
        self.date_edit.setDateTime(QDateTime.currentDateTime())
        top.addWidget(QLabel(tr("Date:")))
        top.addWidget(self.date_edit)
        top.addStretch()
        root.addLayout(top)

        # Client name
        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        self.client_name_edit = QLineEdit()  # This is intentionally left empty by default
        self.client_name_edit.setPlaceholderText(tr("Owner Name"))

        # 300px minimum, left-aligned, and allowed to expand with the dialog/window.
        self.client_name_edit.setMinimumWidth(250)
        self.client_name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.client_name_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        name_layout.addWidget(QLabel(tr("Owner Name") + ":"))
        name_layout.addWidget(self.client_name_edit,1)
        root.addLayout(name_layout)


        # Supplies receipt (reuse mixin UI)
        form_layout = QVBoxLayout()
        root.addLayout(form_layout)
        self._setup_supplies_section(form_layout)

        # Total label (for estimated purchase total)
        self.total_label = QLabel(tr("<b>Estimated Total: $0.00</b>"))
        self.total_label.setProperty("name", "total-price")

        self.buttons = QDialogButtonBox()
        self.ok_button = self.buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        self.cancel_button = self.buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.handle_accept)
        self.buttons.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.buttons)

        root.addLayout(footer_layout)

        # Initial total
        self._update_total()

    
    def handle_accept(self):
        
        name_input = self.client_name_edit.text().strip()
        if not name_input:
            name_input = tr("Anonymous")
        
        formatted_name = name_input.title()
        client = client_repo.get_clients_by_name_exact(formatted_name)
        if client:
            client_id = client[0]["client_id"]
        else:
            client_id = client_repo.add_client(formatted_name, "")
            if not client_id:
                QMessageBox.critical(self, tr("Error"), tr("Failed to create client"))
                return
            client_id = int(client_id)
        
        # Create a visit-less sale receipt (moved into repository layer).
        items = self.get_final_items()
        if not items:
            QMessageBox.warning(self, tr("Validation Error"), tr("Please add at least one receipt item."))
            return

        # Refactored to use visit_repo.add_visit to ensure:
        # 1. A visit record is created (so it shows up in Home/Visits)
        # 2. Stock levels are properly deducted
        # 3. Financial receipt is generated
        result = visit_repo.add_visit(
            visit_date=self.date_edit.dateTime().toString(DATE_TIME_FORMAT_UI),
            diagnosis=tr("Quick Purchase"),
            consult=0,
            notes="",
            pet_id=None,
            items=items,
            client_id=client_id
        )

        if not result:
            QMessageBox.critical(self, tr("Error"), tr("Failed to record purchase."))
            return

        if isinstance(result, str) and result.startswith("STOCK_ERROR"):
            _, name, _qty = result.split("|")
            QMessageBox.warning(self, tr("Stock Error"), tr("Not enough stock for {item}.").format(item=name))
            return

        QMessageBox.information(self, tr("Success"), tr("Purchase recorded. Receipt ID: #{id}").format(id=result))
        self.accept()

