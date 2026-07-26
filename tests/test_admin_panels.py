"""Tests for the embedded admin tool panels (users + undo-journal restore)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QMessageBox, QPushButton, QTableWidget

from src.core.repositories import undo_repo
from src.ui.pages.admin_panels import RestoreDeletedPanel, UserManagementPanel


def _seed_owner_with_pet(entity_factory):
    cid = entity_factory["make_client"]("Restore Owner", "0550000000")
    pid = entity_factory["make_pet"](cid, "Restore Pet", weight=9.0)
    return cid, pid


# --------------------------------------------------------------- Restore --


def test_panel_lists_journaled_deletes_and_restores(qapp, fresh_db, entity_factory, repos, monkeypatch):
    cid, pid = _seed_owner_with_pet(entity_factory)
    client_repo = repos["client"]
    assert client_repo.delete_client(cid, audit_user_id=None) is True

    panel = RestoreDeletedPanel(current_user={"user_id": None, "username": "admin"})
    panel.refresh_data()
    assert isinstance(panel.table, QTableWidget)
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 1).text() == str(cid)
    assert panel.restore_btn.isEnabled()
    assert panel._entries[0]["table_name"] == "owners"

    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.question",
        lambda *a, **k: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.information",
        lambda *a, **k: None,
    )
    restored = []
    panel.record_restored.connect(restored.append)
    panel.table.selectRow(0)
    panel._restore_selected()

    assert restored == ["owners"]
    assert undo_repo.list_deleted_records() == []
    # Owner + pet are back in the live tables.
    from src.core.database.connection import get_connection
    from PyQt5.QtSql import QSqlQuery
    db = get_connection()
    for table, col, value in (("owners", "owner_id", cid), ("pets", "pet_id", pid)):
        q = QSqlQuery(db)
        q.prepare(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?")
        q.addBindValue(value)
        q.exec()
        q.next()
        assert int(q.value(0)) == 1, f"{table} {value} not restored"


def test_panel_empty_state(qapp, fresh_db):
    panel = RestoreDeletedPanel(current_user={"user_id": None, "username": "admin"})
    panel.refresh_data()
    assert panel.table.rowCount() == 0
    assert not panel._empty_label.isHidden()
    assert not panel.restore_btn.isEnabled()


def test_panel_does_not_query_the_database_on_construction(qapp, fresh_db, monkeypatch):
    """The page loads tabs lazily, so __init__ must stay DB-free."""
    calls = []
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.undo_repo.list_deleted_records",
        lambda *a, **k: calls.append(1) or [],
    )
    RestoreDeletedPanel()
    UserManagementPanel()
    assert calls == []


def test_panel_retranslate_rerenders_labels(qapp, fresh_db, entity_factory, repos):
    cid, _ = _seed_owner_with_pet(entity_factory)
    repos["client"].delete_client(cid, audit_user_id=None)

    panel = RestoreDeletedPanel(current_user={"user_id": None, "username": "admin"})
    panel.refresh_data()
    assert panel.table.item(0, 0).text() == "Owner"

    panel.retranslate_ui()

    assert panel.restore_btn.text() == "Restore"
    assert [
        panel.table.horizontalHeaderItem(i).text() for i in range(panel.table.columnCount())
    ] == ["Record Type", "Record ID", "Name / Code", "Deleted On", "Deleted By"]
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "Owner"


def test_panel_clear_selection(qapp, fresh_db, entity_factory, repos):
    cid, _ = _seed_owner_with_pet(entity_factory)
    repos["client"].delete_client(cid, audit_user_id=None)

    panel = RestoreDeletedPanel()
    panel.refresh_data()
    panel.table.selectRow(0)
    assert panel.table.currentRow() == 0

    panel.clear_selection()

    assert panel.table.currentRow() == -1


def test_restore_panel_can_filter_by_table(qapp, fresh_db, entity_factory, repos):
    cid, _ = _seed_owner_with_pet(entity_factory)
    repos["client"].delete_client(cid, audit_user_id=None)

    panel = RestoreDeletedPanel(filter_table="visits")
    panel.refresh_data()

    assert panel.table.rowCount() == 0
    assert panel._entries == []


# ---------------------------------------------------------------- Layout --


@pytest.mark.parametrize("panel_attr,table_attr,expected_items", [
    ("UserManagementPanel", "user_table", 2),   # table + action row
    ("RestoreDeletedPanel", "table", 3),        # table + empty-state label + action row
])
def test_panels_have_no_title_and_table_fills_above_a_bottom_action_row(
        qapp, fresh_db, panel_attr, table_attr, expected_items):
    """No in-tab title: the tab bar labels the tool, the table takes the whole
    page and the action row is the last item (pinned to the bottom edge)."""
    panel = globals()[panel_attr]()
    table = getattr(panel, table_attr)
    layout = panel.layout()

    assert not hasattr(panel, "title_label")
    assert layout.indexOf(table) == 0
    assert layout.count() == expected_items
    # The table is the only growing item and nothing trails the action row.
    assert layout.stretch(0) == 1
    assert layout.itemAt(layout.count() - 1).spacerItem() is None


# ----------------------------------------------------------------- Users --


def test_user_panel_lists_accounts(qapp, fresh_db, repos):
    repos["user"].add_user("panel_user", "secret123", "staff")

    panel = UserManagementPanel()
    panel.refresh_data()

    assert isinstance(panel.user_table, QTableWidget)
    usernames = [panel.user_table.item(r, 1).text() for r in range(panel.user_table.rowCount())]
    assert "panel_user" in usernames


def test_user_panel_exposes_row_action_buttons(qapp, fresh_db):
    panel = UserManagementPanel()
    buttons = [
        panel.add_btn, panel.rename_btn, panel.reset_pwd_btn,
        panel.edit_role_btn, panel.delete_btn, panel.custom_perms_btn,
        panel.roles_btn,
    ]
    assert all(isinstance(btn, QPushButton) for btn in buttons)
    assert [btn.text() for btn in buttons] == [
        "Add User", "Rename Username", "Reset Password", "Edit Roles",
        "Delete User", "Change Permissions", "Customize Roles",
    ]

    layout = panel.layout().itemAt(1).layout()
    assert [layout.itemAt(i).widget() for i in range(7)] == buttons


def test_user_panel_requires_a_selected_user(qapp, fresh_db, monkeypatch):
    shown = []
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.information",
        lambda *a, **k: shown.append(a),
    )
    panel = UserManagementPanel()
    panel.refresh_data()
    panel.user_table.clearSelection()

    assert panel._require_selected_user() is None
    assert len(shown) == 1


def test_user_panel_retranslate(qapp, fresh_db):
    panel = UserManagementPanel()

    panel.retranslate_ui()

    assert [
        panel.user_table.horizontalHeaderItem(i).text()
        for i in range(panel.user_table.columnCount())
    ] == ["User ID", "Username", "Roles", "Overrides", "Last Login"]


@pytest.mark.parametrize("propagation", ["set_current_user", "clear_selection"])
def test_user_panel_page_protocol(qapp, fresh_db, propagation):
    """Both panels implement the hooks AdminPage calls on every tab."""
    panel = UserManagementPanel()
    assert hasattr(panel, propagation)

    panel.set_current_user({"user_id": 1, "username": "admin"})
    panel.clear_selection()


def _select_username(panel, username):
    """Selects the row whose Username cell matches *username*."""
    for row in range(panel.user_table.rowCount()):
        if panel.user_table.item(row, 1).text() == username:
            panel.user_table.selectRow(row)
            return row
    raise AssertionError(f"{username!r} not found in the user table")


def test_user_panel_gates_reset_password_independently(qapp, fresh_db):
    """A manage-users grant without reset-passwords leaves that button off."""
    panel = UserManagementPanel()
    partial = {
        "user_id": 1, "username": "partial", "roles": ["staff"],
        "_role_permissions": {"manage_users"}, "_permissions": {},
    }
    panel.set_current_user(partial)
    assert panel.add_btn.isEnabled()
    assert not panel.reset_pwd_btn.isEnabled()

    full = {
        "user_id": 2, "username": "full", "roles": ["staff"],
        "_role_permissions": {"manage_users", "reset_passwords"}, "_permissions": {},
    }
    panel.set_current_user(full)
    assert panel.add_btn.isEnabled()
    assert panel.reset_pwd_btn.isEnabled()


def test_user_panel_cannot_delete_the_last_admin(qapp, fresh_db, repos, monkeypatch):
    """The clinic must never lock itself out by deleting its only admin."""
    # fresh_db seeds a stock admin; add a second account so we can prove the
    # guard only fires when the admin being deleted is the last one.
    repos["user"].add_user("staffer", "secret123", "staff")

    warnings = []
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.warning",
        lambda *a, **k: warnings.append(a),
    )
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.question",
        lambda *a, **k: QMessageBox.Yes,
    )

    panel = UserManagementPanel()
    panel.refresh_data()
    _select_username(panel, "admin")
    panel._delete_user_dialog()

    assert warnings and "administrator" in warnings[0][2].lower()
    assert _username_present(panel, "admin")


def test_user_panel_warns_before_deleting_your_own_account(qapp, fresh_db, repos, monkeypatch):
    """Deleting yourself needs an explicit confirmation (and can be declined)."""
    second = repos["user"].add_user("admin2", "secret123", "admin")
    assert second is not None

    asked = []
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.question",
        lambda *a, **k: asked.append(a) or QMessageBox.No,
    )
    monkeypatch.setattr(
        "src.ui.pages.admin_panels.QMessageBox.information",
        lambda *a, **k: None,
    )

    panel = UserManagementPanel()
    panel.set_current_user({"user_id": second, "username": "admin2", "roles": ["admin"]})
    panel.refresh_data()
    _select_username(panel, "admin2")
    panel._delete_user_dialog()

    assert asked, "self-delete should prompt for confirmation"
    assert "your own account" in asked[0][2].lower()
    # Declined -> the account is untouched.
    assert _username_present(panel, "admin2")


def _username_present(panel, username):
    panel.refresh_data()
    return any(
        panel.user_table.item(r, 1).text() == username
        for r in range(panel.user_table.rowCount())
    )
