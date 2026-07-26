"""
Clinical management module for the PET Application.
Provides a unified tabbed interface for handling Clients, Pets, Visits, and Appointments.
"""

from PyQt5.QtWidgets import (
    QMessageBox, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, 
    QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QTableWidgetItem, QCompleter, QListView
)
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QColor

from src.utils.i18n import tr
import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.supply_repo as supply_repo
from src.utils.formatters import format_age
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.ui.base_page import BaseEntityPage
from src.ui.dialogs.clinical_dialogs import AddVisitDialog, EditVisitDialog

#=========================================== CONSTANTS ===================================================#

# --- Page Configuration Constants ---

GENDER_OPTIONS = ["Female", "Male", "Other"]
STATUS_OPTIONS = ["Pending", "Completed", "Canceled"]
DEFAULT_SERVICES = ["Consultation", "Vaccination", "Check-up", "Grooming", "Surgery"]

DIALOG_CONFIG = {
    "client": (400, 150), # Width, Height
    "pet": (400, 350), # Width, Height
    "appointment": (400, 300) # Width, Height
}

CLIENTS_TAB_CONFIG = {
    "Clients": {
        "headers": ["Client ID", "Owner Name", "Phone Number"],
        "hide": [0], # Client ID
        "col_widths":[0, 250, 150], # Client ID, Owner Name, Phone
        "filter": ["All", "Owner Name", "Phone Number"]
    },
    "Pets": {
        "headers": ["ID", "Pet Name", "Species", "Breed", "Gender", "Age", "Weight"],
        "hide": [0], # Pet ID
        "col_widths":[0, 150, 100, 150, 80, 100, 100], # Pet ID, Pet Name, Species, Breed, Gender, Age, Weight
        "filter": ["All", "Pet Name", "Species", "Breed", "Gender", "Age", "Weight"]
    },
    "Visits": {
        "headers": ["Visit ID", "Date", "Owner Name", "Pet Name", "Diagnosis", "Consult", "Notes", "ID", "Receipt ID"],
        "hide": [0, 7], # Visit ID, Pet ID
        "col_widths":[0, 150, 180, 150, 150, 100, 350, 0, 100], # Visit ID, Date, Owner, Pet, Diag, Consult, Notes, Pet ID, Receipt ID
        "filter": ["All", "Date", "Owner Name", "Pet Name", "Diagnosis", "Consult", "Notes"]
    },
    "Appointments": {
        "headers": ["ID", "Date", "Owner Name", "Pet Name", "Service", "Status", "Notes", "Client ID", "ID"],
        "hide": [0, 7, 8], # Appointment ID, Client ID, Pet ID
        "col_widths":[0, 160, 180, 150, 200, 100, 200], # Appointment ID, Appointment Date, Client Name, Pet Name, Service, Status, Notes
        "filter": ["All", "Date", "Owner Name", "Pet Name", "Service", "Status", "Notes", "Client ID"]
    }
}


#============================================== CODE =====================================================#

class ClientsPage(BaseEntityPage):
    """
    A unified page for managing clinical entities (Clients, Pets, Visits, Appointments).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Map internal tab logic to callbacks
        self.actions = {
            "Clients": {"add": self.add_client_dialog, "delete": self.delete_selected_client, "refresh": self.refresh_clients},
            "Pets": {"add": self.add_pet_dialog, "delete": self.delete_selected_pet, "refresh": self.refresh_pets},
            "Visits": {"add": self.add_visit_dialog, "delete": self.delete_selected_visit, "refresh": self.refresh_visits},
            "Appointments": {"add": self.add_appointment_dialog, "delete": self.delete_selected_appointment, "refresh": self.refresh_appointments}
        }
        
        self._setup_ui()
        # Initial data load for the first tab
        self.on_tab_changed(0)
        # React to theme changes (Hot-reload / Settings toggle)
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)
    
    def _setup_ui(self):
        """Initializes the main layout and the tabbed interface."""
        # Dynamically build tabs based on config
        for name, cfg in CLIENTS_TAB_CONFIG.items():
            action = self.actions[name]
            self.create_tab(
                name=name,
                headers=cfg["headers"],
                filter_items=cfg["filter"],
                add_callback=action["add"],
                delete_callback=action["delete"],
                refresh_callback=action["refresh"],
                hide_cols=cfg["hide"],
                col_widths=cfg.get("col_widths")
            )

            # Set default sorting for the Visits tab by Visit Date (index 1) Descending
            if name == "Visits":
                self.tables[name].sortByColumn(1, Qt.DescendingOrder)
            # Set default sorting for the Appointments tab by Appointment Date (index 1) Ascending
            elif name == "Appointments":
                self.tables[name].sortByColumn(1, Qt.DescendingOrder)
        
        # Refresh tabs on change
        self.tabs.currentChanged.connect(self.on_tab_changed)
    
    def on_tab_changed(self, index):
        """Refreshes the data when switching between tabs."""
        if 0 <= index < len(self._tab_configs):
            tab_name = self._tab_configs[index]["name_key"]
            if tab_name in self.actions:
                search_text = self.search_bars[tab_name].text()
                self.actions[tab_name]["refresh"](search_text)
    
    def refresh_active_tab(self):
        """Triggers a data refresh for the currently active tab."""
        self.on_tab_changed(self.tabs.currentIndex())

    def retranslate_ui(self):
        """Updates UI text and repopulates tables that contain translated cell values."""
        super().retranslate_ui()

        # Some table cells (e.g., Visit consult Yes/No, Appointment status) are translated
        # when populating rows, so we need to rebuild those values after language switches.
        try:
            current_tab = self.tabs.tabText(self.tabs.currentIndex())
        except Exception:
            current_tab = ""

        # Preserve current search text per tab when refreshing.
        visits_search = self.search_bars.get("Visits").text() if "Visits" in self.search_bars else ""
        apps_search = self.search_bars.get("Appointments").text() if "Appointments" in self.search_bars else ""

        # Refresh both affected tabs; keep it lightweight by only forcing a full refresh
        # for the translated-cell tables.
        self.refresh_visits(visits_search)
        self.refresh_appointments(apps_search)

    def on_row_double_clicked(self, category, row):
        """Triggers the edit flow based on which tab is active."""
        if category == "Clients":
            self.edit_client_dialog(row)
        elif category == "Pets":
            self.edit_pet_dialog(row)
        elif category == "Visits":
            self.edit_visit_dialog(row)
        elif category == "Appointments":
            self.edit_appointment_dialog(row)
    
    def _populate_table(self, tab_name, data, keys, formatter=None):
        """Generic helper to populate table widgets with data and correct sorting."""
        table = self.tables[tab_name]
        table.setSortingEnabled(False)
        table.setRowCount(0)
        
        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)
            for col, key in enumerate(keys):
                item = QTableWidgetItem()
                val = row_data.get(key)
                
                # Apply custom formatting logic if provided
                if formatter:
                    val = formatter(key, val, item)
                
                # Numeric data handling for proper sorting
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")
                
                table.setItem(row, col, item)
                
        table.setSortingEnabled(True)
    
    def _handle_deletion_confirm(self, tab_name, id_col, name_col, repo_func, refresh_func, label="item"):
        """Standardized deletion flow with confirmation dialog."""
        table = self.tables[tab_name]
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("No Selection"), tr("Please select a {label} to delete.").format(label=tr(label)))
            return
            
        entity_id = table.item(row, id_col).text()
        entity_name = table.item(row, name_col).text()
        
        reply = QMessageBox.question(
            self, tr("Confirm Delete"),
            tr("Are you sure you want to delete {label} '{entity_name}'?").format(label=tr(label), entity_name=entity_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # We assume repo functions return success status or handle errors internally
            repo_func(entity_id)
            refresh_func()
            self.data_changed.emit()
    
    # __________________________ Clients Functions __________________________
    def edit_client_dialog(self, row):
        """Opens a dialog to edit an existing client's information."""
        table = self.tables["Clients"]
        client_id = table.item(row, 0).data(Qt.DisplayRole)
        current_name = table.item(row, 1).text()
        current_phone = table.item(row, 2).text()
        
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit Client: {name}").format(name=current_name))
        dialog.setFixedSize(*DIALOG_CONFIG["client"])
        layout = QFormLayout(dialog)
        
        owner_name = QLineEdit(current_name)
        phone_number = QLineEdit(current_phone)
        
        layout.addRow(tr("Owner Name*:"), owner_name)
        layout.addRow(tr("Phone Number:"), phone_number)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_save():
            new_name = owner_name.text().strip().title()
            new_phone = phone_number.text().strip()
            
            if not new_name:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Owner name is required."))
                return
            
            if client_repo.update_client(client_id, new_name, new_phone):
                self.refresh_clients()
                self.data_changed.emit()
                dialog.accept()
            else:
                QMessageBox.critical(dialog, tr("Database Error"), tr("Could not update client."))
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()
    
    def add_client_dialog(self):
        """Opens dialog to add a new client."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Client"))
        dialog.setFixedSize(*DIALOG_CONFIG["client"])
        layout = QFormLayout(dialog)
        
        owner_name = QLineEdit()
        phone_number = QLineEdit()
        
        layout.addRow(tr("Owner Name*:"), owner_name)
        layout.addRow(tr("Phone Number:"), phone_number)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            name_input = owner_name.text().strip()
            phone_input = phone_number.text().strip()
            if not name_input:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Owner name is required."))
                return
            
            formatted_name = name_input.title()

            # Check for exact match (Name + Phone)
            existing_clients = client_repo.get_clients_by_name_exact(formatted_name)
            for client in existing_clients:
                if client['phone_number'] == phone_input:
                    QMessageBox.information(dialog, tr("Information"), tr("Owner is already recorded."))
                    return

            client_repo.add_client(formatted_name, phone_input)
                
            self.refresh_clients()
            self.data_changed.emit()
            dialog.accept()
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def refresh_clients(self, text=""):
        """Updates the clients table from database."""
        filter_field = self.filters["Clients"].currentText()
        data = client_repo.get_clients(text, filter_field)
        self._populate_table("Clients", data, ["client_id", "owner_name", "phone_number"])
    
    def delete_selected_client(self):
        """Deletes the selected client after confirmation."""
        self._handle_deletion_confirm(
            "Clients", 0, 1, 
            client_repo.delete_client, self.refresh_clients, "client"
        )
    
    # __________________________ Pets Functions__________________________
    def add_pet_dialog(self):
        """Opens dialog to add a new pet."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Pet"))
        dialog.setFixedSize(*DIALOG_CONFIG["pet"])
        layout = QFormLayout(dialog)
        
        pet_name = QLineEdit()
        species = QComboBox()
        species.setView(QListView())
        species.view().window().setAttribute(Qt.WA_TranslucentBackground)
        species.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        species.addItems(supply_repo.get_all_species())
        
        breed = QLineEdit()
        breed_completer = QCompleter(pet_repo.get_unique_breeds())
        breed_completer.setCaseSensitivity(Qt.CaseInsensitive)
        breed.setCompleter(breed_completer)
        
        gender = QComboBox()
        gender.view().window().setAttribute(Qt.WA_TranslucentBackground)
        gender.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        gender.setView(QListView())
        gender.addItems([tr(g) for g in GENDER_OPTIONS])
        age_months = QSpinBox()
        age_months.setMaximum(600)
        weight = QDoubleSpinBox()
        weight.setMaximum(500.0)
        
        client_selector = QComboBox()
        client_selector.setView(QListView())
        client_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        client_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        client_selector.setEditable(True)
        client_selector.setInsertPolicy(QComboBox.NoInsert)
        client_selector.completer().setFilterMode(Qt.MatchContains)
        client_selector.setPlaceholderText(tr("Select Owner..."))
        clients = client_repo.get_clients()
        for c in clients:
            client_selector.addItem(c["owner_name"], c["client_id"])
        client_selector.setCurrentIndex(-1)
        
        layout.addRow(tr("Pet Name*:"), pet_name)
        layout.addRow(tr("Species:"), species)
        layout.addRow(tr("Breed:"), breed)
        layout.addRow(tr("Gender:"), gender)
        layout.addRow(tr("Age (Months):"), age_months)
        layout.addRow(tr("Weight (kg):"), weight)
        layout.addRow(tr("Owner*:"), client_selector)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            selected_client_id = client_selector.currentData()
            name_val = pet_name.text().strip().capitalize()
            species_val = species.currentText()
            breed_val = breed.text().strip().capitalize()
            gender_val = gender.currentText()
            age_val = age_months.value()
            weight_val = weight.value()
            
            if not name_val:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Pet name is required."))
                return
            
            if selected_client_id is None:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Owner selection is required."))
                return
            
            # Check for duplicate pet
            existing = pet_repo.get_existing_pet(name_val, species_val, breed_val, gender_val, selected_client_id)
            
            if existing:
                # Check if age or weight is different
                if age_val != existing["age_months"] or weight_val != existing["weight"]:
                    msg = tr("There is a pet already with the same data but different age or weight. Do you want to update the current record?")
                    reply = QMessageBox.question(dialog, tr("Duplicate Pet Found"), msg, QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.Yes:
                        pet_repo.update_pet_details(existing["id"], age_val, weight_val)
                else:
                    QMessageBox.information(dialog, tr("Information"), tr("Pet is already recorded."))
            else:
                # Add as new if no duplicate found
                pet_repo.add_pet(
                    name_val, 
                    species_val, 
                    breed_val, 
                    gender_val,
                    age_val, 
                    weight_val, 
                    selected_client_id
                )
            
            self.refresh_pets()
            self.data_changed.emit()
            dialog.accept()
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def refresh_pets(self, text=""):
        """Updates the pets table from database."""
        filter_field = self.filters["Pets"].currentText()
        data = pet_repo.get_pets(text, filter_field)
        keys = ["pet_id", "pet_name", "species", "breed", "gender", "age_months", "weight"]
        
        def pet_formatter(key, val, _item):
            if key == "age_months":
                return format_age(val)
            return val
            
        self._populate_table("Pets", data, keys, pet_formatter)
    
    def delete_selected_pet(self):
        """Deletes the selected pet after confirmation."""
        self._handle_deletion_confirm(
            "Pets", 0, 1, 
            pet_repo.delete_pet, self.refresh_pets, "pet"
        )
    
    def edit_pet_dialog(self, row):
        """Opens a dialog to edit an existing pet's information."""
        table = self.tables["Pets"]
        pet_id = table.item(row, 0).data(Qt.DisplayRole)
        
        # Fetch full data to populate the dialog correctly
        data = next((p for p in pet_repo.get_pets() if p["pet_id"] == pet_id), None)
        if not data: return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit Pet: {name}").format(name=data['pet_name']))
        dialog.setFixedSize(*DIALOG_CONFIG["pet"])
        layout = QFormLayout(dialog)

        name = QLineEdit(data['pet_name'])
        species = QComboBox(); species.setView(QListView()); species.addItems(supply_repo.get_all_species()); species.setCurrentText(data['species'])
        species.view().window().setAttribute(Qt.WA_TranslucentBackground)
        species.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        
        breed = QLineEdit(data['breed'])
        breed_completer = QCompleter(pet_repo.get_unique_breeds())
        breed_completer.setCaseSensitivity(Qt.CaseInsensitive)
        breed.setCompleter(breed_completer)
        
        gender = QComboBox(); gender.setView(QListView()); gender.addItems(GENDER_OPTIONS); gender.setCurrentText(data['gender'])
        gender.view().window().setAttribute(Qt.WA_TranslucentBackground)
        gender.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        age = QSpinBox(); age.setMaximum(600); age.setValue(data['age_months'])
        weight = QDoubleSpinBox(); weight.setMaximum(500.0); weight.setValue(data['weight'])
        
        client_selector = QComboBox()
        client_selector.setView(QListView())
        client_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        client_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        client_selector.setEditable(True)
        client_selector.setInsertPolicy(QComboBox.NoInsert)
        client_selector.completer().setFilterMode(Qt.MatchContains)
        clients = client_repo.get_clients()
        for c in clients:
            client_selector.addItem(c["owner_name"], c["client_id"])
            if c["client_id"] == data["client_id"]: client_selector.setCurrentIndex(client_selector.count()-1)

        layout.addRow(tr("Pet Name*:"), name)
        layout.addRow(tr("Species:"), species)
        layout.addRow(tr("Breed:"), breed)
        layout.addRow(tr("Gender:"), gender)
        layout.addRow(tr("Age (Months):"), age)
        layout.addRow(tr("Weight (kg):"), weight)
        layout.addRow(tr("Owner:"), client_selector)

        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        def handle_save():
            if pet_repo.update_pet(pet_id, name.text().strip().capitalize(), species.currentText(), 
                                   breed.text().strip().capitalize(), gender.currentText(), 
                                   age.value(), weight.value(), client_selector.currentData()):
                self.refresh_pets(); self.data_changed.emit(); dialog.accept()
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_save); buttons.rejected.connect(dialog.reject)
        dialog.exec()

    # __________________________ Visits Functions __________________________
    def add_visit_dialog(self):
        """Opens dialog to add a new visit record."""
        dialog = AddVisitDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_visits()
            self.data_changed.emit()
    
    def edit_visit_dialog(self, row):
        """Opens a simple dialog to edit visit diagnosis and notes."""
        table = self.tables["Visits"]
        visit_id = table.item(row, 0).data(Qt.DisplayRole)
        date_str = table.item(row, 1).text()
        curr_diag = table.item(row, 4).text()
        is_consult = table.item(row, 5).text() == tr("Yes")
        curr_notes = table.item(row, 6).text()

        dialog = EditVisitDialog(visit_id, date_str, curr_diag, is_consult, curr_notes, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_visits()
            self.data_changed.emit()

    def refresh_visits(self, text=""):
        """Updates the visits table from database."""
        filter_field = self.filters["Visits"].currentText()
        data = visit_repo.get_visits(text, filter_field)
        keys = ["visit_id", "visit_date", "owner_name", "pet_name", "diagnosis", "consult", "notes", "pet_id", "receipt_id"]
        palette = get_active_palette()
        
        def visit_formatter(key, val, item):
            if key == "consult":
                is_yes = (val == 1)
                item.setForeground(palette.qcolor("state_success") if is_yes else palette.qcolor("state_danger"))
                return tr("Yes") if is_yes else tr("No")
            return val
        
        self._populate_table("Visits", data, keys, visit_formatter)
    
    def delete_selected_visit(self):
        """Deletes the selected visit record after confirmation."""
        self._handle_deletion_confirm(
            "Visits", 0, 1, 
            visit_repo.delete_visit, self.refresh_visits, "visit"
        )
    
    # __________________________ Appointments Functions __________________________
    def add_appointment_dialog(self):
        """Opens dialog to schedule a new appointment."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Appointment"))
        dialog.setFixedSize(*DIALOG_CONFIG["appointment"])
        layout = QFormLayout(dialog)
        
        appointment_date = QDateTimeEdit(calendarPopup=True)
        appointment_date.setDateTime(QDateTime.currentDateTime())
        appointment_date.setDisplayFormat("yyyy-MM-dd HH:mm")
        service = QComboBox()
        service.setView(QListView())
        service.view().window().setAttribute(Qt.WA_TranslucentBackground)
        service.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        service.setEditable(True)
        service.addItems(supply_repo.get_all_services())
        service.lineEdit().setPlaceholderText(tr("Consultation"))
        status = QComboBox()
        status.setView(QListView())
        status.view().window().setAttribute(Qt.WA_TranslucentBackground)
        status.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for s in STATUS_OPTIONS:
            status.addItem(tr(s), s)
        notes = QLineEdit()
        
        # Client Selector
        pet_selector = QComboBox()
        pet_selector.setView(QListView())
        pet_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        pet_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        pet_selector.setEditable(True)
        pet_selector.setInsertPolicy(QComboBox.NoInsert)
        pet_selector.completer().setFilterMode(Qt.MatchContains)
        
        client_selector = QComboBox()
        client_selector.setView(QListView())
        client_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        client_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        client_selector.setEditable(True)
        client_selector.setInsertPolicy(QComboBox.NoInsert)
        client_selector.completer().setFilterMode(Qt.MatchContains)
        client_selector.setPlaceholderText(tr("Select Owner..."))

        clients = client_repo.get_clients()
        
        for c in clients:
            client_selector.addItem(c["owner_name"], c["client_id"])
        client_selector.setCurrentIndex(-1)
        
        # Initial population of pet_selector based on the first *valid* client, if any
        self._update_pet_selector_combo(pet_selector, client_selector.currentData())
        
        # Connect client_selector to update pet_selector
        client_selector.currentIndexChanged.connect(
            lambda: self._update_pet_selector_on_client_change(client_selector, pet_selector)
        )
        
        layout.addRow(tr("Appointment Date:"), appointment_date)
        layout.addRow(tr("Service:"), service)
        layout.addRow(tr("Status:"), status)
        layout.addRow(tr("Notes:"), notes)
        layout.addRow(tr("Owner*:"), client_selector)
        layout.addRow(tr("Select Pet:"), pet_selector)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            selected_client_id = client_selector.currentData()
            selected_pet_id = pet_selector.currentData()
            
            if selected_client_id is None:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Please select a client for the appointment."))
                return
            
            service_text = service.currentText().strip().capitalize() or "Consultation"
            appointment_repo.add_appointment(
                appointment_date.dateTime().toString("yyyy-MM-dd HH:mm"), 
                service_text,
                status.currentData(), 
                notes.text().strip().capitalize(), 
                selected_client_id, 
                selected_pet_id
            )
            self.refresh_appointments()
            self.data_changed.emit()
            dialog.accept()
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def edit_appointment_dialog(self, row):
        """Opens a dialog to edit an existing appointment."""
        table = self.tables["Appointments"]
        app_id = table.item(row, 0).data(Qt.DisplayRole)
        
        # Fetch full data to populate
        data = next((a for a in appointment_repo.get_appointments() if a["appointment_id"] == app_id), None)
        if not data: return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit Appointment"))
        dialog.setFixedSize(*DIALOG_CONFIG["appointment"])
        layout = QFormLayout(dialog)

        date_edit = QDateTimeEdit(QDateTime.fromString(data['appointment_date'], "yyyy-MM-dd HH:mm"), calendarPopup=True)
        service = QComboBox(); service.setView(QListView()); service.setEditable(True); service.addItems(supply_repo.get_all_services()); service.setCurrentText(data['service'])
        service.view().window().setAttribute(Qt.WA_TranslucentBackground)
        service.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        status = QComboBox()
        status.setView(QListView())
        for s in STATUS_OPTIONS:
            status.addItem(tr(s), s)
            if s == data['status']: status.setCurrentIndex(status.count() - 1)
        status.view().window().setAttribute(Qt.WA_TranslucentBackground)
        status.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        notes = QLineEdit(data['notes'])
        
        client_sel = QComboBox()
        client_sel.setView(QListView())
        client_sel.view().window().setAttribute(Qt.WA_TranslucentBackground)
        client_sel.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        client_sel.setEditable(True)
        client_sel.setInsertPolicy(QComboBox.NoInsert)
        client_sel.completer().setFilterMode(Qt.MatchContains)
        for c in client_repo.get_clients():
            client_sel.addItem(c["owner_name"], c["client_id"])
            if c["client_id"] == data["client_id"]: client_sel.setCurrentIndex(client_sel.count()-1)
        
        pet_sel = QComboBox()
        pet_sel.setView(QListView())
        pet_sel.view().window().setAttribute(Qt.WA_TranslucentBackground)
        pet_sel.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        pet_sel.setEditable(True)
        pet_sel.setInsertPolicy(QComboBox.NoInsert)
        pet_sel.completer().setFilterMode(Qt.MatchContains)
        self._update_pet_selector_combo(pet_sel, client_sel.currentData())
        pet_sel.setCurrentText(data['pet_name'])

        layout.addRow(tr("Date:"), date_edit); layout.addRow(tr("Service:"), service); layout.addRow(tr("Status:"), status)
        layout.addRow(tr("Notes:"), notes); layout.addRow(tr("Owner:"), client_sel); layout.addRow(tr("Pet:"), pet_sel)

        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        def handle_save():
            if appointment_repo.update_appointment(
                app_id, date_edit.dateTime().toString("yyyy-MM-dd HH:mm"),
                service.currentText(), status.currentData(), notes.text(),
                client_sel.currentData(), pet_sel.currentData()
            ):
                self.refresh_appointments(); self.data_changed.emit(); dialog.accept()

        layout.addWidget(buttons)
        buttons.accepted.connect(handle_save); buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def _update_pet_selector_on_client_change(self, client_selector, pet_selector):
        """Helper to update the pet selector based on the selected client."""
        selected_client_id = client_selector.currentData()
        self._update_pet_selector_combo(pet_selector, selected_client_id)
    
    def _update_pet_selector_combo(self, pet_selector, client_id):
        """Populates the pet_selector QComboBox with pets for the given client_id."""
        pet_selector.clear()
        pet_selector.setPlaceholderText(tr("Select Pet..."))
        pet_selector.setCurrentIndex(-1)
        
        if client_id is not None:
            pets = pet_repo.get_pets_for_client(client_id)
            for p in pets:
                pet_selector.addItem(p['pet_name'], p["pet_id"])
    
    def refresh_appointments(self, text=""):
        """Updates the appointments table from database."""
        filter_field = self.filters["Appointments"].currentText()
        data = appointment_repo.get_appointments(text, filter_field)
        keys = ["appointment_id", "appointment_date", "owner_name", "pet_name", "service", "status", "notes", "client_id", "pet_id"]
        
        palette = get_active_palette()
        status_map = {
            "Pending": palette.qcolor("state_warning"),
            "Completed": palette.qcolor("state_success"),
            "Canceled": palette.qcolor("state_danger")
        }

        def appointment_formatter(key, val, item):
            if key == "status":
                status_text = str(val) if val else "Pending"
                item.setForeground(status_map.get(status_text, palette.qcolor("text_primary")))
                return tr(status_text)
            return val
        
        self._populate_table("Appointments", data, keys, appointment_formatter)
    
    def delete_selected_appointment(self):
        """Deletes the selected appointment after confirmation."""
        self._handle_deletion_confirm(
            "Appointments", 0, 1, 
            appointment_repo.delete_appointment, self.refresh_appointments, "appointment"
        )
