"""
Internal application bootstrap.
This file is now a wrapper to prevent redundancy with the root main.py.
"""

from PyQt5.QtWidgets import QApplication, QDialog

from src.ui.main_window import MainWindow
from src.ui.dialogs.first_run_dialog import FirstRunDialog
from src.config import SETTINGS_FILE


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

    window.show()
    window.apply_window_mode()

    # Return reference to prevent garbage collection
    return window

