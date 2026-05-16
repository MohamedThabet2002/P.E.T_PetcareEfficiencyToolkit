"""
Schema initialization module for the PET Application.
Orchestrates the creation of tables, views, and runs migrations.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database.schema_definitions import lookup_tables, core_tables, views
from src.core.database.migrations import run_migrations
from src.core.database.legacy_migration import archive_legacy_tables

logger = logging.getLogger(__name__)


def initialize_schema(db):
    """Creates tables and views if they don't exist.

    Ordering is important:
        1. Lookup tables, core tables, and views are created FIRST so that
           incremental migrations (ALTER TABLE ADD COLUMN, backfills, etc.)
           have valid tables/columns to operate on.
        2. Migrations run ONCE after the base schema exists. The
           schema_migrations table records applied versions, so calling
           initialize_schema again (e.g. on a restored/upgraded database)
           will not re-run already-applied DDL.

    Args:
        db (QSqlDatabase): The database connection.
    """
    query = QSqlQuery(db)

    # --- 0. Archive a genuine v1.0.0 schema first ---
    # The new tables are created with CREATE TABLE IF NOT EXISTS, so a legacy
    # `pets`/`visits`/... would survive and block the new shape. Copy them to
    # `_legacy_*` and drop the originals so step 1 creates fresh tables; the
    # migration then reads the copies. No-op on fresh/already-migrated DBs.
    archive_legacy_tables(db)

    # --- 1. Create base schema: lookup tables, core tables, views ---
    all_statements = lookup_tables + core_tables + views
    for sql in all_statements:
        if not query.exec(sql):
            _log_sql_error(query, sql)
            raise RuntimeError(f"Database schema initialization failed: {query.lastError().text()}")
    # Release the last DDL statement; an active statement on this connection
    # blocks the DROP TABLE cleanup in the legacy migration.
    query.finish()

    # --- 2. Incremental migrations (once, after base tables exist) ---
    run_migrations(db)

    logger.info("Database schema initialized successfully")


def _log_sql_error(query, sql):
    err = query.lastError().text()
    logger.error(f"SQL Error: {err}\nStatement: {sql[:150]}...")
