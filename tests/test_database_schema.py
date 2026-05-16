"""Tests for database schema, migrations, and seed data."""

import pytest
from PyQt5.QtSql import QSqlQuery

from src.core.database.schema_initializer import initialize_schema
from src.core.repositories import appointment_repo, followup_repo, visit_repo


def _table_names(db):
    """Returns the set of user table names in the database."""
    q = QSqlQuery(db)
    q.exec("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    names = set()
    while q.next():
        names.add(q.value(0))
    return names


def _view_names(db):
    """Returns the set of view names in the database."""
    q = QSqlQuery(db)
    q.exec("SELECT name FROM sqlite_master WHERE type='view'")
    names = set()
    while q.next():
        names.add(q.value(0))
    return names


def _count_rows(db, table):
    q = QSqlQuery(db)
    q.exec(f"SELECT COUNT(*) FROM {table}")
    q.next()
    return int(q.value(0))


class TestSchemaTables:
    def test_core_tables_exist(self, fresh_db):
        names = _table_names(fresh_db)
        required = {
            "owners", "pets", "visits", "appointments", "followups",
            "supplies", "stocks", "stock_movements", "receipts",
            "receipt_supplies", "receipt_other", "packages", "package_items",
            "users", "roles", "user_roles", "sessions",
            "change_header", "change_detail", "logs",
            "health_stats", "medications", "tests", "treatments", "vaccinations",
        }
        assert required.issubset(names)

    def test_lookup_tables_exist(self, fresh_db):
        names = _table_names(fresh_db)
        required = {
            "species_lookup", "breeds_lookup", "services_lookup",
            "tests_lookup", "treatments_lookup", "vaccines_lookup",
            "log_types_lookup", "stat_types_lookup", "states_lookup",
            "categories", "subcategories",
        }
        assert required.issubset(names)

    def test_legacy_tables_dropped(self, fresh_db):
        names = _table_names(fresh_db)
        assert "clients" not in names
        assert "receipt_items" not in names
        assert "supply_reorder_levels" not in names

    def test_views_created(self, fresh_db):
        views = _view_names(fresh_db)
        assert {"v_visit_details", "v_receipt_summary", "v_home_records"}.issubset(views)


class TestSeedData:
    def test_lookup_data_seeded(self, fresh_db):
        assert _count_rows(fresh_db, "species_lookup") >= 5
        assert _count_rows(fresh_db, "services_lookup") >= 5
        assert _count_rows(fresh_db, "tests_lookup") >= 5
        assert _count_rows(fresh_db, "treatments_lookup") >= 5
        assert _count_rows(fresh_db, "vaccines_lookup") >= 5
        assert _count_rows(fresh_db, "log_types_lookup") >= 5

    def test_admin_user_seeded(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.prepare("SELECT user_id FROM users WHERE username = 'admin'")
        assert q.exec() and q.next()

    def test_roles_seeded(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("SELECT role_name FROM roles")
        roles = set()
        while q.next():
            roles.add(q.value(0))
        assert {"admin", "staff"}.issubset(roles)


class TestMigrationColumns:
    """Verifies columns added by migration logic exist."""

    def test_receipt_other_quantity_columns(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(receipt_other)")
        cols = set()
        while q.next():
            cols.add(q.value(1))
        assert cols.issuperset({"quantity", "unit_price", "description", "amount"})

    def test_receipts_have_payment_status(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(receipts)")
        columns = {}
        while q.next():
            columns[q.value(1)] = q.value(4)
        assert "payment_status" in columns
        assert columns["payment_status"] == "'Unpaid'"

    def test_created_at_columns(self, fresh_db):
        # All audited tables get created_at.
        for table in ("owners", "pets", "visits", "supplies", "receipts"):
            q = QSqlQuery(fresh_db)
            q.exec(f"PRAGMA table_info({table})")
            cols = set()
            while q.next():
                cols.add(q.value(1))
            assert "created_at" in cols, f"{table} missing created_at"

        # updated_at is added to owners, pets, visits, supplies — but NOT receipts
        # (the migration only adds created_at to receipts).
        for table in ("owners", "pets", "visits", "supplies"):
            q = QSqlQuery(fresh_db)
            q.exec(f"PRAGMA table_info({table})")
            cols = set()
            while q.next():
                cols.add(q.value(1))
            assert "updated_at" in cols, f"{table} missing updated_at"

    def test_supply_reorder_level_column(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(supplies)")
        cols = set()
        while q.next():
            cols.add(q.value(1))
        assert "reorder_level" in cols

    def test_users_have_doctor_mapping_column(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(users)")
        cols = set()
        while q.next():
            cols.add(q.value(1))
        assert "doctor_id" in cols

    def test_appointments_have_service_column(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(appointments)")
        cols = set()
        while q.next():
            cols.add(q.value(1))
        assert "service" in cols

    def test_followups_have_doctor_column(self, fresh_db):
        q = QSqlQuery(fresh_db)
        q.exec("PRAGMA table_info(followups)")
        cols = set()
        while q.next():
            cols.add(q.value(1))
        assert "doctor_id" in cols


class TestAppointmentAndFollowupData:
    def test_appointment_service_round_trip(self, fresh_db, entity_factory):
        client_id = entity_factory["make_client"]("Service Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")

        assert appointment_repo.add_appointment(
            "2099-09-03 10:00", "Vaccination", "Pending", "", client_id, pet_id
        )
        assert appointment_repo.get_appointments()[0]["service"] == "Vaccination"

    def test_upcoming_followups_can_be_filtered_by_doctor(self, fresh_db, entity_factory):
        client_id = entity_factory["make_client"]("Followup Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")
        visit_id = visit_repo.add_visit(
            "2026-09-02 10:00", "Checkup", 1, "", pet_id=pet_id, doctor_id=7
        )
        assert followup_repo.add_followup(visit_id, "2099-09-10 10:00")

        assert len(followup_repo.get_upcoming_followups(doctor_id=7)) == 1
        assert followup_repo.get_upcoming_followups(doctor_id=99) == []

    def test_past_followups_returned_newest_first(self, fresh_db, entity_factory):
        client_id = entity_factory["make_client"]("Past Followup Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")
        visit_id = visit_repo.add_visit(
            "2026-09-02 10:00", "Checkup", 1, "", pet_id=pet_id, doctor_id=7
        )
        assert followup_repo.add_followup(visit_id, "2020-01-01 10:00", doctor_id=7)

        assert len(followup_repo.get_past_followups(doctor_id=7)) == 1
        assert followup_repo.get_past_followups(doctor_id=99) == []

    def test_followup_defaults_to_visit_doctor_and_supports_substitute(self, fresh_db, entity_factory):
        client_id = entity_factory["make_client"]("Substitute Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")
        visit_id = visit_repo.add_visit(
            "2026-09-02 10:00", "Checkup", 1, "", pet_id=pet_id, doctor_id=7
        )

        assert followup_repo.add_followup(visit_id, "2099-09-10")
        assert followup_repo.add_followup(visit_id, "2099-09-11", doctor_id=9)
        rows = followup_repo.get_followups_for_visit(visit_id)
        assert [row["doctor_id"] for row in rows] == [7, 9]

    def test_visit_inherits_appointment_doctor(self, fresh_db, entity_factory):
        client_id = entity_factory["make_client"]("Appointment Owner")
        pet_id = entity_factory["make_pet"](client_id, name="Rex")
        assert appointment_repo.add_appointment(
            "2099-09-12 10:00", "Checkup", "Pending", "", client_id, pet_id, doctor_id=7
        )

        visit_id = visit_repo.add_visit(
            "2099-09-12 10:00", "Checkup", 1, "", pet_id=pet_id, appointment_id=1
        )
        q = QSqlQuery(fresh_db)
        q.prepare("SELECT doctor_id, appointment_id FROM visits WHERE visit_id = ?")
        q.addBindValue(visit_id)
        assert q.exec() and q.next()
        assert q.value(0) == 7
        assert q.value(1) == 1


class TestForeignKeys:
    def test_foreign_keys_enabled(self, fresh_db):
        q = QSqlQuery(fresh_db)
        assert q.exec("PRAGMA foreign_keys")
        q.next()
        assert q.value(0) == 1


class TestMigrationRegression:
    def test_schema_initialization_is_idempotent(self, fresh_db):
        before = _count_rows(fresh_db, "schema_migrations")
        initialize_schema(fresh_db)
        after = _count_rows(fresh_db, "schema_migrations")

        assert after == before
        assert _count_rows(fresh_db, "roles") >= 3

    def test_legacy_clients_migrate_once(self, fresh_db):
        q = QSqlQuery(fresh_db)
        assert q.exec("CREATE TABLE clients (id INTEGER PRIMARY KEY, owner_name TEXT, phone_number TEXT)")
        q.prepare("INSERT INTO clients (id, owner_name, phone_number) VALUES (?, ?, ?)")
        q.addBindValue(501)
        q.addBindValue("Legacy Client")
        q.addBindValue("0123456789")
        assert q.exec()

        initialize_schema(fresh_db)
        assert "clients" not in _table_names(fresh_db)
        assert _count_rows(fresh_db, "owners") == 1

        initialize_schema(fresh_db)
        assert _count_rows(fresh_db, "owners") == 1
