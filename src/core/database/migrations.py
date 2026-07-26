"""
Migrations module for the PET Application.
Handles incremental schema updates, performance indexes, and migration triggers.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database.legacy_migration import migrate_from_legacy
from src.core.database.seed_data import populate_default_lookup_data

logger = logging.getLogger(__name__)


def run_migrations(db):
    """Handles incremental schema updates + performance indexes."""
    query = QSqlQuery(db)

    # --- Performance indexes ---
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_visits_visit_date ON visits(visit_date)",
        "CREATE INDEX IF NOT EXISTS idx_visits_pet_id ON visits(pet_id)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_appointment_date ON appointments(appointment_date)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_pet_id ON appointments(pet_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_receipt_date ON receipts(receipt_date)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_visit_id ON receipts(visit_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_owner_id ON receipts(owner_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_supplies_receipt_id ON receipt_supplies(receipt_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_services_receipt_id ON receipt_services(receipt_id)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_category ON supplies(category)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_sub_category ON supplies(sub_category)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_expiry_date ON supplies(expiry_date)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_item_name ON supplies(item_name)",
        "CREATE INDEX IF NOT EXISTS idx_pets_owner_id ON pets(owner_id)",
        "CREATE INDEX IF NOT EXISTS idx_pets_species_id ON pets(species_id)",
        "CREATE INDEX IF NOT EXISTS idx_stocks_supply_id ON stocks(supply_id)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_supply_id ON stock_movements(supply_id)",
        "CREATE INDEX IF NOT EXISTS idx_entity_contacts_entity ON entity_contacts(entity_type, entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_logs_entity ON logs(entity_type, entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_change_header_table ON change_header(table_name, record_id)",
        "CREATE INDEX IF NOT EXISTS idx_followups_visit_id ON followups(visit_id)",
        "CREATE INDEX IF NOT EXISTS idx_health_stats_pet_id ON health_stats(pet_id)",
        "CREATE INDEX IF NOT EXISTS idx_medications_visit_id ON medications(visit_id)",
    ]

    for stmt in index_statements:
        try:
            query.exec(stmt)
        except Exception:
            pass

    # --- Schema versioning: Record this migration version ---
    _record_migration(db, "001_initial_schema")

    # --- PHASE 2: Add quantity and unit_price to receipt_other ---
    _add_column_if_not_exists(db, "receipt_other", "quantity", "INTEGER DEFAULT 1")
    _add_column_if_not_exists(db, "receipt_other", "unit_price", "REAL")
    _record_migration(db, "002_receipt_other_columns")

    # --- PHASE 3: Add item_type discriminator to package_items ---
    _add_column_if_not_exists(db, "package_items", "item_type", "TEXT")
    # Backfill existing rows: set item_type based on which FK is non-null
    _backfill_package_item_type(db)
    _record_migration(db, "003_package_item_type")

    # --- Add created_at/updated_at columns to existing tables ---
    # Note: SQLite ALTER TABLE ADD COLUMN requires constant defaults.
    # CURRENT_TIMESTAMP is not a constant, so we add without default
    # and existing rows will have NULL (which we backfill later).
    _add_column_if_not_exists(db, "owners", "created_at", "TEXT")
    _add_column_if_not_exists(db, "owners", "updated_at", "TEXT")
    _add_column_if_not_exists(db, "pets", "created_at", "TEXT")
    _add_column_if_not_exists(db, "pets", "updated_at", "TEXT")
    _add_column_if_not_exists(db, "appointments", "created_at", "TEXT")
    _add_column_if_not_exists(db, "appointments", "updated_at", "TEXT")
    _add_column_if_not_exists(db, "visits", "created_at", "TEXT")
    _add_column_if_not_exists(db, "visits", "updated_at", "TEXT")
    _add_column_if_not_exists(db, "supplies", "created_at", "TEXT")
    _add_column_if_not_exists(db, "supplies", "updated_at", "TEXT")
    _add_column_if_not_exists(db, "receipts", "created_at", "TEXT")
    # Backfill created_at for existing rows that have a date column we can use
    _backfill_created_at(db, "owners", "NULL")
    _backfill_created_at(db, "pets", "NULL")
    _backfill_created_at(db, "appointments", "appointment_date")
    _backfill_created_at(db, "visits", "visit_date")
    _backfill_created_at(db, "supplies", "NULL")
    _backfill_created_at(db, "receipts", "receipt_date")

    # --- Create doctors table if not exists ---
    query.exec("""
        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            specialization TEXT,
            phone TEXT,
            email TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: Check if old schema exists and migrate data
    if query.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='clients'"):
        if query.next():
            logger.info("Legacy schema detected. Running data migration...")
            migrate_from_legacy(db)

    # Migration: Check for species data and populate defaults
    if query.exec("SELECT COUNT(*) FROM species_lookup"):
        if query.next() and query.value(0) == 0:
            populate_default_lookup_data(db)

    # Migration: Seed categories from existing supplies if categories table is empty
    if query.exec("SELECT COUNT(*) FROM categories"):
        if query.next() and query.value(0) == 0:
            query.exec("INSERT OR IGNORE INTO categories (name) SELECT DISTINCT category FROM supplies WHERE category IS NOT NULL")
            query.exec("""
                INSERT OR IGNORE INTO subcategories (category_name, sub_name)
                SELECT DISTINCT category, sub_category FROM supplies
                WHERE category IS NOT NULL AND sub_category IS NOT NULL
            """)


def _add_column_if_not_exists(db, table_name, column_name, column_def):
    """Add a column to a table if it doesn't already exist.
    
    SQLite does not support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
    so we check the table's column list first.
    """
    query = QSqlQuery(db)
    # PRAGMA table_info returns one row per column with name in column 1
    if query.exec(f"PRAGMA table_info({table_name})"):
        existing_columns = set()
        while query.next():
            existing_columns.add(query.value(1))
        if column_name not in existing_columns:
            q = QSqlQuery(db)
            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            if q.exec(sql):
                logger.info(f"Added column '{column_name}' to '{table_name}'")
            else:
                logger.warning(f"Failed to add column '{column_name}' to '{table_name}': {q.lastError().text()}")


def _record_migration(db, version):
    """Record a migration version in the schema_migrations table."""
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)")
    query.addBindValue(version)
    query.exec()


def _backfill_package_item_type(db):
    """Backfill item_type for existing package_items rows based on FK presence."""
    query = QSqlQuery(db)
    # Check if the column exists first
    if query.exec("PRAGMA table_info(package_items)"):
        columns = set()
        while query.next():
            columns.add(query.value(1))
        if "item_type" not in columns:
            return
    # Set item_type = 'service' where service_id is not null
    query.exec("UPDATE package_items SET item_type = 'service' WHERE service_id IS NOT NULL AND item_type IS NULL")
    # Set item_type = 'supply' where supply_id is not null
    query.exec("UPDATE package_items SET item_type = 'supply' WHERE supply_id IS NOT NULL AND item_type IS NULL")
    logged = QSqlQuery(db)
    logged.exec("SELECT COUNT(*) FROM package_items")
    if logged.next():
        count = logged.value(0)
        logger.info(f"Backfilled item_type for package_items. Total items: {count}")


def _backfill_created_at(db, table_name, source_column):
    """Backfill created_at for existing rows using a source date column if available.
    
    Args:
        table_name: The table to update
        source_column: Column name containing a date to use, or 'NULL' to use current timestamp
    """
    query = QSqlQuery(db)
    # Check if created_at column exists
    if query.exec(f"PRAGMA table_info({table_name})"):
        columns = set()
        while query.next():
            columns.add(query.value(1))
        if "created_at" not in columns:
            return
    # Backfill rows where created_at is NULL
    if source_column and source_column != "NULL":
        sql = f"UPDATE {table_name} SET created_at = {source_column} WHERE created_at IS NULL"
    else:
        sql = f"UPDATE {table_name} SET created_at = datetime('now', 'localtime') WHERE created_at IS NULL"
    if query.exec(sql):
        affected = query.numRowsAffected()
        if affected > 0:
            logger.info(f"Backfilled created_at for {affected} rows in '{table_name}'")
