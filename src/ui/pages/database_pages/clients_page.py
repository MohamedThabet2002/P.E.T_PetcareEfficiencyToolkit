"""
Clinical management module for the PET Application.
Provides a tabbed interface for handling Clients (Owners) and Pets.
Visits and Appointments live in the separate visits page (visits_page.py).
"""

from PyQt5.QtWidgets import (
    QMessageBox, QDialog, QFormLayout, QVBoxLayout, QLineEdit, QTextEdit,
    QDialogButtonBox, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidgetItem,
    QCompleter, QListView
)
from PyQt5.QtCore import Qt

from src.utils.i18n import tr
import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.supply_repo as supply_repo
from src.utils.formatters import format_age
from src.ui.themes.color_palettes import ThemeManager
from src.modules.base_page import BaseEntityPage
from src.ui.dialogs.base_clinical_dialog import NOTES_BOX_HEIGHT
from src.ui.dialogs.info_dialogs import OwnerInfoDialog, PetInfoDialog

#=========================================== CONSTANTS ===================================================#

# --- Page Configuration Constants ---

GENDER_OPTIONS = ["Female", "Male", "Other"]

DIALOG_CONFIG = {
    "client": (440, 280), # Width, Height (name + phone + notes)
    "pet": (440, 480), # Width, Height
}

CLIENTS_TAB_CONFIG = {
    "Owners": {
        "headers": ["Client ID", "Owner Name", "Phone Number"],
        "hide": [0], # Client ID
        "col_widths":[0, 250, 150], # Client ID, Owner Name, Phone
        "filter": ["All", "Owner Name", "Phone Number"],
        "link_cells": [1]  # Owner Name (clickable -> owner info)
    },
    "Pets": {
        "headers": ["ID", "Pet Name", "Species", "Age"],
        "hide": [0], # Pet ID
        "col_widths":[0, 150, 100, 100], # Pet ID, Pet Name, Species, Age
        "filter": ["All", "Pet Name", "Species", "Age"],
        "link_cells": [1]  # Pet Name (clickable -> pet/owner info)
    }
}


#============================================== CODE =====================================================#

class ClientsPage(BaseEntityPage):
    """
    A page for managing clinical entities (Clients/Owners and Pets).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Map internal tab logic to callbacks
        self.actions = {
            "Owners": {"add": self.add_client_dialog, "delete": self.delete_selected_client, "refresh": self.refresh_clients},
            "Pets": {"add": self.add_pet_dialog, "delete": self.delete_selected_pet, "refresh": self.refresh_pets}
        }
        
        self._setup_ui()
        # Initial data load for the first tab
        self.on_tab_changed(0)
        # React to theme changes (Hot-reload / Settings toggle)
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)
    
    def _setup_ui(self):
        """Initializes the main layout and the tabbed interface."""
        # Dynamically build tabs based on config
        for name in ("Owners", "Pets"):
            cfg = CLIENTS_TAB_CONFIG[name]
            action = self.actions[name]
            self.create_tab(
                name=name,
                headers=cfg["headers"],
                filter_items=cfg["filter"],
                add_callback=action["add"],
                delete_callback=action["delete"],
                refresh_callback=action["refresh"],
                hide_cols=cfg["hide"],
                col_widths=cfg.get("col_widths"),
                link_cells=cfg.get("link_cells"),
            )
        
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
        """Updates UI text for the page."""
        super().retranslate_ui()

    def on_link_clicked(self, category, row, col, value):
        """Opens a read-only info dialog when a name link is clicked."""
        col_name = self._col_name_for(category, col)
        if col_name == "owner_name":
            owner = self._resolve_owner(category, row, value)
            if owner:
                OwnerInfoDialog(owner, self, current_user=self._current_user).exec_()
            return

        if col_name == "pet_name":
            pet = self._resolve_pet(category, row, value)
            if pet:
                PetInfoDialog(pet, self, current_user=self._current_user).exec_()
            return

    def _col_name_for(self, category, col):
        """Returns the semantic key for a given column in a table tab."""
        if category == "Owners":
            return {0: "id", 1: "owner_name"}.get(col)
        if category == "Pets":
            return {0: "id", 1: "pet_name"}.get(col)
        return None

    def _resolve_owner(self, category, row, owner_name):
        """Resolves owner info + pets from a table row showing an owner link."""
        owner_name = (owner_name or "").strip()
        client = next(
            (c for c in client_repo.get_clients() if c["owner_name"].strip().lower() == owner_name.lower()),
            None,
        )
        if not client:
            return None
        owner = {
            "client_id": client["client_id"],
            "owner_name": client["owner_name"],
            "phone_number": client["phone_number"],
        }
        owner["pets"] = pet_repo.get_pets_for_client(client["client_id"])
        return owner

    def _resolve_pet(self, category, row, pet_name):
        """Resolves full pet info from a table row showing a pet link."""
        pet_name = (pet_name or "").strip()
        pet = next(
            (p for p in pet_repo.get_pets() if p["pet_name"] == pet_name),
            None,
        )
        return pet or None

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
                
                # A formatter may return a fully-built QTableWidgetItem (e.g. a link).
                if isinstance(val, QTableWidgetItem):
                    table.setItem(row, col, val)
                    continue
                
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
            repo_func(entity_id, audit_user_id=(self._current_user or {}).get("user_id"))
            refresh_func()
            self.data_changed.emit()
    
    # __________________________ Clients Functions __________________________
    def add_client_dialog(self):
        """Opens dialog to add a new client."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Client"))
        dialog.setFixedSize(*DIALOG_CONFIG["client"])
        layout = QFormLayout()
        
        owner_name = QLineEdit()
        phone_number = QLineEdit()
        notes = QTextEdit()
        notes.setFixedHeight(NOTES_BOX_HEIGHT)
        notes.setPlaceholderText(tr("Add notes..."))
        
        layout.addRow(tr("Owner Name*:"), owner_name)
        layout.addRow(tr("Phone Number:"), phone_number)
        layout.addRow(tr("Notes") + ":", notes)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            name_input = owner_name.text().strip()
            phone_input = phone_number.text().strip()
            notes_input = notes.toPlainText().strip()
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

            client_repo.add_client(
                formatted_name, phone_input, notes_input,
                audit_user_id=(self._current_user or {}).get("user_id"),
            )
                
            self.refresh_clients()
            self.data_changed.emit()
            dialog.accept()
        
        root = QVBoxLayout(dialog)
        root.addLayout(layout)
        root.addStretch(1)
        root.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def refresh_clients(self, text=""):
        """Updates the owners table from database."""
        filter_field = self.filter_key("Owners")
        data = client_repo.get_clients(text, filter_field)
        keys = ["client_id", "owner_name", "phone_number"]

        def client_formatter(key, val, _item):
            if key == "owner_name":
                return self.make_link_item(val)
            return val

        self._populate_table("Owners", data, keys, client_formatter)
    
    def delete_selected_client(self):
        """Deletes the selected client after confirmation."""
        self._handle_deletion_confirm(
            "Owners", 0, 1, 
            client_repo.delete_client, self.refresh_clients, "client"
        )
    
    # __________________________ Pets Functions__________________________
    def add_pet_dialog(self):
        """Opens dialog to add a new pet."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Pet"))
        dialog.setFixedSize(*DIALOG_CONFIG["pet"])
        layout = QFormLayout()
        
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
        # English value kept as item data so the DB is language-independent.
        for _g in GENDER_OPTIONS:
            gender.addItem(tr(_g), _g)
        age_months = QSpinBox()
        age_months.setMaximum(600)
        weight = QDoubleSpinBox()
        weight.setMaximum(500.0)
        
        notes = QTextEdit()
        notes.setFixedHeight(NOTES_BOX_HEIGHT)
        notes.setPlaceholderText(tr("Add notes..."))
        
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
        layout.addRow(tr("Notes") + ":", notes)
        
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            selected_client_id = client_selector.currentData()
            name_val = pet_name.text().strip().capitalize()
            species_val = species.currentText()
            breed_val = breed.text().strip().capitalize()
            gender_val = gender.currentData() or gender.currentText()
            age_val = age_months.value()
            weight_val = weight.value()
            notes_val = notes.toPlainText().strip()
            
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
                        pet_repo.update_pet_details(
                            existing["id"], age_val, weight_val,
                            audit_user_id=(self._current_user or {}).get("user_id"),
                        )
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
                    selected_client_id,
                    notes=notes_val,
                    audit_user_id=(self._current_user or {}).get("user_id"),
                )
            
            self.refresh_pets()
            self.data_changed.emit()
            dialog.accept()
        
        root = QVBoxLayout(dialog)
        root.addLayout(layout)
        root.addStretch(1)
        root.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def refresh_pets(self, text=""):
        """Updates the pets table from database."""
        filter_field = self.filter_key("Pets")
        data = pet_repo.get_pets(text, filter_field)
        keys = ["pet_id", "pet_name", "species", "age_months"]
        
        def pet_formatter(key, val, item):
            if key == "age_months":
                return format_age(val)
            if key == "pet_name":
                return self.make_link_item(val)
            return val
            
        self._populate_table("Pets", data, keys, pet_formatter)
    
    def delete_selected_pet(self):
        """Deletes the selected pet after confirmation."""
        self._handle_deletion_confirm(
            "Pets", 0, 1, 
            pet_repo.delete_pet, self.refresh_pets, "pet"
        )