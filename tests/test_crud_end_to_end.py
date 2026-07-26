"""
Phase 4 - Step 1: End-to-end CRUD test suite.

Exercises every repository in src/core/repositories/ against an isolated
temporary SQLite database (never touches the production Database.db).

Run with:  python -m pytest tests/ -v
"""

import uuid

from PyQt5.QtSql import QSqlQuery

# =============================================================================
# Shared helpers (pytest-style, using the fresh_db / repos fixtures from
# conftest.py so every repository is bound to an isolated per-test DB).
# =============================================================================


def _unique(prefix: str) -> str:
    """Returns a unique short identifier for test data."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _lookup_id(db, table: str, column: str, value):
    """Returns the first PK value in `table` matching `column = value`."""
    q = QSqlQuery(db)
    q.prepare(f"SELECT * FROM {table} WHERE {column} = ? LIMIT 1")
    q.addBindValue(value)
    if q.exec() and q.next():
        result = q.value(0)
        q.finish()
        return result
    q.finish()
    return None


def _first_id(db, table: str):
    """Returns the first PK value in `table` (or None if empty)."""
    q = QSqlQuery(db)
    if q.exec(f"SELECT * FROM {table} LIMIT 1") and q.next():
        result = q.value(0)
        q.finish()
        return result
    q.finish()
    return None


def _make_client(repos, name: str = None) -> int:
    cid = repos["client"].add_client(name or _unique("John") + " Doe", "0500000000")
    assert cid is not None, "add_client should return an owner_id"
    return int(cid)


def _make_pet(repos, client_id: int) -> int:
    pid = repos["pet"].add_pet("Rex", "Dog", "Labrador Retriever", "M", 24, 25.5, client_id)
    assert pid is not None, "add_pet should return a pet_id"
    return int(pid)


def _make_supply(repos, quantity: int = 100, item_name: str = None) -> tuple:
    """Creates a supply and returns (supply_id, item_name)."""
    name = item_name or _unique("Medicine")
    sid, expense = repos["supply"].add_supply(
        name,
        "Medicine", "Antibiotics",
        purchase_date="2025-01-15", expiry_date="2026-12-31",
        buy_price=5.0, sell_price=10.0, quantity=quantity,
    )
    assert sid is not None, "add_supply should return a supply_id"
    return int(sid), name


# =============================================================================
# Clients
# =============================================================================
class TestClientsCRUD:
    def test_client_crud_lifecycle(self, fresh_db, repos):
        name = _unique("Alice") + " Smith"
        cid = repos["client"].add_client(name, "0501234567")
        assert cid is not None

        # Read
        clients = repos["client"].get_clients()
        assert any(c["client_id"] == cid for c in clients), "Created client should be listed"
        found = repos["client"].get_clients_by_name_exact(name)
        assert any(c["client_id"] == cid for c in found), "Exact-name search should find client"

        # Search by phone
        by_phone = repos["client"].get_clients("0501234567", "Phone Number")
        assert any(c["client_id"] == cid for c in by_phone), "Phone search should find client"

        # Update
        new_name = _unique("Alice") + " Brown"
        assert repos["client"].update_client(cid, new_name, "0509998888")
        updated = repos["client"].get_clients_by_name_exact(new_name)
        assert any(c["client_id"] == cid and c["phone_number"] == "0509998888" for c in updated)

        # Delete
        assert repos["client"].delete_client(cid)
        remaining = repos["client"].get_clients()
        assert not any(c["client_id"] == cid for c in remaining), "Deleted client should be gone"


# =============================================================================
# Pets
# =============================================================================
class TestPetsCRUD:
    def test_pet_crud_lifecycle(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)

        # Read
        pets = repos["pet"].get_pets()
        assert any(p["pet_id"] == pid for p in pets)
        for_client = repos["pet"].get_pets_for_client(cid)
        assert any(p["pet_id"] == pid for p in for_client)
        assert repos["pet"].get_existing_pet("Rex", "Dog", "Labrador Retriever", "M", cid) is not None

        # Full update
        assert repos["pet"].update_pet(pid, "Max", "Cat", "Persian", "F", 12, 4.2, cid)
        pets_after = repos["pet"].get_pets()
        updated = next(p for p in pets_after if p["pet_id"] == pid)
        assert updated["pet_name"] == "Max"
        assert updated["species"] == "Cat"

        # Details update (age/weight)
        assert repos["pet"].update_pet_details(pid, 18, 5.0)
        pets_final = repos["pet"].get_pets()
        final = next(p for p in pets_final if p["pet_id"] == pid)
        assert final["age_months"] == 18
        assert final["weight"] == 5.0

        # Delete
        assert repos["pet"].delete_pet(pid)
        assert not any(p["pet_id"] == pid for p in repos["pet"].get_pets())


# =============================================================================
# Visits + clinical records (health stats, tests, treatments, vaccinations,
# medications) + followups
# =============================================================================
class TestVisitsAndClinicalCRUD:
    def _create_full_visit_context(self, repos, qty=10):
        """Creates client, pet, supply, and resolves lookup IDs for clinical data."""
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)
        sid, item_name = _make_supply(repos, quantity=qty)

        db = repos["client"].get_connection()

        stat_type_id = _first_id(db, "stat_types_lookup")
        assert stat_type_id is not None
        state_id = _first_id(db, "states_lookup")
        assert state_id is not None
        test_id = _first_id(db, "tests_lookup")
        treatment_id = _first_id(db, "treatments_lookup")
        vaccine_id = _first_id(db, "vaccines_lookup")
        assert test_id is not None
        assert treatment_id is not None
        assert vaccine_id is not None

        return cid, pid, sid, item_name, stat_type_id, state_id, test_id, treatment_id, vaccine_id

    def test_full_visit_lifecycle(self, fresh_db, repos):
        cid, pid, sid, item_name, stat_type_id, state_id, test_id, treatment_id, vaccine_id = self._create_full_visit_context(repos)

        # Create visit with supplies, consult, and all clinical records.
        result = repos["visit"].add_visit(
            visit_date="2025-02-10",
            diagnosis="Canine Distemper",
            consult=True,
            notes="Full clinical workup",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 2, "price": 10.0}],
            reason_for_visit="Coughing",
            temperature=39.2,
            health_stats=[{"stat_type_id": stat_type_id, "state_id": state_id, "extra_note": "Elevated"}],
            tests=[{"test_id": test_id, "state_id": state_id}],
            treatments=[treatment_id],
            vaccinations=[vaccine_id],
            medications=[{"supply_id": sid, "dosage": "10 mg", "instructions": "Once daily"}],
        )
        assert result is not None, "add_visit should return a visit/receipt id"
        assert isinstance(result, int)
        result_id = int(result)

        # A consult + billed item => a 'Sale' receipt is created.
        visits = repos["visit"].get_visits()
        visit_row = next((v for v in visits if int(v["receipt_id"] or 0) == result_id), None)
        assert visit_row is not None, "Visit should be retrievable with the created receipt"
        assert visit_row["consult"] == 1, "Consult visit should report consult=1"

        visit_id = int(visit_row["visit_id"])

        # Verify stock was deducted (10 initial - 2 sold = 8).
        supplies = repos["supply"].search_supplies()
        supply_row = next(s for s in supplies if s["supply_id"] == sid)
        assert supply_row["current_stock"] == 8, "Stock should be deducted by visit items"

        # Clinical sub-records are present.
        assert repos["health_stats"].get_health_stats_for_visit(visit_id), "Health stats should exist"
        assert repos["test"].get_tests_for_visit(visit_id), "Tests should exist"
        assert repos["treatment"].get_treatments_for_visit(visit_id), "Treatments should exist"
        assert repos["vaccination"].get_vaccinations_for_visit(visit_id), "Vaccinations should exist"
        assert repos["medication"].get_medications_for_visit(visit_id), "Medications should exist"

        # Pet-level history queries.
        assert repos["health_stats"].get_health_stats_for_pet(pid)
        assert repos["vaccination"].get_vaccination_history(pid)
        assert repos["medication"].get_medication_history(pid)

        # Update visit.
        assert repos["visit"].update_visit(visit_id, "Updated diagnosis", "Updated notes",
                                           "2025-02-11", True, reason_for_visit="Fever")
        updated_rows = repos["visit"].get_visits()
        updated = next(v for v in updated_rows if v["visit_id"] == visit_id)
        assert updated["diagnosis"] == "Updated diagnosis"

        # Followup scheduling.
        fu_id = repos["followup"].add_followup(visit_id, "2030-03-01", None, "Recheck")
        assert fu_id is not None
        upcoming = repos["followup"].get_upcoming_followups()
        assert any(int(f["followup_id"]) == int(fu_id) for f in upcoming)
        assert repos["followup"].update_followup(int(fu_id), "2030-03-05", None, "Recheck 2")
        assert repos["followup"].delete_followup(int(fu_id))

        # Delete individual clinical records.
        hs = repos["health_stats"].get_health_stats_for_visit(visit_id)
        assert repos["health_stats"].delete_health_stat(int(hs[0]["health_stat_id"]))
        t = repos["test"].get_tests_for_visit(visit_id)
        assert repos["test"].delete_test_record(int(t[0]["routine_test_id"]))
        tr = repos["treatment"].get_treatments_for_visit(visit_id)
        assert repos["treatment"].delete_treatment_record(int(tr[0]["treatment_record_id"]))
        v = repos["vaccination"].get_vaccinations_for_visit(visit_id)
        assert repos["vaccination"].delete_vaccination_record(int(v[0]["vaccination_id"]))
        m = repos["medication"].get_medications_for_visit(visit_id)
        assert repos["medication"].delete_medication(int(m[0]["medication_id"]))

        assert not repos["health_stats"].get_health_stats_for_visit(visit_id)
        assert not repos["test"].get_tests_for_visit(visit_id)
        assert not repos["treatment"].get_treatments_for_visit(visit_id)
        assert not repos["vaccination"].get_vaccinations_for_visit(visit_id)
        assert not repos["medication"].get_medications_for_visit(visit_id)

        # Delete the visit.
        assert repos["visit"].delete_visit(visit_id)
        assert not any(v["visit_id"] == visit_id for v in repos["visit"].get_visits())

        # Client/pet cleanup to avoid polluting later tests.
        assert repos["pet"].delete_pet(pid)
        assert repos["client"].delete_client(cid)

    def test_visit_stock_error_returns_error_string(self, fresh_db, repos):
        """Billing more stock than available returns a STOCK_ERROR string."""
        cid, pid, sid, item_name, *_ = self._create_full_visit_context(repos, qty=5)
        result = repos["visit"].add_visit(
            visit_date="2025-02-12",
            diagnosis="Test",
            consult=False,
            notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 999, "price": 10.0}],
        )
        assert isinstance(result, str)
        assert result.startswith("STOCK_ERROR"), f"Expected STOCK_ERROR, got {result!r}"

        assert repos["pet"].delete_pet(pid)
        assert repos["client"].delete_client(cid)


# =============================================================================
# Suppliers, Supplies & Stock batches
# =============================================================================
class TestSuppliesAndStockCRUD:
    def test_supplier_crud(self, fresh_db, repos):
        name = _unique("Vendor")
        sid = repos["supplier"].add_supplier(name)
        assert sid is not None
        assert any(s["supplier_id"] == sid for s in repos["supplier"].get_suppliers())
        assert any(s["supplier_id"] == sid for s in repos["supplier"].get_suppliers(name[:6]))

        assert repos["supplier"].update_supplier(int(sid), _unique("Vendor") + " Inc")
        assert repos["supplier"].delete_supplier(int(sid))
        assert not any(s["supplier_id"] == sid for s in repos["supplier"].get_suppliers())

    def test_supply_crud_and_stock_batches(self, fresh_db, repos):
        item_name = _unique("Medicine")
        sid, expense = repos["supply"].add_supply(
            item_name, "Medicine", "Antibiotics",
            purchase_date="2025-01-15", expiry_date="2026-12-31",
            buy_price=5.0, sell_price=10.0, quantity=50,
        )
        assert sid is not None
        assert expense is not None
        sid = int(sid)

        # Categories / lookups
        assert repos["supply"].get_all_categories()
        assert repos["supply"].get_subcategories_by_category("Medicine")
        assert item_name in repos["supply"].get_unique_supply_names("Medicine")

        # Read existing
        existing = repos["supply"].get_existing_supply(item_name, "Medicine", "Antibiotics", "2025-01-15", "2026-12-31", None)
        assert existing is not None
        assert existing["current_stock"] == 50

        # Search
        rows = repos["supply"].search_supplies()
        row = next(r for r in rows if r["supply_id"] == sid)
        assert row["item_name"] == item_name
        assert row["current_stock"] == 50
        assert row["purchase_date"] == "2025-01-15"

        # Stock batches: add_supply with purchase_date auto-creates an initial
        # stock batch of 50, so totals below include that auto-created batch.
        batch_id = repos["stock"].add_stock_batch(sid, None, "2025-02-01", 20, "Restock")
        assert batch_id is not None
        batches = repos["stock"].get_stock_batches(sid)
        assert any(b["batch_id"] == batch_id for b in batches)
        assert repos["stock"].get_total_stock_for_supply(sid) == 70, "50 initial + 20 restock"

        assert repos["stock"].update_stock_batch(int(batch_id), None, "2025-02-02", 25, "Restock 2")
        assert repos["stock"].get_total_stock_for_supply(sid) == 75, "50 initial + 25 restock"
        assert repos["stock"].delete_stock_batch(int(batch_id))

        # Update supply stock (returns expense details when quantity increases)
        ok, expense_details = repos["supply"].update_supply_stock(sid, 75, buy_price=5.0, sell_price=10.0,
                                                                  purchase_date="2025-02-10")
        assert ok
        assert expense_details is not None
        assert expense_details["quantity"] == 25

        # Full supply update + reorder level
        assert repos["supply"].set_reorder_level(item_name, 10)
        assert repos["supply"].update_supply(sid, _unique("Medicine2"), "Medicine", "Pain Relief",
                                             "2025-03-01", "2027-01-01", 6.0, 12.0, 80, None)

        # Delete supply (stock batch already removed; FK cascade clears stocks)
        assert repos["supply"].add_category("TestCat")
        assert repos["supply"].delete_category("TestCat")
        assert repos["supply"].delete_supply(sid)
        assert not any(r["supply_id"] == sid for r in repos["supply"].search_supplies())

    def test_category_subcategory_crud(self, fresh_db, repos):
        cat_name = _unique("Category")
        assert repos["supply"].add_category(cat_name)
        assert cat_name in repos["supply"].get_all_categories()

        assert repos["supply"].add_subcategory(cat_name, "SubA")
        assert "SubA" in repos["supply"].get_subcategories_by_category(cat_name)
        assert repos["supply"].delete_subcategory(cat_name, "SubA")
        assert repos["supply"].delete_category(cat_name)


# =============================================================================
# Appointments
# =============================================================================
class TestAppointmentsCRUD:
    def test_appointment_crud_lifecycle(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)

        assert repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up", "Scheduled",
                                                    "Routine", cid, pid)
        rows = repos["appointment"].get_appointments()
        appt = next(a for a in rows if a["pet_id"] == pid and a["appointment_date"] == "2030-06-01 10:00")
        appt_id = int(appt["appointment_id"])

        # Upcoming preview
        assert repos["appointment"].get_next_appointments(5)
        assert repos["appointment"].get_next_appointment_time()

        # Update
        assert repos["appointment"].update_appointment(appt_id, "2030-06-02 14:00", "Check-up",
                                                       "Rescheduled", "New time",
                                                       cid, pid)
        rows2 = repos["appointment"].get_appointments()
        updated = next(a for a in rows2 if a["appointment_id"] == appt_id)
        assert updated["appointment_date"] == "2030-06-02 14:00"

        # Delete
        assert repos["appointment"].delete_appointment(appt_id)
        assert not any(a["appointment_id"] == appt_id for a in repos["appointment"].get_appointments())

        assert repos["pet"].delete_pet(pid)
        assert repos["client"].delete_client(cid)


# =============================================================================
# Sales / Receipts
# =============================================================================
class TestSalesReceiptsCRUD:
    def test_sale_receipt_and_expense_lifecycle(self, fresh_db, repos):
        cid = _make_client(repos)
        sid, item_name = _make_supply(repos, quantity=20)

        # Sale receipt from quick purchase flow.
        receipt_id = repos["sales"].create_sale_receipt_for_quick_purchase(
            cid, "2025-02-15", [{"item_name": item_name, "quantity": 2, "price": 10.0}]
        )
        assert receipt_id is not None

        items = repos["sales"].get_receipt_items()
        assert any(int(r["receipt_id"]) == int(receipt_id) for r in items)
        sale_row = next(r for r in items if int(r["receipt_id"]) == int(receipt_id))
        assert sale_row["item_type"] == "Supply"
        assert sale_row["item_name"] == item_name
        assert sale_row["quantity"] == 2

        # Stock deducted.
        supplies = repos["supply"].search_supplies()
        supply_row = next(s for s in supplies if s["supply_id"] == sid)
        assert supply_row["current_stock"] == 18

        # General expense: its category and notes are persisted and surfaced in
        # the ledger (the line used to be bucketed as a generic "Other").
        assert repos["sales"].add_general_expense("2025-02-16", "Utilities", "Electricity", 150.0, "Monthly")
        expense_items = repos["sales"].get_receipt_items()
        expense_row = next(
            r for r in expense_items if r["item_name"] == "Electricity"
        )
        assert expense_row["item_type"] == "Utilities"
        assert expense_row["notes"] == "Monthly"
        assert expense_row["receipt_kind"] == "expense"
        assert str(expense_row["receipt_code"]).upper().startswith("EXPENSE")
        assert repos["sales"].get_receipt(expense_row["receipt_id"])["notes"] == "Monthly"

        # Delete receipts.
        assert repos["sales"].delete_receipt(int(receipt_id))
        assert not any(int(r["receipt_id"]) == int(receipt_id) for r in repos["sales"].get_receipt_items())

        assert repos["supply"].delete_supply(sid)
        assert repos["client"].delete_client(cid)


# =============================================================================
# Packages
# =============================================================================
class TestPackagesCRUD:
    def test_package_crud_lifecycle(self, fresh_db, repos):
        pkg_name = _unique("Package")
        pkg_id = repos["package"].add_package(pkg_name, "Test package", 100.0)
        assert pkg_id is not None

        assert any(p["package_id"] == pkg_id for p in repos["package"].get_all_packages())

        # Items: one service (Consultation exists in seed), one supply.
        db = repos["client"].get_connection()
        service_id = _lookup_id(db, "services_lookup", "service_name", "Consultation")
        assert service_id is not None
        sid, _ = _make_supply(repos, quantity=10)

        assert repos["package"].add_package_item(int(pkg_id), service_id=service_id, quantity=1, item_type="service")
        assert repos["package"].add_package_item(int(pkg_id), supply_id=sid, quantity=2, item_type="supply")

        items = repos["package"].get_package_items(int(pkg_id))
        assert len(items) == 2
        assert any(i.get("item_type") == "service" for i in items)
        assert any(i.get("item_type") == "supply" for i in items)

        # Remove one item.
        assert repos["package"].remove_package_item(int(items[0]["package_item_id"]))
        assert len(repos["package"].get_package_items(int(pkg_id))) == 1

        # Update + delete.
        assert repos["package"].update_package(int(pkg_id), _unique("Package2"), "Updated", 120.0)
        assert repos["package"].delete_package(int(pkg_id))
        assert not any(p["package_id"] == pkg_id for p in repos["package"].get_all_packages())

        assert repos["supply"].delete_supply(sid)


# =============================================================================
# Users & Role-based auth
# =============================================================================
class TestUsersAndAuthCRUD:
    def test_user_auth_lifecycle(self, fresh_db, repos):
        username = _unique("user")
        uid = repos["user"].add_user(username, "Secret123!", role_name="staff")
        assert uid is not None

        users = repos["user"].get_users()
        assert any(u["user_id"] == uid for u in users)

        roles = repos["user"].get_user_roles(int(uid))
        assert "staff" in roles, "User should have the staff role assigned"

        assert repos["user"].get_all_roles()[0]["role_name"] == "admin"

        # Auth success
        authed = repos["user"].authenticate_user(username, "Secret123!")
        assert authed is not None
        assert authed["username"] == username
        assert "user_id" in authed

        # Auth failure
        assert repos["user"].authenticate_user(username, "wrong-password") is None
        assert repos["user"].authenticate_user("nonexistent_user", "x") is None

        # Password update
        assert repos["user"].update_user_password(int(uid), "NewPass456!")
        assert repos["user"].authenticate_user(username, "NewPass456!") is not None
        assert repos["user"].authenticate_user(username, "Secret123!") is None

        # Delete
        assert repos["user"].delete_user(int(uid))
        assert not any(u["user_id"] == uid for u in repos["user"].get_users())


# =============================================================================
# Audit trail & activity logs
# =============================================================================
class TestAuditAndLogsCRUD:
    def test_audit_record_and_retrieval(self, fresh_db, repos):
        header_id = repos["audit"].record_change("owners", 42, [
            {"field_name": "first_name", "old_value": "Old", "new_value": "New"},
            {"field_name": "phone_number", "old_value": "1", "new_value": "2"},
        ], user_id=None)
        assert header_id is not None

        recent = repos["audit"].get_recent_changes()
        assert any(int(c["change_header_id"]) == int(header_id) for c in recent)

        details = repos["audit"].get_change_details(int(header_id))
        assert len(details) == 2

        record_changes = repos["audit"].get_changes_for_record("owners", 42)
        assert any(int(c["change_header_id"]) == int(header_id) for c in record_changes)
        assert record_changes[0]["details"]

    def test_activity_log_lifecycle(self, fresh_db, repos):
        # Log type
        log_types = repos["log"].get_log_types()
        assert log_types
        create_type = next(lt for lt in log_types if lt["log_action"] == "CREATE")

        new_type = _unique("ACTION")
        assert repos["log"].add_log_type(new_type)
        assert any(lt["log_action"] == new_type for lt in repos["log"].get_log_types())

        # Add log entry
        log_id = repos["log"].add_log(None, create_type["log_type_id"], "visit", 99, "Created visit")
        assert log_id is not None

        logs = repos["log"].get_logs()
        assert any(l["log_id"] == log_id for l in logs)

        entity_logs = repos["log"].get_logs_for_entity("visit", 99)
        assert any(l["log_id"] == log_id for l in entity_logs)

        # Delete single + bulk clear
        assert repos["log"].delete_log(int(log_id))
        assert not any(l["log_id"] == log_id for l in repos["log"].get_logs())

        assert repos["log"].add_log(None, create_type["log_type_id"], "visit", 1, "A")
        assert repos["log"].clear_logs()
        assert repos["log"].get_logs(limit=100) == []

        # Delete added log type
        added = next(lt for lt in repos["log"].get_log_types() if lt["log_action"] == new_type)
        assert repos["log"].delete_log_type(added["log_type_id"])


# =============================================================================
# Cascade integrity (regression: delete_client must cascade without FK errors)
# =============================================================================
class TestCascadeIntegrity:
    def test_delete_client_cascades_pets_visits_receipts(self, fresh_db, repos):
        cid = _make_client(repos)
        pid = _make_pet(repos, cid)

        sid, item_name = _make_supply(repos, quantity=10)
        result = repos["visit"].add_visit(
            visit_date="2025-03-01", diagnosis="Cascade", consult=True, notes="",
            pet_id=pid, items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
        )
        assert result is not None
        assert isinstance(result, int)
        receipt_id = int(result)

        # Confirm data is visible before deletion.
        assert any(c["client_id"] == cid for c in repos["client"].get_clients())
        assert repos["pet"].get_pets_for_client(cid)
        assert any(int(r["receipt_id"]) == receipt_id for r in repos["sales"].get_receipt_items())

        # CRITICAL: deleting the owner cascades pets -> visits -> receipts.
        assert repos["client"].delete_client(cid), "delete_client should succeed without FK violations"

        assert not any(c["client_id"] == cid for c in repos["client"].get_clients())
        assert not repos["pet"].get_pets_for_client(cid)
        assert not any(int(r["receipt_id"]) == receipt_id for r in repos["sales"].get_receipt_items())

        assert repos["supply"].delete_supply(sid)
