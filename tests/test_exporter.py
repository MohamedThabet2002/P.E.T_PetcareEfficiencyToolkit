"""Tests for src/core/exporter.py (Excel / CSV data export engine)."""

import csv

import pytest

from src.core import exporter, importer
from src.core.repositories import (
    client_repo,
    payment_repo,
    pet_repo,
    sales_repo,
    supply_repo,
    visit_repo,
)


@pytest.fixture
def exporter_db(fresh_db, monkeypatch):
    """Redirects the repos the exporter calls to the fresh test DB."""
    for module in (client_repo, pet_repo, supply_repo, visit_repo, sales_repo,
                   payment_repo):
        monkeypatch.setattr(module, "get_connection", lambda: fresh_db, raising=False)
    return fresh_db


def _seed_owner(name="Ahmed Ali", phone="01001234567", notes=""):
    return client_repo.add_client(name, phone, notes=notes)


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


# ------------------------------------------------------------------ Rows ---
class TestExportRows:
    def test_headers_match_the_import_template(self, exporter_db):
        _seed_owner()
        for entity_key in exporter.EXPORT_KEYS:
            headers, _rows = exporter.export_rows(entity_key)
            template_headers, _sample = importer.template_rows(entity_key)
            assert headers == template_headers

    def test_unknown_entity_raises(self, exporter_db):
        with pytest.raises(KeyError):
            exporter.export_rows("nope")

    def test_empty_database_yields_headers_only(self, exporter_db):
        headers, rows = exporter.export_rows("owners")
        assert headers == ["Owner Name", "Phone Number", "Notes"]
        assert rows == []

    def test_owner_rows_carry_phone_and_notes(self, exporter_db):
        _seed_owner(notes="VIP")
        _headers, rows = exporter.export_rows("owners")
        assert rows == [["Ahmed Ali", "01001234567", "VIP"]]

    def test_supplier_rows_carry_contact_details(self, exporter_db):
        from src.core.repositories import supplier_repo
        supplier_repo.add_supplier("Acme Vet", phone="01001234567",
                                   location="Cairo", notes="Bulk orders")
        _headers, rows = exporter.export_rows("suppliers")
        assert rows == [["Acme Vet", "01001234567", "Cairo", "Bulk orders"]]

    def test_pet_rows_carry_the_owner_phone(self, exporter_db):
        client_id = _seed_owner()
        pet_repo.add_pet("Rex", "Dog", "Labrador", "Male", 24, 25.5, client_id)
        _headers, rows = exporter.export_rows("pets")
        assert rows == [["Rex", "Ahmed Ali", "01001234567", "Dog", "Labrador",
                         "Male", 24, 25.5]]

    def test_supply_quantity_is_the_batch_total(self, exporter_db):
        supply_repo.add_supply("Amox", "Meds", "Antibiotics", quantity=5,
                               sell_price=25, buy_price=10, audit_user_id=None)
        _headers, rows = exporter.export_rows("supplies")
        assert len(rows) == 1
        row = dict(zip(importer.template_rows("supplies")[0], rows[0]))
        assert row["Item Name"] == "Amox"
        assert row["Quantity"] == 5  # purchased, not what is left after sales
        assert row["Sell Price"] == 25

    def test_visit_rows_format_supplies_and_consultation(self, exporter_db):
        client_id = _seed_owner()
        pet_id = pet_repo.add_pet("Rex", "Dog", None, None, None, None, client_id)
        supply_repo.add_supply("Amox", "Meds", "Antibiotics", quantity=10,
                               sell_price=25, audit_user_id=None)
        visit_repo.add_visit("2025-01-15 10:00:00", "Otitis", True, "Recheck",
                             pet_id=pet_id, client_id=client_id,
                             items=[{"item_name": "Amox", "quantity": 2}],
                             receipt_code="VISIT-9001", audit_user_id=None)

        _headers, rows = exporter.export_rows("visits")
        assert len(rows) == 1
        row = dict(zip(importer.template_rows("visits")[0], rows[0]))
        assert row["Owner Name"] == "Ahmed Ali"
        assert row["Phone Number"] == "01001234567"
        assert row["Pet Name"] == "Rex"
        assert row["Consultation"] == "Yes"
        assert row["Supplies"] == "Amox x2"

    def test_visit_without_consultation_or_supplies(self, exporter_db):
        client_id = _seed_owner()
        pet_id = pet_repo.add_pet("Rex", "Dog", None, None, None, None, client_id)
        visit_repo.add_visit("2025-01-15 10:00:00", "Healthy", False, "",
                             pet_id=pet_id, client_id=client_id,
                             receipt_code="VISIT-9002", audit_user_id=None)
        _headers, rows = exporter.export_rows("visits")
        row = dict(zip(importer.template_rows("visits")[0], rows[0]))
        assert row["Consultation"] == "No"
        assert row["Supplies"] == ""
        assert row["Temperature"] == ""

    def test_export_counts(self, exporter_db):
        _seed_owner("One")
        _seed_owner("Two")
        pet_repo.add_pet("Rex", "Dog", None, None, None, None, 1)
        assert exporter.export_counts()["owners"] == 2
        assert exporter.export_counts()["pets"] == 1
        assert exporter.export_counts()["visits"] == 0

    def test_visit_rows_carry_the_receipt_code(self, exporter_db):
        client_id = _seed_owner()
        pet_id = pet_repo.add_pet("Rex", "Dog", None, None, None, None, client_id)
        visit_repo.add_visit("2025-01-15 10:00:00", "Otitis", True, "",
                             pet_id=pet_id, client_id=client_id,
                             receipt_code="VISIT-9004", audit_user_id=None)

        _headers, rows = exporter.export_rows("visits")
        row = dict(zip(importer.template_rows("visits")[0], rows[0]))
        assert row["Receipt Code"] == "VISIT-9004"

    def test_expense_rows_carry_the_receipt_code(self, exporter_db):
        sales_repo.add_general_expense(
            "2025-01-20", "Rent", "Monthly clinic rent", 5000.0,
            receipt_code="EXPENSE-202501-0007")

        _headers, rows = exporter.export_rows("expenses")
        row = dict(zip(importer.template_rows("expenses")[0], rows[0]))
        assert row["Receipt Code"] == "EXPENSE-202501-0007"

    def test_retail_rows_carry_code_owner_and_items(self, exporter_db):
        client_id = _seed_owner()
        supply_repo.add_supply("Amox", "Meds", "Antibiotics", quantity=10,
                               sell_price=25, audit_user_id=None)
        sales_repo.create_sale_receipt_for_quick_purchase(
            client_id, "2025-01-20 15:00:00",
            [{"item_name": "Amox", "quantity": 2, "price": 25}],
            receipt_code="RETAIL-0001", paid=False)

        _headers, rows = exporter.export_rows("retail_sales")
        assert len(rows) == 1
        row = dict(zip(importer.template_rows("retail_sales")[0], rows[0]))
        assert row["Receipt Code"] == "RETAIL-0001"
        assert row["Owner Name"] == "Ahmed Ali"
        assert row["Phone Number"] == "01001234567"
        assert row["Items"] == "Amox x2"


# ----------------------------------------------------------------- Files ---
class TestWriteEntityFile:
    def test_csv_carries_headers_and_data(self, exporter_db, tmp_path):
        _seed_owner(notes="VIP")
        path, count = exporter.write_entity_file(tmp_path / "owners.csv", "owners")

        assert count == 1
        rows = _read_csv(path)
        assert rows[0] == ["Owner Name", "Phone Number", "Notes"]
        assert rows[1] == ["Ahmed Ali", "01001234567", "VIP"]

    def test_xlsx_keeps_the_template_layout_and_sheets(self, exporter_db, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        _seed_owner(notes="VIP")
        path, count = exporter.write_entity_file(tmp_path / "owners.xlsx", "owners")

        workbook = openpyxl.load_workbook(str(path))
        assert workbook.sheetnames == [importer.TEMPLATE_SHEET_NAME,
                                       importer.INSTRUCTIONS_SHEET_NAME]
        sheet = workbook[importer.TEMPLATE_SHEET_NAME]
        assert [cell.value for cell in sheet[1]] == ["Owner Name", "Phone Number", "Notes"]
        assert count == 1
        assert sheet.max_row == 2
        # The filter must cover the exported rows too, not just the header.
        assert sheet.auto_filter.ref == "A1:C2"
        # Header hover help survives so the file still teaches its own columns.
        assert sheet["A1"].comment is not None

    def test_missing_suffix_uses_the_requested_format(self, exporter_db, tmp_path):
        _seed_owner()
        xlsx_path, _n = exporter.write_entity_file(tmp_path / "owners", "owners")
        assert xlsx_path.suffix == ".xlsx"

        csv_path, _n = exporter.write_entity_file(tmp_path / "owners2", "owners",
                                                 file_format="csv")
        assert csv_path.suffix == ".csv"

    def test_unknown_entity_raises_before_writing(self, exporter_db, tmp_path):
        with pytest.raises(KeyError):
            exporter.write_entity_file(tmp_path / "nope.csv", "nope")
        assert not (tmp_path / "nope.csv").exists()


class TestWriteAllExports:
    def test_writes_one_file_per_entity(self, exporter_db, tmp_path):
        _seed_owner()
        target = tmp_path / "backup"
        written = exporter.write_all_exports(target)

        assert [path.name for path, _count in written] == [
            f"{key}.xlsx" for key in exporter.EXPORT_KEYS]
        assert all(path.exists() for path, _count in written)
        assert written[0][1] == 1  # one owner

    def test_csv_format_and_created_directory(self, exporter_db, tmp_path):
        target = tmp_path / "nested" / "csv"
        written = exporter.write_all_exports(target, "csv")

        assert [path.name for path, _count in written] == [
            f"{key}.csv" for key in exporter.EXPORT_KEYS]
        assert all(path.exists() for path, _count in written)


class TestWriteWorkbook:
    """One Excel file, one sheet per data type."""

    def test_writes_a_single_file_with_a_sheet_per_entity(self, exporter_db,
                                                           tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        _seed_owner()
        target = tmp_path / "clinic.xlsx"

        written, counts, total = exporter.write_workbook(target)

        assert written == target
        assert [p.name for p in tmp_path.iterdir()] == ["clinic.xlsx"]
        assert list(counts) == list(exporter.EXPORT_KEYS)
        assert counts["owners"] == 1 and counts["pets"] == 0
        assert total == 1

        workbook = openpyxl.load_workbook(str(written))
        assert workbook.sheetnames == (
            [importer.entity_sheet_name(key) for key in exporter.EXPORT_KEYS]
            + [importer.INSTRUCTIONS_SHEET_NAME]
        )
        sheet = workbook["Owners"]
        assert [cell.value for cell in sheet[1]] == ["Owner Name", "Phone Number",
                                                     "Notes"]
        assert [cell.value for cell in sheet[2]] == ["Ahmed Ali", "01001234567", None]
        assert sheet.auto_filter.ref == "A1:C2"
        assert sheet["A1"].comment is not None  # hover help survives
        workbook.close()

    def test_every_sheet_keeps_its_template_headers(self, exporter_db, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        written, _counts, _total = exporter.write_workbook(tmp_path / "all.xlsx")

        workbook = openpyxl.load_workbook(str(written))
        for entity_key in exporter.EXPORT_KEYS:
            sheet = workbook[importer.entity_sheet_name(entity_key)]
            headers, _sample = importer.template_rows(entity_key)
            assert [cell.value for cell in sheet[1]] == headers
        workbook.close()

    def test_empty_database_still_writes_all_sheets(self, exporter_db, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        written, counts, total = exporter.write_workbook(tmp_path / "empty.xlsx")

        assert total == 0
        assert list(counts) == list(exporter.EXPORT_KEYS)
        assert all(counts[key] == 0 for key in exporter.EXPORT_KEYS)

    def test_default_name_and_suffix_fallback(self, exporter_db, tmp_path):
        written, _counts, _total = exporter.write_workbook(directory=tmp_path)
        assert written.name == exporter.WORKBOOK_NAME == "pet_data.xlsx"

        fixed, _counts, _total = exporter.write_workbook(tmp_path / "noext")
        assert fixed.suffix == ".xlsx"

    def test_instructions_sheet_documents_every_sheet(self, exporter_db, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        written, _counts, _total = exporter.write_workbook(tmp_path / "doc.xlsx")

        workbook = openpyxl.load_workbook(str(written))
        instructions = workbook[importer.INSTRUCTIONS_SHEET_NAME]
        text = "\n".join(
            str(cell.value) for row in instructions.iter_rows() for cell in row
            if cell.value
        )
        for entity_key in exporter.EXPORT_KEYS:
            assert importer.entity_sheet_name(entity_key) in text
        assert "How to fill in this workbook" in text
        workbook.close()


class TestWorkbookRoundTrip:
    """The exported workbook must import back sheet by sheet."""

    def test_export_then_import_workbook_skips_every_existing_record(
            self, exporter_db, tmp_path):
        pytest.importorskip("openpyxl")
        client_id = _seed_owner(notes="VIP")
        pet_repo.add_pet("Rex", "Dog", "Labrador", "Male", 24, 25.5, client_id)

        written, counts, _total = exporter.write_workbook(tmp_path / "clinic.xlsx")
        assert counts["owners"] == 1 and counts["pets"] == 1
        assert counts["supplies"] == 0 and counts["visits"] == 0

        plan = importer.plan_workbook(written)
        assert [p.sheet_name for p in plan.plans] == [
            importer.entity_sheet_name(key) for key in exporter.EXPORT_KEYS
        ]
        assert plan.entities == tuple(exporter.EXPORT_KEYS)
        # The documentation sheet is listed as skipped, never as data.
        assert plan.ignored == [importer.INSTRUCTIONS_SHEET_NAME]

        summary = importer.import_workbook(written, plan=plan)
        assert summary.failed == 0
        # Owners and pets are duplicates, so nothing new is written.
        assert summary.imported == 0
        assert summary.entities == ()
        assert len(client_repo.get_clients()) == 1

    def test_validating_the_export_writes_nothing(self, exporter_db, tmp_path):
        pytest.importorskip("openpyxl")
        _seed_owner()
        written, _counts, _total = exporter.write_workbook(tmp_path / "clinic.xlsx")

        summary = importer.import_workbook(written, dry_run=True)

        assert summary.total == 1
        assert summary.imported == 0  # the owner already exists
        assert client_repo.get_clients() != []  # and nothing was touched


class TestRoundTrip:
    """An exported file must be readable by the importer as-is."""

    def test_csv_export_reimports_with_matching_headers(self, exporter_db, tmp_path):
        _seed_owner(notes="VIP")
        path, _count = exporter.write_entity_file(tmp_path / "owners.csv", "owners")

        table = importer.read_table(path)
        assert importer.detect_entity(table.headers) == "owners"
        assert table.headers == importer.template_rows("owners")[0]
        summary = importer.import_table("owners", table.headers, table.rows,
                                        table.row_numbers, None, True)
        assert summary.failed == 0
        # Re-importing the same owner is skipped, never duplicated.
        assert summary.skipped == 1

    def test_visits_export_is_accepted_by_the_importer(self, exporter_db, tmp_path):
        client_id = _seed_owner()
        pet_id = pet_repo.add_pet("Rex", "Dog", None, None, None, None, client_id)
        supply_repo.add_supply("Amox", "Meds", "Antibiotics", quantity=10,
                               sell_price=25, audit_user_id=None)
        visit_repo.add_visit("2025-01-15 10:00:00", "Otitis", True, "Recheck",
                             pet_id=pet_id, client_id=client_id,
                             items=[{"item_name": "Amox", "quantity": 2}],
                             receipt_code="VISIT-9003", audit_user_id=None)

        path, _count = exporter.write_entity_file(tmp_path / "visits.csv", "visits")
        table = importer.read_table(path)
        summary = importer.import_table("visits", table.headers, table.rows,
                                        table.row_numbers, None, True)
        assert summary.failed == 0
        # Re-importing the same visit is skipped, never duplicated.
        assert summary.skipped == 1