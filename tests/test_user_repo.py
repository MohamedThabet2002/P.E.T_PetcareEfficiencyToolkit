"""Tests for the user repository (accounts, roles, overrides)."""

from src.core.repositories import user_repo


def test_add_user_rejects_unknown_role(fresh_db):
    """An account with a bogus role would log in but be denied everything."""
    assert user_repo.add_user("ghost", "secret123", "no-such-role") is None
    assert user_repo.get_user_by_username("ghost") is None


def test_add_user_assigns_a_known_role(fresh_db):
    uid = user_repo.add_user("real", "secret123", "staff")
    assert uid is not None
    assert user_repo.get_user_roles(uid) == ["staff"]


def test_count_users_with_role(fresh_db):
    # fresh_db seeds exactly one admin account.
    assert user_repo.count_users_with_role("admin") == 1

    user_repo.add_user("s1", "secret123", "staff")
    user_repo.add_user("s2", "secret123", "staff")
    assert user_repo.count_users_with_role("staff") == 2
    assert user_repo.count_users_with_role("doctor") == 0


def test_get_users_with_roles_reports_roles_and_override_count(fresh_db):
    uid = user_repo.add_user("combined", "secret123", "staff")
    user_repo.set_user_permissions(uid, {"edit_records": 1, "view_reports": 0, "add_visit": -1})

    rows = {u["username"]: u for u in user_repo.get_users_with_roles()}
    user = rows["combined"]
    assert user["roles"] == ["staff"]
    # The inherit (-1) override is stored as no row, so only two count.
    assert user["override_count"] == 2
    assert all(isinstance(u["roles"], list) for u in rows.values())
