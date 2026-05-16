"""
Primary Application Orchestrator for PET.

Manages the main window lifecycle, including sidebar navigation, theme switching,
page transitions, and status bar controls. Coordinates between all UI components
and handles window geometry, styling, and internationalization.
"""

import os
import logging
from functools import partial
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QPushButton, 
    QLabel, QStackedWidget, QToolButton, QSizePolicy, QMenu, 
    QMessageBox, QApplication, QDialog, QShortcut
)
from PyQt5.QtCore import QSize, Qt, QSettings, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QKeySequence


from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.ui.pages import dashboard, home, receipts, supplies, clients
from src.ui.themes.color_palettes import get_styled_qss, PALETTES, ThemeManager, get_active_palette
from src.ui.side_menu import SideMenu, recolor_icon
from src.ui.dialogs.settings import SettingsDialog
from src.ui.dialogs.reorder_settings_dialog import ReorderSettingsDialog
from src.core.backup_manager import create_backup, prune_backups
from src.core.database import get_user_db_path
from src.config import (
    ICONS_DIR, STYLES_DIR, ORG_NAME, APP_NAME, SETTINGS_ORG, SETTINGS_APP, ASSETS_DIR,
    DEFAULT_CLINIC_NAME, DEFAULT_CLINIC_OWNER,
    BACKUPS_DIR, BACKUP_KEEP_24HOURS, BACKUP_KEEP_DAILY_DAYS, BACKUP_KEEP_MANUAL_FOREVER,
    WINDOW_CONFIG
)

logger = logging.getLogger(__name__)

#============================== TRANSLATABLE STRINGS ===================================================#

STRINGS = {
    "UI_OK": "OK",
    "UI_CANCEL": "Cancel",
    "MENU_REORDER": "Reorder Levels",
    "MENU_SETTINGS": "Settings",
    "GREETING_HELLO": "Hello, {name}",
    "GREETING_GOOD": "Good {time}!",
    "TIME_MORNING": "morning",
    "TIME_AFTERNOON": "afternoon",
    "TIME_EVENING": "evening",
    "LOG_UI_UPDATE": "UI language updated to '{lang}'",
    "LOG_TRANS_FAIL": "Failed to reload translations",
    "LOG_STYLE_RELOAD": "Stylesheet reloaded via shortcut at {time}",
    "LOG_STYLE_FAIL": "Failed to load stylesheet from {path}: {error}"
}

#==================================== UI CONSTANTS =====================================================#

STATUS_BAR_CONFIG = {
    "MENU_BTN": (42, 42),
    "MENU_ICO": (32, 32),
    "THEME_BTN": (32, 32),
    "THEME_ICO": (28, 28),
    "ACCOUNT_BTN": (60, 60),
    "ACCOUNT_ICO": (50, 50)
}

ICONS = {
    "WINDOW": "logo-ico.png",
    "MENU": "menu-ico.png",
    "DARK_MODE": "dark-mode-ico.png",
    "PROFILE": "profile-ico.png"
}

# Greeting Timing
GREETING_AFTERNOON_HOUR = 12
GREETING_EVENING_HOUR = 18

#=================================== HELPERS ==========================================================#
class LoadingDialog(QDialog):
    """Blocking loading dialog used while a shutdown backup is in progress."""

    def __init__(self, message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(message)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self.label = QLabel(message)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # Use Qt's built-in busy indicator as a spinner-like element.
        self.spinner = QLabel()
        self.spinner.setFixedSize(48, 48)
        self.spinner.setAlignment(Qt.AlignCenter)
        self.spinner.setText("⏳")
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)

        # If the app is themed via QSS, keep colors consistent.
        self.setStyleSheet("QLabel { qproperty-alignment: 'AlignCenter'; }")


class BackupWorker(QThread):
    """Runs backup/prune routines in a worker thread for closeEvent gating."""

    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, db_conn_unused=None, parent=None):
        # db_conn_unused kept for compatibility with earlier design notes.
        super().__init__(parent)
        self._db_conn_unused = db_conn_unused

    def run(self):
        try:
            create_backup(
                db_path=get_user_db_path(),
                backups_dir=BACKUPS_DIR,
                backup_kind="auto",
            )
            prune_backups(
                backups_dir=BACKUPS_DIR,
                now=None,
                keep_24h=BACKUP_KEEP_24HOURS,
                keep_daily_days=BACKUP_KEEP_DAILY_DAYS,
                keep_manual_forever=BACKUP_KEEP_MANUAL_FOREVER,
            )
            self.finished_with_result.emit(True, "")
        except Exception as e:
            # Emit failure with the error message for the UI.
            self.finished_with_result.emit(False, str(e))

def get_time_of_day():
    """Returns the current period of the day for greeting message."""
    hour = datetime.now().hour
    if hour < GREETING_AFTERNOON_HOUR:
        return STRINGS["TIME_MORNING"]
    elif hour < GREETING_EVENING_HOUR:
        return STRINGS["TIME_AFTERNOON"]
    return STRINGS["TIME_EVENING"]

#============================================== CODE =====================================================#


class MainWindow(QMainWindow):

    """Main application window orchestrator.

    
    Manages the complete application lifecycle including:
    - Window geometry and styling
    - Sidebar and page navigation
    - Theme switching and settings
    - Internationalization and RTL support
    - Stylesheet management with hot-reload for developers
    """
    
    def __init__(self):
        """Initialize the main application window and all components."""
        super().__init__()
        # Must match SettingsDialog's QSettings namespace for CustomPalette values.
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # Ensure backup directory exists + prune old backups on startup
        try:
            prune_backups(
                backups_dir=BACKUPS_DIR,
                now=None,
                keep_24h=BACKUP_KEEP_24HOURS,
                keep_daily_days=BACKUP_KEEP_DAILY_DAYS,
                keep_manual_forever=BACKUP_KEEP_MANUAL_FOREVER,
            )
        except Exception:
            logger.exception("Backup pruning failed on startup")

        # Initialize Window
        self.setProperty("app_language", SettingsManager.get("language", "en"))
        self.update_window_title()
        
        self.update_app_icon()
        self.setBaseSize(*WINDOW_CONFIG["DEFAULT_SIZE"])
        self._setup_ui()
        self.central_widget.setProperty("app_language", self.property("app_language"))
        self.update_ui_language()
        self._setup_status_bar_connections()
        self._setup_menu_connections()
        self._setup_dev_shortcuts()
        
        initial_theme = SettingsManager.get("theme", "light").lower()
        self.load_stylesheet(STYLES_DIR / "style.qss", initial_theme)
    
    def _setup_ui(self):
        """Initializes the central widget, sidebars, and main content area."""
        self.central_widget = QWidget(self)
        self.central_widget.setObjectName("central_widget")
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        #   Importing (creating instance) from the Side Menu class
        self.sidemenus = SideMenu(self.central_widget)
        #   Importing (creating instance) from the Main Page class
        self.main_page = MainPage(self.central_widget)
        #   Adding (side menu small , side menu big , main page) widgets to the Central Widget Layout
        self.main_layout.addWidget(self.sidemenus.sidemenu_small)
        self.main_layout.addWidget(self.sidemenus.sidemenu_big)
        self.main_layout.addWidget(self.main_page)
        # Make this Widget the Central Widget
        self.setCentralWidget(self.central_widget)
        
        # Data Refresh Connections: Update dependent views when data changes
        refresh_triggers = [
            self.main_page.clients_page, 
            self.main_page.supplies_page, 
            self.main_page.home_page, 
            self.main_page.receipts_page
        ]
        
        for page in refresh_triggers:
            page.data_changed.connect(self.main_page.dashboard_page.refresh_data)

        # Low-stock KPI also depends on analytics cache; ensure it refreshes
        # whenever supply quantities change (including inline edits/restocks).
        try:
            # Refresh KPI/insights/appointments directly (and thus invalidate analytics cache)
            self.main_page.supplies_page.data_changed.connect(self.main_page.dashboard_page.refresh_kpis_insights_appointments)
        except Exception:

            # Backward compatible: if method doesn't exist, ignore.
            pass

            
        # Specialized refreshes
        self.main_page.clients_page.data_changed.connect(self.main_page.home_page.refresh_home_table)
        self.main_page.supplies_page.data_changed.connect(self.main_page.home_page.refresh_home_table)
        
        self.main_page.home_page.data_changed.connect(self.main_page.clients_page.refresh_active_tab)
        self.main_page.clients_page.data_changed.connect(self.main_page.supplies_page.refresh_all_tabs)
        self.main_page.home_page.data_changed.connect(self.main_page.supplies_page.refresh_all_tabs)
        
        for p in [self.main_page.clients_page, self.main_page.home_page, self.main_page.supplies_page]:
            p.data_changed.connect(self.main_page.receipts_page.refresh_receipts_table)
    
    def _setup_menu_connections(self):
        """Connects sidebar buttons to page switching and synchronizes menu states."""
        # Map navigation buttons to page indices and synchronize states
        for index, (name, _) in enumerate(self.sidemenus.menu_btn_names.items()):
            small = getattr(self.sidemenus, f"{name}_btn_small")
            big = getattr(self.sidemenus, f"{name}_btn_big")
            
            for btn in [small, big]:
                btn.clicked.connect(partial(self.main_page.main_page_content.setCurrentIndex, index))
            
            small.toggled.connect(big.setChecked)
            big.toggled.connect(small.setChecked)
        
        # Exit logic
        for btn in [self.sidemenus.exit_btn_small, self.sidemenus.exit_btn_big]:
            btn.clicked.connect(self.close)
        self.sidemenus.exit_btn_small.toggled.connect(self.sidemenus.exit_btn_big.setChecked)
        self.sidemenus.exit_btn_big.toggled.connect(self.sidemenus.exit_btn_small.setChecked)
    

    
    def apply_window_mode(self):
        """Applies the saved startup window mode (windowed or fullscreen)."""
        mode = SettingsManager.get("window_mode", WINDOW_CONFIG["DEFAULT_MODE"])
        current_state = self.windowState()
        
        if mode == "fullscreen":
            if not (current_state & Qt.WindowFullScreen):
                self.showFullScreen()
        else:
            if current_state & Qt.WindowFullScreen:
                self.showNormal()
                self.show()
                self.activateWindow()
                self.raise_()
            elif current_state & Qt.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()
                self.show()
    
    def update_window_title(self):
        """Updates the window title based on the clinic name in settings."""
        clinic_name = SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME)
        self.setWindowTitle(clinic_name)
        if hasattr(self, "sidemenus"):
            self.sidemenus.retranslate_ui()

    def update_app_icon(self):
        """Updates the window icon from settings or fallback to default."""
        custom_logo = SettingsManager.get("custom_logo", "")
        if custom_logo and os.path.exists(custom_logo):
            icon_path = custom_logo
        else:
            icon_path = os.path.join(ICONS_DIR, ICONS["WINDOW"])
        self.setWindowIcon(QIcon(icon_path))

    def update_ui_language(self):
        """Reloads translations and refreshes text across the UI, handling RTL if needed."""
        from src.utils.i18n import load_translations
        
        lang = SettingsManager.get("language", "en")
        trans_path = ASSETS_DIR / "translations.json"
        
        if load_translations(str(trans_path), lang=lang):
            self.setProperty("app_language", lang)
            if hasattr(self, 'central_widget'):
                self.central_widget.setProperty("app_language", lang)

            # Propagate language to the sidebar containers as well.
            # QSS selectors use QWidget[app_language="..."] and must see updated property on the
            # widget owning the navigation buttons.
            if hasattr(self, "sidemenus"):
                try:
                    self.sidemenus.setProperty("app_language", lang)
                    if hasattr(self.sidemenus, "sidemenu_big"):
                        self.sidemenus.sidemenu_big.setProperty("app_language", lang)
                    if hasattr(self.sidemenus, "sidemenu_small"):
                        self.sidemenus.sidemenu_small.setProperty("app_language", lang)
                except Exception:
                    logger.exception("Failed to propagate app_language to sidemenus")

            # Stylesheet reload is now handled by the caller (SettingsDialog) to avoid double-rendering

            # Force Qt to re-evaluate QSS selectors that depend on dynamic properties.
            # Use unpolish/polish on the actual sidebar widgets and also re-assign stylesheet
            # to guarantee selector re-matching.
            try:
                if hasattr(self, "sidemenus"):
                    if hasattr(self.sidemenus, "sidemenu_big"):
                        self.sidemenus.sidemenu_big.style().unpolish(self.sidemenus.sidemenu_big)
                        self.sidemenus.sidemenu_big.style().polish(self.sidemenus.sidemenu_big)
                    if hasattr(self.sidemenus, "sidemenu_small"):
                        self.sidemenus.sidemenu_small.style().unpolish(self.sidemenus.sidemenu_small)
                        self.sidemenus.sidemenu_small.style().polish(self.sidemenus.sidemenu_small)

                if hasattr(self, "central_widget"):
                    self.central_widget.style().unpolish(self.central_widget)
                    self.central_widget.style().polish(self.central_widget)

                # Re-apply the same stylesheet so the dynamic property selectors take effect.
                theme = str(SettingsManager.get("theme", "light")).lower()
                self.load_stylesheet(STYLES_DIR / "style.qss", theme, refresh_cache=True)
            except Exception:
                logger.exception("Failed to force stylesheet refresh after app_language update")


            # Trigger recursive text update
            self.retranslate_ui()
            logger.info(STRINGS["LOG_UI_UPDATE"].format(lang=lang))
        else:
            logger.warning(STRINGS["LOG_TRANS_FAIL"])

    def retranslate_ui(self):
        """Coordinates the text update for all nested components."""
        self.update_window_title()  # This now also updates the side menu branding
        self.main_page.retranslate_ui()

    def _setup_dev_shortcuts(self):
        """Configures global shortcuts if developer mode is enabled."""
        # Remove any previously-registered shortcut (avoid stale/duplicate bindings).
        if hasattr(self, "refresh_shortcut") and self.refresh_shortcut is not None:
            try:
                self.refresh_shortcut.setEnabled(False)
                self.refresh_shortcut.setParent(None)
            except Exception:
                pass
            self.refresh_shortcut = None

        if SettingsManager.get("dev_mode", False):
            shortcut_key = (SettingsManager.get("refresh_shortcut", "F5") or "").strip()
            if not shortcut_key:
                shortcut_key = "F5"

            self.refresh_shortcut = QShortcut(QKeySequence(shortcut_key), self)
            # Make it work regardless of which child widget has focus.
            self.refresh_shortcut.setContext(Qt.ApplicationShortcut)
            self.refresh_shortcut.activated.connect(self._hot_reload_style)
    
    def _hot_reload_style(self):
        """Reloads the stylesheet without restarting (developer feature)."""
        # Reload using the currently selected theme (supports "custom" too).
        theme = str(SettingsManager.get("theme", "light")).lower()
        # Force refresh_cache=True so the file is re-read from disk
        self.load_stylesheet(STYLES_DIR / "style.qss", theme, refresh_cache=True)
        logger.info(STRINGS["LOG_STYLE_RELOAD"].format(time=datetime.now().strftime('%H:%M:%S')))
    
    def _setup_status_bar_connections(self):
        """Connects top status bar controls to their respective logic."""
        self.main_page.toggle_menu_btn.toggled.connect(self._toggle_side_menu)
        self.main_page.dark_mode_btn.toggled.connect(self._toggle_dark_mode)
    
    def _toggle_side_menu(self, checked):
        """Toggles between collapsed and expanded side menus (animated via SideMenu)."""
        if checked:
            self.sidemenus.expand_big_menu()
        else:
            self.sidemenus.collapse_small_menu()
    
    def _toggle_dark_mode(self, checked):
        """Toggles between light and dark themes.
        
        Args:
            checked (bool): True for dark mode, False for light mode.
        """
        theme = "dark" if checked else "light"
        
        SettingsManager.set("theme", theme)
        self.load_stylesheet(STYLES_DIR / "style.qss", theme)
        self.retranslate_ui()
    
    def load_stylesheet(self, path, theme="light", palette_obj=None, refresh_cache=False):
        """Loads a stylesheet, processes palette variables, and applies it."""
        try:
            # 1. Use provided palette or fetch the active one
            if palette_obj is None:
                palette_obj = get_active_palette()
            
            # 2. Apply the stylesheet
            self.setStyleSheet(get_styled_qss(path, theme, palette_obj, refresh_cache=refresh_cache))
            
            # 3. Notify the rest of the app that the theme has changed
            ThemeManager.instance().theme_changed.emit(palette_obj)

        except Exception as e:
            logger.error(STRINGS["LOG_STYLE_FAIL"].format(path=path, error=str(e)))

    def _shutdown_after_backup(self):
        """Finish shutdown after a successful close-event backup."""
        # Mark shutdown as complete and quit the application to avoid re-entering closeEvent.
        self._shutdown_backup_running = False
        QApplication.quit()


    def closeEvent(self, event):

        """Creates an automatic backup on app close + prunes backups.

        This version blocks shutdown until the backup completes.
        """

        # If a backup is already running, keep ignoring the close event.
        if getattr(self, "_shutdown_backup_running", False):
            event.ignore()
            return

        self._shutdown_backup_running = True

        loading = LoadingDialog("Backing up database...", parent=self)
        loading.show()

        # Block the current close request until worker completes.
        event.ignore()

        # Worker thread runs the backup & prune.
        worker = BackupWorker(parent=self)

        def _on_backup_done(success: bool, error_message: str):
            # Unblock next close attempt.
            self._shutdown_backup_running = False

            if success:
                try:
                    loading.close()
                except Exception:
                    pass

                # Close normally now that backup succeeded.
                # Use a zero-delay timer so the dialog close and Qt event loop are clean.
                QTimer.singleShot(0, self._shutdown_after_backup)
                return


            else:
                # Cancel the exit.
                try:
                    loading.hide()
                except Exception:
                    pass

                logger.error("Automatic DB backup failed on close: %s", error_message)
                QMessageBox.critical(
                    self,
                    "Backup Failed",
                    f"Failed to back up the database before exit.\n\nError: {error_message}",
                )

        worker.finished_with_result.connect(_on_backup_done)
        worker.start()


class MainPage(QWidget):
    """Container for the status bar and stacked application pages.
    
    Coordinates the top status bar (with greetings and controls) and
    the main content area containing all application pages.
    """
    
    def __init__(self, parent=None):
        """Initialize the main page container.
        
        Args:
            parent (QWidget, optional): Parent widget. Defaults to None.
        """
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Sets up the vertical layout containing status bar and content area."""
        self.main_page_layout = QVBoxLayout(self)
        self.main_page_layout.setContentsMargins(0, 0, 0, 0)
        self.main_page_layout.setSpacing(0)
        
        self._setup_status_bar()
        self._setup_main_page_content()
        
        self.main_page_layout.addWidget(self.statusbar_widget)
        self.main_page_layout.addWidget(self.main_page_content)
    
    def _setup_status_bar(self):
        """Creates and configures the top status bar with controls and greetings."""
        palette = get_active_palette()
        text_primary = palette.get("text_primary")
        brand_color = palette.get("brand_500")

        self.statusbar_widget = QWidget(self)
        self.statusbar_widget.setObjectName("statusbar_widget")
        self.statusbar_layout = QHBoxLayout(self.statusbar_widget)
        
        # Menu Toggle Button
        self.toggle_menu_btn = QPushButton()
        self.toggle_menu_btn.setObjectName("menu_btn")
        self.toggle_menu_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["MENU"]), text_primary, brand_color))
        self.toggle_menu_btn.setFixedSize(QSize(*STATUS_BAR_CONFIG["MENU_BTN"]))
        self.toggle_menu_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["MENU_ICO"]))
        self.toggle_menu_btn.setCheckable(True)
        self.statusbar_layout.addWidget(self.toggle_menu_btn)
        self.statusbar_layout.addStretch()
        
        # Greeting Labels
        account_name = SettingsManager.get("user_name", DEFAULT_CLINIC_OWNER)
        self.welcome_layout = QVBoxLayout()
        
        self.welcome = QLabel(tr(STRINGS["GREETING_HELLO"]).format(name=account_name))
        self.welcome.setObjectName("welcomeLabel")
        self.welcome.setAlignment(Qt.AlignCenter)
        self.welcome_layout.addWidget(self.welcome)
        
        self.state = QLabel(tr(STRINGS["GREETING_GOOD"]).format(time=tr(get_time_of_day())))
        self.state.setObjectName("stateLabel")
        self.state.setAlignment(Qt.AlignCenter)
        self.welcome_layout.addWidget(self.state)
        
        self.statusbar_layout.addLayout(self.welcome_layout)
        self.statusbar_layout.addStretch()
        
        # Theme Toggle Button
        is_dark = SettingsManager.get("theme", "light").lower() == "dark"
        dark_icon = "light-mode-ico.png" if is_dark else "dark-mode-ico.png"

        self.dark_mode_btn = QPushButton()
        self.dark_mode_btn.setObjectName("darkModeButton")
        self.dark_mode_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, dark_icon), text_primary, brand_color))
        self.dark_mode_btn.setFixedSize(QSize(*STATUS_BAR_CONFIG["THEME_BTN"]))
        self.dark_mode_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["THEME_ICO"]))
        self.dark_mode_btn.setCheckable(True)
        
        # Sync toggle state with saved theme
        if is_dark:
            self.dark_mode_btn.setChecked(True)
        
        self.statusbar_layout.addWidget(self.dark_mode_btn)
        
        # Account Menu Button
        self.account_btn = QToolButton()
        self.account_btn.setObjectName("accountButton")
        self.account_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["PROFILE"]), text_primary, text_primary))
        self.account_btn.setFixedSize(*STATUS_BAR_CONFIG["ACCOUNT_BTN"]) # Removed fixed size
        self.account_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["ACCOUNT_ICO"]))
        self.account_btn.setPopupMode(QToolButton.InstantPopup)
        self.statusbar_layout.addWidget(self.account_btn)
        
        # Account Dropdown Menu
        account_drop_down_menu = QMenu(self)
        account_drop_down_menu.setAttribute(Qt.WA_TranslucentBackground)
        account_drop_down_menu.setWindowFlags(account_drop_down_menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        account_drop_down_menu.addAction(tr(STRINGS["MENU_REORDER"]), self.show_reorder_settings)
        account_drop_down_menu.addAction(tr(STRINGS["MENU_SETTINGS"]), self.show_settings_window)

        self.account_btn.setMenu(account_drop_down_menu)
    
    def retranslate_ui(self):
        """Updates the status bar text and action menus when language changes."""
        account_name = SettingsManager.get("user_name", DEFAULT_CLINIC_OWNER)
        self.welcome.setText(tr(STRINGS["GREETING_HELLO"]).format(name=account_name))
        self.state.setText(tr(STRINGS["GREETING_GOOD"]).format(time=tr(get_time_of_day())))

        # Refresh Icons with current palette
        palette = get_active_palette()
        text_primary = palette.get("text_primary")
        brand_color = palette.get("brand_500")

        self.toggle_menu_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["MENU"]), text_primary, brand_color))

        is_dark = SettingsManager.get("theme", "light").lower() == "dark"
        dark_icon = "light-mode-ico.png" if is_dark else "dark-mode-ico.png"
        self.dark_mode_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, dark_icon), text_primary, brand_color))

        self.account_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["PROFILE"]), text_primary, text_primary))
        
        # Update Account Menu Actions
        menu = self.account_btn.menu()
        if menu:
            actions = menu.actions()
            if len(actions) >= 2:
                actions[0].setText(tr(STRINGS["MENU_REORDER"]))
                actions[1].setText(tr(STRINGS["MENU_SETTINGS"]))


        # Propagate to all pages in the stacked widget
        for i in range(self.main_page_content.count()):
            self.main_page_content.widget(i).retranslate_ui()

    def show_reorder_settings(self):
        """Opens the global reorder levels configuration dialog."""
        dialog = ReorderSettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # Refresh views that might depend on this (like supplies page or dashboard)
            self.supplies_page.refresh_all_tabs()
            self.dashboard_page.refresh_data()

    def show_settings_window(self):
        """Opens the application settings dialog."""
        main_window = self.window()
        settings_window = SettingsDialog(main_window)
        settings_window.settings_changed.connect(main_window.update_app_icon)
        if settings_window.exec() == QDialog.Accepted:
            # Re-apply window mode
            was_maximized = main_window.isMaximized()
            main_window.apply_window_mode()
            main_window._setup_dev_shortcuts()
            main_window.update_app_icon()
            main_window.update_ui_language()
            self.dashboard_page.refresh_data()
            self.supplies_page.rebuild_tabs()
            self.home_page.refresh_home_table("")
    

    
    def _setup_main_page_content(self):
        """Initializes the stacked widget containing the application pages."""
        self.main_page_content = QStackedWidget(self)
        self.main_page_content.setObjectName("main_page_main_content")
        # Importing (creating instances) from the Main Pages classes
        self.dashboard_page = dashboard.DashboardPage(self.main_page_content)
        self.home_page = home.HomePage(self.main_page_content)
        self.clients_page = clients.ClientsPage(self.main_page_content)
        self.supplies_page = supplies.SuppliesPage(self.main_page_content)
        self.receipts_page = receipts.ReceiptsPage(self.main_page_content)
        # Adding The Pages to the Stacked Widget
        self.main_page_content.addWidget(self.dashboard_page)
        self.main_page_content.addWidget(self.home_page)
        self.main_page_content.addWidget(self.clients_page)
        self.main_page_content.addWidget(self.supplies_page)
        self.main_page_content.addWidget(self.receipts_page)
        # Setting Default Page to Dashboard
        self.main_page_content.setCurrentIndex(0) # Default to Dashboard
