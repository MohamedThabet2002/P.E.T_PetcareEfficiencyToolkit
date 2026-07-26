"""
Permissions module for the PET Application.

Centralizes all RBAC (role-based access control) checks.
Use ``can(user, action)`` in both UI and service layers — never
scatter role-string comparisons across pages.

Permission model (professional RBAC)
------------------------------------
Authorization is resolved in three layers, from most to least specific:

1. Per-user override   (``user_permissions``) — an admin can grant or revoke
   a single permission for a single user (3-state: -1 inherit / 0 deny / 1 allow).
2. Role templates      (``role_permissions``) — every role (built-in *and*
   user-defined) carries the set of permissions it grants. Editing a role's
   template updates every user holding that role.
3. Static defaults     (``_PERMISSIONS``) — the built-in defaults for the
   three seeded roles (admin/doctor/staff). Used as a fallback so hand-built
   user dicts and fresh installs behave predictably.

The ``admin`` role is protected: its effective set is always at least its
static default, so administrative controls can never be accidentally
removed by editing templates.

A user dict may carry two optional caches (populated at login):
    - ``_role_permissions`` : set of permission keys granted by roles
    - ``_permissions``      : dict of per-user overrides {action: -1/0/1}
When neither is present (e.g. unit tests building bare dicts), resolution
falls back to the static ``_PERMISSIONS`` map.

Usage
-----
    from src.core.permissions import can, get_role, is_admin, is_doctor

    if can(user, "edit_records"):
        ...
"""

from __future__ import annotations

from typing import Optional

OVERRIDE_DENY = 0
OVERRIDE_ALLOW = 1
OVERRIDE_INHERIT = -1

# ---------------------------------------------------------------------------
# Static role defaults (built-in roles). Single authoritative source for the
# seeded roles and the fallback for bare user dicts.
# ---------------------------------------------------------------------------

_PERMISSIONS: dict[str, set[str]] = {
    # Navigation / page access
    "view_dashboard":       {"admin", "doctor", "staff"},
    "view_database":        {"admin", "doctor", "staff"},
    "view_reports":         {"admin"},
    "view_settings":        {"admin", "doctor", "staff"},
    "view_visits":          {"doctor"},          # Standalone top-level Visits page (doctor only)

    # Data CRUD
    "add_records":          {"admin", "doctor"},
    "edit_records":         {"admin"},
    "delete_records":       {"admin"},
    "view_records":         {"admin", "doctor", "staff"},

    # Approval workflow
    "request_change":       {"doctor", "staff"},
    "approve_changes":      {"admin"},

    # Dashboard extras
    "view_financials":      {"admin"},
    "view_own_appointments":{"doctor"},
    "view_all_appointments":{"admin", "staff"},
    "add_visit":            {"admin", "doctor"},
    "add_supplies":         {"admin"},
    "quick_purchase":       {"admin", "doctor"},

    # Settings / ops
    "backup_restore":       {"admin"},
    "manage_users":         {"admin"},
    "reset_passwords":      {"admin"},
}


# ---------------------------------------------------------------------------
# Permission catalog (grouped for the editor UIs)
# ---------------------------------------------------------------------------
# Each section is a tuple (section_key, [(action, display_key, description_key), ...]).
# The *_key values are i18n lookup keys (see src/utils/i18n.py / translations.json).
# i18n keys are namespaced to keep the dialog translations isolated and collision-free.

PERMISSION_CATALOG: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("perm.nav", [
        ("view_dashboard",      "perm.view_dashboard",      "perm.desc.view_dashboard"),
        ("view_database",       "perm.view_database",       "perm.desc.view_database"),
        ("view_reports",        "perm.view_reports",        "perm.desc.view_reports"),
        ("view_settings",       "perm.view_settings",       "perm.desc.view_settings"),
        ("view_visits",         "perm.view_visits",         "perm.desc.view_visits"),
    ]),
    ("perm.records", [
        ("view_records",        "perm.view_records",        "perm.desc.view_records"),
        ("add_records",         "perm.add_records",         "perm.desc.add_records"),
        ("edit_records",        "perm.edit_records",        "perm.desc.edit_records"),
        ("delete_records",      "perm.delete_records",      "perm.desc.delete_records"),
    ]),
    ("perm.dashboard", [
        ("add_visit",           "perm.add_visit",           "perm.desc.add_visit"),
        ("add_supplies",        "perm.add_supplies",        "perm.desc.add_supplies"),
        ("quick_purchase",      "perm.quick_purchase",      "perm.desc.quick_purchase"),
        ("view_financials",     "perm.view_financials",     "perm.desc.view_financials"),
    ]),
    ("perm.appointments", [
        ("view_own_appointments",  "perm.view_own_appointments",  "perm.desc.view_own_appointments"),
        ("view_all_appointments",  "perm.view_all_appointments",  "perm.desc.view_all_appointments"),
    ]),
    ("perm.workflow", [
        ("request_change",      "perm.request_change",      "perm.desc.request_change"),
        ("approve_changes",     "perm.approve_changes",     "perm.desc.approve_changes"),
    ]),
    ("perm.admin", [
        ("backup_restore",      "perm.backup_restore",      "perm.desc.backup_restore"),
        ("manage_users",        "perm.manage_users",        "perm.desc.manage_users"),
        ("reset_passwords",     "perm.reset_passwords",     "perm.desc.reset_passwords"),
    ]),
]

# Ordered set of every known action (union of the catalog).
ALL_ACTIONS: list[str] = [a for _, items in PERMISSION_CATALOG for a, _, _ in items]

# The built-in (protected) role names that are seeded with the app.
SYSTEM_ROLES = ("admin", "doctor", "staff")

# Actions that are intentionally excluded from the protected ``admin`` role.
# ``view_visits`` is the doctors' personal standalone page — administrators do
# not see it (consistent with the pre-existing behavior).
ADMIN_CARVE_OUT = {"view_visits"}


def seed_permissions_for_role(role_name: str) -> set[str]:
    """Returns the default permission set for a built-in role (from the
    static map). For the protected ``admin`` role this is every action minus
    the carve-out set; unknown/custom roles start empty."""
    if role_name == "admin":
        return set(ALL_ACTIONS) - ADMIN_CARVE_OUT
    return {a for a, allowed in _PERMISSIONS.items() if role_name in allowed}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _is_protected_admin(user: Optional[dict]) -> bool:
    """True if the user carries the system ``admin`` role."""
    return bool(user) and "admin" in get_roles(user)


def get_roles(user: Optional[dict]) -> list[str]:
    """Returns a normalised (lower-case) list of role names for *user*."""
    if not user:
        return []
    return [str(r).lower() for r in user.get("roles", [])]


def get_role(user: Optional[dict]) -> str:
    """Returns the primary role name for *user* (first role, lower-case).

    Priority: admin > doctor > staff > '' (unauthenticated).
    """
    roles = get_roles(user)
    for primary in ("admin", "doctor", "staff"):
        if primary in roles:
            return primary
    return roles[0] if roles else ""


def is_admin(user: Optional[dict]) -> bool:
    """Returns True if *user* has the ``admin`` role."""
    return "admin" in get_roles(user)


def is_doctor(user: Optional[dict]) -> bool:
    """Returns True if *user* has the ``doctor`` role (and is not admin)."""
    roles = get_roles(user)
    return "doctor" in roles and "admin" not in roles


def is_staff(user: Optional[dict]) -> bool:
    """Returns True if *user* has the ``staff`` role (and is not admin/doctor)."""
    roles = get_roles(user)
    return "staff" in roles and "admin" not in roles and "doctor" not in roles


def _role_granted_actions(user: Optional[dict]) -> set[str]:
    """Returns the set of actions granted by the user's roles.

    Uses the cached ``_role_permissions`` set when present (attached at login
    from ``role_permissions`` templates). Falls back to the static map.
    Protected admins always gain the full action set (cannot be locked out).
    """
    if not user:
        return set()
    cached = user.get("_role_permissions")
    actions = set(cached) if cached is not None else _from_static(user)
    if _is_protected_admin(user):
        actions |= set(seed_permissions_for_role("admin"))
    return actions


def _from_static(user: Optional[dict]) -> set[str]:
    """Static-map fallback: every action whose allowed-role set intersects the
    user's roles."""
    roles = set(get_roles(user))
    return {a for a, allowed in _PERMISSIONS.items() if roles & allowed}


def effective_permission(user: Optional[dict], action: str) -> int:
    """Returns the resolved permission state for *user* and *action*.

    Returns one of:
        OVERRIDE_ALLOW (1)  — allowed
        OVERRIDE_DENY  (0)  — denied
        OVERRIDE_INHERIT(-1)— resolved to the role default / not allowed
    """
    if not user:
        return OVERRIDE_DENY
    if _is_protected_admin(user) and action in seed_permissions_for_role("admin"):
        return OVERRIDE_ALLOW
    overrides = user.get("_permissions")
    if isinstance(overrides, dict) and action in overrides:
        val = overrides[action]
        if val in (OVERRIDE_ALLOW, OVERRIDE_DENY):
            return val
    if action in _role_granted_actions(user):
        return OVERRIDE_ALLOW
    return OVERRIDE_DENY


def can(user: Optional[dict], action: str) -> bool:
    """Returns True if *user* is permitted to perform *action*.

    Deny-by-default for unknown actions. Resolution order:
    per-user override -> role templates -> static defaults.
    """
    return effective_permission(user, action) == OVERRIDE_ALLOW
