"""Export the clinic's data in the exact layout the importer reads.

The counterpart of :mod:`src.core.importer`: ``export_rows`` pulls one list of
rows per entity through the repositories, and ``write_entity_file`` /
``write_all_exports`` save them as Excel or CSV files whose columns are the
same ones the import templates use. ``write_workbook`` puts every data type in a
single multi-sheet workbook, which ``importer.import_workbook`` reads back
sheet by sheet. Either way, a file written here can be handed to
:func:`src.core.importer.import_table` / :func:`src.core.importer.import_workbook`
unchanged.

Like the importer this module is UI-free (no Qt widgets), so the dialogs only
pick a destination and report the result.
"""

import logging
from pathlib import Path

from src.core import importer
from src.core.repositories import (appointment_repo, client_repo, followup_repo,
                                   medication_repo, package_repo, payment_repo,
                                   pet_repo, sales_repo, supplier_repo,
                                   supply_repo, test_repo, treatment_repo,
                                   vaccination_repo, visit_repo)

logger = logging.getLogger(__name__)

#: The exportable entities - everything the importer accepts.
EXPORT_KEYS = importer.IMPORT_KEYS


def _owner_rows():
    return client_repo.get_owners_for_export()


def _pet_rows():
    return pet_repo.get_pets_for_export()


def _supply_rows():
    rows = []
    for row in supply_repo.search_supplies():
        rows.append({
            "item_name": row.get("item_name", ""),
            "category": row.get("category", ""),
            "sub_category": row.get("sub_category", ""),
            # The batch total is what was purchased, which is what importing a
            # quantity would create; current_stock is what is left after sales.
            "quantity": row.get("batch_quantity", 0),
            "buy_price": row.get("buy_price"),
            "sell_price": row.get("sell_price"),
            "purchase_date": row.get("purchase_date", ""),
            "expiry_date": row.get("expiry_date", ""),
            "supplier": row.get("supplier", ""),
        })
    return rows


def _visit_rows():
    return visit_repo.get_visits_for_export()


def _supplier_rows():
    return supplier_repo.get_suppliers_for_export()


def _package_rows():
    return package_repo.get_packages_for_export()


def _package_item_rows():
    return package_repo.get_package_items_for_export()


def _appointment_rows():
    return appointment_repo.get_appointments_for_export()


def _followup_rows():
    return followup_repo.get_followups_for_export()


def _vaccination_rows():
    return vaccination_repo.get_vaccinations_for_export()


def _medication_rows():
    return medication_repo.get_medications_for_export()


def _treatment_rows():
    return treatment_repo.get_treatments_for_export()


def _test_rows():
    return test_repo.get_tests_for_export()


def _expense_rows():
    return sales_repo.get_expenses_for_export()


def _retail_sale_rows():
    return sales_repo.get_retail_sales_for_export()


def _payment_rows():
    return payment_repo.get_payments_for_export()


_ROW_BUILDERS = {
    "owners": _owner_rows,
    "pets": _pet_rows,
    "suppliers": _supplier_rows,
    "supplies": _supply_rows,
    "packages": _package_rows,
    "package_items": _package_item_rows,
    "appointments": _appointment_rows,
    "visits": _visit_rows,
    "followups": _followup_rows,
    "vaccinations": _vaccination_rows,
    "medications": _medication_rows,
    "treatments": _treatment_rows,
    "tests": _test_rows,
    "expenses": _expense_rows,
    "retail_sales": _retail_sale_rows,
    "payments": _payment_rows,
}


def _blank(value):
    """Normalizes a cell: ``None`` becomes an empty string, numbers stay typed."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def export_rows(entity_key):
    """Returns ``(headers, rows)`` for one entity, in template column order.

    Args:
        entity_key: ``"owners"``, ``"pets"``, ``"supplies"`` or ``"visits"``.

    Returns:
        tuple: the translated headers and a list of row lists, each row padded
        to the header length so the file always matches the template.

    Raises:
        KeyError: if ``entity_key`` is not an exportable entity.
    """
    builder = _ROW_BUILDERS.get(entity_key)
    if builder is None:
        raise KeyError("Unknown export entity: {}".format(entity_key))

    spec = importer.get_spec(entity_key)
    headers = [spec.field_label(name) for name in spec.fields]
    rows = []
    for record in builder():
        rows.append([_blank(record.get(name)) for name in spec.fields])
    return headers, rows


def export_counts():
    """Returns ``{entity_key: row_count}`` for every exportable entity."""
    counts = {}
    for entity_key in EXPORT_KEYS:
        try:
            _headers, rows = export_rows(entity_key)
        except Exception:  # a broken query must not hide the other entities
            logger.exception("Export: could not count %s", entity_key)
            counts[entity_key] = 0
            continue
        counts[entity_key] = len(rows)
    return counts


def write_entity_file(path, entity_key, file_format=None):
    """Writes one entity's data to ``path`` as Excel or CSV.

    The layout is the one :func:`src.core.importer.write_template` produces -
    same headers, same hover comments, same Instructions sheet - so the file can
    be handed straight back to the importer.

    Args:
        path: destination file; its suffix picks the format.
        entity_key: the entity to export.
        file_format: ``"xlsx"`` (default) or ``"csv"``; only consulted when the
            path carries no recognised suffix.

    Returns:
        tuple[Path, int]: the written file and the number of data rows.
    """
    _headers, rows = export_rows(entity_key)
    path = Path(path)
    if path.suffix.lower() not in importer.EXCEL_EXTENSIONS and \
            path.suffix.lower() != ".csv":
        path = path.with_suffix(importer.TEMPLATE_EXTENSIONS[
            importer.normalize_template_format(file_format)])

    written = importer.write_table_file(path, entity_key, rows)
    logger.info("Export: wrote %s %s row(s) to %s", entity_key, len(rows), written)
    return written, len(rows)


def write_all_exports(directory, file_format=None):
    """Writes one data file per entity into ``directory``.

    Args:
        directory: folder to write into (created when missing).
        file_format: ``"xlsx"`` (default) or ``"csv"``.

    Returns:
        list[tuple[Path, int]]: the written file and its row count, in
        :data:`EXPORT_KEYS` order.
    """
    extension = importer.TEMPLATE_EXTENSIONS[importer.normalize_template_format(file_format)]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    written = []
    for entity_key in EXPORT_KEYS:
        path, count = write_entity_file(directory / "{}{}".format(entity_key, extension),
                                        entity_key)
        written.append((path, count))
    logger.info("Export: wrote %s", [(str(p), n) for p, n in written])
    return written


#: File name used when the caller does not choose one.
WORKBOOK_NAME = "pet_data.xlsx"


def write_workbook(path=None, directory=None):
    """Writes EVERY entity into one Excel workbook, one sheet per data type.

    This is what the Settings export button offers: a single file that holds
    Owners, Pets, Supplies and Visits, each in the same layout as its own
    template, plus the documentation sheet. ``plan_workbook`` /
    ``import_workbook`` read it back unchanged.

    Args:
        path: destination file; any other suffix becomes ``.xlsx``.
        directory: used instead of ``path`` when given - the workbook lands in
            this folder under :data:`WORKBOOK_NAME`.

    Returns:
        tuple[Path, dict, int]: the written file, the row count per entity
        (keys of :data:`EXPORT_KEYS`) and the total record count.
    """
    sheets, counts = [], {}
    for entity_key in EXPORT_KEYS:
        _headers, rows = export_rows(entity_key)  # raises on a broken entity
        counts[entity_key] = len(rows)
        sheets.append((importer.entity_sheet_name(entity_key), entity_key, rows))

    if path is None:
        path = Path(directory or ".") / WORKBOOK_NAME
    path = Path(path)
    if path.suffix.lower() not in importer.EXCEL_EXTENSIONS:
        path = path.with_suffix(".xlsx")

    written = importer.write_excel_workbook(path, sheets)
    total = sum(counts.values())
    logger.info("Export: wrote %s record(s) across %s sheet(s) to %s",
                total, len(sheets), written)
    return written, counts, total