"""
Main Pipeline for the PET Application.
Handles the core application initialization and main window execution.
"""

import sys
import logging
import os
import traceback
import json
from logging.handlers import RotatingFileHandler

from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt5.QtCore import Qt

from src.config.meta import APP_NAME, VERSION, ORG_NAME
from src.config.paths import LOG_FILE, SETTINGS_FILE, ASSETS_DIR
from src.ui.main_window import MainWindow
from src.ui.dialogs.first_run_dialog import FirstRunDialog
from src.ui.dialogs.login_dialog import LoginDialog
from src.core.repositories import user_repo
from src.utils.settings_manager import SettingsManager
from src.utils.i18n import load_translations
from src.utils.font_loader import load_bundled_fonts

# Configure logging
logger = logging.getLogger()

def setup_logging():
    """Initializes logging based on user settings."""
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Always add stream handler for console output 
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Check if file logging is enabled in settings
    is_dev = False
    enable_logging = True
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings_data = json.load(f)
                is_dev = settings_data.get("dev_mode", False)
                enable_logging = settings_data.get("enable_logging", True)
        except Exception:
            pass

    if enable_logging:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
            file_handler.setFormatter(formatter)
            if not is_dev:
                file_handler.setLevel(logging.WARNING)
            logger.addHandler(file_handler)
        except Exception:
            pass

def exception_hook(exctype, value, tb):
    """Global hook to catch unhandled exceptions and log them before crashing."""
    traceback_details = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical(f"Unhandled Exception: {traceback_details}")
    
    # Attempt to show a dialog to the user
    if QApplication.instance():
        error_msg = (
            "A critical error occurred. The application will close.\n\n"
            f"Error: {str(value)}\n\n"
            "Please send the 'app.log' file to support."
        )
        QMessageBox.critical(None, "Fatal Error", error_msg)

    # Hard exit to ensure the process dies even if threads or event loops are hanging.
    os._exit(1)
    sys.exit(1)

sys.excepthook = exception_hook

def run_app(app: QApplication):
    """Logic to initialize the main widget, called by the root entry point."""

    # First-run onboarding: show clinic + user prompt when settings.json is missing.
    if not SETTINGS_FILE.exists():
        dialog = FirstRunDialog()
        dialog.setParent(None)
        dialog.setModal(True)

        # QDialog.exec() returns QDialog.Accepted / QDialog.Rejected.
        # Using the class constant is safer than instance attributes.
        result = dialog.exec()
        if result != QDialog.Accepted:
            return None

    # Initialize Main Window
    window = MainWindow()

    # Login gate: authenticate the user before exposing the app.
    # If Remember Me is set (auto_login_user) and that user still exists,
    # skip the dialog and auto-login. Otherwise, prompt for credentials.
    logged_in_user = None
    auto_user = SettingsManager.get("auto_login_user", "")
    if auto_user:
        try:
            logged_in_user = user_repo.get_user_by_username(auto_user)
        except Exception:
            logger.exception("Auto-login lookup failed for '%s'", auto_user)
            logged_in_user = None

    if logged_in_user is None:
        login_dialog = LoginDialog(window)
        login_dialog.login_successful.connect(lambda user: window.main_page._on_login_successful(user))
        if login_dialog.exec() != QDialog.Accepted:
            # User cancelled login — do not open the app window.
            return None
    else:
        # Apply the same post-login UI updates for auto-login.
        window.main_page._on_login_successful(logged_in_user)

    window.show()
    window.apply_window_mode()

    # Return reference to prevent garbage collection
    return window

def main():
    """Main entry point for the application."""
    
    setup_logging()
    
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    _window = None
    try:
        # Load bundled fonts and translations
        load_bundled_fonts(ASSETS_DIR / "fonts")
        
        current_lang = "en"
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)
                    current_lang = settings_data.get("language", "en")
            except Exception as e:
                logger.error(f"Could not read settings.json: {e}")

        trans_path = ASSETS_DIR / "translations.json"
        if not load_translations(str(trans_path), lang=current_lang):
            logger.warning("Falling back to default language strings.")
            
        app.setApplicationName(APP_NAME)
        app.setOrganizationName(ORG_NAME)

        logger.info(f"Starting {APP_NAME} v{VERSION}...")
        
        _window = run_app(app)
        if _window is None:
            # First-run was cancelled, or login was cancelled — exit cleanly.
            logger.info("Startup aborted by user (first-run or login cancelled).")
            sys.exit(0)

        logger.info("Application initialized successfully")
        
        sys.exit(app.exec())
    
    except Exception as e:
        # Log the full stack trace for debugging
        error_details = traceback.format_exc()
        logger.critical(f"Application startup failed:\n{error_details}")

        # Hide the main window if it was partially initialized/shown
        if _window:
            _window.hide()
        
        error_msg = (
            f"The application encountered a critical error and must close.\n\n"
            f"Error: {str(e)}\n\n"
            f"Please check the application logs for details."
        )

        if QApplication.instance():
            QMessageBox.critical(None, "Application Error", error_msg)

        # Use os._exit to force closure if sys.exit hangs
        os._exit(1)
        sys.exit(1)

if __name__ == "__main__":
    main()