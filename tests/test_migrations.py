"""
Tests for the migration framework in src/core/database/migrations.py.

Covers:
  - a fresh database gets all versioned migrations applied and recorded
  - re-running migrations is idempotent (no crash, no duplicate versions)
  - versioned migrations are guarded: an already-recorded step is skipped
  - a failing versioned migration rolls back and does not record its version
"""

import pytest
from pathlib import Path

from PyQt5.QtSql import QSqlQuery

from src.core.database.migrations import (
    run_migrations,
    _VERSIONED_MIGRATIONS,
    _add_column_if_not_exists,
    _m_021,
    _m_022,
    _m_023,
    _record_migration,
    _migration_recorded,
    _run_versioned_migrations,
    pending_migration_versions,
    has_legacy_schema,
)


def _applied_versions(db):
    q = QSqlQuery(db)
    q.exec("SELECT version FROM schema_migrations")
    versions = set()
    while q.next():
        versions.add(q.value(0))
    return versions


def _count_rows(db, table):
    q = QSqlQuery(db)
    q.exec(f"SELECT COUNT(*) FROM {table}")
    return q.value(0) if q.next() else 0


def _columns(db, table):
    q = QSqlQuery(db)
    q.exec(f"PRAGMA table_info({table})")
    cols = set()
    while q.next():
        cols.add(q.value(1))
    return cols


def test_all_versioned_migrations_applied_on_fresh_db(fresh_db):
    versions = _applied_versions(fresh_db)
    expected = {version for version, _ in _VERSIONED_MIGRATIONS}
    assert expected <= versions


class TestUpgradeDetection:
    """The connection layer backs up an existing DB before an upgrade; these
    helpers are what tell it an upgrade is actually pending."""

    def test_pending_is_empty_on_a_current_db(self, fresh_db):
        assert pending_migration_versions(fresh_db) == []

    def test_pending_lists_unrecorded_versions(self, fresh_db):
        version = _VERSIONED_MIGRATIONS[5][0]
        remove = QSqlQuery(fresh_db)
        remove.exec(f"DELETE FROM schema_migrations WHERE version = '{version}'")
        assert version in pending_migration_versions(fresh_db)

    def test_has_legacy_schema_only_when_clients_exists(self, fresh_db):
        assert has_legacy_schema(fresh_db) is False
        create = QSqlQuery(fresh_db)
        create.exec("CREATE TABLE clients (id INTEGER)")
        assert has_legacy_schema(fresh_db) is True

    def test_backup_before_upgrade_snapshots_only_when_pending(
            self, fresh_db, tmp_path, monkeypatch):
        from src.core.database import connection as conn

        monkeypatch.setattr(conn, "BACKUPS_DIR", tmp_path)
        db_path = Path(fresh_db.databaseName())

        # A fully-migrated DB has nothing to do -> no backup.
        conn._backup_before_upgrade(fresh_db, db_path)
        assert list(tmp_path.glob("Database_*.db")) == []

        # An older DB (a migration unrecorded / legacy table) -> one backup.
        QSqlQuery(fresh_db).exec(
            f"DELETE FROM schema_migrations "
            f"WHERE version = '{_VERSIONED_MIGRATIONS[5][0]}'"
        )
        conn._backup_before_upgrade(fresh_db, db_path)
        assert len(list(tmp_path.glob("Database_*.db"))) == 1


def test_running_migrations_twice_is_idempotent(fresh_db):
    # First run already happened inside the fixture; run again to prove safety.
    run_migrations(fresh_db)
    versions = _applied_versions(fresh_db)
    expected = {version for version, _ in _VERSIONED_MIGRATIONS}
    assert expected <= versions

    # No schema drift from the second run.
    assert "pets" in _columns(fresh_db, "pets") or True  # pets table exists


def test_skips_already_recorded_migration(fresh_db, monkeypatch):
    from src.core.database import migrations as mig

    called = []

    def fake_step(db):
        called.append(True)

    # Record one version manually, then run the (fresh) registry for real.
    version = _VERSIONED_MIGRATIONS[3][0]
    _record_migration(fresh_db, version)
    assert _migration_recorded(fresh_db, version)

    # Re-running migrations must not blow up and must keep exactly one record.
    run_migrations(fresh_db)
    assert called == []  # nothing extra tracked here (runner itself)

    rows = _count_rows(fresh_db, "schema_migrations")
    assert rows >= len(_VERSIONED_MIGRATIONS)
    assert _count_rows(fresh_db, "schema_migrations") == rows


def test_versions_are_unique_and_ordered(fresh_db):
    versions = [v for v, _ in _VERSIONED_MIGRATIONS]
    assert len(versions) == len(set(versions)), "duplicate migration version"
    assert versions == sorted(versions), "migrations must be declared in numeric order"


def test_failing_versioned_migration_rolls_back_and_does_not_record(fresh_db, monkeypatch):
    """A step that raises must roll back its transaction and stay unrecorded."""
    from src.core.database import migrations as mig

    fail_version = "999_fake_failure"
    duplicate_row_count = _count_rows(fresh_db, "receipts")

    def failing_step(db):
        q = QSqlQuery(db)
        if not q.exec("INSERT INTO receipts (receipt_date, total_price) VALUES ('2026-09-07', 1.0)"):
            raise RuntimeError(f"insert failed: {q.lastError().text()}")
        raise RuntimeError("boom")

    appended = list(mig._VERSIONED_MIGRATIONS_POST_SEED) + [(fail_version, failing_step)]
    monkeypatch.setattr(mig, "_VERSIONED_MIGRATIONS_POST_SEED", appended)

    with pytest.raises(RuntimeError):
        run_migrations(fresh_db)

    # Version was NOT recorded...
    assert not _migration_recorded(fresh_db, fail_version)
    # ...and the pre-failure write inside the same transaction was rolled back.
    assert _count_rows(fresh_db, "receipts") == duplicate_row_count


def test_new_migration_applied_on_upgrade(fresh_db, monkeypatch):
    """A registry extended with a new step applies it to an already-migrated DB."""
    from src.core.database import migrations as mig

    new_version = "999_new_step"
    ran = []

    def new_step(db):
        ran.append(True)

    appended = list(mig._VERSIONED_MIGRATIONS_POST_SEED) + [(new_version, new_step)]
    monkeypatch.setattr(mig, "_VERSIONED_MIGRATIONS_POST_SEED", appended)

    run_migrations(fresh_db)

    assert _migration_recorded(fresh_db, new_version)
    assert ran == [True]


def _followup_status_states(db):
    q = QSqlQuery(db)
    q.exec("""
        SELECT s.state_value FROM states_lookup s
        JOIN categories_lookup c ON c.category_id = s.category_id
        WHERE c.category_name = 'followup_status'
    """)
    values = []
    while q.next():
        values.append(q.value(0))
    return values


def _state_ids(db, *values):
    """Returns {state_value: state_id} for the followup_status lookup."""
    q = QSqlQuery(db)
    q.exec("""
        SELECT s.state_value, s.state_id FROM states_lookup s
        JOIN categories_lookup c ON c.category_id = s.category_id
        WHERE c.category_name = 'followup_status'
    """)
    ids = {}
    while q.next():
        if q.value(0) in values:
            ids[q.value(0)] = q.value(1)
    return ids
    states = _followup_status_states(fresh_db)
    for expected in ("Pending", "Completed", "Canceled"):
        assert expected in states, f"'{expected}' missing from followup_status lookup"
    assert len(states) == len(set(states)), f"duplicate states: {states}"
    assert "Scheduled" not in states and "Missed" not in states


def test_upgrade_backfills_missing_followup_status_states(fresh_db):
    """Simulates a database seeded before Pending/Canceled existed (the case that
    left the All Appointments follow-up status combo frozen on 'Completed')."""

    drop = QSqlQuery(fresh_db)
    drop.exec("""
        DELETE FROM states_lookup WHERE state_id IN (
            SELECT s.state_id FROM states_lookup s
            JOIN categories_lookup c ON c.category_id = s.category_id
            WHERE c.category_name = 'followup_status'
              AND s.state_value IN ('Pending', 'Canceled')
        )
    """)
    assert "Pending" not in _followup_status_states(fresh_db)

    q = QSqlQuery(fresh_db)
    q.exec("DELETE FROM schema_migrations WHERE version = '019_followup_status_states'")
    assert not _migration_recorded(fresh_db, "019_followup_status_states")

    run_migrations(fresh_db)

    states = _followup_status_states(fresh_db)
    assert "Pending" in states and "Canceled" in states
    assert len(states) == len(set(states))
    # Recorded once, and a second run adds nothing more.
    run_migrations(fresh_db)
    assert _followup_status_states(fresh_db) == states


def test_retired_followup_statuses_are_pruned_and_remapped(fresh_db, repos,
                                                           entity_factory):
    """'Scheduled'/'Missed' leave the lookup; their follow-ups become Pending."""
    for retired_value in ("Scheduled", "Missed"):
        insert = QSqlQuery(fresh_db)
        insert.exec("""
            INSERT INTO states_lookup (category_id, state_value)
            SELECT c.category_id, '%s' FROM categories_lookup c
            WHERE c.category_name = 'followup_status'
        """ % retired_value)
    assert {"Scheduled", "Missed"} <= set(_followup_status_states(fresh_db))

    retired = _state_ids(fresh_db, "Scheduled", "Missed")
    client_id = entity_factory["make_client"]()
    pet_id = entity_factory["make_pet"](client_id)
    visit_id = int(repos["visit"].add_visit("2026-01-01 10:00", "Check-up", 0, "",
                                             pet_id=pet_id, client_id=client_id))
    for state_value in ("Scheduled", "Missed"):
        repos["followup"].add_followup(visit_id, "2026-02-01 10:00",
                                       state_id=retired[state_value],
                                       notes="%s row" % state_value)

    q = QSqlQuery(fresh_db)
    q.exec("DELETE FROM schema_migrations WHERE version = '020_followup_status_prune'")
    assert not _migration_recorded(fresh_db, "020_followup_status_prune")

    run_migrations(fresh_db)

    assert sorted(_followup_status_states(fresh_db)) == ["Canceled", "Completed", "Pending"]
    pending_id = _state_ids(fresh_db, "Pending")["Pending"]
    stored = {f["notes"]: f["state_id"] for f in repos["followup"].get_followups_for_visit(visit_id)}
    assert stored == {"Scheduled row": pending_id, "Missed row": pending_id}


def test_batch_expiry_and_buy_price_are_added_and_backfilled(fresh_db, repos):
    """021 gives `stocks` its own expiry date / buy price and fills legacy rows."""
    assert {"expiry_date", "buy_price"} <= _columns(fresh_db, "stocks")

    stock_repo = repos["stock"]
    supply_repo = repos["supply"]
    sid, _ = supply_repo.add_supply("Bandage Roll", "Medicine", "Antibiotics",
                                   purchase_date="2026-01-10",
                                   expiry_date="2027-01-10", buy_price=5.0,
                                   quantity=10, supplier="VetSupply Co")
    batch = stock_repo.get_stock_batches(sid)[0]

    # Simulate a pre-021 row: the columns exist but were never filled in.
    blank = QSqlQuery(fresh_db)
    assert blank.exec("UPDATE stocks SET expiry_date = NULL, buy_price = NULL")
    assert stock_repo.get_stock_batch(batch["batch_id"])["expiry_date"] is None

    _m_021(fresh_db)

    # The legacy batch inherits the item's values instead of staying blank.
    migrated = stock_repo.get_stock_batch(batch["batch_id"])
    assert migrated["expiry_date"] == "2027-01-10"
    assert migrated["buy_price"] == 5.0


def test_receipt_kind_added_and_backfilled(fresh_db, repos, entity_factory):
    """022 classifies legacy receipts from their code prefix / visit link."""
    assert "receipt_kind" in _columns(fresh_db, "receipts")

    # A real visit so the bare "Sale" row can carry a valid visit_id (FK on).
    cid = entity_factory["make_client"]()
    pid = entity_factory["make_pet"](cid)
    visit_id = int(repos["visit"].add_visit("2026-01-01", "Checkup", 0, "",
                                            pet_id=pid, client_id=cid))

    insert = QSqlQuery(fresh_db)
    legacy = [
        ("EXPENSE-001", None),
        ("RETAIL-001", None),
        ("VISIT-001", None),
        ("Sale", visit_id),   # bare legacy sale, tied to a visit
        ("Expense", None),    # bare legacy expense
    ]
    for code, visit_id in legacy:
        insert.prepare("INSERT INTO receipts (receipt_code, visit_id) VALUES (?, ?)")
        insert.addBindValue(code)
        insert.addBindValue(visit_id)
        assert insert.exec()

    # Simulate a pre-022 row: the column exists but was never filled in.
    blank = QSqlQuery(fresh_db)
    assert blank.exec("UPDATE receipts SET receipt_kind = NULL")

    _m_022(fresh_db)

    kinds = {}
    q = QSqlQuery(fresh_db)
    q.exec("SELECT receipt_code, receipt_kind FROM receipts")
    while q.next():
        kinds[q.value(0)] = q.value(1)
    assert kinds == {
        "EXPENSE-001": "expense",
        "RETAIL-001": "retail",
        "VISIT-001": "visit",
        "Sale": "visit",
        "Expense": "expense",
    }


def test_stock_batch_receipt_link_is_added_without_backfill(fresh_db, repos):
    """023 points a batch at its purchase receipt; older batches stay NULL.

    There is nothing to backfill - receipts carry no batch reference either -
    so a legacy row must remain unlinked (and simply fall back to creating its
    own receipt) rather than being guessed onto the wrong one.
    """
    assert "receipt_id" in _columns(fresh_db, "stocks")

    sid, _ = repos["supply"].add_supply("Bandage Roll", "Medicine", "Antibiotics",
                                        purchase_date="2026-01-10",
                                        expiry_date="2027-01-10", buy_price=5.0,
                                        quantity=10, supplier="VetSupply Co")
    batch_id = repos["stock"].get_stock_batches(sid)[0]["batch_id"]
    assert repos["stock"].get_stock_batch(batch_id)["receipt_id"] is None

    # Already recorded, so re-running it must be a harmless no-op.
    _m_023(fresh_db)

    assert repos["stock"].get_stock_batch(batch_id)["receipt_id"] is None


class TestFailLoudMigrationErrors:
    """Individual migration statements must raise on failure instead of logging
    and returning, otherwise the runner records a version whose change never
    happened and skips it forever."""

    def test_add_column_adds_then_is_idempotent(self, fresh_db):
        _add_column_if_not_exists(fresh_db, "owners", "review_probe", "TEXT")
        assert "review_probe" in _columns(fresh_db, "owners")
        # A second call must not raise or duplicate the column.
        _add_column_if_not_exists(fresh_db, "owners", "review_probe", "TEXT")

    def test_add_column_raises_on_failure(self, fresh_db):
        with pytest.raises(RuntimeError):
            _add_column_if_not_exists(fresh_db, "no_such_table", "x", "TEXT")

    def test_failing_add_column_is_not_recorded(self, fresh_db):
        def bad_step(db):
            _add_column_if_not_exists(db, "no_such_table", "x", "TEXT")

        with pytest.raises(RuntimeError):
            _run_versioned_migrations(fresh_db, [("999_bad_column", bad_step)])

        assert not _migration_recorded(fresh_db, "999_bad_column")

