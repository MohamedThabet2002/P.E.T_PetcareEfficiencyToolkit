"""Excel / CSV import into the clinic database.

Reads a spreadsheet (``.xlsx`` / ``.xlsm`` via ``openpyxl``) or a delimited text
file (``.csv`` / ``.tsv`` / ``.txt`` via the stdlib ``csv`` module), matches its
columns against the fields of one entity (owners / pets / supplies / visits) and
writes the rows through the existing repositories, so auditing, stock
validation and receipt creation behave exactly as they do in the normal UI
flows.

The module is deliberately UI-free; ``src/ui/dialogs/import_data_dialog.py``
drives it. Column matching is alias based so real-world exports ("Client Name",
"Qty", "Phone") work without hand-editing headers, and ``write_template``
produces a ready-to-fill starter file for each entity. Templates ship **headers
only** - the guidance (steps, per-column examples) lives in header comments and a
documentation sheet that the dialog refuses to read, so a demo record can never
be imported by accident.

A workbook may also hold every data type at once (see
:func:`write_excel_workbook` / ``exporter.write_workbook``): ``plan_workbook``
detects the entity behind each sheet from its columns and ``import_workbook``
imports them all in dependency order, so a file exported by this app can be
handed straight back to it.
"""

import csv
import datetime
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.core.database import get_connection
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.client_repo as client_repo
import src.core.repositories.followup_repo as followup_repo
import src.core.repositories.lookup_repo as lookup_repo
import src.core.repositories.medication_repo as medication_repo
import src.core.repositories.package_repo as package_repo
import src.core.repositories.payment_repo as payment_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.supplier_repo as supplier_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.test_repo as test_repo
import src.core.repositories.treatment_repo as treatment_repo
import src.core.repositories.vaccination_repo as vaccination_repo
import src.core.repositories.visit_repo as visit_repo
from src.config.meta import APP_NAME as APP_SHORT_NAME
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

#: Colours used by the generated Excel templates (mirror the brand palette).
_TEMPLATE_BRAND = "4A90E2"
_TEMPLATE_DANGER = "C0392B"

EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xltx", ".xltm")
TEXT_EXTENSIONS = (".csv", ".tsv", ".txt")
SUPPORTED_EXTENSIONS = EXCEL_EXTENSIONS + TEXT_EXTENSIONS

# Excel serial-date origin (day 0 == 1899-12-30, matching Excel's 1900 system
# with the well-known leap-year bug).
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
)

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%m/%d/%Y %H:%M",
)

_TRUE_TOKENS = {"1", "true", "yes", "y", "t", "on", "x", "checked"}
_FALSE_TOKENS = {"0", "false", "no", "n", "f", "off", "", "none", "null", "-"}

_ITEMS_SEPARATOR = re.compile(r"[;\n]+")
_ITEMS_QUANTITY = re.compile(r"^(?P<name>.+?)\s*(?:[x*\u00d7]\s*|\s+)?(?P<qty>\d+(?:\.\d+)?)$")


# --------------------------------------------------------------- Spec model --
@dataclass(frozen=True)
class ImportSpec:
    """Describes one importable entity: its columns, aliases and a sample row."""

    key: str
    label_key: str
    fields: tuple
    required: tuple
    labels: dict
    aliases: dict
    sample: tuple

    def field_label(self, field_name):
        return self.labels.get(field_name, field_name.replace("_", " ").capitalize())


_SPECS = (
    ImportSpec(
        key="owners",
        label_key="Import Owners",
        fields=("owner_name", "phone_number", "notes"),
        required=("owner_name",),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "notes": "Notes",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name", "name", "full name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("Ahmed Ali", "01001234567", ""),
    ),
    ImportSpec(
        key="pets",
        label_key="Import Pets",
        fields=("pet_name", "owner_name", "phone_number", "species", "breed",
                "gender", "age_months", "weight"),
        required=("pet_name", "owner_name"),
        labels={
            "pet_name": "Pet Name",
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "species": "Species",
            "breed": "Breed",
            "gender": "Gender",
            "age_months": "Age (months)",
            "weight": "Weight (kg)",
        },
        aliases={
            "pet_name": ("pet", "pet name", "animal", "animal name", "name"),
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "species": ("species", "animal type", "type", "pet type"),
            "breed": ("breed", "breed name"),
            "gender": ("gender", "sex"),
            "age_months": ("age months", "age in months", "age (months)",
                           "age_months", "age", "months", "age mo"),
            "weight": ("weight", "weight kg", "weight (kg)", "weight in kg",
                       "weight_kg", "kg"),
        },
        sample=("Rex", "Ahmed Ali", "01001234567", "Dog", "Labrador Retriever",
                "Male", 24, 25.5),
    ),
    ImportSpec(
        key="suppliers",
        label_key="Import Suppliers",
        fields=("supplier_name", "phone", "location", "notes"),
        required=("supplier_name",),
        labels={
            "supplier_name": "Supplier Name",
            "phone": "Phone",
            "location": "Location",
            "notes": "Notes",
        },
        aliases={
            "supplier_name": ("supplier", "supplier name", "vendor",
                              "distributor", "name"),
            "phone": ("phone", "phone no", "phone number", "mobile",
                      "mobile number", "contact", "contact number",
                      "telephone", "tel"),
            "location": ("location", "address", "city", "place", "region"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("Acme Veterinary Supplies", "01001234567", "Cairo", ""),
    ),
    ImportSpec(
        key="supplies",
        label_key="Import Supplies",
        fields=("item_name", "category", "sub_category", "quantity", "buy_price",
                "sell_price", "purchase_date", "expiry_date", "supplier"),
        required=("item_name", "category"),
        labels={
            "item_name": "Item Name",
            "category": "Category",
            "sub_category": "Sub Category",
            "quantity": "Quantity",
            "buy_price": "Buy Price",
            "sell_price": "Sell Price",
            "purchase_date": "Purchase Date",
            "expiry_date": "Expiry Date",
            "supplier": "Supplier",
        },
        aliases={
            "item_name": ("item", "item name", "product", "product name",
                          "supply", "supply name", "name"),
            "category": ("category", "main category", "group"),
            "sub_category": ("sub category", "subcategory", "sub cat", "type"),
            "quantity": ("quantity", "qty", "stock", "current stock", "count",
                         "on hand"),
            "buy_price": ("buy price", "buy_price", "cost", "cost price",
                          "purchase price", "unit cost"),
            "sell_price": ("sell price", "sell_price", "price", "sale price",
                           "selling price", "unit price"),
            "purchase_date": ("purchase date", "purchased on", "buy date",
                              "received date", "date"),
            "expiry_date": ("expiry date", "expiration date", "expires on",
                            "expires", "expiry", "exp date"),
            "supplier": ("supplier", "vendor", "distributor"),
        },
        sample=("Amoxicillin 250mg", "Medicine", "Antibiotics", 50, 12.5, 25.0,
                "2025-01-01", "2026-01-01", ""),
    ),
    ImportSpec(
        key="packages",
        label_key="Import Packages",
        fields=("package_name", "description", "total_price"),
        required=("package_name",),
        labels={
            "package_name": "Package Name",
            "description": "Description",
            "total_price": "Total Price",
        },
        aliases={
            "package_name": ("package", "package name", "name", "bundle"),
            "description": ("description", "details", "notes"),
            "total_price": ("total price", "total_price", "price", "total",
                            "amount"),
        },
        sample=("Puppy Starter", "First-year wellness bundle", 1500.0),
    ),
    ImportSpec(
        key="package_items",
        label_key="Import Package Items",
        fields=("package_name", "item_type", "item_name", "quantity"),
        required=("package_name", "item_name"),
        labels={
            "package_name": "Package Name",
            "item_type": "Item Type",
            "item_name": "Item Name",
            "quantity": "Quantity",
        },
        aliases={
            "package_name": ("package", "package name"),
            "item_type": ("item type", "type", "kind"),
            "item_name": ("item", "item name", "service", "supply", "name"),
            "quantity": ("quantity", "qty", "count", "amount"),
        },
        sample=("Puppy Starter", "service", "Consultation", 1),
    ),
    ImportSpec(
        key="appointments",
        label_key="Import Appointments",
        fields=("appointment_date", "owner_name", "phone_number", "pet_name",
                "service", "status", "notes"),
        required=("appointment_date", "owner_name", "pet_name"),
        labels={
            "appointment_date": "Appointment Date",
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "service": "Service",
            "status": "Status",
            "notes": "Notes",
        },
        aliases={
            "appointment_date": ("appointment date", "appointment_date",
                                 "date", "datetime"),
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "service": ("service", "reason", "type", "purpose"),
            "status": ("status", "state"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("2025-02-01 10:00:00", "Ahmed Ali", "01001234567", "Rex",
                "Vaccination", "Pending", ""),
    ),
    ImportSpec(
        key="visits",
        label_key="Import Visits",
        fields=("visit_date", "owner_name", "phone_number", "pet_name",
                "diagnosis", "reason_for_visit", "notes", "consult",
                "temperature", "supplies", "receipt_code"),
        required=("visit_date", "owner_name", "pet_name"),
        labels={
            "visit_date": "Visit Date",
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "diagnosis": "Diagnosis",
            "reason_for_visit": "Reason for Visit",
            "notes": "Notes",
            "consult": "Consultation",
            "temperature": "Temperature",
            "supplies": "Supplies",
            "receipt_code": "Receipt Code",
        },
        aliases={
            "visit_date": ("visit date", "visit_date", "date", "datetime",
                           "visit datetime", "visit date time"),
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "diagnosis": ("diagnosis", "diagnoses", "dx"),
            "reason_for_visit": ("reason for visit", "reason", "complaint",
                                 "cause", "presenting complaint"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
            "consult": ("consult", "consultation", "is consult",
                        "has consult", "consultation charge", "consult fee"),
            "temperature": ("temperature", "temp", "body temperature"),
            "supplies": ("supplies", "supply", "items", "item", "products",
                         "used supplies", "materials", "medications"),
            "receipt_code": ("receipt code", "receipt_code", "receipt",
                             "code", "invoice", "invoice number"),
        },
        sample=("2025-01-15 10:00:00", "Ahmed Ali", "01001234567", "Rex",
                "Severe otitis externa", "Ear scratching", "", "Yes", 38.5,
                "Amoxicillin 250mg x2", "VISIT-202501-0001"),
    ),
    ImportSpec(
        key="followups",
        label_key="Import Follow-ups",
        fields=("owner_name", "phone_number", "pet_name", "visit_date",
                "follow_up_date", "status", "notes"),
        required=("owner_name", "pet_name", "follow_up_date"),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "visit_date": "Visit Date",
            "follow_up_date": "Follow-up Date",
            "status": "Status",
            "notes": "Notes",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "visit_date": ("visit date", "visit_date", "original visit date",
                           "parent visit date"),
            "follow_up_date": ("follow up date", "follow-up date",
                               "follow_up_date", "followup date", "due date",
                               "date"),
            "status": ("status", "state"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "2025-02-15", "Pending", ""),
    ),
    ImportSpec(
        key="vaccinations",
        label_key="Import Vaccinations",
        fields=("owner_name", "phone_number", "pet_name", "visit_date",
                "vaccine_name"),
        required=("owner_name", "pet_name", "visit_date", "vaccine_name"),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "visit_date": "Visit Date",
            "vaccine_name": "Vaccine",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "visit_date": ("visit date", "visit_date", "date"),
            "vaccine_name": ("vaccine", "vaccine name", "vaccination", "name"),
        },
        sample=("Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "Rabies"),
    ),
    ImportSpec(
        key="medications",
        label_key="Import Medications",
        fields=("owner_name", "phone_number", "pet_name", "visit_date",
                "item_name", "dosage", "instructions"),
        required=("owner_name", "pet_name", "visit_date", "item_name"),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "visit_date": "Visit Date",
            "item_name": "Medication",
            "dosage": "Dosage",
            "instructions": "Instructions",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "visit_date": ("visit date", "visit_date", "date"),
            "item_name": ("medication", "medicine", "item", "item name",
                          "drug", "name"),
            "dosage": ("dosage", "dose"),
            "instructions": ("instructions", "directions", "notes"),
        },
        sample=("Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "Amoxicillin 250mg", "1 tablet twice daily", "After food"),
    ),
    ImportSpec(
        key="treatments",
        label_key="Import Treatments",
        fields=("owner_name", "phone_number", "pet_name", "visit_date",
                "treatment_name"),
        required=("owner_name", "pet_name", "visit_date", "treatment_name"),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "visit_date": "Visit Date",
            "treatment_name": "Treatment",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "visit_date": ("visit date", "visit_date", "date"),
            "treatment_name": ("treatment", "treatment name", "procedure",
                               "name"),
        },
        sample=("Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "Wound cleaning"),
    ),
    ImportSpec(
        key="tests",
        label_key="Import Tests",
        fields=("owner_name", "phone_number", "pet_name", "visit_date",
                "test_name", "result"),
        required=("owner_name", "pet_name", "visit_date", "test_name"),
        labels={
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "pet_name": "Pet Name",
            "visit_date": "Visit Date",
            "test_name": "Test",
            "result": "Result",
        },
        aliases={
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "pet_name": ("pet", "pet name", "animal", "animal name"),
            "visit_date": ("visit date", "visit_date", "date"),
            "test_name": ("test", "test name", "lab test", "name"),
            "result": ("result", "state", "status", "outcome"),
        },
        sample=("Ahmed Ali", "01001234567", "Rex", "2025-01-15 10:00:00",
                "Blood count", "Normal"),
    ),
    ImportSpec(
        key="expenses",
        label_key="Import Expenses",
        fields=("expense_date", "category", "item_name", "amount", "notes",
                "receipt_code"),
        required=("expense_date", "item_name", "amount"),
        labels={
            "expense_date": "Expense Date",
            "category": "Category",
            "item_name": "Item Name",
            "amount": "Amount",
            "notes": "Notes",
            "receipt_code": "Receipt Code",
        },
        aliases={
            "expense_date": ("expense date", "expense_date", "date"),
            "category": ("category", "type", "group"),
            "item_name": ("item", "item name", "description", "expense",
                          "name"),
            "amount": ("amount", "total", "price", "cost", "value"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
            "receipt_code": ("receipt code", "receipt_code", "receipt",
                             "code", "invoice", "invoice number"),
        },
        sample=("2025-01-20", "Rent", "Monthly clinic rent", 5000.0, "",
                "EXPENSE-001"),
    ),
    ImportSpec(
        key="retail_sales",
        label_key="Import Retail Sales",
        fields=("receipt_code", "receipt_date", "owner_name", "phone_number",
                "items", "discount", "notes"),
        required=("receipt_code", "receipt_date", "items"),
        labels={
            "receipt_code": "Receipt Code",
            "receipt_date": "Receipt Date",
            "owner_name": "Owner Name",
            "phone_number": "Phone Number",
            "items": "Items",
            "discount": "Discount",
            "notes": "Notes",
        },
        aliases={
            "receipt_code": ("receipt code", "receipt_code", "receipt",
                             "code", "invoice", "invoice number"),
            "receipt_date": ("receipt date", "receipt_date", "date",
                             "sale date", "purchase date"),
            "owner_name": ("owner", "owner name", "client", "client name",
                           "customer", "customer name", "name"),
            "phone_number": ("phone", "phone no", "phone number", "mobile",
                             "mobile number", "contact", "contact number",
                             "telephone", "tel"),
            "items": ("items", "item", "supplies", "supply", "products",
                      "basket", "sale items"),
            "discount": ("discount", "disc", "reduction"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("RETAIL-001", "2025-01-20 15:00:00", "Ahmed Ali", "01001234567",
                "Hill's Wet Cat Food x2", 0, ""),
    ),
    ImportSpec(
        key="payments",
        label_key="Import Payments",
        fields=("receipt_code", "amount", "payment_method", "payment_date",
                "notes"),
        required=("receipt_code", "amount"),
        labels={
            "receipt_code": "Receipt Code",
            "amount": "Amount",
            "payment_method": "Payment Method",
            "payment_date": "Payment Date",
            "notes": "Notes",
        },
        aliases={
            "receipt_code": ("receipt code", "receipt_code", "receipt",
                             "code", "invoice", "invoice number"),
            "amount": ("amount", "paid", "payment", "value"),
            "payment_method": ("payment method", "method", "type"),
            "payment_date": ("payment date", "payment_date", "date"),
            "notes": ("note", "notes", "comment", "comments", "remarks"),
        },
        sample=("VISIT-202501-0001", 500.0, "Cash", "2025-01-15", ""),
    ),
)

IMPORT_SPECS = {spec.key: spec for spec in _SPECS}
IMPORT_KEYS = tuple(IMPORT_SPECS.keys())


def get_spec(entity_key):
    """Returns the :class:`ImportSpec` for ``entity_key``.

    Raises:
        KeyError: when the entity is not importable.
    """
    try:
        return IMPORT_SPECS[entity_key]
    except KeyError:
        raise KeyError(f"Unknown import entity: {entity_key}") from None


# ----------------------------------------------------------------- Tables ---
@dataclass
class ImportTable:
    """A parsed sheet: normalized headers plus raw text cells."""

    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    row_numbers: list = field(default_factory=list)
    sheet_name: str = ""


def _cell_to_text(value):
    """Renders one spreadsheet/CSV cell as trimmed text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime.datetime):
        if value.hour or value.minute or value.second:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value).rstrip("0").rstrip(".")
    return str(value).strip()


def _is_blank_row(cells):
    return all(_cell_to_text(cell) == "" for cell in cells)


def _build_table(raw_rows, sheet_name=""):
    """Turns raw sheet rows (first non-empty row = headers) into an ImportTable.

    ``row_numbers`` records each data row's 1-based position in the file (the
    header is row 1), so error messages point at the user's actual spreadsheet.
    """
    table = ImportTable(sheet_name=sheet_name)
    file_row = 0
    for cells in raw_rows:
        file_row += 1
        if _is_blank_row(cells):
            continue
        if not table.headers:
            table.headers = [_cell_to_text(cell) for cell in cells]
            continue
        table.rows.append([_cell_to_text(cell) for cell in cells])
        table.row_numbers.append(file_row)
    return table


def list_sheets(path):
    """Returns the sheet names of an Excel workbook ([] for text files)."""
    path = Path(path)
    if path.suffix.lower() not in EXCEL_EXTENSIONS:
        return []
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("openpyxl is required to read Excel files") from exc

    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _read_excel(path, sheet=None):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to read Excel files") from exc

    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        sheet_names = list(workbook.sheetnames)
        if not sheet_names:
            return ImportTable(sheet_name="")
        target = sheet or sheet_names[0]
        if target not in sheet_names:
            raise ValueError(f"Sheet not found: {target}")
        worksheet = workbook[target]
        return _build_table(list(worksheet.iter_rows(values_only=True)), target)
    finally:
        workbook.close()


def _read_text(path):
    text = None
    last_error = None
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as handle:
                text = handle.read()
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if text is None:
        raise last_error

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(text.splitlines(), dialect)
    return _build_table(list(reader))


def read_table(path, sheet=None):
    """Reads ``path`` into an :class:`ImportTable`.

    Raises:
        ValueError: for an unsupported file extension.
        RuntimeError: when openpyxl is missing but an Excel file was given.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    suffix = path.suffix.lower()
    if suffix in EXCEL_EXTENSIONS:
        return _read_excel(path, sheet)
    if suffix in TEXT_EXTENSIONS:
        return _read_text(path)
    raise ValueError(f"Unsupported file type: {suffix or path.name}")


# ------------------------------------------------------- Column matching ---
def normalize_header(value):
    """Lower-cases a header and collapses its whitespace."""
    return re.sub(r"\s+", " ", _cell_to_text(value)).strip().lower()


def _squash(value):
    return re.sub(r"[^a-z0-9]+", "", normalize_header(value))


def match_columns(headers, spec):
    """Maps each spec field to a column index (``None`` when absent).

    Two passes are used: an exact match on the normalized header, then a
    punctuation-insensitive match so ``Age (months)`` still finds ``age months``.
    The first matching column wins, so duplicates never overwrite each other.
    """
    normalized = [normalize_header(header) for header in headers]
    squashed = [_squash(header) for header in headers]

    column_map = {}
    used_indexes = set()

    def _assign(field_name, lookup, values):
        if field_name in column_map or not lookup:
            return
        for index, value in enumerate(values):
            if index in used_indexes or value not in lookup:
                continue
            column_map[field_name] = index
            used_indexes.add(index)
            return

    for field_name in spec.fields:
        candidates = [field_name, field_name.replace("_", " ")]
        candidates.extend(spec.aliases.get(field_name, ()))
        _assign(field_name, {normalize_header(c) for c in candidates}, normalized)
    for field_name in spec.fields:
        if field_name in column_map:
            continue
        candidates = [field_name, field_name.replace("_", " ")]
        candidates.extend(spec.aliases.get(field_name, ()))
        _assign(field_name, {_squash(c) for c in candidates}, squashed)

    return {name: column_map.get(name) for name in spec.fields}


def missing_required_columns(headers, spec):
    """Returns the required fields that are absent from ``headers``."""
    column_map = match_columns(headers, spec)
    return [name for name in spec.required if column_map.get(name) is None]


def detect_entity(headers):
    """Returns the importable entity whose columns best fit ``headers``.

    Used to preselect a data type when the user picks a file. Falls back to
    ``None`` when nothing scores at least 2 matched required/optional fields.
    """
    best_key, best_score = None, 0
    for key, spec in IMPORT_SPECS.items():
        column_map = match_columns(headers, spec)
        matched = sum(1 for index in column_map.values() if index is not None)
        if missing_required_columns(headers, spec):
            matched = 0
        if matched > best_score:
            best_key, best_score = key, matched
    return best_key if best_score >= 2 else None


def _entity_from_sheet_name(sheet_name):
    """Maps a template/export sheet name back to its entity, or None.

    Only used as a fallback when :func:`detect_entity` finds nothing: the
    ``suppliers`` sheet is a single column, which can never satisfy the
    two-column detection threshold, so our own named sheets are resolved by
    their :data:`SHEET_NAMES` entry instead.
    """
    if not sheet_name:
        return None
    key = str(sheet_name).strip().lower()
    for entity_key, name in SHEET_NAMES.items():
        if name.lower() == key:
            return entity_key
    return None


# --------------------------------------------------------- Value coercion --
def to_text(value, default=""):
    text = _cell_to_text(value)
    return text if text else default


def to_number(value, default=0.0):
    text = to_text(value).replace(",", "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        pass
    # Tolerate a leading currency symbol such as "$12.50" or "EGP 12.50".
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else default


def to_int(value, default=0):
    return int(round(to_number(value, default)))


def to_bool(value, default=False):
    text = _squash(value)
    if text in _FALSE_TOKENS:
        return False
    if text in _TRUE_TOKENS:
        return True
    if text in ("true", "yes"):
        return True
    return default


def to_date(value):
    """Parses a cell into a ``YYYY-MM-DD`` string (or ``None``)."""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")

    text = to_text(value)
    if not text:
        return None
    # Raw Excel serial numbers (dates stored without a date format).
    if re.fullmatch(r"-?\d{5}(\.\d+)?", text):
        try:
            serial = float(text)
        except ValueError:
            return None
        return (_EXCEL_EPOCH + datetime.timedelta(days=int(serial))).strftime("%Y-%m-%d")

    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # A cell that carries a time as well ("2025-01-15 10:30").
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def to_datetime(value):
    """Parses a cell into a ``YYYY-MM-DD HH:MM:SS`` string (or ``None``)."""
    text = to_text(value)
    if not text:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    date_text = to_date(text)
    if date_text:
        return f"{date_text} 00:00:00"
    return None


def parse_items(value):
    """Parses a free-text supplies cell into ``add_visit`` item dicts.

    Accepts ``Name; Other x2`` / ``Name 3`` / ``Name*1.5`` (quantity rounded).
    """
    items = []
    for chunk in _ITEMS_SEPARATOR.split(to_text(value)):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _ITEMS_QUANTITY.match(chunk)
        if match:
            name = match.group("name").strip(" ,;")
            quantity = max(1, int(round(float(match.group("qty")))))
        else:
            name, quantity = chunk, 1
        if name:
            items.append({"item_name": name, "quantity": quantity})
    return items


# ---------------------------------------------------------------- Results ---
STATUS_IMPORTED = "imported"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class RowResult:
    """Outcome of a single imported row (row_number is the file row, 1-based)."""

    row_number: int
    status: str
    message: str = ""
    entity_id: object = None


@dataclass
class ImportSummary:
    """Aggregated outcome of one ``import_table`` run."""

    entity: str
    total: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    results: list = field(default_factory=list)

    def add(self, result):
        self.total += 1
        self.results.append(result)
        if result.status == STATUS_IMPORTED:
            self.imported += 1
        elif result.status == STATUS_SKIPPED:
            self.skipped += 1
        else:
            self.failed += 1
        return result

    def problems(self):
        """Row results the user should look at (failures first)."""
        return [r for r in self.results if r.status != STATUS_SKIPPED]


# ------------------------------------------------------------ Import core --
class _Context:
    """Per-run caches so repeated owner/pet lookups hit the DB only once.

    A dry run additionally remembers what the run *would* have created, so a
    whole workbook can be validated in one pass: a pet whose owner is created
    by the owners sheet, or a visit whose supply item is created by the supplies
    sheet, resolves instead of being reported as a failure. Planned records get
    negative placeholder ids, which can never collide with real row ids.
    """

    def __init__(self, user_id=None, dry_run=False):
        self.user_id = user_id
        self.dry_run = dry_run
        self._owners = {}
        self._pets = {}
        self._categories = None
        self._suppliers = {}
        self._packages = {}
        self._visits = {}
        self._receipts = set()
        self._planned_items = set()
        self._planned_supplies = set()
        self._followups = set()
        self._clinical = set()
        self._package_items = set()
        self._appointments = set()
        self._planned_counter = 0
        self.created_owners = 0

    def planned_id(self):
        """Returns a fresh negative id standing in for a record not written yet."""
        self._planned_counter -= 1
        return self._planned_counter

    # -- owners ------------------------------------------------------------
    @staticmethod
    def _owner_key(owner_name, phone=""):
        return (to_text(owner_name).strip().lower(), to_text(phone).strip())

    def remember_owner(self, owner_name, phone, owner_id):
        """Caches a freshly created owner so later rows resolve as duplicates."""
        self._owners[self._owner_key(owner_name, phone)] = owner_id

    def find_owner(self, owner_name, phone=""):
        """Finds an existing owner id by exact name (and phone when supplied)."""
        name = to_text(owner_name)
        phone = to_text(phone)
        key = self._owner_key(name, phone)
        if key in self._owners:
            return self._owners[key]

        owner_id = None
        if name:
            for row in client_repo.get_clients_by_name_exact(name):
                if phone and to_text(row.get("phone_number")) != phone:
                    continue
                owner_id = row.get("client_id")
                break
        if owner_id is None and phone:
            for row in client_repo.get_clients(text=phone, filter_field="Phone Number"):
                if to_text(row.get("phone_number")) == phone:
                    owner_id = row.get("client_id")
                    break

        self._owners[key] = owner_id
        return owner_id

    def resolve_owner(self, owner_name, phone=""):
        """Returns ``(owner_id, created)``, creating the owner when missing.

        An import usually brings a whole clinic history, so a missing owner is
        created rather than rejected; the caller reports it in the row message.
        A dry run returns a placeholder id so later sheets of the same run can
        still be validated against the owner this run would have created.
        """
        owner_id = self.find_owner(owner_name, phone)
        if owner_id is not None:
            return owner_id, False
        if not to_text(owner_name):
            return None, False

        if self.dry_run:
            owner_id = self.planned_id()
            self.remember_owner(owner_name, phone, owner_id)
            return owner_id, True

        owner_id = client_repo.add_client(
            to_text(owner_name), to_text(phone), audit_user_id=self.user_id
        )
        if owner_id is not None:
            self.created_owners += 1
            self.remember_owner(owner_name, phone, owner_id)
        return owner_id, True

    # -- pets --------------------------------------------------------------
    def find_pet(self, owner_id, pet_name):
        name = to_text(pet_name)
        key = (owner_id, name.strip().lower())
        if key in self._pets:
            return self._pets[key]

        pet_id = None
        if owner_id is not None and owner_id >= 0 and name:
            for row in pet_repo.get_pets_for_client(owner_id):
                if to_text(row.get("pet_name")).strip().lower() == name.strip().lower():
                    pet_id = row.get("pet_id")
                    break
        self._pets[key] = pet_id
        return pet_id

    def remember_pet(self, owner_id, pet_name, pet_id=None):
        """Caches a pet the run created (or would create) for later sheets."""
        if pet_id is None:
            pet_id = self.planned_id()
        name = to_text(pet_name)
        self._pets[(owner_id, name.strip().lower())] = pet_id
        return pet_id

    # -- inventory ---------------------------------------------------------
    def known_categories(self):
        if self._categories is None:
            self._categories = {to_text(name) for name in supply_repo.get_all_categories()}
        return self._categories

    def ensure_category(self, category, sub_category=""):
        """Registers the category / sub-category so the ledger stays tidy."""
        categories = self.known_categories()
        if category not in categories:
            supply_repo.add_category(category)
            categories.add(category)
        if sub_category:
            existing = {to_text(name) for name in supply_repo.get_subcategories_by_category(category)}
            if sub_category not in existing:
                supply_repo.add_subcategory(category, sub_category)

    # -- planned supplies --------------------------------------------------
    def remember_item(self, item_name):
        """Notes an item the run created (or would create) by its name."""
        self._planned_items.add(to_text(item_name).strip().lower())

    def knows_item(self, item_name):
        """True when the item exists in the DB or is created by this run."""
        name = to_text(item_name).strip().lower()
        if name in self._planned_items:
            return True
        return supply_repo.resolve_supply_id(item_name) is not None

    @staticmethod
    def _supply_key(item_name, category):
        return (to_text(item_name).strip().lower(),
                to_text(category).strip().lower())

    def remember_supply(self, item_name, category):
        """Notes an item+category the run created so it is not added twice."""
        self._planned_supplies.add(self._supply_key(item_name, category))

    def knows_supply(self, item_name, category):
        """True when this item+category already exists or is created by the run."""
        key = self._supply_key(item_name, category)
        if key in self._planned_supplies:
            return True
        return supply_repo.get_existing_supply(item_name, category) is not None

    # -- planned follow-ups -------------------------------------------------
    @staticmethod
    def _followup_key(visit_id, followup_date):
        return (visit_id, to_date(followup_date) or to_text(followup_date))

    def remember_followup(self, visit_id, followup_date):
        """Notes a follow-up the run created so it is not scheduled twice."""
        self._followups.add(self._followup_key(visit_id, followup_date))

    def knows_followup(self, visit_id, followup_date):
        """True when this visit+date follow-up exists or is created by the run."""
        key = self._followup_key(visit_id, followup_date)
        if key in self._followups:
            return True
        return followup_repo.find_followup_id(visit_id, followup_date) is not None

    # -- other visit-linked / child rows ------------------------------------
    def remember_row(self, bucket, *key_parts):
        """Notes a child row the run created so it is not added twice.

        ``bucket`` separates the namespaces (``clinical``, ``package_items``,
        ``appointments``); ``key_parts`` identify the row within it.
        """
        target = getattr(self, bucket)
        target.add(tuple(to_text(part).strip().lower() for part in key_parts))

    def knows_row(self, bucket, *key_parts):
        """True when a row was already created by this run (dry run included)."""
        target = getattr(self, bucket)
        return tuple(to_text(part).strip().lower() for part in key_parts) in target

    # -- suppliers ---------------------------------------------------------
    def known_suppliers(self):
        return self._suppliers

    @staticmethod
    def _supplier_key(supplier_name, phone=None, location=None):
        return (to_text(supplier_name).strip().lower(),
                (to_text(phone) or "").strip().lower(),
                (to_text(location) or "").strip().lower())

    def remember_supplier(self, supplier_name, supplier_id, phone=None,
                          location=None):
        self._suppliers[self._supplier_key(supplier_name, phone, location)] = supplier_id

    def find_supplier(self, supplier_name, phone=None, location=None):
        """Finds a supplier id by exact name+phone+location from the cache or
        the DB. With no phone/location it falls back to name-only matching."""
        key = self._supplier_key(supplier_name, phone, location)
        if key in self._suppliers:
            return self._suppliers[key]
        supplier_id = supplier_repo.find_supplier_id(supplier_name, phone, location)
        self._suppliers[key] = supplier_id
        return supplier_id

    # -- packages ----------------------------------------------------------
    def known_packages(self):
        return self._packages

    def find_package_id(self, package_name):
        """Finds a package id by exact name from the cache or the DB."""
        name = to_text(package_name).strip().lower()
        if name in self._packages:
            return self._packages[name]
        package_id = package_repo.find_package_id(package_name)
        self._packages[name] = package_id
        return package_id

    def remember_package(self, package_name, package_id):
        self._packages[to_text(package_name).strip().lower()] = package_id

    # -- receipts -----------------------------------------------------------
    def remember_receipt(self, receipt_code):
        """Notes a receipt code this run created (or would create)."""
        code = to_text(receipt_code).strip().upper()
        if code:
            self._receipts.add(code)

    def knows_receipt(self, receipt_code):
        """True when the code exists in the DB or is created by this run."""
        code = to_text(receipt_code).strip()
        if not code:
            return False
        if code.upper() in self._receipts:
            return True
        return sales_repo.get_receipt_id_by_code(code) is not None

    # -- visits -------------------------------------------------------------
    @staticmethod
    def _visit_key(owner_name, phone, pet_name, visit_date):
        return (
            to_text(owner_name).strip().lower(),
            to_text(phone).strip(),
            to_text(pet_name).strip().lower(),
            to_text(visit_date).strip(),
        )

    def remember_visit(self, owner_name, phone, pet_name, visit_date, visit_id):
        """Caches a visit this run created (or would create) for later sheets.

        A dry run has no committed visit row for the visit-linked sheets
        (follow-ups, vaccinations, medications, treatments, tests) to find, so
        the planned visit is registered under the same key :meth:`resolve_visit`
        looks up.
        """
        self._visits[self._visit_key(owner_name, phone, pet_name, visit_date)] = visit_id
        return visit_id

    def resolve_visit(self, owner_name, phone="", pet_name="", visit_date=""):
        key = self._visit_key(owner_name, phone, pet_name, visit_date)
        if key in self._visits:
            return self._visits[key]
        owner_id = self.find_owner(owner_name, phone)
        if owner_id is None:
            return None
        pet_id = self.find_pet(owner_id, pet_name) if pet_name else None
        if pet_id is None and pet_name:
            return None
        dt = to_datetime(visit_date)
        visit_id = visit_repo.find_visit_id(owner_id, pet_id, dt) if dt else None
        self._visits[key] = visit_id
        return visit_id


def _values_from_row(row, column_map):
    values = {}
    for name, index in column_map.items():
        if index is None or index >= len(row):
            continue
        text = to_text(row[index])
        if text:
            values[name] = text
    return values


def _import_owners(values, ctx, row_number):
    owner_name = to_text(values.get("owner_name"))
    if not owner_name:
        return RowResult(row_number, STATUS_FAILED, "Owner name is empty.")

    phone = to_text(values.get("phone_number"))
    if ctx.find_owner(owner_name, phone) is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Owner already exists.")

    notes = to_text(values.get("notes"))
    if ctx.dry_run:
        # Remembered so a later sheet of the same run resolves this owner
        # instead of reporting it as a duplicate to create.
        ctx.remember_owner(owner_name, phone, ctx.planned_id())
        return RowResult(row_number, STATUS_IMPORTED, "Will add owner.")

    owner_id = client_repo.add_client(owner_name, phone, audit_user_id=ctx.user_id)
    if owner_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add owner.")
    ctx.remember_owner(owner_name, phone, owner_id)
    if notes:
        client_repo.update_client(owner_id, owner_name, phone, notes=notes,
                                  audit_user_id=ctx.user_id)
    return RowResult(row_number, STATUS_IMPORTED, "Owner added.", owner_id)


def _import_pets(values, ctx, row_number):
    pet_name = to_text(values.get("pet_name"))
    owner_name = to_text(values.get("owner_name"))
    if not pet_name:
        return RowResult(row_number, STATUS_FAILED, "Pet name is empty.")
    if not owner_name:
        return RowResult(row_number, STATUS_FAILED, "Owner name is empty.")

    phone = to_text(values.get("phone_number"))
    client_id, created_owner = ctx.resolve_owner(owner_name, phone)
    if client_id is None:
        return RowResult(row_number, STATUS_FAILED, f"Owner '{owner_name}' not found.")

    existing = ctx.find_pet(client_id, pet_name)
    if existing is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Pet already exists.", existing)

    message = "Owner created, pet added." if created_owner else "Pet added."
    if ctx.dry_run:
        ctx.remember_pet(client_id, pet_name)
        return RowResult(row_number, STATUS_IMPORTED, f"Will add pet ({message})")

    pet_id = pet_repo.add_pet(
        pet_name,
        to_text(values.get("species")),
        to_text(values.get("breed")),
        to_text(values.get("gender")),
        to_int(values.get("age_months"), 0),
        to_number(values.get("weight"), 0.0),
        client_id,
        audit_user_id=ctx.user_id,
    )
    if pet_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add pet.")
    # Cache the new pet: the visit that cached "no such pet" for this owner
    # must not report a failure, and a repeated row must be skipped as a
    # duplicate instead of creating the pet twice.
    ctx.remember_pet(client_id, pet_name, pet_id)
    return RowResult(row_number, STATUS_IMPORTED, message, pet_id)


def _import_supplies(values, ctx, row_number):
    item_name = to_text(values.get("item_name"))
    category = to_text(values.get("category"))
    if not item_name:
        return RowResult(row_number, STATUS_FAILED, "Item name is empty.")
    if not category:
        return RowResult(row_number, STATUS_FAILED, "Category is empty.")

    sub_category = to_text(values.get("sub_category"))
    quantity = to_int(values.get("quantity"), 0)
    purchase_date = to_date(values.get("purchase_date")) or (
        datetime.date.today().isoformat() if quantity else None
    )
    expiry_date = to_date(values.get("expiry_date"))

    existed = ctx.knows_supply(item_name, category)

    if ctx.dry_run:
        ctx.remember_item(item_name)
        if existed:
            return RowResult(row_number, STATUS_SKIPPED, "Item already exists.")
        ctx.remember_supply(item_name, category)
        return RowResult(row_number, STATUS_IMPORTED, f"Will add item (stock {quantity}).")

    if existed:
        # A re-imported item must not stack its stock: adding it again would
        # inflate current_stock (and open a second stock batch) every time.
        ctx.remember_item(item_name)
        return RowResult(row_number, STATUS_SKIPPED, "Item already exists.")

    ctx.ensure_category(category, sub_category)
    supply_id, _expense = supply_repo.add_supply(
        item_name,
        category,
        sub_category,
        purchase_date=purchase_date,
        expiry_date=expiry_date,
        buy_price=to_number(values.get("buy_price"), 0.0),
        sell_price=to_number(values.get("sell_price"), 0.0),
        quantity=quantity,
        supplier=to_text(values.get("supplier")),
        audit_user_id=ctx.user_id,
    )
    if supply_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add item.")

    ctx.remember_item(item_name)
    ctx.remember_supply(item_name, category)
    return RowResult(row_number, STATUS_IMPORTED, "Item added.", supply_id)


def _import_visits(values, ctx, row_number):
    visit_date = to_datetime(values.get("visit_date"))
    if not visit_date:
        return RowResult(row_number, STATUS_FAILED, "Visit date is missing or invalid.")

    owner_name = to_text(values.get("owner_name"))
    pet_name = to_text(values.get("pet_name"))
    if not owner_name:
        return RowResult(row_number, STATUS_FAILED, "Owner name is empty.")
    if not pet_name:
        return RowResult(row_number, STATUS_FAILED, "Pet name is empty.")

    phone = to_text(values.get("phone_number"))
    client_id, created_owner = ctx.resolve_owner(owner_name, phone)
    if client_id is None:
        return RowResult(row_number, STATUS_FAILED, f"Owner '{owner_name}' not found.")

    pet_id = ctx.find_pet(client_id, pet_name)
    if pet_id is None:
        return RowResult(
            row_number,
            STATUS_FAILED,
            f"Pet '{pet_name}' not found for {owner_name}. Import pets first.",
        )

    items = parse_items(values.get("supplies"))
    missing_items = [
        item["item_name"] for item in items if not ctx.knows_item(item["item_name"])
    ]
    if missing_items:
        return RowResult(
            row_number,
            STATUS_FAILED,
            "Unknown supply item: {}".format(", ".join(missing_items)),
        )

    temperature = values.get("temperature")
    temperature = to_number(temperature, 0.0) or None if to_text(temperature) else None

    receipt_code = to_text(values.get("receipt_code"))

    # A visit is identified by owner + pet + day, the same key the visit-linked
    # sheets use, so a re-imported visit is skipped instead of duplicated.
    if ctx.resolve_visit(owner_name, phone, pet_name,
                         values.get("visit_date")) is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Visit already exists.")

    if ctx.dry_run:
        ctx.remember_receipt(receipt_code)
        ctx.remember_visit(owner_name, phone, pet_name,
                           values.get("visit_date"), ctx.planned_id())
        return RowResult(row_number, STATUS_IMPORTED, "Will add visit.")

    if receipt_code and sales_repo.get_receipt_id_by_code(receipt_code) is not None:
        ctx.remember_receipt(receipt_code)
        return RowResult(row_number, STATUS_SKIPPED, "Visit already imported.")

    receipt_code = receipt_code or sales_repo.next_visit_code(get_connection())
    if not receipt_code:
        return RowResult(row_number, STATUS_FAILED, "Could not allocate a receipt code.")

    result = visit_repo.add_visit(
        visit_date,
        to_text(values.get("diagnosis")),
        to_bool(values.get("consult")),
        to_text(values.get("notes")),
        pet_id=pet_id,
        items=items,
        client_id=client_id,
        reason_for_visit=to_text(values.get("reason_for_visit")),
        temperature=temperature,
        receipt_code=receipt_code,
        audit_user_id=ctx.user_id,
    )
    if isinstance(result, str):
        parts = result.split("|")
        if len(parts) == 3 and parts[0] == "STOCK_ERROR":
            return RowResult(
                row_number,
                STATUS_FAILED,
                f"Not enough stock for {parts[1]} (available {parts[2]}).",
            )
        return RowResult(row_number, STATUS_FAILED, result)
    if not result:
        return RowResult(row_number, STATUS_FAILED, "Failed to add visit.")

    ctx.remember_receipt(receipt_code)
    ctx.remember_visit(owner_name, phone, pet_name,
                       values.get("visit_date"), result)
    message = "Owner created, visit added." if created_owner else "Visit added."
    return RowResult(row_number, STATUS_IMPORTED, message, result)


def _resolve_visit_for_row(values, ctx, row_number):
    """Resolves the parent visit of a visit-linked row.

    Returns ``(visit_id, None)`` on success or ``(None, RowResult)`` with a
    failure that explains which record must be imported first. The owner/pet
    must already exist (or have been created by an earlier sheet of the same
    run); a missing visit fails the row instead of creating one silently.
    """
    owner_name = to_text(values.get("owner_name"))
    pet_name = to_text(values.get("pet_name"))
    if not owner_name:
        return None, RowResult(row_number, STATUS_FAILED, "Owner name is empty.")
    if not pet_name:
        return None, RowResult(row_number, STATUS_FAILED, "Pet name is empty.")

    visit_id = ctx.resolve_visit(
        owner_name, to_text(values.get("phone_number")), pet_name,
        values.get("visit_date"),
    )
    if visit_id is None:
        return None, RowResult(
            row_number,
            STATUS_FAILED,
            f"Visit not found for {owner_name} / {pet_name} on "
            f"{values.get('visit_date') or '?'}. Import visits first.",
        )
    return visit_id, None


def _import_suppliers(values, ctx, row_number):
    name = to_text(values.get("supplier_name"))
    if not name:
        return RowResult(row_number, STATUS_FAILED, "Supplier name is empty.")

    phone = to_text(values.get("phone")) or None
    location = to_text(values.get("location")) or None
    notes = to_text(values.get("notes")) or None

    if ctx.find_supplier(name, phone, location) is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Supplier already exists.")

    if ctx.dry_run:
        ctx.remember_supplier(name, ctx.planned_id(), phone, location)
        return RowResult(row_number, STATUS_IMPORTED, "Will add supplier.")

    supplier_id = supplier_repo.add_supplier(name, phone, location, notes)
    if supplier_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add supplier.")
    ctx.remember_supplier(name, supplier_id, phone, location)
    return RowResult(row_number, STATUS_IMPORTED, "Supplier added.", supplier_id)


def _import_packages(values, ctx, row_number):
    package_name = to_text(values.get("package_name"))
    if not package_name:
        return RowResult(row_number, STATUS_FAILED, "Package name is empty.")
    if ctx.find_package_id(package_name) is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Package already exists.")

    if ctx.dry_run:
        ctx.remember_package(package_name, ctx.planned_id())
        return RowResult(row_number, STATUS_IMPORTED, "Will add package.")

    package_id = package_repo.add_package(
        package_name,
        to_text(values.get("description")),
        to_number(values.get("total_price"), 0.0),
    )
    if package_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add package.")
    ctx.remember_package(package_name, package_id)
    return RowResult(row_number, STATUS_IMPORTED, "Package added.", package_id)


def _package_has_item(package_id, item_type, name):
    """True when ``package_id`` already holds this service/supply (by name)."""
    key = to_text(name).strip().lower()
    for row in package_repo.get_package_items(package_id):
        if to_text(row.get("item_type")) != item_type:
            continue
        db_name = (row.get("service_name") if item_type == "service"
                   else row.get("item_name"))
        if to_text(db_name).strip().lower() == key:
            return True
    return False


def _import_package_items(values, ctx, row_number):
    package_name = to_text(values.get("package_name"))
    item_name = to_text(values.get("item_name"))
    if not package_name:
        return RowResult(row_number, STATUS_FAILED, "Package name is empty.")
    if not item_name:
        return RowResult(row_number, STATUS_FAILED, "Item name is empty.")

    package_id = ctx.find_package_id(package_name)
    if package_id is None:
        return RowResult(
            row_number,
            STATUS_FAILED,
            f"Unknown package '{package_name}'. Import packages first.",
        )

    item_type = to_text(values.get("item_type")).strip().lower() or "supply"
    quantity = to_number(values.get("quantity"), 1.0)
    if item_type in ("service", "services", "consult", "consultation"):
        if _package_has_item(package_id, "service", item_name) or ctx.knows_row(
                "_package_items", package_id, "service", item_name):
            return RowResult(row_number, STATUS_SKIPPED,
                             "Service item already in package.")
        if ctx.dry_run:
            ctx.remember_row("_package_items", package_id, "service", item_name)
            return RowResult(row_number, STATUS_IMPORTED,
                             "Will add service item to package.", package_id)
        service_id = supply_repo.get_or_create_service(item_name)
        if service_id is None:
            return RowResult(row_number, STATUS_FAILED, "Failed to resolve service.")
        if package_repo.add_package_item(package_id, service_id=service_id,
                                         quantity=quantity, item_type="service"):
            ctx.remember_row("_package_items", package_id, "service", item_name)
            return RowResult(row_number, STATUS_IMPORTED,
                             "Service item added to package.", package_id)
        return RowResult(row_number, STATUS_FAILED, "Failed to add package item.")

    supply_id = supply_repo.resolve_supply_id(item_name)
    if supply_id is None and not ctx.knows_item(item_name):
        return RowResult(
            row_number,
            STATUS_FAILED,
            f"Unknown supply item '{item_name}'. Import supplies first.",
        )
    if _package_has_item(package_id, "supply", item_name) or ctx.knows_row(
            "_package_items", package_id, "supply", item_name):
        return RowResult(row_number, STATUS_SKIPPED,
                         "Supply item already in package.")
    if ctx.dry_run:
        ctx.remember_row("_package_items", package_id, "supply", item_name)
        return RowResult(row_number, STATUS_IMPORTED,
                         "Will add supply item to package.", package_id)
    if package_repo.add_package_item(package_id, supply_id=supply_id,
                                     quantity=quantity, item_type="supply"):
        ctx.remember_row("_package_items", package_id, "supply", item_name)
        return RowResult(row_number, STATUS_IMPORTED,
                         "Supply item added to package.", package_id)
    return RowResult(row_number, STATUS_FAILED, "Failed to add package item.")


def _import_appointments(values, ctx, row_number):
    appointment_date = to_datetime(values.get("appointment_date"))
    if not appointment_date:
        return RowResult(row_number, STATUS_FAILED,
                         "Appointment date is missing or invalid.")
    owner_name = to_text(values.get("owner_name"))
    pet_name = to_text(values.get("pet_name"))
    if not owner_name:
        return RowResult(row_number, STATUS_FAILED, "Owner name is empty.")
    if not pet_name:
        return RowResult(row_number, STATUS_FAILED, "Pet name is empty.")

    phone = to_text(values.get("phone_number"))
    client_id = ctx.find_owner(owner_name, phone)
    if client_id is None:
        return RowResult(
            row_number, STATUS_FAILED,
            f"Owner '{owner_name}' not found. Import owners first.",
        )
    pet_id = ctx.find_pet(client_id, pet_name)
    if pet_id is None:
        return RowResult(
            row_number, STATUS_FAILED,
            f"Pet '{pet_name}' not found for {owner_name}. Import pets first.",
        )

    status = to_text(values.get("status")) or "Pending"
    if status not in ("Pending", "Completed", "Canceled"):
        return RowResult(row_number, STATUS_FAILED,
                         f"Invalid appointment status '{status}'.")

    # Identified by pet + minute, so a re-imported appointment is skipped.
    if ctx.knows_row("_appointments", pet_id, appointment_date) or \
            appointment_repo.find_appointment_id(
                client_id, pet_id, appointment_date) is not None:
        return RowResult(row_number, STATUS_SKIPPED, "Appointment already exists.")

    if ctx.dry_run:
        ctx.remember_row("_appointments", pet_id, appointment_date)
        return RowResult(row_number, STATUS_IMPORTED, "Will add appointment.")

    ok = appointment_repo.add_appointment(
        appointment_date,
        to_text(values.get("service")),
        status,
        to_text(values.get("notes")),
        client_id,
        pet_id,
    )
    if not ok:
        return RowResult(row_number, STATUS_FAILED, "Failed to add appointment.")
    ctx.remember_row("_appointments", pet_id, appointment_date)
    return RowResult(row_number, STATUS_IMPORTED, "Appointment added.")


def _import_followups(values, ctx, row_number):
    follow_up_date = to_datetime(values.get("follow_up_date"))
    if not follow_up_date:
        return RowResult(row_number, STATUS_FAILED,
                         "Follow-up date is missing or invalid.")

    visit_id, error = _resolve_visit_for_row(values, ctx, row_number)
    if error is not None:
        return error

    status = to_text(values.get("status"))
    state_id = followup_repo.resolve_status_state_id(status) if status else None
    if status and state_id is None:
        return RowResult(row_number, STATUS_FAILED,
                         f"Invalid follow-up status '{status}'.")

    # A follow-up is identified by its visit + day, so a re-imported follow-up
    # is skipped instead of scheduled again.
    if ctx.knows_followup(visit_id, values.get("follow_up_date")):
        return RowResult(row_number, STATUS_SKIPPED, "Follow-up already exists.")

    if ctx.dry_run:
        ctx.remember_followup(visit_id, values.get("follow_up_date"))
        return RowResult(row_number, STATUS_IMPORTED, "Will add follow-up.")

    followup_id = followup_repo.add_followup(
        visit_id,
        follow_up_date,
        state_id=state_id,
        notes=to_text(values.get("notes")),
    )
    if followup_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to add follow-up.")
    ctx.remember_followup(visit_id, values.get("follow_up_date"))
    return RowResult(row_number, STATUS_IMPORTED, "Follow-up added.", followup_id)


def _has_named(rows, field, name):
    """True when any row's ``field`` matches ``name`` case-insensitively."""
    key = to_text(name).strip().lower()
    return any(to_text(row.get(field)).strip().lower() == key for row in rows)


def _import_vaccinations(values, ctx, row_number):
    vaccine_name = to_text(values.get("vaccine_name"))
    if not vaccine_name:
        return RowResult(row_number, STATUS_FAILED, "Vaccine name is empty.")

    visit_id, error = _resolve_visit_for_row(values, ctx, row_number)
    if error is not None:
        return error

    if ctx.knows_row("_clinical", "vaccinations", visit_id, vaccine_name) or \
            _has_named(vaccination_repo.get_vaccinations_for_visit(visit_id),
                       "vaccine_name", vaccine_name):
        return RowResult(row_number, STATUS_SKIPPED, "Vaccination already recorded.")

    if ctx.dry_run:
        ctx.remember_row("_clinical", "vaccinations", visit_id, vaccine_name)
        return RowResult(row_number, STATUS_IMPORTED, "Will add vaccination.")

    vaccine_id = vaccination_repo.get_or_create_vaccine(vaccine_name)
    if vaccine_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to resolve vaccine.")
    if vaccination_repo.record_vaccination(visit_id, vaccine_id):
        ctx.remember_row("_clinical", "vaccinations", visit_id, vaccine_name)
        return RowResult(row_number, STATUS_IMPORTED, "Vaccination added.")
    return RowResult(row_number, STATUS_FAILED, "Failed to add vaccination.")


def _import_medications(values, ctx, row_number):
    item_name = to_text(values.get("item_name"))
    if not item_name:
        return RowResult(row_number, STATUS_FAILED, "Medication name is empty.")

    visit_id, error = _resolve_visit_for_row(values, ctx, row_number)
    if error is not None:
        return error

    if not ctx.knows_item(item_name):
        return RowResult(
            row_number, STATUS_FAILED,
            f"Unknown supply item '{item_name}'. Import supplies first.",
        )

    if ctx.knows_row("_clinical", "medications", visit_id, item_name) or \
            _has_named(medication_repo.get_medications_for_visit(visit_id),
                       "item_name", item_name):
        return RowResult(row_number, STATUS_SKIPPED, "Medication already recorded.")

    if ctx.dry_run:
        ctx.remember_row("_clinical", "medications", visit_id, item_name)
        return RowResult(row_number, STATUS_IMPORTED, "Will add medication.")

    supply_id = supply_repo.resolve_supply_id(item_name)
    if supply_id is None:
        return RowResult(row_number, STATUS_FAILED,
                         f"Unknown supply item '{item_name}'.")
    if medication_repo.prescribe_medication(
            visit_id, supply_id,
            to_text(values.get("dosage")),
            to_text(values.get("instructions"))):
        ctx.remember_row("_clinical", "medications", visit_id, item_name)
        return RowResult(row_number, STATUS_IMPORTED, "Medication added.")
    return RowResult(row_number, STATUS_FAILED, "Failed to add medication.")


def _import_treatments(values, ctx, row_number):
    treatment_name = to_text(values.get("treatment_name"))
    if not treatment_name:
        return RowResult(row_number, STATUS_FAILED, "Treatment name is empty.")

    visit_id, error = _resolve_visit_for_row(values, ctx, row_number)
    if error is not None:
        return error

    if ctx.knows_row("_clinical", "treatments", visit_id, treatment_name) or \
            _has_named(treatment_repo.get_treatments_for_visit(visit_id),
                       "treatment_name", treatment_name):
        return RowResult(row_number, STATUS_SKIPPED, "Treatment already recorded.")

    if ctx.dry_run:
        ctx.remember_row("_clinical", "treatments", visit_id, treatment_name)
        return RowResult(row_number, STATUS_IMPORTED, "Will add treatment.")

    treatment_id = treatment_repo.get_or_create_treatment(treatment_name)
    if treatment_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to resolve treatment.")
    if treatment_repo.record_treatment(visit_id, treatment_id):
        ctx.remember_row("_clinical", "treatments", visit_id, treatment_name)
        return RowResult(row_number, STATUS_IMPORTED, "Treatment added.")
    return RowResult(row_number, STATUS_FAILED, "Failed to add treatment.")


def _import_tests(values, ctx, row_number):
    test_name = to_text(values.get("test_name"))
    if not test_name:
        return RowResult(row_number, STATUS_FAILED, "Test name is empty.")

    visit_id, error = _resolve_visit_for_row(values, ctx, row_number)
    if error is not None:
        return error

    result = to_text(values.get("result"))
    if ctx.knows_row("_clinical", "tests", visit_id, test_name) or \
            _has_named(test_repo.get_tests_for_visit(visit_id),
                       "test_name", test_name):
        return RowResult(row_number, STATUS_SKIPPED, "Test already recorded.")

    if ctx.dry_run:
        ctx.remember_row("_clinical", "tests", visit_id, test_name)
        return RowResult(row_number, STATUS_IMPORTED, "Will add test.")

    test_id = test_repo.get_or_create_test(test_name)
    if test_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to resolve test.")
    state_id = lookup_repo.get_state_id("test_result", result) if result else None
    if result and state_id is None:
        return RowResult(row_number, STATUS_FAILED,
                         f"Invalid test result '{result}'.")
    if test_repo.record_test(visit_id, test_id, state_id=state_id):
        ctx.remember_row("_clinical", "tests", visit_id, test_name)
        return RowResult(row_number, STATUS_IMPORTED, "Test added.")
    return RowResult(row_number, STATUS_FAILED, "Failed to add test.")


def _import_expenses(values, ctx, row_number):
    expense_date = to_date(values.get("expense_date"))
    if not expense_date:
        return RowResult(row_number, STATUS_FAILED,
                         "Expense date is missing or invalid.")
    item_name = to_text(values.get("item_name"))
    if not item_name:
        return RowResult(row_number, STATUS_FAILED, "Item name is empty.")
    amount = to_number(values.get("amount"))
    if amount is None or amount <= 0:
        return RowResult(row_number, STATUS_FAILED,
                         "Amount must be a positive number.")

    receipt_code = to_text(values.get("receipt_code"))

    # An expense is identified by its receipt code; check even in dry run so
    # Validate reports the same result the real import would.
    if receipt_code and sales_repo.get_receipt_id_by_code(receipt_code) is not None:
        ctx.remember_receipt(receipt_code)
        return RowResult(row_number, STATUS_SKIPPED, "Expense already exists.")

    if ctx.dry_run:
        ctx.remember_receipt(receipt_code)
        return RowResult(row_number, STATUS_IMPORTED, "Will add expense.")

    ok = sales_repo.add_general_expense(
        expense_date,
        to_text(values.get("category")),
        item_name,
        amount,
        notes=to_text(values.get("notes")),
        audit_user_id=ctx.user_id,
        receipt_code=receipt_code or None,
    )
    if not ok:
        return RowResult(row_number, STATUS_FAILED, "Failed to add expense.")
    ctx.remember_receipt(receipt_code)
    return RowResult(row_number, STATUS_IMPORTED, "Expense added.")


def _payment_exists(receipt_id, amount, method, payment_date):
    """True when an identical payment (amount + method + day) already exists.

    Checked against the DB only, so a file that legitimately holds two equal
    same-day installments still imports both on a first run, while re-importing
    a file whose payments are already recorded changes nothing.
    """
    day = to_text(payment_date)[:10]
    for row in payment_repo.get_payments_for_receipt(receipt_id):
        if (abs(float(row.get("amount") or 0.0) - amount) < 0.005
                and to_text(row.get("payment_method")) == method
                and to_text(row.get("payment_date"))[:10] == day):
            return True
    return False


def _import_payments(values, ctx, row_number):
    receipt_code = to_text(values.get("receipt_code"))
    amount = to_number(values.get("amount"))
    if not receipt_code:
        return RowResult(row_number, STATUS_FAILED, "Receipt code is empty.")
    if amount is None or amount == 0:
        return RowResult(row_number, STATUS_FAILED,
                         "Amount must be a non-zero number.")

    method = to_text(values.get("payment_method")) or "Cash"
    notes = to_text(values.get("notes"))
    payment_date = to_date(values.get("payment_date")) or datetime.date.today().isoformat()

    receipt_id = sales_repo.get_receipt_id_by_code(receipt_code)

    if ctx.dry_run:
        # A receipt created earlier in this run only exists in the plan; a
        # receipt already in the DB can be checked for the payment itself.
        if receipt_id is None and not ctx.knows_receipt(receipt_code):
            return RowResult(
                row_number, STATUS_FAILED,
                f"Receipt '{receipt_code}' not found. Import its receipt first.",
            )
        if receipt_id is not None and _payment_exists(
                receipt_id, amount, method, payment_date):
            return RowResult(row_number, STATUS_SKIPPED, "Payment already recorded.")
        return RowResult(row_number, STATUS_IMPORTED, "Will record payment.")

    if receipt_id is None:
        return RowResult(
            row_number, STATUS_FAILED,
            f"Receipt '{receipt_code}' not found. Import its receipt first.",
        )

    if _payment_exists(receipt_id, amount, method, payment_date):
        return RowResult(row_number, STATUS_SKIPPED, "Payment already recorded.")
    if amount < 0:
        payment_id = payment_repo.add_refund(
            receipt_id, -amount, payment_method=method, notes=notes,
            audit_user_id=ctx.user_id, payment_date=payment_date)
        message = "Refund recorded."
    else:
        payment_id = payment_repo.add_payment(
            receipt_id, amount, payment_method=method, notes=notes,
            audit_user_id=ctx.user_id, payment_date=payment_date)
        message = "Payment recorded."
    if payment_id is None:
        return RowResult(row_number, STATUS_FAILED, "Failed to record payment.")
    return RowResult(row_number, STATUS_IMPORTED, message, payment_id)


def _import_retail_sales(values, ctx, row_number):
    receipt_code = to_text(values.get("receipt_code"))
    receipt_date = to_datetime(values.get("receipt_date"))
    if not receipt_code:
        return RowResult(row_number, STATUS_FAILED, "Receipt code is empty.")
    if not receipt_date:
        return RowResult(row_number, STATUS_FAILED,
                         "Receipt date is missing or invalid.")

    items = parse_items(values.get("items"))
    if not items:
        return RowResult(row_number, STATUS_FAILED, "No sale items given.")
    missing_items = [
        item["item_name"] for item in items if not ctx.knows_item(item["item_name"])
    ]
    if missing_items:
        return RowResult(
            row_number,
            STATUS_FAILED,
            "Unknown supply item: {}. Import supplies first.".format(
                ", ".join(missing_items)),
        )

    if sales_repo.get_receipt_id_by_code(receipt_code) is not None:
        ctx.remember_receipt(receipt_code)
        return RowResult(row_number, STATUS_SKIPPED, "Retail sale already exists.")

    if ctx.dry_run:
        ctx.remember_receipt(receipt_code)
        return RowResult(row_number, STATUS_IMPORTED, "Will add retail sale.")

    owner_name = to_text(values.get("owner_name"))
    owner_id, created_owner = ctx.resolve_owner(
        owner_name, to_text(values.get("phone_number")))
    if owner_id is None:
        return RowResult(row_number, STATUS_FAILED, "Owner name is empty.")

    priced_items = []
    for item in items:
        price = supply_repo.get_sell_price(item["item_name"])
        if price is None:
            return RowResult(
                row_number, STATUS_FAILED,
                f"Unknown supply item: {item['item_name']}. Import supplies first.",
            )
        priced_items.append({
            "item_name": item["item_name"],
            "quantity": item["quantity"],
            "price": price,
        })

    result = sales_repo.create_sale_receipt_for_quick_purchase(
        owner_id,
        receipt_date,
        priced_items,
        user_id=ctx.user_id,
        receipt_code=receipt_code,
        paid=False,
        discount=to_number(values.get("discount"), 0.0),
    )
    if isinstance(result, str):
        parts = result.split("|")
        if len(parts) == 3 and parts[0] == "STOCK_ERROR":
            return RowResult(
                row_number,
                STATUS_FAILED,
                f"Not enough stock for {parts[1]} (available {parts[2]}).",
            )
        return RowResult(row_number, STATUS_FAILED, result)
    if not result:
        return RowResult(row_number, STATUS_FAILED, "Failed to add retail sale.")

    ctx.remember_receipt(receipt_code)
    message = "Owner created, retail sale added." if created_owner else "Retail sale added."
    return RowResult(row_number, STATUS_IMPORTED, message, result)


_HANDLERS = {
    "owners": _import_owners,
    "pets": _import_pets,
    "suppliers": _import_suppliers,
    "supplies": _import_supplies,
    "packages": _import_packages,
    "package_items": _import_package_items,
    "appointments": _import_appointments,
    "visits": _import_visits,
    "followups": _import_followups,
    "vaccinations": _import_vaccinations,
    "medications": _import_medications,
    "treatments": _import_treatments,
    "tests": _import_tests,
    "expenses": _import_expenses,
    "retail_sales": _import_retail_sales,
    "payments": _import_payments,
}


def import_table(entity_key, headers, rows, row_numbers=None, user_id=None,
                 dry_run=False, context=None):
    """Validates and (unless ``dry_run``) writes ``rows`` as ``entity_key``.

    Args:
        entity_key: one of ``IMPORT_KEYS``.
        headers: the file's header row.
        rows: raw text rows (already stringified).
        row_numbers: 1-based file row numbers for reporting; defaults to
            sequential values.
        user_id: attribution for the audit log (``None`` writes no audit row).
        dry_run: validate + resolve only, without writing anything.
        context: an existing :class:`_Context` to share (see
            :func:`import_workbook`); a fresh one is created when omitted.

    Returns:
        ImportSummary: per-row outcomes plus imported/skipped/failed counts.
    """
    spec = get_spec(entity_key)
    handler = _HANDLERS[entity_key]
    summary = ImportSummary(entity=entity_key)

    numbers = list(row_numbers) if row_numbers else list(range(1, len(rows) + 1))
    column_map = match_columns(headers, spec)

    absent = [spec.field_label(name) for name in spec.required
              if column_map.get(name) is None]
    if absent:
        for number in numbers:
            summary.add(RowResult(
                number, STATUS_FAILED,
                "Missing required column: {}".format(", ".join(absent)),
            ))
        return summary

    ctx = context or _Context(user_id=user_id, dry_run=dry_run)
    for index, row in enumerate(rows):
        number = numbers[index] if index < len(numbers) else index + 1
        values = _values_from_row(row, column_map)
        try:
            result = handler(values, ctx, number)
        except Exception as exc:  # keep one bad row from killing the run
            logger.exception("Import row %s failed for %s", number, entity_key)
            result = RowResult(number, STATUS_FAILED, str(exc))
        summary.add(result)
    return summary


def import_file(path, entity_key, sheet=None, user_id=None, dry_run=False, limit=None):
    """Reads ``path`` then imports it as ``entity_key``."""
    table = read_table(path, sheet)
    rows = table.rows
    numbers = table.row_numbers
    if limit:
        rows, numbers = rows[:limit], numbers[:limit]
    return import_table(entity_key, table.headers, rows, numbers,
                        user_id=user_id, dry_run=dry_run)


# ------------------------------------------------------- Multi-sheet import --
@dataclass
class SheetPlan:
    """One importable sheet of a file, paired with the entity it holds."""

    sheet_name: str
    entity: str
    table: ImportTable

    @property
    def row_count(self):
        return len(self.table.rows)


@dataclass
class WorkbookPlan:
    """Every sheet that can be imported, plus the ones that were skipped."""

    path: object = None
    plans: list = field(default_factory=list)
    ignored: list = field(default_factory=list)

    @property
    def entities(self):
        """The distinct data types found, in import order."""
        return tuple(dict.fromkeys(plan.entity for plan in self.plans))

    @property
    def row_count(self):
        return sum(plan.row_count for plan in self.plans)


def plan_workbook(path):
    """Reads ``path`` and pairs every importable sheet with its data type.

    Documentation sheets (see :func:`is_instructions_sheet`) and sheets whose
    columns match no entity land in :attr:`WorkbookPlan.ignored` instead of
    failing, so a workbook written by ``exporter.write_workbook`` can be
    imported as-is - including its Instructions sheet.

    Sheets are returned in :data:`IMPORT_KEYS` order (owners, pets, supplies,
    visits) so a record created by one sheet resolves for the sheets that
    depend on it, whatever order the workbook happens to be in.

    Raises:
        FileNotFoundError: when ``path`` does not exist.
        ValueError: for an unsupported file extension.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    sheet_names = list_sheets(path)  # [] for a text file
    if not sheet_names:
        sheet_names = [None]

    plans, ignored = [], []
    for name in sheet_names:
        label = name or path.name
        if name is not None and is_instructions_sheet(name):
            ignored.append(label)
            continue
        table = read_table(path, name)
        entity = detect_entity(table.headers) if table.headers else None
        if entity is None and table.headers:
            # Our own template/export sheets are identified by name: the
            # suppliers sheet holds a single column, which can never reach the
            # two-column detection threshold.
            entity = _entity_from_sheet_name(name)
        if entity is None:
            ignored.append(label)
            continue
        plans.append(SheetPlan(label, entity, table))

    plans.sort(key=lambda plan: IMPORT_KEYS.index(plan.entity))
    return WorkbookPlan(path=path, plans=plans, ignored=ignored)


@dataclass
class WorkbookImportSummary:
    """Aggregated outcome of one :func:`import_workbook` run.

    Exposes the same ``total`` / ``imported`` / ``skipped`` / ``failed``
    counters as :class:`ImportSummary`, aggregated over every sheet.
    """

    sheets: list = field(default_factory=list)  # (sheet_name, entity, summary)

    def add(self, sheet_name, entity, summary):
        self.sheets.append((sheet_name, entity, summary))
        return summary

    @property
    def summaries(self):
        return [summary for _name, _entity, summary in self.sheets]

    @property
    def total(self):
        return sum(summary.total for summary in self.summaries)

    @property
    def imported(self):
        return sum(summary.imported for summary in self.summaries)

    @property
    def skipped(self):
        return sum(summary.skipped for summary in self.summaries)

    @property
    def failed(self):
        return sum(summary.failed for summary in self.summaries)

    @property
    def entities(self):
        """Data types that received at least one record, in import order."""
        return tuple(dict.fromkeys(
            entity for _name, entity, summary in self.sheets if summary.imported
        ))

    def sheet_summary(self, entity):
        """The :class:`ImportSummary` of the first sheet holding ``entity``."""
        for _name, sheet_entity, summary in self.sheets:
            if sheet_entity == entity:
                return summary
        return None

    def problems(self):
        """``(sheet_name, RowResult)`` pairs the user should look at."""
        return [(name, result)
                for name, _entity, summary in self.sheets
                for result in summary.problems()]


def result_details(summary, limit=200):
    """Readable ``Sheet - Row N: message`` lines for either summary type."""
    if isinstance(summary, WorkbookImportSummary):
        pairs = summary.problems()
    else:
        pairs = [("", result) for result in summary.problems()]
    return "\n".join(
        "{prefix}Row {row}: {msg}".format(
            prefix="{} - ".format(sheet) if sheet else "",
            row=result.row_number, msg=result.message,
        )
        for sheet, result in pairs[:limit]
    )


def import_workbook(path, user_id=None, dry_run=False, plan=None):
    """Imports every importable sheet of ``path`` in a single pass.

    The sheets share one resolution cache, so an owner created on the owners
    sheet is found - never duplicated - by the pets and visits sheets, and a
    dry run can validate the whole file at once.

    Args:
        path: an ``.xlsx`` / ``.xlsm`` workbook (a CSV/TSV is treated as a
            single sheet).
        user_id: attribution for the audit log.
        dry_run: validate + resolve only, without writing anything.
        plan: a :func:`plan_workbook` result to reuse instead of re-reading.

    Returns:
        WorkbookImportSummary: per-sheet outcomes plus aggregate counts.
    """
    plan = plan or plan_workbook(path)
    ctx = _Context(user_id=user_id, dry_run=dry_run)
    summary = WorkbookImportSummary()

    for sheet_plan in plan.plans:
        table = sheet_plan.table
        summary.add(
            sheet_plan.sheet_name,
            sheet_plan.entity,
            import_table(sheet_plan.entity, table.headers, table.rows,
                         table.row_numbers, user_id=user_id, dry_run=dry_run,
                         context=ctx),
        )

    logger.info(
        "Import workbook %s (%s): %s sheet(s) %s, imported=%s skipped=%s failed=%s",
        path, "validate" if dry_run else "commit", len(summary.sheets),
        summary.entities, summary.imported, summary.skipped, summary.failed,
    )
    return summary


# -------------------------------------------------------------- Templates ---
def template_rows(entity_key):
    """Returns ``(headers, sample_row)`` for an entity's starter file."""
    spec = get_spec(entity_key)
    return [spec.field_label(name) for name in spec.fields], list(spec.sample)


def write_template(path, entity_key):
    """Writes a starter file for ``entity_key`` (``.xlsx`` or delimited text).

    The file carries **headers only** - there is deliberately no sample row, so
    a freshly saved template can never push a demo record into the database.
    Guidance lives where it cannot be imported: hover a header cell for its
    required/optional state plus an example value (Excel comments), and read the
    second sheet of the workbook for the full step-by-step instructions.

    Returns:
        Path: the written file.
    """
    get_spec(entity_key)  # validates the entity before touching the filesystem
    return write_table_file(path, entity_key)


#: File extension used for each template format in :func:`write_all_templates`.
TEMPLATE_EXTENSIONS = {"xlsx": ".xlsx", "csv": ".csv"}


def normalize_template_format(file_format=None):
    """Maps a user/template format name onto a supported template extension.

    ``None``/``""`` means the default format (``.xlsx``).
    """
    key = (file_format or "xlsx").strip().lower().lstrip(".")
    if key in TEMPLATE_EXTENSIONS:
        return key
    if key in ("excel", "xls", "xltx"):
        return "xlsx"
    if key in ("csv", "text", "txt", "tsv"):
        return "csv"
    raise ValueError(f"Unsupported template format: {file_format}")


def write_all_templates(directory, file_format=None):
    """Writes one starter file per importable entity into ``directory``.

    Used by the **CSV** button: a delimited file holds a single data type, so
    each entity needs its own file. The Excel button saves one workbook instead
    (see :func:`write_templates_workbook`).

    Args:
        directory: folder to write into (created when missing).
        file_format: ``"xlsx"`` (default) or ``"csv"``.

    Returns:
        list[Path]: the written files, in :data:`IMPORT_KEYS` order.
    """
    extension = TEMPLATE_EXTENSIONS[normalize_template_format(file_format)]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return [write_template(directory / f"{entity_key}_template{extension}",
                           entity_key)
            for entity_key in IMPORT_KEYS]


#: Sheet names used by the generated Excel templates.
TEMPLATE_SHEET_NAME = "Template"
INSTRUCTIONS_SHEET_NAME = "Instructions"

#: Default file name of the headers-only workbook holding every data sheet.
TEMPLATE_WORKBOOK_NAME = "pet_templates.xlsx"

#: Sheet name per entity when ONE workbook holds every data type. The names are
#: never parsed - a sheet is matched to its entity by its columns (see
#: :func:`detect_entity`) - they only have to stay readable and unique.
SHEET_NAMES = {
    "owners": "Owners",
    "pets": "Pets",
    "suppliers": "Suppliers",
    "supplies": "Supplies",
    "packages": "Packages",
    "package_items": "Package Items",
    "appointments": "Appointments",
    "visits": "Visits",
    "followups": "Follow-ups",
    "vaccinations": "Vaccinations",
    "medications": "Medications",
    "treatments": "Treatments",
    "tests": "Tests",
    "expenses": "Expenses",
    "retail_sales": "Retail Sales",
    "payments": "Payments",
}


def entity_sheet_name(entity_key):
    """Returns the sheet name used for ``entity_key`` in a multi-sheet workbook."""
    get_spec(entity_key)  # validates the entity
    return SHEET_NAMES.get(entity_key, entity_key.replace("_", " ").title())

#: Documentation-only sheet names (never imported; see :func:`is_instructions_sheet`).
INSTRUCTIONS_SHEET_ALIASES = (
    "instructions", "instruction", "how to use", "howto use", "readme",
    "read me", "help", "guide", "notes", "about",
)

#: Steps written to the instructions sheet of every Excel template.
TEMPLATE_STEPS = (
    "Open the {sheet} sheet and type one record per row, starting in row 2.",
    "Keep the header row exactly as it is - your column names are matched automatically.",
    "Hover a header cell to see whether it is required and what a value looks like.",
    "Leave optional columns blank when you do not have the value.",
    "Existing records are skipped, never overwritten.",
    "Save the file, then import it from Settings > Database Backup > Import Data.",
)

#: Steps written to the instructions sheet of a multi-sheet export/import book.
WORKBOOK_STEPS = (
    "Every data type has its own sheet - type one record per row, starting in row 2.",
    "Sheets are matched automatically, so their names and order do not matter.",
    "Keep each header row exactly as it is - your column names are matched automatically.",
    "Hover a header cell to see whether it is required and what a value looks like.",
    "Leave optional columns blank when you do not have the value.",
    "Sheets are imported owners first, then pets, supplies and visits, so records "
    "created by one sheet are found by the next.",
    "Existing records are skipped, never overwritten.",
    "Save the file, then import it from Settings > Database Backup > Import Data "
    "with every sheet at once.",
)

#: Per-field guidance shown in the instructions sheet / header comments.
_FIELD_HINTS = {
    "owner_name": "Matched against existing owners by name plus phone number.",
    "phone_number": "Any format is fine, e.g. 01001234567.",
    "pet_name": "Matched against the pets of the owner on the same row.",
    "species": "Free text, e.g. Dog, Cat, Rabbit.",
    "gender": "Female, Male or Other.",
    "age_months": "Whole number of months, e.g. 24 for two years old.",
    "weight": "Number only, in kilograms.",
    "category": "Your supply category, e.g. Medicine.",
    "sub_category": "Free text inside the category, e.g. Antibiotics.",
    "quantity": "Number of units received; the first stock batch is created from it.",
    "buy_price": "Number only, cost per unit.",
    "sell_price": "Number only, price per unit shown on receipts.",
    "purchase_date": "Any common date format, e.g. 2025-01-31 or 31/01/2025.",
    "expiry_date": "Leave blank when the item has no expiry date.",
    "supplier": "Free text, e.g. the distributor name.",
    "visit_date": "Date, or date and time, of the visit.",
    "diagnosis": "Free text, e.g. Severe otitis externa.",
    "reason_for_visit": "Why the owner came in, e.g. Ear scratching.",
    "consult": "Yes or No - whether a consultation charge applies.",
    "temperature": "Number only, in degrees Celsius.",
    "supplies": "Items used, separated by ';' with an optional quantity, e.g. Amox x2; Vit 3.",
    "supplier_name": "The supplier's exact name, e.g. Acme Veterinary Supplies.",
    "package_name": "The package's exact name, e.g. Puppy Starter.",
    "description": "Free text describing the package.",
    "total_price": "Number only, the full package price.",
    "item_type": "service or supply - the kind of item this package line holds.",
    "appointment_date": "Date, or date and time, the appointment is booked for.",
    "service": "What the appointment is for, e.g. Vaccination.",
    "follow_up_date": "Date the follow-up is due.",
    "vaccine_name": "The vaccine's name, e.g. Rabies.",
    "dosage": "Free text, e.g. 1 tablet twice daily.",
    "instructions": "Free text, e.g. After food.",
    "treatment_name": "The treatment or procedure name, e.g. Wound cleaning.",
    "test_name": "The laboratory test name, e.g. Blood count.",
    "result": "Normal, Abnormal or Pending - the test outcome.",
    "expense_date": "Date the expense was paid.",
    "amount": "Number only, in your currency.",
    "receipt_code": "An existing receipt code, e.g. VISIT-202501-0001.",
    "payment_method": "Cash, Card, Bank Transfer or Other.",
    "payment_date": "Date the payment was recorded.",
    "receipt_date": "Date, or date and time, of the sale.",
    "items": "Item names, e.g. Amoxicillin 250mg x2; Dental Chews.",
    "discount": "Cash amount taken off the sale total.",
}


def is_instructions_sheet(sheet_name):
    """True when ``sheet_name`` is a documentation-only sheet.

    The import dialog refuses these sheets, so the examples that live there can
    never reach the database.
    """
    if not sheet_name:
        return False
    key = re.sub(r"[^a-z0-9]+", " ", str(sheet_name).strip().lower()).strip()
    return key in INSTRUCTIONS_SHEET_ALIASES


def field_guidance(entity_key, field_name):
    """Returns ``(label, required, example, hint)`` for one template column."""
    spec = get_spec(entity_key)
    if field_name not in spec.fields:
        raise KeyError(f"Unknown field for {entity_key}: {field_name}")
    index = spec.fields.index(field_name)
    sample = spec.sample[index] if index < len(spec.sample) else ""
    example = str(sample) if sample != "" else tr("leave blank")
    return (
        spec.field_label(field_name),
        field_name in spec.required,
        example,
        _FIELD_HINTS.get(field_name, ""),
    )


def template_guidance(entity_key):
    """Returns one :func:`field_guidance` tuple per column, in sheet order."""
    spec = get_spec(entity_key)
    return [field_guidance(entity_key, name) for name in spec.fields]


def _load_openpyxl():
    """Imports openpyxl lazily and returns the pieces the writers need."""
    try:
        import openpyxl
        from openpyxl.comments import Comment
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to write Excel files") from exc
    return openpyxl, Comment, Alignment, Font, PatternFill, get_column_letter


def _fill_data_sheet(sheet, entity_key, headers, rows, Comment, Alignment, Font,
                     PatternFill, get_column_letter):
    """Writes one entity's headers plus ``rows`` into ``sheet``, template style.

    Shared by the single-entity templates and the multi-sheet export, so a
    workbook with many sheets is laid out exactly like its template. ``rows``
    is empty for a starter template and holds the real records for a data file.
    """
    sheet.append(headers)
    for row in rows or ():
        sheet.append(list(row))

    header_fill = PatternFill("solid", start_color=_TEMPLATE_BRAND,
                              end_color=_TEMPLATE_BRAND)
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.comment = Comment(_header_comment(entity_key, header), APP_SHORT_NAME)
        sheet.column_dimensions[get_column_letter(index)].width = max(
            16, len(str(header)) + 6
        )

    last_column = get_column_letter(len(headers))
    sheet.freeze_panes = "A2"  # the header stays visible while scrolling
    # The filter covers the data too when the file carries records.
    sheet.auto_filter.ref = f"A1:{last_column}{1 + len(rows or ())}"
    return sheet


def write_excel_workbook(path, sheets):
    """Writes an ``.xlsx`` workbook with one styled sheet per ``sheets`` entry.

    Every sheet is built by :func:`_fill_data_sheet`, and one Instructions
    sheet documents them all, so the workbook can be handed straight back to
    :func:`import_workbook`.

    Args:
        path: destination workbook file.
        sheets: ``(sheet_name, entity_key, rows)`` triples in the order the
            sheets should appear; ``rows`` may be empty (headers only).

    Returns:
        Path: the written file.
    """
    (openpyxl, Comment, Alignment, Font, PatternFill,
     get_column_letter) = _load_openpyxl()

    sheets = list(sheets)
    if not sheets:
        raise ValueError("A workbook needs at least one data sheet")

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # every sheet below is named explicitly
    for sheet_name, entity_key, rows in sheets:
        headers, _sample = template_rows(entity_key)
        _fill_data_sheet(workbook.create_sheet(sheet_name), entity_key, headers,
                         rows, Comment, Alignment, Font, PatternFill,
                         get_column_letter)

    _write_instructions_sheet(workbook, sheets, Font, Alignment, get_column_letter)

    workbook.save(str(path))
    return Path(path)


def write_templates_workbook(path):
    """Writes ONE headers-only workbook with a sheet per importable entity.

    The counterpart of ``exporter.write_workbook``: the same sheet names, the
    same Instructions sheet and the same layout, but with no sample row, so a
    starter file can never push a demo record into the database. Filling it in
    and importing it needs nothing but the **every data sheet** option.

    Returns:
        Path: the written file.
    """
    return write_excel_workbook(path, [
        (entity_sheet_name(entity_key), entity_key, None)
        for entity_key in IMPORT_KEYS
    ])


def write_table_file(path, entity_key, rows=None):
    """Writes ``entity_key``'s headers, plus ``rows`` when given, to ``path``.

    The single writer behind both the headers-only starter templates and the
    data exports, so an exported file is laid out exactly like its template.

    Args:
        path: destination file; its suffix picks Excel vs delimited text.
        entity_key: the entity whose columns are written.
        rows: optional row lists aligned to the entity's columns.

    Returns:
        Path: the written file.
    """
    get_spec(entity_key)  # validates the entity before touching the filesystem
    path = Path(path)
    headers, _sample = template_rows(entity_key)

    if path.suffix.lower() in EXCEL_EXTENSIONS:
        return write_excel_workbook(path, [(TEMPLATE_SHEET_NAME, entity_key, rows)])

    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows or ())
    return path


def _write_instructions_sheet(workbook, sheets, Font, Alignment, get_column_letter):
    """Adds the documentation sheet: steps, per-column tables and a warning.

    ``sheets`` is the same ``(sheet_name, entity_key, rows)`` list the workbook
    was built from, so the steps and tables name the real sheets - a
    single-entity template gets one column table, a multi-sheet export one per
    sheet.
    """
    sheets = list(sheets) or [
        (TEMPLATE_SHEET_NAME, entity_key, None)
        for entity_key in IMPORT_KEYS
    ]
    multi = len(sheets) > 1
    only_sheet = "" if multi else sheets[0][0]

    sheet = workbook.create_sheet(INSTRUCTIONS_SHEET_NAME)

    title = sheet.cell(row=1, column=1, value=tr(
        "How to fill in this workbook" if multi else "How to fill in this template"
    ))
    title.font = Font(bold=True, size=14)

    row = 3
    for step in (WORKBOOK_STEPS if multi else TEMPLATE_STEPS):
        text = tr(step)
        if only_sheet and "{sheet}" in text:
            text = text.format(sheet=only_sheet)
        sheet.cell(row=row, column=1, value=text)
        row += 1

    row += 1
    for sheet_name, entity_key, _rows in sheets:
        if multi:
            heading = sheet.cell(row=row, column=1,
                                 value=tr("Sheet: {name}").format(name=sheet_name))
            heading.font = Font(bold=True, size=12)
            row += 2

        for offset, heading_text in enumerate(("Column", "Required", "Example", "Notes")):
            cell = sheet.cell(row=row, column=1 + offset, value=tr(heading_text))
            cell.font = Font(bold=True)
        row += 1

        for label, required, example, hint in template_guidance(entity_key):
            sheet.cell(row=row, column=1, value=label)
            sheet.cell(row=row, column=2, value=tr("Yes") if required else tr("No"))
            sheet.cell(row=row, column=3, value=example)
            sheet.cell(row=row, column=4, value=hint)
            row += 1
        row += 1

    if multi:
        warning_text = tr("This sheet is documentation only - the app never "
                          "imports it. Type your records on the data sheets.")
    else:
        warning_text = tr("This sheet is documentation only - the app never "
                          "imports it. Type your records on the '{sheet}' sheet."
                          ).format(sheet=only_sheet)
    warning = sheet.cell(row=row, column=1, value=warning_text)
    warning.font = Font(bold=True, color=_TEMPLATE_DANGER)
    row += 1
    sheet.cell(row=row, column=1, value=tr(
        "Examples shown here are illustrations, not real records."
    )).font = Font(italic=True)

    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 26
    sheet.column_dimensions["D"].width = 70
    sheet.sheet_view.showGridLines = False


def _header_comment(entity_key, header):
    """Builds the hover help of one header cell (never a data row)."""
    spec = get_spec(entity_key)
    for field_name in spec.fields:
        if spec.field_label(field_name) != header:
            continue
        label, required, example, hint = field_guidance(entity_key, field_name)
        lines = [
            f"{label}: {tr('required') if required else tr('optional')}",
            tr("Example: {example}").format(example=example),
        ]
        if hint:
            lines.append(hint)
        return "\n".join(lines)
    return header