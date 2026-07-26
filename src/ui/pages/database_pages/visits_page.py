"""Visits module for the PET Application.
Provides a standalone 'Visits' page with dedicated Visits and Appointments tabs.
Owners and Pets are managed on the separate clients page (clients_page.py).
"""

from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QBrush, QColor, QIcon
from PyQt5.QtWidgets import (
    QWidget, QDialog, QDialogButtonBox, QDateTimeEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QTableWidgetItem, QPushButton, QMessageBox, QLineEdit, QFormLayout,
    QComboBox, QListView, QTextEdit
)

from src.core.repositories import client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.followup_repo as followup_repo
import src.core.repositories.user_repo as user_repo
import src.core.repositories.supply_repo as supply_repo
from src.core.repositories import pending_changes_repo
from src.config.constants import DATE_TIME_FORMAT_UI
from src.ui.dialogs.full_entry_dialog import AddFullEntryDialog
from src.ui.dialogs.followup_dialog import FollowupDialog, FollowupEditDialog
from src.ui.dialogs.quick_purchase_dialog import QuickPurchaseDialog
from src.ui.dialogs.info_dialogs import OwnerInfoDialog, PetInfoDialog, VisitInfoDialog
from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.modules.base_page import (
    BaseEntityPage,
    SEARCH_DEBOUNCE_MS,
    CLEAR_ICON_SIZE,
    CLEAR_BUTTON_SIZE,
    CLEAR_ICON,
)
from src.core.permissions import can

#=========================================== CONSTANTS ===================================================#

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
    ("Consult", "consult", 90),
    ("Notes", "notes", 400),
    ("Receipt ID", "receipt_id", 100),
]

# (Header Name, Database Key)
VISITS_TAB_CONFIG = {
    "Visits": {
        "headers": ["Visit ID", "Date", "Owner Name", "Pet Name", "Diagnosis", "Consult", "Receipt ID"],
        "hide": [],
        "col_widths":[70, 150, 180, 150, 150, 100, 100], # Visit ID, Date, Owner, Pet, Diag, Consult, Receipt ID
        "filter": ["All", "Date", "Owner Name", "Pet Name", "Diagnosis", "Consult"],
        "link_cells": [0, 2, 3, 6]  # Visit ID, Owner Name, Pet Name, Receipt ID (clickable)
    },
    "Appointments": {
        "headers": ["ID", "Date", "Owner Name", "Pet Name", "Service", "Status"],
        "hide": [0], # Appointment ID
        "col_widths":[0, 160, 180, 150, 200, 100], # Appointment ID, Date, Owner, Pet, Service, Status
        "filter": ["All", "Date", "Owner Name", "Pet Name", "Service", "Status"],
        "link_cells": [2, 3]  # Owner Name, Pet Name (clickable)
    }
}

STATUS_OPTIONS = ["Pending", "Completed", "Canceled"]
APPOINTMENT_DIALOG_SIZE = (440, 340)

#=========================================== CODE ===================================================#

# Re-exported for backward compatibility (tests import via visits_page).
class VisitsPage(BaseEntityPage):
    """Dedicated clinical page containing only Visits and Appointments tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # visit_id -> authoritative repo row, populated by refresh_visits; used
        # so _visit_row_from_table never parses displayed table cells.
        self._visits_by_id = {}

        # Map internal tab logic to callbacks
        self.actions = {
            "Visits": {"add": self.add_visit_dialog, "delete": self.delete_selected_visit, "refresh": self.refresh_visits},
            "Appointments": {"add": self.add_appointment_dialog, "delete": self.delete_selected_appointment, "refresh": self.refresh_appointments}
        }

        self._setup_ui()
        self.table = self.tables["Visits"]

        self.quick_purchase_btn = QPushButton(tr("Quick Purchase"))
        self.quick_purchase_btn.setObjectName("quick_purchase_btn")
        self.quick_purchase_btn.clicked.connect(self.open_quick_purchase_dialog)
        self.tabs.setCornerWidget(self.quick_purchase_btn, Qt.TopRightCorner)

        self.followup_btn = QPushButton(tr("Follow-up"))
        self.followup_btn.clicked.connect(self.open_followup_dialog)
        visits_controls = self.tabs.widget(0).layout().itemAt(0).layout()
        visits_controls.insertWidget(1, self.followup_btn)

        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)
        self.set_current_user(self._current_user)

    def _setup_ui(self):
        """Initializes the main layout and the tabbed interface."""
        for name in ("Visits", "Appointments"):
            cfg = VISITS_TAB_CONFIG[name]
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

        # Set default sorting for the Visits tab by Visit Date (index 1) Descending
        self.tables["Visits"].sortByColumn(1, Qt.DescendingOrder)
        # Set default sorting for the Appointments tab by Appointment Date (index 1) Descending
        self.tables["Appointments"].sortByColumn(1, Qt.DescendingOrder)

        # Refresh tabs on change
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.on_tab_changed(0)

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

    def set_current_user(self, user):
        """Propagate user, apply permissions, and re-filter the Appointments tab."""
        super().set_current_user(user)
        self.quick_purchase_btn.setVisible(can(user, "quick_purchase"))
        self.followup_btn.setVisible(can(user, "add_visit"))
        if "Appointments" in self.search_bars:
            self.refresh_appointments(self.search_bars["Appointments"].text())

    def retranslate_ui(self):
        """Updates UI text and repopulates tables that contain translated cell values."""
        super().retranslate_ui()
        self.quick_purchase_btn.setText(tr("Quick Purchase"))
        self.followup_btn.setText(tr("Follow-up"))
        self.refresh_visits(self.search_bars["Visits"].text())
        self.refresh_appointments(self.search_bars["Appointments"].text())

    def on_row_double_clicked(self, category, row):
        """Triggers the appointment edit flow on the Appointments tab only.

        Admins write directly; doctors/staff submit a pending-change request.
        """
        if category != "Appointments":
            return
        user_can_edit    = can(self._current_user, "edit_records")
        user_can_request = can(self._current_user, "request_change")
        if not user_can_edit and not user_can_request:
            return
        self.edit_appointment_dialog(row)

    def on_link_clicked(self, category, row, col, value):
        """Opens a read-only info dialog when a name/receipt link is clicked."""
        col_name = self._col_name_for(category, col)
        if col_name == "id" and category == "Visits":
            visit_row = self._visit_row_from_table(category, row, value)
            if visit_row:
                VisitInfoDialog(visit_row, self, current_user=self._current_user).exec_()
            return

        if col_name == "receipt_id":
            table = self.tables[category]
            receipt_id = value
            cell_item = table.item(row, col)
            if cell_item is not None:
                receipt_id = cell_item.data(Qt.DisplayRole)
                if receipt_id is None:
                    receipt_id = cell_item.text()
            try:
                receipt_id = int(receipt_id)
            except (TypeError, ValueError):
                return
            if sales_repo.get_receipt(receipt_id) is not None:
                receipt_dialog = ReceiptInfoDialog(
                    receipt_id, self, current_user=self._current_user
                )
                # A payment made here changes balances the rest of the app shows.
                receipt_dialog.data_changed.connect(self.data_changed.emit)
                receipt_dialog.exec_()
            return

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
        # Visits & Appointments share the same layout
        return {0: "id", 2: "owner_name", 3: "pet_name", 6: "receipt_id"}.get(col)

    def _visit_row_from_table(self, category, row, value):
        """Returns the authoritative visit row for a clicked Visits link.

        Uses the repo data cached by :meth:`refresh_visits` instead of parsing
        the displayed cells — the consult flag is receipt-driven and the cells
        hold localized, formatted text.
        """
        try:
            visit_id = int(value)
        except (TypeError, ValueError):
            return None
        return self._visits_by_id.get(visit_id)

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

    def open_followup_dialog(self):
        row = self.tables["Visits"].currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a visit first."))
            return

        table = self.tables["Visits"]
        visit_id = table.item(row, 0).data(Qt.DisplayRole)
        owner_name = table.item(row, 2).text()
        pet_name = table.item(row, 3).text()
        dialog = FollowupDialog(
            visit_id=visit_id,
            pet_name=pet_name,
            owner_name=owner_name,
            parent=self,
            current_user=self._current_user,
        )
        if dialog.exec() == QDialog.Accepted:
            self.refresh_visits(self.search_bars["Visits"].text())
            self.data_changed.emit()

    def add_visit_dialog(self):
        dialog = AddFullEntryDialog(self, current_user=self._current_user)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_visits(self.search_bars["Visits"].text())
            self.data_changed.emit()

    def refresh_visits(self, text=""):
        """Updates the visits table from database."""
        filter_field = self.filter_key("Visits")
        data = visit_repo.get_visits(text, filter_field)
        keys = ["visit_id", "visit_date", "owner_name", "pet_name", "diagnosis", "consult", "receipt_id"]
        palette = get_active_palette()

        self._visits_by_id = {
            int(r["visit_id"]): r
            for r in data if r.get("visit_id") is not None
        }

        def visit_formatter(key, val, item):
            if key == "consult":
                is_yes = (val == 1)
                item.setForeground(palette.qcolor("state_success") if is_yes else palette.qcolor("state_danger"))
                return tr("Yes") if is_yes else tr("No")
            if key in ("visit_id", "owner_name", "pet_name", "receipt_id"):
                return self.make_link_item(val)
            return val

        self._populate_table("Visits", data, keys, visit_formatter)

    def delete_selected_visit(self):
        """Deletes the selected visit record after confirmation."""
        self._handle_deletion_confirm(
            "Visits", 0, 1,
            visit_repo.delete_visit, self.refresh_visits, "visit"
        )

    def add_appointment_dialog(self):
        """Opens dialog to schedule a new appointment."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Appointment"))
        dialog.setFixedSize(*APPOINTMENT_DIALOG_SIZE)
        layout = QFormLayout()

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
                selected_pet_id,
                doctor_id=user_repo.get_doctor_id(self._current_user),
                user_id=(self._current_user or {}).get("user_id")
            )
            self.refresh_appointments()
            self.data_changed.emit()
            dialog.accept()

        root = QVBoxLayout(dialog)
        root.addLayout(layout)
        root.addStretch(1)
        root.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)

        dialog.exec()

    def edit_appointment_dialog(self, row):
        """Opens the editor for the selected row of the Appointments tab.

        The tab lists scheduled appointments AND follow-ups, so the row kind
        decides which record (and which table) is edited. Both kinds share the
        hidden id column, and a followup_id can collide with an appointment_id,
        so the kind must be read from the row itself.
        """
        kind, record_id = self._appointment_row_record(row)
        if record_id is None:
            return
        if kind == "followup":
            self.edit_followup_dialog(record_id)
            return
        self._edit_scheduled_appointment(record_id)

    def _appointment_row_record(self, row):
        """Returns (kind, record_id) for an Appointments row.

        ``kind`` is 'appointment' or 'followup'; ``record_id`` is None when the
        row cannot be resolved.
        """
        table = self.tables.get("Appointments")
        if table is None or not (0 <= row < table.rowCount()):
            return None, None
        item = table.item(row, 0)
        if item is None:
            return None, None
        try:
            record_id = int(item.data(Qt.DisplayRole))
        except (TypeError, ValueError):
            record_id = None
        return item.data(Qt.UserRole) or "appointment", record_id

    def edit_followup_dialog(self, followup_id):
        """Edits a follow-up row of the Appointments tab (writes to `followups`)."""
        data = followup_repo.get_followup(int(followup_id))
        if data is None:
            return
        editor = FollowupEditDialog(
            data["visit_id"], self,
            followup_id=data["followup_id"],
            followup_date=data["followup_date"] or "",
            status=data["status"] or "",
            notes=data["notes"] or "",
            current_user=self._current_user,
        )
        if editor.exec() != QDialog.Accepted:
            return
        payload = editor.get_data()

        if can(self._current_user, "edit_records"):
            if not followup_repo.update_followup(
                data["followup_id"], payload["followup_date"], payload.get("state_id"),
                payload["notes"], payload.get("doctor_id"),
            ):
                QMessageBox.critical(self, tr("Error"), tr("Failed to save record to database."))
                return
            self.refresh_appointments(self.search_bars["Appointments"].text())
            self.data_changed.emit()
            return

        pid = pending_changes_repo.submit_change(
            (self._current_user or {}).get("user_id"),
            "followups", data["followup_id"], "UPDATE",
            {
                "followup_date": payload["followup_date"],
                "state_id": payload.get("state_id"),
                "notes": payload["notes"],
                "doctor_id": payload.get("doctor_id"),
            },
        )
        if pid:
            QMessageBox.information(
                editor, tr("Submitted"),
                tr("Your change has been submitted for admin approval."),
            )
        else:
            QMessageBox.critical(editor, tr("Error"), tr("Failed to submit change request."))

    def _edit_scheduled_appointment(self, app_id):
        """Opens the appointment editor for a scheduled-appointment row."""
        # Match on row_type as well as the id: a followup_id may equal an
        # appointment_id, and get_appointments() returns both kinds.
        data = next(
            (a for a in appointment_repo.get_appointments()
             if a.get("row_type") == "appointment" and a["appointment_id"] == app_id),
            None,
        )
        if not data:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit Appointment"))
        dialog.setFixedSize(*APPOINTMENT_DIALOG_SIZE)
        layout = QFormLayout()

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
            new_date      = date_edit.dateTime().toString("yyyy-MM-dd HH:mm")
            new_service   = service.currentText()
            new_status    = status.currentData()
            new_notes     = notes.text()
            new_client_id = client_sel.currentData()
            new_pet_id    = pet_sel.currentData()

            if can(self._current_user, "edit_records"):
                if appointment_repo.update_appointment(
                    app_id, new_date, new_service, new_status, new_notes,
                    new_client_id, new_pet_id,
                    doctor_id=user_repo.get_doctor_id(self._current_user),
                    user_id=(self._current_user or {}).get("user_id")
                ):
                    self.refresh_appointments(); self.data_changed.emit(); dialog.accept()
            else:
                user_id = (self._current_user or {}).get("user_id")
                payload = {
                    "appointment_date": new_date,
                    "service":          new_service,
                    "status":           new_status,
                    "notes":            new_notes,
                    "client_id":        new_client_id,
                    "pet_id":           new_pet_id,
                }
                pid = pending_changes_repo.submit_change(
                    user_id, "appointments", app_id, "UPDATE", payload
                )
                if pid:
                    QMessageBox.information(
                        dialog, tr("Submitted"),
                        tr("Your change has been submitted for admin approval."),
                    )
                    dialog.accept()
                else:
                    QMessageBox.critical(dialog, tr("Error"), tr("Failed to submit change request."))

        root = QVBoxLayout(dialog)
        root.addLayout(layout)
        root.addStretch(1)
        root.addWidget(buttons)
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
        """Updates the appointments table from database.

        Admins and staff see all appointments and follow-ups.
        Doctors see only rows assigned to their doctor_id (strict match).
        Follow-up rows are highlighted in light blue (state_info colour).
        """
        filter_field = self.filter_key("Appointments")

        # Determine doctor filter: doctors see only their own rows.
        doctor_id = None
        if can(self._current_user, "view_own_appointments") and \
                not can(self._current_user, "view_all_appointments"):
            doctor_id = user_repo.get_doctor_id(self._current_user)

        data = appointment_repo.get_appointments(text, filter_field, doctor_id=doctor_id)
        keys = ["appointment_id", "appointment_date", "owner_name", "pet_name",
                "service", "status"]

        palette = get_active_palette()
        status_map = {
            "Pending":   palette.qcolor("state_warning"),
            "Completed": palette.qcolor("state_success"),
            "Canceled":  palette.qcolor("state_danger"),
            "Late":      palette.qcolor("state_late"),
        }
        followup_bg = palette.qcolor("state_info")
        # Use a semi-transparent tint so the row is clearly tinted but readable.
        followup_bg.setAlpha(60)

        # Populate manually so we can apply per-row background colouring.
        table = self.tables["Appointments"]
        table.setSortingEnabled(False)
        table.setRowCount(0)

        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)
            is_followup = row_data.get("row_type") == "followup"

            for col, key in enumerate(keys):
                item = QTableWidgetItem()
                val = row_data.get(key)

                if key == "status":
                    status_text = str(val) if val else ("Pending" if is_followup else "Pending")
                    item.setForeground(status_map.get(status_text, palette.qcolor("text_primary")))
                    item.setText(tr(status_text))
                elif key in ("owner_name", "pet_name"):
                    item = self.make_link_item(val)
                elif isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")

                if is_followup:
                    item.setBackground(QBrush(followup_bg))

                if key == "appointment_id":
                    # Appointments and follow-ups share this hidden id column, so
                    # the row kind travels with the row (UserRole) to keep the
                    # edit flow from writing one kind to the other's table.
                    item.setData(Qt.UserRole, row_data.get("row_type") or "appointment")

                table.setItem(row, col, item)

        table.setSortingEnabled(True)

    def delete_selected_appointment(self):
        """Deletes the selected appointment after confirmation."""
        self._handle_deletion_confirm(
            "Appointments", 0, 1,
            appointment_repo.delete_appointment, self.refresh_appointments, "appointment"
        )

    def refresh_visits_table(self, text=""):
        """Compatibility wrapper for existing MainWindow signal connections."""
        self.refresh_visits(text)

    def open_quick_purchase_dialog(self):
        dialog = QuickPurchaseDialog(self, current_user=self._current_user)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_visits(self.search_bars["Visits"].text())
            self.data_changed.emit()

