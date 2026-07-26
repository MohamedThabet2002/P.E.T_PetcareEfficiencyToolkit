"""
My Visits Page for the PET Application.
Provides a doctor-specific view of clinical visit records.
"""

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QIcon, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QComboBox, QAbstractItemView, QListView
)

import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.user_repo as user_repo
from src.config.paths import ICONS_DIR
from src.utils.formatters import format_age
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.modules.base_page import (
    SEARCH_DEBOUNCE_MS,
    CLEAR_ICON_SIZE,
    CLEAR_BUTTON_SIZE,
    CLEAR_ICON,
)
from src.ui.dialogs.info_dialogs import VisitInfoDialog
from src.ui.pages.database_pages.visits_page import HOME_COLUMN_MAP


class MyVisitsPage(QWidget):
    """Doctor-specific visits page displaying their assigned/recorded visits."""

    data_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_user = None
        # visit_id -> authoritative repo row, so opening a row passes real DB
        # data to the dialog instead of re-parsing displayed table cells.
        self._visits_by_id = {}

        self._setup_ui()

        # Default sort: Visit Date (index 10) from last to first
        self.table.setSortingEnabled(False)
        self.table.sortByColumn(10, Qt.DescendingOrder)
        self.table.setSortingEnabled(True)

        self.refresh_visits_table("")
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)

    def _setup_ui(self):
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._apply_search)
        self._pending_search_text = ""

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 10, 0, 0)
        main_layout.setSpacing(8)

        # Toolbar Section
        controls = QHBoxLayout()
        controls.setSpacing(0)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(f"{tr('Search')} {tr('My Visits')}...")
        self.search_bar.setProperty("action", "search")

        self.search_clear_btn = QPushButton()
        self.search_clear_btn.setProperty("action", "clear")
        self.search_clear_btn.setIcon(QIcon(str(ICONS_DIR / CLEAR_ICON)))
        self.search_clear_btn.setFixedSize(QSize(CLEAR_BUTTON_SIZE[0], CLEAR_BUTTON_SIZE[1]))
        self.search_clear_btn.setIconSize(QSize(CLEAR_ICON_SIZE[0], CLEAR_ICON_SIZE[1]))
        self.search_clear_btn.clicked.connect(self.search_bar.clear)

        self.filter_combo = QComboBox()
        self.filter_combo.setProperty("action", "filter")
        self.filter_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.filter_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.filter_combo.setEditable(True)
        self.filter_combo.setView(QListView())
        self.filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.filter_combo.lineEdit().setReadOnly(True)
        self.filter_combo.lineEdit().setTextMargins(-2, 0, -6, 0)

        self.filter_combo.addItem(tr("All"), "All")
        for h in HOME_COLUMN_MAP:
            self.filter_combo.addItem(tr(h[0]), h[0])

        controls.addWidget(self.search_bar)
        controls.addWidget(self.search_clear_btn)
        controls.addWidget(self.filter_combo)

        main_layout.addLayout(controls)

        # Table Section
        self.table = QTableWidget()
        self.table.setColumnCount(len(HOME_COLUMN_MAP))

        headers = [h[0] for h in HOME_COLUMN_MAP]
        self.table.setHorizontalHeaderLabels(headers)

        self.table.hideColumn(1)

        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionsClickable(True)

        for i, (_, __, width) in enumerate(HOME_COLUMN_MAP):
            if width:
                self.table.setColumnWidth(i, width)

        # Visit ID is now visible as a clickable link.
        self.table.setColumnWidth(0, 70)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)

        main_layout.addWidget(self.table)

        self.table.cellClicked.connect(self._on_table_cell_clicked)

        self.search_bar.textChanged.connect(self._trigger_debounce)
        self.filter_combo.currentIndexChanged.connect(
            lambda: self.refresh_visits_table(self.search_bar.text())
        )

    def set_current_user(self, user):
        self._current_user = user
        self.refresh_visits_table(self.search_bar.text())

    def _on_table_cell_clicked(self, row: int, column: int):
        """Opens the visit details dialog when the Visit ID link is clicked."""
        if column != 0:
            return
        self._open_visit_details(row)

    def _open_visit_details(self, row: int):
        visit_item = self.table.item(row, 0)
        if not visit_item:
            return
        try:
            visit_id = int(visit_item.text())
        except (TypeError, ValueError):
            return

        # Use the authoritative repo row kept from the last refresh; never
        # rebuild the record by parsing localized, formatted table cells.
        row_data = self._visits_by_id.get(visit_id)
        if row_data is None:
            return

        visit_row = {
            "visit_id": visit_id,
            "visit_date": row_data.get("visit_date"),
            "owner_name": row_data.get("owner_full_name"),
            "pet_name": row_data.get("pet_name"),
            "diagnosis": row_data.get("diagnosis"),
            "consult": int(row_data.get("consult") or 0),
            "notes": row_data.get("notes"),
            "receipt_id": row_data.get("receipt_id"),
            "owner_id": row_data.get("owner_id"),
            "pet_id": row_data.get("pet_id"),
        }

        VisitInfoDialog(visit_row, self, current_user=self._current_user).exec_()

    def _make_link_item(self, text):
        """Returns a QTableWidgetItem styled as a clickable link."""
        item = QTableWidgetItem(str(text) if text is not None else "")
        font = item.font()
        font.setUnderline(True)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(get_active_palette().qcolor("brand_500")))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _trigger_debounce(self, text: str):
        self._pending_search_text = text
        self._debounce_timer.stop()
        self._debounce_timer.start(SEARCH_DEBOUNCE_MS)

    def _apply_search(self):
        self.refresh_visits_table(self._pending_search_text)

    def _current_filter_field(self) -> str:
        data = self.filter_combo.currentData()
        return data if data is not None else (self.filter_combo.currentText() or "All")

    def refresh_visits_table(self, text: str = ""):
        table = self.table
        filter_field = self._current_filter_field()

        # Doctors should only see their own visits; never fall back to all visits.
        doctor_id = user_repo.get_doctor_id(self._current_user)
        data = visit_repo.get_doctor_visits(doctor_id=doctor_id, text=text, filter_field=filter_field)

        self._visits_by_id = {
            int(r["visit_id"]): r
            for r in data if r.get("visit_id") is not None
        }

        table.setSortingEnabled(False)
        table.setRowCount(0)

        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)

            for col, (_, key, _) in enumerate(HOME_COLUMN_MAP):
                item = QTableWidgetItem()
                val = row_data.get(key)

                if key == "visit_id":
                    item = self._make_link_item(val)
                elif key == "age_in_months":
                    item.setText(format_age(val))
                elif key == "consult":
                    item.setText(tr("Yes") if val else tr("No"))
                elif key in ("species_name", "breed_name"):
                    item.setText(str(val) if val is not None else "")
                elif isinstance(val, (int, float)):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")

                table.setItem(row, col, item)

        table.setSortingEnabled(True)

    def retranslate_ui(self):
        self.search_bar.setPlaceholderText(f"{tr('Search')} {tr('My Visits')}...")
        current_idx = self.filter_combo.currentIndex()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem(tr("All"), "All")
        for h in HOME_COLUMN_MAP:
            self.filter_combo.addItem(tr(h[0]), h[0])
        self.filter_combo.setCurrentIndex(current_idx)
        self.filter_combo.blockSignals(False)

        self.table.setHorizontalHeaderLabels([tr(h[0]) for h in HOME_COLUMN_MAP])
        self.refresh_visits_table(self.search_bar.text())
