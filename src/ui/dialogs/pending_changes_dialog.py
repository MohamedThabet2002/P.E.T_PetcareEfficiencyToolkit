"""
Pending-Changes Approval Dialog for the PET Application.

Admin-only dialog that lists all pending change requests submitted by
doctors/staff. The admin can approve or reject each request, optionally
adding a reviewer note.

Usage
-----
    from src.ui.dialogs.pending_changes_dialog import PendingChangesDialog

    dialog = PendingChangesDialog(current_user=user, parent=self)
    dialog.exec()
"""

import json
import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QInputDialog, QSplitter, QTextEdit, QWidget,
    QDialogButtonBox, QFrame,
)

from src.core.repositories import pending_changes_repo
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
DIALOG_MIN_WIDTH  = 880
DIALOG_MIN_HEIGHT = 560

COLUMNS = [
    ("pending_id",   "ID",          50),
    ("submitted_at", "Submitted",   140),
    ("username",     "Requested By",120),
    ("table_name",   "Table",       100),
    ("record_id",    "Record ID",   80),
    ("operation",    "Operation",   80),
    ("payload",      "Changes",     0),   # stretch
]


class PendingChangesDialog(QDialog):
    """Admin dialog for reviewing, approving, and rejecting pending changes."""

    # Emitted when any row is approved or rejected so the dashboard can refresh.
    data_changed = pyqtSignal()

    def __init__(self, current_user: dict, parent=None):
        super().__init__(parent)
        self._current_user = current_user or {}
        self._reviewer_id  = self._current_user.get("user_id")

        self.setWindowTitle(tr("Pending Approvals"))
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.resize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)

        self._setup_ui()
        self._refresh()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Title
        title = QLabel(tr("Pending Change Requests"))
        title.setProperty("class", "dialog-title")
        root.addWidget(title)

        subtitle = QLabel(tr("Review and approve or reject edits submitted by staff and doctors."))
        subtitle.setProperty("class", "dialog-subtitle")
        root.addWidget(subtitle)

        # Splitter: table (top) + detail pane (bottom)
        splitter = QSplitter(Qt.Vertical)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c[1]) for c in COLUMNS])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, __, width) in enumerate(COLUMNS):
            if width:
                self.table.setColumnWidth(i, width)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.selectionModel().currentRowChanged.connect(
            lambda current, _prev: self._on_row_selected(current.row())
        )
        splitter.addWidget(self.table)

        # --- Detail pane ---
        detail_frame = QFrame()
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_lbl = QLabel(tr("Change details:"))
        detail_lbl.setProperty("class", "value-strong")
        detail_layout.addWidget(detail_lbl)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(120)
        detail_layout.addWidget(self.detail_view)
        splitter.addWidget(detail_frame)

        splitter.setSizes([320, 120])
        root.addWidget(splitter, 1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()

        self.approve_btn = QPushButton(tr("✓  Approve"))
        self.approve_btn.setToolTip(tr("Approve the selected request"))
        self.approve_btn.clicked.connect(self._approve_selected)

        self.reject_btn = QPushButton(tr("✕  Reject"))
        self.reject_btn.setToolTip(tr("Reject the selected request"))
        self.reject_btn.clicked.connect(self._reject_selected)

        self.approve_all_btn = QPushButton(tr("Approve All"))
        self.approve_all_btn.setToolTip(tr("Approve all pending requests"))
        self.approve_all_btn.clicked.connect(self._approve_all)

        self.refresh_btn = QPushButton(tr("Refresh"))
        self.refresh_btn.clicked.connect(self._refresh)

        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.approve_btn)
        btn_row.addWidget(self.reject_btn)
        btn_row.addWidget(self.approve_all_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # Status bar
        self.status_label = QLabel()
        self.status_label.setProperty("class", "dialog-hint")
        root.addWidget(self.status_label)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _refresh(self):
        """Reload pending rows from the database."""
        rows = pending_changes_repo.get_pending(status="pending")
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, (key, _, __) in enumerate(COLUMNS):
                val = row_data.get(key, "")
                if key == "payload":
                    # Pretty-print the payload dict
                    text = ", ".join(f"{k}: {v}" for k, v in (val.items() if isinstance(val, dict) else {}.items()))
                else:
                    text = str(val) if val is not None else ""
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, row_data)   # store full dict on col 0
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        count = self.table.rowCount()
        self.status_label.setText(
            tr("{count} pending request(s)").format(count=count) if count else tr("No pending requests.")
        )
        self._update_buttons()

    def _on_row_selected(self, row: int):
        """Populate the detail pane when a row is selected."""
        if row < 0:
            self.detail_view.clear()
            return
        item = self.table.item(row, 0)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        payload = data.get("payload", {})
        lines = [
            f"Table:     {data.get('table_name', '')}",
            f"Record ID: {data.get('record_id', 'N/A')}",
            f"Operation: {data.get('operation', '')}",
            f"By:        {data.get('username', '?')} on {data.get('submitted_at', '')}",
            "",
            "Proposed changes:",
        ]
        if isinstance(payload, dict):
            for field, value in payload.items():
                lines.append(f"  {field}: {value}")
        else:
            lines.append(f"  {payload}")
        self.detail_view.setPlainText("\n".join(lines))
        self._update_buttons()

    def _update_buttons(self):
        has_selection = self.table.currentRow() >= 0
        has_rows      = self.table.rowCount() > 0
        self.approve_btn.setEnabled(has_selection)
        self.reject_btn.setEnabled(has_selection)
        self.approve_all_btn.setEnabled(has_rows)

    def _get_selected_pending_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        data = item.data(Qt.UserRole)
        return data.get("pending_id") if data else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _approve_selected(self):
        pending_id = self._get_selected_pending_id()
        if pending_id is None:
            return
        # Grab the full row *before* marking approved so we can apply the payload.
        row = self.table.currentRow()
        row_data = self.table.item(row, 0).data(Qt.UserRole) if row >= 0 else None

        if not pending_changes_repo.approve_change(pending_id, self._reviewer_id):
            QMessageBox.critical(self, tr("Error"), tr("Failed to approve the request."))
            return

        # Apply the payload to the live table.
        if row_data and not pending_changes_repo.apply_pending_change(row_data, reviewer_id=self._reviewer_id):
            QMessageBox.warning(
                self, tr("Apply Failed"),
                tr("Request marked approved but the live-table update failed.\n"
                   "Please check the data and apply manually."),
            )

        self.data_changed.emit()
        self._refresh()

    def _reject_selected(self):
        pending_id = self._get_selected_pending_id()
        if pending_id is None:
            return
        notes, ok = QInputDialog.getText(
            self, tr("Rejection Reason"),
            tr("Optional reason (shown to the requester):")
        )
        if not ok:
            return
        if pending_changes_repo.reject_change(pending_id, self._reviewer_id, notes.strip()):
            self.data_changed.emit()
            self._refresh()
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to reject the request."))

    def _approve_all(self):
        count = self.table.rowCount()
        if count == 0:
            return
        reply = QMessageBox.question(
            self,
            tr("Approve All"),
            tr("Approve all {count} pending request(s)?").format(count=count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        failed_approve = 0
        failed_apply   = 0
        for row in range(count):
            item = self.table.item(row, 0)
            if not item:
                continue
            row_data = item.data(Qt.UserRole)
            if not row_data:
                continue
            pending_id = row_data["pending_id"]
            if not pending_changes_repo.approve_change(pending_id, self._reviewer_id):
                failed_approve += 1
                continue
            if not pending_changes_repo.apply_pending_change(row_data, reviewer_id=self._reviewer_id):
                failed_apply += 1

        self.data_changed.emit()
        self._refresh()
        if failed_approve:
            QMessageBox.warning(
                self, tr("Partial Success"),
                tr("{failed} request(s) could not be approved.").format(failed=failed_approve),
            )
        if failed_apply:
            QMessageBox.warning(
                self, tr("Apply Failed"),
                tr("{failed} request(s) were approved but the live-table update failed.\n"
                   "Please check those records and apply manually.").format(failed=failed_apply),
            )
