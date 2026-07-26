"""
Schema initialization module for the PET Application.
Orchestrates the creation of tables, views, and runs migrations.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database.schema_definitions import lookup_tables, core_tables, views
from src.core.database.migrations import run_migrations

logger = logging.getLogger(__name__)


def initialize_schema(db):
    """Creates tables and views if they don't exist.

    Args:
        db (QSqlDatabase): The database connection.
    """
    query = QSqlQuery(db)

    # --- 1. Schema Migrations ---
    run_migrations(db)

    # --- 2. Lookup Tables ---
    # --- 3. Core Tables ---
    # --- 4. View Definitions ---
    all_statements = lookup_tables + core_tables + views
    for sql in all_statements:
        if not query.exec(sql):
            _log_sql_error(query, sql)
            raise RuntimeError(f"Database schema initialization failed: {query.lastError().text()}")

    logger.info("Database schema initialized successfully")


def _log_sql_error(query, sql):
    err = query.lastError().text()
    logger.error(f"SQL Error: {err}\nStatement: {sql[:150]}...")
