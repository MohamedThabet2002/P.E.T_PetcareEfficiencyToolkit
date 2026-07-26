"""
Settings Dialog module for the PET Application.

Handles application-wide configuration and user preferences through a tabbed dialog interface,
including clinic profile, appearance settings, and advanced options like developer mode and
custom color palette editing.

Includes Database Backup tab (manual backup + restore) backed by SQLite file copies.
"""

import os
import logging
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QApplication, QVBoxLayout, QFormLayout, QLineEdit, QGroupBox, QMessageBox, QDialogButtonBox,
    QLabel, QListView, QTabWidget, QWidget, QComboBox, QCheckBox, QPushButton, QHBoxLayout, QGridLayout,
    QColorDialog, QInputDialog, QDoubleSpinBox, QKeySequenceEdit, QListWidget, QFileDialog, QScrollArea,
)
from PyQt5.QtCore import Qt, QSize, QSettings, pyqtSignal, QRegularExpression
from PyQt5.QtGui import QKeySequence, QColor, QRegularExpressionValidator, QPixmap

from src.utils.settings_manager import SettingsManager
from src.utils.i18n import tr
from src.ui.themes.color_palettes import PALETTES, ThemeConfig
from src.config import (
    STYLES_DIR, APP_NAME, ORG_NAME, SETTINGS_ORG, SETTINGS_APP, SETTING_CONSULT_FEE_LABEL, 
    DEFAULT_CONSULT_FEE, BACKUPS_DIR, WINDOW_CONFIG, ICONS_DIR,
)
from src.core.backup_manager import create_backup, list_backups, restore_backup
from src.core.database import get_user_db_path
import src.core.repositories.supply_repo as supply_repo

logger = logging.getLogger(__name__)

# Settings Keys for QSettings storage
SETTINGS_KEYS = {
    "CLINIC": "clinic_name",
    "USER": "user_name",
    "MODE": "window_mode",
    "THEME": "theme",
    "DEV": "dev_mode",
    "LANG": "language",
    "LOGO": "custom_logo",
}

# Dialog Dimensions
DIALOG_MIN_WIDTH = 600
DIALOG_MIN_HEIGHT = 550
DIALOG_DEFAULT_WIDTH = 600
DIALOG_DEFAULT_HEIGHT = 550

# Color Picker Button Style
COLOR_BUTTON_WIDTH = 40
COLOR_BUTTON_HEIGHT = 24
COLOR_BUTTON_BORDER = "1px solid #888"
COLOR_BUTTON_BORDER_RADIUS = "2px"

# Theme Options
THEME_OPTIONS = ["Light", "Dark", "Custom"]

# Window Mode Options
WINDOW_MODE_OPTIONS = ["Windowed", "Fullscreen"]

# Language Options
LANGUAGE_OPTIONS = [
    ("English", "en"),
    ("Arabic", "ar"),
]

# Fee Range
CONSULT_FEE_MIN = 0.0
CONSULT_FEE_MAX = 9999.99

# Default Shortcut Key
DEFAULT_SHORTCUT_KEY = "F5"

# Logo Configuration
LOGO_ICON = "logo-ico.png"
LOGO_PREVIEW_SIZE = QSize(48, 48)

# Clinic name constraints
CLINIC_NAME_MAX_LEN = 30
# Unicode-aware letter set via Qt regex:
# - must start with a letter
# - then letters/spaces and a small set of separators/punctuation
CLINIC_NAME_REGEX = r"^[\p{L}][\p{L}\s\-\.'’&]{0,%d}$" % (CLINIC_NAME_MAX_LEN - 1)


class SettingsDialog(QDialog):
    """Dialog for managing application-wide settings and preferences."""

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.resize(DIALOG_DEFAULT_WIDTH, DIALOG_DEFAULT_HEIGHT)

        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # Temporary storage for custom palette edits
        self.custom_colors = {}
        self.color_buttons = {}

        # Backup UI state
        self._backup_entries = []  # list[BackupEntry] from list_backups

        self._setup_ui()
        self._load_settings()
        # Apply translations after UI is created and settings are loaded.
        # (Qt may otherwise keep initial hardcoded tab/title text until a reset.)
        self._apply_translated_tab_titles()

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # Make each tab scrollable (content can exceed window height).
        self._wrap_tab_in_scroll_area = True

        self._init_profile_tab()

        self._init_appearance_tab()
        self._init_database_backup_tab()
        self._init_inventory_tab()
        self._init_dev_tab()

        self.buttons = QDialogButtonBox()
        self.buttons.addButton(tr("Save"), QDialogButtonBox.AcceptRole)
        cancel_button = self.buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.main_layout.addWidget(self.buttons)

    def _make_scrollable_tab(self, content_widget: QWidget) -> QWidget:
        if not getattr(self, "_wrap_tab_in_scroll_area", False):
            return content_widget

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content_widget)
        return scroll

    def _init_profile_tab(self):
        self.profile_tab = QWidget()
        self.profile_vbox = QVBoxLayout(self.profile_tab)

        identity_group = QGroupBox(tr("Clinic Information"))
        identity_form = QFormLayout(identity_group)

        self.clinic_name_edit = QLineEdit()
        self.clinic_name_edit.setPlaceholderText(tr("Enter your clinic's name"))
        self.clinic_name_edit.setMaxLength(CLINIC_NAME_MAX_LEN)
        self.clinic_name_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(CLINIC_NAME_REGEX), self.clinic_name_edit)
        )

        self.user_name_edit = QLineEdit()
        self.user_name_edit.setPlaceholderText(tr("Your name or title"))

        identity_form.addRow(tr("Clinic Name:"), self.clinic_name_edit)
        identity_form.addRow(tr("Your Name:"), self.user_name_edit)

        # Custom Logo Selection
        logo_layout = QHBoxLayout()
        self.logo_preview_label = QLabel()
        self.logo_preview_label.setFixedSize(LOGO_PREVIEW_SIZE)
        self.logo_preview_label.setScaledContents(True)
        self.logo_preview_label.setStyleSheet("border: 1px solid #ccc; border-radius: 4px; background: #eee;")

        self.logo_path_edit = QLineEdit()
        self.logo_path_edit.setReadOnly(True)
        self.logo_path_edit.setPlaceholderText(tr("Select a custom logo..."))
        browse_btn = QPushButton(tr("Browse..."))
        browse_btn.clicked.connect(self._browse_for_logo)
        reset_btn = QPushButton(tr("Reset"))
        reset_btn.clicked.connect(self._reset_logo)
        
        logo_layout.addWidget(self.logo_preview_label)
        logo_layout.addWidget(self.logo_path_edit)
        logo_layout.addWidget(browse_btn)
        logo_layout.addWidget(reset_btn)
        identity_form.addRow(tr("Custom Logo:"), logo_layout)

        self.profile_vbox.addWidget(identity_group)

        fees_group = QGroupBox(tr("Financial Settings"))
        fees_form = QFormLayout(fees_group)

        self.consult_fee_edit = QDoubleSpinBox()
        self.consult_fee_edit.setRange(CONSULT_FEE_MIN, CONSULT_FEE_MAX)
        self.consult_fee_edit.setPrefix("$ ")
        self.consult_fee_edit.setToolTip(tr("Default consultation fee charged per visit"))

        fees_form.addRow(tr("Consultation Fee:"), self.consult_fee_edit)
        self.profile_vbox.addWidget(fees_group)

        self.profile_vbox.addStretch()

        info_text = QLabel(
            "<b>© 2026 MOHAMED THABET</b>. All Rights Reserved<br/>"
            "Contact: <a href='mailto:mohamed.thabet.9112002@gmail.com'>mohamed.thabet.9112002@gmail.com</a>"
        )
        info_text.setObjectName("info_label")
        info_text.setAlignment(Qt.AlignCenter)
        info_text.setTextFormat(Qt.RichText)
        info_text.setOpenExternalLinks(True)
        info_text.setStyleSheet(
            "color: gray; font-size: 10px; margin-top: 10px; a { color: #1e6bff; }"
        )
        self.profile_vbox.addWidget(info_text)

        self.profile_tab = self._make_scrollable_tab(self.profile_tab)
        self.tabs.addTab(self.profile_tab, tr("Clinic Profile"))

    def _init_appearance_tab(self):
        self.appearance_tab = QWidget()
        self.appearance_vbox = QVBoxLayout(self.appearance_tab)

        # Window Mode group
        mode_group = QGroupBox(tr("Window Mode"))
        mode_form = QFormLayout(mode_group)
        self.window_mode_combo = QComboBox()
        self.window_mode_combo.setView(QListView())
        self.window_mode_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.window_mode_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for mode in WINDOW_MODE_OPTIONS:
            self.window_mode_combo.addItem(tr(mode), mode)
        mode_form.addRow(tr("Startup Window Mode:"), self.window_mode_combo)
        self.appearance_vbox.addWidget(mode_group)

        theme_group = QGroupBox(tr("Visual Style"))
        theme_form = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.setView(QListView())
        self.theme_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.theme_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for theme in THEME_OPTIONS:
            self.theme_combo.addItem(tr(theme), theme)
        theme_form.addRow(tr("Default Theme:"), self.theme_combo)

        # Language group (must be above Visual Style)
        lang_group = QGroupBox(tr("Localization"))
        lang_form = QFormLayout(lang_group)

        self.language_combo = QComboBox()
        self.language_combo.setView(QListView())
        self.language_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.language_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for lang_name, lang_code in LANGUAGE_OPTIONS:
            self.language_combo.addItem(tr(lang_name), lang_code)

        lang_form.addRow(tr("Language:"), self.language_combo)
        self.appearance_vbox.insertWidget(1, lang_group)
        self.appearance_vbox.addWidget(theme_group)

        # Palette editor placeholder (moved from DEV to Appearance)
        self.palette_editor_container = QGroupBox(tr("Custom Palette Editor"))
        self.palette_editor_container.setVisible(False)
        self.palette_editor_layout = QVBoxLayout(self.palette_editor_container)

        self.appearance_vbox.addWidget(self.palette_editor_container)
        self.appearance_vbox.addStretch()
        self.appearance_tab = self._make_scrollable_tab(self.appearance_tab)
        self.tabs.addTab(self.appearance_tab, tr("Appearance"))

    def _init_inventory_tab(self):
        """Initializes tab for managing dynamic inventory categories."""
        self.inventory_tab = QWidget()
        main_vbox = QVBoxLayout(self.inventory_tab)

        # --- GROUP 1: INVENTORY STRUCTURE ---
        inv_group = QGroupBox(tr("Inventory Categories"))
        inv_layout = QVBoxLayout(inv_group)
        inv_content = QHBoxLayout()

        # Left Column: Categories
        cat_vbox = QVBoxLayout()
        cat_vbox.addWidget(QLabel(tr("Categories:")))
        self.cat_list = QListWidget()
        cat_vbox.addWidget(self.cat_list)
        inv_content.addLayout(cat_vbox, 2)

        # Middle Column: Sub-Categories
        sub_vbox = QVBoxLayout()
        sub_vbox.addWidget(QLabel(tr("Sub-Categories:")))
        self.sub_list = QListWidget()
        sub_vbox.addWidget(self.sub_list)
        inv_content.addLayout(sub_vbox, 2)

        # Right Column: Action Buttons
        btn_vbox = QVBoxLayout()
        btn_vbox.setAlignment(Qt.AlignTop)

        add_cat_btn = QPushButton(tr("+ Category"))
        del_cat_btn = QPushButton(tr("- Category"))
        add_sub_btn = QPushButton(tr("+ Sub-Cat"))
        del_sub_btn = QPushButton(tr("- Sub-Cat"))

        for btn in [add_cat_btn, del_cat_btn, add_sub_btn, del_sub_btn]:
            btn.setFixedWidth(110)
            btn_vbox.addWidget(btn)
        btn_vbox.insertSpacing(2, 20)
        inv_content.addLayout(btn_vbox, 1)
        inv_layout.addLayout(inv_content)
        main_vbox.addWidget(inv_group)

        # --- GROUP 2: CLINIC LISTS (Species & Services) ---
        list_group = QGroupBox(tr("Clinic Lists"))
        list_layout = QVBoxLayout(list_group)
        list_content = QHBoxLayout()

        # Left Column: Species
        spec_vbox = QVBoxLayout()
        spec_vbox.addWidget(QLabel(tr("Species:")))
        self.spec_combo = QComboBox()
        self.spec_combo.setView(QListView())
        self.spec_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.spec_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        spec_vbox.addWidget(self.spec_combo)
        spec_btns = QHBoxLayout()
        add_spec_btn = QPushButton(tr("+ Species"))
        del_spec_btn = QPushButton(tr("- Species"))
        spec_btns.addWidget(add_spec_btn); spec_btns.addWidget(del_spec_btn)
        spec_vbox.addLayout(spec_btns)
        list_content.addLayout(spec_vbox, 1)
        
        # Right Column: Services
        serv_vbox = QVBoxLayout()
        serv_vbox.addWidget(QLabel(tr("Services:")))
        self.serv_combo = QComboBox()
        self.serv_combo.setView(QListView())
        self.serv_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.serv_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        serv_vbox.addWidget(self.serv_combo)
        serv_btns = QHBoxLayout()
        add_serv_btn = QPushButton(tr("+ Service"))
        del_serv_btn = QPushButton(tr("- Service"))
        serv_btns.addWidget(add_serv_btn); serv_btns.addWidget(del_serv_btn)
        serv_vbox.addLayout(serv_btns)
        list_content.addLayout(serv_vbox, 1)
        
        list_layout.addLayout(list_content)
        main_vbox.addWidget(list_group)
        
        def refresh_cats():
            self.cat_list.clear()
            self.cat_list.addItems(supply_repo.get_all_categories())
            refresh_subs()

        def refresh_subs():
            self.sub_list.clear()
            current_cat = self.cat_list.currentItem()
            if current_cat:
                self.sub_list.addItems(supply_repo.get_subcategories_by_category(current_cat.text()))

        def refresh_clinic_lists():
            self.spec_combo.clear(); self.spec_combo.addItems(supply_repo.get_all_species())
            self.serv_combo.clear(); self.serv_combo.addItems(supply_repo.get_all_services())

        def add_item(repo_func, refresh_func, title):
            name, ok = QInputDialog.getText(self, tr("New {title}").format(title=tr(title)), tr("{title} Name:").format(title=tr(title)))
            if ok and name.strip():
                if repo_func(name.strip()): refresh_func()
                else: QMessageBox.warning(self, tr("Custom Lists"), tr("Item already exists."))

        def add_cat():
            name, ok = QInputDialog.getText(self, tr("New Category"), tr("Category Name:"))
            if ok and name.strip():
                if supply_repo.add_category(name.strip()):
                    refresh_cats()
                    items = self.cat_list.findItems(name.strip(), Qt.MatchExactly)
                    if items: self.cat_list.setCurrentItem(items[0])
                else:
                    QMessageBox.warning(self, tr("Custom Lists"), tr("Failed to add category. It might already exist."))

        def del_cat():
            current_cat = self.cat_list.currentItem()
            if current_cat:
                cat = current_cat.text()
                if QMessageBox.question(self, tr("Restore Database"), tr("Delete category '{cat}'?").format(cat=cat)) == QMessageBox.Yes:
                    supply_repo.delete_category(cat)
                    refresh_cats()

        def add_sub():
            current_cat = self.cat_list.currentItem()
            if not current_cat:
                QMessageBox.information(self, tr("Custom Lists"), tr("Please select a category first."))
                return
            name, ok = QInputDialog.getText(self, tr("New Sub-Category"), tr("Sub-Category Name:"))
            if ok and name.strip():
                if supply_repo.add_subcategory(current_cat.text(), name.strip()):
                    refresh_subs()
                else:
                    QMessageBox.warning(self, tr("Custom Lists"), tr("Failed to add sub-category."))

        def del_sub():
            current_cat = self.cat_list.currentItem()
            current_sub = self.sub_list.currentItem()
            if current_cat and current_sub:
                if QMessageBox.question(self, tr("Restore Database"), tr("Delete Sub-Category '{val}'?").format(val=current_sub.text())) == QMessageBox.Yes:
                    supply_repo.delete_subcategory(current_cat.text(), current_sub.text())
                    refresh_subs()

        def del_clinic_item(combo, repo_func, refresh_func, title):
            val = combo.currentText()
            if val and QMessageBox.question(self, tr("Restore Database"), tr("Delete {title} '{val}'?").format(title=tr(title), val=val)) == QMessageBox.Yes:
                repo_func(val); refresh_func()

        add_cat_btn.clicked.connect(add_cat); del_cat_btn.clicked.connect(del_cat)
        add_sub_btn.clicked.connect(add_sub); del_sub_btn.clicked.connect(del_sub)
        
        add_spec_btn.clicked.connect(lambda: add_item(supply_repo.add_species, refresh_clinic_lists, "Species"))
        del_spec_btn.clicked.connect(lambda: del_clinic_item(self.spec_combo, supply_repo.delete_species, refresh_clinic_lists, "Species"))
        add_serv_btn.clicked.connect(lambda: add_item(supply_repo.add_service, refresh_clinic_lists, "Service"))
        del_serv_btn.clicked.connect(lambda: del_clinic_item(self.serv_combo, supply_repo.delete_service, refresh_clinic_lists, "Service"))

        self.cat_list.currentItemChanged.connect(refresh_subs)
        
        refresh_cats(); refresh_clinic_lists()
        main_vbox.addStretch()
        self.inventory_tab = self._make_scrollable_tab(self.inventory_tab)
        self.tabs.addTab(self.inventory_tab, tr("Custom Lists"))

    def _init_database_backup_tab(self):
        self.backup_tab = QWidget()
        self.backup_vbox = QVBoxLayout(self.backup_tab)

        # Create backup
        self.backup_create_btn = QPushButton(tr("Create Backup Now"))
        self.backup_vbox.addWidget(self.backup_create_btn)

        # Restore controls
        restore_group = QGroupBox(tr("Backup && Restore"))
        self._restore_group = restore_group
        restore_vbox = QVBoxLayout(restore_group)

        self.backup_list_combo = QComboBox()
        self.backup_list_combo.setView(QListView())
        self.backup_list_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.backup_list_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        restore_vbox.addWidget(self.backup_list_combo)

        btn_row = QHBoxLayout()
        self.backup_refresh_btn = QPushButton(tr("Refresh"))
        self.backup_restore_btn = QPushButton(tr("Restore Selected Backup"))
        btn_row.addWidget(self.backup_refresh_btn)
        btn_row.addWidget(self.backup_restore_btn)
        restore_vbox.addLayout(btn_row)

        self.backup_status_label = QLabel(tr("Ready"))
        restore_vbox.addWidget(self.backup_status_label)

        self.backup_vbox.addWidget(restore_group)
        self.backup_vbox.addStretch()
        self.backup_tab = self._make_scrollable_tab(self.backup_tab)
        self.tabs.addTab(self.backup_tab, tr("Database Backup"))

        # Wiring
        self.backup_create_btn.clicked.connect(self._on_create_manual_backup)
        self.backup_refresh_btn.clicked.connect(self._refresh_backup_list)
        self.backup_restore_btn.clicked.connect(self._on_restore_selected_backup)

        # Populate on open
        self._refresh_backup_list()

    def _init_dev_tab(self):
        self.advanced_tab = QWidget()
        self.advanced_vbox = QVBoxLayout(self.advanced_tab)

        dev_group = QGroupBox(tr("Developer Settings"))
        dev_form = QFormLayout(dev_group)

        self.dev_options_check = QCheckBox(tr("Enable Developer Options"))
        dev_form.addRow(self.dev_options_check)

        self.logging_check = QCheckBox(tr("Enable File Logging"))
        dev_form.addRow(self.logging_check)

        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setEnabled(False)
        dev_form.addRow(tr("Hot-Reload Style:"), self.shortcut_edit)

        self.advanced_vbox.addWidget(dev_group)
        self.advanced_vbox.addStretch()
        self.advanced_tab = self._make_scrollable_tab(self.advanced_tab)
        self.tabs.addTab(self.advanced_tab, tr("DEV"))

        self.dev_options_check.toggled.connect(self._toggle_dev_widgets)
        self.theme_combo.currentTextChanged.connect(self._update_palette_editor_enabled)

    def _browse_for_logo(self):
        """Opens a file dialog to select a custom logo image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("Select Logo Image"), "", tr("Image Files (*.png *.jpg *.jpeg *.bmp *.gif)")
        )
        if file_path:
            self.logo_path_edit.setText(file_path)
            self._update_logo_preview(file_path)

    def _reset_logo(self):
        """Clears the custom logo path."""
        self.logo_path_edit.clear()
        self._update_logo_preview("")

    def _update_logo_preview(self, path):
        """Updates the image preview in the dialog."""
        if path and os.path.exists(path):
            pixmap = QPixmap(path)
        else:
            default_path = os.path.join(ICONS_DIR, LOGO_ICON)
            pixmap = QPixmap(default_path)
        
        if not pixmap.isNull():
            self.logo_preview_label.setPixmap(pixmap)

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
                if self.theme_combo.currentText().lower() == "custom":
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

    def _refresh_backup_list(self):
        try:
            self._backup_entries = list_backups(BACKUPS_DIR)
            self.backup_list_combo.clear()

            if not self._backup_entries:
                self.backup_list_combo.addItem(tr("(No backups found)"))
                self.backup_restore_btn.setEnabled(False)
                return

            self.backup_restore_btn.setEnabled(True)

            for entry in self._backup_entries:
                tag = tr(" [MANUAL]") if entry.is_manual else ""
                label = f"{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}{tag}"
                self.backup_list_combo.addItem(label, userData=str(entry.backup_path))

            logger.info("SettingsDialog: Backup list refreshed (%d entries)", len(self._backup_entries))
            self.backup_status_label.setText(tr("Status: OK"))
        except Exception:
            logger.exception("SettingsDialog: Failed to refresh backup list")
            QMessageBox.critical(self, tr("Settings"), tr("Failed to refresh backup list. Check logs."))

    def _on_create_manual_backup(self):
        try:
            db_path = get_user_db_path()
            if not db_path.exists():
                QMessageBox.warning(self, tr("Settings"), tr("Database file not found. Nothing to back up."))
                return

            backup_path = create_backup(
                db_path=db_path,
                backups_dir=BACKUPS_DIR,
                backup_kind="manual",
            )
            logger.info("Manual backup created: %s", backup_path)

            QMessageBox.information(self, tr("Settings"), tr("Manual backup created:\n{name}").format(name=backup_path.name))
            self._refresh_backup_list()
        except Exception as e:
            logger.exception("Manual backup creation failed")
            QMessageBox.critical(self, tr("Settings"), tr("Failed to create backup.\n{error}").format(error=str(e)))

    def _on_restore_selected_backup(self):
        try:
            if self.backup_list_combo.currentIndex() < 0:
                return

            user_data = self.backup_list_combo.currentData()
            if not user_data:
                QMessageBox.warning(self, tr("Settings"), tr("Select a backup first."))
                return

            selected_backup = Path(user_data)
            if not selected_backup.exists():
                QMessageBox.warning(self, tr("Settings"), tr("Selected backup file no longer exists."))
                return

            resp = QMessageBox.question(
                self,
                tr("Restore Database"),
                tr("This will replace the current database with the selected backup.\n\nA safety backup will be created first.\n\nContinue?"),
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

            logger.info("Restore requested from SettingsDialog: %s", selected_backup)
            restore_backup(db_path=get_user_db_path(), backup_file=selected_backup, backups_dir=BACKUPS_DIR)
            logger.info("Restore completed successfully: %s", selected_backup)

            QMessageBox.information(
                self,
                tr("Settings"),
                tr("Restore completed. Please restart the application to ensure all data is loaded from the restored DB."),
            )

            self._refresh_backup_list()
        except Exception as e:
            logger.exception("Restore failed")
            QMessageBox.critical(self, tr("Settings"), tr("Restore failed.\n{error}").format(error=str(e)))

    def _load_settings(self):
        from src.config import DEFAULT_CLINIC_NAME, DEFAULT_CLINIC_OWNER

        # Profile
        self.clinic_name_edit.setText(SettingsManager.get(SETTINGS_KEYS["CLINIC"], DEFAULT_CLINIC_NAME))
        self.user_name_edit.setText(SettingsManager.get(SETTINGS_KEYS["USER"], DEFAULT_CLINIC_OWNER))
        logo_path = SettingsManager.get(SETTINGS_KEYS["LOGO"], "")
        self.logo_path_edit.setText(logo_path)
        self._update_logo_preview(logo_path)

        # Financial
        self.consult_fee_edit.setValue(
            float(self.settings.value(SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE))
        )

        # Appearance
        saved_theme = SettingsManager.get(SETTINGS_KEYS["THEME"], THEME_OPTIONS[0])
        theme_key = str(saved_theme).capitalize() if saved_theme else THEME_OPTIONS[0]
        idx = self.theme_combo.findData(theme_key)
        if idx >= 0: self.theme_combo.setCurrentIndex(idx)

        saved_mode = SettingsManager.get(SETTINGS_KEYS["MODE"], WINDOW_MODE_OPTIONS[0])
        mode_key = "Fullscreen" if isinstance(saved_mode, str) and saved_mode.lower() == "fullscreen" else "Windowed"
        idx = self.window_mode_combo.findData(mode_key)
        if idx >= 0: self.window_mode_combo.setCurrentIndex(idx)

        current_lang = SettingsManager.get(SETTINGS_KEYS["LANG"], "en")
        lang_idx = self.language_combo.findData(current_lang)
        self.language_combo.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)

        # Advanced
        is_dev = SettingsManager.get(SETTINGS_KEYS["DEV"], False)
        self.dev_options_check.setChecked(is_dev)
        
        # Load logging status (default to True for supportability)
        self.logging_check.setChecked(SettingsManager.get("enable_logging", True))

        self._toggle_dev_widgets(is_dev)
        self._update_palette_editor_enabled()

        # Custom Palette
        self.settings.beginGroup("CustomPalette")
        for key in PALETTES["light"].keys():
            color_val = self.settings.value(key, PALETTES["light"][key])
            self.custom_colors[key] = color_val
            if key in self.color_buttons:
                self._update_button_style(self.color_buttons[key], color_val)
        self.settings.endGroup()

        self.shortcut_edit.setKeySequence(
            QKeySequence(SettingsManager.get("refresh_shortcut", DEFAULT_SHORTCUT_KEY))
        )

    def _apply_translated_tab_titles(self):
        """Ensure tab titles are translated for the currently selected language."""
        if hasattr(self, "profile_tab"):
            idx = self.tabs.indexOf(self.profile_tab)
            if idx != -1:
                self.tabs.setTabText(idx, tr("Clinic Profile"))

        if hasattr(self, "appearance_tab"):
            idx = self.tabs.indexOf(self.appearance_tab)
            if idx != -1:
                self.tabs.setTabText(idx, tr("Appearance"))

        if hasattr(self, "backup_tab"):
            idx = self.tabs.indexOf(self.backup_tab)
            if idx != -1:
                self.tabs.setTabText(idx, tr("Database Backup"))

        if hasattr(self, "inventory_tab"):
            idx = self.tabs.indexOf(self.inventory_tab)
            if idx != -1:
                self.tabs.setTabText(idx, tr("Custom Lists"))

        if hasattr(self, "advanced_tab"):
            idx = self.tabs.indexOf(self.advanced_tab)
            if idx != -1:
                self.tabs.setTabText(idx, tr("DEV"))

        self.setWindowTitle(tr("Settings"))

    def accept(self):
        clinic_name = self.clinic_name_edit.text().strip()
        if not clinic_name:
            QMessageBox.warning(
                self,
                tr("Validation Error"),
                tr("Clinic Name cannot be empty."),
            )
            return

        if (
            len(clinic_name) > CLINIC_NAME_MAX_LEN
            or QRegularExpression(CLINIC_NAME_REGEX).match(clinic_name).hasMatch() is False
        ):
            QMessageBox.warning(
                self,
                tr("Validation Error"),
                tr("Clinic Name contains invalid characters or is too long.\n\nAllowed: letters, spaces, hyphen (-), apostrophe ('), dot (.), ampersand (&).\nMax length: {max_len}").format(max_len=CLINIC_NAME_MAX_LEN),
            )
            return

        # Batch update settings to avoid multiple disk writes
        settings_data = SettingsManager.load()
        settings_data[SETTINGS_KEYS["CLINIC"]] = clinic_name
        settings_data[SETTINGS_KEYS["USER"]] = self.user_name_edit.text().strip()
        settings_data[SETTINGS_KEYS["LOGO"]] = self.logo_path_edit.text().strip()
        settings_data[SETTINGS_KEYS["MODE"]] = str(self.window_mode_combo.currentData()).lower()
        settings_data[SETTINGS_KEYS["THEME"]] = str(self.theme_combo.currentData())
        settings_data[SETTINGS_KEYS["DEV"]] = self.dev_options_check.isChecked()
        settings_data["enable_logging"] = self.logging_check.isChecked()
        settings_data["refresh_shortcut"] = self.shortcut_edit.keySequence().toString()
        settings_data[SETTINGS_KEYS["LANG"]] = self.language_combo.currentData()
        
        SettingsManager.save(settings_data)
        self.settings_changed.emit()

        # QSettings are handled separately by the OS/Qt
        self.settings.setValue(SETTING_CONSULT_FEE_LABEL, self.consult_fee_edit.value())

        # Save CustomPalette (RGB)
        self.settings.beginGroup("CustomPalette")
        for key, val in self.custom_colors.items():
            self.settings.setValue(key, val)
        self.settings.endGroup()

        self.settings.sync()

        self._handle_style_refresh()

        main_window = self.parent()
        if main_window and hasattr(main_window, "update_window_title"):
            main_window.update_window_title()

        if main_window and hasattr(main_window, "main_page"):
            main_window.main_page.welcome.setText(
                tr("Hello, {name}").format(name=self.user_name_edit.text())
            )

        super().accept()

    def _handle_style_refresh(self):
        main_window = self.window() if hasattr(self, "window") else None
        if not (main_window and hasattr(main_window, "load_stylesheet")):
            main_window = self.parent()

        if not (main_window and hasattr(main_window, "load_stylesheet")):
            return

        theme = (self.theme_combo.currentText() or "").strip().lower()
        if hasattr(main_window, "main_page"):
            main_window.main_page.dark_mode_btn.setChecked(theme == "dark")

        palette_obj = None
        if theme == "custom":
            palette_obj = ThemeConfig(self.custom_colors)

        main_window.load_stylesheet(str(STYLES_DIR / "style.qss"), theme, palette_obj)
