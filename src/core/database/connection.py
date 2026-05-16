"""
Connection management module for the PET Application.
Handles SQLite connection lifecycle, PRAGMA settings, and schema/view initialization.
"""

import logging
import os

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtSql import QSqlDatabase, QSqlQuery, QSqlError

from src.core.backup_manager import create_backup, list_backups, load_backup_bytes
from src.config.paths import APP_DATA_ROOT, BACKUPS_DIR, USER_DB_PATH as USER_DB_PATH_CFG

from src.core.database.schema_initializer import initialize_schema

logger = logging.getLogger(__name__)

# Guard to ensure we don't repeatedly run schema/view init + migrations
# during the app lifetime.
_SCHEMA_INITIALIZED = False


def get_user_db_path():
    """Return the user-writable DB path (and initialize it if needed)."""
    global USER_DB_PATH_CFG
    if USER_DB_PATH_CFG is None:
        USER_DB_PATH_CFG = APP_DATA_ROOT / "Database.db"

        if not USER_DB_PATH_CFG.exists():
            backups = list_backups(BACKUPS_DIR)
            if backups:
                latest_backup = backups[0].backup_path
                try:
                    # Verify the checksum and decrypt if the backup was
                    # encrypted; a raw copy would restore ciphertext and the
                    # connection would then fail.
                    data = load_backup_bytes(latest_backup)
                    USER_DB_PATH_CFG.parent.mkdir(parents=True, exist_ok=True)
                    USER_DB_PATH_CFG.write_bytes(data)
                    logger.info(f"Database missing. Recovered from latest backup: {latest_backup}")
                except Exception as e:
                    logger.error(f"Failed to recover database from backup: {e}")
            else:
                logger.info(f"Initial database not found and no backups available. A new one will be created at {USER_DB_PATH_CFG}")

    return USER_DB_PATH_CFG


def get_connection():
    """Establishes and returns the database connection.

    Notes:
        We only run schema init/migrations once per app lifetime to avoid
        unnecessary startup overhead.
    """
    global _SCHEMA_INITIALIZED

    if not QSqlDatabase.contains("clinic_connection"):
        db_path = get_user_db_path()
        # Capture existence BEFORE the connection is opened: SQLite creates the
        # file on open, so afterwards it always exists. Only a pre-existing
        # database can be an upgrade that needs a safety backup.
        db_existed = db_path.exists()

        db = QSqlDatabase.addDatabase("QSQLITE", "clinic_connection")
        db.setDatabaseName(str(db_path))
        if not db.open():
            error_msg = f"Database connection failed: {db.lastError().text()}"
            logger.critical(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Database connection established at {db_path}")

        # Enable foreign keys (important for SQLite integrity)
        query = QSqlQuery(db)
        if not query.exec("PRAGMA foreign_keys = ON;"):
            logger.warning(f"Could not enable foreign keys: {query.lastError().text()}")

        # Schema/view init + migrations (guarded)
        if not _SCHEMA_INITIALIZED:
            if db_existed:
                _backup_before_upgrade(db, db_path)
            initialize_schema(db)
            _SCHEMA_INITIALIZED = True

        # SQLite performance-oriented PRAGMAs
        query.exec("PRAGMA journal_mode = WAL;")
        query.exec("PRAGMA synchronous = NORMAL;")
        query.exec("PRAGMA temp_store = MEMORY;")
        query.exec("PRAGMA cache_size = -2000;")

    return QSqlDatabase.database("clinic_connection")


def _backup_before_upgrade(db, db_path):
    """Take an automatic safety backup before an upgrade rewrites the schema.

    A database that already exists and still has pending migrations (or the
    pre-owners/pets legacy schema) is about to be modified in place by
    ``initialize_schema``. If a migration fails halfway the user would be left
    with a broken database and no way back, so snapshot it first.

    The backup is best-effort: a failure here must never stop the upgrade
    (the migration runner records each step only after it commits, so a failed
    run rolls back cleanly on its own).
    """
    from src.core.database.migrations import (
        has_legacy_schema,
        pending_migration_versions,
    )

    try:
        pending = pending_migration_versions(db)
        is_legacy = has_legacy_schema(db)
    except Exception:
        logger.warning(
            "Could not inspect pending migrations; skipping pre-upgrade backup.",
            exc_info=True,
        )
        return

    if not pending and not is_legacy:
        return

    try:
        backup_path = create_backup(db_path, BACKUPS_DIR, backup_kind="auto")
        logger.info(
            "Pre-upgrade safety backup created (%d pending migration(s)): %s",
            len(pending), backup_path,
        )
    except Exception:
        logger.exception("Pre-upgrade backup failed; continuing with the upgrade.")
