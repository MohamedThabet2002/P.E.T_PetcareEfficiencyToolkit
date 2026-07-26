"""Dialog for viewing the complete appointment list from the dashboard."""

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QListView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt

from src.core.repositories import appointment_repo, followup_repo, user_repo
from src.core.permissions import can
from src.utils.i18n import tr

# The statuses offered in the Status combo, for both row kinds: appointments
# store them in `appointments.status`, follow-ups resolve them to a
# 'followup_status' state (see followup_repo.resolve_status_state_id).
# "Late" is derived by src/core/status_resolver.py and shown as the
# current value only.
STATUS_OPTIONS = ["Pending", "Completed", "Canceled"]

STATUS_COLUMN = 4


class AppointmentsDialog(QDialog):
    """Displays all appointments visible to the current user."""

    def __init__(self, current_user=None, parent=None):
        super().__init__(parent)
        self._current_user = current_user
        self.setWindowTitle(tr("All Appointments"))
        self.setMinimumSize(680, 500)
        # Parallel to table rows: {"kind": "appointment"/"followup", "id": record id}.
        self._row_records = []
        self._can_edit = can(self._current_user, "edit_records")
        self._setup_ui()
        self._load_appointments()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("Date"),
            tr("Owner"),
            tr("Pet"),
            tr("Service"),
            tr("Status"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(STATUS_COLUMN, 120)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _load_appointments(self):
        doctor_id = None
        if not can(self._current_user, "view_all_appointments"):
            doctor_id = user_repo.get_doctor_id(self._current_user)

        rows = appointment_repo.get_appointments(doctor_id=doctor_id)

        # Build display rows. get_appointments returns both scheduled
        # appointments and virtual follow-up rows (row_type == "followup",
        # whose id is a followup_id). Keep the row kind next to the id so a
        # status change is persisted on the right table.
        display_rows = []
        self._row_records = []
        for row in rows:
            display_rows.append([
                row.get("appointment_date", ""),
                row.get("owner_name", ""),
                row.get("pet_name", ""),
                row.get("service", ""),
                row.get("status", ""),
            ])
            record_id = row.get("appointment_id")
            self._row_records.append({
                "kind": "followup" if row.get("row_type") == "followup" else "appointment",
                "id": int(record_id) if record_id is not None else None,
            })

        order = sorted(range(len(display_rows)), key=lambda i: display_rows[i][0] or "", reverse=True)
        display_rows = [display_rows[i] for i in order]

        self.table.setRowCount(len(display_rows))
        for row_index, values in enumerate(display_rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column, item)

            record = self._row_records[order[row_index]]
            if record["id"] is not None and self._can_edit:
                self._set_status_combo(
                    row_index, values[STATUS_COLUMN], record["id"], record["kind"]
                )

    def _set_status_combo(self, row, current_status, record_id, kind):
        """Replaces the Status cell with a combo for fast status changes."""
        combo = QComboBox(self.table)
        # Both row kinds use the appointment vocabulary. It must NOT be derived
        # from the 'followup_status' states lookup: follow-ups store their
        # status as a state id and "Pending" legitimately has none (NULL reads
        # back as Pending), so a lookup-driven list could end up with a single
        # item and freeze the combo. Values that are not part of the vocabulary
        # (the derived "Late") stay visible as the current value only.
        options = list(STATUS_OPTIONS)
        if current_status and current_status not in options:
            options.append(current_status)
        combo.setView(QListView(self.table))
        for value in options:
            combo.addItem(value)
        # Pre-select the current status
        idx = combo.findText(current_status)
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)
        combo.setProperty("record_id", record_id)
        combo.setProperty("row_kind", kind)
        combo.setProperty("initial_status", current_status)
        combo.setEnabled(True)  # allow re-selecting after completion
        combo.activated.connect(self._on_status_changed)
        self.table.setCellWidget(row, STATUS_COLUMN, combo)

    def _on_status_changed(self, index):
        """Persists the newly selected status and refreshes the row."""
        combo = self.sender()
        if not combo:
            return
        new_status = combo.currentText()
        initial_status = combo.property("initial_status")
        record_id = combo.property("record_id")
        kind = combo.property("row_kind")
        user_id = (self._current_user or {}).get("user_id")
        if record_id is None or not new_status:
            return
        if new_status == initial_status:
            return
        if kind == "followup":
            # Resolved here rather than read from the combo so a status with no
            # state row ("Pending" on such a database) still gets written —
            # update_followup_status stores None as "no state".
            state_id = followup_repo.resolve_status_state_id(new_status)
            if state_id is None and new_status != "Pending":
                return
            if not followup_repo.update_followup_status(int(record_id), state_id):
                return
        elif not appointment_repo.update_appointment_status(int(record_id), new_status, user_id=user_id):
            return

        # Keep the resolved view consistent with what was just selected.
        combo.setProperty("initial_status", new_status)
        # Find the row containing this combo widget.
        row = None
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, STATUS_COLUMN) is combo:
                row = r
                break
        if row is not None:
            cell = self.table.item(row, STATUS_COLUMN)
            if cell is not None:
                cell.setText(new_status)

