"""
Main application page container (status bar + stacked app pages).

Splits the old MainPage out of ``main_window.py``: owns the top status bar
(greetings, theme toggle, account menu) and the QStackedWidget of application
pages, plus login/logout + role-based nav gating and audit logging of auth
events.
"""

import os
import logging
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QStackedWidget, QToolButton, QMenu,
    QApplication, QDialog,
)
from PyQt5.QtCore import Qt, QSize

from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.ui.pages import admin_page, dashboard_page, settings_page
from src.ui.pages.reports_pages.reports_page import ReportsPage
from src.ui.pages.database_pages import database_page, my_visits_page
from src.ui.themes.color_palettes import get_active_palette
from src.ui.side_menu import recolor_icon
from src.ui.dialogs.login_dialog import LoginDialog
import src.core.repositories.log_repo as log_repo
from src.core.permissions import can
from src.config.constants import DEFAULT_CLINIC_OWNER
from src.config.paths import ICONS_DIR

logger = logging.getLogger(__name__)

STATUS_BAR_CONFIG = {
    "MENU_BTN": (40, 40),
    "MENU_ICO": (32, 32),
    "THEME_BTN": (32, 32),
    "THEME_ICO": (24, 24),
    "ACCOUNT_BTN": (44, 44),
    "ACCOUNT_ICO": (36, 36),
}

ICONS = {
    "WINDOW": "logo.png",
    "MENU": "menu.png",
    "DARK_MODE": "dark-mode.png",
    "LIGHT_MODE": "light-mode.png",
    "PROFILE": "profile.png",
}

# Greeting Timing
GREETING_AFTERNOON_HOUR = 12
GREETING_EVENING_HOUR = 18


def get_time_of_day():
    """Returns the current period of the day for greeting message."""
    hour = datetime.now().hour
    if hour < GREETING_AFTERNOON_HOUR:
        return "morning"
    elif hour < GREETING_EVENING_HOUR:
        return "afternoon"
    return "evening"


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
        self.statusbar_widget.setFixedHeight(60)
        self.statusbar_layout = QHBoxLayout(self.statusbar_widget)

        # Menu Toggle Button
        self.toggle_menu_btn = QPushButton()
        self.toggle_menu_btn.setObjectName("menu_btn")
        self.toggle_menu_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["MENU"]), text_primary, brand_color))
        self.toggle_menu_btn.setMinimumSize(QSize(*STATUS_BAR_CONFIG["MENU_BTN"]))
        self.toggle_menu_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["MENU_ICO"]))
        self.toggle_menu_btn.setCheckable(True)
        self.statusbar_layout.addWidget(self.toggle_menu_btn)
        self.statusbar_layout.addStretch()

        # Greeting Labels
        account_name = DEFAULT_CLINIC_OWNER
        self.welcome_layout = QVBoxLayout()

        self.welcome = QLabel(tr("Hello, {name}").format(name=account_name))
        self.welcome.setObjectName("welcomeLabel")
        self.welcome.setAlignment(Qt.AlignCenter)
        self.welcome_layout.addWidget(self.welcome)

        self.state = QLabel(tr("Good {time}!").format(time=tr(get_time_of_day())))
        self.state.setObjectName("stateLabel")
        self.state.setAlignment(Qt.AlignCenter)
        self.welcome_layout.addWidget(self.state)

        self.statusbar_layout.addLayout(self.welcome_layout)
        self.statusbar_layout.addStretch()

        # Theme Toggle Button
        is_dark = SettingsManager.get("theme", "light").lower() == "dark"
        dark_icon = ICONS["LIGHT_MODE"] if is_dark else ICONS["DARK_MODE"]
        self.dark_mode_btn = QPushButton()
        self.dark_mode_btn.setObjectName("darkModeButton")
        self.dark_mode_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, dark_icon), text_primary, brand_color))
        self.dark_mode_btn.setFixedSize(*STATUS_BAR_CONFIG["THEME_BTN"])
        self.dark_mode_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["THEME_ICO"]))
        self.dark_mode_btn.setToolTip(tr("Dark Mode"))
        self.dark_mode_btn.setCheckable(True)

        # Sync toggle state with saved theme
        if is_dark:
            self.dark_mode_btn.setChecked(True)

        self.statusbar_layout.addWidget(self.dark_mode_btn)

        # Account Menu Button
        self.account_btn = QToolButton()
        self.account_btn.setObjectName("accountButton")
        self.account_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["PROFILE"]), text_primary, text_primary))
        self.account_btn.setFixedSize(*STATUS_BAR_CONFIG["ACCOUNT_BTN"])
        self.account_btn.setIconSize(QSize(*STATUS_BAR_CONFIG["ACCOUNT_ICO"]))
        self.account_btn.setPopupMode(QToolButton.InstantPopup)
        self.account_btn.setToolTip(tr("Account"))
        self.statusbar_layout.addWidget(self.account_btn)

        # Account Dropdown Menu
        account_drop_down_menu = QMenu(self)
        account_drop_down_menu.setAttribute(Qt.WA_TranslucentBackground)
        account_drop_down_menu.setWindowFlags(account_drop_down_menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)

        # Login/Logout action (single toggle handled by _handle_auth_action)
        self.login_action = account_drop_down_menu.addAction(tr("Login"))
        self.login_action.triggered.connect(self._handle_auth_action)
        account_drop_down_menu.addSeparator()

        self.account_btn.setMenu(account_drop_down_menu)

        # Track login state
        self._current_user = None

        # Initialize account menu state (Login visible, admin actions hidden)
        self._update_account_menu()

    def retranslate_ui(self):
        """Updates the status bar text and action menus when language changes."""
        account_name = DEFAULT_CLINIC_OWNER
        self.welcome.setText(tr("Hello, {name}").format(name=account_name))
        self.state.setText(tr("Good {time}!").format(time=tr(get_time_of_day())))

        # Refresh Icons with current palette
        palette = get_active_palette()
        text_primary = palette.get("text_primary")
        brand_color = palette.get("brand_500")

        self.toggle_menu_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["MENU"]), text_primary, brand_color))

        is_dark = SettingsManager.get("theme", "light").lower() == "dark"
        dark_icon = ICONS["LIGHT_MODE"] if is_dark else ICONS["DARK_MODE"]
        self.dark_mode_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, dark_icon), text_primary, brand_color))

        self.account_btn.setIcon(recolor_icon(os.path.join(ICONS_DIR, ICONS["PROFILE"]), text_primary, text_primary))

        # Update Account Menu Actions (references preserved for role gating)
        if hasattr(self, "login_action"):
            self.login_action.setText(tr("Logout") if self._current_user else tr("Login"))

        # Propagate to all pages in the stacked widget
        for i in range(self.main_page_content.count()):
            self.main_page_content.widget(i).retranslate_ui()

    def _handle_auth_action(self):
        """Single toggle for login/logout from the account menu."""
        if self._current_user:
            self.show_logout_dialog()
        else:
            self.show_login_dialog()

    def show_login_dialog(self):
        """Opens the login dialog for user authentication."""
        dialog = LoginDialog(self)
        dialog.login_successful.connect(self._on_login_successful)
        dialog.exec()

    def _on_login_successful(self, user):
        """Handles successful login by updating the UI and auditing the event."""
        self._current_user = user
        self.welcome.setText(tr("Hello, {name}").format(name=user.get("username", "")))
        if hasattr(self, "settings_page") and hasattr(self.settings_page, "set_current_user"):
            self.settings_page.set_current_user(user)
        self._update_account_menu()
        self._apply_role_based_access()
        self._audit_log("LOGIN", "User '{}' logged in".format(user.get("username", "")))
        logger.info("User '%s' logged in", user.get("username"))

    def show_logout_dialog(self):
        """Logs out the current user, then immediately forces the login screen.

        The main window is hidden while the login dialog is shown.
        If the user cancels or closes the dialog, the application quits.
        """
        if self._current_user:
            username = self._current_user.get("username", "")
            self._audit_log("LOGOUT", "User '{}' logged out".format(username))
            logger.info("User '%s' logged out", username)

        # Reset user state
        self._current_user = None
        account_name = DEFAULT_CLINIC_OWNER
        self.welcome.setText(tr("Hello, {name}").format(name=account_name))
        if hasattr(self, "settings_page") and hasattr(self.settings_page, "set_current_user"):
            self.settings_page.set_current_user(None)
        self._update_account_menu()
        self._apply_role_based_access()
        self.main_page_content.setCurrentIndex(0)

        # Hide the window and force re-login; quit if the user cancels
        main_window = self.window()
        if main_window:
            main_window.hide()

        login_dialog = LoginDialog(main_window)
        login_dialog.login_successful.connect(self._on_login_successful)
        if login_dialog.exec() != QDialog.Accepted:
            QApplication.quit()
            return

        if main_window:
            main_window.show()
            main_window.apply_window_mode()

    def _update_account_menu(self):
        """Updates the account menu based on auth state and current user role."""
        logged_in = self._current_user is not None
        if hasattr(self, "login_action"):
            self.login_action.setText(tr("Logout") if logged_in else tr("Login"))

    def _apply_role_based_access(self):
        """Hides nav items the current user cannot access and bounces them to Dashboard.

        Page indices are computed from MENU_ITEMS_CONFIG order to stay in sync
        with _setup_menu_connections and _setup_main_page_content.
        """
        user = self._current_user
        show_reports  = can(user, "view_reports")
        show_visits   = can(user, "view_visits")     # doctor only
        show_admin    = can(user, "manage_users") or can(user, "reset_passwords")  # admin tools
        show_settings = can(user, "view_settings")   # admin, doctor, staff

        # --- Compute page indices from the menu config (single source of truth) ---
        page_indices: dict = {}
        idx = 0
        for item in self.window().sidemenus.menu_items_config:
            if item.is_page:
                page_indices[item.name] = idx
                idx += 1

        reports_idx  = page_indices.get("reports",  2)
        visits_idx   = page_indices.get("visits",   3)
        admin_idx    = page_indices.get("admin",    4)
        settings_idx = page_indices.get("settings", 5)

        # --- Update sidebar button visibility ---
        main_window = self.window()
        if hasattr(main_window, "sidemenus"):
            sidemenus = main_window.sidemenus
            for suffix in ("small", "big"):
                for nav_name, visible in (
                    ("reports",  show_reports),
                    ("settings", show_settings),
                    ("visits",   show_visits),
                    ("admin",    show_admin),
                ):
                    btn = getattr(sidemenus, f"{nav_name}_btn_{suffix}", None)
                    if btn is not None:
                        btn.setVisible(visible)

        # --- Bounce user off pages they can no longer access ---
        current = self.main_page_content.currentIndex()
        for allowed, page_idx in (
            (show_reports,  reports_idx),
            (show_settings, settings_idx),
            (show_visits,   visits_idx),
            (show_admin,    admin_idx),
        ):
            if not allowed and current == page_idx:
                self.main_page_content.setCurrentIndex(0)
                break

        # --- Propagate logged-in user to all pages ---
        for attr in ("dashboard_page", "reports_page", "database_page", "settings_page",
                     "visits_page", "admin_page"):
            page = getattr(self, attr, None)
            if page is not None and hasattr(page, "set_current_user"):
                page.set_current_user(user)

    def _get_log_type_id(self, action_name):
        """Returns the log_type_id for a seeded action (e.g. LOGIN/LOGOUT)."""
        try:
            for row in log_repo.get_log_types():
                if str(row.get("log_action", "")).strip().upper() == action_name.upper():
                    return row.get("log_type_id")
        except Exception:
            logger.exception("Failed to resolve log type id for '%s'", action_name)
        return None

    def _audit_log(self, action_name, details=""):
        """Writes an audit entry if a user is logged in."""
        if not self._current_user:
            return
        try:
            log_type_id = self._get_log_type_id(action_name)
            if log_type_id is not None:
                log_repo.add_log(
                    user_id=self._current_user.get("user_id"),
                    log_type_id=log_type_id,
                    entity_type="user",
                    entity_id=self._current_user.get("user_id"),
                    details=details,
                )
        except Exception:
            logger.exception("Failed to write %s audit log", action_name)

    def _setup_main_page_content(self):
        """Initializes the stacked widget containing the application pages."""
        self.main_page_content = QStackedWidget(self)
        self.main_page_content.setObjectName("main_page_main_content")
        # Importing (creating instances) from the Main Pages classes
        self.dashboard_page = dashboard_page.DashboardPage(self.main_page_content)
        self.database_page = database_page.DatabasePage(self.main_page_content)
        self.reports_page = ReportsPage(self.main_page_content)
        # Standalone Visits page — reuses MyVisitsPage (doctor-scoped view)
        self.visits_page = my_visits_page.MyVisitsPage(self.main_page_content)
        self.admin_page = admin_page.AdminPage(self.main_page_content)
        self.settings_page = settings_page.SettingsPage(self.main_page_content)

        # Adding The Pages to the Stacked Widget
        # Order must match MENU_ITEMS_CONFIG (dashboard, database, reports,
        # visits, admin, settings) — see side_menu.py.
        self.main_page_content.addWidget(self.dashboard_page)
        self.main_page_content.addWidget(self.database_page)
        self.main_page_content.addWidget(self.reports_page)
        self.main_page_content.addWidget(self.visits_page)
        self.main_page_content.addWidget(self.admin_page)
        self.main_page_content.addWidget(self.settings_page)
        # Setting Default Page to Dashboard
        self.main_page_content.setCurrentIndex(0) # Default to Dashboard