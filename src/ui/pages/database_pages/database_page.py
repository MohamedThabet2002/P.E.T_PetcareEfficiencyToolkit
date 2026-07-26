"""
Database Navigation Page for the PET Application.
Provides a hub with 4 navigation buttons (Clients, Visits, Supplies, Receipts)
that switch between sub-pages embedded in a sub-stacked widget.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget,
    QSizePolicy, QLabel, QFrame
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon
import os

from src.ui.pages.database_pages import clients_page, visits_page, supplies_page, receipts_page
from src.ui.themes.color_palettes import get_active_palette
from src.ui.side_menu import recolor_icon
from src.config.paths import ICONS_DIR
from src.utils.i18n import tr

#=========================================== CONSTANTS ===================================================#

NAV_BUTTON_SIZE = (150, 80)
NAV_ICON_SIZE = (48, 48)
NAV_BUTTON_SPACING = 20
# Checked buttons use a brand background with white text (see QPushButton:checked in style.qss),
# so the checked icon must be white too.
NAV_ICON_ON_COLOR = "#FFFFFF"

#============================================== CODE =====================================================#

class DatabasePage(QWidget):
    def __init__(self, parent=None):
        """Initializes the database page with navigation buttons."""
        super().__init__(parent)
        self._current_user = None

        self._setup_ui()

    def _setup_ui(self):
        """Sets up the main layout with navigation buttons and sub-stacked widget."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Navigation buttons container
        self.nav_container = QWidget()
        self.nav_container.setObjectName("database_nav_container")
        self.nav_container.setFixedHeight(120)
        nav_layout = QHBoxLayout(self.nav_container)
        nav_layout.setContentsMargins(20, 10, 20, 10)
        nav_layout.setSpacing(NAV_BUTTON_SPACING)
        nav_layout.setAlignment(Qt.AlignCenter)

        # Create navigation buttons
        self.nav_buttons = {}
        nav_items = [
            ("clients",  tr("Clients"),  "clients.png"),
            ("visits",   tr("Visits"),   "visits.png"),
            ("supplies", tr("Supplies"), "supplies.png"),
            ("receipts", tr("Receipts"), "receipts.png"),
        ]

        for name, display_name, icon_file in nav_items:
            btn = self._create_nav_button(icon_file, display_name)
            self.nav_buttons[name] = btn
            nav_layout.addWidget(btn)

        main_layout.addWidget(self.nav_container)

        # Sub-stacked widget for the sub-pages
        self.sub_page_content = QStackedWidget(self)
        self.sub_page_content.setObjectName("database_sub_page_content")

        # Create sub-page instances
        self.clients_page = clients_page.ClientsPage(self.sub_page_content)
        self.visits_page = visits_page.VisitsPage(self.sub_page_content)
        self.supplies_page = supplies_page.SuppliesPage(self.sub_page_content)
        self.receipts_page = receipts_page.ReceiptsPage(self.sub_page_content)

        # Add sub-pages to stacked widget
        self.sub_page_content.addWidget(self.clients_page)   # index 0
        self.sub_page_content.addWidget(self.visits_page)    # index 1
        self.sub_page_content.addWidget(self.supplies_page)  # index 2
        self.sub_page_content.addWidget(self.receipts_page)  # index 3

        main_layout.addWidget(self.sub_page_content)

        # Connect navigation buttons to sub-page switching
        self._connect_nav_buttons()

        # Set default to Clients page
        self.nav_buttons["clients"].setChecked(True)
        self.sub_page_content.setCurrentIndex(0)

    def _create_nav_button(self, icon_file, button_label):
        """Helper method to create a navigation QPushButton with icon and text."""
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setFixedSize(*NAV_BUTTON_SIZE)
        btn.setProperty("nav", "database")

        # Set icon with palette colors
        palette = get_active_palette()
        unselected_color = palette.get("text_primary")
        icon_path = os.path.join(ICONS_DIR, icon_file)
        btn.setIcon(recolor_icon(icon_path, unselected_color, NAV_ICON_ON_COLOR))
        btn.setIconSize(QSize(*NAV_ICON_SIZE))
        btn.setText(f"  {button_label}")

        return btn

    def _connect_nav_buttons(self):
        """Connects navigation buttons to switch the sub-stacked widget."""
        page_names = ["clients", "visits", "supplies", "receipts"]
        for index, name in enumerate(page_names):
            btn = self.nav_buttons.get(name)
            if btn:
                btn.clicked.connect(lambda checked, idx=index: self.sub_page_content.setCurrentIndex(idx))

    def retranslate_ui(self):
        """Updates text on navigation buttons and propagates to sub-pages."""
        nav_labels = {
            "clients":  tr("Clients"),
            "visits":   tr("Visits"),
            "supplies": tr("Supplies"),
            "receipts": tr("Receipts"),
        }

        palette = get_active_palette()
        unselected_color = palette.get("text_primary")

        for name, label in nav_labels.items():
            btn = self.nav_buttons.get(name)
            if btn:
                btn.setText(f"  {label}")
                icon_map = {
                    "clients":  "clients.png",
                    "visits":   "visits.png",
                    "supplies": "supplies.png",
                    "receipts": "receipts.png",
                }
                icon_path = os.path.join(ICONS_DIR, icon_map[name])
                btn.setIcon(recolor_icon(icon_path, unselected_color, NAV_ICON_ON_COLOR))

        # Propagate to sub-pages
        for i in range(self.sub_page_content.count()):
            widget = self.sub_page_content.widget(i)
            if hasattr(widget, "retranslate_ui"):
                widget.retranslate_ui()

    def refresh_data(self):
        """Refreshes data on all sub-pages."""
        for i in range(self.sub_page_content.count()):
            widget = self.sub_page_content.widget(i)
            if hasattr(widget, "refresh_data"):
                widget.refresh_data()

    def set_current_user(self, user):
        """Propagate the logged-in user to all sub-pages so they can gate write actions."""
        self._current_user = user
        for i in range(self.sub_page_content.count()):
            widget = self.sub_page_content.widget(i)
            if hasattr(widget, "set_current_user"):
                widget.set_current_user(user)

    def open_appointments(self):
        """Opens the appointments tab used by the dashboard View All action."""
        self.nav_buttons["visits"].setChecked(True)
        self.sub_page_content.setCurrentIndex(1)
        tab_index = next(
            (index for index, config in enumerate(self.visits_page._tab_configs)
             if config["name_key"] == "Appointments"), -1
        )
        if tab_index >= 0:
            self.visits_page.tabs.setCurrentIndex(tab_index)
