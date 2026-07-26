"""
Follow-up Dialog for the PET Application.
Allows scheduling, viewing, and managing follow-up visits.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QDateTimeEdit, QMessageBox, QHeaderView, QGroupBox, QSplitter,
    QDialogButtonBox, QWidget, QFrame
)
from PyQt5.QtCore import Qt, QDateTime, QSize, pyqtSignal
from PyQt5.QtGui import QIcon

import src.core.repositories.followup_repo as followup_repo
import src.core.repositories.user_repo as user_repo
import src.core.repositories.lookup_repo as lookup_repo
from src.core.permissions import can
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette


class FollowupDialog(QDialog):
    """
    Dialog for managing follow-up visits.
    Allows adding, editing, and deleting follow-ups for a visit.
    """

    data_changed = pyqtSignal()

    def __init__(self, visit_id=None, pet_name="", owner_name="", parent=None, current_user=None):
        super().__init__(parent)
        self._visit_id = visit_id
        self._pet_name = pet_name
        self._owner_name = owner_name
        self._current_user = current_user
        self.setWindowTitle(tr("Follow-up Management"))
        self.setMinimumSize(660, 500)
        self._setup_ui()
        if visit_id:
            self._load_followups()

    def _setup_ui(self):
        palette = get_active_palette()
        main_layout = QVBoxLayout(self)

        # Info section
        if self._visit_id and self._pet_name:
            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>{tr('Pet:')}</b> {self._pet_name}"))
            if self._owner_name:
                info_layout.addWidget(QLabel(f"<b>{tr('Owner:')}</b> {self._owner_name}"))
            info_layout.addStretch()
            main_layout.addLayout(info_layout)

        # Follow-up list table
        self.followup_table = QTableWidget()
        self.followup_table.setColumnCount(4)
        self.followup_table.setHorizontalHeaderLabels([
            tr("Follow-up ID"), tr("Date"), tr("Status"), tr("Notes")
        ])
        self.followup_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.followup_table.setSelectionMode(QTableWidget.SingleSelection)
        self.followup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.followup_table.hideColumn(0)
        self.followup_table.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.followup_table)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton(tr("+ Schedule Follow-up"))
        self.add_btn.clicked.connect(self._add_followup)
        self.edit_btn = QPushButton(tr("Edit Selected"))
        self.edit_btn.clicked.connect(self._edit_followup)
        self.delete_btn = QPushButton(tr("Delete Selected"))
        self.delete_btn.clicked.connect(self._delete_followup)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        main_layout.addLayout(close_layout)

    def _load_followups(self):
        """Loads follow-ups for the current visit."""
        if not self._visit_id:
            return

        followups = followup_repo.get_followups_for_visit(self._visit_id)
        self.followup_table.setRowCount(0)

        for fup in followups:
            row = self.followup_table.rowCount()
            self.followup_table.insertRow(row)
            self.followup_table.setItem(row, 0, QTableWidgetItem(str(fup["followup_id"])))
            self.followup_table.setItem(row, 1, QTableWidgetItem(fup["followup_date"] or ""))
            self.followup_table.setItem(row, 2, QTableWidgetItem(fup.get("status") or tr("Pending")))
            self.followup_table.setItem(row, 3, QTableWidgetItem(fup.get("notes") or ""))

    def _add_followup(self):
        """Opens dialog to add a new follow-up."""
        dialog = FollowupEditDialog(self._visit_id, self, current_user=self._current_user)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if followup_repo.add_followup(**data):
                self._load_followups()
                self.data_changed.emit()

    def _edit_followup(self):
        """Opens dialog to edit the selected follow-up."""
        row = self.followup_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a follow-up to edit."))
            return

        followup_id = int(self.followup_table.item(row, 0).text())
        followup_date = self.followup_table.item(row, 1).text()
        status = self.followup_table.item(row, 2).text()
        notes = self.followup_table.item(row, 3).text()

        dialog = FollowupEditDialog(
            self._visit_id, self, followup_id, followup_date, status, notes,
            current_user=self._current_user,
        )
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if followup_repo.update_followup(
                followup_id, data["followup_date"], data.get("state_id"), data["notes"], data.get("doctor_id")
            ):
                self._load_followups()
                self.data_changed.emit()

    def _delete_followup(self):
        """Deletes the selected follow-up after confirmation."""
        row = self.followup_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a follow-up to delete."))
            return

        followup_id = int(self.followup_table.item(row, 0).text())

        reply = QMessageBox.question(
            self, tr("Confirm Delete"),
            tr("Delete this follow-up record?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if followup_repo.delete_followup(followup_id):
                self._load_followups()
                self.data_changed.emit()
                QMessageBox.information(self, tr("Success"), tr("Follow-up deleted."))
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to delete follow-up."))


class FollowupEditDialog(QDialog):
    """Dialog for adding/editing a single follow-up record.

    Opened on its own when scheduling a follow-up, from the follow-up list
    (FollowupDialog), and for a follow-up row of the Appointments tab.
    """

    def __init__(self, visit_id, parent=None, followup_id=None,
                 followup_date="", status="", notes="", current_user=None):
        super().__init__(parent)
        self._visit_id = visit_id
        self._followup_id = followup_id
        self._current_user = current_user or {}
        self._status = status or ""
        self.setWindowTitle(tr("Edit Follow-up") if followup_id else tr("Schedule Follow-up"))
        self.setMinimumWidth(440)
        self._setup_ui(followup_date, notes)

    def _setup_ui(self, followup_date, notes):
        layout = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(layout)
        root.addStretch(1)

        # Default follow-up date (7 days from now)
        default_dt = QDateTime.currentDateTime().addDays(7)
        if followup_date:
            parsed = QDateTime.fromString(followup_date, "yyyy-MM-dd HH:mm")
            if parsed.isValid():
                default_dt = parsed

        self.date_edit = QDateTimeEdit(calendarPopup=True)
        self.date_edit.setDateTime(default_dt)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addRow(tr("Follow-up Date:"), self.date_edit)

        # Follow-up status (values come from the followup_status states lookup)
        self.status_combo = QComboBox()
        self._status_by_value = {}
        for value, state_id in lookup_repo.get_followup_statuses():
            self.status_combo.addItem(tr(value), state_id)
            self._status_by_value[value] = state_id
        if self.status_combo.count() == 0:
            self.status_combo.addItem(tr("Pending"), None)
        # Pre-select the current status when editing (defaults to Pending).
        select_value = self._status if self._status in self._status_by_value else "Pending"
        idx = self.status_combo.findData(self._status_by_value.get(select_value))
        if idx < 0:
            idx = self.status_combo.findText(tr(select_value))
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)
        layout.addRow(tr("Status:"), self.status_combo)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText(tr("Optional notes about the follow-up"))
        self.notes_edit.setMaximumHeight(100)
        if notes:
            self.notes_edit.setPlainText(notes)
        layout.addRow(tr("Notes:"), self.notes_edit)

        self.doctor_combo = QComboBox()
        self.doctor_combo.addItem(tr("Use original visit doctor"), None)
        for doctor in user_repo.get_doctors():
            self.doctor_combo.addItem(doctor["doctor_name"], doctor["doctor_id"])
        self.doctor_combo.setEnabled(can(self._current_user, "edit_records"))
        layout.addRow(tr("Follow-up Doctor:"), self.doctor_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self):
        if not self.date_edit.dateTime().isValid():
            QMessageBox.warning(self, tr("Validation Error"), tr("Please select a valid date and time."))
            return
        self.accept()

    def get_data(self):
        return {
            "visit_id": self._visit_id,
            "followup_date": self.date_edit.dateTime().toString("yyyy-MM-dd HH:mm"),
            "state_id": self.status_combo.currentData(),
            "notes": self.notes_edit.toPlainText().strip(),
            "doctor_id": self.doctor_combo.currentData(),
        }
