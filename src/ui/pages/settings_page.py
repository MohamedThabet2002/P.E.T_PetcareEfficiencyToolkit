"""
Application Settings Page for the PET Application.

Replaces the old settings dialog with a fully self-contained tabbed settings page.
Contains the same tabs as the old dialog (Clinic Profile, Appearance, Database Backup,
Custom Lists, DEV) with page-level Save/Cancel buttons.
Admin-only tools (User Management, Restore Deleted Records) live on the
admin page instead (``src/ui/pages/admin_page.py``); supplier CRUD lives in
``src/ui/dialogs/suppliers_dialog.py``, opened from the Supplies page.
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QGroupBox, QMessageBox,
    QLabel, QListView, QTabWidget, QComboBox, QCheckBox, QPushButton, QFrame,
    QInputDialog, QDoubleSpinBox, QKeySequenceEdit, QListWidget, QFileDialog, QScrollArea,
    QSpinBox,
)
from PyQt5.QtCore import Qt, QSize, QSettings, QRegularExpression
from PyQt5.QtGui import QKeySequence, QRegularExpressionValidator, QPixmap

from src.utils.settings_manager import SettingsManager
from src.utils.i18n import tr
from src.ui.themes.color_palettes import PALETTES, ThemeConfig
from src.config.paths import STYLES_DIR, BACKUPS_DIR, ICONS_DIR
from src.config.meta import APP_NAME, ORG_NAME
from src.config.paths import SETTINGS_ORG, SETTINGS_APP
from src.config.constants import (
    AUTO_CANCEL_HOURS_MAX,
    AUTO_CANCEL_HOURS_MIN,
    DEFAULT_AUTO_CANCEL_HOURS,
    DEFAULT_CONSULT_FEE,
)
from src.core.backup_manager import create_backup, list_backups, restore_backup
from src.core.database import get_user_db_path
from src.core.importer import normalize_template_format
from src.core.permissions import can
import src.core.repositories.supply_repo as supply_repo
import src.core.status_resolver as status_resolver
from src.ui.pages.settings_palette_mixin import SettingsPaletteMixin

logger = logging.getLogger(__name__)

# Settings Keys for QSettings storage
SETTINGS_KEYS = {
    "CLINIC": "clinic_name",
    "MODE": "window_mode",
    "THEME": "theme",
    "DEV": "dev_mode",
    "LANG": "language",
    "LOGO": "custom_logo",
}

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
LOGO_ICON = "logo.png"
LOGO_PREVIEW_SIZE = QSize(48, 48)

# Clinic name constraints
CLINIC_NAME_MAX_LEN = 30
# Unicode-aware letter set via Qt regex:
# - must start with a letter
# - then letters/spaces and a small set of separators/punctuation
CLINIC_NAME_REGEX = r"^[\p{L}][\p{L}\s\-\.'’&]{0,%d}$" % (CLINIC_NAME_MAX_LEN - 1)


class SettingsPage(SettingsPaletteMixin, QWidget):
    """Admin-only application settings page with the full tabbed layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_user = {}

        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # Temporary storage for custom palette edits
        self.custom_colors = {}
        self.color_buttons = {}

        # Custom Lists edits are staged here and only written on Save
        # (reverted by Cancel / _load_settings).
        self._pending_list_ops = []

        # Backup UI state
        self._backup_entries = []  # list[BackupEntry] from list_backups

        # Tabs whose (slow) data has already been loaded on first view.
        self._loaded_tab_indices = set()

        self._setup_ui()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._load_settings()
        # Apply translations after UI is created and settings are loaded.
        self._apply_translated_tab_titles()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Title
        title = QLabel(tr("Settings"))
        title.setProperty("class", "dialog-title")
        main_layout.addWidget(title)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # Make each tab scrollable (content can exceed window height).
        self._wrap_tab_in_scroll_area = True

        self._init_profile_tab()

        self._init_appearance_tab()
        self._init_database_backup_tab()
        self._init_inventory_tab()

        self._init_dev_tab()

        # Page-level Save / Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton(tr("Save"))
        self.save_btn.setProperty("class", "primary-action")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.clicked.connect(self.save_settings)
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setProperty("class", "secondary-action")
        self.cancel_btn.setMinimumHeight(34)
        self.cancel_btn.clicked.connect(self.cancel_settings)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(btn_layout)

    def _make_scrollable_tab(self, content_widget: QWidget) -> QWidget:
        if not getattr(self, "_wrap_tab_in_scroll_area", False):
            return content_widget

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content_widget)
        return scroll

    def showEvent(self, event):
        super().showEvent(event)
        # Load the tab the user is looking at (tabs load lazily on first view,
        # mirroring the Admin page, so opening Settings does not hit the DB).
        self._on_tab_changed(self.tabs.currentIndex())

    def _on_tab_changed(self, index):
        """Populates a tab's slow data the first time it becomes visible."""
        if index < 0 or index in self._loaded_tab_indices:
            return
        tab = self.tabs.widget(index)
        if tab is getattr(self, "inventory_tab", None):
            self._refresh_custom_lists()
        elif tab is getattr(self, "backup_tab", None):
            self._refresh_backup_list()
        self._loaded_tab_indices.add(index)

    def _init_profile_tab(self):
        self.profile_tab = QWidget()
        self.profile_vbox = QVBoxLayout(self.profile_tab)

        self.identity_group = QGroupBox(tr("Clinic Information"))
        self.identity_form = QFormLayout(self.identity_group)

        self.clinic_name_edit = QLineEdit()
        self.clinic_name_edit.setPlaceholderText(tr("Enter your clinic's name"))
        self.clinic_name_edit.setMaxLength(CLINIC_NAME_MAX_LEN)
        self.clinic_name_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(CLINIC_NAME_REGEX), self.clinic_name_edit)
        )

        self.identity_form.addRow(tr("Clinic Name:"), self.clinic_name_edit)

        # Custom Logo Selection
        logo_layout = QHBoxLayout()
        self.logo_preview_label = QLabel()
        self.logo_preview_label.setFixedSize(LOGO_PREVIEW_SIZE)
        self.logo_preview_label.setScaledContents(True)
        self.logo_preview_label.setProperty("class", "logo-preview")

        self.logo_path_edit = QLineEdit()
        self.logo_path_edit.setReadOnly(True)
        self.logo_path_edit.setPlaceholderText(tr("Select a custom logo..."))
        self.browse_btn = QPushButton(tr("Browse..."))
        self.browse_btn.clicked.connect(self._browse_for_logo)
        self.reset_btn = QPushButton(tr("Reset"))
        self.reset_btn.clicked.connect(self._reset_logo)

        logo_layout.addWidget(self.logo_preview_label)
        logo_layout.addWidget(self.logo_path_edit)
        logo_layout.addWidget(self.browse_btn)
        logo_layout.addWidget(self.reset_btn)
        self.identity_form.addRow(tr("Custom Logo:"), logo_layout)

        self.profile_vbox.addWidget(self.identity_group)

        self.fees_group = QGroupBox(tr("Financial Settings"))
        self.fees_form = QFormLayout(self.fees_group)

        self.consult_fee_edit = QDoubleSpinBox()
        self.consult_fee_edit.setRange(CONSULT_FEE_MIN, CONSULT_FEE_MAX)
        self.consult_fee_edit.setPrefix("$ ")
        self.consult_fee_edit.setToolTip(tr("Default consultation fee charged per visit"))

        self.fees_form.addRow(tr("Consultation Fee:"), self.consult_fee_edit)
        self.profile_vbox.addWidget(self.fees_group)

        # --- Scheduling Rules (the "Late" -> auto-canceled window) ---
        self.scheduling_group = QGroupBox(tr("Scheduling Rules"))
        self.scheduling_form = QFormLayout(self.scheduling_group)

        self.auto_cancel_edit = QSpinBox()
        self.auto_cancel_edit.setRange(AUTO_CANCEL_HOURS_MIN, AUTO_CANCEL_HOURS_MAX)
        self.auto_cancel_edit.setSuffix(" h")
        self.auto_cancel_edit.setToolTip(tr(
            "How long an appointment or follow-up stays Late after its "
            "scheduled time before it is automatically marked Canceled."
        ))
        self.auto_cancel_edit.valueChanged.connect(self._update_late_preview)

        self.scheduling_form.addRow(tr("Auto-cancel after:"), self.auto_cancel_edit)

        self.scheduling_preview = QLabel()
        self.scheduling_preview.setWordWrap(True)
        self.scheduling_preview.setProperty("class", "settings-hint")
        self.scheduling_form.addRow(self.scheduling_preview)

        self.profile_vbox.addWidget(self.scheduling_group)
        self._update_late_preview()

        self.profile_vbox.addStretch()

        info_text = QLabel(
            "<b>© 2026 MOHAMED THABET</b>. All Rights Reserved<br/>"
            "Contact: <a href='mailto:mohamed.thabet.9112002@gmail.com'>mohamed.thabet.9112002@gmail.com</a>"
        )
        info_text.setObjectName("info_label")
        info_text.setAlignment(Qt.AlignCenter)
        info_text.setTextFormat(Qt.RichText)
        info_text.setOpenExternalLinks(True)
        info_text.setProperty("class", "info-text")
        self.profile_vbox.addWidget(info_text)

        self.profile_tab = self._make_scrollable_tab(self.profile_tab)
        self.tabs.addTab(self.profile_tab, tr("Clinic Profile"))

    def _update_late_preview(self):
        """Rewrites the Scheduling Rules example line from the spinbox value."""
        if not getattr(self, "scheduling_preview", None):
            return
        hours = self.auto_cancel_edit.value()
        now = datetime.now()
        # Sample = the next whole hour, so the example always reads as an
        # upcoming appointment.
        start = now.replace(minute=0, second=0, microsecond=0)
        if start <= now:
            start += timedelta(hours=1)
        end = start + timedelta(hours=hours)
        self.scheduling_preview.setText(
            tr("Example: a visit at {start} turns Late at that time and is "
               "auto-canceled after {end}.").format(
                start=start.strftime("%Y-%m-%d %H:%M"),
                end=end.strftime("%Y-%m-%d %H:%M"),
            )
        )

    def _init_appearance_tab(self):
        self.appearance_tab = QWidget()
        self.appearance_vbox = QVBoxLayout(self.appearance_tab)

        # Window Mode group
        self.mode_group = QGroupBox(tr("Window Mode"))
        self.mode_form = QFormLayout(self.mode_group)
        self.window_mode_combo = QComboBox()
        self.window_mode_combo.setView(QListView())
        self.window_mode_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.window_mode_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for mode in WINDOW_MODE_OPTIONS:
            self.window_mode_combo.addItem(tr(mode), mode)
        self.mode_form.addRow(tr("Startup Window Mode:"), self.window_mode_combo)
        self.appearance_vbox.addWidget(self.mode_group)

        self.theme_group = QGroupBox(tr("Visual Style"))
        self.theme_form = QFormLayout(self.theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.setView(QListView())
        self.theme_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.theme_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for theme in THEME_OPTIONS:
            self.theme_combo.addItem(tr(theme), theme)
        self.theme_form.addRow(tr("Default Theme:"), self.theme_combo)

        # Language group (must be above Visual Style)
        self.lang_group = QGroupBox(tr("Localization"))
        self.lang_form = QFormLayout(self.lang_group)

        self.language_combo = QComboBox()
        self.language_combo.setView(QListView())
        self.language_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.language_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        for lang_name, lang_code in LANGUAGE_OPTIONS:
            self.language_combo.addItem(tr(lang_name), lang_code)

        self.lang_form.addRow(tr("Language:"), self.language_combo)
        self.appearance_vbox.insertWidget(1, self.lang_group)
        self.appearance_vbox.addWidget(self.theme_group)

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
        self.inv_group = QGroupBox(tr("Inventory Categories"))
        inv_layout = QVBoxLayout(self.inv_group)
        inv_content = QHBoxLayout()

        # Left Column: Categories
        cat_vbox = QVBoxLayout()
        self.cat_label = QLabel(tr("Categories:"))
        cat_vbox.addWidget(self.cat_label)
        self.cat_list = QListWidget()
        cat_vbox.addWidget(self.cat_list)
        inv_content.addLayout(cat_vbox, 2)

        # Middle Column: Sub-Categories
        sub_vbox = QVBoxLayout()
        self.sub_label = QLabel(tr("Sub-Categories:"))
        sub_vbox.addWidget(self.sub_label)
        self.sub_list = QListWidget()
        sub_vbox.addWidget(self.sub_list)
        inv_content.addLayout(sub_vbox, 2)

        # Right Column: Action Buttons
        btn_vbox = QVBoxLayout()
        btn_vbox.setAlignment(Qt.AlignTop)
        btn_vbox.setContentsMargins(4, 0, 4, 0)

        self.add_cat_btn = QPushButton(tr("+ Category"))
        self.del_cat_btn = QPushButton(tr("- Category"))
        self.add_sub_btn = QPushButton(tr("+ Sub-Cat"))
        self.del_sub_btn = QPushButton(tr("- Sub-Cat"))

        for btn in [self.add_cat_btn, self.del_cat_btn, self.add_sub_btn, self.del_sub_btn]:
            btn.setMinimumWidth(110)
            btn_vbox.addWidget(btn)
        btn_vbox.insertSpacing(2, 20)
        inv_content.addLayout(btn_vbox, 1)
        inv_layout.addLayout(inv_content)
        main_vbox.addWidget(self.inv_group)

        # --- GROUP 2: CLINIC LISTS (Species & Services) ---
        self.list_group = QGroupBox(tr("Clinic Lists"))
        list_layout = QVBoxLayout(self.list_group)
        list_content = QHBoxLayout()

        # Left Column: Species
        spec_vbox = QVBoxLayout()
        self.spec_label = QLabel(tr("Species:"))
        spec_vbox.addWidget(self.spec_label)
        self.spec_combo = QComboBox()
        self.spec_combo.setView(QListView())
        self.spec_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.spec_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        spec_vbox.addWidget(self.spec_combo)
        spec_btns = QHBoxLayout()
        self.add_spec_btn = QPushButton(tr("+ Species"))
        self.del_spec_btn = QPushButton(tr("- Species"))
        spec_btns.addWidget(self.add_spec_btn); spec_btns.addWidget(self.del_spec_btn)
        spec_vbox.addLayout(spec_btns)
        list_content.addLayout(spec_vbox, 1)

        # Right Column: Services
        serv_vbox = QVBoxLayout()
        self.serv_label = QLabel(tr("Services:"))
        serv_vbox.addWidget(self.serv_label)
        self.serv_combo = QComboBox()
        self.serv_combo.setView(QListView())
        self.serv_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.serv_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        serv_vbox.addWidget(self.serv_combo)
        serv_btns = QHBoxLayout()
        self.add_serv_btn = QPushButton(tr("+ Service"))
        self.del_serv_btn = QPushButton(tr("- Service"))
        serv_btns.addWidget(self.add_serv_btn); serv_btns.addWidget(self.del_serv_btn)
        serv_vbox.addLayout(serv_btns)
        list_content.addLayout(serv_vbox, 1)

        list_layout.addLayout(list_content)
        main_vbox.addWidget(self.list_group)

        # Staging hint: list edits are only written when Save is clicked.
        self.list_hint = QLabel(tr("Changes are applied when you click Save."))
        self.list_hint.setWordWrap(True)
        self.list_hint.setProperty("class", "settings-hint")
        main_vbox.addWidget(self.list_hint)

        self.add_cat_btn.clicked.connect(self._stage_add_category)
        self.del_cat_btn.clicked.connect(self._stage_delete_category)
        self.add_sub_btn.clicked.connect(self._stage_add_subcategory)
        self.del_sub_btn.clicked.connect(self._stage_delete_subcategory)

        self.add_spec_btn.clicked.connect(lambda: self._stage_add_clinic_item("species", "Species"))
        self.del_spec_btn.clicked.connect(
            lambda: self._stage_delete_clinic_item("species", self.spec_combo, "Species"))
        self.add_serv_btn.clicked.connect(lambda: self._stage_add_clinic_item("service", "Service"))
        self.del_serv_btn.clicked.connect(
            lambda: self._stage_delete_clinic_item("service", self.serv_combo, "Service"))

        self.cat_list.currentItemChanged.connect(self._refresh_subcategories)

        main_vbox.addStretch()
        self.inventory_tab = self._make_scrollable_tab(self.inventory_tab)
        self.tabs.addTab(self.inventory_tab, tr("Custom Lists"))

    # --- Custom Lists: staged edits (written only by Save, dropped by Cancel) ---

    def _effective_categories(self):
        items = list(supply_repo.get_all_categories())
        for op in self._pending_list_ops:
            if op[0] == "add_category" and op[1] not in items:
                items.append(op[1])
            elif op[0] == "delete_category" and op[1] in items:
                items.remove(op[1])
        return items

    def _effective_subcategories(self, category):
        items = list(supply_repo.get_subcategories_by_category(category))
        for op in self._pending_list_ops:
            if op[1] != category:
                continue
            if op[0] == "add_subcategory" and op[2] not in items:
                items.append(op[2])
            elif op[0] == "delete_subcategory" and op[2] in items:
                items.remove(op[2])
        return items

    def _effective_species(self):
        items = list(supply_repo.get_all_species())
        for op in self._pending_list_ops:
            if op[0] == "add_species" and op[1] not in items:
                items.append(op[1])
            elif op[0] == "delete_species" and op[1] in items:
                items.remove(op[1])
        return items

    def _effective_services(self):
        items = list(supply_repo.get_all_services())
        for op in self._pending_list_ops:
            if op[0] == "add_service" and op[1] not in items:
                items.append(op[1])
            elif op[0] == "delete_service" and op[1] in items:
                items.remove(op[1])
        return items

    def _refresh_categories(self):
        previous = self.cat_list.currentItem()
        previous_text = previous.text() if previous else None
        self.cat_list.blockSignals(True)
        self.cat_list.clear()
        self.cat_list.addItems(self._effective_categories())
        self.cat_list.blockSignals(False)
        if previous_text:
            matches = self.cat_list.findItems(previous_text, Qt.MatchExactly)
            if matches:
                self.cat_list.setCurrentItem(matches[0])
        self._refresh_subcategories()

    def _refresh_subcategories(self, *_args):
        self.sub_list.clear()
        current_cat = self.cat_list.currentItem()
        if current_cat:
            self.sub_list.addItems(self._effective_subcategories(current_cat.text()))

    def _refresh_clinic_lists(self):
        self.spec_combo.blockSignals(True)
        self.spec_combo.clear()
        self.spec_combo.addItems(self._effective_species())
        self.spec_combo.blockSignals(False)

        self.serv_combo.blockSignals(True)
        self.serv_combo.clear()
        self.serv_combo.addItems(self._effective_services())
        self.serv_combo.blockSignals(False)

    def _refresh_custom_lists(self):
        self._refresh_categories()
        self._refresh_clinic_lists()

    def _stage_add_category(self):
        name, ok = QInputDialog.getText(self, tr("New Category"), tr("Category Name:"))
        if not (ok and name and name.strip()):
            return
        name = name.strip()
        if name in self._effective_categories():
            QMessageBox.warning(self, tr("Custom Lists"), tr("Item already exists."))
            return
        self._pending_list_ops.append(("add_category", name))
        self._refresh_categories()
        matches = self.cat_list.findItems(name, Qt.MatchExactly)
        if matches:
            self.cat_list.setCurrentItem(matches[0])

    @staticmethod
    def _category_has_items(category):
        return bool(supply_repo.get_unique_supply_names(category))

    @staticmethod
    def _subcategory_has_items(category, subcategory):
        return bool(supply_repo.get_items_by_subcategory(category, subcategory))

    def _stage_delete_category(self):
        current = self.cat_list.currentItem()
        if not current:
            return
        cat = current.text()
        if self._category_has_items(cat):
            QMessageBox.warning(self, tr("Custom Lists"), tr(
                "This category still has items. Please delete them or move them "
                "to another category before deleting this category."
            ))
            return
        if QMessageBox.question(
            self, tr("Delete Category"), tr("Delete category '{cat}'?").format(cat=cat)
        ) != QMessageBox.Yes:
            return
        self._pending_list_ops.append(("delete_category", cat))
        self._refresh_categories()

    def _stage_add_subcategory(self):
        current = self.cat_list.currentItem()
        if not current:
            QMessageBox.information(self, tr("Custom Lists"), tr("Please select a category first."))
            return
        category = current.text()
        name, ok = QInputDialog.getText(self, tr("New Sub-Category"), tr("Sub-Category Name:"))
        if not (ok and name and name.strip()):
            return
        name = name.strip()
        if name in self._effective_subcategories(category):
            QMessageBox.warning(self, tr("Custom Lists"), tr("Item already exists."))
            return
        self._pending_list_ops.append(("add_subcategory", category, name))
        self._refresh_subcategories()

    def _stage_delete_subcategory(self):
        current_cat = self.cat_list.currentItem()
        current_sub = self.sub_list.currentItem()
        if not (current_cat and current_sub):
            return
        cat, sub = current_cat.text(), current_sub.text()
        if self._subcategory_has_items(cat, sub):
            QMessageBox.warning(self, tr("Custom Lists"), tr(
                "This sub-category still has items. Please delete them or move "
                "them to another sub-category before deleting this sub-category."
            ))
            return
        if QMessageBox.question(
            self, tr("Delete Sub-Category"),
            tr("Delete Sub-Category '{val}'?").format(val=sub)
        ) != QMessageBox.Yes:
            return
        self._pending_list_ops.append(("delete_subcategory", cat, sub))
        self._refresh_subcategories()

    def _stage_add_clinic_item(self, kind, title):
        name, ok = QInputDialog.getText(
            self, tr("New {title}").format(title=tr(title)),
            tr("{title} Name:").format(title=tr(title))
        )
        if not (ok and name and name.strip()):
            return
        name = name.strip()
        existing = self._effective_species() if kind == "species" else self._effective_services()
        if name in existing:
            QMessageBox.warning(self, tr("Custom Lists"), tr("Item already exists."))
            return
        self._pending_list_ops.append(("add_" + kind, name))
        self._refresh_clinic_lists()

    def _stage_delete_clinic_item(self, kind, combo, title):
        val = combo.currentText()
        if not val:
            return
        if QMessageBox.question(
            self, tr("Delete {title}").format(title=tr(title)),
            tr("Delete {title} '{val}'?").format(title=tr(title), val=val)
        ) != QMessageBox.Yes:
            return
        self._pending_list_ops.append(("delete_" + kind, val))
        self._refresh_clinic_lists()

    def _apply_pending_list_ops(self):
        """Replays staged Custom Lists edits into the database (Save only).

        Returns the labels of the edits that could not be written; the staging
        list is always cleared so the next Save starts from a clean slate.
        """
        if not self._pending_list_ops:
            return []

        writers = {
            "add_category": lambda op: supply_repo.add_category(op[1]),
            "delete_category": lambda op: supply_repo.delete_category(op[1]),
            "add_subcategory": lambda op: supply_repo.add_subcategory(op[1], op[2]),
            "delete_subcategory": lambda op: supply_repo.delete_subcategory(op[1], op[2]),
            "add_species": lambda op: supply_repo.add_species(op[1]),
            "delete_species": lambda op: supply_repo.delete_species(op[1]),
            "add_service": lambda op: supply_repo.add_service(op[1]),
            "delete_service": lambda op: supply_repo.delete_service(op[1]),
        }

        failures = []
        for op in self._pending_list_ops:
            try:
                if self._op_conflicts_with_items(op):
                    # Items appeared after the delete was staged (they are not
                    # staged themselves); refuse rather than orphan them.
                    saved = False
                else:
                    saved = writers[op[0]](op)
            except Exception:
                logger.exception("SettingsPage: custom list change failed (%s)", op[0])
                saved = False
            if not saved:
                failures.append(self._op_label(op))

        self._pending_list_ops = []
        self._refresh_custom_lists()
        return failures

    @classmethod
    def _op_conflicts_with_items(cls, op):
        """True when a staged delete targets a category/sub that still has items."""
        if op[0] == "delete_category":
            return cls._category_has_items(op[1])
        if op[0] == "delete_subcategory":
            return cls._subcategory_has_items(op[1], op[2])
        return False

    @staticmethod
    def _op_label(op):
        verb = tr("Add") if op[0].startswith("add_") else tr("Delete")
        name = op[1] if len(op) == 2 else "{parent} / {child}".format(parent=op[1], child=op[2])
        return "{verb} {name}".format(verb=verb, name=name)

    def _init_database_backup_tab(self):
        self.backup_tab = QWidget()
        self.backup_vbox = QVBoxLayout(self.backup_tab)
        self.backup_vbox.setSpacing(18)

        # Page header
        self.backup_page_title = QLabel(tr("Backup & Data Transfer"))
        self.backup_page_title.setProperty("class", "page-title")
        self.backup_vbox.addWidget(self.backup_page_title)

        self.backup_page_hint = QLabel(tr(
            "Create full backups of your database, restore an older copy, or "
            "move records between computers with Excel or CSV files."
        ))
        self.backup_page_hint.setWordWrap(True)
        self.backup_page_hint.setProperty("class", "template-hint")
        self.backup_vbox.addWidget(self.backup_page_hint)
        self.backup_vbox.addSpacing(4)

        # Temporary warning: the spreadsheet import/export engine is new.
        self.backup_experimental_banner = QLabel(tr(
            "Note: importing and exporting data is an experimental feature and may cause "
            "issues. Keep a backup before you use it, and check the results carefully."
        ))
        self.backup_experimental_banner.setWordWrap(True)
        self.backup_experimental_banner.setProperty("class", "experimental-banner")
        self.backup_vbox.addWidget(self.backup_experimental_banner)

        # Backup & Restore
        self.restore_group = QGroupBox(tr("Backup && Restore"))
        self.restore_group.setProperty("class", "backup-card")
        self._restore_group = self.restore_group
        restore_vbox = QVBoxLayout(self.restore_group)
        restore_vbox.setSpacing(10)

        self.backup_create_btn = QPushButton(tr("Create Backup Now"))
        self.backup_create_btn.setProperty("class", "primary-action")
        restore_vbox.addWidget(self.backup_create_btn)

        self.backup_list_combo = QComboBox()
        self.backup_list_combo.setView(QListView())
        self.backup_list_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.backup_list_combo.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        restore_vbox.addWidget(self.backup_list_combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.backup_refresh_btn = QPushButton(tr("Refresh"))
        self.backup_refresh_btn.setProperty("class", "template-action")
        self.backup_restore_btn = QPushButton(tr("Restore Selected Backup"))
        self.backup_restore_btn.setProperty("class", "template-action")
        btn_row.addWidget(self.backup_refresh_btn)
        btn_row.addWidget(self.backup_restore_btn)
        btn_row.addStretch()
        restore_vbox.addLayout(btn_row)

        self.backup_status_label = QLabel(tr("Ready"))
        self.backup_status_label.setProperty("class", "backup-status")
        restore_vbox.addWidget(self.backup_status_label)

        # Spreadsheet import (Excel / CSV)
        self.import_group = QGroupBox(tr("Import Data"))
        self.import_group.setProperty("class", "backup-card")
        import_vbox = QVBoxLayout(self.import_group)
        import_vbox.setSpacing(10)
        self.import_desc_label = QLabel()
        self.import_desc_label.setWordWrap(True)
        import_vbox.addWidget(self.import_desc_label)

        import_btn_row = QHBoxLayout()
        self.import_btn = QPushButton(tr("Import from Excel or CSV"))
        self.import_btn.setProperty("class", "primary-action")
        import_btn_row.addWidget(self.import_btn)
        import_btn_row.addStretch()
        import_vbox.addLayout(import_btn_row)

        # Data export (same columns as the templates, with the real records)
        self.export_group = QGroupBox(tr("Export Data"))
        self.export_group.setProperty("class", "backup-card")
        export_vbox = QVBoxLayout(self.export_group)
        export_vbox.setSpacing(10)

        self.export_desc_label = QLabel()
        self.export_desc_label.setWordWrap(True)
        self.export_desc_label.setProperty("class", "template-hint")
        export_vbox.addWidget(self.export_desc_label)

        export_btn_row = QHBoxLayout()
        export_btn_row.setSpacing(8)
        self.export_xlsx_btn = QPushButton(tr("Export Excel Data (.xlsx)"))
        self.export_csv_btn = QPushButton(tr("Export CSV Data (.csv)"))
        for export_btn in (self.export_xlsx_btn, self.export_csv_btn):
            export_btn.setProperty("class", "template-action")
            export_btn_row.addWidget(export_btn)
        export_btn_row.addStretch()
        export_vbox.addLayout(export_btn_row)

        # Starter templates for the import above (same columns, header-only)
        export_vbox.addSpacing(4)
        self.import_templates_divider = QFrame()
        self.import_templates_divider.setObjectName("importTemplatesDivider")
        self.import_templates_divider.setFrameShape(QFrame.NoFrame)
        export_vbox.addWidget(self.import_templates_divider)
        export_vbox.addSpacing(6)

        self.import_templates_label = QLabel()
        self.import_templates_label.setWordWrap(True)
        self.import_templates_label.setProperty("class", "template-hint")
        export_vbox.addWidget(self.import_templates_label)

        templates_btn_row = QHBoxLayout()
        templates_btn_row.setSpacing(8)
        self.import_templates_btn = QPushButton(tr("Save Excel Templates (.xlsx)"))
        self.import_templates_csv_btn = QPushButton(tr("Save CSV Templates (.csv)"))
        for templates_btn in (self.import_templates_btn,
                              self.import_templates_csv_btn):
            templates_btn.setProperty("class", "template-action")
            templates_btn_row.addWidget(templates_btn)
        templates_btn_row.addStretch()
        export_vbox.addLayout(templates_btn_row)

        self.backup_vbox.addWidget(self.restore_group)
        self.backup_vbox.addWidget(self.import_group)
        self.backup_vbox.addWidget(self.export_group)
        self.backup_vbox.addStretch()
        self.backup_tab = self._make_scrollable_tab(self.backup_tab)
        self.tabs.addTab(self.backup_tab, tr("Database Backup"))

        # Wiring
        self.backup_create_btn.clicked.connect(self._on_create_manual_backup)
        self.backup_refresh_btn.clicked.connect(self._refresh_backup_list)
        self.backup_restore_btn.clicked.connect(self._on_restore_selected_backup)
        self.import_btn.clicked.connect(self._on_import_data)
        self.import_templates_btn.clicked.connect(
            lambda: self._on_save_import_templates("xlsx")
        )
        self.import_templates_csv_btn.clicked.connect(
            lambda: self._on_save_import_templates("csv")
        )
        self.export_xlsx_btn.clicked.connect(self._on_export_workbook)
        self.export_csv_btn.clicked.connect(lambda: self._on_export_data("csv"))

        # The backup list is populated lazily the first time this tab is shown.
        self._update_import_access()

    def _init_dev_tab(self):
        self.advanced_tab = QWidget()
        self.advanced_vbox = QVBoxLayout(self.advanced_tab)

        self.dev_group = QGroupBox(tr("Developer Settings"))
        self.dev_form = QFormLayout(self.dev_group)

        self.dev_options_check = QCheckBox(tr("Enable Developer Options"))
        self.dev_form.addRow(self.dev_options_check)

        self.logging_check = QCheckBox(tr("Enable File Logging"))
        self.dev_form.addRow(self.logging_check)

        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setEnabled(False)
        self.dev_form.addRow(tr("Hot-Reload Style:"), self.shortcut_edit)

        self.advanced_vbox.addWidget(self.dev_group)

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

    def _refresh_backup_list(self):
        try:
            self._backup_entries = list_backups(BACKUPS_DIR)
            self.backup_list_combo.clear()

            if not self._backup_entries:
                self.backup_list_combo.addItem(tr("(No backups found)"))
                self.backup_restore_btn.setEnabled(False)
                return

            self.backup_restore_btn.setEnabled(getattr(self, "_can_restore_backup", False))

            for entry in self._backup_entries:
                tag = tr(" [MANUAL]") if entry.is_manual else ""
                label = f"{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}{tag}"
                self.backup_list_combo.addItem(label, userData=str(entry.backup_path))

            logger.info("SettingsPage: Backup list refreshed (%d entries)", len(self._backup_entries))
            self.backup_status_label.setText(tr("Status: OK"))
        except Exception:
            logger.exception("SettingsPage: Failed to refresh backup list")
            QMessageBox.critical(self, tr("Settings"), tr("Failed to refresh backup list. Check logs."))

    def _on_create_manual_backup(self):
        if not can(self._current_user, "backup_restore"):
            return
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
        if not can(self._current_user, "backup_restore"):
            return
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

            logger.info("Restore requested from SettingsPage: %s", selected_backup)
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

    # ------------------------------------------------------- Spreadsheet import --

    def _update_import_access(self):
        """Enables the import buttons only for users allowed to edit records."""
        allowed = can(self._current_user, "edit_records")
        self.import_btn.setEnabled(allowed)
        self.import_templates_btn.setEnabled(allowed)
        self.import_templates_csv_btn.setEnabled(allowed)
        self.import_group.setEnabled(allowed)
        self.export_group.setEnabled(allowed)
        self._update_import_description()

    def _update_backup_access(self):
        """Enables backup/restore only for users allowed to back up the DB.

        The Database Backup tab shows for every role that can view settings,
        so creating or (destructively) restoring a backup must be gated on the
        dedicated ``backup_restore`` permission rather than tab visibility.
        """
        allowed = can(self._current_user, "backup_restore")
        self._can_restore_backup = allowed
        self.backup_create_btn.setEnabled(allowed)
        self.backup_refresh_btn.setEnabled(allowed)
        self.backup_list_combo.setEnabled(allowed)
        has_backups = bool(getattr(self, "_backup_entries", None))
        self.backup_restore_btn.setEnabled(allowed and has_backups)

    def _update_import_description(self):
        """Keeps the description in sync with access in both directions.

        The group is built while ``_current_user`` is still empty, so the label
        starts out as the "no permission" text; it must be restored once an
        authorised user logs in, not only when the language changes.
        """
        if can(self._current_user, "edit_records"):
            self.import_desc_label.setText(tr(
                "Import owners, pets, supplies, visits and other clinic records from an Excel or CSV file. Existing records are skipped, never overwritten."
            ))
            self.import_templates_label.setText(tr(
                "Starter templates: header-only sheets for every data type (Owners, Pets, "
                "Supplies, Appointments and more). Hover a header for examples, read the "
                "Instructions sheet, then import your filled copy above."
            ))
            self.export_desc_label.setText(tr(
                "Export your current data using the same columns as the templates. "
                "Excel writes one workbook with a sheet per data type; CSV writes one "
                "file per data type. Open an export, change what you need, then import "
                "it back."
            ))
        else:
            self.import_desc_label.setText(tr(
                "You do not have permission to import data."
            ))
            self.import_templates_label.setText("")
            self.export_desc_label.setText("")

    def _on_import_data(self):
        """Opens the Excel / CSV import dialog and refreshes pages afterwards."""
        if not can(self._current_user, "edit_records"):
            QMessageBox.warning(
                self, tr("Settings"), tr("You do not have permission to import data.")
            )
            return

        from src.ui.dialogs.import_data_dialog import ImportDataDialog

        dialog = ImportDataDialog(self, current_user=self._current_user)
        dialog.data_changed.connect(self._refresh_after_import)
        dialog.exec()

    def _on_save_import_templates(self, file_format="xlsx"):
        """Saves the starter templates - one workbook, or one CSV per entity.

        The Excel button writes a single headers-only workbook with a sheet per
        data type (same shape as the data export, so the filled copy imports
        with the every-sheet option); a delimited file holds one data type only,
        so the CSV button still drops one file per entity into a folder.
        """
        if not can(self._current_user, "edit_records"):
            return

        from src.core import importer

        if normalize_template_format(file_format) == "xlsx":
            self._on_save_templates_workbook()
            return

        directory = QFileDialog.getExistingDirectory(
            self, tr("Choose Folder for Import Templates"), ""
        )
        if not directory:
            return
        try:
            written = importer.write_all_templates(directory, file_format)
        except Exception as e:
            logger.exception("Writing import templates failed")
            QMessageBox.critical(
                self, tr("Settings"),
                tr("Failed to write import templates.\n{error}").format(error=str(e)),
            )
            return
        QMessageBox.information(
            self, tr("Settings"),
            tr("Import templates saved to:\n{path}").format(path=directory),
        )
        logger.info("Import templates written: %s", [str(p) for p in written])

    def _on_save_templates_workbook(self):
        """Writes ONE headers-only workbook, a sheet per data type."""
        if not can(self._current_user, "edit_records"):
            return

        from src.core import importer

        path, _selected_filter = QFileDialog.getSaveFileName(
            self, tr("Save Excel Templates"), importer.TEMPLATE_WORKBOOK_NAME,
            tr("Excel Workbooks (*.xlsx)"),
        )
        if not path:
            return
        if Path(path).suffix.lower() not in importer.EXCEL_EXTENSIONS:
            path += ".xlsx"

        try:
            written = importer.write_templates_workbook(path)
        except Exception as e:
            logger.exception("Writing the templates workbook failed")
            QMessageBox.critical(
                self, tr("Settings"),
                tr("Failed to write import templates.\n{error}").format(error=str(e)),
            )
            return
        QMessageBox.information(
            self, tr("Settings"),
            tr("Import templates saved to:\n{path}").format(path=str(written)),
        )
        logger.info("Template workbook written: %s", written)

    def _on_export_workbook(self):
        """Writes every data type into ONE Excel workbook, one sheet each."""
        if not can(self._current_user, "edit_records"):
            return

        from src.core import exporter, importer

        path, _selected_filter = QFileDialog.getSaveFileName(
            self, tr("Export Excel Data"), exporter.WORKBOOK_NAME,
            tr("Excel Workbooks (*.xlsx)"),
        )
        if not path:
            return
        if Path(path).suffix.lower() not in importer.EXCEL_EXTENSIONS:
            path += ".xlsx"

        try:
            written, counts, total = exporter.write_workbook(path)
        except Exception as e:
            logger.exception("Writing the data export workbook failed")
            QMessageBox.critical(
                self, tr("Settings"),
                tr("Failed to export the data.\n{error}").format(error=str(e)),
            )
            return

        summary = "\n".join(
            "{name}: {count}".format(
                name=importer.entity_sheet_name(entity_key),
                count=counts[entity_key],
            )
            for entity_key in exporter.EXPORT_KEYS
        )
        QMessageBox.information(
            self, tr("Settings"),
            tr("Exported {total} record(s) to:\n{path}\n\n{summary}").format(
                total=total, path=str(written), summary=summary),
        )
        logger.info("Data export workbook written: %s (%s record(s))",
                    written, total)

    def _on_export_data(self, file_format="csv"):
        """Writes one file per entity, in template layout, to a chosen folder.

        Used by the CSV button - a delimited file cannot hold several data
        types; the Excel button uses :meth:`_on_export_workbook` instead.
        """
        if not can(self._current_user, "edit_records"):
            return

        from src.core import exporter

        directory = QFileDialog.getExistingDirectory(
            self, tr("Choose Folder for Data Export"), ""
        )
        if not directory:
            return
        try:
            written = exporter.write_all_exports(directory, file_format)
        except Exception as e:
            logger.exception("Writing data export failed")
            QMessageBox.critical(
                self, tr("Settings"),
                tr("Failed to export the data.\n{error}").format(error=str(e)),
            )
            return

        total = sum(count for _path, count in written)
        summary = "\n".join(
            "{name}: {count}".format(name=path.name, count=count)
            for path, count in written
        )
        QMessageBox.information(
            self, tr("Settings"),
            tr("Exported {total} record(s) to:\n{path}\n\n{summary}").format(
                total=total, path=directory, summary=summary),
        )
        logger.info("Data export written: %s",
                    [(str(p), n) for p, n in written])

    def _refresh_after_import(self, entity_key):
        """Refreshes the pages affected by a completed import."""
        try:
            main_win = self.window()
            main_page = getattr(main_win, "main_page", None)
            if main_page is None:
                return
            db_page = getattr(main_page, "database_page", None)
            dash_page = getattr(main_page, "dashboard_page", None)
            visits_standalone = getattr(main_page, "visits_page", None)

            if entity_key in ("owners", "pets") and db_page is not None:
                db_page.clients_page.refresh_active_tab()
                db_page.visits_page.refresh_visits_table()
            elif entity_key == "visits":
                if db_page is not None:
                    db_page.visits_page.refresh_active_tab()
                    db_page.clients_page.refresh_active_tab()
                    db_page.receipts_page.refresh_receipts_table()
                if visits_standalone is not None:
                    visits_standalone.refresh_visits_table()
            elif entity_key == "supplies" and db_page is not None:
                db_page.supplies_page.refresh_all_tabs()
                db_page.receipts_page.refresh_receipts_table()

            if dash_page is not None:
                dash_page.refresh_data()
        except Exception:
            # Never crash the UI over a refresh failure.
            logger.exception("Post-import refresh failed")

    def _load_settings(self):
        from src.config.constants import DEFAULT_CLINIC_NAME

        # Profile
        self.clinic_name_edit.setText(SettingsManager.get(SETTINGS_KEYS["CLINIC"], DEFAULT_CLINIC_NAME))
        logo_path = SettingsManager.get(SETTINGS_KEYS["LOGO"], "")
        self.logo_path_edit.setText(logo_path)
        self._update_logo_preview(logo_path)

        # Financial
        self.consult_fee_edit.setValue(
            float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
        )

        # Scheduling Rules
        try:
            auto_cancel = int(float(SettingsManager.get(
                status_resolver.SETTING_KEY, DEFAULT_AUTO_CANCEL_HOURS)))
        except (TypeError, ValueError):
            auto_cancel = DEFAULT_AUTO_CANCEL_HOURS
        self.auto_cancel_edit.setValue(
            min(max(auto_cancel, AUTO_CANCEL_HOURS_MIN), AUTO_CANCEL_HOURS_MAX)
        )
        self._update_late_preview()

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

        # Drop any staged Custom Lists edits (Cancel / reload reverts them).
        if self._pending_list_ops:
            self._pending_list_ops.clear()
            self._refresh_custom_lists()

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

    def set_current_user(self, user):
        """Stores the logged-in user for admin gating."""
        self._current_user = user if user else {}
        self._apply_translated_tab_titles()
        if hasattr(self, "import_group"):
            self._update_import_access()
        if hasattr(self, "backup_create_btn"):
            self._update_backup_access()

    def save_settings(self):
        """Validates and saves all settings plus staged Custom Lists edits."""
        # Validate clinic name
        clinic_name = self.clinic_name_edit.text().strip()
        if not clinic_name:
            QMessageBox.warning(self, tr("Validation Error"), tr("Clinic Name cannot be empty."))
            return
        if (
            len(clinic_name) > CLINIC_NAME_MAX_LEN
            or not QRegularExpression(CLINIC_NAME_REGEX).match(clinic_name).hasMatch()
        ):
            QMessageBox.warning(
                self,
                tr("Validation Error"),
                tr("Clinic Name contains invalid characters or is too long."),
            )
            return

        # Save settings (including any staged Custom Lists edits)
        failures = self.apply_settings()

        if failures:
            QMessageBox.warning(
                self,
                tr("Custom Lists"),
                tr("Some list changes could not be saved: {items}").format(
                    items=", ".join(failures)
                ),
            )
        else:
            QMessageBox.information(self, tr("Success"), tr("Settings saved successfully."))

    def cancel_settings(self):
        """Reloads settings to discard unsaved page edits."""
        self._load_settings()

    def apply_settings(self):
        """Saves the current form values without closing the page.

        Returns the labels of staged Custom Lists edits that failed to write
        (empty when everything landed).
        """
        # Batch update settings to avoid multiple disk writes
        settings_data = SettingsManager.load()
        # Capture the values the UI currently runs with so we can apply only
        # the changes that actually moved (language / window mode).
        old_window_mode = settings_data.get(SETTINGS_KEYS["MODE"], "windowed")
        old_language = settings_data.get(SETTINGS_KEYS["LANG"], "en")
        settings_data[SETTINGS_KEYS["CLINIC"]] = self.clinic_name_edit.text().strip()
        settings_data[SETTINGS_KEYS["LOGO"]] = self.logo_path_edit.text().strip()
        settings_data[SETTINGS_KEYS["MODE"]] = str(self.window_mode_combo.currentData()).lower()
        settings_data[SETTINGS_KEYS["THEME"]] = str(self.theme_combo.currentData())
        settings_data[SETTINGS_KEYS["DEV"]] = self.dev_options_check.isChecked()
        settings_data["enable_logging"] = self.logging_check.isChecked()
        settings_data["refresh_shortcut"] = self.shortcut_edit.keySequence().toString()
        settings_data[SETTINGS_KEYS["LANG"]] = self.language_combo.currentData()
        settings_data["consultation_fee"] = self.consult_fee_edit.value()
        settings_data[status_resolver.SETTING_KEY] = self.auto_cancel_edit.value()

        SettingsManager.save(settings_data)

        # Staged Custom Lists edits land in the database only here (Save).
        list_failures = self._apply_pending_list_ops()

        # Save CustomPalette (RGB)
        self.settings.beginGroup("CustomPalette")
        for key, val in self.custom_colors.items():
            self.settings.setValue(key, val)
        self.settings.endGroup()

        self.settings.sync()

        self._handle_style_refresh()

        main_window = self.window()
        if main_window and hasattr(main_window, "update_window_title"):
            main_window.update_window_title()

        # Apply window mode and language changes immediately so the user sees
        # them without restarting the app.
        if main_window:
            new_window_mode = str(settings_data.get(SETTINGS_KEYS["MODE"], "")).lower()
            if new_window_mode != str(old_window_mode).lower() and hasattr(main_window, "apply_window_mode"):
                main_window.apply_window_mode()

            new_language = settings_data.get(SETTINGS_KEYS["LANG"])
            if new_language != old_language and hasattr(main_window, "update_ui_language"):
                main_window.update_ui_language()

        return list_failures

    def _handle_style_refresh(self):
        main_window = self.window()
        if not (main_window and hasattr(main_window, "load_stylesheet")):
            return

        theme = str(self.theme_combo.currentData() or "").strip().lower()
        if hasattr(main_window, "main_page"):
            main_window.main_page.dark_mode_btn.setChecked(theme == "dark")

        palette_obj = None
        if theme == "custom":
            palette_obj = ThemeConfig(self.custom_colors)

        main_window.load_stylesheet(str(STYLES_DIR / "style.qss"), theme, palette_obj)

    def _set_form_label(self, form, row, text):
        """Update the label text at the given row of a QFormLayout."""
        item = form.itemAt(row, QFormLayout.LabelRole)
        if item and item.widget():
            item.widget().setText(text)

    def _retranslate_combo(self, combo, options):
        """Rebuild combo items with translated text, preserving selection."""
        current_data = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for option in options:
            if isinstance(option, (tuple, list)):
                name, code = option
                combo.addItem(tr(name), code)
            else:
                combo.addItem(tr(option), option)
        if current_data is not None:
            idx = combo.findData(current_data)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def retranslate_ui(self):
        """Updates text on this page when the language changes."""
        self._apply_translated_tab_titles()

        # Page-level buttons
        self.save_btn.setText(tr("Save"))
        self.cancel_btn.setText(tr("Cancel"))

        # --- Profile tab ---
        self.identity_group.setTitle(tr("Clinic Information"))
        self.clinic_name_edit.setPlaceholderText(tr("Enter your clinic's name"))
        self.logo_path_edit.setPlaceholderText(tr("Select a custom logo..."))
        self.browse_btn.setText(tr("Browse..."))
        self.reset_btn.setText(tr("Reset"))
        self.fees_group.setTitle(tr("Financial Settings"))
        self.consult_fee_edit.setToolTip(tr("Default consultation fee charged per visit"))
        self.scheduling_group.setTitle(tr("Scheduling Rules"))
        self.auto_cancel_edit.setToolTip(tr(
            "How long an appointment or follow-up stays Late after its "
            "scheduled time before it is automatically marked Canceled."
        ))
        self._update_late_preview()
        self._set_form_label(self.identity_form, 0, tr("Clinic Name:"))
        self._set_form_label(self.identity_form, 1, tr("Custom Logo:"))
        self._set_form_label(self.fees_form, 0, tr("Consultation Fee:"))
        self._set_form_label(self.scheduling_form, 0, tr("Auto-cancel after:"))

        # --- Appearance tab ---
        self.mode_group.setTitle(tr("Window Mode"))
        self._set_form_label(self.mode_form, 0, tr("Startup Window Mode:"))
        self.theme_group.setTitle(tr("Visual Style"))
        self._set_form_label(self.theme_form, 0, tr("Default Theme:"))
        self.lang_group.setTitle(tr("Localization"))
        self._set_form_label(self.lang_form, 0, tr("Language:"))
        self.palette_editor_container.setTitle(tr("Custom Palette Editor"))
        self._retranslate_combo(self.window_mode_combo, WINDOW_MODE_OPTIONS)
        self._retranslate_combo(self.theme_combo, THEME_OPTIONS)
        self._retranslate_combo(self.language_combo, LANGUAGE_OPTIONS)

        # --- Backup tab ---
        self.backup_page_title.setText(tr("Backup & Data Transfer"))
        self.backup_page_hint.setText(tr(
            "Create full backups of your database, restore an older copy, or "
            "move records between computers with Excel or CSV files."
        ))
        self.backup_experimental_banner.setText(tr(
            "Note: importing and exporting data is an experimental feature and may cause "
            "issues. Keep a backup before you use it, and check the results carefully."
        ))
        self.backup_create_btn.setText(tr("Create Backup Now"))
        self.restore_group.setTitle(tr("Backup && Restore"))
        self.backup_refresh_btn.setText(tr("Refresh"))
        self.backup_restore_btn.setText(tr("Restore Selected Backup"))
        self.import_group.setTitle(tr("Import Data"))
        self.import_btn.setText(tr("Import from Excel or CSV"))
        self.import_templates_btn.setText(tr("Save Excel Templates (.xlsx)"))
        self.import_templates_csv_btn.setText(tr("Save CSV Templates (.csv)"))
        self.export_group.setTitle(tr("Export Data"))
        self.export_xlsx_btn.setText(tr("Export Excel Data (.xlsx)"))
        self.export_csv_btn.setText(tr("Export CSV Data (.csv)"))
        self._update_import_description()

        # --- Inventory tab ---
        self.inv_group.setTitle(tr("Inventory Categories"))
        self.cat_label.setText(tr("Categories:"))
        self.sub_label.setText(tr("Sub-Categories:"))
        self.add_cat_btn.setText(tr("+ Category"))
        self.del_cat_btn.setText(tr("- Category"))
        self.add_sub_btn.setText(tr("+ Sub-Cat"))
        self.del_sub_btn.setText(tr("- Sub-Cat"))
        self.list_group.setTitle(tr("Clinic Lists"))
        self.spec_label.setText(tr("Species:"))
        self.add_spec_btn.setText(tr("+ Species"))
        self.del_spec_btn.setText(tr("- Species"))
        self.serv_label.setText(tr("Services:"))
        self.add_serv_btn.setText(tr("+ Service"))
        self.del_serv_btn.setText(tr("- Service"))
        self.list_hint.setText(tr("Changes are applied when you click Save."))

        # --- DEV tab ---
        self.dev_group.setTitle(tr("Developer Settings"))
        self.dev_options_check.setText(tr("Enable Developer Options"))
        self.logging_check.setText(tr("Enable File Logging"))
        self._set_form_label(self.dev_form, 2, tr("Hot-Reload Style:"))
