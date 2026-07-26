"""Tests for the custom RBAC layer: role templates + per-user overrides.

Covers:
  - built-in role templates seeded by migration 014
  - custom role CRUD (add / rename / duplicate / delete) with system protection
  - role template editing (set_role_permissions / get_role_permissions)
  - per-user permission overrides (set / get / clear)
  - effective-permission resolution: override > role template > static default
"""

import pytest

from src.core import permissions as perm
from src.core.permissions import (
    OVERRIDE_ALLOW, OVERRIDE_DENY, OVERRIDE_INHERIT, can, effective_permission,
)
from src.core.repositories import user_repo


def _user(user_id, roles):
    return {"user_id": user_id, "roles": roles}


# ---------------------------------------------------------------------------
# Built-in role templates (seeded by migration 014)
# ---------------------------------------------------------------------------

def test_builtin_roles_are_system_and_seeded(fresh_db, repos):
    roles = user_repo.get_all_roles()
    by_name = {r["role_name"]: r for r in roles}
    assert set(by_name) == {"admin", "doctor", "staff"}
    for r in roles:
        assert r["is_system"] is True

    admin_perm = user_repo.get_role_by_name("admin")["permissions"]
    assert "view_reports" in admin_perm
    assert "view_financials" in admin_perm
    assert "view_visits" not in admin_perm  # carved out for admin

    doctor_perm = user_repo.get_role_by_name("doctor")["permissions"]
    assert "view_visits" in doctor_perm
    assert "view_reports" not in doctor_perm
    assert "view_dashboard" in doctor_perm

    staff_perm = user_repo.get_role_by_name("staff")["permissions"]
    assert "view_dashboard" in staff_perm
    assert "edit_records" not in staff_perm
    assert "request_change" in staff_perm


# ---------------------------------------------------------------------------
# Custom role lifecycle
# ---------------------------------------------------------------------------

def test_add_rename_duplicate_delete_role(fresh_db):
    role_id = user_repo.add_role("receptionist", "Front desk", {"view_dashboard", "view_records"})
    assert role_id is not None
    role = user_repo.get_role_by_id(role_id)
    assert role["role_name"] == "receptionist"
    assert role["description"] == "Front desk"
    assert role["is_system"] is False
    assert role["permissions"] == {"view_dashboard", "view_records"}

    # Duplicate
    dup_id = user_repo.add_role("receptionist_copy", role["description"], role["permissions"])
    assert dup_id is not None
    dup = user_repo.get_role_by_id(dup_id)
    assert dup["permissions"] == {"view_dashboard", "view_records"}

    # Rename
    assert user_repo.rename_role(role_id, "frontdesk") is True
    # Name collision
    assert user_repo.rename_role(role_id, "receptionist_copy") is None
    # Empty name
    assert user_repo.rename_role(role_id, "  ") is False

    # Delete custom roles
    assert user_repo.delete_role(role_id) is True
    assert user_repo.delete_role(dup_id) is True
    assert user_repo.get_role_by_id(role_id) is None


def test_system_roles_are_protected(fresh_db):
    admin_role = user_repo.get_role_by_name("admin")
    doctor_role = user_repo.get_role_by_name("doctor")
    staff_role = user_repo.get_role_by_name("staff")
    for r in (admin_role, doctor_role, staff_role):
        assert user_repo.rename_role(r["role_id"], "hacked") is False
        assert user_repo.delete_role(r["role_id"]) is False

    # Duplicate name collision for built-ins
    assert user_repo.add_role("doctor") is None


def test_set_role_permissions_updates_template(fresh_db):
    doctor = user_repo.get_role_by_name("doctor")
    assert "view_reports" not in doctor["permissions"]

    user_repo.set_role_permissions(doctor["role_id"], {"view_reports", "view_dashboard"})
    updated = user_repo.get_role_by_id(doctor["role_id"])
    assert updated["permissions"] == {"view_reports", "view_dashboard"}

    # Empty set is allowed for non-admin build-ins
    user_repo.set_role_permissions(doctor["role_id"], set())
    assert user_repo.get_role_by_id(doctor["role_id"])["permissions"] == set()


def test_users_holding_role_pick_up_new_template(fresh_db):
    uid = user_repo.add_user("dr_templ", "pw12345", "doctor")
    user = user_repo.get_user_by_id(uid)
    assert can(user, "view_reports") is False
    assert can(user, "view_visits") is True

    # Admin regrants the role with reports access.
    dr = user_repo.get_role_by_name("doctor")
    perms = set(dr["permissions"])
    perms.add("view_reports")
    user_repo.set_role_permissions(dr["role_id"], perms)

    user = user_repo.get_user_by_id(uid)  # simulates next login reload
    assert can(user, "view_reports") is True
    assert can(user, "view_visits") is True


# ---------------------------------------------------------------------------
# Per-user overrides
# ---------------------------------------------------------------------------

def test_user_permission_override_roundtrip(fresh_db):
    uid = user_repo.add_user("ovr", "pw12345", "doctor")
    assert user_repo.get_user_permissions(uid) == {}

    user_repo.set_user_permissions(uid, {"view_reports": OVERRIDE_ALLOW})
    saved = user_repo.get_user_permissions(uid)
    assert saved.get("view_reports") == OVERRIDE_ALLOW

    # Inherit values are not persisted (no explicit override)
    user_repo.set_user_permissions(uid, {"view_financials": OVERRIDE_INHERIT})
    assert user_repo.get_user_permissions(uid) == {}

    user_repo.set_user_permissions(uid, {"view_visits": OVERRIDE_DENY})
    assert user_repo.get_user_permissions(uid) == {"view_visits": OVERRIDE_DENY}

    user_repo.clear_user_permissions(uid)
    assert user_repo.get_user_permissions(uid) == {}

    # Unknown actions are ignored
    user_repo.set_user_permissions(uid, {"not_a_real_permission": OVERRIDE_ALLOW})
    assert user_repo.get_user_permissions(uid) == {}


def test_doctor_can_be_granted_reports_via_override(fresh_db):
    uid = user_repo.add_user("dr_override", "pw12345", "doctor")
    user = user_repo.get_user_by_id(uid)
    assert can(user, "view_reports") is False

    user_repo.set_user_permissions(uid, {"view_reports": OVERRIDE_ALLOW})
    user = user_repo.get_user_by_id(uid)  # reload on next login
    assert can(user, "view_reports") is True

    # Role defaults still apply.
    assert can(user, "view_visits") is True
    assert can(user, "add_supplies") is False


def test_deny_override_removes_role_capability(fresh_db):
    uid = user_repo.add_user("staff_deny", "pw12345", "staff")
    user = user_repo.get_user_by_id(uid)
    assert can(user, "request_change") is True

    user_repo.set_user_permissions(uid, {"request_change": OVERRIDE_DENY})
    user = user_repo.get_user_by_id(uid)
    assert can(user, "request_change") is False

    user_repo.clear_user_permissions(uid)
    user = user_repo.get_user_by_id(uid)
    assert can(user, "request_change") is True


# ---------------------------------------------------------------------------
# Effective-permission resolution (pure, no DB)
# ---------------------------------------------------------------------------

def test_effective_permission_override_beats_role(monkeypatch):
    doctor = {
        "user_id": 1,
        "roles": ["doctor"],
        "_role_permissions": set(perm.seed_permissions_for_role("doctor")),
    }
    assert effective_permission(doctor, "view_reports") == OVERRIDE_DENY

    doctor["_permissions"] = {"view_reports": OVERRIDE_ALLOW}
    assert effective_permission(doctor, "view_reports") == OVERRIDE_ALLOW
    assert can(doctor, "view_reports") is True

    doctor["_permissions"] = {"view_visits": OVERRIDE_DENY}
    assert effective_permission(doctor, "view_visits") == OVERRIDE_DENY
    assert can(doctor, "view_visits") is False


def test_admin_cannot_be_locked_out(monkeypatch):
    admin = {"user_id": 1, "roles": ["admin"]}
    for action in perm.ALL_ACTIONS:
        assert can(admin, action) is (action != "view_visits")

    # Even a hostile template/override cannot remove core admin powers.
    admin["_role_permissions"] = set()
    admin["_permissions"] = {a: OVERRIDE_DENY for a in perm.ALL_ACTIONS}
    assert can(admin, "manage_users") is True
    assert can(admin, "view_reports") is True
    assert can(admin, "view_visits") is False


def test_unknown_action_is_denied(monkeypatch):
    user = {"user_id": 1, "roles": ["admin"]}
    assert can(user, "does_not_exist") is False
    assert effective_permission(user, "does_not_exist") == OVERRIDE_DENY


# ---------------------------------------------------------------------------
# Catalog consistency
# ---------------------------------------------------------------------------

def test_catalog_covers_every_static_permission():
    catalog_keys = set(perm.ALL_ACTIONS)
    static_keys = set(perm._PERMISSIONS.keys())
    assert catalog_keys == static_keys or static_keys <= catalog_keys
    # Every catalog entry is a 3-tuple
    for section, items in perm.PERMISSION_CATALOG:
        assert isinstance(section, str)
        assert len(items) > 0
        for item in items:
            assert len(item) == 3
            assert item[0] in catalog_keys


def test_seed_permissions_for_custom_role_is_empty():
    assert perm.seed_permissions_for_role("receptionist") == set()
    assert perm.seed_permissions_for_role("doctor") == {
        a for a, allowed in perm._PERMISSIONS.items() if "doctor" in allowed
    }