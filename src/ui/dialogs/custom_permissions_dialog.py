"""
Custom Permissions Dialog for the PET Application.

Per-user permission overrides: an admin can fine-tune exactly what a single
user may do, on top of (and overriding) the permissions granted by their
roles. Each permission offers three states:

    inherit  - use the role's default (no override)
    allow    - force allow, even if the role denies it
    deny     - force deny, even if the role grants it

A live "effective" column shows what the user actually ends up with once the
role template and the selected overrides are combined.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QScrollArea, QWidget, QFrame, QGroupBox, QGridLayout,
)

from src.core import permissions as perm
from src.core.repositories import user_repo
from src.ui.dialogs.permission_group_widget import PermissionGroupWidget
from src.utils.i18n import tr

DIALOG_WIDTH = 880
DIALOG_HEIGHT = 640


class CustomPermissionsDialog(QDialog):
    """Fine-grained per-user permission editor."""

    def __init__(self, user_id, username, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.username = username
        self.setWindowTitle(tr("custom_permissions_title").format(name=username))
        self.setMinimumSize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)

        self._groups = {}
        self._roles = user_repo.get_user_roles(user_id)
        self._role_actions = self._compute_role_actions()
        self._setup_ui()
        self._load_overrides()

    # ---------------------------------------------------------- role set
    def _compute_role_actions(self):
        """Set of actions granted by the user's role templates (from DB)."""
        actions = set()
        for role_name in self._roles:
            actions |= user_repo.get_role_permissions_by_name(role_name)
        if "admin" in self._roles:
            actions |= set(perm.seed_permissions_for_role("admin"))
        return actions

    def _effective_for(self, action, override):
        """Effective (allow/deny) for an action given a selected override.

        Resolution mirrors the runtime path exactly (override -> role template
        -> protected-admin floor) by delegating to
        :func:`permissions.effective_permission`, so the "Effective" column can
        never disagree with what the user will actually be allowed to do.
        """
        overrides = {}
        if override in (perm.OVERRIDE_ALLOW, perm.OVERRIDE_DENY):
            overrides[action] = override
        probe = {
            "user_id": self.user_id,
            "roles": list(self._roles),
            "_role_permissions": set(self._role_actions),
            "_permissions": overrides,
        }
        return perm.effective_permission(probe, action) == perm.OVERRIDE_ALLOW

    def _refresh_effective(self):
        """Recomputes the per-row "Default / Effective" hint text."""
        for section, _items in perm.PERMISSION_CATALOG:
            group = self._groups.get(section)
            if group is None:
                continue
            for row in group.rows:
                default_allowed = row.action in self._role_actions
                effective = self._effective_for(row.action, row.value())
                row.set_hint(
                    tr("default") + ": " + (tr("yes") if default_allowed else tr("no"))
                    + "  |  " + tr("effective") + ": "
                    + (tr("allow") if effective else tr("deny"))
                )

    # -------------------------------------------------------------- UI
    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        title = QLabel(tr("custom_permissions_title").format(name=self.username))
        title.setProperty("class", "dialog-title")
        main.addWidget(title)

        subtitle = QLabel(
            tr("roles_for") + (", ".join(self._roles) if self._roles else tr("none"))
        )
        subtitle.setProperty("class", "dialog-subtitle")
        main.addWidget(subtitle)

        legend = QLabel(
            tr("legend_allow") + "  |  " + tr("legend_deny") + "  |  " + tr("legend_inherit")
        )
        legend.setProperty("class", "dialog-hint")
        main.addWidget(legend)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        main.addWidget(scroll, 1)
        self._content_layout = content_layout

        self._overrides = {}
        for section, items in perm.PERMISSION_CATALOG:
            g = PermissionGroupWidget(
                section, items, mode="tri-state",
                defaults=self._role_actions,
                overrides=self._overrides,
            )
            self._content_layout.insertWidget(self._content_layout.count() - 1, g)
            self._groups[section] = g
            for row in g.rows:
                row.group.buttonClicked.connect(lambda *_: self._on_override_changed())

        # Bottom actions
        actions = QHBoxLayout()
        self.reset_btn = QPushButton(tr("reset_all"))
        self.reset_btn.clicked.connect(self._reset_all)
        self.save_btn = QPushButton(tr("Save"))
        self.save_btn.clicked.connect(self._save)
        self.close_btn = QPushButton(tr("Cancel"))
        self.close_btn.clicked.connect(self.reject)
        actions.addWidget(self.reset_btn)
        actions.addStretch()
        actions.addWidget(self.save_btn)
        actions.addWidget(self.close_btn)
        main.addLayout(actions)

    def _load_overrides(self):
        self._overrides = user_repo.get_user_permissions(self.user_id)
        for section, items in perm.PERMISSION_CATALOG:
            g = self._groups.get(section)
            if g is None:
                continue
            for row in g.rows:
                val = self._overrides.get(row.action, perm.OVERRIDE_INHERIT)
                row.radios[val].setChecked(True)
        self._refresh_effective()

    def _on_override_changed(self):
        # Recompute overrides from the live UI state.
        for section, items in perm.PERMISSION_CATALOG:
            g = self._groups.get(section)
            if g is None:
                continue
            for row in g.rows:
                self._overrides[row.action] = row.value()
        self._refresh_effective()

    def _reset_all(self):
        reply = QMessageBox.question(
            self, tr("reset_all"), tr("reset_all_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._overrides = {}
        for section, items in perm.PERMISSION_CATALOG:
            g = self._groups.get(section)
            if g is None:
                continue
            for row in g.rows:
                row.radios[perm.OVERRIDE_INHERIT].setChecked(True)
        self._refresh_effective()

    def _save(self):
        for section, items in perm.PERMISSION_CATALOG:
            g = self._groups.get(section)
            if g is None:
                continue
            for row in g.rows:
                self._overrides[row.action] = row.value()
        user_repo.set_user_permissions(self.user_id, self._overrides)
        QMessageBox.information(self, tr("Success"), tr("permissions_saved"))
        self.accept()
