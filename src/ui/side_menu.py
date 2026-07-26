"""
Navigation UI module for the PET Application.
Provides adaptive sidebar components supporting both collapsed (icon-only) and expanded states.
"""

#====================================== IMPORTS =======================================================#

import html
import os

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QColor

from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.config import ICONS_DIR, DEFAULT_CLINIC_NAME

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

# --- Sidebar Tuning Configuration ---
MENU_ITEMS = {
    #(Name, Title)
    "dashboard": "Dashboard",
    "home": "Home",
    "clients": "Clients",
    "supplies": "Supplies",
    "receipts": "Receipts",
    "exit": "Exit"
}

LOGO_ICON = "logo-ico.png"
LOGO_ICON_SIZE = (60, 60)

NAV_ICON = "{name}-ico.png"
NAV_ICON_SIZE = (40, 40)

BUTTON_SMALL_SIZE = (60, 60)
# Big buttons include text; give extra height so large fonts (e.g. Aldhabi) don't get clipped.
BUTTON_BIG_SIZE = (240, 60)

SIDEBAR_CONFIG = {
    "small": {  "width": 60,
                "logo_file": LOGO_ICON,
                "logo_size": LOGO_ICON_SIZE,
                "icon_file": NAV_ICON,
                "icon_size": NAV_ICON_SIZE,
                "btn_size": BUTTON_SMALL_SIZE
                },
    "big": {    "width": 240,
                "logo_file": LOGO_ICON,
                "logo_size": LOGO_ICON_SIZE,
                "icon_file": NAV_ICON,
                "icon_size": NAV_ICON_SIZE,
                "btn_label": list(MENU_ITEMS.items()),
                "btn_size": BUTTON_BIG_SIZE}
}

LAYOUT_SPACING = 25
LAYOUT_STRETCH = (2, 10) # Top(above logo), Logo-to-Buttons, Buttons-to-Exit

#============================================== CODE =====================================================#

class SideMenu(QWidget):
    
    # Collapse/expand widths (must match requirements)
    _SMALL_WIDTH = 60
    _BIG_WIDTH = 240
    _ANIM_MS = 300

    """
    Container class for the application's navigation sidebars.
    Manages two versions of the menu: small (icons only) and big (text/wide icons).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
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
            logo_file = cfg["logo_file"]
            logo_size = QSize(*cfg["logo_size"])
            icon_file = cfg["icon_file"]
            icon_size = QSize(*cfg["icon_size"])
            btn_size = QSize(*cfg["btn_size"])

            # Per-element tuning:
            # - Big layouts use full scaling.
            # - Small icon-only buttons/icons use slightly reduced scaling to avoid overshoot.
            small_factor = 0.9 if is_small else 1.0

            
            # Create container widget
            menu_widget = QWidget(self)
            menu_widget.setObjectName(f"sidemenu_{suffix}")
            if is_small:
                menu_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            else:
                menu_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            menu_widget.setMinimumWidth(width)

            setattr(self, f"sidemenu_{suffix}", menu_widget)
            
            layout = QVBoxLayout(menu_widget)
            layout.setContentsMargins(4, 0, 2, 10)
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
            for name, display_name in self.menu_btn_names.items():
                icon_name = icon_file.format(name=name)
                btn = self._create_nav_button(
                    icon_name,
                    icon_size,
                    display_name,
                    btn_size,
                    is_small,
                )
                
                if is_small:
                    btn.setToolTip(display_name)
                setattr(self, f"{name}_btn_{suffix}", btn)
                if name == "exit":
                    layout.addStretch(LAYOUT_STRETCH[1])
                layout.addWidget(btn)
            # Default active state and bottom spacing
            getattr(self, f"dashboard_btn_{suffix}").setChecked(True)

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
        if is_small:
            btn.setFixedSize(QSize(button_size.width(), button_size.height())) # Fixed size for small buttons
        else:
            btn.setFixedSize(QSize(button_size.width(), button_size.height())) # Minimum size for big buttons, allow expansion
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

        for name, display_name_key in self.menu_btn_names.items():
            translated = tr(display_name_key)
            icon_path = os.path.join(ICONS_DIR, NAV_ICON.format(name=name))
            new_icon = recolor_icon(icon_path, unselected_color, brand_color)

            btn_small = getattr(self, f"{name}_btn_small", None)
            if btn_small:
                btn_small.setToolTip(translated)
                btn_small.setIcon(new_icon)

            btn_big = getattr(self, f"{name}_btn_big", None)
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
        """Expand from small(60px) to big(240px) with a modern width animation."""
        if hasattr(self, "_current_animation") and self._current_animation:
            self._current_animation.stop()

        # Hide small immediately when expanding
        self.sidemenu_small.hide()

        # Show big at collapsed width (60px) first
        start_w = self._SMALL_WIDTH
        end_w = self._BIG_WIDTH
        
        self.sidemenu_big.setMinimumWidth(start_w)
        self.sidemenu_big.setMaximumWidth(start_w)
        self.sidemenu_big.show()

        # Animate both properties to prevent the layout from snapping to child sizes immediately
        self._current_animation = QParallelAnimationGroup(self)
        for prop in [b"minimumWidth", b"maximumWidth"]:
            anim = QPropertyAnimation(self.sidemenu_big, prop)
            anim.setDuration(self._ANIM_MS)
            anim.setStartValue(start_w)
            anim.setEndValue(end_w)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._current_animation.addAnimation(anim)

        self._current_animation.start()

    def collapse_small_menu(self):
        """Collapse big menu back to small(60px) with width animation."""
        if hasattr(self, "_current_animation") and self._current_animation:
            self._current_animation.stop()

        start_w = self.sidemenu_big.width()
        end_w = self._SMALL_WIDTH

        self._current_animation = QParallelAnimationGroup(self)
        for prop in [b"minimumWidth", b"maximumWidth"]:
            anim = QPropertyAnimation(self.sidemenu_big, prop)
            anim.setDuration(self._ANIM_MS)
            anim.setStartValue(start_w)
            anim.setEndValue(end_w)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._current_animation.addAnimation(anim)

        self._current_animation.finished.connect(lambda: (
            self.sidemenu_big.hide(),
            self.sidemenu_small.show(),
            # Reset values so the big menu is internally ready for its next expansion
            self.sidemenu_big.setMinimumWidth(self._BIG_WIDTH),
            self.sidemenu_big.setMaximumWidth(self._BIG_WIDTH)
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
