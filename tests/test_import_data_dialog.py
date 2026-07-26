"""Tests for src/ui/dialogs/import_data_dialog.py."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv

import pytest
from PyQt5.QtWidgets import QMessageBox

from src.core import importer
import src.ui.dialogs.import_data_dialog as dialog_module
from src.ui.dialogs.import_data_dialog import ImportDataDialog


def _write_csv(path, headers, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


@pytest.fixture
def importer_db(fresh_db, monkeypatch):
    """Points the importer at the fresh test DB."""
    monkeypatch.setattr(importer, "get_connection", lambda: fresh_db, raising=False)
    return fresh_db


@pytest.fixture
def dialog(qapp, importer_db, tmp_path, monkeypatch):
    """A live dialog with modal message boxes auto-answered and backups stubbed."""
    backups = []
    (tmp_path / "Database.db").write_bytes(b"")

    monkeypatch.setattr(dialog_module, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(dialog_module, "get_user_db_path",
                        lambda: tmp_path / "Database.db")

    def _fake_create_backup(**kwargs):
        backups.append(kwargs.get("backup_kind"))
        return kwargs.get("backups_dir") / "Database_stub.db"

    monkeypatch.setattr(dialog_module, "create_backup", _fake_create_backup)
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(dialog_module.QMessageBox, name,
                            staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(dialog_module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))

    widget = ImportDataDialog(current_user={"user_id": 1, "roles": ["admin"]})
    widget.backup_calls = backups
    # The detailed results box runs a nested modal loop, which cannot be driven
    # from a test; record the calls instead.
    widget.result_boxes = []
    widget._show_results = lambda summary, title: widget.result_boxes.append(
        (summary, title)
    )
    yield widget
    widget.deleteLater()


class TestDialogLayout:
    def test_offers_every_importable_entity(self, dialog):
        keys = [dialog.type_combo.itemData(i)
                for i in range(dialog.type_combo.count())]
        assert keys == list(importer.IMPORT_KEYS)

    def test_buttons_start_disabled_until_a_file_is_chosen(self, dialog):
        assert dialog.import_btn.isEnabled() is False
        assert dialog.validate_btn.isEnabled() is False

    def test_retranslate_relabels_without_losing_selection(self, dialog):
        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("supplies"))
        dialog.retranslate_ui()

        assert dialog.type_combo.currentData() == "supplies"
        assert dialog.import_btn.text() == "Import"


class TestFileLoading:
    def test_loading_detects_the_entity_and_previews_rows(self, dialog, tmp_path):
        path = _write_csv(
            tmp_path / "owners.csv",
            ["Owner Name", "Phone Number", "Notes"],
            [["Ahmed Ali", "01001234567", "VIP"], ["Mona Hassan", "01112223333", ""]],
        )

        assert dialog.load_file(path) is True
        assert dialog.path_edit.text() == path
        assert dialog.entity_key == "owners"
        assert dialog.import_btn.isEnabled() is True
        assert dialog.preview_table.rowCount() == 2
        assert dialog.preview_table.columnCount() == 3

    def test_missing_required_column_keeps_import_disabled(self, dialog, tmp_path):
        path = _write_csv(tmp_path / "owners.csv", ["Phone Number"], [["0100"]])

        dialog.load_file(path)
        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("owners"))

        assert dialog.import_btn.isEnabled() is False
        assert "Missing" in dialog.columns_label.text()

    def test_unreadable_file_is_reported(self, dialog, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4")

        assert dialog.load_file(str(path)) is False
        assert dialog.import_btn.isEnabled() is False

    def test_excel_sheet_selector_appears_for_workbooks(self, dialog, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Owners"
        workbook.active.append(["Owner Name", "Phone Number"])
        workbook.active.append(["Ahmed Ali", "01001234567"])
        workbook.create_sheet("Spare").append(["nothing"])
        workbook.save(str(path))

        assert dialog.load_file(str(path)) is True
        assert dialog.sheet_combo.isHidden() is False
        assert dialog.sheet_combo.count() == 2

    def test_single_column_suppliers_sheet_is_detected_by_name(self, dialog,
                                                               tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Suppliers"
        workbook.active.append(["Supplier"])
        workbook.active.append(["Acme Veterinary Supplies"])
        workbook.save(str(path))

        assert dialog.load_file(str(path)) is True
        # One column can never reach the two-field auto-detect threshold, so the
        # sheet name must carry it - otherwise every other type stays disabled.
        assert dialog.entity_key == "suppliers"
        assert dialog.import_btn.isEnabled() is True

    def test_changing_the_type_selects_the_matching_sheet(self, dialog, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Owners"
        workbook.active.append(["Owner Name", "Phone Number"])
        workbook.active.append(["Ahmed Ali", "01001234567"])
        supplies = workbook.create_sheet("Supplies")
        supplies.append(["Item Name", "Category", "Quantity", "Sell Price"])
        supplies.append(["Amox", "Medicine", 10, 25])
        workbook.save(str(path))
        dialog.load_file(str(path))
        dialog.all_sheets_check.setChecked(False)  # unlock the selectors
        assert dialog.entity_key == "owners"

        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("supplies"))

        # The sheet follows the type so the required columns are checked against
        # the right data and the buttons stay enabled.
        assert dialog.sheet_combo.currentText() == "Supplies"
        assert dialog.entity_key == "supplies"
        assert dialog.import_btn.isEnabled() is True
        assert dialog.validate_btn.isEnabled() is True


class TestValidateAndImport:
    def test_validate_reports_counts_without_writing(self, dialog, tmp_path, repos):
        path = _write_csv(tmp_path / "owners.csv",
                          ["Owner Name", "Phone Number"],
                          [["Ahmed Ali", "01001234567"], ["Mona Hassan", "0111"]])
        dialog.load_file(path)

        dialog._on_validate()

        assert dialog.last_summary.imported == 2
        assert "2 to add" in dialog.status_label.text()
        assert repos["client"].get_clients() == []
        assert dialog.backup_calls == []

    def test_import_writes_rows_and_creates_a_backup(self, dialog, tmp_path, repos):
        path = _write_csv(tmp_path / "owners.csv",
                          ["Owner Name", "Phone Number"],
                          [["Ahmed Ali", "01001234567"]])
        dialog.load_file(path)

        emitted = []
        dialog.data_changed.connect(emitted.append)
        dialog._on_import()

        assert dialog.last_summary.imported == 1
        assert len(repos["client"].get_clients()) == 1
        assert dialog.backup_calls == ["manual"]
        assert emitted == ["owners"]

    def test_declining_the_confirmation_writes_nothing(self, dialog, tmp_path,
                                                       repos, monkeypatch):
        monkeypatch.setattr(dialog_module.QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.No))
        path = _write_csv(tmp_path / "owners.csv", ["Owner Name"], [["Ahmed Ali"]])
        dialog.load_file(path)

        dialog._on_import()

        assert dialog.last_summary is None
        assert repos["client"].get_clients() == []

    def test_failures_are_listed_and_keep_the_dialog_open(self, dialog, tmp_path,
                                                          repos):
        # Row 2 has a pet but no usable owner, so only row 1 lands.
        path = _write_csv(tmp_path / "pets.csv",
                          ["Pet Name", "Owner Name"],
                          [["Rex", "Ahmed Ali"], ["Buddy", "   "]])
        dialog.load_file(path)

        dialog._on_import()

        assert dialog.last_summary.imported == 1
        assert dialog.last_summary.failed == 1
        assert dialog.result_boxes  # the user is shown what went wrong
        assert dialog.result() == 0  # not accepted, so the file can be fixed

    def test_safety_backup_can_be_skipped(self, dialog, tmp_path):
        path = _write_csv(tmp_path / "owners.csv", ["Owner Name"], [["Ahmed Ali"]])
        dialog.load_file(path)
        dialog.backup_check.setChecked(False)

        dialog._on_import()

        assert dialog.backup_calls == []

    def test_failed_backup_cancels_the_import(self, dialog, tmp_path, repos,
                                              monkeypatch):
        def _boom(**kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(dialog_module, "create_backup", _boom)
        path = _write_csv(tmp_path / "owners.csv", ["Owner Name"], [["Ahmed Ali"]])
        dialog.load_file(path)

        dialog._on_import()

        assert dialog.last_summary is None
        assert repos["client"].get_clients() == []


def _write_workbook(path, sheets):
    """Writes a ``(sheet_name, entity_key, rows)`` workbook (openpyxl only)."""
    return importer.write_excel_workbook(path, sheets)


_OWNER = ["Ahmed Ali", "01001234567", ""]
_PET = ["Rex", "Ahmed Ali", "01001234567", "Dog", "Labrador Retriever", "Male",
        24, 25.5]
_SUPPLY = ["Amox 250", "Medicine", "Antibiotics", 10, 12.5, 25, "2025-01-01",
           "2026-01-01", ""]
_VISIT = ["2025-01-15 10:00", "Ahmed Ali", "01001234567", "Rex", "Otitis",
          "Ear scratching", "", "Yes", 38.5, "Amox 250 x2"]


class TestAllSheetsMode:
    """A workbook holding several data types is imported sheet by sheet."""

    def _clinic_book(self, tmp_path, name="clinic.xlsx"):
        return _write_workbook(tmp_path / name, [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
            ("Supplies", "supplies", [_SUPPLY]),
            ("Visits", "visits", [_VISIT]),
        ])

    def test_every_sheet_is_announced_in_the_preview(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))

        assert dialog._all_sheets_mode() is True
        assert dialog._plan.entities == ("owners", "pets", "supplies", "visits")
        # The preview lists the sheets instead of the cells of one of them.
        headers = [dialog.preview_table.horizontalHeaderItem(i).text()
                   for i in range(dialog.preview_table.columnCount())]
        assert headers == ["Sheet", "Data Type", "Rows"]
        listed = [dialog.preview_table.item(row, 0).text()
                  for row in range(dialog.preview_table.rowCount())]
        assert listed == ["Owners", "Pets", "Supplies", "Visits"]
        assert dialog.preview_table.item(0, 2).text() == "1"
        assert "Ignored sheets" in dialog.columns_label.text()
        assert importer.INSTRUCTIONS_SHEET_NAME in dialog.columns_label.text()

    def test_sheet_and_type_selectors_are_locked(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))

        assert dialog.sheet_combo.isEnabled() is False
        assert dialog.type_combo.isEnabled() is False
        assert dialog.validate_btn.isEnabled() is True
        assert dialog.import_btn.isEnabled() is True

    def test_the_user_can_switch_back_to_one_sheet(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))

        dialog.all_sheets_check.setChecked(False)

        assert dialog._all_sheets_mode() is False
        assert dialog.sheet_combo.isEnabled() is True
        assert dialog.type_combo.isEnabled() is True
        assert dialog.preview_table.columnCount() == 3  # the owners columns

    def test_validating_the_workbook_touches_nothing(self, dialog, tmp_path, repos):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))

        dialog._on_validate()

        assert dialog.last_summary.total == 4
        assert dialog.last_summary.failed == 0
        assert "4 to add" in dialog.status_label.text()
        assert repos["client"].get_clients() == []
        assert repos["pet"].get_pets() == []
        assert repos["visit"].get_visits() == []

    def test_importing_the_workbook_lands_every_sheet(self, dialog, tmp_path, repos):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))
        emitted = []
        dialog.data_changed.connect(emitted.append)

        dialog._on_import()

        assert dialog.last_summary.imported == 4
        assert dialog.last_summary.failed == 0
        assert len(repos["client"].get_clients()) == 1
        assert len(repos["pet"].get_pets()) == 1
        assert len(repos["visit"].get_visits()) == 1
        # The owner is shared, so it is never created twice.
        assert repos["supply"].get_existing_supply(
            "Amox 250", "Medicine")["current_stock"] == 8
        assert emitted == ["owners", "pets", "supplies", "visits"]
        assert dialog.backup_calls == ["manual"]
        assert dialog.result() == 1  # accepted

    def test_the_confirmation_names_every_sheet(self, dialog, tmp_path,
                                               monkeypatch):
        pytest.importorskip("openpyxl")
        seen = {}

        def _capture(_parent, _title, text, _buttons):
            seen["text"] = text
            return QMessageBox.Yes

        monkeypatch.setattr(dialog_module.QMessageBox, "question",
                            staticmethod(_capture))
        dialog.load_file(self._clinic_book(tmp_path))

        dialog._on_import()

        assert "4 row(s)" in seen["text"]
        for sheet in ("Owners", "Pets", "Supplies", "Visits"):
            assert sheet in seen["text"]

    def test_failures_name_the_sheet_they_came_from(self, dialog, tmp_path, repos):
        pytest.importorskip("openpyxl")
        # The visit's supply is on no sheet, so that row fails.
        path = _write_workbook(tmp_path / "broken.xlsx", [
            ("Owners", "owners", [_OWNER]),
            ("Pets", "pets", [_PET]),
            ("Visits", "visits", [_VISIT]),
        ])
        dialog.load_file(path)

        dialog._on_import()

        assert dialog.last_summary.imported == 2
        assert dialog.last_summary.failed == 1
        assert dialog.result_boxes
        summary, _title = dialog.result_boxes[0]
        assert "Visits - Row 2" in importer.result_details(summary)
        assert dialog.result() == 0  # stays open so the file can be fixed

    def test_a_single_data_sheet_stays_single(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        # One data sheet plus the Instructions sheet: nothing to choose between.
        path = _write_workbook(tmp_path / "one.xlsx", [("Owners", "owners", [_OWNER])])
        dialog.load_file(path)

        assert dialog._plan.entities == ("owners",)
        assert dialog._all_sheets_mode() is False
        assert dialog.sheet_combo.isEnabled() is True

    def test_a_text_file_has_no_all_sheets_option(self, dialog, tmp_path):
        path = _write_csv(tmp_path / "owners.csv",
                          ["Owner Name", "Phone Number"],
                          [["Ahmed Ali", "01001234567"]])

        dialog.load_file(path)

        assert dialog._plan is None
        assert dialog._all_sheets_mode() is False
        assert dialog.all_sheets_check.isHidden() is True

    def test_a_workbook_without_data_sheets_is_reported(self, dialog, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "scratch.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.title = "Scratch"
        workbook.active.append(["Nothing", "Here"])
        workbook.active.append(["a", "b"])
        workbook.save(str(path))

        dialog.load_file(str(path))

        assert dialog._plan.plans == []
        assert dialog.import_btn.isEnabled() is False
        assert "no sheet the app can import" in dialog.status_label.text()

    def test_the_choice_survives_a_sheet_switch(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))
        dialog.all_sheets_check.setChecked(False)

        dialog.sheet_combo.setCurrentIndex(
            dialog.sheet_combo.findText("Visits"))

        # Looking at another sheet does not silently switch back on.
        assert dialog._all_sheets_mode() is False

    def test_retranslate_relabels_the_option(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        dialog.load_file(self._clinic_book(tmp_path))

        dialog.retranslate_ui()

        assert dialog.all_sheets_check.text() == (
            "Import every data sheet in this workbook"
        )


class TestTemplateSheetGuard:
    """The template's Instructions sheet must never be importable."""

    def test_instructions_sheet_disables_validate_and_import(self, dialog,
                                                              tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_template(tmp_path / "owners_template.xlsx", "owners")

        assert dialog.load_file(path, importer.INSTRUCTIONS_SHEET_NAME) is True

        assert dialog.validate_btn.isEnabled() is False
        assert dialog.import_btn.isEnabled() is False
        assert "nothing is read from here" in dialog.status_label.text()

    def test_data_sheet_of_the_same_workbook_stays_importable(self, dialog,
                                                               tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_template(tmp_path / "owners_template.xlsx", "owners")

        assert dialog.load_file(path, importer.TEMPLATE_SHEET_NAME) is True

        assert dialog.validate_btn.isEnabled() is True
        assert dialog.import_btn.isEnabled() is True

    def test_both_sheets_are_offered(self, dialog, tmp_path):
        pytest.importorskip("openpyxl")
        path = importer.write_template(tmp_path / "owners_template.xlsx", "owners")

        dialog.load_file(path)

        titles = [dialog.sheet_combo.itemText(i)
                  for i in range(dialog.sheet_combo.count())]
        assert titles == [importer.TEMPLATE_SHEET_NAME,
                          importer.INSTRUCTIONS_SHEET_NAME]
        # The data sheet is preselected, so a straight Import cannot hit the docs.
        assert dialog.sheet_combo.currentText() == importer.TEMPLATE_SHEET_NAME

