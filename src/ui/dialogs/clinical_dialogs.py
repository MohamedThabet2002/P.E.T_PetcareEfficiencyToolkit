"""
Clinical Dialogs for the PET Application.

This module provides the user interface for clinical data entry. 
It includes a Mixin for supply-based receipts and standardized dialogs 
for recording individual medical visits or full clinical patient intake 
(Client + Pet + Visit).
"""
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QTextEdit, QCompleter,
    QVBoxLayout, QWidget, QFrame, QListView, QSizePolicy
)
from PyQt5.QtCore import Qt, QDateTime, QSettings
from PyQt5.QtSql import QSqlQuery


from src.core.database import get_connection
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.services.clinical_service as clinical_service
from src.config import (SETTINGS_ORG, SETTINGS_APP,
    SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE
)
from src.utils.i18n import tr

# Date/Time Formats
DATE_TIME_FORMAT = "yyyy-MM-dd HH:mm"

# UI Symbols
DELETE_BUTTON_SYMBOL = "✕"

#==================================== CONSTANTS =======================================================#
NOTES_BOX_HEIGHT = 60
SUPPLIES_QUANTITY_MAX = 9999
DELETE_BUTTON_SIZE = (36, 36)
SUPPLY_COLUMN_WIDTHS = {
    "category": 110,
    "sub_category": 130,
    "item_name": 150,
    "quantity": 70,
    "price": 90
}

BASE_DIALOG_WIDTH = 800
BASE_DIALOG_HEIGHT = 600

ADD_VISIT_DIALOG_WIDTH = 800
ADD_VISIT_DIALOG_HEIGHT = 600

LEFT_CONTAINER_MIN_WIDTH = 320

SUPPLIES_RECEIPT_CONTAINER_MIN_WIDTH = 450
SUPPLIES_RECEIPT_CONTAINER_MAX_WIDTH = 650

EDIT_VISIT_DIALOG_TITLE_WIDTH = 450

ADD_FULL_ENTRY_DIALOG_WIDTH = 800
ADD_FULL_ENTRY_DIALOG_HEIGHT = 600
ADD_FULL_ENTRY_DIALOG_LEFT_CONTAINER_MIN_WIDTH = 300
ADD_FULL_ENTRY_DIALOG_MAX_AGE = 999
ADD_FULL_ENTRY_DIALOG_MAX_WEIGHT = 9999

#============================================== CODE =====================================================#

class SupplyReceiptMixin:
    """Mixin to provide consistent Supply Receipt UI across dialogs."""
    def _setup_supplies_section(self, parent_layout):
        self._supply_rows = []
        container = QWidget()
        container.setMinimumWidth(SUPPLIES_RECEIPT_CONTAINER_MIN_WIDTH)
        layout = QVBoxLayout(container)
        
        # Store reference to the header for potential retranslation
        self.supplies_header_label = QLabel(f"<b>{tr('SUPPLIES RECEIPT')}</b>")
        layout.addWidget(self.supplies_header_label)
        
        self.add_item_btn = QPushButton(tr("+ Add Supply Item"))
        layout.addWidget(self.add_item_btn)
        
        # Column Headers Frame
        self.headers_frame = QFrame()
        h_layout = QHBoxLayout(self.headers_frame)
        h_layout.setContentsMargins(0, 5, 40, 5) # 40px margin to account for delete button
        h_layout.setSpacing(5)

        for text, width in [
            ("Category", SUPPLY_COLUMN_WIDTHS["category"]),
            ("Sub-Category", SUPPLY_COLUMN_WIDTHS["sub_category"]),
            ("Item Name", SUPPLY_COLUMN_WIDTHS["item_name"]),
            ("Quantity", SUPPLY_COLUMN_WIDTHS["quantity"]),
            ("Price", SUPPLY_COLUMN_WIDTHS["price"])
        ]:
            lbl = QLabel(f"<b>{tr(text)}</b>")
            lbl.setFixedWidth(width)
            lbl.setAlignment(Qt.AlignCenter)
            h_layout.addWidget(lbl)

        layout.addWidget(self.headers_frame)

        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_widget = QWidget()
        self.items_layout = QVBoxLayout(self.items_widget)
        self.items_layout.setAlignment(Qt.AlignTop)
        self.items_scroll.setWidget(self.items_widget)
        layout.addWidget(self.items_scroll)
        
        # Connections
        self.add_item_btn.clicked.connect(self._add_supply_row)
        
        parent_layout.addWidget(container, 3)
    
    def _add_supply_row(self):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(5)
        
        cat = QComboBox()
        cat.setView(QListView())
        cat.view().window().setAttribute(Qt.WA_TranslucentBackground)
        cat.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        cat.setEditable(True)
        cat.setInsertPolicy(QComboBox.NoInsert)
        cat.completer().setFilterMode(Qt.MatchContains)
        cat.addItems(supply_repo.get_all_categories())
        cat.setFixedWidth(SUPPLY_COLUMN_WIDTHS["category"])
        
        sub = QComboBox()
        sub.setView(QListView())
        sub.view().window().setAttribute(Qt.WA_TranslucentBackground)
        sub.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        sub.setFixedWidth(SUPPLY_COLUMN_WIDTHS["sub_category"])
        sub.setEditable(True)
        sub.setInsertPolicy(QComboBox.NoInsert)
        sub.completer().setFilterMode(Qt.MatchContains)
        item = QComboBox()
        item.setView(QListView())
        item.view().window().setAttribute(Qt.WA_TranslucentBackground)
        item.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        item.setEditable(True)
        item.setInsertPolicy(QComboBox.NoInsert)
        item.completer().setFilterMode(Qt.MatchContains)
        item.setFixedWidth(SUPPLY_COLUMN_WIDTHS["item_name"])
        
        qty = QSpinBox()
        qty.setRange(1, SUPPLIES_QUANTITY_MAX)
        qty.setFixedWidth(SUPPLY_COLUMN_WIDTHS["quantity"])
        
        price = QDoubleSpinBox()
        price.setRange(0.0, 99999.99)
        price.setSuffix(" $")
        price.setFixedWidth(SUPPLY_COLUMN_WIDTHS["price"])
        
        del_b = QPushButton(DELETE_BUTTON_SYMBOL)
        del_b.setFixedSize(*DELETE_BUTTON_SIZE)
        del_b.setProperty("action", "delete")
        
        row_entry = (cat, item, qty, price)
        
        def remove_row():
            if row_entry in self._supply_rows:
                self._supply_rows.remove(row_entry)
            row_widget.deleteLater()
            self._update_total()
        
        del_b.clicked.connect(remove_row)
        
        # Cascading dropdown logic
        def update_items():
            item.clear()
            item.addItems(supply_repo.get_items_by_subcategory(cat.currentText(), sub.currentText()))
            update_price()
            self._update_total()
        
        def update_price():
            name = item.currentText()
            category = cat.currentText()
            if name:
                db = get_connection()
                query = QSqlQuery(db)
                query.prepare("SELECT sell_price FROM supplies WHERE item_name = ? AND category = ? LIMIT 1")
                query.addBindValue(name)
                query.addBindValue(category)
                if query.exec() and query.next():
                    price.setValue(query.value(0))
            else:
                price.setValue(0.0)

        def update_subs():
            sub.clear()
            sub.addItems(supply_repo.get_subcategories_by_category(cat.currentText()))
            update_items()
        cat.currentTextChanged.connect(update_subs)
        sub.currentTextChanged.connect(update_items)
        item.currentIndexChanged.connect(update_price)
        
        qty.valueChanged.connect(self._update_total)
        price.valueChanged.connect(self._update_total)

        # Initialize values
        update_subs()
        for w in [cat, sub, item, qty, price, del_b]: 
            row_layout.addWidget(w)
        self.items_layout.addWidget(row_widget)
        self._supply_rows.append(row_entry)
        self._update_total()
    
    def get_final_items(self):
        """Extracts selected supply items for database processing."""
        final_items = []
        
        for c, i, q, p in self._supply_rows:
            if i.currentText():
                final_items.append({"category": c.currentText(), "item_name": i.currentText(), "quantity": q.value(), "price": p.value()})
        return final_items



class BaseClinicalDialog(QDialog, SupplyReceiptMixin):
    """Base class to reduce boilerplate for clinical-related dialogs."""
    def __init__(self, title, size=(BASE_DIALOG_WIDTH, BASE_DIALOG_HEIGHT), parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        
        self.main_layout = QVBoxLayout(self)
        self.content_layout = QHBoxLayout()

        # Left form area: keep dialog height capped and allow scrolling
        self.left_container = QWidget()
        self.form = QFormLayout(self.left_container)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setMinimumWidth(LEFT_CONTAINER_MIN_WIDTH)
        self.left_scroll.setWidget(self.left_container)

        self.content_layout.addWidget(self.left_scroll, 2)
        self._setup_supplies_section(self.content_layout)
        self.main_layout.addLayout(self.content_layout)

        
        # Footer with Total Label
        footer_layout = QHBoxLayout()
        self.total_label = QLabel(f"<b>{tr('Estimated Total: ${total:,.2f}').format(total=0.0)}</b>")
        self.total_label.setStyleSheet("font-size: 14px; color: #2ECC71; margin-left: 10px;")
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch()
        
        self.buttons = QDialogButtonBox()
        ok_button = self.buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = self.buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.handle_accept)
        self.buttons.rejected.connect(self.reject)
        footer_layout.addWidget(self.buttons)
        self.main_layout.addLayout(footer_layout)
    
    def _add_section_header(self, text):
        """Adds a stylized bold header to the form."""
        self.form.addRow(QLabel(f"<br><b>{tr(text)}</b>"), QLabel(""))
    
    def handle_stock_error(self, result):
        """Common logic to display insufficient stock warnings."""
        if isinstance(result, str) and result.startswith("STOCK_ERROR"):
            _, name, max_qty = result.split("|")
            QMessageBox.warning(self, tr("Stock Error"), tr("Insufficient stock for {name}. Maximum available: {max_qty}").format(name=name, max_qty=max_qty))
            return True
        return False
    
    def _update_total(self):
        """Calculates and updates the estimated total for the visit."""
        total = 0.0
        
        # 1. Add Consultation Fee if applicable
        if hasattr(self, 'consult') and self.consult.isChecked():
            settings = QSettings()
            fee = float(settings.value(SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE))
            total += fee
            
        # 2. Add Supply Item totals
        if hasattr(self, '_supply_rows'):
            for cat_cb, item_cb, qty_sb, price_sb in self._supply_rows:
                if item_cb.currentText():
                    total += qty_sb.value() * price_sb.value()
        
        if hasattr(self, 'total_label'):
            self.total_label.setText(f"<b>{tr('Estimated Total: ${total:,.2f}').format(total=total)}</b>")
    
    def handle_accept(self):
        """Should be overridden by child classes."""
        raise NotImplementedError
    

class AddVisitDialog(BaseClinicalDialog):
    def __init__(self, parent=None):
        super().__init__(tr("Add Visit"), (ADD_VISIT_DIALOG_WIDTH, ADD_VISIT_DIALOG_HEIGHT), parent)
        self.left_container.setMinimumWidth(LEFT_CONTAINER_MIN_WIDTH)
        self.left_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._setup_fields()
    
    def _setup_fields(self):
        self.visit_date = QDateTimeEdit(calendarPopup=True)
        self.visit_date.setDateTime(QDateTime.currentDateTime())
        self.visit_date.setDisplayFormat(DATE_TIME_FORMAT)
        
        self.client_selector = QComboBox()
        self.client_selector.setView(QListView())
        self.client_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.client_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.client_selector.setEditable(True)
        self.client_selector.setInsertPolicy(QComboBox.NoInsert)
        self.client_selector.completer().setFilterMode(Qt.MatchContains)
        self.client_selector.setPlaceholderText(tr("Select Client..."))
        for c in client_repo.get_clients():
            display_text = f"{c['owner_name']} ({c['phone_number']})" if c['phone_number'] else c['owner_name']
            self.client_selector.addItem(display_text, c["client_id"])
        self.client_selector.setCurrentIndex(-1)
        
        self.pet_selector = QComboBox()
        self.pet_selector.setView(QListView())
        self.pet_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.pet_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.pet_selector.setEditable(True)
        self.pet_selector.setInsertPolicy(QComboBox.NoInsert)
        self.pet_selector.completer().setFilterMode(Qt.MatchContains)
        self.pet_selector.setPlaceholderText(tr("Select Pet..."))
        self.client_selector.currentIndexChanged.connect(self._update_pets)
        
        # Fetch current fee from settings
        settings = QSettings()
        fee = settings.value(SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE)
        self.consult = QCheckBox(f"{tr('Consult Charge Applied?')} (${fee})")
        # Removed setLayoutDirection(Qt.RightToLeft) to maintain LTR policy
        self.diagnosis = QLineEdit()
        diag_completer = QCompleter(visit_repo.get_unique_diagnoses())
        diag_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.diagnosis.setCompleter(diag_completer)
        self.diagnosis.setPlaceholderText(tr("Add diagnosis..."))
        
        self.notes = QTextEdit()
        self.notes.setFixedHeight(NOTES_BOX_HEIGHT)
        self.notes.setPlaceholderText(tr("Add notes..."))
        
        self.form.addRow(tr("Date:") + ":", self.visit_date)
        self.form.addRow(tr("Owner Name") + "*:", self.client_selector)
        self.form.addRow(tr("Pet Name") + ":", self.pet_selector)
        self.form.addRow(tr("Consult:"), self.consult)
        self.form.addRow(tr("Diagnosis") + ":", self.diagnosis)
        self.form.addRow(tr("Notes") + ":", self.notes)
        
        self._update_pets()
        self._update_total()
    
    def _update_pets(self):
        self.pet_selector.clear()
        self.pet_selector.setPlaceholderText(tr("Select Pet..."))
        cid = self.client_selector.currentData()
        if cid:
            for p in pet_repo.get_pets_for_client(cid):
                self.pet_selector.addItem(p['pet_name'], p["pet_id"])
        self.pet_selector.setCurrentIndex(-1)
    
    def handle_accept(self):
        cid = self.client_selector.currentData()
        pid = self.pet_selector.currentData()
        if not cid:
            # Only the owner selection is strictly required now.
            QMessageBox.warning(self, tr("Error"), tr("Owner selection is required."))
            return
        
        items = self.get_final_items()
        is_consult = self.consult.isChecked()
        
        result = visit_repo.add_visit(
            self.visit_date.dateTime().toString(DATE_TIME_FORMAT), 
            self.diagnosis.text().strip().capitalize(),
            1 if is_consult else 0, 
            self.notes.toPlainText().strip().capitalize(), 
            pet_id=pid,
            items=items,
            client_id=cid
        )
        
        if not self.handle_stock_error(result):
            if result:
                msg = tr("Record added successfully.")
                # Only show Receipt ID if a financial transaction occurred (Consult or Supplies)
                if is_consult or items:
                    msg += tr("\n\nReceipt ID: {receipt_id}").format(receipt_id=result)
                QMessageBox.information(self, tr("Success"), msg)
            else:
                QMessageBox.critical(self, tr("Critical Error"), tr("Failed to save record to database."))
                return
            self.accept()


class AddFullEntryDialog(BaseClinicalDialog):
    def __init__(self, parent=None):
        super().__init__(tr("Add Full Clinical Entry"), (ADD_FULL_ENTRY_DIALOG_WIDTH, ADD_FULL_ENTRY_DIALOG_HEIGHT), parent)
        self.left_container.setMinimumWidth(ADD_FULL_ENTRY_DIALOG_LEFT_CONTAINER_MIN_WIDTH)
        self.left_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._setup_fields()
    
    def _setup_fields(self):
        self.v_date = QDateTimeEdit(QDateTime.currentDateTime())
        self.v_date.setCalendarPopup(True)
        self.form.addRow(tr("Date:") + ":", self.v_date)
        
        self._add_section_header("CLIENT DETAILS")
        self.owner_name = QLineEdit()
        self.phone = QLineEdit()
        self.form.addRow(tr("Owner Name") + "*:", self.owner_name)
        self.form.addRow(tr("Phone Number") + ":", self.phone)
        
        self._add_section_header("PET DETAILS")
        self.pet_name = QLineEdit()
        self.species = QComboBox()
        self.species.setView(QListView())
        self.species.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.species.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.species.addItems(supply_repo.get_all_species())
        
        self.breed = QLineEdit()
        breed_completer = QCompleter(pet_repo.get_unique_breeds())
        breed_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.breed.setCompleter(breed_completer)
        self.gender = QComboBox()
        self.gender.setView(QListView())
        self.gender.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.gender.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.gender.addItems([tr("Male"), tr("Female"), tr("Other")])
        self.age = QSpinBox(); self.age.setMaximum(ADD_FULL_ENTRY_DIALOG_MAX_AGE)
        self.weight = QDoubleSpinBox(); self.weight.setMaximum(ADD_FULL_ENTRY_DIALOG_MAX_WEIGHT)
        
        self.form.addRow(tr("Pet Name") + ":", self.pet_name)
        self.form.addRow(tr("Species") + ":", self.species)
        self.form.addRow(tr("Breed") + ":", self.breed)
        self.form.addRow(tr("Gender") + ":", self.gender)
        self.form.addRow(tr("Age") + ":", self.age)
        self.form.addRow(tr("Weight") + ":", self.weight)
        
        self._add_section_header("VISIT DETAILS")
        # Fetch current fee from settings
        settings = QSettings()
        fee = settings.value(SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE)
        self.consult = QCheckBox(f"{tr('Consult Charge Applied?')} (${fee})")
        # Removed setLayoutDirection(Qt.RightToLeft) to maintain LTR policy
        self.consult.toggled.connect(self._update_total)
        self.diagnosis = QLineEdit()
        diag_completer = QCompleter(visit_repo.get_unique_diagnoses())
        diag_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.diagnosis.setCompleter(diag_completer)
        self.diagnosis.setPlaceholderText(tr("Add diagnosis..."))
        
        self.notes = QTextEdit()
        self.notes.setFixedHeight(NOTES_BOX_HEIGHT)
        self.notes.setPlaceholderText(tr("Add notes..."))
        
        self.form.addRow(tr("Consult:"), self.consult)
        self.form.addRow(tr("Diagnosis") + ":", self.diagnosis)
        self.form.addRow(tr("Notes") + ":", self.notes)
        self._update_total()
    
    def handle_accept(self):
        if not self.owner_name.text():
            QMessageBox.warning(self, tr("Error"), tr("Owner name is required."))
            return
        
        name_input = self.owner_name.text().strip().title()
        phone_input = self.phone.text().strip()
        
        merge_id = None
        new_phone_val = None

        # Check for exact match (Name + Phone) to offer merging
        existing_clients = client_repo.get_clients_by_name_exact(name_input)
        for client in existing_clients:
            if client['phone_number'] == phone_input:
                msg = tr("Owner '{owner}' with phone '{phone}' already exists. Do you want to merge this entry into their existing record?").format(owner=name_input, phone=phone_input)
                if QMessageBox.question(self, tr("Duplicate Owner Name"), msg, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                    merge_id = client['client_id']
                    break
                else:
                    return # Cancel addition
        
        # Only prepare pet details if a name is provided
        pet_name_input = self.pet_name.text().strip()
        pet_data = None
        if pet_name_input:
            pet_data = {
                'name': pet_name_input,
                'species': self.species.currentText(),
                'breed': self.breed.text(),
                'gender': self.gender.currentText(),
                'age': self.age.value(),
                'weight': self.weight.value()
            }

        # Call the Service
        success, result = clinical_service.process_full_clinical_entry(
            owner_data={'name': name_input, 'phone': phone_input, 'merge_id': merge_id, 'new_phone': new_phone_val},
            pet_data=pet_data,
            visit_data={
                'date': self.v_date.dateTime().toString(DATE_TIME_FORMAT),
                'diagnosis': self.diagnosis.text(),
                'is_consult': 1 if self.consult.isChecked() else 0,
                'notes': self.notes.toPlainText()
            },
            items=self.get_final_items()
        )
        
        if not success:
            if not self.handle_stock_error(result):
                QMessageBox.critical(self, tr("Error"), str(result))
            return
        msg = tr("Record added successfully.")
        if result and isinstance(result, dict) and 'receipt_id' in result:
            msg += tr("\n\nReceipt ID: {receipt_id}").format(receipt_id=result['receipt_id'])
        QMessageBox.information(self, tr("Success"), msg)
        self.accept()


class EditVisitDialog(QDialog):
    """Dialog to edit an existing medical visit's details."""
    def __init__(self, visit_id, date_str, diagnosis, is_consult, notes, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit Visit #{visit_id}").format(visit_id=visit_id))
        self.setFixedWidth(EDIT_VISIT_DIALOG_TITLE_WIDTH)
        layout = QFormLayout(self)
        
        self.visit_id = visit_id
        self.date_edit = QDateTimeEdit(QDateTime.fromString(date_str, DATE_TIME_FORMAT), calendarPopup=True)
        self.date_edit.setDisplayFormat(DATE_TIME_FORMAT)
        self.diag_edit = QLineEdit(diagnosis)
        diag_completer = QCompleter(visit_repo.get_unique_diagnoses())
        diag_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.diag_edit.setCompleter(diag_completer)
        
        self.consult_cb = QCheckBox(tr("Consult Charge Applied?"))
        self.consult_cb.setChecked(is_consult)
        self.notes_edit = QTextEdit(notes)
        self.notes_edit.setFixedHeight(NOTES_BOX_HEIGHT)
        
        layout.addRow(tr("Date:") + ":", self.date_edit)
        layout.addRow(tr("Consult:"), self.consult_cb)
        layout.addRow(tr("Diagnosis") + ":", self.diag_edit)
        layout.addRow(tr("Notes") + ":", self.notes_edit)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.handle_save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def handle_save(self):
        """Updates the visit record via the repository."""
        success = visit_repo.update_visit(
            self.visit_id,
            self.diag_edit.text().strip().capitalize(),
            self.notes_edit.toPlainText().strip().capitalize(),
            self.date_edit.dateTime().toString(DATE_TIME_FORMAT),
            1 if self.consult_cb.isChecked() else 0
        )
        if success:
            self.accept()
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to update visit record."))
