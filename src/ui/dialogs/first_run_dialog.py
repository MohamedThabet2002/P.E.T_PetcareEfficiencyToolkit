"""First-run onboarding dialog.

Shown when the application is opened for the first time (i.e., settings.json does
not exist yet). Prompts the user for clinic name and user name, then persists
those values via SettingsManager.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QDialogButtonBox,
    QMessageBox,
    QLabel,
)

from src.utils.settings_manager import SettingsManager
from src.config import DEFAULT_CLINIC_NAME, DEFAULT_CLINIC_OWNER


class FirstRunDialog(QDialog):
    """Collects clinic name and user name on first launch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setModal(True)

        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Please enter your clinic information to personalize the app."
        )
        info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(info)

        form = QFormLayout()

        self.clinic_name_edit = QLineEdit()
        self.clinic_name_edit.setPlaceholderText("Enter your clinic's name")

        self.user_name_edit = QLineEdit()
        self.user_name_edit.setPlaceholderText("Enter your name or title")

        form.addRow("Clinic name:", self.clinic_name_edit)
        form.addRow("Your name:", self.user_name_edit)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Continue")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _load_defaults(self):
        # Pre-fill with defaults so user can quickly accept/adjust.
        self.clinic_name_edit.setText(SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME))
        self.user_name_edit.setText(SettingsManager.get("user_name", DEFAULT_CLINIC_OWNER))

    def accept(self):
        clinic_name = self.clinic_name_edit.text().strip()
        user_name = self.user_name_edit.text().strip()

        if not clinic_name:
            QMessageBox.warning(self, "Validation Error", "Clinic name cannot be empty.")
            return
        if not user_name:
            QMessageBox.warning(self, "Validation Error", "User name cannot be empty.")
            return

        SettingsManager.set("clinic_name", clinic_name)
        SettingsManager.set("user_name", user_name)

        super().accept()

