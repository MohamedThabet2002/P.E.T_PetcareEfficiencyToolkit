"""
Login Dialog for the PET Application.
Provides user authentication via username/password using user_repo.py,
with optional "Remember Me" persistence for auto-login on next launch.
"""

import logging

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QDialogButtonBox, QWidget, QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap

from src.core.repositories import user_repo
from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.config.paths import ICONS_DIR

logger = logging.getLogger(__name__)

# Dialog dimensions
LOGIN_DIALOG_WIDTH = 420
LOGIN_DIALOG_HEIGHT = 460
#: The form is shorter than this on small font scales, so the dialog keeps a
#: minimum height instead of a fixed one and stays comfortably proportioned.
LOGIN_DIALOG_MIN_HEIGHT = 400
LOGO_SIZE = QSize(64, 64)


class LoginDialog(QDialog):
    """Login dialog for user authentication.

    Provides username/password fields and authenticates against the users table.
    On success, emits a signal with the authenticated user's info.
    """

    login_successful = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Login"))
        self.setMinimumWidth(LOGIN_DIALOG_WIDTH)
        self.setMinimumHeight(LOGIN_DIALOG_MIN_HEIGHT)
        self.resize(LOGIN_DIALOG_WIDTH, LOGIN_DIALOG_HEIGHT)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._setup_ui()

    def _setup_ui(self):
        """Sets up the login form UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 20, 30, 20)
        main_layout.setSpacing(12)

        # Logo
        logo_label = QLabel()
        logo_path = SettingsManager.get("custom_logo", "")
        if not logo_path:
            logo_path = ICONS_DIR / "logo.png"
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(LOGO_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        logo_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(logo_label)

        # Title
        title_label = QLabel(tr("Welcome Back"))
        title_label.setProperty("class", "dialog-title")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        main_layout.addSpacing(10)

        # Username field
        username_label = QLabel(tr("Username:"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText(tr("Enter your username"))
        self.username_input.setMinimumHeight(32)
        main_layout.addWidget(username_label)
        main_layout.addWidget(self.username_input)

        # Password field
        password_label = QLabel(tr("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText(tr("Enter your password"))
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(32)
        main_layout.addWidget(password_label)
        main_layout.addWidget(self.password_input)

        # Remember Me checkbox
        self.remember_me_checkbox = QCheckBox(tr("Remember Me"))
        self.remember_me_checkbox.setToolTip(tr("Stay logged in on this device until you log out."))
        # Pre-check if an auto-login user is already persisted
        if SettingsManager.get("auto_login_user", ""):
            self.remember_me_checkbox.setChecked(True)
        main_layout.addWidget(self.remember_me_checkbox)

        main_layout.addSpacing(10)

        # Buttons
        button_layout = QHBoxLayout()
        self.login_btn = QPushButton(tr("Login"))
        self.login_btn.setProperty("class", "primary-action")
        self.login_btn.setAutoDefault(False)
        self.login_btn.setMinimumHeight(36)
        self.login_btn.clicked.connect(self._handle_login)

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setProperty("class", "secondary-action")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.login_btn)
        button_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(button_layout)

        # Connect Enter key in password field
        self.password_input.returnPressed.connect(self._handle_login)
        self.username_input.returnPressed.connect(lambda: self.password_input.setFocus())

    def _handle_login(self):
        """Authenticates the user and emits signal on success."""
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            QMessageBox.warning(self, tr("Login Error"), tr("Please enter both username and password."))
            return

        user = user_repo.authenticate_user(username, password)
        if user:
            logger.info(f"User '{username}' logged in successfully")

            # Remember Me: persist or clear the auto-login user
            if self.remember_me_checkbox.isChecked():
                SettingsManager.set("auto_login_user", username)
                logger.info(f"Remember Me enabled for user '{username}'")
            else:
                # Clear any previously saved auto-login user
                SettingsManager.set("auto_login_user", "")
                logger.info(f"Remember Me disabled for user '{username}'")

            self.login_successful.emit(user)
            self.accept()
        else:
            logger.warning("Failed login attempt for user '%s'", username)
            QMessageBox.warning(self, tr("Login Error"), tr("Invalid username or password."))
            self.password_input.clear()
            self.password_input.setFocus()
