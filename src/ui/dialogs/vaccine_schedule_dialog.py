"""
Vaccine Schedule Dialog for the PET Application.
Manages vaccination schedules per species and shows due reminders.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QComboBox, QSpinBox, QLineEdit,
    QHeaderView, QAbstractItemView, QLabel, QFormLayout, QDialogButtonBox
)
from PyQt5.QtCore import Qt

import src.core.repositories.vaccine_schedule_repo as schedule_repo
import src.core.repositories.supply_repo as supply_repo
from src.utils.i18n import tr


class VaccineScheduleDialog(QDialog):
    """Dialog for managing vaccine schedules and viewing due reminders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Vaccine Schedules & Reminders"))
        self.setMinimumSize(820, 580)
        self._setup_ui()
        self._load_schedules()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Schedules Section ---
        sched_header = QHBoxLayout()
        sched_title = QLabel(tr("<b>Vaccination Schedules</b>"))
        sched_header.addWidget(sched_title)
        sched_header.addStretch()
        self.add_schedule_btn = QPushButton(tr("+ Add Schedule"))
        self.add_schedule_btn.clicked.connect(self._add_schedule)
        sched_header.addWidget(self.add_schedule_btn)
        layout.addLayout(sched_header)

        self.sched_table = QTableWidget()
        self.sched_table.setColumnCount(5)
        self.sched_table.setHorizontalHeaderLabels([
            tr("ID"), tr("Vaccine"), tr("Species"), tr("Interval (days)"), tr("Notes")
        ])
        self.sched_table.hideColumn(0)
        self.sched_table.horizontalHeader().setStretchLastSection(True)
        self.sched_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sched_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sched_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sched_table.setAlternatingRowColors(True)
        layout.addWidget(self.sched_table)

        sched_btns = QHBoxLayout()
        edit_sched_btn = QPushButton(tr("Edit"))
        edit_sched_btn.clicked.connect(self._edit_schedule)
        delete_sched_btn = QPushButton(tr("Delete"))
        delete_sched_btn.clicked.connect(self._delete_schedule)
        sched_btns.addWidget(edit_sched_btn)
        sched_btns.addWidget(delete_sched_btn)
        sched_btns.addStretch()
        layout.addLayout(sched_btns)

        # --- Reminders Section ---
        rem_header = QHBoxLayout()
        rem_title = QLabel(tr("<b>Due / Upcoming Reminders</b>"))
        rem_header.addWidget(rem_title)
        rem_header.addStretch()
        self.generate_btn = QPushButton(tr("Generate Reminders"))
        self.generate_btn.setToolTip(tr("Scan all pets and create due reminders based on schedules"))
        self.generate_btn.clicked.connect(self._generate_reminders)
        rem_header.addWidget(self.generate_btn)
        layout.addLayout(rem_header)

        self.rem_table = QTableWidget()
        self.rem_table.setColumnCount(6)
        self.rem_table.setHorizontalHeaderLabels([
            tr("ID"), tr("Pet"), tr("Owner"), tr("Vaccine"), tr("Due Date"), tr("Status")
        ])
        self.rem_table.hideColumn(0)
        self.rem_table.horizontalHeader().setStretchLastSection(True)
        self.rem_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rem_table.setSelectionMode(QTableWidget.SingleSelection)
        self.rem_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rem_table.setAlternatingRowColors(True)
        layout.addWidget(self.rem_table)

        rem_btns = QHBoxLayout()
        complete_btn = QPushButton(tr("Mark Completed"))
        complete_btn.clicked.connect(self._complete_reminder)
        skip_btn = QPushButton(tr("Skip"))
        skip_btn.clicked.connect(self._skip_reminder)
        delete_rem_btn = QPushButton(tr("Delete"))
        delete_rem_btn.clicked.connect(self._delete_reminder)
        rem_btns.addWidget(complete_btn)
        rem_btns.addWidget(skip_btn)
        rem_btns.addWidget(delete_rem_btn)
        rem_btns.addStretch()
        layout.addLayout(rem_btns)

        # Close
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

    def _load_schedules(self):
        schedules = schedule_repo.get_all_schedules()
        self.sched_table.setRowCount(0)
        for s in schedules:
            row = self.sched_table.rowCount()
            self.sched_table.insertRow(row)
            self.sched_table.setItem(row, 0, QTableWidgetItem(str(s["schedule_id"])))
            self.sched_table.setItem(row, 1, QTableWidgetItem(s["vaccine_name"] or ""))
            self.sched_table.setItem(row, 2, QTableWidgetItem(s["species_name"] or ""))
            interval_item = QTableWidgetItem()
            interval_item.setData(Qt.DisplayRole, s["interval_days"])
            interval_item.setTextAlignment(Qt.AlignCenter)
            self.sched_table.setItem(row, 3, interval_item)
            self.sched_table.setItem(row, 4, QTableWidgetItem(s["notes"] or ""))

        self._load_reminders()

    def _load_reminders(self):
        reminders = schedule_repo.get_due_reminders(limit=50, include_completed=True)
        self.rem_table.setRowCount(0)
        for r in reminders:
            row = self.rem_table.rowCount()
            self.rem_table.insertRow(row)
            self.rem_table.setItem(row, 0, QTableWidgetItem(str(r["reminder_id"])))
            self.rem_table.setItem(row, 1, QTableWidgetItem(r["pet_name"] or ""))
            self.rem_table.setItem(row, 2, QTableWidgetItem(r["owner_name"] or ""))
            self.rem_table.setItem(row, 3, QTableWidgetItem(r["vaccine_name"] or ""))
            self.rem_table.setItem(row, 4, QTableWidgetItem(r["due_date"] or ""))
            status_item = QTableWidgetItem(tr(r["status"].capitalize()))
            self.rem_table.setItem(row, 5, status_item)

    def _add_schedule(self):
        dialog = _ScheduleEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if schedule_repo.add_schedule(data["vaccine_id"], data["species_id"], data["interval_days"], data["notes"]):
                self._load_schedules()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to add schedule. A schedule for this vaccine+species may already exist."))

    def _edit_schedule(self):
        row = self.sched_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a schedule to edit."))
            return
        schedule_id = int(self.sched_table.item(row, 0).text())
        interval = int(self.sched_table.item(row, 3).text() or 365)
        notes = self.sched_table.item(row, 4).text() or ""
        dialog = _ScheduleEditDialog(self, interval_days=interval, notes=notes)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            schedule_repo.update_schedule(schedule_id, data["interval_days"], data["notes"])
            self._load_schedules()

    def _delete_schedule(self):
        row = self.sched_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a schedule to delete."))
            return
        schedule_id = int(self.sched_table.item(row, 0).text())
        reply = QMessageBox.question(self, tr("Confirm Delete"), tr("Delete this schedule?"), QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            schedule_repo.delete_schedule(schedule_id)
            self._load_schedules()

    def _generate_reminders(self):
        total = schedule_repo.generate_reminders_for_all_pets()
        QMessageBox.information(self, tr("Reminders Generated"), tr("Created {count} new reminders.").format(count=total))
        self._load_reminders()

    def _complete_reminder(self):
        row = self.rem_table.currentRow()
        if row < 0:
            return
        reminder_id = int(self.rem_table.item(row, 0).text())
        schedule_repo.complete_reminder(reminder_id)
        self._load_reminders()

    def _skip_reminder(self):
        row = self.rem_table.currentRow()
        if row < 0:
            return
        reminder_id = int(self.rem_table.item(row, 0).text())
        schedule_repo.skip_reminder(reminder_id)
        self._load_reminders()

    def _delete_reminder(self):
        row = self.rem_table.currentRow()
        if row < 0:
            return
        reminder_id = int(self.rem_table.item(row, 0).text())
        schedule_repo.delete_reminder(reminder_id)
        self._load_reminders()


class _ScheduleEditDialog(QDialog):
    """Internal dialog for adding/editing a vaccine schedule."""

    def __init__(self, parent=None, interval_days=365, notes=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Vaccine Schedule"))
        self.setMinimumWidth(440)
        self._setup_ui(interval_days, notes)

    def _setup_ui(self, interval_days, notes):
        layout = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(layout)
        root.addStretch(1)

        self.vaccine_combo = QComboBox()
        from src.core.repositories import vaccination_repo
        vaccines_data = vaccination_repo.get_all_vaccines()
        for v in vaccines_data:
            self.vaccine_combo.addItem(v["vaccine_name"], v["vaccine_id"])
        layout.addRow(tr("Vaccine:"), self.vaccine_combo)

        self.species_combo = QComboBox()
        for species_id, species_name in supply_repo.get_all_species_with_ids():
            self.species_combo.addItem(species_name, species_id)
        layout.addRow(tr("Species:"), self.species_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 3650)
        self.interval_spin.setValue(interval_days)
        self.interval_spin.setSuffix(tr(" days"))
        layout.addRow(tr("Interval:"), self.interval_spin)

        self.notes_edit = QLineEdit(notes)
        self.notes_edit.setPlaceholderText(tr("Optional notes"))
        layout.addRow(tr("Notes:"), self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self):
        if self.vaccine_combo.currentIndex() < 0:
            QMessageBox.warning(self, tr("Validation Error"), tr("Please select a vaccine."))
            return
        if self.species_combo.currentData() is None:
            QMessageBox.warning(self, tr("Validation Error"), tr("Please select a species."))
            return
        self.accept()

    def get_data(self):
        return {
            "vaccine_id": self.vaccine_combo.currentData(),
            "species_id": self.species_combo.currentData(),
            "interval_days": self.interval_spin.value(),
            "notes": self.notes_edit.text().strip(),
        }
