"""Tests for the first-run default-admin hardening.

The stock seed inserts an ``admin`` user with the known placeholder password
``admin123``. ``FirstRunDialog`` hardens it: if the clinic reuses the ``admin``
username its password is reset to the chosen one; otherwise the stock account is
deleted after the real admin is created. These tests exercise the same repo
calls the dialog makes against a fresh seeded DB.
"""

from src.core.repositories.user_repo import (
    add_user,
    authenticate_user,
    delete_user,
    get_user_by_username,
    update_user_password,
)


def test_stock_admin_exists_with_known_password(fresh_db, repos):
    stock = repos["user"].get_user_by_username("admin")
    assert stock is not None
    assert authenticate_user("admin", "admin123") is not None


def test_reuse_admin_username_resets_password(fresh_db, repos):
    stock = repos["user"].get_user_by_username("admin")
    assert stock is not None
    assert update_user_password(stock["user_id"], "NewSecret!") is True

    assert authenticate_user("admin", "NewSecret!") is not None
    assert authenticate_user("admin", "admin123") is None


def test_new_admin_removes_stock_admin(fresh_db, repos):
    user_repo = repos["user"]
    stock = user_repo.get_user_by_username("admin")
    assert stock is not None

    # Same flow as FirstRunDialog.accept() when a non-"admin" name is chosen.
    new_id = add_user("clinic_owner", "s3curePass", role_name="admin")
    assert new_id is not None
    if stock is not None:
        delete_user(stock["user_id"])

    assert user_repo.get_user_by_username("admin") is None
    assert user_repo.get_user_by_username("clinic_owner") is not None
    assert authenticate_user("admin", "admin123") is None
    assert authenticate_user("clinic_owner", "s3curePass") is not None


def test_stock_admin_is_not_recreated_once_users_exist(fresh_db, repos):
    """Re-seeding the lookup tables must never resurrect admin/admin123.

    ``populate_default_lookup_data`` also runs as seed maintenance whenever a
    lookup table is emptied. Once the clinic has replaced the stock admin, that
    maintenance pass must not silently reopen the default credential.
    """
    from src.core.database.seed_data import populate_default_lookup_data

    user_repo = repos["user"]
    add_user("clinic_owner", "s3curePass", role_name="admin")
    delete_user(user_repo.get_user_by_username("admin")["user_id"])

    populate_default_lookup_data(fresh_db)

    assert user_repo.get_user_by_username("admin") is None
    assert authenticate_user("admin", "admin123") is None
    assert authenticate_user("clinic_owner", "s3curePass") is not None