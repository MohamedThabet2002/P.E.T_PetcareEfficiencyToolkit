"""
Primary Application Orchestrator for PET.

Manages the main window lifecycle, including sidebar navigation, theme switching,
page transitions, and status bar controls. Coordinates between all UI components
and handles window geometry, styling, and internationalization.
"""

import os
import logging
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QHBoxLayout, QVBoxLayout, QLabel,
    QMessageBox, QApplication, QDialog, QShortcut, QWidget
)
from PyQt5.QtCore import Qt, QSettings, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QKeySequence

from src.utils.settings_manager import SettingsManager
from src.ui.pages.main_page import MainPage, ICONS
from src.ui.themes.color_palettes import get_styled_qss, ThemeManager, get_active_palette
from src.ui.side_menu import SideMenu
from src.modules.signal_bus import SignalBus
from src.core.backup_manager import create_backup, prune_backups
from src.core.database import get_user_db_path
from src.config.paths import ICONS_DIR, STYLES_DIR, ASSETS_DIR, BACKUPS_DIR, SETTINGS_ORG, SETTINGS_APP
from src.config.constants import (
    DEFAULT_CLINIC_NAME,
    BACKUP_KEEP_24HOURS, BACKUP_KEEP_DAILY_DAYS, BACKUP_KEEP_MANUAL_FOREVER,
    WINDOW_CONFIG
)

logger = logging.getLogger(__name__)

#==================================== CONSTANTS =====================================================#

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
        self.spinner.setText("â³")
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
        # Must match SettingsPage's QSettings namespace for CustomPalette values.
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
        min_size = WINDOW_CONFIG.get("MIN_SIZE") or (800, 600)
        self.setMinimumSize(*min_size)
        default_size = WINDOW_CONFIG.get("DEFAULT_SIZE") or (1280, 720)
        # Never open wider/taller than the screen the app is launched on
        # (Qt applies the minimum size itself if the screen is that small).
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry().size()
            default_size = (min(default_size[0], available.width()),
                            min(default_size[1], available.height()))
        self.resize(*default_size)
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
        # The sub-pages (clients, visits, supplies, receipts) are now inside database_page
        db_page = self.main_page.database_page
        dash_page = self.main_page.dashboard_page
        
        refresh_triggers = [
            db_page.clients_page,
            db_page.visits_page, 
            db_page.receipts_page,
            db_page.supplies_page,
        ]
        
        for page in refresh_triggers:
            page.data_changed.connect(dash_page.refresh_data)
            page.data_changed.connect(self.main_page.reports_page.refresh_data)

        # Low-stock KPI also depends on analytics cache; ensure it refreshes
        # whenever supply quantities change (including inline edits/restocks).
        try:
            db_page.supplies_page.data_changed.connect(dash_page.refresh_kpis_insights_appointments)
        except Exception:
            # Backward compatible: if method doesn't exist, ignore.
            pass
            
        # Specialized refreshes (within database sub-pages)
        db_page.clients_page.data_changed.connect(db_page.visits_page.refresh_visits_table)
        db_page.supplies_page.data_changed.connect(db_page.visits_page.refresh_visits_table)
        
        db_page.visits_page.data_changed.connect(db_page.clients_page.refresh_clients)
        db_page.clients_page.data_changed.connect(
            lambda: db_page.supplies_page.refresh_all_tabs()
        )
        db_page.visits_page.data_changed.connect(
            lambda: db_page.supplies_page.refresh_all_tabs()
        )
        
        for p in [db_page.clients_page, db_page.visits_page, db_page.supplies_page]:
            p.data_changed.connect(lambda: db_page.receipts_page.refresh_receipts_table())

        # Keep the standalone Visits page (doctor top-level) in sync with Database visits changes
        visits_standalone = self.main_page.visits_page
        db_page.visits_page.data_changed.connect(visits_standalone.refresh_visits_table)
        db_page.clients_page.data_changed.connect(visits_standalone.refresh_visits_table)
        visits_standalone.data_changed.connect(dash_page.refresh_data)

        # Central signal bus: coarse domain events emitted alongside the legacy
        # per-page data_changed wiring. New cross-page code should subscribe here.
        self.signal_bus = SignalBus.instance()
        db_page.clients_page.data_changed.connect(self._emit_clients_changed)
        db_page.visits_page.data_changed.connect(self._emit_visits_changed)
        db_page.supplies_page.data_changed.connect(self._emit_supplies_changed)
        db_page.receipts_page.data_changed.connect(self._emit_receipts_changed)
        visits_standalone.data_changed.connect(self._emit_visits_changed)
    
    def _emit_clients_changed(self):
        self.signal_bus.emit_event("clients_changed")

    def _emit_visits_changed(self):
        self.signal_bus.emit_event("visits_changed")

    def _emit_supplies_changed(self):
        self.signal_bus.emit_event("supplies_changed")

    def _emit_receipts_changed(self):
        self.signal_bus.emit_event("receipts_changed")

    def _setup_menu_connections(self):
        """Connects sidebar buttons to page switching and synchronizes menu states.
        
        Uses MENU_ITEMS_CONFIG metadata to dynamically map page items to
        stacked widget indices and handle exit/navigation separately.
        """
        # Map navigation buttons to page indices dynamically from the config
        page_index = 0
        for item in self.sidemenus.menu_items_config:
            if item.is_page:
                small = getattr(self.sidemenus, f"{item.name}_btn_small")
                big = getattr(self.sidemenus, f"{item.name}_btn_big")
                
                for btn in [small, big]:
                    btn.clicked.connect(lambda checked, idx=page_index: self.main_page.main_page_content.setCurrentIndex(idx))
                
                small.toggled.connect(big.setChecked)
                big.toggled.connect(small.setChecked)
                page_index += 1
            
            elif item.is_exit:
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

            # Stylesheet reload is now handled by the caller (SettingsPage) to avoid double-rendering

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
            logger.info("UI language updated to '{lang}'".format(lang=lang))
        else:
            logger.warning("Failed to reload translations")

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
        logger.info("Stylesheet reloaded via shortcut at {time}".format(time=datetime.now().strftime('%H:%M:%S')))
    
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
            logger.error("Failed to load stylesheet from {path}: {error}".format(path=path, error=str(e)))

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


