"""
Admin-only Application Page for the PET Application.

Top-level page (side-menu item ``admin``) that hosts the administrative tools
which used to live inside the Settings page, one tool per tab:

* **User Management** tab — the user management tool (accounts, roles, permissions).
* **Restore Records** tab — the undo-journal restore tool.

Both tools are *embedded* panels (``src/ui/pages/admin_panels.py``), not modal
dialogs — opening a tab shows the tool inline. A page-level **Save** / **Cancel**
row sits at the bottom like the Settings page; because every panel action writes
through its repo immediately, Save re-reads all tabs from the database and
confirms, while Cancel drops the row selection and re-reads them silently.

The nav item itself is gated on ``manage_users``; each tab re-checks its own
permission so a custom role template stays honest (a tab whose permission is
denied is hidden entirely). Supplier CRUD lives in its own dialog, opened from
the Supplies page (see ``src/ui/dialogs/suppliers_dialog.py``).
"""

from PyQt5.QtWidgets import (
    QHBoxLayout, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from src.core.permissions import can
from src.ui.pages.admin_panels import RestoreDeletedPanel, UserManagementPanel
from src.utils.i18n import tr


class AdminPage(QWidget):
    """Admin-only page hosting the user management and restore tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_user = {}
        self._setup_ui()

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._refresh_current_tab)
        main_layout.addWidget(self.tabs, 1)

        self._init_users_tab()
        self._init_restore_tab()

        # Page-level Save / Cancel (same shape as the Settings page).
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

        self.set_current_user(self._current_user)

    def _init_users_tab(self):
        """User Management tab — user accounts / roles / permissions (``manage_users``)."""
        self.users_panel = UserManagementPanel()
        self.users_tab = self.users_panel
        self.tabs.addTab(self.users_panel, tr("User Management"))

    def _init_restore_tab(self):
        """Restore Records tab — undo-journal restore tool (``edit_records``)."""
        self.restore_panel = RestoreDeletedPanel(current_user=self._current_user)
        self.restore_panel.record_restored.connect(self._refresh_pages_after_restore)
        self.restore_tab = self.restore_panel
        self.tabs.addTab(self.restore_panel, tr("Restore Records"))

    def _panels(self):
        """Every hosted tool panel, in tab order."""
        return [self.users_panel, self.restore_panel]

    def showEvent(self, event):
        """Loads the visible tab whenever the page is shown."""
        super().showEvent(event)
        self._refresh_current_tab()

    def _refresh_current_tab(self, *_args):
        """Reloads the panel of the active tab (index arg is optional)."""
        panel = self.tabs.currentWidget()
        if hasattr(panel, "refresh_data"):
            panel.refresh_data()

    def refresh_data(self):
        """Reloads every tool panel from the database."""
        for panel in self._panels():
            panel.refresh_data()

    # -------------------------------------------------------------- Gating --

    def set_current_user(self, user):
        """Stores the logged-in user and re-applies tab visibility."""
        self._current_user = user if user else {}
        for panel in self._panels():
            panel.set_current_user(self._current_user)
        self.refresh_section_visibility()

    def refresh_section_visibility(self):
        """Shows/hides each tab based on the user's permissions.

        Only the *tab* is toggled — never the panel itself. ``QTabWidget`` owns
        the visibility of its page widgets (only the current one is shown), so
        calling ``panel.setVisible(True)`` would un-hide the inactive tab and
        stack it on top of the current one until the user switches tabs.

        The User Management tab is reachable by anyone who can manage users
        *or* reset passwords (the latter is a meaningful sub-grant); each
        action inside the panel re-checks its own permission. The Restore
        Records tab follows ``edit_records``.
        """
        show_users = can(self._current_user, "manage_users") or can(
            self._current_user, "reset_passwords"
        )
        self.tabs.setTabVisible(self.tabs.indexOf(self.users_tab), show_users)
        self.tabs.setTabVisible(
            self.tabs.indexOf(self.restore_tab),
            can(self._current_user, "edit_records"),
        )

    # ----------------------------------------------------- Page-level Save --

    def save_settings(self):
        """Global Save — re-reads every tab and confirms.

        Panel actions already persisted through their repos, so the page only
        has to make sure it displays what is stored. Permission edits take
        effect on the surrounding UI at the target user's next login.
        """
        self.refresh_data()
        QMessageBox.information(self, tr("Success"), tr("Admin changes saved."))

    def cancel_settings(self):
        """Global Cancel — drops the row selection and re-reads every tab."""
        for panel in self._panels():
            panel.clear_selection()
        self.refresh_data()

    def _refresh_pages_after_restore(self, table_name: str):
        """Refresh the page(s) affected by a just-completed record restore.

        Walks up to MainWindow via ``self.window()`` and calls the fine-grained
        refresh methods on the database sub-pages that own the restored table.

        table_name → affected pages:
          owners / pets  → clients_page  (and receipts / dashboard)
          visits         → visits_page + clients_page (visit counts shown there)
          appointments   → visits_page
        """
        try:
            main_win = self.window()
            main_page = getattr(main_win, "main_page", None)
            if main_page is None:
                return
            db_page = getattr(main_page, "database_page", None)
            dash_page = getattr(main_page, "dashboard_page", None)
            visits_standalone = getattr(main_page, "visits_page", None)

            if table_name in ("owners", "pets"):
                if db_page is not None:
                    db_page.clients_page.refresh_active_tab()
                    db_page.visits_page.refresh_visits_table()
                    db_page.receipts_page.refresh_receipts_table()

            elif table_name == "visits":
                if db_page is not None:
                    db_page.visits_page.refresh_active_tab()
                    db_page.clients_page.refresh_active_tab()
                    db_page.receipts_page.refresh_receipts_table()
                if visits_standalone is not None:
                    visits_standalone.refresh_visits_table()

            elif table_name == "appointments":
                if db_page is not None:
                    db_page.visits_page.refresh_appointments()

            elif table_name == "supplies":
                if db_page is not None:
                    db_page.supplies_page.refresh_all_tabs()

            elif table_name == "receipts":
                if db_page is not None:
                    db_page.receipts_page.refresh_receipts_table()

            # Always freshen the dashboard KPIs after any restore.
            if dash_page is not None:
                dash_page.refresh_data()

        except Exception:
            # Never crash the UI over a refresh failure.
            pass

    # --------------------------------------------------------- Translation --

    def retranslate_ui(self):
        """Updates text on this page when the language changes."""
        users_idx = self.tabs.indexOf(self.users_tab)
        if users_idx != -1:
            self.tabs.setTabText(users_idx, tr("User Management"))
        restore_idx = self.tabs.indexOf(self.restore_tab)
        if restore_idx != -1:
            self.tabs.setTabText(restore_idx, tr("Restore Records"))

        self.save_btn.setText(tr("Save"))
        self.cancel_btn.setText(tr("Cancel"))

        for panel in self._panels():
            panel.retranslate_ui()
