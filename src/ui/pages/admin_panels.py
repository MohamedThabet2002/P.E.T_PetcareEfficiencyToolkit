"""
Admin tool panels for the PET Application.

These were modal dialogs (``UserManagementDialog`` / ``RestoreDeletedDialog``)
once; they are plain ``QWidget`` tab bodies now, hosted by
``src/ui/pages/admin_page.py`` (one panel per tab).

Each panel keeps its own per-row action buttons — the page-level Save / Cancel
row lives on the Admin page itself. Neither panel touches the database from
``__init__``: the Admin page calls ``refresh_data()`` when the page/tab is
shown, so no query runs for a tab the user cannot see.
"""

import json
import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from src.core.permissions import can
from src.core.repositories import undo_repo, user_repo
from src.ui.dialogs.custom_permissions_dialog import CustomPermissionsDialog
from src.ui.dialogs.role_editor_dialog import RoleEditorDialog
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

PASSWORD_MIN_LEN = 4

# Table headers, kept as tuples so retranslate_ui can rebuild them.
USER_TABLE_HEADERS = ("User ID", "Username", "Roles", "Overrides", "Last Login")
RESTORE_TABLE_HEADERS = ("Record Type", "Record ID", "Name / Code", "Deleted On", "Deleted By")

# Display label per journal table_name.
_TYPE_LABELS = {
    "owners": "Owner",
    "pets": "Pet",
    "visits": "Visit",
    "appointments": "Appointment",
    "supplies": "Supply",
    "receipts": "Receipt",
}

# Key inside the snapshot's first table row used to build a human-readable
# summary shown in the "Name / Code" column.
_SUMMARY_KEY = {
    "owners": "first_name",
    "pets": "pet_name",
    "visits": "diagnosis",
    "appointments": "reason_for_visit",
    "supplies": "item_name",
    "receipts": "receipt_code",
}


class UserManagementPanel(QWidget):
    """User accounts table with add / rename / role / permission actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_user = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # The table owns the whole page; the action row is pinned to the bottom.
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(len(USER_TABLE_HEADERS))
        self.user_table.setHorizontalHeaderLabels([tr(key) for key in USER_TABLE_HEADERS])
        self.user_table.horizontalHeader().setStretchLastSection(True)
        self.user_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.user_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.user_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.user_table.setAlternatingRowColors(True)
        self.user_table.setSortingEnabled(True)
        layout.addWidget(self.user_table, 1)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)

        self.add_btn = QPushButton(tr("Add User"))
        self.add_btn.clicked.connect(self._add_user_dialog)

        self.rename_btn = QPushButton(tr("Rename Username"))
        self.rename_btn.clicked.connect(self._rename_username_dialog)
        
        self.reset_pwd_btn = QPushButton(tr("Reset Password"))
        self.reset_pwd_btn.clicked.connect(self._reset_password_dialog)
        
        self.edit_role_btn = QPushButton(tr("Edit Roles"))
        self.edit_role_btn.clicked.connect(self._edit_roles_dialog)
        
        self.delete_btn = QPushButton(tr("Delete User"))
        self.delete_btn.clicked.connect(self._delete_user_dialog)
        
        self.custom_perms_btn = QPushButton(tr("Change Permissions"))
        self.custom_perms_btn.setToolTip(tr("custom_permissions_btn_tip"))
        self.custom_perms_btn.clicked.connect(self._custom_permissions_dialog)

        self.roles_btn = QPushButton(tr("Customize Roles"))
        self.roles_btn.setToolTip(tr("custom_roles_btn_tip"))
        self.roles_btn.clicked.connect(self._role_editor_dialog)





        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.rename_btn)
        button_layout.addWidget(self.reset_pwd_btn)
        button_layout.addWidget(self.edit_role_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addWidget(self.custom_perms_btn)
        button_layout.addWidget(self.roles_btn)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)
        button_layout.addStretch()

        layout.addLayout(button_layout)
        self._apply_permission_gating()

    # ------------------------------------------------------------ Gating --

    def _apply_permission_gating(self):
        """Enables each action only for users allowed to perform it.

        The whole tab is gated by ``manage_users`` (AdminPage hides it), but a
        user can hold ``manage_users`` while a per-user override denies
        ``reset_passwords`` — so each destructive action re-checks here rather
        than trusting the tab gate alone.
        """
        can_manage = can(self._current_user, "manage_users")
        can_reset = can(self._current_user, "reset_passwords")
        for btn in (self.add_btn, self.rename_btn, self.edit_role_btn,
                    self.delete_btn, self.custom_perms_btn, self.roles_btn):
            btn.setEnabled(can_manage)
        self.reset_pwd_btn.setEnabled(can_reset)

    # ---------------------------------------------------------------- Data --

    def set_current_user(self, user):
        """Stores the logged-in user and re-applies per-action gating."""
        self._current_user = user if user else {}
        self._apply_permission_gating()

    def clear_selection(self):
        """Clears the selected row (used by the page-level Cancel)."""
        self.user_table.clearSelection()
        self.user_table.setCurrentCell(-1, -1)

    def refresh_data(self):
        """Refreshes the user table from the database."""
        users = user_repo.get_users_with_roles()
        self.user_table.setSortingEnabled(False)
        self.user_table.setRowCount(len(users))

        for row, user in enumerate(users):
            user_id = user["user_id"]
            id_item = QTableWidgetItem()
            id_item.setData(Qt.DisplayRole, user_id)
            self.user_table.setItem(row, 0, id_item)

            username_item = QTableWidgetItem(user["username"])
            self.user_table.setItem(row, 1, username_item)

            roles = user.get("roles") or []
            roles_str = ", ".join(roles) if roles else tr("None")
            roles_item = QTableWidgetItem(roles_str)
            self.user_table.setItem(row, 2, roles_item)

            override_count = user.get("override_count", 0)
            if override_count:
                overrides_item = QTableWidgetItem(str(override_count))
                overrides_item.setTextAlignment(Qt.AlignCenter)
            else:
                overrides_item = QTableWidgetItem("")
            self.user_table.setItem(row, 3, overrides_item)

            last_login = user.get("last_login")
            login_item = QTableWidgetItem(str(last_login) if last_login else tr("Never"))
            self.user_table.setItem(row, 4, login_item)

        self.user_table.setSortingEnabled(True)

    # -------------------------------------------------------------- Actions --

    def _get_selected_user_id(self):
        """Returns the user_id of the selected row, or None."""
        row = self.user_table.currentRow()
        if row < 0:
            return None
        item = self.user_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.DisplayRole)

    def _require_selected_user(self):
        """Returns the selected user_id, or None after informing the user."""
        user_id = self._get_selected_user_id()
        if user_id is None:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a user."))
        return user_id

    def _add_user_dialog(self):
        """Opens a dialog to add a new user."""
        username, ok = QInputDialog.getText(self, tr("Add User"), tr("Username:"))
        if not ok or not username.strip():
            return

        password, ok = QInputDialog.getText(
            self, tr("Add User"), tr("Password:"),
            echo=QLineEdit.Password
        )
        if not ok or not password.strip():
            return

        if len(password) < PASSWORD_MIN_LEN:
            QMessageBox.warning(
                self, tr("Validation Error"),
                tr("Password must be at least {n} characters.").format(n=PASSWORD_MIN_LEN)
            )
            return

        # Select role
        roles = user_repo.get_all_roles()
        role_names = [r["role_name"] for r in roles]

        if role_names:
            role, ok = QInputDialog.getItem(
                self, tr("User Role"), tr("Select role:"),
                role_names, 0, False
            )
            if not ok:
                return
        else:
            role = "staff"

        result = user_repo.add_user(username.strip(), password, role)
        if result:
            QMessageBox.information(self, tr("Success"), tr("User '{name}' created.").format(name=username))
            self.refresh_data()
        else:
            QMessageBox.warning(self, tr("Error"), tr("Failed to create user. Username may already exist."))

    def _edit_roles_dialog(self):
        """Opens a dialog to assign/remove a role for the selected user."""
        user_id = self._require_selected_user()
        if user_id is None:
            return

        row = self.user_table.currentRow()
        username = self.user_table.item(row, 1).text()
        current_roles = user_repo.get_user_roles(user_id)

        roles = user_repo.get_all_roles()
        role_names = [r["role_name"] for r in roles]
        if not role_names:
            return

        actions = [f"{tr('Assign Role')}: {r}" for r in role_names if r not in current_roles]
        actions += [f"{tr('Remove Role')}: {r}" for r in current_roles]

        if not actions:
            QMessageBox.information(self, tr("Roles"), tr("No role modifications available."))
            return

        chosen_action, ok = QInputDialog.getItem(
            self, tr("Edit Roles: {name}").format(name=username), tr("Select action:"),
            actions, 0, False
        )
        if not ok or not chosen_action:
            return

        for r in role_names:
            if chosen_action == f"{tr('Assign Role')}: {r}":
                user_repo.assign_role(user_id, r)
            elif chosen_action == f"{tr('Remove Role')}: {r}":
                user_repo.remove_role(user_id, r)

        self.refresh_data()

    def _custom_permissions_dialog(self):
        """Opens the fine-grained per-user permission editor for the selected user."""
        user_id = self._require_selected_user()
        if user_id is None:
            return
        row = self.user_table.currentRow()
        username = self.user_table.item(row, 1).text()
        dlg = CustomPermissionsDialog(user_id, username, self)
        if dlg.exec_():
            self.refresh_data()

    def _role_editor_dialog(self):
        """Opens the role template editor."""
        dlg = RoleEditorDialog(self)
        dlg.exec_()
        self.refresh_data()

    def _reset_password_dialog(self):
        """Opens a dialog to reset a user's password."""
        user_id = self._require_selected_user()
        if user_id is None:
            return

        password, ok = QInputDialog.getText(
            self, tr("Reset Password"), tr("New Password:"),
            echo=QLineEdit.Password
        )
        if not ok or not password.strip():
            return

        if len(password) < PASSWORD_MIN_LEN:
            QMessageBox.warning(
                self, tr("Validation Error"),
                tr("Password must be at least {n} characters.").format(n=PASSWORD_MIN_LEN)
            )
            return

        if user_repo.update_user_password(user_id, password):
            QMessageBox.information(self, tr("Success"), tr("Password updated successfully."))
        else:
            QMessageBox.warning(self, tr("Error"), tr("Failed to update password."))

    def _rename_username_dialog(self):
        """Opens a dialog to rename the selected user's username."""
        user_id = self._require_selected_user()
        if user_id is None:
            return

        row = self.user_table.currentRow()
        current_username = self.user_table.item(row, 1).text()

        new_username, ok = QInputDialog.getText(
            self,
            tr("Rename Username"),
            tr("New Username:"),
            text=current_username,
        )
        if not ok:
            return
        new_username = new_username.strip()
        if not new_username:
            QMessageBox.warning(self, tr("Validation Error"), tr("Username cannot be empty."))
            return
        if new_username == current_username:
            return

        result = user_repo.rename_user(user_id, new_username)
        if result is True:
            QMessageBox.information(self, tr("Success"), tr("Username updated successfully."))
            self.refresh_data()
        elif result is None:
            QMessageBox.warning(
                self, tr("Error"),
                tr("Username '{name}' is already in use.").format(name=new_username)
            )
        else:
            QMessageBox.warning(self, tr("Error"), tr("Failed to update username."))

    def _delete_user_dialog(self):
        """Deletes the selected user after confirmation."""
        user_id = self._require_selected_user()
        if user_id is None:
            return

        row = self.user_table.currentRow()
        username = self.user_table.item(row, 1).text()

        # Never let the clinic lock itself out: refuse to delete the last admin.
        target_roles = [r.lower() for r in user_repo.get_user_roles(user_id)]
        if "admin" in target_roles and user_repo.count_users_with_role("admin") <= 1:
            QMessageBox.warning(
                self, tr("Cannot Delete"),
                tr("You cannot delete the last administrator account."),
            )
            return

        # Deleting your own account is allowed, but warned about explicitly.
        if user_id == (self._current_user or {}).get("user_id"):
            if QMessageBox.question(
                self, tr("Confirm Delete"),
                tr("You are about to delete your own account. You will be logged out. Continue?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return

        reply = QMessageBox.question(
            self, tr("Confirm Delete"),
            tr("Delete user '{name}'?\n\nThis action cannot be undone.").format(name=username),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if user_repo.delete_user(user_id):
                self.refresh_data()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to delete user."))

    # --------------------------------------------------------- Translation --

    def retranslate_ui(self):
        """Updates text on this panel when the language changes."""
        self.user_table.setHorizontalHeaderLabels([tr(key) for key in USER_TABLE_HEADERS])
        self.add_btn.setText(tr("Add User"))
        self.rename_btn.setText(tr("Rename Username"))
        self.reset_pwd_btn.setText(tr("Reset Password"))
        self.edit_role_btn.setText(tr("Edit Roles"))
        self.delete_btn.setText(tr("Delete User"))
        self.custom_perms_btn.setText(tr("Change Permissions"))
        self.custom_perms_btn.setToolTip(tr("custom_permissions_btn_tip"))
        self.roles_btn.setText(tr("Customize Roles"))
        self.roles_btn.setToolTip(tr("custom_roles_btn_tip"))


class RestoreDeletedPanel(QWidget):
    """Shows journaled deletes and restores the selected one on demand.

    Pass ``filter_table="supplies"`` (or ``"receipts"``) to show only that
    record type; omit or pass ``None`` to show everything.

    Emits ``record_restored(table_name)`` each time a record is successfully
    restored so callers can refresh the relevant pages without polling.
    """

    # Emitted with the restored record's table_name (e.g. "owners", "visits").
    record_restored = pyqtSignal(str)

    def __init__(self, parent=None, current_user=None, filter_table=None):
        super().__init__(parent)
        self._current_user = current_user or {}
        self._filter_table = filter_table  # None = all types
        self._entries = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # The table owns the whole page; the Restore button is pinned to the bottom.
        self.table = QTableWidget()
        self.table.setColumnCount(len(RESTORE_TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels([tr(key) for key in RESTORE_TABLE_HEADERS])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self._empty_label = QLabel(tr("No deleted records to restore."))
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        self.restore_btn = QPushButton(tr("Restore"))
        self.restore_btn.setMinimumHeight(34)
        self.restore_btn.clicked.connect(self._restore_selected)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.restore_btn)
        layout.addLayout(btn_row)

    # ---------------------------------------------------------------- Data --

    def set_current_user(self, user):
        """Stores the logged-in user used to attribute the restore action."""
        self._current_user = user if user else {}

    def clear_selection(self):
        """Clears the selected row (used by the page-level Cancel)."""
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)

    def refresh_data(self):
        """Re-reads the undo journal into the table."""
        all_entries = undo_repo.list_deleted_records()
        # Filter to a specific table type when hosted by a sub-page.
        if self._filter_table:
            self._entries = [e for e in all_entries if e["table_name"] == self._filter_table]
        else:
            self._entries = all_entries
        self.table.setRowCount(0)
        owner_names = self._owner_names()
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            table_name = entry["table_name"]
            type_label = tr(_TYPE_LABELS.get(table_name, table_name.title()))
            self.table.setItem(row, 0, QTableWidgetItem(type_label))
            self.table.setItem(row, 1, QTableWidgetItem(str(entry["record_id"])))
            self.table.setItem(row, 2, QTableWidgetItem(self._summary(entry)))
            self.table.setItem(row, 3, QTableWidgetItem(str(entry["deleted_at"] or "")))
            self.table.setItem(row, 4, QTableWidgetItem(owner_names.get(entry["deleted_by"], "")))
        self._empty_label.setVisible(not self._entries)
        self.restore_btn.setEnabled(bool(self._entries))

    def _summary(self, entry):
        """Extract a short human-readable label from the snapshot's first row."""
        try:
            snapshot = json.loads(entry.get("snapshot") or "")
            table_name = entry["table_name"]
            key = _SUMMARY_KEY.get(table_name)
            if not key or not snapshot.get("tables"):
                return ""
            first_block = snapshot["tables"][0]
            if first_block["rows"]:
                val = first_block["rows"][0].get(key, "")
                return str(val) if val is not None else ""
        except Exception:
            pass
        return ""

    def _owner_names(self):
        try:
            return {int(u["user_id"]): u.get("username", "") for u in user_repo.get_users()}
        except Exception:
            return {}

    # -------------------------------------------------------------- Actions --

    def _restore_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        if QMessageBox.question(
            self, tr("Restore Deleted Records"),
            tr("Restore this record?"),
        ) != QMessageBox.Yes:
            return

        ok, msg = undo_repo.restore_deleted_record(
            entry["deleted_record_id"],
            user_id=(self._current_user or {}).get("user_id"),
        )
        if ok:
            QMessageBox.information(self, tr("Restore Deleted Records"),
                                    tr("Restored successfully."))
            self.record_restored.emit(entry["table_name"])
            self.refresh_data()
        else:
            QMessageBox.warning(self, tr("Restore Deleted Records"),
                                tr("Failed to restore the record.") + f"\n{msg}")

    # --------------------------------------------------------- Translation --

    def retranslate_ui(self):
        """Updates text on this panel when the language changes."""
        self.table.setHorizontalHeaderLabels([tr(key) for key in RESTORE_TABLE_HEADERS])
        self._empty_label.setText(tr("No deleted records to restore."))
        self.restore_btn.setText(tr("Restore"))
        # Row labels are translated values, so re-render them.
        self.refresh_data()
