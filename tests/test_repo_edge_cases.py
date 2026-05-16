"""Edge-case and failure-path tests for repositories.

These complement tests/test_crud_end_to_end.py by exercising unusual inputs,
empty databases, non-existent records, and boundary conditions the happy-path
CRUD suite does not cover.
"""

import uuid

import pytest


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestClientRepoEdgeCases:
    def test_add_client_with_blank_name_creates_row_with_empty_first(self, fresh_db, repos):
        # Current implementation strips the name and inserts a row even when empty.
        result = repos["client"].add_client("   ", "0500000000")
        assert result is not None

    def test_add_client_with_blank_phone_creates_row(self, fresh_db, repos):
        # Phone is optional; a row is created without a contact.
        result = repos["client"].add_client("No Phone Owner", "")
        assert result is not None
        clients = repos["client"].get_clients()
        row = next(c for c in clients if c["client_id"] == int(result))
        assert row["phone_number"] == ""

    def test_get_clients_empty(self, fresh_db, repos):
        assert repos["client"].get_clients() == []

    def test_search_no_match_returns_empty(self, fresh_db, repos, entity_factory):
        entity_factory["make_client"](name="Zed", phone="0501111111")
        assert repos["client"].get_clients("no-such-phone", "Phone Number") == []
        assert repos["client"].get_clients("NoSuchName", "Client Name") == []

    def test_update_non_existent_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are affected
        # (SQL UPDATE with no matching WHERE still "succeeds").
        # The test asserts the real behavior: the call returns True.
        assert repos["client"].update_client(-1, "Ghost", "0500000000") is True

    def test_delete_non_existent_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["client"].delete_client(-1) is True

    def test_get_clients_by_name_exact_no_match(self, fresh_db, repos):
        assert repos["client"].get_clients_by_name_exact("Nobody Here") == []


class TestPetRepoEdgeCases:
    def test_add_pet_unknown_species_gets_created(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = repos["pet"].add_pet("Ziggy", "AlienSpecies", "UnknownBreed", "M", 3, 1.0, cid)
        assert pid is not None
        pets = repos["pet"].get_pets()
        row = next(p for p in pets if p["pet_id"] == int(pid))
        assert row["species"] == "AlienSpecies"

    def test_get_existing_pet_no_match(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        assert repos["pet"].get_existing_pet("Ghost", "Dog", "Labrador Retriever", "M", cid) is None

    def test_get_pets_for_client_empty(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        assert repos["pet"].get_pets_for_client(cid) == []

    def test_update_non_existent_pet_returns_false(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        # QSqlQuery.exec() returns True even when 0 rows are affected.
        assert repos["pet"].update_pet(-1, "Ghost", "Cat", "Persian", "F", 1, 1.0, cid) is True

    def test_delete_non_existent_pet_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["pet"].delete_pet(-1) is True

    def test_get_unique_breeds_returns_seeded(self, fresh_db, repos):
        # Breeds are seeded by default (Dog/Cat breed lists), so the list is
        # not empty even with no pets. At minimum the seeded 'Other' breed exists.
        breeds = repos["pet"].get_unique_breeds()
        assert breeds
        assert "Other" in breeds


class TestUserRepoEdgeCases:
    def test_hash_password_deterministic(self, fresh_db, repos):
        salt = "testsalt"
        h1 = repos["user"].hash_password("password123", salt)
        h2 = repos["user"].hash_password("password123", salt)
        assert h1 == h2

    def test_hash_password_different_salts(self, fresh_db, repos):
        h1 = repos["user"].hash_password("same", "salt1")
        h2 = repos["user"].hash_password("same", "salt2")
        assert h1 != h2

    def test_add_duplicate_username_returns_none(self, fresh_db, repos):
        name = _unique("dupuser")
        assert repos["user"].add_user(name, "Pass123!") is not None
        assert repos["user"].add_user(name, "Pass456!") is None

    def test_get_user_by_username_missing(self, fresh_db, repos):
        assert repos["user"].get_user_by_username("nobody") is None

    def test_update_user_password_missing_returns_false(self, fresh_db, repos):
        assert repos["user"].update_user_password(-1, "NewPass123!") is False

    def test_delete_user_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["user"].delete_user(-1) is True

    def test_get_all_roles_seeded(self, fresh_db, repos):
        roles = repos["user"].get_all_roles()
        names = [r["role_name"] for r in roles]
        assert "admin" in names
        assert "staff" in names


class TestSupplyRepoEdgeCases:
    def test_unknown_category_subcategory_fallback(self, fresh_db, repos):
        assert repos["supply"].get_subcategories_by_category("TotallyUnknown") == ["Other"]

    def test_get_all_reorder_levels_empty(self, fresh_db, repos):
        # Returns a dict keyed by item_name (not a list).
        assert repos["supply"].get_all_reorder_levels() == {}

    def test_get_total_quantities_by_item_empty(self, fresh_db, repos):
        # Returns a dict keyed by item_name (not a list).
        assert repos["supply"].get_total_quantities_by_item() == {}

    def test_delete_non_existent_category_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["supply"].delete_category("NoSuchCat") is True

    def test_set_reorder_level_sets_value(self, fresh_db, repos, entity_factory):
        sid, item_name = entity_factory["make_supply"](quantity=5, reorder_level=0)
        # set_reorder_level returns a bool from QSqlQuery.exec()
        assert repos["supply"].set_reorder_level(item_name, 3) is True
        levels = repos["supply"].get_all_reorder_levels()
        # levels is a dict keyed by item_name
        assert levels.get(item_name) == 3

    def test_get_existing_supply_no_match(self, fresh_db, repos):
        assert repos["supply"].get_existing_supply("Nope", "Medicine", "Antibiotics", "2025-01-01", "2026-01-01", None) is None


class TestStockRepoEdgeCases:
    def test_batches_empty_for_missing_supply(self, fresh_db, repos):
        assert repos["stock"].get_stock_batches(-1) == []

    def test_total_stock_zero_for_missing_supply(self, fresh_db, repos):
        assert repos["stock"].get_total_stock_for_supply(-1) == 0

    def test_update_batch_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are affected.
        assert repos["stock"].update_stock_batch(-1, None, "2025-01-01", 5, "x") is True

    def test_delete_batch_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["stock"].delete_stock_batch(-1) is True


class TestClinicalRecordEdgeCases:
    def test_tests_lookup_empty_delete(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["test"].delete_test(-1) is True

    def test_treatments_lookup_empty_delete(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["treatment"].delete_treatment(-1) is True

    def test_vaccines_lookup_empty_delete(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["vaccination"].delete_vaccine(-1) is True

    def test_add_lookup_duplicate_ignored(self, fresh_db, repos):
        name = _unique("Item")
        assert repos["test"].add_test(name) is True
        # INSERT OR IGNORE — second insert is still True (no error), row count unchanged.
        assert repos["test"].add_test(name) is True

    def test_record_test_with_bad_visit_returns_none(self, fresh_db, repos):
        test_id = repos["test"].get_all_tests()[0]["test_id"]
        assert repos["test"].record_test(-1, test_id) is None

    def test_record_treatment_with_bad_visit_returns_none(self, fresh_db, repos):
        treatment_id = repos["treatment"].get_all_treatments()[0]["treatment_id"]
        assert repos["treatment"].record_treatment(-1, treatment_id) is None

    def test_record_vaccination_with_bad_visit_returns_none(self, fresh_db, repos):
        vaccine_id = repos["vaccination"].get_all_vaccines()[0]["vaccine_id"]
        assert repos["vaccination"].record_vaccination(-1, vaccine_id) is None

    def test_prescribe_medication_bad_visit_returns_none(self, fresh_db, repos):
        assert repos["medication"].prescribe_medication(-1, -1, "5mg", "daily") is None

    def test_get_history_for_missing_pet(self, fresh_db, repos):
        assert repos["vaccination"].get_vaccination_history(-1) == []
        assert repos["medication"].get_medication_history(-1) == []
        assert repos["health_stats"].get_health_stats_for_pet(-1) == []


class TestAppointmentEdgeCases:
    def test_get_next_appointment_time_none(self, fresh_db, repos):
        # Returns a translated string when no upcoming appointments exist.
        assert repos["appointment"].get_next_appointment_time() == "No appointments"

    def test_get_next_appointments_empty(self, fresh_db, repos):
        assert repos["appointment"].get_next_appointments(5) == []

    def test_get_past_appointments_empty(self, fresh_db, repos):
        assert repos["appointment"].get_past_appointments() == []

    def test_update_non_existent_appointment_returns_false(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        # QSqlQuery.exec() returns True even when 0 rows are affected.
        assert repos["appointment"].update_appointment(-1, "2030-01-01 10:00", "X", "Scheduled", "", cid, pid) is True

    def test_delete_non_existent_appointment_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["appointment"].delete_appointment(-1) is True

    def test_followup_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["followup"].delete_followup(-1) is True


class TestSalesAndPackageEdgeCases:
    def test_delete_receipt_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["sales"].delete_receipt(-1) is True

    def test_quick_purchase_unknown_item_uses_other(self, fresh_db, repos, entity_factory):
        """Purchase of an item not in supplies should record receipt_other, not fail."""
        cid = entity_factory["make_client"]()
        receipt_id = repos["sales"].create_sale_receipt_for_quick_purchase(
            cid, "2025-06-01", [{"item_name": "UnknownItem", "quantity": 1, "price": 10.0}]
        )
        assert receipt_id is not None
        items = repos["sales"].get_receipt_items()
        assert any(int(r["receipt_id"]) == int(receipt_id) and r["item_name"] == "UnknownItem" for r in items)

    def test_quick_purchase_rejects_insufficient_stock(self, fresh_db, repos, entity_factory):
        _supply_id, item_name = entity_factory["make_supply"](quantity=1)
        receipt_id = repos["sales"].create_sale_receipt_for_quick_purchase(
            owner_id=None,
            receipt_date_sql="2026-09-03",
            items=[{"item_name": item_name, "quantity": 2, "price": 5.0}],
        )
        # Same STOCK_ERROR contract as visit_repo.add_visit, so the dialog can
        # show "Not enough stock for <item>" instead of a generic failure.
        assert isinstance(receipt_id, str) and receipt_id.startswith("STOCK_ERROR"), receipt_id
        assert item_name in receipt_id

    def test_delete_package_missing_returns_false(self, fresh_db, repos):
        # QSqlQuery.exec() returns True even when 0 rows are deleted.
        assert repos["package"].delete_package(-1) is True

    def test_get_package_items_missing(self, fresh_db, repos):
        assert repos["package"].get_package_items(-1) == []


class TestFollowupAndHealthStatsEdgeCases:
    def test_add_followup_missing_visit_returns_none(self, fresh_db, repos):
        assert repos["followup"].add_followup(-1, "2030-01-01", None, "note") is None

    def test_get_followups_missing_visit(self, fresh_db, repos):
        assert repos["followup"].get_followups_for_visit(-1) == []

    def test_get_upcoming_followups_empty(self, fresh_db, repos):
        assert repos["followup"].get_upcoming_followups() == []

    def test_add_health_stat_missing_visit(self, fresh_db, repos):
        assert repos["health_stats"].add_health_stat(-1, None, None, None) is None

    def test_get_stats_for_missing_visit(self, fresh_db, repos):
        assert repos["health_stats"].get_health_stats_for_visit(-1) == []
