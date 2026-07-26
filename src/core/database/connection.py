"""
Connection management module for the PET Application.
Handles SQLite connection lifecycle, PRAGMA settings, and schema/view initialization.
"""

import logging
import os
import shutil

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtSql import QSqlDatabase, QSqlQuery, QSqlError

from src.core.backup_manager import list_backups
import src.config as config

from src.core.database.schema_initializer import initialize_schema

logger = logging.getLogger(__name__)

# Guard to ensure we don't repeatedly run schema/view init + migrations
# during the app lifetime.
_SCHEMA_INITIALIZED = False


def get_user_db_path() -> "config.Path":
    """Return the user-writable DB path (and initialize it if needed)."""
    if config.USER_DB_PATH is None:
        config.USER_DB_PATH = config.APP_DATA_ROOT / "Database.db"

        if not config.USER_DB_PATH.exists():
            backups = list_backups(config.BACKUPS_DIR)
            if backups:
                latest_backup = backups[0].backup_path
                try:
                    shutil.copy2(str(latest_backup), str(config.USER_DB_PATH))
                    logger.info(f"Database missing. Recovered from latest backup: {latest_backup}")
                except Exception as e:
                    logger.error(f"Failed to recover database from backup: {e}")
            else:
                logger.info(f"Initial database not found and no backups available. A new one will be created at {config.USER_DB_PATH}")

    return config.USER_DB_PATH


def get_connection():
    """Establishes and returns the database connection.

    Notes:
        We only run schema init/migrations once per app lifetime to avoid
        unnecessary startup overhead.
    """
    global _SCHEMA_INITIALIZED

    if not QSqlDatabase.contains("clinic_connection"):
        db_path = get_user_db_path()
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
            initialize_schema(db)
            _SCHEMA_INITIALIZED = True

        # SQLite performance-oriented PRAGMAs
        query.exec("PRAGMA journal_mode = WAL;")
        query.exec("PRAGMA synchronous = NORMAL;")
        query.exec("PRAGMA temp_store = MEMORY;")
        query.exec("PRAGMA cache_size = -2000;")

    return QSqlDatabase.database("clinic_connection")
