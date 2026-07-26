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
    QSizePolicy
)
from PyQt5.QtCore import pyqtSignal, QTimer, QSize, Qt
from PyQt5.QtGui import QIcon

from src.config import ICONS_DIR
from src.utils.i18n import tr

#=========================================== CONSTANTS ===================================================#

# --- UI Shared Tuning ---
SEARCH_DEBOUNCE_MS = 300
CLEAR_ICON_SIZE = (24, 24)
CLEAR_BUTTON_SIZE = (36, 36)
CLEAR_ICON = "cancel-ico.png"

#============================================== CODE =====================================================#

class BaseEntityPage(QWidget):
    """
    Base class for tabbed clinical and inventory pages.
    Provides a standardized layout with search, filtering, and table management.
    """
    data_changed = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
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
                    col_widths: Optional[List[int]] = None):
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
        filter_combo.addItems([tr(f) for f in filter_items])
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
            
            # Refresh Filter Combo
            combo = cfg["filter_combo"]
            current_idx = combo.currentIndex()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([tr(f) for f in cfg["filter_keys"]])
            combo.setCurrentIndex(current_idx)
            combo.blockSignals(False)
            
            # Refresh Headers
            table = self.tables[name_key]
            table.setHorizontalHeaderLabels([tr(h) for h in cfg["header_keys"]])

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