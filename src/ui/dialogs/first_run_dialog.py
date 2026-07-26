"""First-run onboarding dialog.

Shown when the application is opened for the first time (i.e., settings.json does
not exist yet). Prompts the user for clinic name and an admin username/password,
then persists those values via SettingsManager and creates the admin user.

The dialog is branded to match the rest of the app (banner + form card) and lets
the user pick the UI language before anything else is set up; switching the
language relabels the whole dialog immediately.
"""

import logging

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.config.constants import DEFAULT_CLINIC_NAME
from src.config.meta import APP_NAME
from src.config.paths import ASSETS_DIR, ICONS_DIR, STYLES_DIR
from src.core.repositories.user_repo import (
    add_user,
    delete_user,
    get_user_by_username,
    update_user_password,
)
from src.ui.themes.color_palettes import get_active_palette, get_styled_qss
from src.utils.i18n import load_translations, tr
from src.utils.settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# Mirrors SettingsPage.LANGUAGE_OPTIONS. Kept local so the first-run screen does
# not import the whole settings page before the application is initialized.
LANGUAGE_OPTIONS = [("English", "en"), ("Arabic", "ar")]

LOGO_SIZE = QSize(56, 56)


class FirstRunDialog(QDialog):
    """Collects clinic name and the first admin user's credentials."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Welcome"))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(520)

        self._setup_ui()
        self._load_defaults()
        self._apply_style()

    # ------------------------------------------------------------------ UI --
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_banner())

        body = QVBoxLayout()
        body.setContentsMargins(28, 22, 28, 20)
        body.setSpacing(16)
        body.addWidget(self._build_form_card())
        body.addStretch(1)
        body.addLayout(self._build_buttons())
        root.addLayout(body)

    def _build_banner(self):
        banner = QFrame()
        banner.setProperty("class", "first-run-banner")
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(16)

        self.logo_label = QLabel()
        self.logo_label.setProperty("class", "first-run-logo")
        self.logo_label.setFixedSize(LOGO_SIZE)
        self.logo_label.setAlignment(Qt.AlignCenter)
        self._set_logo()
        lay.addWidget(self.logo_label, alignment=Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = QLabel(APP_NAME)
        self.title_label.setProperty("class", "first-run-title")
        self.subtitle_label = QLabel(
            tr("Please enter your clinic information to personalize the app.")
        )
        self.subtitle_label.setProperty("class", "first-run-subtitle")
        self.subtitle_label.setWordWrap(True)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.subtitle_label)
        lay.addLayout(text_col, 1)
        return banner

    def _build_form_card(self):
        card = QFrame()
        card.setProperty("class", "form-card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        # Language selector first so the rest of the dialog can follow it.
        self.language_label = QLabel(tr("Language:"))
        self.language_label.setProperty("class", "form-card-title")
        self.language_combo = QComboBox()
        self.language_combo.setView(QListView())
        self.language_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.language_combo.view().window().setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        for name, code in LANGUAGE_OPTIONS:
            self.language_combo.addItem(tr(name), code)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(self.language_label, self.language_combo)

        self.clinic_title = QLabel(tr("Clinic Details"))
        self.clinic_title.setProperty("class", "form-card-title")
        form.addRow(self.clinic_title)

        self.clinic_label = QLabel(tr("Clinic name:"))
        self.clinic_name_edit = QLineEdit()
        self.clinic_name_edit.setPlaceholderText(tr("Enter your clinic's name"))
        self.clinic_name_edit.setMinimumHeight(34)
        form.addRow(self.clinic_label, self.clinic_name_edit)

        self.admin_title = QLabel(tr("Administrator Account"))
        self.admin_title.setProperty("class", "form-card-title")
        form.addRow(self.admin_title)

        self.user_label = QLabel(tr("Admin username:"))
        self.user_name_edit = QLineEdit()
        self.user_name_edit.setPlaceholderText(tr("Choose an admin username"))
        self.user_name_edit.setMinimumHeight(34)
        form.addRow(self.user_label, self.user_name_edit)

        self.password_label = QLabel(tr("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText(tr("Choose a password"))
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(34)
        form.addRow(self.password_label, self.password_edit)

        lay.addLayout(form)
        return card

    def _build_buttons(self):
        row = QHBoxLayout()
        row.addStretch(1)

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setProperty("class", "secondary-action")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)

        self.continue_btn = QPushButton(tr("Continue"))
        self.continue_btn.setProperty("class", "primary-action")
        self.continue_btn.setMinimumHeight(38)
        self.continue_btn.setDefault(True)
        self.continue_btn.clicked.connect(self.accept)

        row.addWidget(self.cancel_btn)
        row.addWidget(self.continue_btn)
        return row

    # -------------------------------------------------------------- styling --
    def _apply_style(self):
        try:
            theme = str(SettingsManager.get("theme", "light")).lower()
            qss = get_styled_qss(STYLES_DIR / "style.qss", theme, get_active_palette())
            if qss:
                self.setStyleSheet(qss)
        except Exception:
            logger.exception("Failed to apply the stylesheet to the first-run dialog")

    def _set_logo(self):
        logo_path = SettingsManager.get("custom_logo", "")
        if not logo_path:
            logo_path = ICONS_DIR / "logo.png"
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(LOGO_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(pixmap)

    # ----------------------------------------------------------- i18n & data --
    def _load_defaults(self):
        # Pre-fill clinic name with the default so user can quickly accept/adjust.
        self.clinic_name_edit.setText(
            SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME)
        )

        lang = SettingsManager.get("language", "en")
        idx = self.language_combo.findData(lang)
        if idx >= 0:
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(idx)
            self.language_combo.blockSignals(False)

    def _on_language_changed(self, index):
        lang = self.language_combo.itemData(index) or "en"
        if load_translations(str(ASSETS_DIR / "translations.json"), lang=lang):
            self._retranslate_ui()

    def _retranslate_ui(self):
        """Relabels every text element after a language switch."""
        self.setWindowTitle(tr("Welcome"))
        self.title_label.setText(APP_NAME)
        self.subtitle_label.setText(
            tr("Please enter your clinic information to personalize the app.")
        )
        self.language_label.setText(tr("Language:"))
        self._retranslate_combo(self.language_combo, LANGUAGE_OPTIONS)
        self.clinic_title.setText(tr("Clinic Details"))
        self.clinic_label.setText(tr("Clinic name:"))
        self.clinic_name_edit.setPlaceholderText(tr("Enter your clinic's name"))
        self.admin_title.setText(tr("Administrator Account"))
        self.user_label.setText(tr("Admin username:"))
        self.user_name_edit.setPlaceholderText(tr("Choose an admin username"))
        self.password_label.setText(tr("Password:"))
        self.password_edit.setPlaceholderText(tr("Choose a password"))
        self.cancel_btn.setText(tr("Cancel"))
        self.continue_btn.setText(tr("Continue"))

    @staticmethod
    def _retranslate_combo(combo, options):
        for i, (name, _code) in enumerate(options):
            if i < combo.count():
                combo.setItemText(i, tr(name))

    # ------------------------------------------------------------- actions --
    def accept(self):
        clinic_name = self.clinic_name_edit.text().strip()
        user_name = self.user_name_edit.text().strip()
        password = self.password_edit.text()

        if not clinic_name:
            QMessageBox.warning(self, tr("Validation Error"), tr("Clinic name cannot be empty."))
            return
        if not user_name:
            QMessageBox.warning(self, tr("Validation Error"), tr("Admin username cannot be empty."))
            return
        if not password:
            QMessageBox.warning(self, tr("Validation Error"), tr("Password cannot be empty."))
            return

        # The stock seeded 'admin' account ships with a known placeholder password
        # (admin123). On first run we harden it: if the clinic reuses the "admin"
        # username we reset its password to the chosen one; otherwise we create the
        # real admin and remove the stock account so the default cannot be used.
        stock_admin = get_user_by_username("admin")

        if user_name == "admin" and stock_admin is not None:
            update_user_password(stock_admin["user_id"], password)
            self._finish(clinic_name)
            return

        user_id = add_user(user_name, password, role_name="admin")
        if user_id is None:
            QMessageBox.warning(
                self,
                tr("Error"),
                tr("Failed to create the admin user. The username may already be in use."),
            )
            return

        # Remove the default seeded admin so the known admin123 credential is gone.
        if stock_admin is not None:
            delete_user(stock_admin["user_id"])

        self._finish(clinic_name)

    def _finish(self, clinic_name):
        """Persist the chosen setup once everything has succeeded.

        Deferred until here so a cancelled/failed first run never creates
        settings.json (which would skip onboarding on the next launch).
        """
        SettingsManager.set("language", self.language_combo.currentData() or "en")
        SettingsManager.set("clinic_name", clinic_name)
        super().accept()
