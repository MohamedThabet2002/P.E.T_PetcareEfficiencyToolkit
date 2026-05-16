"""
Migrations module for the PET Application.
Handles incremental schema updates, performance indexes, and migration triggers.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database.legacy_migration import migrate_from_legacy
from src.core.database.schema_definitions import views as _SCHEMA_VIEWS
from src.core.database.seed_data import (
    FOLLOWUP_STATUS_RETIRED,
    FOLLOWUP_STATUS_STATES,
    ensure_lookup_states,
    populate_default_lookup_data,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Versioned migrations.
#
# Each entry is (version, callable). The runner executes every entry exactly
# once per database, in declaration order, each inside its own transaction,
# and only records the version in `schema_migrations` after the step commits.
# This is what lets a fully-initialized database skip unchanged work on every
# app startup (see connection._SCHEMA_INITIALIZED) while still upgrading old
# databases in place.
#
# NOTE: only genuinely one-time schema changes belong here. Repair/cleanup
# work that must re-check its own preconditions every startup (e.g. legacy
# schema migration) stays in the unconditional maintenance phase below.
# ---------------------------------------------------------------------------

def run_migrations(db):
    """Handles incremental schema updates + performance indexes.

    Steps are deliberately ordered into phases that mirror the original
    hand-written run order. In particular, the seed/maintenance phase MUST
    run between migration 003 and migration 004: migrations 004 and 014
    depend on the `roles` rows that ``populate_default_lookup_data`` creates.
    If 014 ran before the seed, `_mark_system_roles`/`_seed_builtin_role_permissions`
    would no-op (empty roles table) and the seed would then recreate roles with
    `is_system=0` — breaking RBAC.

    Phases:

      1. ``_apply_indexes``                            - safe every startup.
      2. ``_ensure_base_columns``                      - timestamp cols + doctors.
      3. ``_run_versioned_migrations(PRE_SEED)``       - 001-003, once each.
      4. ``_run_legacy_repair`` + ``_run_seed_maintenance``  - self-guarding.
      5. ``_run_versioned_migrations(POST_SEED)``      - 004-019, once each
                                                        (needs roles/seed).
    """
    _apply_indexes(db)
    _ensure_base_columns(db)
    _run_versioned_migrations(db, _VERSIONED_MIGRATIONS_PRE_SEED)
    _run_legacy_repair(db)
    _run_seed_maintenance(db)
    _run_versioned_migrations(db, _VERSIONED_MIGRATIONS_POST_SEED)


def pending_migration_versions(db):
    """Return the versioned migration versions not yet recorded on *db*.

    The connection layer calls this *before* ``initialize_schema`` on an
    existing database so it can take a safety backup when an upgrade is about
    to touch the schema. A missing ``schema_migrations`` table reports every
    migration as pending (it is created by ``initialize_schema``), which is the
    right answer for a database old enough to predate the migration framework.
    """
    return [
        version for version, _ in _VERSIONED_MIGRATIONS
        if not _migration_recorded(db, version)
    ]


def has_legacy_schema(db):
    """True when the pre-owners/pets ``clients`` table still exists.

    Used alongside :func:`pending_migration_versions` to decide whether an
    upgrade will rewrite data (legacy repair) and therefore deserves a backup.
    """
    query = QSqlQuery(db)
    if query.exec("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clients'"):
        return bool(query.next())
    return False


# --- PHASE 1: Performance indexes (idempotent, run every startup) -----------


def _apply_indexes(db):
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

    query = QSqlQuery(db)
    for stmt in index_statements:
        try:
            query.exec(stmt)
        except Exception:
            pass
    query.finish()


# --- PHASE 2: Base maintenance columns (idempotent, run every startup) -------


def _ensure_base_columns(db):
    """Add created_at/updated_at + the doctors table (all idempotent)."""
    query = QSqlQuery(db)

    # Add created_at/updated_at columns to existing tables
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
    _add_column_if_not_exists(
        db, "receipts", "payment_status", "TEXT NOT NULL DEFAULT 'Unpaid'"
    )
    # Backfill created_at for existing rows that have a date column we can use
    _backfill_created_at(db, "owners", "NULL")
    _backfill_created_at(db, "pets", "NULL")
    _backfill_created_at(db, "appointments", "appointment_date")
    _backfill_created_at(db, "visits", "visit_date")
    _backfill_created_at(db, "supplies", "NULL")
    _backfill_created_at(db, "receipts", "receipt_date")

    # Create doctors table if not exists
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
    query.finish()


# --- PHASE 3: Versioned migrations (once per DB, transactional) -------------


def _run_versioned_migrations(db, registry):
    """Runs each registered migration exactly once, each in its own
    transaction, recording the version only after a successful commit."""
    newly_applied = []
    for version, fn in registry:
        if _migration_recorded(db, version):
            continue
        db.transaction()
        try:
            fn(db)
            _record_migration(db, version)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Migration '%s' failed; rolled back.", version)
            raise
        newly_applied.append(version)
    if newly_applied:
        logger.info("Applied migrations: %s", ", ".join(newly_applied))


def _m_002(db):
    # PHASE 2: Add quantity and unit_price to receipt_other
    _add_column_if_not_exists(db, "receipt_other", "quantity", "INTEGER DEFAULT 1")
    _add_column_if_not_exists(db, "receipt_other", "unit_price", "REAL")


def _m_003(db):
    # PHASE 3: Add item_type discriminator to package_items
    _add_column_if_not_exists(db, "package_items", "item_type", "TEXT")
    # Backfill existing rows: set item_type based on which FK is non-null
    _backfill_package_item_type(db)


def _m_004(db):
    # Migration 004: Ensure 'doctor' role exists (added in v2.0.0)
    # Existing databases that only had 'admin' and 'staff' need this backfilled.
    _ensure_role_exists(db, "doctor")


def _m_005(db):
    # Migration 005: Add pending_changes table for approval workflow (v2.1.0)
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS pending_changes (
            pending_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            table_name   TEXT NOT NULL,
            record_id    INTEGER,
            operation    TEXT NOT NULL CHECK(operation IN ('UPDATE','INSERT','DELETE')),
            payload      TEXT,
            status       TEXT NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','approved','rejected')),
            reviewer_id  INTEGER,
            reviewed_at  TEXT,
            review_notes TEXT,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)     REFERENCES users(user_id) ON DELETE SET NULL,
            FOREIGN KEY(reviewer_id) REFERENCES users(user_id) ON DELETE SET NULL
        )
    """)


def _m_007(db):
    # Migration 007: Link authenticated users to provider records.
    _add_column_if_not_exists(db, "users", "doctor_id", "INTEGER")
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_users_doctor_id ON users(doctor_id)"
    )


def _m_008(db):
    # Migration 008: Preserve the service selected for an appointment.
    _add_column_if_not_exists(db, "appointments", "service", "TEXT")


def _m_009(db):
    # Migration 009: Track the provider responsible for a follow-up visit.
    _add_column_if_not_exists(db, "followups", "doctor_id", "INTEGER")
    QSqlQuery(db).exec(
        "UPDATE followups SET doctor_id = "
        "(SELECT doctor_id FROM visits WHERE visits.visit_id = followups.visit_id) "
        "WHERE doctor_id IS NULL"
    )
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_followups_doctor_id ON followups(doctor_id)"
    )


def _m_010(db):
    # Migration 010: Add discount (dollar amount) to receipts for sale adjustments.
    _add_column_if_not_exists(db, "receipts", "discount", "REAL DEFAULT 0")


def _m_011(db):
    # PHASE 11: Vaccine schedules and vaccination reminders
    query = QSqlQuery(db)
    query.exec("""
        CREATE TABLE IF NOT EXISTS vaccine_schedules (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            vaccine_id INTEGER NOT NULL,
            species_id INTEGER NOT NULL,
            interval_days INTEGER NOT NULL,
            notes TEXT,
            FOREIGN KEY(vaccine_id) REFERENCES vaccines_lookup(vaccine_id) ON DELETE CASCADE,
            FOREIGN KEY(species_id) REFERENCES species_lookup(species_id) ON DELETE CASCADE,
            UNIQUE(vaccine_id, species_id)
        )
    """)
    query.exec("""
        CREATE TABLE IF NOT EXISTS vaccination_reminders (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,
            vaccine_id INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','completed','skipped')),
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE,
            FOREIGN KEY(vaccine_id) REFERENCES vaccines_lookup(vaccine_id) ON DELETE CASCADE
        )
    """)
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_vaccination_reminders_pet ON vaccination_reminders(pet_id)"
    )
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_vaccination_reminders_due ON vaccination_reminders(due_date)"
    )


def _m_012(db):
    # PHASE 12: Payments table for partial/split payments
    query = QSqlQuery(db)
    query.exec("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash'
                               CHECK(payment_method IN ('Cash','Card','Bank Transfer','Other')),
            payment_date TEXT DEFAULT CURRENT_DATE,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE
        )
    """)
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_payments_receipt ON payments(receipt_id)"
    )
    _add_column_if_not_exists(db, "receipts", "payment_status", "TEXT NOT NULL DEFAULT 'Unpaid'")


def _m_013(db):
    # PHASE 13: Report archives (saved report timeline)
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS report_archives (
            archive_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            report_kind  TEXT NOT NULL,
            period_type  TEXT NOT NULL DEFAULT 'Month',
            period_start TEXT,
            period_end   TEXT,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT,
            data_json    TEXT NOT NULL
        )
    """)
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_report_archives_generated_at ON report_archives(generated_at)"
    )


def _m_014(db):
    # PHASE 14: RBAC role templates + per-user overrides
    _add_column_if_not_exists(db, "roles", "description", "TEXT")
    _add_column_if_not_exists(db, "roles", "is_system", "INTEGER NOT NULL DEFAULT 0")
    _mark_system_roles(db)
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER NOT NULL,
            permission_key TEXT NOT NULL,
            FOREIGN KEY(role_id) REFERENCES roles(role_id) ON DELETE CASCADE,
            UNIQUE(role_id, permission_key)
        )
    """)
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            permission_key TEXT NOT NULL,
            override INTEGER NOT NULL DEFAULT -1,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE(user_id, permission_key)
        )
    """)
    # Seed built-in role templates. The versioned runner guarantees this step
    # runs once per database, so admin edits are never reset on restart.
    _seed_builtin_role_permissions(db)


def _m_015(db):
    # PHASE 15: Pet notes column (editable from the pet details card)
    _add_column_if_not_exists(db, "pets", "notes", "TEXT")


def _m_016(db):
    # PHASE 16: Receipt adjustments (revision history for billing changes)
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS receipt_adjustments (
            adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            visit_id INTEGER,
            adjusted_by INTEGER,
            description TEXT,
            old_total REAL,
            new_total REAL,
            delta REAL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE,
            FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE SET NULL,
            FOREIGN KEY(adjusted_by) REFERENCES users(user_id) ON DELETE SET NULL
        )
    """)
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_receipt_adjustments_receipt ON receipt_adjustments(receipt_id)"
    )


def _m_017(db):
    # PHASE 17: Undo/redo journal — full snapshots captured before deletes,
    # restorable from the dashboard (Restore Deleted Records).
    QSqlQuery(db).exec("""
        CREATE TABLE IF NOT EXISTS deleted_records (
            deleted_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            deleted_by INTEGER,
            deleted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            restored_at TEXT,
            restored_by INTEGER,
            FOREIGN KEY(deleted_by) REFERENCES users(user_id) ON DELETE SET NULL,
            FOREIGN KEY(restored_by) REFERENCES users(user_id) ON DELETE SET NULL
        )
    """)
    QSqlQuery(db).exec(
        "CREATE INDEX IF NOT EXISTS idx_deleted_records_unrestored "
        "ON deleted_records(restored_at, deleted_at)"
    )


def _m_018(db):
    # PHASE 18: Expense category + receipt notes.
    #
    # `receipt_other.category` lets an expense line carry its own category
    # (Utilities/Rent/...) instead of the view's hardcoded 'Other', and
    # `receipts.notes` stores the free-text notes entered in the Add General
    # Expense dialog. Both were previously collected by the UI and discarded.
    #
    # v_receipt_summary is dropped and recreated from schema_definitions.views
    # on every startup (see initialize_schema), which picks up the new
    # columns; CREATE VIEW does not validate references, so it is safe for the
    # view to be recreated before these ALTERs run.
    _add_column_if_not_exists(db, "receipts", "notes", "TEXT")
    _add_column_if_not_exists(db, "receipt_other", "category", "TEXT")


def _m_019(db):
    # PHASE 19: Backfill the followup_status lookup states.
    #
    # `populate_default_lookup_data` only runs when other lookup tables are
    # empty, so a database created before a status was added to the seed list
    # never receives it. That left upgraded databases with
    # Scheduled/Completed/Missed only: the All Appointments dialog offers
    # Pending/Completed/Canceled for follow-ups, so "Pending" and "Canceled"
    # resolved to no state at all and the status combo silently did nothing.
    # (The Scheduled/Missed rows that used to be backfilled here are pruned by
    # 020_followup_status_prune.)
    ensure_lookup_states(db, "followup_status", FOLLOWUP_STATUS_STATES)


def _m_020(db):
    # PHASE 20: Drop the retired follow-up statuses.
    #
    # "Scheduled" (the original single status) and "Missed" are gone from the
    # UI, so they are removed from the lookup too. followups.state_id has no FK
    # to states_lookup, so any follow-up still pointing at one of them would
    # simply read back blank — they are first moved to Pending, which is also
    # what a missing state resolves to anyway.
    ensure_lookup_states(db, "followup_status", FOLLOWUP_STATUS_STATES)

    retired = ", ".join("?" * len(FOLLOWUP_STATUS_RETIRED))
    query = QSqlQuery(db)
    query.prepare(
        "SELECT s.state_id FROM states_lookup s "
        "JOIN categories_lookup c ON c.category_id = s.category_id "
        "WHERE c.category_name = 'followup_status' AND s.state_value IN (%s)" % retired
    )
    for state_value in FOLLOWUP_STATUS_RETIRED:
        query.addBindValue(state_value)
    state_ids = []
    if query.exec():
        while query.next():
            state_ids.append(query.value(0))
    query.finish()
    if not state_ids:
        return

    pending_id = lookup_state_id(db, "followup_status", "Pending")
    ids = ", ".join(str(int(sid)) for sid in state_ids)
    if pending_id is not None:
        remap = QSqlQuery(db)
        remap.prepare("UPDATE followups SET state_id = ? WHERE state_id IN (%s)" % ids)
        remap.addBindValue(int(pending_id))
        if not remap.exec():
            raise RuntimeError(
                "Failed to remap follow-up statuses: %s" % remap.lastError().text()
            )
        remap.finish()
        logger.info("Moved follow-ups off retired statuses onto Pending")
    prune = QSqlQuery(db)
    prune.prepare("DELETE FROM states_lookup WHERE state_id IN (%s)" % ids)
    if not prune.exec():
        raise RuntimeError(
            "Failed to remove retired follow-up statuses: %s" % prune.lastError().text()
        )
    prune.finish()
    logger.info("Removed retired follow-up statuses: %s",
                ", ".join(FOLLOWUP_STATUS_RETIRED))


def _m_021(db):
    # PHASE 21: Per-batch expiry date and buy price.
    #
    # Both used to live only on the item (supplies.expiry_date / supplies.buy_price),
    # so every batch of the same item showed identical values. They now belong to
    # the individual stock batch: two purchases of one item can carry different
    # prices and expire on different dates. Existing rows inherit the item's
    # values so upgraded databases do not show blank batches.
    _add_column_if_not_exists(db, "stocks", "expiry_date", "TEXT")
    _add_column_if_not_exists(db, "stocks", "buy_price", "REAL")

    backfill = QSqlQuery(db)
    backfill.prepare("""
        UPDATE stocks SET
            expiry_date = (SELECT s.expiry_date FROM supplies s
                           WHERE s.supply_id = stocks.supply_id)
        WHERE expiry_date IS NULL
          AND EXISTS (SELECT 1 FROM supplies s
                      WHERE s.supply_id = stocks.supply_id AND s.expiry_date IS NOT NULL)
    """)
    if not backfill.exec():
        raise RuntimeError(
            "Failed to backfill batch expiry dates: %s" % backfill.lastError().text()
        )
    backfill.finish()

    price_backfill = QSqlQuery(db)
    price_backfill.prepare("""
        UPDATE stocks SET
            buy_price = (SELECT s.buy_price FROM supplies s
                         WHERE s.supply_id = stocks.supply_id)
        WHERE buy_price IS NULL
          AND EXISTS (SELECT 1 FROM supplies s
                      WHERE s.supply_id = stocks.supply_id AND s.buy_price IS NOT NULL)
    """)
    if not price_backfill.exec():
        raise RuntimeError(
            "Failed to backfill batch buy prices: %s" % price_backfill.lastError().text()
        )
    price_backfill.finish()


def _m_022(db):
    # PHASE 22: receipts.receipt_kind - separates a receipt's business kind
    # (visit / retail / expense) from receipt_code, which is now purely its
    # unique human number. Previously the code doubled as a type discriminator
    # ("Sale"/"Expense"), so once codes became unique every query filtering
    # `receipt_code = 'Sale'` matched nothing.
    #
    # Named `receipt_kind` (not `receipt_type`) on purpose: the legacy schema
    # still has a `receipts.receipt_type` column that legacy_migration reads.
    _add_column_if_not_exists(db, "receipts", "receipt_kind", "TEXT")

    backfill = QSqlQuery(db)
    backfill.prepare("""
        UPDATE receipts SET receipt_kind = CASE
            WHEN UPPER(COALESCE(receipt_code, '')) LIKE 'EXPENSE%' THEN 'expense'
            WHEN UPPER(COALESCE(receipt_code, '')) LIKE 'RETAIL%'  THEN 'retail'
            WHEN UPPER(COALESCE(receipt_code, '')) LIKE 'VISIT%'   THEN 'visit'
            WHEN visit_id IS NOT NULL THEN 'visit'
            ELSE 'retail'
        END
        WHERE receipt_kind IS NULL OR receipt_kind = ''
    """)
    if not backfill.exec():
        raise RuntimeError(
            "Failed to backfill receipt kinds: %s" % backfill.lastError().text()
        )
    backfill.finish()


def _m_023(db):
    # PHASE 23: stocks.receipt_id - links a batch back to the expense receipt
    # that recorded its purchase. A later quantity correction is then *appended*
    # to that receipt (see sales_repo.log_stock_adjustment's receipt_id path)
    # instead of minting a fresh EXPENSE row for every edit.
    #
    # No backfill: receipts carry no batch reference either, so an existing
    # batch's purchase receipt cannot be recovered without guessing. Those rows
    # stay NULL and behave exactly as before - the first correction stands alone
    # and is then reused (stock_repo stamps it back onto the batch).
    #
    # ON DELETE SET NULL: removing the receipt from the ledger drops the link,
    # so the next correction falls back to a standalone receipt instead of
    # writing a line onto a row that no longer exists.
    _add_column_if_not_exists(
        db, "stocks", "receipt_id",
        "INTEGER REFERENCES receipts(receipt_id) ON DELETE SET NULL")


def _m_024(db):
    # PHASE 24: receipt_other.unit_price was added in 002 but never written,
    # so older expense/adjustment lines are NULL. Derive it from the amount so
    # an edit round-trip (quantity * unit_price) reproduces the original total
    # instead of collapsing to 0. quantity defaults to 1, so guard the divide.
    query = QSqlQuery(db)
    if not query.exec("""
        UPDATE receipt_other
           SET unit_price = amount / COALESCE(NULLIF(quantity, 0), 1)
         WHERE unit_price IS NULL
    """):
        raise RuntimeError(
            "Failed to derive receipt_other.unit_price: %s" % query.lastError().text()
        )
    query.finish()



def _m_025(db):
    """PHASE 025: Add normalized clinical exam tables."""
    from src.core.database import schema_definitions
    from PyQt5.QtSql import QSqlQuery

    for ddl in getattr(schema_definitions, 'clinical_exam_tables', []) or []:
        q = QSqlQuery(db)
        if not q.exec(ddl):
            raise RuntimeError(
                "Failed to create clinical exam table: %s" % q.lastError().text()
            )
        q.finish()


def _m_026(db):
    # PHASE 26: Per-pet health indicator override (empty/NULL = derive from exam).
    _add_column_if_not_exists(db, "pets", "health_status", "TEXT")


def _m_027(db):
    # PHASE 27: Supplier contact details (editable from the Suppliers dialog).
    _add_column_if_not_exists(db, "suppliers", "phone", "TEXT")
    _add_column_if_not_exists(db, "suppliers", "location", "TEXT")
    _add_column_if_not_exists(db, "suppliers", "notes", "TEXT")


def _m_028(db):
    """PHASE 28: Add newly-catalogued permissions to the built-in templates.

    Migration 014 seeds the built-in role templates once, so a permission added
    to ``PERMISSION_CATALOG`` afterwards would never reach the doctor/staff
    templates on an existing install (the admin role is lockout-proof at
    resolution time, but the others are not). This reconciles *additively*:
    only keys missing from a template are inserted, so admin edits to the
    built-in templates are preserved.
    """
    from src.core.permissions import seed_permissions_for_role

    for role_name in ("admin", "doctor", "staff"):
        get_rid = QSqlQuery(db)
        get_rid.prepare("SELECT role_id FROM roles WHERE role_name = ?")
        get_rid.addBindValue(role_name)
        found = get_rid.exec() and get_rid.next()
        role_id = get_rid.value(0) if found else None
        get_rid.finish()
        if not found:
            continue

        have_q = QSqlQuery(db)
        have_q.prepare("SELECT permission_key FROM role_permissions WHERE role_id = ?")
        have_q.addBindValue(role_id)
        existing = set()
        if have_q.exec():
            while have_q.next():
                existing.add(have_q.value(0))
        have_q.finish()

        for key in seed_permissions_for_role(role_name) - existing:
            ins = QSqlQuery(db)
            ins.prepare(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_key) "
                "VALUES (?, ?)"
            )
            ins.addBindValue(role_id)
            ins.addBindValue(key)
            ins.exec()
            ins.finish()


def lookup_state_id(db, category_name, state_value):
    """Returns the state_id of *state_value* inside a lookup category."""
    query = QSqlQuery(db)
    query.prepare(
        "SELECT s.state_id FROM states_lookup s "
        "JOIN categories_lookup c ON c.category_id = s.category_id "
        "WHERE c.category_name = ? AND s.state_value = ?"
    )
    query.addBindValue(category_name)
    query.addBindValue(state_value)
    if query.exec() and query.next():
        return query.value(0)
    return None


# Migrations that only touch schema and do not depend on seeded lookup data.
# These run before the seed/maintenance phase.
_VERSIONED_MIGRATIONS_PRE_SEED = [
    ("001_initial_schema", lambda db: None),
    ("002_receipt_other_columns", _m_002),
    ("003_package_item_type", _m_003),
]

# Migrations that run AFTER the seed/maintenance phase, because they depend on
# the `roles` rows created by `populate_default_lookup_data` (004 ensures the
# doctor role; 014 marks system roles + seeds role_permissions). Order matters.
_VERSIONED_MIGRATIONS_POST_SEED = [
    ("004_add_doctor_role", _m_004),
    ("005_pending_changes", _m_005),
    ("006_receipt_payment_status", lambda db: None),
    ("007_user_doctor_mapping", _m_007),
    ("008_appointment_service", _m_008),
    ("009_followup_doctor", _m_009),
    ("010_receipt_discount", _m_010),
    ("011_vaccine_schedules", _m_011),
    ("012_payments", _m_012),
    ("013_report_archives", _m_013),
    ("014_rbac_role_permissions", _m_014),
    ("015_pet_notes", _m_015),
    ("016_receipt_adjustments", _m_016),
    ("017_deleted_records", _m_017),
    ("018_expense_category_notes", _m_018),
    ("019_followup_status_states", _m_019),
    ("020_followup_status_prune", _m_020),
    ("021_stock_batch_expiry_buy_price", _m_021),
    ("022_receipt_kind", _m_022),
    ("023_stock_batch_receipt", _m_023),
    ("024_receipt_other_unit_price", _m_024),
    ("025_clinical_exam_data", _m_025),
    ("026_pet_health_status", _m_026),
    ("027_supplier_contact", _m_027),
    ("028_sync_builtin_role_permissions", _m_028),
]

_VERSIONED_MIGRATIONS = (
    _VERSIONED_MIGRATIONS_PRE_SEED + _VERSIONED_MIGRATIONS_POST_SEED
)


# --- PHASE 4: Conditional legacy repair + seed maintenance -------------------


def _run_legacy_repair(db):
    """Migrates from the pre-owners/pets schema and cleans up its leftovers.

    Every step below is self-guarding: it only acts when the legacy schema /
    stale artifacts are actually detected, so it is safe to run every startup
    (important: an old database may already have 001-016 recorded yet still
    contain legacy `clients` data or a dangling `client_id` on visits).
    """
    # Migration: Check if old schema exists and migrate data
    detect = QSqlQuery(db)
    has_legacy_clients = False
    if detect.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='clients'"):
        has_legacy_clients = detect.next()
    # Release the active statement on sqlite_master BEFORE any DDL: a live
    # SELECT over sqlite_master locks it, so the DROP TABLE cleanup inside
    # migrate_from_legacy fails with 'database table is locked'.
    detect.finish()
    if has_legacy_clients:
        logger.info("Legacy schema detected. Running data migration...")
        migrate_from_legacy(db)

    # Cleanup: Drop stale legacy tables that may remain after migration.
    # These old tables have broken foreign keys (referencing dropped tables/columns)
    # which cause SQLite "foreign key mismatch" errors on DELETE operations.
    # NOTE: Use a fresh QSqlQuery per statement and ensure no active queries
    # are held before performing DDL to avoid "database table is locked".
    for legacy_table in [
        "_legacy_pets",
        "_legacy_visits",
        "_legacy_appointments",
        "_legacy_supplies",
        "_legacy_receipts",
        "receipt_items",
        "clients",
        "supply_reorder_levels",
    ]:
        drop_q = QSqlQuery(db)
        if not drop_q.exec(f"DROP TABLE IF EXISTS {legacy_table}"):
            logger.warning(f"Failed to drop legacy table '{legacy_table}': {drop_q.lastError().text()}")
        else:
            logger.info(f"Cleaned up legacy table '{legacy_table}'")
        drop_q.finish()

    # Cleanup: Drop stale legacy views that reference the dropped legacy tables
    # (e.g. 'clients', 'receipt_items'). These would error on any query and can
    # interfere with schema/query behavior.
    for legacy_view in ["v_receipt_items", "home_clients"]:
        drop_v = QSqlQuery(db)
        if not drop_v.exec(f"DROP VIEW IF EXISTS {legacy_view}"):
            logger.warning(f"Failed to drop legacy view '{legacy_view}': {drop_v.lastError().text()}")
        else:
            logger.info(f"Cleaned up legacy view '{legacy_view}'")
        drop_v.finish()

    # Cleanup: Rebuild the 'visits' table to remove the stale legacy
    # 'client_id' column (references the now-dropped 'clients' table).
    # This dangling FK causes SQLite "no such table: main.clients" errors
    # during cascade deletes (e.g. when deleting an owner with pets/visits).
    _rebuild_visits_without_client_id(db)


def _run_seed_maintenance(db):
    """Ensures default lookup data + categories are present when empty."""
    query = QSqlQuery(db)

    # Migration: Check for species data and populate defaults
    # Run default seed data when ANY core lookup table is empty to ensure
    # roles, tests, treatments, vaccines, log types, systems, and services
    # are populated even if species already exist (e.g., from legacy migration).
    seed_needed = False
    for check_table in ["species_lookup", "roles", "tests_lookup",
                        "treatments_lookup", "vaccines_lookup",
                        "log_types_lookup", "systems_lookup"]:
        cq = QSqlQuery(db)
        if cq.exec(f"SELECT COUNT(*) FROM {check_table}"):
            if cq.next() and cq.value(0) == 0:
                seed_needed = True
                break
    if seed_needed:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _migration_recorded(db, version):
    """Returns True if a migration version is already recorded."""
    q = QSqlQuery(db)
    q.prepare("SELECT 1 FROM schema_migrations WHERE version = ?")
    q.addBindValue(version)
    return bool(q.exec() and q.next())


def _seed_builtin_role_permissions(db):
    """Populates role_permissions for the built-in roles when a row is newly
    inserted, so their template always reflects the static defaults."""
    from src.core.permissions import seed_permissions_for_role

    for role_name in ("admin", "doctor", "staff"):
        get_rid = QSqlQuery(db)
        get_rid.prepare("SELECT role_id FROM roles WHERE role_name = ?")
        get_rid.addBindValue(role_name)
        if not (get_rid.exec() and get_rid.next()):
            continue
        role_id = get_rid.value(0)

        # Reconcile: delete existing rows not in the template and insert rows
        # that are missing, so the template is an exact snapshot of defaults.
        existing = QSqlQuery(db)
        existing.prepare("SELECT permission_key FROM role_permissions WHERE role_id = ?")
        existing.addBindValue(role_id)
        have = set()
        if existing.exec():
            while existing.next():
                have.add(existing.value(0))

        target = set(seed_permissions_for_role(role_name))

        for key in have - target:
            dq = QSqlQuery(db)
            dq.prepare("DELETE FROM role_permissions WHERE role_id = ? AND permission_key = ?")
            dq.addBindValue(role_id)
            dq.addBindValue(key)
            dq.exec()
        for key in target - have:
            iq = QSqlQuery(db)
            iq.prepare(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?, ?)"
            )
            iq.addBindValue(role_id)
            iq.addBindValue(key)
            iq.exec()


def _mark_system_roles(db):
    """Marks the three built-in roles as system (protected) roles."""
    for role_name in ("admin", "doctor", "staff"):
        q = QSqlQuery(db)
        q.prepare("UPDATE roles SET is_system = 1 WHERE role_name = ?")
        q.addBindValue(role_name)
        q.exec()


def _add_column_if_not_exists(db, table_name, column_name, column_def):
    """Add a column to a table if it doesn't already exist.

    SQLite does not support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
    so we check the table's column list first.

    Raises RuntimeError if the column is missing and cannot be added. A silent
    failure here would let the migration runner record the version as applied
    while the column is still absent, so it would be skipped forever.
    """
    query = QSqlQuery(db)
    # PRAGMA table_info returns one row per column with name in column 1
    if not query.exec(f"PRAGMA table_info({table_name})"):
        raise RuntimeError(
            f"Could not inspect table '{table_name}': {query.lastError().text()}"
        )
    existing_columns = set()
    while query.next():
        existing_columns.add(query.value(1))
    query.finish()

    if column_name in existing_columns:
        return

    q = QSqlQuery(db)
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
    if not q.exec(sql):
        raise RuntimeError(
            f"Failed to add column '{column_name}' to '{table_name}': {q.lastError().text()}"
        )
    logger.info(f"Added column '{column_name}' to '{table_name}'")


def _record_migration(db, version):
    """Record a migration version in the schema_migrations table.

    Raises RuntimeError on failure so the runner rolls the migration back
    instead of committing a change it never actually recorded.
    """
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)")
    query.addBindValue(version)
    if not query.exec():
        raise RuntimeError(
            f"Could not record migration '{version}': {query.lastError().text()}"
        )
    query.finish()


def _ensure_role_exists(db, role_name):
    """Insert a role into the roles table if it does not already exist."""
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO roles (role_name) VALUES (?)")
    query.addBindValue(role_name)
    if query.exec():
        logger.info(f"Ensured role '{role_name}' exists in roles table")
    else:
        logger.warning(f"Failed to ensure role '{role_name}': {query.lastError().text()}")


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
        query.finish()
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
    query.finish()


def _rebuild_visits_without_client_id(db):
    """Rebuilds the 'visits' table to remove a stale legacy 'client_id' column.

    Background:
        The old (pre-migration) schema stored a `client_id` column on `visits`
        that referenced the legacy `clients` table. After migrating to the new
        schema (owners/pets), the `clients` table is dropped, leaving a dangling
        foreign key `REFERENCES clients(id)`. SQLite enforces this dangling FK
        during cascade deletes, raising "no such table: main.clients" when
        deleting an owner that has associated pets/visits.

        SQLite < 3.35 does not support `ALTER TABLE DROP COLUMN`, so we rebuild
        the table using the standard "create new, copy, drop old" procedure.

    Notes:
        - Views that depend on `visits` are dropped before the rebuild and
          recreated at the end of this function (the rebuild runs *after*
          `initialize_schema` already created them, so nothing else would).
        - Foreign keys are temporarily disabled during the rebuild so that
          dropping the old `visits` table does not cascade-delete child rows
          (followups, health_stats, medications, tests, etc.).
        - A temp-named table is used (visits_new) and renamed back to `visits`,
          which keeps FK references from child tables (e.g. `receipts`) intact.
        - Recreates indexes after the rebuild.
    """
    # Detect whether the stale column exists
    col_q = QSqlQuery(db)
    if not col_q.exec("PRAGMA table_info(visits)"):
        return
    has_client_id = False
    while col_q.next():
        if col_q.value(1) == "client_id":
            has_client_id = True
            break
    col_q.finish()

    if not has_client_id:
        return

    logger.info("Detected stale 'client_id' column on visits. Rebuilding table...")

    # Drop views that depend on `visits` BEFORE the rebuild. SQLite cannot
    # rename the table while a view references the old (dropped) name, so every
    # view that selects FROM visits must go — including v_pet_health_timeline,
    # which would otherwise make the RENAME fail and silently roll the rebuild
    # back, leaving the stale column in place.
    for view_name in ["v_visit_details", "v_receipt_summary", "v_home_records",
                      "v_pet_health_timeline"]:
        drop_v = QSqlQuery(db)
        if not drop_v.exec(f"DROP VIEW IF EXISTS {view_name}"):
            logger.warning(f"Failed to drop view '{view_name}': {drop_v.lastError().text()}")

    # Disable FK enforcement OUTSIDE a transaction (PRAGMA foreign_keys is a
    # no-op inside a transaction). We re-enable it in a finally block.
    fk_q = QSqlQuery(db)
    fk_q.exec("PRAGMA foreign_keys = OFF")

    try:
        db.transaction()

        # 1. Create the new clean visits table under a temporary name
        #    (matching schema_definitions core_tables).
        cq = QSqlQuery(db)
        if not cq.exec("""
            CREATE TABLE visits_new (
                visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pet_id INTEGER NOT NULL,
                doctor_id INTEGER,
                appointment_id INTEGER,
                visit_date TEXT NOT NULL,
                reason_for_visit TEXT,
                temperature_in_c REAL,
                temperature_status_id INTEGER,
                weight_status_id INTEGER,
                diagnosis TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE,
                FOREIGN KEY(appointment_id) REFERENCES appointments(appointment_id) ON DELETE SET NULL
            )
        """):
            logger.error(f"Failed to create new visits table: {cq.lastError().text()}")
            db.rollback()
            return

        # 2. Copy data from the old table (excluding the stale client_id column)
        iq = QSqlQuery(db)
        if not iq.exec("""
            INSERT INTO visits_new (
                visit_id, pet_id, doctor_id, appointment_id, visit_date,
                reason_for_visit, temperature_in_c, temperature_status_id,
                weight_status_id, diagnosis, notes, created_at, updated_at
            )
            SELECT
                visit_id, pet_id, doctor_id, appointment_id, visit_date,
                reason_for_visit, temperature_in_c, temperature_status_id,
                weight_status_id, diagnosis, notes, created_at, updated_at
            FROM visits
        """):
            logger.error(f"Failed to copy visits data: {iq.lastError().text()}")
            db.rollback()
            return

        # 3. Drop the old table (FKs are OFF, so child rows are preserved)
        dq = QSqlQuery(db)
        if not dq.exec("DROP TABLE visits"):
            logger.error(f"Failed to drop old visits table: {dq.lastError().text()}")
            db.rollback()
            return

        # 4. Rename the new table to 'visits'. Child tables' FK references
        #    point to 'visits' by name, so they resolve to the new table.
        rq = QSqlQuery(db)
        if not rq.exec("ALTER TABLE visits_new RENAME TO visits"):
            logger.error(f"Failed to rename visits_new: {rq.lastError().text()}")
            db.rollback()
            return

        # 5. Recreate indexes on the rebuilt visits table
        for idx_stmt in [
            "CREATE INDEX IF NOT EXISTS idx_visits_visit_date ON visits(visit_date)",
            "CREATE INDEX IF NOT EXISTS idx_visits_pet_id ON visits(pet_id)",
        ]:
            idx_q = QSqlQuery(db)
            idx_q.exec(idx_stmt)

        if not db.commit():
            logger.error("Failed to commit visits rebuild transaction")
            db.rollback()
            return

        logger.info("Rebuilt 'visits' table without the stale 'client_id' column.")
    except Exception as e:
        logger.error(f"Failed to rebuild visits table: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        # Re-enable FK enforcement
        fk_on = QSqlQuery(db)
        if not fk_on.exec("PRAGMA foreign_keys = ON"):
            logger.warning(f"Failed to re-enable foreign_keys: {fk_on.lastError().text()}")

        # Verify schema integrity
        check_q = QSqlQuery(db)
        if check_q.exec("PRAGMA foreign_key_check"):
            has_violation = False
            while check_q.next():
                has_violation = True
                logger.warning(
                    f"FK violation: table={check_q.value(0)} rowid={check_q.value(1)} "
                    f"parent={check_q.value(2)}"
                )
            if has_violation:
                logger.warning("Foreign key violations found after visits rebuild.")
            else:
                logger.info("Foreign key check passed after visits rebuild.")

        # Recreate the views dropped above. This function runs after
        # `initialize_schema` already created them, so without this the
        # dependent views (v_visit_details, v_receipt_summary, v_home_records)
        # would stay missing until the *next* startup. Re-running the full view
        # definitions is idempotent (DROP IF EXISTS + CREATE IF NOT EXISTS) and
        # safe even when the rebuild rolled back (the views only reference
        # generic `visits` columns).
        for view_sql in _SCHEMA_VIEWS:
            view_q = QSqlQuery(db)
            if not view_q.exec(view_sql):
                logger.warning(
                    "Failed to recreate views after visits rebuild: %s",
                    view_q.lastError().text(),
                )
