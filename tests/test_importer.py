"""Tests for src/core/importer.py (Excel / CSV import engine)."""

import csv
import datetime

import pytest

from src.core import importer
from src.core.importer import (
    STATUS_FAILED,
    detect_entity,
    import_table,
    match_columns,
    missing_required_columns,
    parse_items,
    read_table,
    to_bool,
    to_date,
    to_datetime,
    to_int,
    to_number,
    write_all_templates,
    write_template,
)
from src.core.repositories import payment_repo


@pytest.fixture
def importer_db(fresh_db, monkeypatch):
    """Redirects the importer's own ``get_connection`` to the fresh test DB."""
    monkeypatch.setattr(importer, "get_connection", lambda: fresh_db, raising=False)
    return fresh_db


def _write_csv(path, headers, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _sheet_text(book, sheet_name):
    """Every non-empty cell of ``sheet_name``, joined for substring asserts."""
    return "\n".join(
        str(cell.value)
        for row in book[sheet_name].iter_rows()
        for cell in row
        if cell.value is not None
    )


# Data rows laid out exactly like the template columns of the sheet they feed.
_OWNER = ["Ahmed Ali", "01001234567", ""]
_OWNER_2 = ["Sara Mahmoud", "01009998888", "VIP"]
_PET = ["Rex", "Ahmed Ali", "01001234567", "Dog", "Labrador Retriever", "Male",
        24, 25.5]
_SUPPLY = ["Amox 250", "Medicine", "Antibiotics", 10, 12.5, 25, "2025-01-01",
           "2026-01-01", ""]
_VISIT = ["2025-01-15 10:00", "Ahmed Ali", "01001234567", "Rex", "Otitis",
          "Ear scratching", "", "Yes", 38.5, "Amox 250 x2"]

_SUPPLIER = ["Acme Veterinary Supplies", "01001234567", "Cairo", "Bulk orders"]
_PACKAGE = ["Puppy Starter", "First-year wellness bundle", 1500.0]
_PACKAGE_ITEM_SERVICE = ["Puppy Starter", "service", "Consultation", 1]
_PACKAGE_ITEM_SUPPLY = ["Puppy Starter", "supply", "Amox 250", 2]
_APPOINTMENT = ["2025-02-01 10:00:00", "Ahmed Ali", "01001234567", "Rex",
                "Vaccination", "Pending", ""]
_FOLLOWUP = ["Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
             "2025-02-15", "Pending", ""]
_VACCINATION = ["Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "Rabies"]
_MEDICATION = ["Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
               "Amox 250", "1 tablet twice daily", "After food"]
_TREATMENT = ["Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
              "Wound cleaning"]
_TEST = ["Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
         "Blood count", "Normal"]
_EXPENSE = ["2025-01-20", "Rent", "Monthly clinic rent", 5000.0, ""]

# Template-column header rows, one per entity.
_H_OWNERS = ["Owner Name", "Phone Number", "Notes"]
_H_PETS = ["Pet Name", "Owner Name", "Phone Number", "Species", "Breed",
           "Gender", "Age (months)", "Weight (kg)"]
_H_SUPPLIES = ["Item Name", "Category", "Sub Category", "Quantity", "Buy Price",
               "Sell Price", "Purchase Date", "Expiry Date", "Supplier"]
_H_SUPPLIERS = ["Supplier Name", "Phone", "Location", "Notes"]
_H_PACKAGES = ["Package Name", "Description", "Total Price"]
_H_PACKAGE_ITEMS = ["Package Name", "Item Type", "Item Name", "Quantity"]
_H_APPOINTMENTS = ["Appointment Date", "Owner Name", "Phone Number", "Pet Name",
                   "Service", "Status", "Notes"]
_H_VISITS = ["Visit Date", "Owner Name", "Phone Number", "Pet Name",
             "Diagnosis", "Reason for Visit", "Notes", "Consultation",
             "Temperature", "Supplies"]
_H_FOLLOWUPS = ["Owner Name", "Phone Number", "Pet Name", "Visit Date",
                "Follow-up Date", "Status", "Notes"]
_H_VACCINATIONS = ["Owner Name", "Phone Number", "Pet Name", "Visit Date",
                   "Vaccine"]
_H_MEDICATIONS = ["Owner Name", "Phone Number", "Pet Name", "Visit Date",
                  "Medication", "Dosage", "Instructions"]
_H_TREATMENTS = ["Owner Name", "Phone Number", "Pet Name", "Visit Date",
                 "Treatment"]
_H_TESTS = ["Owner Name", "Phone Number", "Pet Name", "Visit Date", "Test",
            "Result"]
_H_EXPENSES = ["Expense Date", "Category", "Item Name", "Amount", "Notes"]
_H_PAYMENTS = ["Receipt Code", "Amount", "Payment Method", "Payment Date",
               "Notes"]


# --------------------------------------------------------------- Reading ---
class TestReadTable:
    def test_reads_csv_and_strips_blank_rows(self, tmp_path):
        path = _write_csv(
            tmp_path / "owners.csv",
            ["Owner Name", "Phone Number"],
            [["Ahmed Ali", "01001234567"], ["", ""], ["Mona Hassan", "01112223333"]],
        )
        table = read_table(path)

        assert table.headers == ["Owner Name", "Phone Number"]
        assert table.rows == [["Ahmed Ali", "01001234567"], ["Mona Hassan", "01112223333"]]
        # File rows: header is 1, the blank row is 3, so the data rows are 2 and 4.
        assert table.row_numbers == [2, 4]

    def test_reads_semicolon_delimited_file(self, tmp_path):
        path = tmp_path / "pets.csv"
        path.write_text("Pet Name;Owner Name\nRex;Ahmed Ali\n", encoding="utf-8")

        table = read_table(path)
        assert table.headers == ["Pet Name", "Owner Name"]
        assert table.rows == [["Rex", "Ahmed Ali"]]

    def test_reads_excel_with_multiple_sheets(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Owners"
        workbook.active.append(["Owner Name", "Phone Number"])
        workbook.active.append(["Ahmed Ali", "01001234567"])
        second = workbook.create_sheet("Visits")
        second.append(["Visit Date", "Pet Name"])
        workbook.save(str(path))

        assert importer.list_sheets(path) == ["Owners", "Visits"]

        owners = read_table(path)
        assert owners.sheet_name == "Owners"
        assert owners.rows == [["Ahmed Ali", "01001234567"]]

        visits = read_table(path, "Visits")
        assert visits.headers == ["Visit Date", "Pet Name"]

    def test_rejects_unsupported_extension(self, tmp_path):
        text = tmp_path / "notes.txt"
        text.write_text("hello", encoding="utf-8")
        assert read_table(text).headers == ["hello"]

        other = tmp_path / "data.pdf"
        other.write_bytes(b"%PDF")
        with pytest.raises(ValueError):
            read_table(other)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_table(tmp_path / "nope.csv")


# ------------------------------------------------------- Column matching ---
class TestMatchColumns:
    def test_matches_aliases_case_insensitively(self):
        spec = importer.get_spec("pets")
        headers = ["PET", "Client Name", "Mobile", "Age (months)", "Weight (kg)"]
        column_map = match_columns(headers, spec)

        assert column_map["pet_name"] == 0
        assert column_map["owner_name"] == 1
        assert column_map["phone_number"] == 2
        assert column_map["age_months"] == 3
        assert column_map["weight"] == 4

    def test_missing_required_columns_reported(self):
        spec = importer.get_spec("owners")
        assert missing_required_columns(["Phone Number", "Notes"], spec) == ["owner_name"]
        assert missing_required_columns(["Owner", "Mobile"], spec) == []

    def test_one_column_is_never_mapped_twice(self):
        spec = importer.get_spec("owners")
        column_map = match_columns(["Name", "Owner Name"], spec)
        assert column_map["owner_name"] in (0, 1)

    def test_detect_entity(self):
        assert detect_entity(["Pet Name", "Owner Name", "Species"]) == "pets"
        assert detect_entity(["Item Name", "Category", "Quantity"]) == "supplies"
        assert detect_entity(["Visit Date", "Pet Name", "Owner Name"]) == "visits"
        assert detect_entity(["Owner Name", "Phone Number"]) == "owners"
        assert detect_entity(["Foo", "Bar"]) is None


# ------------------------------------------------------------ Coercion ---
class TestCoercion:
    @pytest.mark.parametrize("value,expected", [
        ("12", 12), ("12.7", 13), ("1,200", 1200), ("", 0),
        ("EGP 30", 30), ("abc", 0),
    ])
    def test_to_int(self, value, expected):
        assert to_int(value) == expected

    def test_to_number(self):
        assert to_number("2,499.99") == 2499.99
        assert to_number("", 5.0) == 5.0

    @pytest.mark.parametrize("value,expected", [
        ("Yes", True), ("y", True), ("1", True), ("true", True),
        ("No", False), ("0", False), ("", False), ("maybe", False),
    ])
    def test_to_bool(self, value, expected):
        assert to_bool(value) is expected

    def test_to_date_formats(self):
        assert to_date("2025-01-15") == "2025-01-15"
        assert to_date("15/01/2025") == "2025-01-15"
        assert to_date("2025-01-15 10:30:00") == "2025-01-15"
        assert to_date("not a date") is None
        assert to_date("") is None

    def test_to_datetime_formats(self):
        assert to_datetime("2025-01-15 10:30") == "2025-01-15 10:30:00"
        assert to_datetime("15/01/2025") == "2025-01-15 00:00:00"
        assert to_datetime("") is None

    def test_parse_items(self):
        assert parse_items("Amox x2; Vitamin B 3") == [
            {"item_name": "Amox", "quantity": 2},
            {"item_name": "Vitamin B", "quantity": 3},
        ]
        assert parse_items("Bandage") == [{"item_name": "Bandage", "quantity": 1}]
        assert parse_items("") == []


# -------------------------------------------------------------- Owners ---
class TestImportOwners:
    def test_adds_owners_and_skips_duplicates(self, importer_db, repos):
        headers = ["Owner Name", "Phone Number", "Notes"]
        rows = [
            ["Ahmed Ali", "01001234567", "VIP"],
            ["Ahmed Ali", "01001234567", "VIP"],
            ["Mona Hassan", "01112223333", ""],
        ]

        summary = import_table("owners", headers, rows, user_id=None)

        assert summary.imported == 2
        assert summary.skipped == 1
        assert summary.failed == 0
        assert len(repos["client"].get_clients()) == 2

    def test_dry_run_writes_nothing(self, importer_db, repos):
        summary = import_table(
            "owners", ["Owner Name"], [["Ahmed Ali"]], dry_run=True
        )
        assert summary.imported == 1
        assert repos["client"].get_clients() == []

    def test_missing_column_fails_every_row(self, importer_db):
        summary = import_table("owners", ["Phone Number"], [["0100"], ["0111"]])
        assert summary.failed == 2
        assert "Owner Name" in summary.results[0].message

    def test_blank_name_row_fails(self, importer_db):
        summary = import_table("owners", ["Owner Name", "Phone Number"],
                               [["Ahmed Ali", "01"], ["", "02"]])
        assert summary.imported == 1
        assert summary.failed == 1
        assert summary.results[1].status == STATUS_FAILED

    def test_unknown_entity_raises(self):
        with pytest.raises(KeyError):
            import_table("invoices", ["Owner Name"], [])


# ---------------------------------------------------------------- Pets ---
class TestImportPets:
    def test_creates_missing_owner_automatically(self, importer_db, repos):
        headers = ["Pet Name", "Owner Name", "Species", "Breed", "Age (months)", "Weight"]
        rows = [["Rex", "Ahmed Ali", "Dog", "Labrador", "24", "25.5"]]

        summary = import_table("pets", headers, rows)

        assert summary.imported == 1
        assert "Owner created" in summary.results[0].message
        owners = repos["client"].get_clients()
        assert len(owners) == 1
        pets = repos["pet"].get_pets()
        assert len(pets) == 1
        assert pets[0]["pet_name"] == "Rex"

    def test_skips_existing_pet(self, importer_db, repos, entity_factory):
        client_id = entity_factory["make_client"]("Ahmed Ali", "01001234567")
        entity_factory["make_pet"](client_id, "Rex")

        summary = import_table("pets", ["Pet Name", "Owner Name"],
                               [["rex", "Ahmed Ali"]])

        assert summary.skipped == 1
        assert len(repos["pet"].get_pets()) == 1

    def test_missing_owner_name_fails(self, importer_db):
        summary = import_table("pets", ["Pet Name", "Owner Name"], [["Rex", ""]])
        assert summary.failed == 1


# ------------------------------------------------------------ Supplies ---
class TestImportSupplies:
    def test_adds_supply_and_registers_category(self, importer_db, repos):
        headers = ["Item Name", "Category", "Sub Category", "Quantity",
                   "Buy Price", "Sell Price"]
        rows = [["Amox 250", "Medicine", "Antibiotics", "50", "12.5", "25"]]

        summary = import_table("supplies", headers, rows)

        assert summary.imported == 1
        found = repos["supply"].search_supplies(text="Amox 250")
        assert found
        assert found[0]["current_stock"] == 50

    def test_second_identical_row_is_skipped_not_restocked(self, importer_db, repos):
        headers = ["Item Name", "Category", "Quantity"]
        rows = [["Amox 250", "Medicine", "10"], ["Amox 250", "Medicine", "5"]]

        summary = import_table("supplies", headers, rows)

        assert summary.imported == 1
        assert summary.skipped == 1
        assert "already exists" in summary.results[1].message
        # The skipped row must NOT top up stock (no double import).
        assert repos["supply"].get_existing_supply("Amox 250", "Medicine")["current_stock"] == 10

    def test_missing_category_fails(self, importer_db):
        summary = import_table("supplies", ["Item Name", "Category"], [["Amox", ""]])
        assert summary.failed == 1


# -------------------------------------------------------------- Visits ---
class TestImportVisits:
    @pytest.fixture
    def clinic(self, entity_factory, repos):
        client_id = entity_factory["make_client"]("Ahmed Ali", "01001234567")
        pet_id = entity_factory["make_pet"](client_id, "Rex")
        entity_factory["make_supply"](quantity=10, name="Amox 250")
        return client_id, pet_id

    def test_adds_visit_with_items(self, importer_db, repos, clinic):
        headers = ["Visit Date", "Owner Name", "Pet Name", "Diagnosis",
                   "Consultation", "Supplies"]
        rows = [["2025-01-15 10:00", "Ahmed Ali", "Rex", "Otitis", "Yes", "Amox 250 x2"]]

        summary = import_table("visits", headers, rows)

        assert summary.imported == 1, summary.results[0].message
        visits = repos["visit"].get_visits()
        assert len(visits) == 1
        assert visits[0]["diagnosis"] == "Otitis"
        assert repos["supply"].get_existing_supply("Amox 250", "Medicine")["current_stock"] == 8

    def test_unknown_supply_item_fails_row(self, importer_db, clinic):
        headers = ["Visit Date", "Owner Name", "Pet Name", "Supplies"]
        summary = import_table("visits", headers,
                               [["2025-01-15", "Ahmed Ali", "Rex", "Unknown Drug x1"]])

        assert summary.failed == 1
        assert "Unknown Drug" in summary.results[0].message

    def test_missing_pet_fails_row(self, importer_db, clinic):
        summary = import_table("visits", ["Visit Date", "Owner Name", "Pet Name"],
                               [["2025-01-15", "Ahmed Ali", "Fido"]])

        assert summary.failed == 1
        assert "Fido" in summary.results[0].message

    def test_invalid_date_fails_row(self, importer_db, clinic):
        summary = import_table("visits", ["Visit Date", "Owner Name", "Pet Name"],
                               [["tomorrow", "Ahmed Ali", "Rex"]])

        assert summary.failed == 1
        assert "date" in summary.results[0].message.lower()

    def test_each_visit_gets_a_unique_receipt(self, importer_db, repos, clinic):
        headers = ["Visit Date", "Owner Name", "Pet Name", "Diagnosis", "Consultation"]
        rows = [
            ["2025-01-15 10:00", "Ahmed Ali", "Rex", "A", "Yes"],
            ["2025-01-16 10:00", "Ahmed Ali", "Rex", "B", "Yes"],
        ]

        summary = import_table("visits", headers, rows)

        assert summary.imported == 2, [r.message for r in summary.results]
        # A unique receipt code per row: without one the second insert would
        # fail the receipts.receipt_code UNIQUE constraint.
        receipt_ids = {r["receipt_id"] for r in repos["sales"].get_receipt_items()}
        assert len(receipt_ids) == 2

    def test_too_little_stock_fails_row(self, importer_db, clinic):
        headers = ["Visit Date", "Owner Name", "Pet Name", "Supplies"]
        summary = import_table("visits", headers,
                               [["2025-01-15", "Ahmed Ali", "Rex", "Amox 250 x99"]])

        assert summary.failed == 1
        assert "stock" in summary.results[0].message.lower()

    def test_preserves_a_given_receipt_code(self, importer_db, repos, clinic):
        token = "VISIT-202501-0009"
        summary = import_table(
            "visits",
            ["Visit Date", "Owner Name", "Pet Name", "Consultation",
             "Receipt Code"],
            [["2025-01-15 10:00", "Ahmed Ali", "Rex", "Yes", token]],
        )

        assert summary.imported == 1, summary.results[0].message
        # The code survives so a Payments sheet can reattach to the same receipt.
        assert repos["sales"].get_receipt_id_by_code(token) is not None

    def test_existing_receipt_code_skips_the_row(self, importer_db, repos, clinic):
        token = "VISIT-202501-0010"
        headers = ["Visit Date", "Owner Name", "Pet Name", "Consultation",
                   "Receipt Code"]
        rows = [["2025-01-15 10:00", "Ahmed Ali", "Rex", "Yes", token]]

        import_table("visits", headers, rows)
        summary = import_table("visits", headers, rows)

        assert summary.skipped == 1
        assert len(repos["visit"].get_visits()) == 1


# ------------------------------------------------------------ Auditing ---
class TestAuditing:
    def test_rows_are_attributed_to_the_importing_user(self, importer_db, repos):
        user_id = repos["user"].add_user("importer", "secret", "admin")

        summary = import_table("owners", ["Owner Name", "Phone Number"],
                               [["Ahmed Ali", "01001234567"]], user_id=user_id)

        assert summary.imported == 1
        actions = repos["audit"].get_recent_changes_with_details(limit=5)
        assert any(a.get("user_id") == user_id for a in actions)


# ----------------------------------------------------------- Templates ---
class TestSheetNames:
    def test_every_entity_has_a_readable_sheet_name(self):
        assert list(importer.SHEET_NAMES) == list(importer.IMPORT_KEYS)
        assert importer.entity_sheet_name("owners") == "Owners"
        assert importer.entity_sheet_name("visits") == "Visits"
        assert len(set(importer.SHEET_NAMES.values())) == len(importer.IMPORT_KEYS)

    def test_unknown_entity_raises(self):
        with pytest.raises(KeyError):
            importer.entity_sheet_name("nope")


class TestPlanWorkbook:
    def _book(self, tmp_path, sheets, name="book.xlsx"):
        """Writes a workbook of ``(sheet_name, entity_key, data_rows)`` sheets."""
        return importer.write_excel_workbook(tmp_path / name, sheets)

    def test_pairs_every_sheet_with_its_entity(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Visits", "visits", [_VISIT]),
            ("Owners", "owners", [_OWNER]),
        ])

        plan = importer.plan_workbook(path)

        # Sheets come back in IMPORT_KEYS order whatever the workbook order is.
        assert [p.sheet_name for p in plan.plans] == ["Owners", "Visits"]
        assert [p.entity for p in plan.plans] == ["owners", "visits"]
        assert [p.row_count for p in plan.plans] == [1, 1]
        assert plan.entities == ("owners", "visits")
        assert plan.row_count == 2
        # The Instructions sheet every workbook carries is never data.
        assert plan.ignored == [importer.INSTRUCTIONS_SHEET_NAME]

    def test_matches_sheets_by_their_columns_not_their_names(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Sheet 1", "owners", [_OWNER]),
            ("Copy of Sheet1", "owners", [_OWNER_2]),
        ])

        plan = importer.plan_workbook(path)

        assert plan.entities == ("owners",)
        assert [p.sheet_name for p in plan.plans] == ["Sheet 1", "Copy of Sheet1"]

    def test_ignores_the_instructions_sheet(self, tmp_path):
        pytest.importorskip("openpyxl")
        # write_excel_workbook always appends the Instructions sheet.
        path = self._book(tmp_path, [("Owners", "owners", [_OWNER])])

        plan = importer.plan_workbook(path)

        assert [p.sheet_name for p in plan.plans] == ["Owners"]
        assert plan.ignored == [importer.INSTRUCTIONS_SHEET_NAME]

    def test_ignores_sheets_that_match_no_entity(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [("Owners", "owners", [_OWNER])])

        book = openpyxl.load_workbook(str(path))
        scratch = book.create_sheet("Scratch")
        scratch.append(["Nothing", "Like", "The", "Others"])
        scratch.append(["a", "b", "c", "d"])
        book.save(str(path))

        plan = importer.plan_workbook(path)

        assert [p.sheet_name for p in plan.plans] == ["Owners"]
        assert "Scratch" in plan.ignored

    def test_untouched_sheet_is_importable_and_counts_no_rows(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", []),
            ("Pets", "pets", []),
        ])

        plan = importer.plan_workbook(path)

        assert plan.entities == ("owners", "pets")
        assert plan.row_count == 0

    def test_a_csv_is_planned_as_a_single_sheet(self, tmp_path):
        path = _write_csv(tmp_path / "owners.csv",
                          ["Owner Name", "Phone Number"],
                          [["Ahmed Ali", "01001234567"]])

        plan = importer.plan_workbook(path)

        assert plan.entities == ("owners",)
        assert plan.plans[0].sheet_name == "owners.csv"
        assert plan.ignored == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            importer.plan_workbook(tmp_path / "nope.xlsx")

    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "data.pdf"
        path.write_bytes(b"%PDF-1.4")
        with pytest.raises(ValueError):
            importer.plan_workbook(path)


class TestImportWorkbook:
    def _book(self, tmp_path, sheets, name="book.xlsx"):
        return importer.write_excel_workbook(tmp_path / name, sheets)

    def test_imports_every_sheet(self, importer_db, repos, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Supplies", "supplies", [_SUPPLY]),
        ])

        summary = importer.import_workbook(path)

        assert (summary.total, summary.imported, summary.failed) == (2, 2, 0)
        assert summary.entities == ("owners", "supplies")
        assert len(repos["client"].get_clients()) == 1
        assert repos["supply"].get_existing_supply("Amox 250", "Medicine")

    def test_sheets_share_one_lookup_context(self, importer_db, repos, tmp_path):
        """A pet created on the Pets sheet reuses the owner from the Owners sheet."""
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
        ])

        summary = importer.import_workbook(path)

        assert summary.failed == 0, summary.problems()
        assert summary.imported == 2
        assert len(repos["client"].get_clients()) == 1  # not created twice
        assert len(repos["pet"].get_pets()) == 1

    def test_visits_resolve_owners_pets_and_supplies_from_earlier_sheets(
            self, importer_db, repos, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
            ("Supplies", "supplies", [_SUPPLY]),
            ("Visits", "visits", [_VISIT]),
        ])

        summary = importer.import_workbook(path)

        assert summary.failed == 0, summary.problems()
        assert summary.imported == 4
        assert len(repos["visit"].get_visits()) == 1
        # Stock came out of the supply the Supplies sheet created.
        assert repos["supply"].get_existing_supply(
            "Amox 250", "Medicine")["current_stock"] == 8

    def test_dry_run_resolves_dependencies_without_writing(self, importer_db, repos,
                                                            tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
        ])

        summary = importer.import_workbook(path, dry_run=True)

        # Rex's owner only exists on the Owners sheet, so a clean dry run proves
        # the planned owner is resolved instead of reported as missing.
        assert summary.failed == 0, summary.problems()
        assert summary.total == 2
        assert repos["client"].get_clients() == []
        assert repos["pet"].get_pets() == []

    def test_dry_run_resolves_planned_package_supplies(self, importer_db, repos,
                                                       tmp_path):
        pytest.importorskip("openpyxl")
        # Package Items reference a supply the same dry run would create.
        path = self._book(tmp_path, [
            ("Supplies", "supplies", [_SUPPLY]),
            ("Packages", "packages", [_PACKAGE]),
            ("Package Items", "package_items", [_PACKAGE_ITEM_SUPPLY]),
        ])

        summary = importer.import_workbook(path, dry_run=True)

        assert summary.failed == 0, summary.problems()
        assert repos["supply"].get_existing_supply("Amox 250", "Medicine") is None
        assert repos["package"].get_packages_for_export() == []

    def test_dry_run_reports_supplies_a_visit_needs(self, importer_db, repos,
                                                     tmp_path):
        pytest.importorskip("openpyxl")
        # No Supplies sheet: the visit names an item nothing knows about.
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
            ("Visits", "visits", [_VISIT]),
        ])

        summary = importer.import_workbook(path, dry_run=True)

        assert summary.failed == 1
        assert "Unknown supply item: Amox 250" in importer.result_details(summary)

    def test_a_broken_sheet_does_not_stop_the_others(self, importer_db, repos,
                                                      tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER, ["", "01009998888"]]),
            ("Pets", "pets", [_PET]),
        ])

        summary = importer.import_workbook(path)

        assert (summary.imported, summary.failed) == (2, 1)
        assert len(repos["client"].get_clients()) == 1
        assert summary.problems()[0][0] == "Owners"

    def test_untouched_template_workbook_imports_nothing(self, importer_db, repos,
                                                          tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_templates_workbook(tmp_path / "starters.xlsx")

        summary = importer.import_workbook(path)

        assert (summary.total, summary.imported, summary.failed) == (0, 0, 0)
        assert summary.entities == ()  # nothing landed, so nothing to refresh
        # but every data sheet was read
        assert len(summary.sheets) == len(importer.IMPORT_KEYS)
        assert repos["client"].get_clients() == []

    def test_untouched_sheets_import_nothing(self, importer_db, repos, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", []),
            ("Pets", "pets", []),
        ])

        summary = importer.import_workbook(path)

        assert (summary.total, summary.imported, summary.failed) == (0, 0, 0)
        assert repos["client"].get_clients() == []

    def test_reuses_a_prebuilt_plan(self, importer_db, repos, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [("Owners", "owners", [_OWNER])])
        plan = importer.plan_workbook(path)

        summary = importer.import_workbook(path, plan=plan)

        assert summary.imported == 1
        assert summary.sheets[0][0] == "Owners"

    def test_audit_rows_are_attributed_to_the_importing_user(self, importer_db,
                                                             repos, tmp_path):
        pytest.importorskip("openpyxl")
        user_id = repos["user"].add_user("importer", "secret", "admin")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
        ])

        importer.import_workbook(path, user_id=user_id)

        actions = repos["audit"].get_recent_changes_with_details(limit=10)
        assert len([a for a in actions if a.get("user_id") == user_id]) == 2

    def test_sheet_summary_finds_one_sheet_per_entity(self, importer_db, tmp_path):
        pytest.importorskip("openpyxl")
        path = self._book(tmp_path, [
            ("Owners", "owners", [_OWNER, _OWNER_2]),
            ("Pets", "pets", [_PET]),
        ])

        summary = importer.import_workbook(path)

        assert summary.sheet_summary("owners").imported == 2
        assert summary.sheet_summary("pets").imported == 1
        assert summary.sheet_summary("visits") is None


class TestResultDetails:
    """``result_details`` works for both summary types and names the sheet."""

    def test_names_the_sheet_a_problem_came_from(self, importer_db, tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_excel_workbook(tmp_path / "book.xlsx", [
            ("Owners", "owners", [["", "01001234567", ""]]),
        ])

        summary = importer.import_workbook(path)

        assert summary.failed == 1
        assert importer.result_details(summary) == (
            "Owners - Row 2: Owner name is empty."
        )

    def test_single_table_summary_has_no_sheet_prefix(self, importer_db):
        # Without file row numbers the first row is row 1.
        summary = import_table("owners", ["Owner Name", "Phone Number"],
                               [["", "01001234567"]])

        assert importer.result_details(summary) == "Row 1: Owner name is empty."

    def test_skipped_rows_are_not_listed(self, importer_db):
        summary = import_table("owners", ["Owner Name", "Phone Number"],
                               [["Ahmed Ali", "01001234567"]],
                               user_id=None)
        # Importing the same row again is skipped, so it is not worth reporting.
        again = import_table("owners", ["Owner Name", "Phone Number"],
                             [["Ahmed Ali", "01001234567"]], context=None)

        assert summary.imported == 1
        assert again.skipped == 1
        assert importer.result_details(again) == ""

    def test_limits_the_list(self, importer_db):
        rows = [[f"Owner {index}", "0100123" + str(index).zfill(4)] for index in range(5)]
        summary = import_table("owners", ["Owner Name", "Phone Number"], rows)

        assert len(importer.result_details(summary, limit=2).splitlines()) == 2


class TestWorkbookInstructionsSheet:
    def test_multi_sheet_workbook_documents_every_sheet(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = importer.write_excel_workbook(tmp_path / "book.xlsx", [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
        ])

        book = openpyxl.load_workbook(str(path))
        text = _sheet_text(book, importer.INSTRUCTIONS_SHEET_NAME)

        assert "How to fill in this workbook" in text
        for step in importer.WORKBOOK_STEPS:
            assert step in text
        assert "Sheet: Owners" in text
        assert "Sheet: Pets" in text
        assert "documentation only" in text
        book.close()

    def test_single_sheet_workbook_keeps_the_template_wording(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = importer.write_excel_workbook(tmp_path / "one.xlsx", [
            ("Owners", "owners", [_OWNER]),
        ])

        book = openpyxl.load_workbook(str(path))
        text = _sheet_text(book, importer.INSTRUCTIONS_SHEET_NAME)

        assert "How to fill in this template" in text
        assert "'Owners'" in text  # the single-sheet sentence still fits
        book.close()

    def test_workbook_sheets_are_named_and_typed_like_their_templates(
            self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = importer.write_excel_workbook(tmp_path / "book.xlsx", [
            ("Owners", "owners", [_OWNER]),
            ("Visits", "visits", [_VISIT]),
        ])

        book = openpyxl.load_workbook(str(path))
        assert book.sheetnames == ["Owners", "Visits",
                                   importer.INSTRUCTIONS_SHEET_NAME]
        owners = book["Owners"]
        assert owners.max_row == 2
        assert [cell.value for cell in owners[1]] == importer.template_rows(
            "owners")[0]
        assert owners.freeze_panes == "A2"
        assert owners.auto_filter.ref == "A1:C2"
        # Every header keeps its hover help.
        assert owners["A1"].comment is not None
        book.close()


class TestTemplateWorkbook:
    """The headers-only workbook mirrors the export, minus the records."""

    def test_one_sheet_per_entity_with_no_sample_rows(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = importer.write_templates_workbook(tmp_path / "starters.xlsx")

        book = openpyxl.load_workbook(str(path))
        expected = (list(importer.entity_sheet_name(key) for key in importer.IMPORT_KEYS)
                    + [importer.INSTRUCTIONS_SHEET_NAME])
        assert book.sheetnames == expected
        for entity_key in importer.IMPORT_KEYS:
            sheet = book[importer.entity_sheet_name(entity_key)]
            assert sheet.max_row == 1  # headers only
            headers, _sample = importer.template_rows(entity_key)
            assert [cell.value for cell in sheet[1]] == headers
            assert sheet["A1"].comment is not None
        book.close()

    def test_same_sheet_names_as_the_data_export(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_templates_workbook(tmp_path / "starters.xlsx")

        plan = importer.plan_workbook(path)

        assert plan.entities == importer.IMPORT_KEYS
        assert [p.sheet_name for p in plan.plans] == [
            importer.entity_sheet_name(key) for key in importer.IMPORT_KEYS
        ]
        assert plan.ignored == [importer.INSTRUCTIONS_SHEET_NAME]

    def test_default_file_name(self):
        assert importer.TEMPLATE_WORKBOOK_NAME == "pet_templates.xlsx"

    def test_write_all_templates_still_writes_one_file_per_entity(self, tmp_path):
        """The CSV button needs per-entity files; Excel uses the workbook."""
        pytest.importorskip("openpyxl")
        written = write_all_templates(tmp_path, "csv")

        assert [p.name for p in written] == [
            f"{entity_key}_template.csv" for entity_key in importer.IMPORT_KEYS
        ]


class TestTemplates:
    def test_writes_excel_template_for_each_entity(self, tmp_path):
        pytest.importorskip("openpyxl")
        written = write_all_templates(tmp_path)

        assert [p.name for p in written] == [
            f"{entity_key}_template.xlsx" for entity_key in importer.IMPORT_KEYS
        ]
        headers, _sample = importer.template_rows("owners")

        table = read_table(written[0])
        assert table.headers == headers
        assert table.sheet_name == importer.TEMPLATE_SHEET_NAME

    def test_template_has_no_sample_row(self, tmp_path):
        """A freshly saved template must never push a demo record into the DB."""
        pytest.importorskip("openpyxl")
        for entity_key in importer.IMPORT_KEYS:
            book = write_template(tmp_path / f"{entity_key}.xlsx", entity_key)
            assert read_table(book).rows == []
            csv_path = write_template(tmp_path / f"{entity_key}.csv", entity_key)
            table = read_table(csv_path)
            assert table.rows == []
            assert table.headers == importer.template_rows(entity_key)[0]

    def test_empty_template_imports_nothing(self, importer_db, repos, tmp_path):
        path = write_template(tmp_path / "owners_template.xlsx", "owners")

        summary = importer.import_file(path, "owners")

        assert (summary.imported, summary.failed) == (0, 0)
        assert repos["client"].get_clients() == []

    def test_excel_template_carries_instructions_sheet(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = write_template(tmp_path / "pets_template.xlsx", "pets")

        sheets = importer.list_sheets(path)
        assert sheets[0] == importer.TEMPLATE_SHEET_NAME
        assert importer.INSTRUCTIONS_SHEET_NAME in sheets
        # The documentation sheet is recognised and refused as a data source.
        assert importer.is_instructions_sheet(importer.INSTRUCTIONS_SHEET_NAME)
        assert not importer.is_instructions_sheet(importer.TEMPLATE_SHEET_NAME)
        # Its columns are documentation, not entity columns.
        doc = read_table(path, importer.INSTRUCTIONS_SHEET_NAME)
        assert importer.detect_entity(doc.headers) is None

    def test_header_cells_explain_the_column(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = write_template(tmp_path / "supplies_template.xlsx", "supplies")

        book = openpyxl.load_workbook(str(path))
        sheet = book[importer.TEMPLATE_SHEET_NAME]
        assert sheet.max_row == 1  # headers only, nothing to import by accident
        assert sheet.freeze_panes == "A2"

        # Every header carries hover help (required/optional + an example).
        labels, required, example, hint = importer.field_guidance(
            "supplies", "purchase_date"
        )
        assert labels == "Purchase Date"
        assert required is False
        assert example == "2025-01-01"
        assert hint

        fields = importer.get_spec("supplies").fields
        header_index = fields.index("purchase_date") + 1
        comment = sheet.cell(row=1, column=header_index).comment
        assert comment is not None
        assert "Purchase Date" in comment.text
        assert "2025-01-01" in comment.text
        book.close()

    def test_field_guidance_covers_every_column(self):
        for entity_key in importer.IMPORT_KEYS:
            guidance = importer.template_guidance(entity_key)
            spec = importer.get_spec(entity_key)
            assert [row[0] for row in guidance] == [
                spec.field_label(name) for name in spec.fields
            ]
            assert [row[1] for row in guidance] == [
                name in spec.required for name in spec.fields
            ]

    def test_field_guidance_rejects_unknown_field(self):
        with pytest.raises(KeyError):
            importer.field_guidance("owners", "nope")

    def test_is_instructions_sheet_aliases(self):
        assert importer.is_instructions_sheet("How to use")
        assert importer.is_instructions_sheet("Read Me")
        assert not importer.is_instructions_sheet("Sheet1")
        assert not importer.is_instructions_sheet("")

    def test_writes_csv_templates_when_asked(self, tmp_path):
        written = write_all_templates(tmp_path, "csv")

        assert [p.name for p in written] == [
            f"{entity_key}_template.csv" for entity_key in importer.IMPORT_KEYS
        ]

    def test_template_format_normalization(self):
        assert importer.normalize_template_format(None) == "xlsx"
        assert importer.normalize_template_format("") == "xlsx"
        assert importer.normalize_template_format(".XLSX") == "xlsx"
        assert importer.normalize_template_format("excel") == "xlsx"
        assert importer.normalize_template_format("tsv") == "csv"
        with pytest.raises(ValueError):
            importer.normalize_template_format("pdf")

    def test_writes_excel_template(self, tmp_path):
        pytest.importorskip("openpyxl")
        path = write_template(tmp_path / "pets_template.xlsx", "pets")
        headers, _sample = importer.template_rows("pets")
        assert read_table(path).headers == headers

    def test_written_template_is_importable(self, importer_db, tmp_path):
        write_template(tmp_path / "owners_template.csv", "owners")
        path = _write_csv(tmp_path / "owners.csv",
                          ["Owner Name", "Phone Number"],
                          [["Ahmed Ali", "01001234567"]])
        summary = importer.import_file(path, "owners")
        assert summary.imported == 1

    def test_import_file_validates_before_writing(self, importer_db, tmp_path):
        path = _write_csv(tmp_path / "owners.csv",
                          ["Phone Number"], [["01001234567"]])
        summary = importer.import_file(path, "owners", dry_run=True)
        assert summary.failed == 1
        assert summary.total == 1


# ------------------------------------------- Suppliers, packages, packages --
class TestImportSuppliers:
    def test_adds_suppliers_and_skips_duplicates(self, importer_db, repos):
        summary = import_table("suppliers", _H_SUPPLIERS, [_SUPPLIER, _SUPPLIER])

        assert (summary.imported, summary.skipped, summary.failed) == (1, 1, 0)
        suppliers = repos["supplier"].get_suppliers()
        assert len(suppliers) == 1
        assert suppliers[0]["supplier_name"] == "Acme Veterinary Supplies"
        assert suppliers[0]["phone"] == "01001234567"
        assert suppliers[0]["location"] == "Cairo"
        assert suppliers[0]["notes"] == "Bulk orders"

    def test_blank_name_fails(self, importer_db):
        summary = import_table("suppliers", _H_SUPPLIERS, [["  "], ["Acme"]])
        assert (summary.imported, summary.failed) == (1, 1)

    def test_dedup_is_by_name_plus_phone_and_location(self, importer_db, repos):
        rows = [
            ["Acme", "0100", "Cairo", ""],
            ["Acme", "0200", "Cairo", ""],
            ["Acme", "0100", "Giza", ""],
            ["Acme", "0100", "Cairo", "notes"],
        ]
        summary = import_table("suppliers", _H_SUPPLIERS, rows)

        assert (summary.imported, summary.skipped, summary.failed) == (3, 1, 0)
        suppliers = repos["supplier"].get_suppliers()
        assert len(suppliers) == 3
        contacts = [(s["supplier_name"], s["phone"], s["location"])
                    for s in suppliers]
        assert ("Acme", "0100", "Cairo") in contacts
        assert ("Acme", "0200", "Cairo") in contacts
        assert ("Acme", "0100", "Giza") in contacts


class TestImportPackages:
    def test_adds_packages_and_skips_duplicates(self, importer_db, repos):
        summary = import_table("packages", _H_PACKAGES, [_PACKAGE, _PACKAGE])

        assert (summary.imported, summary.skipped, summary.failed) == (1, 1, 0)
        rows = repos["package"].get_packages_for_export()
        assert len(rows) == 1
        assert rows[0]["package_name"] == "Puppy Starter"

    def test_package_items_resolve_service_and_supply(self, importer_db, repos):
        import_table("packages", _H_PACKAGES, [_PACKAGE])
        import_table("supplies", _H_SUPPLIES, [_SUPPLY])

        summary = import_table("package_items", _H_PACKAGE_ITEMS,
                               [_PACKAGE_ITEM_SERVICE, _PACKAGE_ITEM_SUPPLY])

        assert (summary.imported, summary.failed) == (2, 0)
        items = repos["package"].get_package_items_for_export()
        kinds = {row["item_type"] for row in items}
        assert kinds == {"service", "supply"}
        assert items[0]["package_name"] == "Puppy Starter"

    def test_package_item_needs_an_existing_package(self, importer_db):
        summary = import_table("package_items", _H_PACKAGE_ITEMS,
                               [["Nobody", "service", "Consultation", 1]])
        assert summary.failed == 1
        assert "Import packages first" in summary.problems()[0].message

    def test_reimported_package_item_is_skipped(self, importer_db, repos):
        import_table("packages", _H_PACKAGES, [_PACKAGE])
        import_table("supplies", _H_SUPPLIES, [_SUPPLY])

        import_table("package_items", _H_PACKAGE_ITEMS, [_PACKAGE_ITEM_SERVICE])
        summary = import_table("package_items", _H_PACKAGE_ITEMS,
                               [_PACKAGE_ITEM_SERVICE])

        assert (summary.imported, summary.skipped) == (0, 1)
        assert len(repos["package"].get_package_items_for_export()) == 1


class TestImportAppointments:
    def _seed_owner_and_pet(self, importer_db):
        import_table("owners", _H_OWNERS, [_OWNER])
        import_table("pets", _H_PETS, [_PET])

    def test_adds_an_appointment(self, importer_db, repos):
        self._seed_owner_and_pet(importer_db)

        summary = import_table("appointments", _H_APPOINTMENTS, [_APPOINTMENT])

        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["appointment"].get_appointments_for_export()
        assert len(rows) == 1
        assert rows[0]["pet_name"] == "Rex"
        assert rows[0]["status"] == "Pending"

    def test_rejects_an_unknown_status(self, importer_db, repos):
        self._seed_owner_and_pet(importer_db)

        row = list(_APPOINTMENT)
        row[5] = "Later"
        summary = import_table("appointments", _H_APPOINTMENTS, [row])

        assert summary.failed == 1
        assert "Invalid appointment status" in summary.problems()[0].message

    def test_requires_an_existing_pet(self, importer_db):
        import_table("owners", _H_OWNERS, [_OWNER])  # no pet imported

        summary = import_table("appointments", _H_APPOINTMENTS, [_APPOINTMENT])

        assert summary.failed == 1
        assert "Import pets first" in summary.problems()[0].message

    def test_reimported_appointment_is_skipped(self, importer_db, repos):
        self._seed_owner_and_pet(importer_db)
        import_table("appointments", _H_APPOINTMENTS, [_APPOINTMENT])

        summary = import_table("appointments", _H_APPOINTMENTS, [_APPOINTMENT])

        assert (summary.imported, summary.skipped) == (0, 1)
        assert len(repos["appointment"].get_appointments_for_export()) == 1


class TestVisitLinkedRecords:
    """Follow-ups, vaccinations, medications, treatments and tests all hang off
    an existing visit, resolved by owner + pet + visit date."""

    def _seed_visit(self, importer_db):
        import_table("owners", _H_OWNERS, [_OWNER])
        import_table("pets", _H_PETS, [_PET])
        import_table("supplies", _H_SUPPLIES, [_SUPPLY])
        import_table("visits", _H_VISITS, [_VISIT])

    def _seed_owner_pet_only(self, importer_db):
        import_table("owners", _H_OWNERS, [_OWNER])
        import_table("pets", _H_PETS, [_PET])

    def test_followup_added(self, importer_db, repos):
        self._seed_visit(importer_db)

        summary = import_table("followups", _H_FOLLOWUPS, [_FOLLOWUP])

        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["followup"].get_followups_for_export()
        assert len(rows) == 1
        assert rows[0]["status"] == "Pending"  # raw state, never the derived "Late"

    def test_followup_requires_the_visit(self, importer_db, repos):
        self._seed_owner_pet_only(importer_db)  # owner + pet, but no visit

        summary = import_table("followups", _H_FOLLOWUPS, [_FOLLOWUP])

        assert summary.failed == 1
        assert "Import visits first" in summary.problems()[0].message
        assert repos["followup"].get_followups_for_export() == []

    def test_followup_rejects_unknown_status(self, importer_db):
        self._seed_visit(importer_db)
        row = list(_FOLLOWUP)
        row[5] = "Late"
        summary = import_table("followups", _H_FOLLOWUPS, [row])
        assert summary.failed == 1

    def test_vaccination_added(self, importer_db, repos):
        self._seed_visit(importer_db)
        summary = import_table("vaccinations", _H_VACCINATIONS, [_VACCINATION])
        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["vaccination"].get_vaccinations_for_export()
        assert len(rows) == 1
        assert rows[0]["vaccine_name"] == "Rabies"

    def test_medication_added(self, importer_db, repos):
        self._seed_visit(importer_db)
        summary = import_table("medications", _H_MEDICATIONS, [_MEDICATION])
        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["medication"].get_medications_for_export()
        assert len(rows) == 1
        assert rows[0]["item_name"] == "Amox 250"
        assert rows[0]["dosage"] == "1 tablet twice daily"

    def test_medication_requires_a_known_supply(self, importer_db, repos):
        self._seed_owner_pet_only(importer_db)  # no supplies imported
        import_table("visits", _H_VISITS,
                     [["2025-01-15 10:00", "Ahmed Ali", "01001234567", "Rex",
                       "", "", "", "Yes", 38.5, ""]])

        summary = import_table("medications", _H_MEDICATIONS, [_MEDICATION])

        assert summary.failed == 1
        assert "Import supplies first" in summary.problems()[0].message

    def test_treatment_added(self, importer_db, repos):
        self._seed_visit(importer_db)
        summary = import_table("treatments", _H_TREATMENTS, [_TREATMENT])
        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["treatment"].get_treatments_for_export()
        assert len(rows) == 1
        assert rows[0]["treatment_name"] == "Wound cleaning"

    def test_test_added_with_result_state(self, importer_db, repos):
        self._seed_visit(importer_db)
        summary = import_table("tests", _H_TESTS, [_TEST])
        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["test"].get_tests_for_export()
        assert len(rows) == 1
        assert rows[0]["result"] == "Normal"

    def test_test_rejects_unknown_result(self, importer_db):
        self._seed_visit(importer_db)
        row = list(_TEST)
        row[5] = "Nope"
        summary = import_table("tests", _H_TESTS, [row])
        assert summary.failed == 1

    def test_visit_linked_records_are_not_duplicated(self, importer_db, repos):
        """Every visit-linked sheet skips a record it already added."""
        self._seed_visit(importer_db)
        sheets = [
            ("followups", _H_FOLLOWUPS, _FOLLOWUP),
            ("vaccinations", _H_VACCINATIONS, _VACCINATION),
            ("medications", _H_MEDICATIONS, _MEDICATION),
            ("treatments", _H_TREATMENTS, _TREATMENT),
            ("tests", _H_TESTS, _TEST),
        ]
        for key, headers, row in sheets:
            first = import_table(key, headers, [row])
            second = import_table(key, headers, [row])
            assert first.imported == 1, (key, first.results[0].message)
            assert second.skipped == 1, (key, second.results[0].message)

    def test_visit_linked_records_resolve_in_a_shared_run(self, importer_db,
                                                          repos, tmp_path):
        """The handful of linked sheets validate against one shared context."""
        plan_rows = [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
            ("Supplies", "supplies", [_SUPPLY]),
            ("Visits", "visits", [_VISIT]),
            ("Follow-ups", "followups", [_FOLLOWUP]),
            ("Vaccinations", "vaccinations", [_VACCINATION]),
            ("Medications", "medications", [_MEDICATION]),
            ("Treatments", "treatments", [_TREATMENT]),
            ("Tests", "tests", [_TEST]),
        ]
        path = importer.write_excel_workbook(tmp_path / "linked.xlsx",
                                             plan_rows)
        summary = importer.import_workbook(path)
        assert summary.failed == 0
        assert summary.imported == 9
        for key in ("followups", "vaccinations", "medications",
                    "treatments", "tests"):
            assert summary.sheet_summary(key).imported == 1


class TestImportExpenses:
    def test_adds_an_expense_receipt(self, importer_db, repos):
        summary = import_table("expenses", _H_EXPENSES, [_EXPENSE])

        assert (summary.imported, summary.failed) == (1, 0)
        rows = repos["sales"].get_expenses_for_export()
        assert len(rows) == 1
        assert rows[0]["amount"] == 5000.0

    def test_requires_a_positive_amount(self, importer_db):
        row = list(_EXPENSE)
        row[3] = -5
        summary = import_table("expenses", _H_EXPENSES, [row])
        assert summary.failed == 1

    def test_preserves_a_given_receipt_code(self, importer_db, repos):
        token = "EXPENSE-202501-0007"
        headers = _H_EXPENSES + ["Receipt Code"]
        summary = import_table("expenses", headers, [_EXPENSE + [token]])

        assert summary.imported == 1, summary.results[0].message
        assert repos["sales"].get_receipt_id_by_code(token) is not None

    def test_validate_skips_an_existing_expense(self, importer_db, repos):
        token = "EXPENSE-202501-0009"
        headers = _H_EXPENSES + ["Receipt Code"]
        import_table("expenses", headers, [_EXPENSE + [token]])

        summary = import_table("expenses", headers, [_EXPENSE + [token]],
                               dry_run=True)

        assert (summary.imported, summary.skipped) == (0, 1)


class TestImportRetailSales:
    _H = ["Receipt Code", "Receipt Date", "Owner Name", "Phone Number",
          "Items", "Discount", "Notes"]

    def test_adds_a_retail_receipt_with_items(self, importer_db, repos,
                                              entity_factory):
        entity_factory["make_client"]("Ahmed Ali", "01001234567")
        entity_factory["make_supply"](quantity=10, name="Amox 250", sell_price=25)
        row = ["RETAIL-0001", "2025-01-20 15:00:00", "Ahmed Ali",
               "01001234567", "Amox 250 x2", 0, ""]

        summary = import_table("retail_sales", self._H, [row])

        assert summary.imported == 1, summary.results[0].message
        assert repos["sales"].get_receipt_id_by_code("RETAIL-0001") is not None
        exported = repos["sales"].get_retail_sales_for_export()
        assert exported[0]["items"] == "Amox 250 x2"
        assert exported[0]["receipt_code"] == "RETAIL-0001"

    def test_existing_receipt_code_is_skipped(self, importer_db, repos,
                                              entity_factory):
        entity_factory["make_client"]("Ahmed Ali", "01001234567")
        entity_factory["make_supply"](quantity=10, name="Amox 250", sell_price=25)
        row = ["RETAIL-0002", "2025-01-20 15:00:00", "Ahmed Ali",
               "01001234567", "Amox 250 x2", 0, ""]

        import_table("retail_sales", self._H, [row])
        summary = import_table("retail_sales", self._H, [row])

        assert summary.skipped == 1

    def test_validate_skips_an_existing_retail_sale(self, importer_db, repos,
                                                    entity_factory):
        entity_factory["make_client"]("Ahmed Ali", "01001234567")
        entity_factory["make_supply"](quantity=10, name="Amox 250", sell_price=25)
        row = ["RETAIL-0009", "2025-01-20 15:00:00", "Ahmed Ali",
               "01001234567", "Amox 250 x2", 0, ""]

        import_table("retail_sales", self._H, [row])
        summary = import_table("retail_sales", self._H, [row], dry_run=True)

        assert (summary.imported, summary.skipped) == (0, 1)

    def test_unknown_item_fails_row(self, importer_db, entity_factory):
        entity_factory["make_client"]("Ahmed Ali", "01001234567")
        row = ["RETAIL-0003", "2025-01-20 15:00:00", "Ahmed Ali",
               "01001234567", "Mystery x1", 0, ""]

        summary = import_table("retail_sales", self._H, [row])

        assert summary.failed == 1
        assert "Mystery" in summary.results[0].message


class TestImportPayments:
    def _seed_expense_receipt(self, importer_db):
        import_table("expenses", _H_EXPENSES, [_EXPENSE])

    def test_payment_added_against_an_expense_receipt(self, importer_db, repos):
        self._seed_expense_receipt(importer_db)
        month = datetime.date.today().strftime("%Y%m")
        payment = [f"EXPENSE-{month}-0001", 5000.0, "Cash", "2025-01-15", ""]

        summary = import_table("payments", _H_PAYMENTS, [payment])

        assert (summary.imported, summary.failed) == (1, 0)
        rows = payment_repo.get_payments_for_export()
        assert len(rows) == 1
        assert rows[0]["amount"] == 5000.0
        assert rows[0]["payment_date"] == "2025-01-15"

    def test_negative_amount_records_a_refund(self, importer_db, repos):
        self._seed_expense_receipt(importer_db)
        month = datetime.date.today().strftime("%Y%m")
        code = f"EXPENSE-{month}-0001"
        import_table("payments", _H_PAYMENTS,
                     [[code, 5000.0, "Cash", "2025-01-15", ""],
                      [code, 1000.0, "Cash", "2025-01-16", ""],  # overpays
                      [code, -200.0, "Cash", "2025-01-17", ""]])  # refund

        amounts = [row["amount"] for row in
                   payment_repo.get_payments_for_export()]
        assert sum(amounts) == 5800.0  # 5000 + 1000 - 200

    def test_unknown_receipt_fails(self, importer_db, repos):
        summary = import_table("payments", _H_PAYMENTS,
                               [["VISIT-999999-0001", 100.0, "Cash", "", ""]])
        assert summary.failed == 1
        assert "not found" in summary.problems()[0].message
        assert payment_repo.get_payments_for_export() == []

    def test_reimported_payment_is_skipped(self, importer_db, repos):
        self._seed_expense_receipt(importer_db)
        month = datetime.date.today().strftime("%Y%m")
        payment = [f"EXPENSE-{month}-0001", 5000.0, "Cash", "2025-01-15", ""]

        import_table("payments", _H_PAYMENTS, [payment])
        summary = import_table("payments", _H_PAYMENTS, [payment])

        assert (summary.imported, summary.skipped) == (0, 1)
        assert sum(r["amount"] for r in
                   payment_repo.get_payments_for_export()) == 5000.0

    def test_validate_skips_an_existing_payment(self, importer_db, repos):
        self._seed_expense_receipt(importer_db)
        month = datetime.date.today().strftime("%Y%m")
        payment = [f"EXPENSE-{month}-0001", 5000.0, "Cash", "2025-01-15", ""]

        import_table("payments", _H_PAYMENTS, [payment])
        summary = import_table("payments", _H_PAYMENTS, [payment], dry_run=True)

        assert (summary.imported, summary.skipped) == (0, 1)

    def test_distinct_installments_are_both_imported(self, importer_db, repos):
        self._seed_expense_receipt(importer_db)
        month = datetime.date.today().strftime("%Y%m")
        code = f"EXPENSE-{month}-0001"

        summary = import_table("payments", _H_PAYMENTS,
                               [[code, 3000.0, "Cash", "2025-01-15", ""],
                                [code, 2000.0, "Cash", "2025-01-16", ""]])

        assert (summary.imported, summary.skipped) == (2, 0)
        assert sum(r["amount"] for r in
                   payment_repo.get_payments_for_export()) == 5000.0