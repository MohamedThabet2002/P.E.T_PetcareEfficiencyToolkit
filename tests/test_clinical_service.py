"""Tests for src/core/services/clinical_service.py"""

import pytest

import src.core.services.clinical_service as clinical_service


class TestProcessFullClinicalEntry:
    def test_new_client_pet_and_visit(self, fresh_db, repos, entity_factory):
        """Happy path: creates new client, pet and visit together."""
        owner_data = {"name": "New Owner", "phone": "0501112222"}
        pet_data = {"name": "Buddy", "species": "Dog", "breed": "Labrador Retriever",
                    "gender": "M", "age": 12, "weight": 20.0}
        visit_data = {"date": "2025-06-01", "diagnosis": "Allergy", "is_consult": True,
                      "notes": "Initial checkup"}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data
        )
        assert success is True
        assert isinstance(result, int)

        # Client was created and searchable
        clients = repos["client"].get_clients()
        assert any(c["client_id"] == int(result) or c["client_id"] is not None for c in clients)

    def test_existing_client_merged_by_name_and_phone(self, fresh_db, repos, entity_factory):
        """When client already exists with same name+phone, no duplicate is created."""
        cid = entity_factory["make_client"](name="Existing Owner", phone="0505556666")
        owner_data = {"name": "Existing Owner", "phone": "0505556666"}
        pet_data = {"name": "Milo", "species": "Cat", "breed": "Persian",
                    "gender": "F", "age": 6, "weight": 4.0}
        visit_data = {"date": "2025-06-01", "diagnosis": "Dental", "is_consult": False,
                      "notes": ""}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data
        )
        assert success is True

        # Still exactly one client with that name
        matches = repos["client"].get_clients_by_name_exact("Existing Owner")
        assert len(matches) == 1
        assert matches[0]["client_id"] == cid

    def test_existing_pet_gets_updated_not_duplicated(self, fresh_db, repos, entity_factory):
        """A second entry for same pet updates age/weight instead of creating duplicate."""
        cid = entity_factory["make_client"](name="Pet Owner", phone="0507778888")
        pid = entity_factory["make_pet"](cid, name="Rex", age=12, weight=20.0)

        owner_data = {"name": "Pet Owner", "phone": "0507778888"}
        pet_data = {"name": "Rex", "species": "Dog", "breed": "Labrador Retriever",
                    "gender": "M", "age": 24, "weight": 30.0}
        visit_data = {"date": "2025-06-02", "diagnosis": "Follow-up", "is_consult": False,
                      "notes": ""}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data
        )
        assert success is True

        # Same pet, still one pet for that client
        pets = repos["pet"].get_pets_for_client(cid)
        assert len(pets) == 1
        assert pets[0]["pet_id"] == pid

    def test_existing_pet_breed_species_and_gender_changes_are_saved(
            self, fresh_db, repos, entity_factory):
        """Every edited pet field lands on the existing pet, not a duplicate.

        The Add Visit dialog confirms each of these edits before proceeding,
        so the message it shows has to be true.
        """
        cid = entity_factory["make_client"](name="Edit Owner", phone="0502223333")
        pid = entity_factory["make_pet"](cid, name="Rex", species="Dog",
                                         breed="Labrador Retriever", gender="M",
                                         age=12, weight=20.0)

        success, _ = clinical_service.process_full_clinical_entry(
            {"name": "Edit Owner", "phone": "0502223333"},
            {"name": "Rex", "species": "Cat", "breed": "Persian",
             "gender": "F", "age": 24, "weight": 30.0},
            {"date": "2025-06-07", "diagnosis": "Recheck", "is_consult": False,
             "notes": ""},
        )
        assert success is True

        pets = repos["pet"].get_pets_for_client(cid)
        assert len(pets) == 1
        pet = pets[0]
        assert pet["pet_id"] == pid
        assert pet["species"] == "Cat"
        assert pet["breed"] == "Persian"
        assert pet["gender"] == "F"
        assert pet["age_months"] == 24
        assert pet["weight"] == 30.0

    def test_visit_with_items_deducts_stock(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"](name="Stock Buyer", phone="0509990000")
        pid = entity_factory["make_pet"](cid, name="Rex")
        sid, item_name = entity_factory["make_supply"](quantity=10)

        owner_data = {"name": "Stock Buyer", "phone": "0509990000"}
        pet_data = {"name": "Rex", "species": "Dog", "breed": "Labrador Retriever",
                    "gender": "M", "age": 12, "weight": 25.0}
        visit_data = {"date": "2025-06-03", "diagnosis": "Checkup", "is_consult": True,
                      "notes": ""}
        items = [{"item_name": item_name, "quantity": 2, "price": 10.0}]

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data, items=items
        )
        assert success is True

        # Stock was deducted from 10 to 8
        supplies = repos["supply"].search_supplies()
        row = next(s for s in supplies if s["supply_id"] == sid)
        assert row["current_stock"] == 8

    def test_stock_error_returns_failure(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"](name="Over Buyer", phone="0501231234")
        pid = entity_factory["make_pet"](cid, name="Rex")
        sid, item_name = entity_factory["make_supply"](quantity=3)

        owner_data = {"name": "Over Buyer", "phone": "0501231234"}
        pet_data = {"name": "Rex", "species": "Dog", "breed": "Labrador Retriever",
                    "gender": "M", "age": 12, "weight": 25.0}
        visit_data = {"date": "2025-06-04", "diagnosis": "X", "is_consult": False,
                      "notes": ""}
        items = [{"item_name": item_name, "quantity": 999, "price": 10.0}]

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data, items=items
        )
        assert success is False
        assert isinstance(result, str)
        assert result.startswith("STOCK_ERROR")

    def test_missing_client_returns_failure(self, fresh_db, repos, monkeypatch):
        """If client creation fails, returns False with error message."""
        original_add_client = repos["client"].add_client
        monkeypatch.setattr(repos["client"], "add_client", lambda *a, **kw: None)

        owner_data = {"name": "Failing Owner", "phone": "0500000000"}
        visit_data = {"date": "2025-06-05", "diagnosis": "X", "is_consult": False,
                      "notes": ""}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, None, visit_data
        )
        assert success is False
        assert "client" in result.lower()

    def test_no_pet_data_fails_gracefully(self, fresh_db, repos, entity_factory):
        """Visit without pet data fails gracefully.

        The `visits.pet_id` column is NOT NULL, so `visit_repo.add_visit`
        returns None when pet_id is None; the service reports that failure.
        """
        owner_data = {"name": "No Pet Owner", "phone": "0503334444"}
        pet_data = None
        visit_data = {"date": "2025-06-06", "diagnosis": "Consultation only",
                      "is_consult": True, "notes": "No pet provided"}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data
        )
        assert success is False
        assert result is None


class TestScheduleFollowupAfterEntry:
    def test_schedules_followup_for_just_recorded_visit(self, fresh_db, repos, entity_factory):
        """Happy path: follow-up lands on the visit created for this owner/date."""
        owner_name = "Followup Owner"
        phone = "0501002003"
        visit_date = "2025-06-10"

        success, _ = clinical_service.process_full_clinical_entry(
            {"name": owner_name, "phone": phone},
            {"name": "Rex", "species": "Dog", "breed": "Labrador Retriever",
             "gender": "M", "age": 12, "weight": 25.0},
            {"date": visit_date, "diagnosis": "Checkup", "is_consult": False,
             "notes": ""},
        )
        assert success is True

        followup_id = clinical_service.schedule_followup_after_entry(
            owner_name, phone, visit_date, "2025-07-01 10:00", notes="Recheck"
        )
        assert followup_id is not None

        # Follow-up is linked to the right visit
        visits = repos["visit"].get_visits()
        visit = next(v for v in visits if v["visit_id"] is not None)
        followups = repos["followup"].get_followups_for_visit(visit["visit_id"])
        assert any(f["followup_id"] == int(followup_id) for f in followups)

    def test_unknown_owner_returns_none(self, fresh_db, repos):
        """No matching owner/visit means no follow-up is created."""
        result = clinical_service.schedule_followup_after_entry(
            "Nobody", "0500000000", "2025-06-10", "2025-07-01 10:00"
        )
        assert result is None

    def test_missing_followup_date_returns_none(self, fresh_db, repos, entity_factory):
        """A missing follow-up date short-circuits without a DB lookup."""
        result = clinical_service.schedule_followup_after_entry(
            "Owner", "0500000000", "2025-06-10", None
        )
        assert result is None


class TestFullClinicalEntryIntegration:
    """End-to-end service flow: client+pet+visit+clinical records+billing+follow-up."""

    def test_creates_full_entry_with_clinical_records_and_billing(
            self, fresh_db, repos, entity_factory):
        """A rich entry lands everything on one visit: client, pet, records,
        receipt with consultation+item lines, stock deduction, and audit."""
        test_id = repos["test"].add_test("Blood Panel")
        assert test_id is not None
        treatment_id = repos["treatment"].add_treatment("Physiotherapy")
        assert treatment_id is not None
        vaccine_id = repos["vaccination"].add_vaccine("Rabies")
        assert vaccine_id is not None
        sid, item_name = entity_factory["make_supply"](quantity=5, sell_price=20.0)

        import src.core.repositories.lookup_repo as lookup_repo
        stat_type_id, state_id = None, None
        if lookup_repo.get_stat_types():
            stat_type_id, _ = lookup_repo.get_stat_types()[0]
        if lookup_repo.get_states(category_id=1):
            state_id, _ = lookup_repo.get_states(category_id=1)[0]

        owner_data = {"name": "Full Owner", "phone": "0506667777"}
        pet_data = {"name": "Milo", "species": "Cat", "breed": "Persian",
                    "gender": "M", "age": 12, "weight": 4.5}
        visit_data = {"date": "2025-07-15", "diagnosis": "Arthritis",
                      "is_consult": True, "notes": "n/a"}

        success, result = clinical_service.process_full_clinical_entry(
            owner_data, pet_data, visit_data,
            items=[{"item_name": item_name, "quantity": 1, "price": 15.0}],
            health_stats=([{"stat_type_id": stat_type_id, "state_id": state_id,
                            "extra_note": "mild"}] if stat_type_id else []),
            tests=[{"test_id": test_id, "state_id": state_id}],
            treatments=[treatment_id],
            vaccinations=[vaccine_id],
            medications=[{"supply_id": sid, "dosage": "2x daily",
                          "instructions": "after meals"}],
        )
        assert success is True

        client = next(c for c in repos["client"].get_clients()
                      if c["owner_name"] == "Full Owner")
        pets = repos["pet"].get_pets_for_client(client["client_id"])
        assert len(pets) == 1
        pet_id = pets[0]["pet_id"]
        visits = repos["visit"].get_visits()
        visits_for_pet = [v for v in visits if v["pet_id"] == pet_id]
        assert len(visits_for_pet) == 1
        visit_id = visits_for_pet[0]["visit_id"]

        # Clinical records for the visit
        meds = repos["medication"].get_medications_for_visit(visit_id)
        assert any(m["item_name"] == item_name for m in meds)
        tests = repos["test"].get_tests_for_visit(visit_id)
        assert any(t["test_id"] == test_id for t in tests)
        treatments = repos["treatment"].get_treatments_for_visit(visit_id)
        assert any(t["treatment_id"] == treatment_id for t in treatments)
        vaccination = repos["vaccination"].get_vaccinations_for_visit(visit_id)
        assert any(v["vaccine_id"] == vaccine_id for v in vaccination)

        # Stock deducted 5 -> 4
        supplies = repos["supply"].search_supplies()
        row = next(s for s in supplies if s["supply_id"] == sid)
        assert row["current_stock"] == 4

        # Receipt totals: item(15) + consultation fee
        from src.config.constants import DEFAULT_CONSULT_FEE
        from src.utils.settings_manager import SettingsManager
        consult_fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
        receipt_rows = repos["sales"].get_receipt_items()
        assert any(r["total_amount"] == 15.0 + consult_fee for r in receipt_rows)

    def test_discount_in_visit_data_reaches_the_receipt(self, fresh_db, repos):
        """visit_data['discount'] is cash off the bill, not a percentage."""
        from src.config.constants import DEFAULT_CONSULT_FEE
        from src.utils.settings_manager import SettingsManager
        consult_fee = float(SettingsManager.get("consultation_fee",
                                                 DEFAULT_CONSULT_FEE))

        success, receipt_id = clinical_service.process_full_clinical_entry(
            {"name": "Discounted Owner", "phone": "0509998888"},
            {"name": "Bella", "species": "Dog", "breed": "Beagle",
             "gender": "F", "age": 3, "weight": 9.0},
            {"date": "2025-07-16", "diagnosis": "Check-up",
             "is_consult": True, "notes": "", "discount": 12.5},
        )
        assert success is True

        receipt = repos["sales"].get_receipt(receipt_id)
        assert receipt is not None
        assert receipt["visit_id"] is not None
        assert float(receipt["discount"]) == pytest.approx(12.5)
        assert float(receipt["total_price"]) == pytest.approx(consult_fee - 12.5)

    def test_followup_chain_after_full_entry(self, fresh_db, repos, entity_factory):
        """process_full_clinical_entry then schedule_followup_after_entry leaves
        one follow-up linked to that exact visit."""
        owner_name, phone, visit_date = "Chain Owner", "0508889999", "2025-07-20"
        success, _ = clinical_service.process_full_clinical_entry(
            {"name": owner_name, "phone": phone},
            {"name": "Bella", "species": "Dog", "breed": "Poodle",
             "gender": "F", "age": 24, "weight": 8.0},
            {"date": visit_date, "diagnosis": "Allergy", "is_consult": False,
             "notes": ""},
        )
        assert success is True

        followup_id = clinical_service.schedule_followup_after_entry(
            owner_name, phone, visit_date, "2025-08-01 09:00", notes="monitor"
        )
        assert followup_id is not None

        owners = repos["client"].get_clients_by_name_exact(owner_name)
        owner_id = owners[0]["client_id"]
        visits = repos["visit"].get_recent_visits_for_client(owner_id, limit=10)
        assert visits, "expected at least one visit"
        linked = repos["followup"].get_followups_for_visit(visits[0]["visit_id"])
        assert any(f["followup_id"] == int(followup_id) for f in linked)
