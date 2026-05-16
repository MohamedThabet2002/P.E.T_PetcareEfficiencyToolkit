"""
Palette editor mixin for the SettingsPage.

Holds the custom theme color-picker construction and enable/disable logic so the
settings page itself stays focused on the tab builders. Operates purely on
``self`` state created by ``SettingsPage``:
    custom_colors, color_buttons, theme_combo, palette_editor_layout,
    palette_editor_container, shortcut_edit, logging_check.
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QGridLayout, QGroupBox, QColorDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from src.utils.i18n import tr

# Color Picker Button Style
COLOR_BUTTON_WIDTH = 40
COLOR_BUTTON_HEIGHT = 24
COLOR_BUTTON_BORDER = "1px solid #888"
COLOR_BUTTON_BORDER_RADIUS = "2px"


class SettingsPaletteMixin:
    """Provides the custom theme color-picker editor for the settings page."""

    def _create_color_button(self, key):
        btn = QPushButton()
        btn.setFixedSize(COLOR_BUTTON_WIDTH, COLOR_BUTTON_HEIGHT)
        btn.setCursor(Qt.PointingHandCursor)

        def pick_color():
            current = QColor(self.custom_colors.get(key, "#FFFFFF"))
            color = QColorDialog.getColor(current, self, tr("Select {key}").format(key=key))
            if color.isValid():
                self.custom_colors[key] = color.name()
                self._update_button_style(btn, color.name())
                if str(self.theme_combo.currentData() or "").strip().lower() == "custom":
                    self._handle_style_refresh()

        btn.clicked.connect(pick_color)
        self.color_buttons[key] = btn
        return btn

    def _ensure_palette_editor_built(self):
        """Lazily build palette editor content under appearance tab."""
        if getattr(self, "_palette_editor_built", False):
            return

        self._palette_editor_built = True

        primary_keys = [
            "brand_500",
            "bg_base",
            "bg_surface",
            "text_primary",
            "text_secondary",
            "border",
        ]
        advanced_keys = [
            "state_success",
            "state_warning",
            "state_danger",
            "state_info",
            "chart_revenue",
            "chart_costs",
            "chart_net",
            "chart_color_1",
            "chart_color_2",
            "chart_color_3",
            "chart_color_4",
            "chart_color_5",
            "chart_color_6",
            "stock_out",
            "stock_low",
        ]

        palette_labels = {
            "brand_500": "Primary Brand Color",
            "bg_base": "Window Background",
            "bg_surface": "Card & Surface Background",
            "text_primary": "Main Text Color",
            "text_secondary": "Muted/Secondary Text",
            "border": "UI Border Color",
            "state_success": "Success State (Green)",
            "state_warning": "Warning State (Orange)",
            "state_danger": "Danger State (Red)",
            "state_info": "Info State (Blue)",
            "chart_revenue": "Chart: Revenue Line",
            "chart_costs": "Chart: Costs Line",
            "chart_net": "Chart: Net Income Line",
            "chart_color_1": "Chart Series 1",
            "chart_color_2": "Chart Series 2",
            "chart_color_3": "Chart Series 3",
            "chart_color_4": "Chart Palette 4",
            "chart_color_5": "Chart Palette 5",
            "chart_color_6": "Chart Palette 6",
            "stock_out": "Out of Stock Highlight",
            "stock_low": "Low Stock Highlight",
        }

        def build_group(group_title: str, keys: list):
            grp = QGroupBox(tr(group_title))
            grid = QGridLayout(grp)
            grid.setContentsMargins(5, 0, 5, 10)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(8)

            def add_item(col: int, row: int, key: str):
                lbl_text = tr(palette_labels.get(key, key.replace("_", " ").title()))
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                lbl = QLabel(f"{lbl_text}:")
                lbl.setMinimumWidth(140)
                btn = self._create_color_button(key)
                cell_layout.addWidget(lbl)
                cell_layout.addWidget(btn)
                grid.addWidget(cell, row, col)

            for i, key in enumerate(keys):
                row = i // 2
                col = i % 2
                add_item(col=col, row=row, key=key)

            grp.setCheckable(False)
            return grp

        primary_grp = build_group(tr("Primary Colors"), primary_keys)
        advanced_grp = build_group(tr("Advanced Colors"), advanced_keys)
        advanced_grp.setChecked(False)

        self.palette_editor_layout.addWidget(primary_grp)
        self.palette_editor_layout.addWidget(advanced_grp)

    def _toggle_dev_widgets(self, enabled):
        self.shortcut_edit.setEnabled(enabled)
        self.logging_check.setEnabled(enabled)
        self._update_palette_editor_enabled()

    def _update_palette_editor_enabled(self, *_args):
        """Show palette editor only when theme is Custom."""
        theme_is_custom = str(self.theme_combo.currentData()).strip().lower() == "custom"
        if hasattr(self, "palette_editor_container"):
            self._ensure_palette_editor_built()
            self.palette_editor_container.setVisible(theme_is_custom)

    def _update_button_style(self, btn, color_hex):
        style = (
            f"background-color: {color_hex}; "
            f"border: {COLOR_BUTTON_BORDER}; "
            f"border-radius: {COLOR_BUTTON_BORDER_RADIUS};"
        )
        btn.setStyleSheet(style)