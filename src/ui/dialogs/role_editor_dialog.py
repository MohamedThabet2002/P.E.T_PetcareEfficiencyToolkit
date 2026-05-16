"""
Role Editor Dialog for the PET Application.

Lets an admin manage roles as reusable permission templates:
  - list existing roles (built-in protected roles + user-defined ones)
  - create / rename / duplicate / delete custom roles
  - edit a role's permission set with grouped checkbox sections

Editing a role's template immediately affects every user holding that role
when they next log in.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QInputDialog, QScrollArea, QWidget, QFrame, QLineEdit,
)

from src.core import permissions as perm
from src.core.repositories import user_repo
from src.ui.dialogs.permission_group_widget import PermissionGroupWidget
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

DIALOG_WIDTH = 860
DIALOG_HEIGHT = 600


class RoleEditorDialog(QDialog):
    """Dialog for managing role permission templates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Role Editor"))
        self.setMinimumSize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)

        self._groups = {}
        self._current_role = None
        self._setup_ui()
        self._load_roles()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        title = QLabel(tr("Custom Roles"))
        title.setProperty("class", "dialog-title")
        main.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(10)

        # --- Left: role list + management buttons ---
        left = QVBoxLayout()
        self.role_list = QListWidget()
        self.role_list.setMinimumWidth(200)
        self.role_list.currentItemChanged.connect(self._on_role_selected)
        left.addWidget(self.role_list)

        role_btns = QHBoxLayout()
        self.add_role_btn = QPushButton(tr("New"))
        self.add_role_btn.clicked.connect(self._add_role)
        self.rename_role_btn = QPushButton(tr("Rename"))
        self.rename_role_btn.clicked.connect(self._rename_role)
        self.duplicate_btn = QPushButton(tr("Duplicate"))
        self.duplicate_btn.clicked.connect(self._duplicate_role)
        self.delete_role_btn = QPushButton(tr("Delete"))
        self.delete_role_btn.clicked.connect(self._delete_role)
        role_btns.addWidget(self.add_role_btn)
        role_btns.addWidget(self.rename_role_btn)
        role_btns.addWidget(self.duplicate_btn)
        role_btns.addWidget(self.delete_role_btn)
        left.addLayout(role_btns)
        body.addLayout(left, 0)

        # --- Right: permission template editor ---
        right = QVBoxLayout()
        self.detail_title = QLabel(tr("no_role_selected"))
        self.detail_title.setProperty("class", "section-heading")
        right.addWidget(self.detail_title)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText(tr("role_desc_placeholder"))
        self.desc_edit.setEnabled(False)
        right.addWidget(self.desc_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        right.addWidget(scroll, 1)
        self._content_layout = content_layout
        self._content = content

        # Help footnote
        hint = QLabel(tr("role_editor_hint"))
        hint.setProperty("class", "dialog-hint")
        hint.setWordWrap(True)
        right.addWidget(hint)

        body.addLayout(right, 1)
        main.addLayout(body, 1)

        # Bottom actions
        actions = QHBoxLayout()
        self.save_btn = QPushButton(tr("Save"))
        self.save_btn.clicked.connect(self._save_current)
        self.cancel_btn = QPushButton(tr("Close"))
        self.cancel_btn.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(self.save_btn)
        actions.addWidget(self.cancel_btn)
        main.addLayout(actions)

    # ------------------------------------------------------------ helpers
    def _load_roles(self):
        self.role_list.clear()
        self._roles = user_repo.get_all_roles()
        for role in self._roles:
            item = QListWidgetItem(role["role_name"])
            if role["is_system"]:
                item.setData(Qt.UserRole, "system")
                item.setToolTip(tr("system_role_tip"))
            self.role_list.addItem(item)
        if self.role_list.count():
            self.role_list.setCurrentRow(0)

    def _selected_role(self):
        row = self.role_list.currentRow()
        if row < 0 or row >= len(self._roles):
            return None
        return self._roles[row]

    def _is_system(self, role_id):
        for r in self._roles:
            if r["role_id"] == role_id:
                return r["is_system"]
        return False

    def _on_role_selected(self):
        role = self._selected_role()
        self.desc_edit.blockSignals(True)
        if role is None:
            self.detail_title.setText(tr("no_role_selected"))
            self.desc_edit.clear()
            self.desc_edit.setEnabled(False)
            self._current_role = None
            self._clear_groups()
            self.desc_edit.blockSignals(False)
            return

        # Editing a role is loaded fresh from the DB on every selection; the
        # Save button persists the current tab's changes.
        perms = user_repo.get_role_permissions(role["role_id"])
        self._current_role = role
        self.desc_edit.setText(role.get("description") or "")
        self.desc_edit.setEnabled(True)
        suffix = ""
        if role["is_system"]:
            suffix = tr("system_badge")
        self.detail_title.setText(f"{role['role_name']}{suffix}")
        self._clear_groups()
        for section, items in perm.PERMISSION_CATALOG:
            g = PermissionGroupWidget(section, items, mode="check")
            for row in g.rows:
                row.checkbox.setChecked(row.action in perms)
            self._content_layout.insertWidget(self._content_layout.count() - 1, g)
            self._groups[section] = g
        self.desc_edit.blockSignals(False)

    def _clear_groups(self):
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._groups.clear()

    def _save_current(self):
        role = self._current_role
        if role is None:
            return
        description = self.desc_edit.text().strip()
        user_repo.update_role_description(role["role_id"], description)

        selected = set()
        for section, items in perm.PERMISSION_CATALOG:
            g = self._groups.get(section)
            if g is None:
                continue
            for row in g.rows:
                if row.checkbox.isChecked():
                    selected.add(row.action)
        if role["is_system"] and "admin" == role["role_name"]:
            # Protect the admin role: keep the full carved admin set no matter
            # what the admin toggles (cannot be locked out).
            selected |= set(perm.seed_permissions_for_role("admin"))
        user_repo.set_role_permissions(role["role_id"], selected)
        for r in self._roles:
            if r["role_id"] == role["role_id"]:
                r["description"] = description
        QMessageBox.information(self, tr("Success"), tr("role_saved"))

    # ------------------------------------------------------ role lifecycle
    def _add_role(self):
        name, ok = QInputDialog.getText(self, tr("New Role"), tr("Role name:"))
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        result = user_repo.add_role(name, "")
        if result is None:
            QMessageBox.warning(self, tr("Error"), tr("role_name_taken"))
            return
        if result is False:
            QMessageBox.warning(self, tr("Error"), tr("role_create_failed"))
            return
        self._load_roles()
        for i, r in enumerate(self._roles):
            if r["role_name"] == name:
                self.role_list.setCurrentRow(i)
                break

    def _rename_role(self):
        role = self._selected_role()
        if role is None:
            return
        if role["is_system"]:
            QMessageBox.information(self, tr("Role Editor"), tr("system_role_no_rename"))
            return
        new_name, ok = QInputDialog.getText(
            self, tr("Rename Role"), tr("New Role name:"), text=role["role_name"]
        )
        if not ok or not new_name.strip():
            return
        result = user_repo.rename_role(role["role_id"], new_name.strip())
        if result is True:
            self._load_roles()
        elif result is None:
            QMessageBox.warning(self, tr("Error"), tr("role_name_taken"))
        else:
            QMessageBox.warning(self, tr("Error"), tr("role_rename_failed"))

    def _duplicate_role(self):
        role = self._selected_role()
        if role is None:
            return
        new_name, ok = QInputDialog.getText(
            self, tr("Duplicate Role"), tr("New Role name:"),
            text=role["role_name"] + "_copy",
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        perms = user_repo.get_role_permissions(role["role_id"])
        result = user_repo.add_role(new_name, role.get("description") or "", perms)
        if result is None:
            QMessageBox.warning(self, tr("Error"), tr("role_name_taken"))
            return
        if result is False:
            QMessageBox.warning(self, tr("Error"), tr("role_create_failed"))
            return
        self._load_roles()
        for i, r in enumerate(self._roles):
            if r["role_name"] == new_name:
                self.role_list.setCurrentRow(i)
                break

    def _delete_role(self):
        role = self._selected_role()
        if role is None:
            return
        if role["is_system"]:
            QMessageBox.information(self, tr("Role Editor"), tr("system_role_no_delete"))
            return
        reply = QMessageBox.question(
            self, tr("Confirm Delete"),
            tr("delete_role_confirm").format(name=role["role_name"])
            + "\n\n" + tr("role_delete_users_effect"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        if not user_repo.delete_role(role["role_id"]):
            QMessageBox.warning(self, tr("Error"), tr("role_delete_failed"))
            return
        self._load_roles()
