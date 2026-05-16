"""
Shared pytest fixtures for the PET Application test suite.

Architecture note:
    Every repository module binds `get_connection` at import time via
    `from src.core.database import get_connection`.  To redirect repositories to
    an isolated per-test SQLite database, this module monkeypatches the
    `get_connection` attribute on *every* repo module at runtime (per test)
    to a fresh temporary database.

    This approach is deterministic regardless of pytest collection order and
    never touches the production Database.db.
"""

import atexit
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from PyQt5.QtSql import QSqlDatabase, QSqlQuery

import src.core.database as _db_pkg
import src.core.database.connection as _db_connection
from src.core.database.schema_initializer import initialize_schema
from src.core.database.seed_data import populate_default_lookup_data

# ---------------------------------------------------------------------------
# Repository modules whose `get_connection` we override per-test.
#
# IMPORTANT: we import repos lazily (inside fixtures, never at module level).
# The existing tests/test_crud_end_to_end.py patches `src.core.database.get_connection`
# in its own module body and then imports repos — if conftest imported the repos
# first, they would have bound the ORIGINAL get_connection and that test's
# bootstrap would silently break.  Lazy import avoids the conflict entirely:
# the first importer wins the initial binding, and our per-test fixture patches
# each module's `get_connection` attribute directly before any test code runs.
#
# Auto-discovered from the repositories directory so new repos are patched
# automatically (no manual list to keep in sync).  Only `*_repo.py` modules are
# included; helper modules such as `analytics_cache.py` are intentionally left out.
# ---------------------------------------------------------------------------
_REPO_DIR = Path(__file__).resolve().parent.parent / "src" / "core" / "repositories"
_REPO_NAMES = tuple(sorted(path.stem for path in _REPO_DIR.glob("*_repo.py")))


def _get_repo_modules():
    """Import (once) and return a dict of repo module objects, keyed by short name."""
    import importlib

    return {
        name: importlib.import_module(f"src.core.repositories.{name}")
        for name in _REPO_NAMES
    }

# ---------------------------------------------------------------------------
# Session-scoped Qt application (needed for QColor, QBrush, ThemeManager, etc.)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp():
    """Provides a single QApplication instance for the whole test session."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Per-test isolated application settings (SettingsManager).
#
# The Reports page writes a daily checkpoint marker through SettingsManager, so
# tests must never touch the real AppData settings.json. This autouse fixture
# redirects SETTINGS_FILE to a throwaway temp path (defaults are used when the
# file is missing) and resets the class cache around every test.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_app_settings(tmp_path, monkeypatch):
    from src.utils.settings_manager import SettingsManager

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("src.utils.settings_manager.SETTINGS_FILE", settings_file)
    SettingsManager._cache = None
    yield settings_file
    SettingsManager._cache = None


# ---------------------------------------------------------------------------
# Per-test isolated SQLite database backed by a real temporary file.
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_db(monkeypatch):
    """Creates a brand-new seeded SQLite database for each test.

    After the test completes the connection is closed, the temporary
    directory is removed, and all monkeypatched `get_connection` attributes
    are automatically restored.
    """
    test_dir = Path(tempfile.mkdtemp(prefix="pet_pytest_db_"))
    db_path = test_dir / "test_database.db"
    conn_name = f"pytest_conn_{uuid.uuid4().hex[:8]}"

    db = QSqlDatabase.addDatabase("QSQLITE", conn_name)
    db.setDatabaseName(str(db_path))
    if not db.open():
        raise RuntimeError(f"Could not open test database: {db.lastError().text()}")

    q = QSqlQuery(db)
    q.exec("PRAGMA foreign_keys = ON;")
    q.exec("PRAGMA journal_mode = MEMORY;")
    # Finish the PRAGMA statement. Because this fixture uses `yield`, every
    # local (including `q`) stays alive for the whole test; an unfinished
    # active statement would make `db.commit()` fail with
    # "cannot commit transaction - SQL statements in progress".
    q.finish()
    del q

    initialize_schema(db)
    populate_default_lookup_data(db)

    def _conn():
        return db

    # Redirect every repository + the database package to our fresh DB.
    for mod in _get_repo_modules().values():
        monkeypatch.setattr(mod, "get_connection", _conn, raising=False)
    monkeypatch.setattr(_db_pkg, "get_connection", _conn, raising=False)
    monkeypatch.setattr(_db_connection, "get_connection", _conn, raising=False)

    yield db

    try:
        db.close()
    except Exception:
        pass
    if QSqlDatabase.contains(conn_name):
        QSqlDatabase.removeDatabase(conn_name)
    shutil.rmtree(test_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helper: convenience fixture exposing repository modules themselves.
# ---------------------------------------------------------------------------
@pytest.fixture
def repos():
    """Returns the repository modules (patched to the fresh DB).

    Short-name keys map to the lazy-imported repo modules.
    """
    mods = _get_repo_modules()
    return {
        "client": mods["client_repo"],
        "pet": mods["pet_repo"],
        "visit": mods["visit_repo"],
        "appointment": mods["appointment_repo"],
        "supply": mods["supply_repo"],
        "stock": mods["stock_repo"],
        "sales": mods["sales_repo"],
        "analytics": mods["analytics_repo"],
        "followup": mods["followup_repo"],
        "health_stats": mods["health_stats_repo"],
        "test": mods["test_repo"],
        "treatment": mods["treatment_repo"],
        "vaccination": mods["vaccination_repo"],
        "medication": mods["medication_repo"],
        "user": mods["user_repo"],
        "audit": mods["audit_repo"],
        "log": mods["log_repo"],
        "package": mods["package_repo"],
        "supplier": mods["supplier_repo"],
    }


# ---------------------------------------------------------------------------
# Entity factory helpers shared by repository/service tests.
# ---------------------------------------------------------------------------
@pytest.fixture
def entity_factory(repos):
    """Provides factory callables for creating common entities."""
    import uuid as _uuid

    def make_client(name=None, phone="0500000000"):
        return int(repos["client"].add_client(name or f"Client {_uuid.uuid4().hex[:6]}", phone))

    def make_pet(client_id, name="Rex", species="Dog", breed="Labrador Retriever",
                 gender="M", age=24, weight=25.5):
        return int(repos["pet"].add_pet(name, species, breed, gender, age, weight, client_id))

    def make_supply(quantity=10, name=None, reorder_level=0, expiry=None,
                    category="Medicine", sub="Antibiotics",
                    buy_price=5.0, sell_price=10.0, purchase_date="2025-01-01"):
        item_name = name or f"Item {_uuid.uuid4().hex[:6]}"
        sid, _ = repos["supply"].add_supply(
            item_name, category, sub,
            purchase_date=purchase_date,
            expiry_date=expiry or "2026-12-31",
            buy_price=buy_price, sell_price=sell_price, quantity=quantity,
        )
        if reorder_level:
            repos["supply"].set_reorder_level(item_name, reorder_level)
        return int(sid), item_name

    return {
        "make_client": make_client,
        "make_pet": make_pet,
        "make_supply": make_supply,
    }
