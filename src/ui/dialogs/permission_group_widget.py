"""
Shared collapsible permission-group widget for the RBAC editor dialogs.

Supports two modes:
  - check mode   : each permission is a QCheckBox (used by the role editor)
  - tri-state    : each permission is Inherit/Allow/Deny radios (per-user
                   overrides in the custom-permissions dialog)

The whole dialog owns a single outer scroll area; each section here is a plain
collapsible block (no per-section scrollbar). Every permission row shows its
name and a short description, so the meaning of each row is always visible.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QRadioButton,
    QToolButton, QVBoxLayout, QWidget, QSizePolicy,
)

from src.core import permissions as perm
from src.utils.i18n import tr


class _PermissionRow(QWidget):
    """One permission row: name + description (left) + control (right)."""

    def __init__(self, action, display_key, desc_key, mode, default_hint=None,
                 initial=None, parent=None):
        super().__init__(parent)
        self.action = action
        self.mode = mode
        self._default_hint = default_hint

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(10)

        # ---- Left: name + description ----
        self._name_label = QLabel(tr(display_key))
        self._name_label.setProperty("class", "row-title")
        desc = QLabel(tr(desc_key))
        desc.setProperty("class", "caption-label")
        desc.setWordWrap(True)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        text_col.addWidget(self._name_label)
        text_col.addWidget(desc)
        text_col.addStretch(1)
        layout.addLayout(text_col, 1)

        # ---- Right: control ----
        if mode == "check":
            self.checkbox = QCheckBox()
            if initial:
                self.checkbox.setChecked(True)
            layout.addWidget(self.checkbox)
        else:
            self.radios = {
                perm.OVERRIDE_ALLOW: QRadioButton(tr("allow")),
                perm.OVERRIDE_DENY: QRadioButton(tr("deny")),
                perm.OVERRIDE_INHERIT: QRadioButton(tr("default")),
            }
            self.group = QButtonGroup(self)
            self.group.setExclusive(True)
            for value, rb in self.radios.items():
                self.group.addButton(rb, value)
                layout.addWidget(rb)
            self.radios[perm.OVERRIDE_INHERIT].setChecked(True)
            if initial in self.radios:
                self.radios[initial].setChecked(True)

            hint = tr("role.hint", default="Default")
            self.hint_label = QLabel(f"({hint}: " + (self._default_hint or "—") + ")")
            self.hint_label.setProperty("class", "caption-label")
            layout.addWidget(self.hint_label)



    def value(self):
        """Returns True/False (check mode) or override int (tri-state mode)."""
        if self.mode == "check":
            return self.checkbox.isChecked()
        return self.group.checkedId() if self.group.checkedId() != -1 else perm.OVERRIDE_INHERIT

    def set_default_hint(self, hint):
        """Updates the tri-state 'Role default' hint text."""
        self._default_hint = hint

    def set_hint(self, text):
        """Replaces the tri-state hint label text (used for the live
        Default/Effective summary in the custom-permissions dialog)."""
        if self.mode != "check":
            self.hint_label.setText(f"({text})")


class PermissionGroupWidget(QWidget):
    """A collapsible section holding permission rows for one catalog module."""

    def __init__(self, section_key, items, mode="check", defaults=None,
                 overrides=None, parent=None):
        super().__init__(parent)
        self.section_key = section_key
        self.mode = mode
        self.rows = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # Collapsible header (tool button with arrow). No per-section scroll:
        # the dialog provides a single outer scroll area for everything.
        title = QToolButton()
        title.setText(tr(section_key))
        title.setCheckable(True)
        title.setChecked(True)
        title.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        title.setArrowType(Qt.DownArrow)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title.setProperty("class", "section-toggle")
        outer.addWidget(title)

        # Section body: a plain widget (no scrollbar of its own).
        body = QWidget()
        inner_layout = QVBoxLayout(body)
        inner_layout.setContentsMargins(8, 4, 8, 6)
        inner_layout.setSpacing(2)
        body.setLayout(inner_layout)
        outer.addWidget(body)

        self._inner_layout = inner_layout
        self._body = body

        for action, display_key, desc_key in items:
            default_hint = None
            initial = None
            if mode == "tri-state":
                if defaults:
                    default_hint = tr("yes") if action in defaults else tr("no")
                if isinstance(overrides, dict) and action in overrides:
                    initial = overrides[action]
            row = _PermissionRow(
                action, display_key, desc_key, mode,
                default_hint=default_hint, initial=initial,
            )
            inner_layout.addWidget(row)
            self.rows.append(row)

        # Wire the collapsible toggle.
        self._body.setVisible(True)
        title.clicked.connect(self._toggle)

    def _toggle(self, checked):
        self._body.setVisible(checked)
        self.sender().setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def collect(self):
        """Returns {action: value} based on current control state."""
        if self.mode == "check":
            return {r.action: r.checkbox.isChecked() for r in self.rows}
        return {r.action: r.group.checkedId() for r in self.rows}