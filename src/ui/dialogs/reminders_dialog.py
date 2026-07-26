"""
Reminders Dialog for the PET Application.
Displays the full list of operational reminders and notifications, role-aware.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton
)
from PyQt5.QtCore import Qt

from src.core.repositories import analytics_repo
from src.core.permissions import can, is_admin, is_doctor
from src.ui.themes.color_palettes import get_active_palette
from src.utils.i18n import tr


class RemindersDialog(QDialog):
    """Full view dialog for all system reminders and notifications."""

    def __init__(self, current_user=None, parent=None):
        super().__init__(parent)
        self._current_user = current_user
        self.setWindowTitle(tr("All Reminders & Notifications"))
        self.setMinimumSize(760, 540)

        self._setup_ui()
        self._load_reminders()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        title = QLabel(tr("Reminders & Alerts"))
        title.setProperty("class", "dialog-title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([tr("Type"), tr("Item / Subject"), tr("Details")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _load_reminders(self):
        try:
            notifications = analytics_repo.get_notifications(limit=100)
        except Exception:
            notifications = []

        palette = get_active_palette()
        self.table.setRowCount(0)

        # Filter by role:
        # - admins see all (financial, pending approvals, low stock, expiring, appointments, followups)
        # - doctors see supplies, today's appointments/follow-ups
        # - others see supplies
        filtered = []
        for n in notifications:
            ntype = n.get("type")
            if is_admin(self._current_user):
                filtered.append(n)
            elif is_doctor(self._current_user):
                if ntype in ("low_stock", "expiring", "appointment", "unpaid_receipt"):
                    filtered.append(n)
            else:
                if ntype in ("low_stock", "expiring", "unpaid_receipt"):
                    filtered.append(n)

        for n in filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)

            title_item = QTableWidgetItem(tr(n.get("title", "")))
            msg_item = QTableWidgetItem(n.get("message", ""))
            detail_item = QTableWidgetItem(n.get("details", ""))

            severity = n.get("severity", "info")
            if severity == "critical":
                color = palette.qcolor("state_danger")
                for item in (title_item, msg_item, detail_item):
                    item.setForeground(color)
            elif severity == "warning":
                color = palette.qcolor("state_warning")
                for item in (title_item, msg_item, detail_item):
                    item.setForeground(color)

            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, msg_item)
            self.table.setItem(row, 2, detail_item)
