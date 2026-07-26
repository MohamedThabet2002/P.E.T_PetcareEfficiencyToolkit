"""
Pet Health Timeline Dialog for the PET Application.
Displays a chronological view of all clinical events for a pet.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QHeaderView, QAbstractItemView, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import src.core.repositories.pet_health_timeline_repo as timeline_repo
from src.ui.themes.color_palettes import get_active_palette
from src.utils.i18n import tr


EVENT_TYPE_COLORS = {
    "Visit":       "state_success",
    "Medication":  "brand_500",
    "Test":        "state_warning",
    "Treatment":   "chart_costs",
    "Vaccination": "chart_revenue",
    "Health Stat": "state_late",
}


class PetHealthTimelineDialog(QDialog):
    """Read-only dialog showing the chronological health timeline for a pet."""

    def __init__(self, pet_id, pet_name, parent=None):
        super().__init__(parent)
        self.pet_id = pet_id
        self.setWindowTitle(tr("Health Timeline — {name}").format(name=pet_name))
        self.setMinimumSize(820, 560)
        self._setup_ui()
        self._load_timeline()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(tr("Clinical events for <b>{name}</b>").format(name=self.windowTitle().split("—")[-1].strip() if "—" in self.windowTitle() else ""))
        header.setProperty("class", "dialog-title")
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("Date"), tr("Type"), tr("Summary"), tr("Details"), tr("Visit #")
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _load_timeline(self):
        events = timeline_repo.get_pet_health_timeline(self.pet_id, limit=100)
        palette = get_active_palette()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for ev in events:
            row = self.table.rowCount()
            self.table.insertRow(row)

            date_item = QTableWidgetItem(str(ev.get("event_date") or ""))
            date_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, date_item)

            event_type = ev.get("event_type", "")
            type_item = QTableWidgetItem(tr(event_type))
            type_item.setTextAlignment(Qt.AlignCenter)
            color_key = EVENT_TYPE_COLORS.get(event_type)
            if color_key and palette.get(color_key):
                type_item.setForeground(QColor(palette.get(color_key)))
                font = type_item.font()
                font.setBold(True)
                type_item.setFont(font)
            self.table.setItem(row, 1, type_item)

            summary_item = QTableWidgetItem(str(ev.get("summary") or ""))
            self.table.setItem(row, 2, summary_item)

            details = ev.get("detail_2") or ""
            self.table.setItem(row, 3, QTableWidgetItem(str(details)))

            visit_item = QTableWidgetItem()
            visit_id = ev.get("source_visit_id")
            if visit_id:
                visit_item.setData(Qt.DisplayRole, int(visit_id))
            else:
                visit_item.setText("")
            visit_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, visit_item)

        self.table.setSortingEnabled(True)
