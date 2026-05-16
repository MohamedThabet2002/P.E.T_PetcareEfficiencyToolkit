"""Tests for the legacy-schema data migration remapping.

The migration targets a hybrid database: the new-schema tables exist, and the
legacy source columns/rows coexist in them (the historical state an old install
settled into). It must remap every reference through old->new id maps instead of
guessing ids (owner ids, pet ids on appointments, visit/client ids on receipts,
and the supplies `quantity` column instead of `sell_price`).
"""

import tempfile
import uuid
from pathlib import Path

import pytest
from PyQt5.QtSql import QSqlDatabase, QSqlQuery

from src.core.database.legacy_migration import migrate_from_legacy
from src.core.database.schema_initializer import initialize_schema
from src.core.database.seed_data import populate_default_lookup_data


# Legacy source columns that the new-shaped tables do NOT have. Added to the
# new tables so they can carry the legacy rows the migration reads.
LEGACY_ALT_COLUMNS = [
    "ALTER TABLE pets ADD COLUMN id INTEGER",
    "ALTER TABLE pets ADD COLUMN client_id INTEGER",
    "ALTER TABLE pets ADD COLUMN species TEXT",
    "ALTER TABLE pets ADD COLUMN breed TEXT",
    "ALTER TABLE pets ADD COLUMN age_months INTEGER",
    "ALTER TABLE pets ADD COLUMN weight REAL",
    "ALTER TABLE visits ADD COLUMN id INTEGER",
    "ALTER TABLE visits ADD COLUMN client_id INTEGER",
    "ALTER TABLE visits ADD COLUMN receipt_id INTEGER",
    "ALTER TABLE appointments ADD COLUMN id INTEGER",
    "ALTER TABLE appointments ADD COLUMN client_id INTEGER",
    "ALTER TABLE supplies ADD COLUMN id INTEGER",
    "ALTER TABLE supplies ADD COLUMN quantity INTEGER DEFAULT 0",
    "ALTER TABLE supplies ADD COLUMN supplier TEXT",
    "ALTER TABLE supplies ADD COLUMN purchase_date TEXT",
    "ALTER TABLE receipts ADD COLUMN id INTEGER",
    "ALTER TABLE receipts ADD COLUMN client_id INTEGER",
    "ALTER TABLE receipts ADD COLUMN total_amount REAL DEFAULT 0.0",
    "ALTER TABLE receipts ADD COLUMN receipt_type TEXT DEFAULT 'Sale'",
    # NOTE: no `notes` ALTER here - `receipts.notes` is part of the current
    # schema (migration 018), so the legacy column no longer has to be faked.
]

LEGACY_ONLY_TABLES = [
    "CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "owner_name TEXT NOT NULL, phone_number TEXT)",
    "CREATE TABLE receipt_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "receipt_id INTEGER, item_id INTEGER, item_name TEXT NOT NULL, category TEXT, "
    "quantity INTEGER DEFAULT 1, unit_price REAL DEFAULT 0.0, total_price REAL DEFAULT 0.0)",
]


@pytest.fixture
def legacy_db():
    """A hybrid database: new schema + legacy source columns/rows co-existing.

    Yields (db, exec) where exec(sql, values=()) runs a statement and the
    database uses the legacy migration's real connection semantics.
    """
    test_dir = Path(tempfile.mkdtemp(prefix="pet_legacy_db_"))
    db_path = test_dir / "test_database.db"
    conn_name = f"pytest_legacy_conn_{uuid.uuid4().hex[:8]}"

    db = QSqlDatabase.addDatabase("QSQLITE", conn_name)
    db.setDatabaseName(str(db_path))
    assert db.open(), f"Could not open test database: {db.lastError().text()}"

    # Legacy rows intentionally violate new NOT NULL/FKs, so build with FK
    # enforcement off (real migration also tolerates this).
    q = QSqlQuery(db)
    q.exec("PRAGMA foreign_keys = OFF;")
    q.exec("PRAGMA journal_mode = MEMORY;")
    q.finish()

    initialize_schema(db)
    populate_default_lookup_data(db)

    for sql in LEGACY_ONLY_TABLES + LEGACY_ALT_COLUMNS:
        qq = QSqlQuery(db)
        assert qq.exec(sql), f"setup failed: {sql}: {qq.lastError().text()}"

    def exec_sql(sql, values=()):
        qq = QSqlQuery(db)
        qq.prepare(sql)
        for v in values:
            qq.addBindValue(v)
        assert qq.exec(), f"failed: {sql}: {qq.lastError().text()}"
        return qq

    def one(sql, values=()):
        qq = exec_sql(sql, values)
        assert qq.next(), f"no row for: {sql} {list(values)}"
        return qq.value(0)

    _seed_legacy(exec_sql)

    yield db, exec_sql, one

    db.close()
    if QSqlDatabase.contains(conn_name):
        QSqlDatabase.removeDatabase(conn_name)


def _seed_legacy(exec_sql):
    """Insert a realistic legacy dataset (ids deliberately non-contiguous)."""
    exec_sql("INSERT INTO clients (id, owner_name, phone_number) VALUES (7, 'Legacy Owner', '0501111111')")
    exec_sql("INSERT INTO pets (pet_id, id, owner_id, client_id, pet_name, species, age_months, weight) "
             "VALUES (500, 8, 1, 7, 'Rex', 'Dog', 24, 25.0)")
    exec_sql("INSERT INTO pets (pet_id, id, owner_id, client_id, pet_name, species, age_months, weight) "
             "VALUES (501, 9, 1, 7, 'Milo', 'Cat', 12, 4.0)")
    exec_sql("INSERT INTO visits (visit_id, id, client_id, pet_id, visit_date, diagnosis) "
             "VALUES (600, 10, 7, 8, '2025-01-05', 'Check')")
    exec_sql("INSERT INTO appointments (appointment_id, id, client_id, pet_id, appointment_date, service, status) "
             "VALUES (700, 11, 7, 9, '2025-02-01', 'Vaccine', 'Pending')")
    exec_sql("INSERT INTO receipts (receipt_id, id, visit_id, client_id, receipt_date, total_amount, receipt_type) "
             "VALUES (800, 12, 10, 7, '2025-01-05', 30.0, 'Sale')")
    exec_sql("INSERT INTO receipt_items (id, receipt_id, item_name, quantity, total_price) "
             "VALUES (13, 12, 'Consult', 1, 30.0)")
    exec_sql("INSERT INTO supplies (supply_id, id, item_name, category, sub_category, buy_price, sell_price, "
             "quantity, purchase_date) "
             "VALUES (900, 14, 'Syringe', 'Tool', 'Needle', 1.0, 2.5, 100, '2025-01-02')")


class TestLegacyRemapping:
    def test_migrated_rows_keep_owner_links(self, legacy_db):
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)

        # New owner created (id != legacy 7) with phone contact attached.
        new_owner = one("SELECT owner_id FROM owners "
                        "WHERE first_name = 'Legacy' AND last_name = 'Owner'")
        assert new_owner != 7
        assert one("SELECT COUNT(*) FROM entity_contacts ec JOIN contacts c "
                   "ON c.contact_id = ec.contact_id "
                   "WHERE ec.entity_type='owner' AND ec.entity_id=? "
                   "AND c.phone_number='0501111111'", (new_owner,)) == 1
        # Both pets re-created under the new owner (2 new + 2 placeholder).
        assert one("SELECT COUNT(*) FROM pets WHERE owner_id=? AND id IS NULL", (new_owner,)) == 2

    def test_appointment_pet_remap(self, legacy_db):
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)

        # The appointment that referenced legacy pet 9 must point to the NEW
        # re-created pet row, not the stale legacy id.
        new_owner = one("SELECT owner_id FROM owners "
                        "WHERE first_name = 'Legacy' AND last_name = 'Owner'")
        milo = one("SELECT pet_id FROM pets WHERE pet_name='Milo' AND owner_id=? AND id IS NULL", (new_owner,))
        assert milo != 9
        assert one("SELECT pet_id FROM appointments "
                   "WHERE appointment_date='2025-02-01' AND id IS NULL") == milo

    def test_receipt_owner_and_visit_remap(self, legacy_db):
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)

        # The receipt's client/visit must map through the old->new tables, NOT
        # be guessed (old code took the globally-latest visit).
        new_owner = one("SELECT owner_id FROM owners "
                        "WHERE first_name = 'Legacy' AND last_name = 'Owner'")
        new_visit = one("SELECT visit_id FROM visits "
                        "WHERE visit_date='2025-01-05' AND id IS NULL")
        assert one("SELECT owner_id FROM receipts WHERE total_price=30.0") == new_owner
        assert one("SELECT visit_id FROM receipts WHERE total_price=30.0") == new_visit
        # Receipt item migrated into receipt_other.
        assert one("SELECT COUNT(*) FROM receipt_other WHERE amount=30.0") == 1

    def test_supplies_quantity_maps_to_current_stock(self, legacy_db):
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)

        # Legacy 'quantity' (100) feeds current_stock, NOT sell_price (2.5).
        assert one("SELECT current_stock FROM supplies WHERE item_name='Syringe' AND id IS NULL") == 100
        # Stock batch row records the same quantity.
        assert one("SELECT quantity FROM stocks WHERE supply_id=("
                   "SELECT supply_id FROM supplies WHERE item_name='Syringe' AND id IS NULL)") == 100

    def test_supplies_migration_terminates(self, legacy_db):
        """Regression: re-migrating the same rows must not loop forever.

        The supplies block used to iterate the very table it inserts into, so a
        successful insert re-fed the SELECT and duplicated rows endlessly.
        """
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)
        # The legacy + re-created rows must be finite.
        assert one("SELECT COUNT(*) FROM supplies WHERE item_name='Syringe'") == 2

    def test_legacy_only_tables_dropped(self, legacy_db):
        db, exec_sql, one = legacy_db
        migrate_from_legacy(db)

        q = QSqlQuery(db)
        assert q.exec("SELECT name FROM sqlite_master "
                      "WHERE type='table' AND name IN ('clients', 'receipt_items')")
        assert q.next() is False


class TestVisitsRebuildKeepsViews:
    """Rebuilding `visits` must not leave its dependent views missing.

    `_rebuild_visits_without_client_id` drops v_visit_details /
    v_receipt_summary / v_home_records before swapping the table. That runs
    *after* `initialize_schema` has already created the views, so unless the
    rebuild recreates them the whole session runs with the views gone (billing
    and the home records break until the next launch).
    """

    def test_views_survive_the_rebuild(self, legacy_db):
        db, exec_sql, one = legacy_db

        # The real startup sequence: detect the stale `client_id`, migrate the
        # legacy rows, then rebuild `visits`.
        initialize_schema(db)

        cols = QSqlQuery(db)
        cols.exec("PRAGMA table_info(visits)")
        names = set()
        while cols.next():
            names.add(cols.value(1))
        cols.finish()
        assert "client_id" not in names, "the stale column should be gone"

        for view in ("v_visit_details", "v_receipt_summary", "v_home_records"):
            assert one("SELECT COUNT(*) FROM sqlite_master "
                       "WHERE type='view' AND name=?", (view,)) == 1, view

        # They must actually be queryable (no missing table/column errors).
        assert one("SELECT COUNT(*) FROM v_receipt_summary") >= 0
        assert one("SELECT COUNT(*) FROM v_visit_details") >= 0
        assert one("SELECT COUNT(*) FROM v_home_records") >= 0


# The exact v1.0.0 schema (src/core/database.py at tag v1.0.0). A real v1.0.0
# install has ONLY these legacy tables - none of the v2 tables exist yet. This
# is what an in-place upgrade actually opens.
V1_TABLES = [
    "CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "owner_name TEXT NOT NULL, phone_number TEXT)",
    "CREATE TABLE IF NOT EXISTS pets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "pet_name TEXT NOT NULL, species TEXT, breed TEXT, gender TEXT, "
    "age_months INTEGER, weight REAL, client_id INTEGER)",
    "CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "visit_date TEXT NOT NULL, diagnosis TEXT, is_consult INTEGER DEFAULT 0, "
    "notes TEXT, receipt_id INTEGER, client_id INTEGER, pet_id INTEGER)",
    "CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "appointment_date TEXT NOT NULL, service TEXT, status TEXT, notes TEXT, "
    "client_id INTEGER NOT NULL, pet_id INTEGER)",
    "CREATE TABLE IF NOT EXISTS supplies (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "item_name TEXT NOT NULL, category TEXT, sub_category TEXT, purchase_date TEXT, "
    "expiry_date TEXT, buy_price REAL DEFAULT 0.0, sell_price REAL DEFAULT 0.0, "
    "quantity INTEGER DEFAULT 0, reorder_level INTEGER DEFAULT 0, supplier TEXT, "
    "receipt_id INTEGER)",
    "CREATE TABLE IF NOT EXISTS receipts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "visit_id INTEGER, client_id INTEGER, receipt_date TEXT NOT NULL, "
    "total_amount REAL DEFAULT 0.0, receipt_type TEXT DEFAULT 'Sale', notes TEXT)",
    "CREATE TABLE IF NOT EXISTS receipt_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "receipt_id INTEGER, item_id INTEGER, item_name TEXT NOT NULL, category TEXT, "
    "quantity INTEGER DEFAULT 1, unit_price REAL DEFAULT 0.0, total_price REAL DEFAULT 0.0)",
    "CREATE TABLE IF NOT EXISTS supply_reorder_levels (item_name TEXT PRIMARY KEY, "
    "level INTEGER DEFAULT 0)",
]

V1_LEGACY_TABLES = [
    "clients",
    "receipt_items",
    "supply_reorder_levels",
    "_legacy_pets",
    "_legacy_visits",
    "_legacy_appointments",
    "_legacy_supplies",
    "_legacy_receipts",
]


@pytest.fixture
def pure_v1_db():
    """A genuine v1.0.0 database: only the old tables exist, no v2 schema.

    This is the real upgrade path (an installed v1.0.0 Database.db opened by
    v2). It used to crash because CREATE TABLE IF NOT EXISTS left the old-shaped
    tables in place and every migration INSERT silently mismatched columns.
    """
    test_dir = Path(tempfile.mkdtemp(prefix="pet_v1_db_"))
    db_path = test_dir / "Database.db"
    conn_name = f"pytest_v1_conn_{uuid.uuid4().hex[:8]}"

    db = QSqlDatabase.addDatabase("QSQLITE", conn_name)
    db.setDatabaseName(str(db_path))
    assert db.open(), f"Could not open test database: {db.lastError().text()}"

    q = QSqlQuery(db)
    q.exec("PRAGMA foreign_keys = OFF;")
    q.exec("PRAGMA journal_mode = MEMORY;")
    for sql in V1_TABLES:
        assert q.exec(sql), f"v1 setup failed: {sql}: {q.lastError().text()}"

    # Two receipts of the SAME legacy type ("Sale") prove the old
    # receipt_type-derived code cannot collide on the UNIQUE receipt_code.
    seed = [
        "INSERT INTO clients (id, owner_name, phone_number) VALUES (1, 'John Doe', '0500000000')",
        "INSERT INTO pets (id, pet_name, species, gender, age_months, weight, client_id) "
        "VALUES (1, 'Rex', 'Dog', 'Male', 12, 10.5, 1)",
        "INSERT INTO pets (id, pet_name, species, gender, age_months, weight, client_id) "
        "VALUES (2, 'Milo', 'Cat', 'Female', 6, 4.0, 1)",
        "INSERT INTO visits (id, visit_date, diagnosis, pet_id, client_id) "
        "VALUES (1, '2025-01-05', 'Check', 1, 1)",
        "INSERT INTO appointments (id, appointment_date, service, status, client_id, pet_id) "
        "VALUES (1, '2025-02-01', 'Vaccine', 'Pending', 1, 2)",
        "INSERT INTO supplies (id, item_name, category, sub_category, purchase_date, "
        "buy_price, sell_price, quantity, reorder_level, supplier) "
        "VALUES (1, 'Syringe', 'Tool', 'Needle', '2025-01-02', 1.0, 2.5, 100, 10, 'Acme')",
        "INSERT INTO receipts (id, visit_id, client_id, receipt_date, total_amount, receipt_type) "
        "VALUES (1, 1, 1, '2025-01-05', 30.0, 'Sale')",
        "INSERT INTO receipts (id, visit_id, client_id, receipt_date, total_amount, receipt_type) "
        "VALUES (2, NULL, NULL, '2025-01-06', 15.0, 'Sale')",
        "INSERT INTO receipt_items (id, receipt_id, item_name, quantity, total_price) "
        "VALUES (1, 1, 'Consult', 1, 30.0)",
    ]
    for sql in seed:
        assert q.exec(sql), f"v1 seed failed: {sql}: {q.lastError().text()}"
    q.finish()

    yield db, conn_name

    db.close()
    if QSqlDatabase.contains(conn_name):
        QSqlDatabase.removeDatabase(conn_name)


class TestPureLegacyUpgrade:
    def _upgrade(self, db):
        # The real startup sequence; must not raise.
        initialize_schema(db)
        populate_default_lookup_data(db)

    def _one(self, db, sql, values=()):
        q = QSqlQuery(db)
        q.prepare(sql)
        for v in values:
            q.addBindValue(v)
        assert q.exec(), f"failed: {sql}: {q.lastError().text()}"
        assert q.next(), f"no row for: {sql} {list(values)}"
        val = q.value(0)
        q.finish()
        return val

    def test_upgrade_completes_without_error(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)  # raises if the upgrade regresses

    def test_legacy_tables_are_removed(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)
        for table in V1_LEGACY_TABLES:
            assert self._one(
                db,
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ) == 0, f"{table} should have been dropped"

    def test_data_is_preserved_and_new_shaped(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)

        assert self._one(db, "SELECT COUNT(*) FROM owners") == 1
        assert self._one(db, "SELECT COUNT(*) FROM pets") == 2
        assert self._one(db, "SELECT COUNT(*) FROM contacts") == 1
        assert self._one(db, "SELECT COUNT(*) FROM visits") == 1
        assert self._one(db, "SELECT COUNT(*) FROM appointments") == 1
        assert self._one(db, "SELECT COUNT(*) FROM supplies") == 1
        assert self._one(db, "SELECT COUNT(*) FROM receipt_other") == 1

        # New columns exist (old-shaped tables would not have them).
        for table, column in [
            ("pets", "pet_id"),
            ("pets", "owner_id"),
            ("visits", "visit_id"),
            ("supplies", "current_stock"),
            ("receipts", "receipt_code"),
            ("receipts", "receipt_kind"),
        ]:
            assert self._one(
                db,
                "SELECT COUNT(*) FROM pragma_table_info(?) WHERE name=?",
                (table, column),
            ) == 1, f"{table}.{column} missing"

        # Legacy 'quantity' fed current_stock, not sell_price.
        assert self._one(db, "SELECT current_stock FROM supplies WHERE item_name='Syringe'") == 100

    def test_receipt_codes_are_unique(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)

        # Both legacy "Sale" receipts migrated (no UNIQUE collision).
        assert self._one(db, "SELECT COUNT(*) FROM receipts") == 2
        assert self._one(db, "SELECT COUNT(DISTINCT receipt_code) FROM receipts") == 2
        # A visit-linked one is 'visit', the standalone one is 'retail'.
        kinds = set()
        q = QSqlQuery(db)
        q.exec("SELECT receipt_kind FROM receipts")
        while q.next():
            kinds.add(q.value(0))
        q.finish()
        assert kinds == {"visit", "retail"}

    def test_visits_reference_their_own_pet(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)

        # The visit referenced legacy pet 1 ('Rex'); after remap it must point
        # to the migrated Rex row, not the owner's first pet by luck.
        rex = self._one(db, "SELECT pet_id FROM pets WHERE pet_name='Rex'")
        assert self._one(db, "SELECT pet_id FROM visits WHERE visit_date='2025-01-05'") == rex

    def test_views_are_queryable(self, pure_v1_db):
        db, _ = pure_v1_db
        self._upgrade(db)
        # The view emits one row per line item; the visit receipt carries the
        # migrated 'Consult' line (the standalone retail receipt has no lines).
        assert self._one(db, "SELECT COUNT(*) FROM v_receipt_summary WHERE receipt_kind='visit'") == 1
        assert self._one(db, "SELECT COUNT(*) FROM v_visit_details") == 1