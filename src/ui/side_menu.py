"""
Navigation UI module for the PET Application.
Provides adaptive sidebar components supporting both collapsed (icon-only) and expanded states.
"""

#====================================== IMPORTS =======================================================#

import html
import os
from collections import namedtuple

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QColor

from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.config.paths import ICONS_DIR
from src.config.constants import DEFAULT_CLINIC_NAME

from src.ui.themes.color_palettes import get_active_palette

#====================================== HELPER FUNCTIONS =======================================================#

def recolor_icon(path, color_off, color_on):
    """Returns a QIcon with color_off for the 'Off' state and color_on for the 'On' state."""
    if not os.path.exists(path):
        return QIcon()

    def get_colored_pixmap(color_hex):
        pixmap = QPixmap(path)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color_hex))
        painter.end()
        return pixmap
    
    icon = QIcon()
    # Unchecked state uses text_primary (color_off)
    icon.addPixmap(get_colored_pixmap(color_off), QIcon.Normal, QIcon.Off)
    # Checked state uses brand color (color_on)
    icon.addPixmap(get_colored_pixmap(color_on), QIcon.Normal, QIcon.On)
    return icon

#=========================================== CONSTANTS ===================================================#

# --- Menu Item Definition ---

MenuItemDef = namedtuple(
    "MenuItemDef",
    ["name", "title_key", "is_page", "is_exit", "stretch_before"],
)

MENU_ITEMS_CONFIG = [
    # (name,       title_key,    is_page, is_exit, stretch_before)
    MenuItemDef("dashboard", "Dashboard",   True,  False,  False),
    MenuItemDef("database",  "Database",    True,  False,  False),
    MenuItemDef("reports",   "Reports",     True,  False,  False),
    MenuItemDef("visits",    "Visits",      True,  False,  False),  # Doctor-only top-level visits page
    MenuItemDef("admin",     "Admin",       True,  False,  False),  # Admin-only tools page
    MenuItemDef("settings",  "Settings",    True,  False,  True),
    MenuItemDef("exit",      "Exit",        False, True,   False),
]

# Backward-compatible dict for other parts of the code
MENU_ITEMS = {item.name: item.title_key for item in MENU_ITEMS_CONFIG}

LOGO_ICON = "logo.png"
LOGO_ICON_SIZE = (48, 48)

NAV_ICON = "{name}.png"
NAV_ICON_SIZE = (24, 24)

BUTTON_SMALL_SIZE = (48, 40)
# Big buttons include text; give extra height so large fonts (e.g. Aldhabi) don't get clipped.
BUTTON_BIG_SIZE = (150, 40)

SIDEBAR_CONFIG = {
    "small": {  "width": 48,
                "logo_file": LOGO_ICON,
                "logo_size": LOGO_ICON_SIZE,
                "icon_file": NAV_ICON,
                "icon_size": NAV_ICON_SIZE,
                "btn_size": BUTTON_SMALL_SIZE
                },
    "big": {    "width": 150,
                "logo_file": LOGO_ICON,
                "logo_size": LOGO_ICON_SIZE,
                "icon_file": NAV_ICON,
                "icon_size": NAV_ICON_SIZE,
                "btn_size": BUTTON_BIG_SIZE}
}

LAYOUT_SPACING = 25
LAYOUT_STRETCH = (2, 2) # Top(above logo), Logo-to-Buttons, Buttons-to-last-section

# Collapse/expand widths (must match requirements)
SMALL_WIDTH = 48
BIG_WIDTH = 150
ANIM_MS = 300

#============================================== CODE =====================================================#

class SideMenu(QWidget):
    """
    Container class for the application's navigation sidebars.
    Manages two versions of the menu: small (icons only) and big (text/wide icons).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.menu_items_config = MENU_ITEMS_CONFIG
        self.menu_btn_names = MENU_ITEMS
        
        self._setup_menus()
        
        # Hide the big menu by default
        self.sidemenu_big.hide()
    
    def _setup_menus(self):
        """Initializes both collapsed and expanded sidebars using a unified loop."""
        for is_small in [True, False]:
            suffix = "small" if is_small else "big"
            cfg = SIDEBAR_CONFIG[suffix]
            
            width = cfg["width"]
            logo_size = QSize(*cfg["logo_size"])
            icon_file = cfg["icon_file"]
            icon_size = QSize(*cfg["icon_size"])
            btn_size = QSize(*cfg["btn_size"])

            # Create container widget
            menu_widget = QWidget(self)
            menu_widget.setObjectName(f"sidemenu_{suffix}")
            menu_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            menu_widget.setMinimumWidth(width)

            setattr(self, f"sidemenu_{suffix}", menu_widget)
            
            layout = QVBoxLayout(menu_widget)
            layout.setContentsMargins(0, 0, 0, 10)
            layout.setSpacing(LAYOUT_SPACING)
            
            # Logo setup: Uses a horizontal layout for the expanded menu to show both icon and name
            if is_small:
                self.logo_label_small = QLabel()
                self.logo_label_small.setProperty("logo", "primary")
                self.logo_label_small.setObjectName(f"logo_{suffix}")
                self.logo_label_small.setFixedSize(QSize(logo_size.width(), logo_size.height()))
                self.logo_label_small.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.logo_label_small)
            else:
                header_container = QWidget()
                header_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                header_container.setObjectName("side_menu_big_logo_container")
                header_layout = QHBoxLayout(header_container)
                header_layout.setContentsMargins(0, 0, 0, 0)
                header_layout.setSpacing(10)
                header_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                
                self.logo_label_big = QLabel()
                self.logo_label_big.setProperty("logo", "primary")
                self.logo_label_big.setFixedSize(QSize(logo_size.width(), logo_size.height()))
                self.logo_label_big.setAlignment(Qt.AlignCenter)
                clinic_name = SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME)
                safe_name = html.escape(str(clinic_name))
                self.logo_text_label = QLabel(
                    f"<div style='line-height: 40%; white-space: pre-wrap;'>{safe_name}</div>"
                )
                self.logo_text_label.setObjectName("logo_text")
                self.logo_text_label.setWordWrap(True)
                self.logo_text_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                self.logo_text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                
                header_layout.addWidget(self.logo_label_big)
                header_layout.addWidget(self.logo_text_label)
                layout.addWidget(header_container)
            layout.addStretch(LAYOUT_STRETCH[0])
            
            # Create Navigation Buttons
            for item in self.menu_items_config:
                icon_name = icon_file.format(name=item.name)
                btn = self._create_nav_button(
                    icon_name,
                    icon_size,
                    item.title_key,
                    btn_size,
                    is_small,
                )
                
                if is_small:
                    btn.setToolTip(item.title_key)
                setattr(self, f"{item.name}_btn_{suffix}", btn)
                if item.stretch_before:
                    layout.addStretch(LAYOUT_STRETCH[1])
                layout.addWidget(btn)
            # Default active state and bottom spacing
            first_page_item = next(item for item in self.menu_items_config if item.is_page)
            getattr(self, f"{first_page_item.name}_btn_{suffix}").setChecked(True)

        self._update_logo_pixmaps()
            
    
    def _create_nav_button(self, icon_file, icon_size, button_label, button_size, is_small=True, auto_exclusive=True):
        """Helper method to create a navigation QPushButton with standard properties."""
        btn = QPushButton()
        
        # Get the colors from the active palette
        palette = get_active_palette()
        brand_color = palette.get("brand_500")
        unselected_color = palette.get("text_primary")

        btn.setProperty("nav", "primary")
        # Applying text_primary for unchecked and brand_500 for checked states
        btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, icon_file), unselected_color, brand_color))
        btn.setFixedSize(QSize(button_size.width(), button_size.height()))
        if not is_small:
            btn.setText(f"  {tr(button_label)}") # Set text directly on the button
        btn.setIconSize(QSize(icon_size.width(), icon_size.height()))
        btn.setCheckable(True)
        if auto_exclusive:
            btn.setAutoExclusive(True)
        return btn

    def retranslate_ui(self):
        """Refresh navigation labels/tooltips and refresh clinic branding."""
        # Get latest palette colors to ensure icons update if the theme changes
        palette = get_active_palette()
        brand_color = palette.get("brand_500")
        unselected_color = palette.get("text_primary")

        for item in self.menu_items_config:
            translated = tr(item.title_key)
            icon_path = os.path.join(ICONS_DIR, NAV_ICON.format(name=item.name))
            new_icon = recolor_icon(icon_path, unselected_color, brand_color)

            btn_small = getattr(self, f"{item.name}_btn_small", None)
            if btn_small:
                btn_small.setToolTip(translated)
                btn_small.setIcon(new_icon)

            btn_big = getattr(self, f"{item.name}_btn_big", None)
            if btn_big:
                btn_big.setText(f"  {translated}")
                btn_big.setIcon(new_icon)

        self._update_logo_pixmaps()

        # Refresh the clinic name in the side menu header (big menu).
        if hasattr(self, "logo_text_label") and self.logo_text_label is not None:
            clinic_name = SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME)
            safe_name = html.escape(str(clinic_name))
            self.logo_text_label.setText(
                f"<div style='line-height: 40%; white-space: pre-wrap;'>{safe_name}</div>"
            )

    def expand_big_menu(self):
        """Expand from small width to big width with a modern width animation."""
        if hasattr(self, "_current_animation") and self._current_animation:
            self._current_animation.stop()

        # Hide small immediately when expanding
        self.sidemenu_small.hide()

        # Show big at collapsed width first
        start_w = SMALL_WIDTH
        end_w = BIG_WIDTH
        
        self.sidemenu_big.setMinimumWidth(start_w)
        self.sidemenu_big.setMaximumWidth(start_w)
        self.sidemenu_big.show()

        # Animate both properties to prevent the layout from snapping to child sizes immediately
        self._current_animation = QParallelAnimationGroup(self)
        for prop in [b"minimumWidth", b"maximumWidth"]:
            anim = QPropertyAnimation(self.sidemenu_big, prop)
            anim.setDuration(ANIM_MS)
            anim.setStartValue(start_w)
            anim.setEndValue(end_w)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._current_animation.addAnimation(anim)

        self._current_animation.start()

    def collapse_small_menu(self):
        """Collapse big menu back to small width with width animation."""
        if hasattr(self, "_current_animation") and self._current_animation:
            self._current_animation.stop()

        start_w = self.sidemenu_big.width()
        end_w = SMALL_WIDTH

        self._current_animation = QParallelAnimationGroup(self)
        for prop in [b"minimumWidth", b"maximumWidth"]:
            anim = QPropertyAnimation(self.sidemenu_big, prop)
            anim.setDuration(ANIM_MS)
            anim.setStartValue(start_w)
            anim.setEndValue(end_w)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._current_animation.addAnimation(anim)

        self._current_animation.finished.connect(lambda: (
            self.sidemenu_big.hide(),
            self.sidemenu_small.show(),
            # Reset values so the big menu is internally ready for its next expansion
            self.sidemenu_big.setMinimumWidth(BIG_WIDTH),
            self.sidemenu_big.setMaximumWidth(BIG_WIDTH)
        ))
        self._current_animation.start()

    def _update_logo_pixmaps(self):
        """Loads the current logo from settings or assets and applies it to the labels."""
        custom_path = SettingsManager.get("custom_logo", "")
        if custom_path and os.path.exists(custom_path):
            pixmap = QPixmap(custom_path)
        else:
            pixmap = QPixmap(os.path.join(ICONS_DIR, LOGO_ICON))

        if not pixmap.isNull():
            pixmap = pixmap.scaled(QSize(LOGO_ICON_SIZE[0], LOGO_ICON_SIZE[1]), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        if hasattr(self, "logo_label_small") and self.logo_label_small:
            self.logo_label_small.setPixmap(pixmap)
        if hasattr(self, "logo_label_big") and self.logo_label_big:
            self.logo_label_big.setPixmap(pixmap)
