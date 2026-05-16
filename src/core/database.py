"""
Database management module for the PET Application.
Handles SQLite connection lifecycle, PRAGMA settings, and schema/view initialization.
"""

import logging
import os # Keep os for os.makedirs, though Path.mkdir is preferred
import shutil
from PyQt5.QtSql import QSqlDatabase, QSqlQuery, QSqlError
from PyQt5.QtCore import QStandardPaths # Added for user-writable paths
import src.config as config
from src.core.backup_manager import list_backups

logger = logging.getLogger(__name__)

# Guard to ensure we don't repeatedly run schema/view init + migrations
# during the app lifetime.
_SCHEMA_INITIALIZED = False


def get_user_db_path() -> "config.Path":
    """Return the user-writable DB path (and initialize it if needed)."""
    # Keep all code paths consistent: config.USER_DB_PATH is the single source of truth.
    if config.USER_DB_PATH is None:
        config.USER_DB_PATH = config.APP_DATA_ROOT / "Database.db"

        if not config.USER_DB_PATH.exists():
            # Check for existing backups before creating a fresh one
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
        db.setDatabaseName(str(db_path)) # Use the user-writable path
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
            _initialize_schema(db)
            _SCHEMA_INITIALIZED = True

        # SQLite performance-oriented PRAGMAs
        # Note: QSqlQuery is cheap here; these run once with the connection.
        query.exec("PRAGMA journal_mode = WAL;")
        query.exec("PRAGMA synchronous = NORMAL;")
        query.exec("PRAGMA temp_store = MEMORY;")
        query.exec("PRAGMA cache_size = -2000;")


    return QSqlDatabase.database("clinic_connection")


def _initialize_schema(db):
    """Creates tables and views if they don't exist.
    
    Args:
        db (QSqlDatabase): The database connection.
    """
    query = QSqlQuery(db)
    
    # --- 1. Schema Migrations ---
    _run_migrations(db)

    # --- 2. Table Definitions ---
    tables = [
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_name TEXT NOT NULL,
            phone_number TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_name TEXT NOT NULL,
            species TEXT,
            breed TEXT,
            gender TEXT,
            age_months INTEGER,
            weight REAL,
            client_id INTEGER,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_date TEXT NOT NULL,
            diagnosis TEXT,
            is_consult INTEGER DEFAULT 0,
            notes TEXT,
            receipt_id INTEGER,
            client_id INTEGER,
            pet_id INTEGER,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
            FOREIGN KEY(pet_id) REFERENCES pets(id) ON DELETE CASCADE,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_date TEXT NOT NULL,
            service TEXT,
            status TEXT,
            notes TEXT, 
            client_id INTEGER NOT NULL,
            pet_id INTEGER,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
            FOREIGN KEY(pet_id) REFERENCES pets(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS supplies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            category TEXT,
            sub_category TEXT,
            purchase_date TEXT,
            expiry_date TEXT,
            buy_price REAL DEFAULT 0.0,
            sell_price REAL DEFAULT 0.0,
            quantity INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 0,
            supplier TEXT,
            receipt_id INTEGER,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_id INTEGER,
            client_id INTEGER,
            receipt_date TEXT NOT NULL,
            total_amount REAL DEFAULT 0.0,
            receipt_type TEXT DEFAULT 'Sale',
            notes TEXT,
            FOREIGN KEY(visit_id) REFERENCES visits(id) ON DELETE SET NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER,
            item_id INTEGER,
            item_name TEXT NOT NULL,
            category TEXT,
            quantity INTEGER DEFAULT 1,
            unit_price REAL DEFAULT 0.0,
            total_price REAL DEFAULT 0.0,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE CASCADE,
            FOREIGN KEY(item_id) REFERENCES supplies(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS supply_reorder_levels (
            item_name TEXT PRIMARY KEY,
            level INTEGER DEFAULT 0
        )
        """
    ]

    # --- 3. View Definitions ---
    views = [
        "DROP VIEW IF EXISTS v_receipt_items",
        "DROP VIEW IF EXISTS home_clients",
        """
        CREATE VIEW IF NOT EXISTS v_receipt_items AS
        SELECT 
            ri.id, r.receipt_date, ri.item_name, ri.category, ri.quantity, 
            ri.unit_price, ri.total_price, r.total_amount, r.id as receipt_id, 
            r.receipt_type, r.notes
        FROM receipt_items ri
        JOIN receipts r ON ri.receipt_id = r.id
        """,
        """
        CREATE VIEW IF NOT EXISTS home_clients AS
        SELECT 
            v.id as visit_id, c.id as client_id, c.owner_name, c.phone_number,
            p.pet_name, p.species, p.breed, p.gender, p.age_months, p.weight,
            v.visit_date, v.diagnosis, v.is_consult, v.notes, v.receipt_id
        FROM visits v
        JOIN clients c ON v.client_id = c.id
        LEFT JOIN pets p ON v.pet_id = p.id
        """
    ]
    
    for sql in tables + views:
        if not query.exec(sql):
            _log_sql_error(query, sql)
            # Fail fast if critical schema components cannot be created.
            # This prevents the app from running with a "messed up" model.
            raise RuntimeError(f"Database schema initialization failed: {query.lastError().text()}")

def _run_migrations(db):
    """Handles incremental schema updates + performance indexes."""
    query = QSqlQuery(db)

    # --- Performance indexes (safe on existing DBs) ---
    # These indexes target the main dashboard analytics queries.
    # (SQLite ignores duplicates when using IF NOT EXISTS.)
    index_statements = [
        # visits: date filtering + joins
        "CREATE INDEX IF NOT EXISTS idx_visits_visit_date ON visits(visit_date)",
        "CREATE INDEX IF NOT EXISTS idx_visits_client_id ON visits(client_id)",
        "CREATE INDEX IF NOT EXISTS idx_visits_pet_id ON visits(pet_id)",

        # appointments: upcoming/previous queries
        "CREATE INDEX IF NOT EXISTS idx_appointments_appointment_date ON appointments(appointment_date)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_client_id ON appointments(client_id)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_pet_id ON appointments(pet_id)",

        # receipts: receipt_type filtering + date + joins
        "CREATE INDEX IF NOT EXISTS idx_receipts_receipt_type ON receipts(receipt_type)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_receipt_date ON receipts(receipt_date)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_visit_id ON receipts(visit_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_client_id ON receipts(client_id)",

        # receipt_items: join + category + item_name
        "CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id ON receipt_items(receipt_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_items_item_id ON receipt_items(item_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_items_category ON receipt_items(category)",
        "CREATE INDEX IF NOT EXISTS idx_receipt_items_item_name ON receipt_items(item_name)",

        # supplies: category/subcategory/expiry + reorder join
        "CREATE INDEX IF NOT EXISTS idx_supplies_category ON supplies(category)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_sub_category ON supplies(sub_category)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_expiry_date ON supplies(expiry_date)",
        "CREATE INDEX IF NOT EXISTS idx_supplies_item_name ON supplies(item_name)",

        # reorder levels uses item_name join
        "CREATE INDEX IF NOT EXISTS idx_supply_reorder_levels_item_name ON supply_reorder_levels(item_name)",

        # pets: species filtering
        "CREATE INDEX IF NOT EXISTS idx_pets_species ON pets(species)",
        "CREATE INDEX IF NOT EXISTS idx_pets_client_id ON pets(client_id)",
    ]

    for stmt in index_statements:
        try:
            query.exec(stmt)
        except Exception:
            # QSqlQuery.lastError can be unreliable to fetch inside broad excepts,
            # but we keep startup resilient.
            pass

    # Migration: Add client_id to visits if missing (Legacy Support)
    if query.exec("PRAGMA table_info(visits)"):

        cols = []
        while query.next():
            cols.append(query.value(1))
        
        if 'client_id' not in cols:
            logger.info("Migrating database: Adding client_id to visits...")
            if query.exec("ALTER TABLE visits ADD COLUMN client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE"):
                # Backfill
                query.exec("UPDATE visits SET client_id = (SELECT client_id FROM pets WHERE pets.id = visits.pet_id)")
            else:
                _log_sql_error(query, "ALTER TABLE visits")

def _log_sql_error(query, sql):
    err = query.lastError().text()
    logger.error(f"SQL Error: {err}\nStatement: {sql[:150]}...")