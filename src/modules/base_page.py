"""
Abstract base view module for the PET Application.
Provides the BaseEntityPage class, implementing shared logic for tabbed layouts, 
debounced search functionality, and standardized table management.
"""

#====================================== IMPORTS =======================================================#

import os
from typing import Callable, Optional, List, Dict, Any

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QPushButton, QLineEdit, 
    QHBoxLayout, QComboBox, QTableWidget, QAbstractItemView, QListView,
    QSizePolicy, QTableWidgetItem, QStyledItemDelegate, QApplication, QStyle,
    QStyleOptionViewItem,
)
from PyQt5.QtCore import pyqtSignal, QTimer, QSize, Qt
from PyQt5.QtGui import QIcon, QBrush, QColor, QPalette

from src.ui.themes.color_palettes import get_active_palette

from src.config.paths import ICONS_DIR
from src.utils.i18n import tr
from src.core.permissions import can

#=========================================== CONSTANTS ===================================================#

# --- UI Shared Tuning ---
SEARCH_DEBOUNCE_MS = 300
CLEAR_ICON_SIZE = (24, 24)
CLEAR_BUTTON_SIZE = (38, 38)
CLEAR_ICON = "cancel.png"

#============================================== CODE =====================================================#


class LinkCellDelegate(QStyledItemDelegate):
    """Renders table cells in the configured ``link_cells`` columns as links.

    A custom delegate is used because the global ``QWidget { color: @text_primary }``
    stylesheet rule overrides per-item ``setForeground`` colours, which would
    otherwise render link names in black instead of the brand (link) colour.
    Non-link cells are passed through to the default painting unchanged.
    """

    def __init__(self, link_cols, parent=None):
        super().__init__(parent)
        self._link_cols = set(link_cols)

    def paint(self, painter, option, index):
        if index.column() not in self._link_cols:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        widget = opt.widget
        style = widget.style() if widget else QApplication.style()

        # Draw the row background / selection / hover (respects the stylesheet).
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, widget)

        font = opt.font
        font.setUnderline(True)
        font.setBold(True)
        opt.font = font

        color = QColor(get_active_palette().get("brand_500"))
        if opt.state & QStyle.State_Selected:
            # Keep text readable on the brand-coloured selection background.
            color = opt.palette.color(QPalette.HighlightedText)

        painter.save()
        painter.setFont(opt.font)
        painter.setPen(color)
        rect = opt.rect.adjusted(6, 0, -6, 0)
        painter.drawText(rect, int(opt.displayAlignment), opt.text)
        painter.restore()


class BaseEntityPage(QWidget):
    """
    Base class for tabbed clinical and inventory pages.
    Provides a standardized layout with search, filtering, and table management.
    """
    data_changed = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_user = None
        self.tables: Dict[str, QTableWidget] = {}
        self.search_bars: Dict[str, QLineEdit] = {}
        self.filters: Dict[str, QComboBox] = {}
        self._tab_configs: List[Dict[str, Any]] = []
        self._pending_search_callback: Optional[Callable] = None
        
        self.main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        # Initialize Search Debounce Timer
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._on_search_timeout)
        
        self.main_layout.addWidget(self.tabs)
    
    def create_tab( self, name: str,
                    headers: List[str], 
                    filter_items: List[str], 
                    add_callback: Callable, 
                    delete_callback: Callable, 
                    refresh_callback: Callable, 
                    hide_cols: Optional[List[int]] = None, 
                    col_widths: Optional[List[int]] = None,
                    link_cells: Optional[List[int]] = None):
        """Standardized tab creation logic with integrated controls and table."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # --- Toolbar Section ---
        controls = QHBoxLayout()
        controls.setSpacing(0)
        
        add_btn = QPushButton(f"{tr('Add')} {tr(name)}")
        search_bar = QLineEdit()
        search_bar.setPlaceholderText(f"{tr('Search')} {tr(name)}...")
        search_bar.setProperty("action", "search")
        
        search_clear_btn = QPushButton()
        search_clear_btn.setProperty("action", "clear")
        search_clear_btn.setIcon(QIcon(os.path.join(ICONS_DIR, CLEAR_ICON)))
        search_clear_btn.setFixedSize(QSize(CLEAR_BUTTON_SIZE[0], CLEAR_BUTTON_SIZE[1]))
        search_clear_btn.setIconSize(QSize(CLEAR_ICON_SIZE[0], CLEAR_ICON_SIZE[1]))
        search_clear_btn.clicked.connect(search_bar.clear)
        
        filter_combo = QComboBox()
        filter_combo.setView(QListView())
        filter_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        filter_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        # Store the raw (untranslated) key as item data so the selected column
        # stays stable no matter what language the label is shown in.
        for f in filter_items:
            filter_combo.addItem(tr(f), f)
        filter_combo.setProperty("action", "filter")
        filter_combo.setEditable(True)
        filter_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        filter_combo.lineEdit().setReadOnly(True)
        filter_combo.lineEdit().setTextMargins(-2, 0, -6, 0)  # Align text inside the combo

        
        delete_btn = QPushButton(tr('Delete Selected'))
        
        # Populate layout with a spacer to separate Add/Search from Delete
        controls.addWidget(add_btn)
        controls.addWidget(search_bar)
        controls.addWidget(search_clear_btn)
        controls.addWidget(filter_combo)
        controls.addWidget(delete_btn)
        layout.addLayout(controls)
        
        # --- Table Section ---
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        if hide_cols:
            for col in hide_cols:
                table.hideColumn(col)
        
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionsClickable(True)
        
        if col_widths:
            for i, width in enumerate(col_widths):
                table.setColumnWidth(i, width)
                
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSortingEnabled(True)
        if link_cells:
            table.setItemDelegate(LinkCellDelegate(link_cells, table))
        layout.addWidget(table)
        
        # --- Translation Management ---
        self._tab_configs.append({
            "name_key": name,
            "header_keys": headers,
            "filter_keys": filter_items,
            "add_btn": add_btn,
            "delete_btn": delete_btn,
            "search_bar": search_bar,
            "filter_combo": filter_combo
        })        
        # --- State Management & Signals ---
        self.tables[name] = table
        self.search_bars[name] = search_bar
        self.filters[name] = filter_combo
        
        add_btn.clicked.connect(add_callback)
        delete_btn.clicked.connect(delete_callback)
        
        # Debounced Search Connection
        search_bar.textChanged.connect(lambda text: self._trigger_debounce(text, refresh_callback))
        filter_combo.currentIndexChanged.connect(lambda: refresh_callback(search_bar.text()))
        
        table.cellDoubleClicked.connect(lambda r, c: self.on_row_double_clicked(name, r))
        if link_cells:
            # Re-route clicks on the configured link columns to the click handler.
            table.cellClicked.connect(
                lambda r, c, n=name, cols=tuple(link_cells): self._on_link_cell_clicked(n, r, c, cols)
            )
        
        self.tabs.addTab(tab, tr(name))
        
        # Hide the tab bar if there is only one tab to provide a cleaner look for single-view pages
        self.tabs.tabBar().setVisible(self.tabs.count() > 1)
    
    def retranslate_ui(self):
        """Standardized logic to refresh text for search bars, filters, and buttons."""
        for i, cfg in enumerate(self._tab_configs):
            name_key = cfg["name_key"]
            translated_name = tr(name_key)
            
            self.tabs.setTabText(i, translated_name)
            cfg["add_btn"].setText(f"{tr('Add')} {translated_name}")
            cfg["delete_btn"].setText(tr('Delete Selected'))
            cfg["search_bar"].setPlaceholderText(f"{tr('Search')} {translated_name}...")
            
            # Refresh Filter Combo (keep the raw key as item data)
            combo = cfg["filter_combo"]
            current_idx = combo.currentIndex()
            combo.blockSignals(True)
            combo.clear()
            for f in cfg["filter_keys"]:
                combo.addItem(tr(f), f)
            combo.setCurrentIndex(current_idx)
            combo.blockSignals(False)
            
            # Refresh Headers
            table = self.tables[name_key]
            table.setHorizontalHeaderLabels([tr(h) for h in cfg["header_keys"]])

    def filter_key(self, name):
        """Return the selected filter's raw column key for a tab.

        The combo displays a translated label but carries the untranslated key
        as item data (see ``create_tab``), so callers always get a stable,
        language-independent value to hand to the repository.
        """
        combo = self.filters.get(name)
        if combo is None:
            return "All"
        data = combo.currentData()
        return data if data is not None else (combo.currentText() or "All")

    def set_current_user(self, user):
        """Propagate the logged-in user and apply permission-based visibility."""
        self._current_user = user
        self._apply_permissions()

    def _apply_permissions(self):
        """Show/hide Add and Delete buttons across all tabs based on the current user's role."""
        can_add    = can(self._current_user, "add_records")
        can_delete = can(self._current_user, "delete_records")
        for cfg in self._tab_configs:
            cfg["add_btn"].setVisible(can_add)
            cfg["delete_btn"].setVisible(can_delete)

    def clear_tabs(self):
        """Resets the page state and removes all existing tabs."""
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
        self.tables.clear()
        self.search_bars.clear()
        self.filters.clear()
        self._tab_configs.clear()
    
    def on_row_double_clicked(self, category: str, row: int):
        """
        Virtual method to be overridden by child pages.
        Typically used to launch an edit dialog for the selected entity.
        Subclasses should call can(self._current_user, "edit_records") before opening dialogs.
        """
        pass

    def make_link_item(self, text):
        """Returns a QTableWidgetItem styled as a clickable link (blue/underlined/hand cursor).

        Use this when populating cells that should open a detail view on click.
        """
        item = QTableWidgetItem(str(text) if text is not None else "")
        font = item.font()
        font.setUnderline(True)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(get_active_palette().qcolor("brand_500")))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _on_link_cell_clicked(self, category, row, col, link_cols):
        """Dispatches a single-click on a configured link column to on_link_clicked."""
        if col not in link_cols:
            return
        table = self.tables.get(category)
        if table is None or not (0 <= row < table.rowCount()):
            return
        text = table.item(row, col).text() if table.item(row, col) else ""
        self.on_link_clicked(category, row, col, text)

    def on_link_clicked(self, category: str, row: int, col: int, value: str):
        """Virtual method overridden by child pages to open a detail view for a link cell.

        Args:
            category: The tab name (e.g. 'Clients', 'Pets', 'Visits').
            row:      Row index in the table.
            col:      Column index that was clicked.
            value:    Display text of the clicked cell.
        """
        pass
    
    def _trigger_debounce(self, text: str, callback: Callable[[str], None]):
        """Restarts the search timer and stores the callback with the current text."""
        self.search_timer.stop()
        self._pending_search_callback = lambda: callback(text)
        self.search_timer.start(SEARCH_DEBOUNCE_MS)
    
    def _on_search_timeout(self):
        """Executes the search callback after the user finishes typing."""
        if self._pending_search_callback:
            self._pending_search_callback()
            self._pending_search_callback = None