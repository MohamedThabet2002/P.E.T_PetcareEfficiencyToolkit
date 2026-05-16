"""Tests for the AdminPage (admin-only tools page)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QMessageBox, QPushButton, QTabWidget

from src.ui.pages.admin_page import AdminPage
from src.ui.pages.admin_panels import RestoreDeletedPanel, UserManagementPanel
from src.ui.pages.settings_page import SettingsPage
from src.ui.side_menu import MENU_ITEMS, MENU_ITEMS_CONFIG


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _staff():
    return {"user_id": 2, "username": "staff", "roles": ["staff"]}


def test_admin_page_hosts_only_the_two_tool_panels(qapp):
    page = AdminPage()

    # Users + Restore are the only tools; suppliers moved to a dialog.
    assert isinstance(page.users_panel, UserManagementPanel)
    assert isinstance(page.restore_panel, RestoreDeletedPanel)
    for gone in ("suppliers_section", "supplier_list", "add_supp_btn",
                 "edit_supp_btn", "del_supp_btn"):
        assert not hasattr(page, gone)
    for method in ("refresh_suppliers", "add_supplier", "edit_supplier", "delete_supplier"):
        assert not hasattr(page, method)


def test_admin_page_embeds_the_panels_instead_of_opening_dialogs(qapp):
    page = AdminPage()

    assert isinstance(page.tabs, QTabWidget)
    assert page.tabs.count() == 2
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "User Management", "Restore Records",
    ]

    # Each tab body IS the tool (no launcher button in between).
    assert page.tabs.widget(0) is page.users_panel
    assert page.tabs.widget(1) is page.restore_panel
    assert page.users_tab is page.users_panel
    assert page.restore_tab is page.restore_panel
    for gone in ("users_section", "restore_section", "user_mgmt_btn", "restore_deleted_btn",
                 "_open_user_management", "_open_restore_deleted"):
        assert not hasattr(page, gone)


def test_admin_page_panels_have_no_title_and_tables_fill_the_page(qapp):
    """The tab bar is the only title; each table owns the page and its action
    row is pinned to the bottom edge."""
    page = AdminPage()

    for panel, table in ((page.users_panel, page.users_panel.user_table),
                         (page.restore_panel, page.restore_panel.table)):
        assert not hasattr(panel, "title_label")
        layout = panel.layout()
        assert layout.indexOf(table) == 0          # table is the first/only growing item
        assert table.parentWidget() is panel
        # No trailing stretch pushing the action row away from the bottom edge.
        assert layout.itemAt(layout.count() - 1).layout() is not None


def test_admin_page_has_a_global_save_and_cancel_row(qapp):
    page = AdminPage()

    assert isinstance(page.save_btn, QPushButton)
    assert isinstance(page.cancel_btn, QPushButton)
    assert page.save_btn.text() == "Save"
    assert page.cancel_btn.text() == "Cancel"

    # Both buttons sit in the page-level row below the tabs (Save then Cancel).
    page_layout = page.layout()
    assert page_layout.indexOf(page.tabs) == 0
    button_row = page_layout.itemAt(page_layout.count() - 1).layout()
    assert [button_row.itemAt(i).widget() for i in range(button_row.count())
            if button_row.itemAt(i).widget()] == [page.save_btn, page.cancel_btn]


def test_admin_page_gates_tabs_by_permission(qapp):
    page = AdminPage()
    page.set_current_user(_staff())

    assert page.tabs.isTabVisible(page.tabs.indexOf(page.users_tab)) is False   # manage_users
    assert page.tabs.isTabVisible(page.tabs.indexOf(page.restore_tab)) is False  # edit_records

    page.set_current_user(_admin())
    assert page.tabs.isTabVisible(page.tabs.indexOf(page.users_tab)) is True
    assert page.tabs.isTabVisible(page.tabs.indexOf(page.restore_tab)) is True


def test_admin_page_never_shows_the_inactive_tab(qapp):
    """Regression: gating must not call setVisible on the panels — doing so
    un-hides the inactive tab, which then paints on top of the current one
    until the user switches tabs."""
    page = AdminPage()
    page.set_current_user(_admin())

    page.tabs.setCurrentIndex(0)
    assert page.users_panel.isHidden() is False
    assert page.restore_panel.isHidden() is True

    page.tabs.setCurrentIndex(1)
    assert page.restore_panel.isHidden() is False
    assert page.users_panel.isHidden() is True


def test_admin_page_propagates_the_user_to_panels(qapp):
    page = AdminPage()
    user = _admin()

    page.set_current_user(user)

    assert page.users_panel._current_user == user
    assert page.restore_panel._current_user == user


def test_admin_page_save_refreshes_every_panel(qapp, fresh_db, monkeypatch):
    calls = []
    monkeypatch.setattr(UserManagementPanel, "refresh_data",
                        lambda self: calls.append("users"))
    monkeypatch.setattr(RestoreDeletedPanel, "refresh_data",
                        lambda self: calls.append("restore"))
    monkeypatch.setattr("src.ui.pages.admin_page.QMessageBox.information",
                        lambda *a, **k: None)
    page = AdminPage()
    calls.clear()

    page.save_settings()

    assert calls == ["users", "restore"]


def test_admin_page_cancel_clears_selection_and_refreshes(qapp, fresh_db, monkeypatch):
    cleared = []
    calls = []
    monkeypatch.setattr(UserManagementPanel, "clear_selection",
                        lambda self: cleared.append("users"))
    monkeypatch.setattr(RestoreDeletedPanel, "clear_selection",
                        lambda self: cleared.append("restore"))
    monkeypatch.setattr(UserManagementPanel, "refresh_data",
                        lambda self: calls.append("users"))
    monkeypatch.setattr(RestoreDeletedPanel, "refresh_data",
                        lambda self: calls.append("restore"))
    page = AdminPage()
    calls.clear()

    page.cancel_settings()

    assert cleared == ["users", "restore"]
    assert calls == ["users", "restore"]


def test_admin_page_switching_tabs_reloads_the_visible_panel(qapp, fresh_db, monkeypatch):
    calls = []
    monkeypatch.setattr(UserManagementPanel, "refresh_data",
                        lambda self: calls.append("users"))
    monkeypatch.setattr(RestoreDeletedPanel, "refresh_data",
                        lambda self: calls.append("restore"))
    page = AdminPage()
    page.set_current_user(_admin())

    page.tabs.setCurrentIndex(1)
    assert calls[-1] == "restore"

    page.tabs.setCurrentIndex(0)
    assert calls[-1] == "users"


def test_admin_page_builds_without_a_database(qapp, monkeypatch):
    """Construction must not query — tabs load lazily when shown."""
    monkeypatch.setattr(UserManagementPanel, "refresh_data",
                        lambda self: pytest.fail("users tab queried at construction"))
    monkeypatch.setattr(RestoreDeletedPanel, "refresh_data",
                        lambda self: pytest.fail("restore tab queried at construction"))

    AdminPage()



def test_admin_nav_item_is_a_page_before_settings():
    names = [item.name for item in MENU_ITEMS_CONFIG]
    assert "admin" in names
    assert names.index("admin") < names.index("settings")
    assert MENU_ITEMS["admin"] == "Admin"


def test_nav_config_matches_main_page_stack_order():
    """The stacked page order must stay in lockstep with MENU_ITEMS_CONFIG."""
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "ui" / "pages" / "main_page.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    def _setup_main_page_content(node):
        return next(
            child for child in ast.walk(node)
            if isinstance(child, ast.FunctionDef) and child.name == "_setup_main_page_content"
        )

    added = [
        call.args[0].attr
        for call in ast.walk(_setup_main_page_content(tree))
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "addWidget"
        and isinstance(call.args[0], ast.Attribute)
    ]

    expected = [item.name + "_page" for item in MENU_ITEMS_CONFIG if item.is_page]
    assert added == expected
    assert "admin_page" in added


def test_settings_page_no_longer_hosts_admin_tools(qapp):
    page = SettingsPage()

    assert not hasattr(page, "suppliers_tab")
    assert not hasattr(page, "supplier_list")
    assert not hasattr(page, "user_mgmt_btn")
    assert not hasattr(page, "restore_deleted_btn")
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Clinic Profile",
        "Appearance",
        "Database Backup",
        "Custom Lists",
        "DEV",
    ]


def test_supplier_crud_lives_in_the_supplies_dialog(qapp, fresh_db):
    """Suppliers are reached from the Supplies page, not the Admin page."""
    from src.ui.dialogs.suppliers_dialog import SuppliersDialog

    page = AdminPage()
    dialog = SuppliersDialog()

    assert dialog.supplier_list.count() == 0
    assert hasattr(dialog, "add_supplier")
    assert not hasattr(page, "add_supplier")


def test_admin_page_retranslates_labels(qapp, fresh_db):
    page = AdminPage()

    page.retranslate_ui()

    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "User Management", "Restore Records",
    ]
    assert page.save_btn.text() == "Save"
    assert page.cancel_btn.text() == "Cancel"
    assert page.users_panel.add_btn.text() == "Add User"
    assert page.restore_panel.restore_btn.text() == "Restore"


@pytest.mark.parametrize("table_name", ["owners", "visits", "supplies", "unknown"])
def test_refresh_after_restore_is_safe_without_main_window(qapp, table_name):
    page = AdminPage()

    # No MainWindow parent — must not raise.
    page._refresh_pages_after_restore(table_name)


def test_admin_i18n_key_exists(qapp):
    from src.utils.i18n import tr

    assert tr("Admin") == "Admin"
    assert tr("User Management") == "User Management"
    assert tr("Restore Records") == "Restore Records"
