"""Tests for the spreadsheet-import section of src/ui/pages/settings_page.py."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import src.core.importer as importer
import src.ui.pages.settings_page as settings_page_module
from PyQt5.QtCore import QSettings, Qt
from src.ui.pages.settings_page import SettingsPage


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _staff():
    return {"user_id": 2, "username": "staff", "roles": ["staff"]}


@pytest.fixture
def page(qapp, monkeypatch):
    # Keep the page's modal message boxes out of the test (they need a real
    # window; under the offscreen platform they would crash the process).
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(settings_page_module.QMessageBox, name,
                            staticmethod(lambda *a, **k: None))

    widget = SettingsPage()
    yield widget
    widget.deleteLater()


class TestLazyTabs:
    """Settings does not hit the database until a tab is actually opened."""

    def test_construction_defers_the_custom_lists_query(
            self, qapp, fresh_db, monkeypatch):
        calls = []

        def _record(*a, **k):
            calls.append(1)
            return ["Medicine"]

        monkeypatch.setattr(
            settings_page_module.supply_repo, "get_all_categories", _record)

        page = SettingsPage()
        try:
            assert calls == [], "no DB query before the Custom Lists tab opens"

            page.tabs.setCurrentIndex(page.tabs.indexOf(page.inventory_tab))

            assert calls, "opening the Custom Lists tab loads the categories"
            items = [page.cat_list.item(i).text() for i in range(page.cat_list.count())]
            assert "Medicine" in items
        finally:
            page.deleteLater()

    def test_switching_back_does_not_query_again(
            self, qapp, fresh_db, monkeypatch):
        calls = []
        monkeypatch.setattr(
            settings_page_module.supply_repo, "get_all_categories",
            lambda *a, **k: calls.append(1) or ["Medicine"])

        page = SettingsPage()
        try:
            page.tabs.setCurrentIndex(page.tabs.indexOf(page.inventory_tab))
            first = len(calls)
            page.tabs.setCurrentIndex(page.tabs.indexOf(page.backup_tab))
            page.tabs.setCurrentIndex(page.tabs.indexOf(page.inventory_tab))
            assert len(calls) == first, "a revisited tab must not reload"
        finally:
            page.deleteLater()


class TestImportSection:
    def test_import_group_lives_on_the_backup_tab(self, page):
        assert page.tabs.indexOf(page.backup_tab) == 2
        assert page.backup_tab.widget() is page.import_group.parentWidget()
        assert page.import_group.title() == "Import Data"
        assert page.import_btn.text() == "Import from Excel or CSV"

    def test_import_is_gated_on_edit_records(self, page):
        page.set_current_user(_staff())
        assert page.import_btn.isEnabled() is False
        assert page.import_group.isEnabled() is False

    def test_description_clears_once_an_authorised_user_logs_in(self, page):
        denied = page.import_desc_label.text()
        page.set_current_user(_admin())
        assert page.import_btn.isEnabled() is True
        assert page.import_group.isEnabled() is True
        assert page.import_desc_label.text() != denied
        assert "permission" not in page.import_desc_label.text().lower()
        page.set_current_user(_staff())
        assert page.import_desc_label.text() == denied

        page.set_current_user(_admin())
        assert page.import_btn.isEnabled() is True
        assert page.import_group.isEnabled() is True

    def test_dialog_is_not_opened_without_permission(self, page, monkeypatch):
        opened = []

        class _Signal:
            def connect(self, *_args):
                pass

        class _FakeDialog:
            data_changed = _Signal()

            def __init__(self, *args, **kwargs):
                opened.append(kwargs)

            def exec(self):
                return 0

        monkeypatch.setattr(
            "src.ui.dialogs.import_data_dialog.ImportDataDialog", _FakeDialog
        )
        page.set_current_user(_staff())

        page._on_import_data()

        assert opened == []

        page.set_current_user(_admin())
        page._on_import_data()
        assert len(opened) == 1

    def test_excel_template_button_writes_one_workbook(self, page, tmp_path,
                                                       monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")
        calls = {}

        def _fake_save(*args, **kwargs):
            calls["name"] = args[2]
            calls["filter"] = args[3]
            return str(tmp_path / "starters"), args[3]

        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(_fake_save))
        page.set_current_user(_admin())

        page.import_templates_btn.click()

        assert calls["name"] == importer.TEMPLATE_WORKBOOK_NAME
        assert calls["name"] == "pet_templates.xlsx"
        assert calls["filter"].startswith("Excel Workbooks (*.xlsx)")
        assert [p.name for p in tmp_path.iterdir()] == ["starters.xlsx"]

        book = openpyxl.load_workbook(str(tmp_path / "starters.xlsx"))
        assert book.sheetnames == (
            [importer.entity_sheet_name(k) for k in importer.IMPORT_KEYS]
            + [importer.INSTRUCTIONS_SHEET_NAME]
        )
        # Headers only: a starter file can never add a demo record.
        for entity_key in importer.IMPORT_KEYS:
            assert book[importer.entity_sheet_name(entity_key)].max_row == 1
        book.close()

    def test_excel_template_appends_the_extension(self, page, tmp_path,
                                                  monkeypatch):
        pytest.importorskip("openpyxl")
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "starters"), "")))
        page.set_current_user(_admin())

        page.import_templates_btn.click()

        assert (tmp_path / "starters.xlsx").exists()

    def test_csv_template_button_writes_csv_files(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(tmp_path)))
        page.set_current_user(_admin())

        page.import_templates_csv_btn.click()

        # A delimited file holds one data type only, so CSV keeps one file each.
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
            f"{k}_template.csv" for k in importer.IMPORT_KEYS
        )

    def test_cancelled_save_dialog_writes_nothing(self, page, tmp_path,
                                                  monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        page.set_current_user(_admin())

        page.import_templates_btn.click()

        assert list(tmp_path.iterdir()) == []

    def test_cancelled_folder_picker_writes_nothing(self, page, tmp_path,
                                                     monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: ""))
        page.set_current_user(_admin())

        page.import_templates_csv_btn.click()

        assert list(tmp_path.iterdir()) == []

    def test_template_buttons_are_gated_on_edit_records(self, page, tmp_path,
                                                         monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "x"), "")))
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(tmp_path)))
        page.set_current_user(_staff())
        assert page.import_templates_btn.isEnabled() is False
        assert page.import_templates_csv_btn.isEnabled() is False

        page.import_templates_btn.click()
        page.import_templates_csv_btn.click()
        assert list(tmp_path.iterdir()) == []

        page.set_current_user(_admin())
        assert page.import_templates_btn.isEnabled() is True
        assert page.import_templates_csv_btn.isEnabled() is True

    def test_templates_row_has_hint_and_outlined_buttons(self, page):
        page.set_current_user(_admin())

        assert page.import_templates_label.property("class") == "template-hint"
        assert "Starter templates" in page.import_templates_label.text()
        assert page.import_templates_btn.property("class") == "template-action"
        assert page.import_templates_csv_btn.property("class") == "template-action"


class TestExportSection:
    def test_export_group_lives_on_the_backup_tab(self, page):
        assert page.backup_tab.widget() is page.export_group.parentWidget()
        assert page.export_group.title() == "Export Data"
        assert page.export_xlsx_btn.text() == "Export Excel Data (.xlsx)"
        assert page.export_csv_btn.text() == "Export CSV Data (.csv)"

    def test_export_is_gated_on_edit_records(self, page):
        page.set_current_user(_staff())
        assert page.export_group.isEnabled() is False
        assert page.export_xlsx_btn.isEnabled() is False

        page.set_current_user(_admin())
        assert page.export_group.isEnabled() is True
        assert page.export_xlsx_btn.isEnabled() is True
        assert page.export_csv_btn.isEnabled() is True

    def test_description_is_blank_without_permission(self, page):
        page.set_current_user(_staff())
        assert page.export_desc_label.text() == ""

        page.set_current_user(_admin())
        assert "same columns as the templates" in page.export_desc_label.text()

    def test_buttons_carry_the_outlined_style(self, page):
        assert page.export_xlsx_btn.property("class") == "template-action"
        assert page.export_csv_btn.property("class") == "template-action"

    def test_excel_button_writes_one_multi_sheet_workbook(self, page, tmp_path,
                                                          monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")
        calls = {}

        def _fake_save(*args, **kwargs):
            calls["name"] = args[2]
            calls["filter"] = args[3]
            return str(tmp_path / "clinic"), args[3]

        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(_fake_save))
        page.set_current_user(_admin())

        page.export_xlsx_btn.click()

        assert calls["name"] == "pet_data.xlsx"
        assert calls["filter"].startswith("Excel Workbooks (*.xlsx)")
        written = tmp_path / "clinic.xlsx"
        assert [p.name for p in tmp_path.iterdir()] == ["clinic.xlsx"]

        workbook = openpyxl.load_workbook(str(written))
        assert workbook.sheetnames == (
            [importer.entity_sheet_name(k) for k in importer.IMPORT_KEYS]
            + [importer.INSTRUCTIONS_SHEET_NAME]
        )
        workbook.close()

    def test_excel_button_appends_the_extension(self, page, tmp_path, monkeypatch):
        pytest.importorskip("openpyxl")
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "clinic"), "")))
        page.set_current_user(_admin())

        page.export_xlsx_btn.click()

        assert (tmp_path / "clinic.xlsx").exists()

    def test_cancelled_save_dialog_writes_nothing(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        page.set_current_user(_admin())

        page.export_xlsx_btn.click()

        assert list(tmp_path.iterdir()) == []

    def test_csv_button_writes_csv_files(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(tmp_path)))
        page.set_current_user(_admin())

        page.export_csv_btn.click()

        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
            f"{k}.csv" for k in importer.IMPORT_KEYS
        )

    def test_cancelled_folder_picker_writes_nothing(self, page, tmp_path,
                                                     monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: ""))
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        page.set_current_user(_admin())

        page.export_csv_btn.click()

        assert list(tmp_path.iterdir()) == []

    def test_export_is_skipped_without_permission(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(settings_page_module.QFileDialog, "getExistingDirectory",
                            staticmethod(lambda *a, **k: str(tmp_path)))
        monkeypatch.setattr(settings_page_module.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "clinic"), "")))
        page.set_current_user(_staff())

        page.export_xlsx_btn.click()
        page.export_csv_btn.click()

        assert list(tmp_path.iterdir()) == []

    def test_retranslate_relabels_the_export_row(self, page):
        page.retranslate_ui()
        assert page.export_group.title() == "Export Data"
        assert page.export_xlsx_btn.text() == "Export Excel Data (.xlsx)"
        assert page.export_csv_btn.text() == "Export CSV Data (.csv)"

    def test_refresh_after_import_is_safe_without_main_window(self, page):
        # No MainWindow parent - must not raise.
        page._refresh_after_import("visits")

    def test_retranslate_keeps_the_import_labels(self, page):
        page.set_current_user(_admin())

        page.retranslate_ui()

        assert page.import_group.title() == "Import Data"
        assert page.import_btn.text() == "Import from Excel or CSV"
        assert page.import_templates_btn.text() == "Save Excel Templates (.xlsx)"
        assert page.import_templates_csv_btn.text() == "Save CSV Templates (.csv)"


def test_import_i18n_keys_exist_in_english_and_arabic():
    import json
    from pathlib import Path

    translations = Path(__file__).resolve().parent.parent / "assets" / "translations.json"
    data = json.loads(translations.read_text(encoding="utf-8"))

    for key in ("Import Data", "Import from Excel or CSV",
                "Save Excel Templates (.xlsx)", "Save CSV Templates (.csv)",
                "Import Owners", "Import Pets", "Import Supplies", "Import Visits"):
        assert key in data["en"], key
        assert key in data["ar"], key
        assert data["ar"][key] != key, key


def test_templates_stylesheet_classes_exist():
    from pathlib import Path

    qss = (Path(__file__).resolve().parent.parent / "assets" / "style.qss"
           ).read_text(encoding="utf-8")

    assert 'QPushButton[class="template-action"]' in qss
    assert 'QLabel[class="template-hint"]' in qss
    assert "QFrame#importTemplatesDivider" in qss


def test_csv_template_is_headers_only(tmp_path):
    path = importer.write_template(tmp_path / "owners_template.csv", "owners")
    table = importer.read_table(path)

    assert table.headers == [importer.get_spec("owners").field_label(f)
                             for f in importer.get_spec("owners").fields]
    assert table.rows == []  # no sample row that could reach the database


class TestSchedulingSection:
    """Settings > Clinic Profile > Scheduling Rules (the auto-cancel window)."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, tmp_path, monkeypatch):
        from src.utils.settings_manager import SettingsManager

        monkeypatch.setattr(
            "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
        )
        SettingsManager._cache = None
        yield
        SettingsManager._cache = None

    def test_group_lives_on_the_profile_tab_below_financial_settings(self, page):
        from src.config.constants import DEFAULT_AUTO_CANCEL_HOURS

        assert page.tabs.indexOf(page.profile_tab) == 0
        assert page.profile_tab.isAncestorOf(page.scheduling_group)
        assert page.scheduling_group.title() == "Scheduling Rules"
        assert page.profile_vbox.indexOf(page.scheduling_group) > \
            page.profile_vbox.indexOf(page.fees_group)
        assert page.auto_cancel_edit.value() == DEFAULT_AUTO_CANCEL_HOURS

    def test_spinbox_range_and_suffix(self, page):
        from src.config.constants import AUTO_CANCEL_HOURS_MAX, AUTO_CANCEL_HOURS_MIN

        assert page.auto_cancel_edit.minimum() == AUTO_CANCEL_HOURS_MIN
        assert page.auto_cancel_edit.maximum() == AUTO_CANCEL_HOURS_MAX
        assert page.auto_cancel_edit.suffix() == " h"
        assert page.auto_cancel_edit.toolTip()

    def test_preview_explains_the_rule_and_follows_the_spinbox(self, page):
        assert "auto-canceled" in page.scheduling_preview.text()

        page.auto_cancel_edit.setValue(6)
        six_hours = page.scheduling_preview.text()
        page.auto_cancel_edit.setValue(48)
        assert page.scheduling_preview.text() != six_hours

    def test_load_reads_the_saved_window(self, page):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        SettingsManager.set(status_resolver.SETTING_KEY, 6)
        page._load_settings()
        assert page.auto_cancel_edit.value() == 6

    def test_load_falls_back_to_the_default_for_junk(self, page):
        from src.config.constants import AUTO_CANCEL_HOURS_MIN, DEFAULT_AUTO_CANCEL_HOURS
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        SettingsManager.set(status_resolver.SETTING_KEY, "whenever")
        page._load_settings()
        assert page.auto_cancel_edit.value() == DEFAULT_AUTO_CANCEL_HOURS

        SettingsManager.set(status_resolver.SETTING_KEY, -3)
        page._load_settings()
        assert page.auto_cancel_edit.value() == AUTO_CANCEL_HOURS_MIN

    def test_save_persists_the_window(self, page):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        page.auto_cancel_edit.setValue(48)
        page.apply_settings()
        assert SettingsManager.get(status_resolver.SETTING_KEY) == 48

    def test_cancel_reverts_an_unsaved_edit(self, page):
        from src.core import status_resolver
        from src.utils.settings_manager import SettingsManager

        SettingsManager.set(status_resolver.SETTING_KEY, 12)
        page._load_settings()
        page.auto_cancel_edit.setValue(200)
        page.cancel_settings()
        assert page.auto_cancel_edit.value() == 12

    def test_retranslate_keeps_the_scheduling_labels(self, page):
        page.retranslate_ui()
        assert page.scheduling_group.title() == "Scheduling Rules"
        assert page.scheduling_preview.text()


def test_scheduling_i18n_keys_exist_in_english_and_arabic():
    import json
    from pathlib import Path

    translations = Path(__file__).resolve().parent.parent / "assets" / "translations.json"
    data = json.loads(translations.read_text(encoding="utf-8"))

    keys = (
        "Scheduling Rules",
        "Auto-cancel after:",
        "How long an appointment or follow-up stays Late after its scheduled "
        "time before it is automatically marked Canceled.",
        "Example: a visit at {start} turns Late at that time and is "
        "auto-canceled after {end}.",
    )
    for key in keys:
        assert key in data["en"], key
        assert key in data["ar"], key
        assert data["ar"][key] != key, key


def test_settings_hint_stylesheet_class_exists():
    from pathlib import Path

    qss = (Path(__file__).resolve().parent.parent / "assets" / "style.qss"
           ).read_text(encoding="utf-8")

    assert 'QLabel[class="settings-hint"]' in qss


class TestCustomListsStaging:
    """Settings > Custom Lists: edits are staged and only written by Save."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, tmp_path, monkeypatch):
        from src.utils.settings_manager import SettingsManager

        monkeypatch.setattr(
            "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
        )
        SettingsManager._cache = None
        yield
        SettingsManager._cache = None

    @pytest.fixture
    def list_page(self, fresh_db, tmp_path, monkeypatch):
        # Built after fresh_db so the page renders against the isolated DB;
        # modal boxes/input dialogs would crash the offscreen platform.
        for name in ("information", "warning", "critical"):
            monkeypatch.setattr(settings_page_module.QMessageBox, name,
                                staticmethod(lambda *a, **k: None))
        monkeypatch.setattr(
            settings_page_module.QMessageBox, "question",
            staticmethod(lambda *a, **k: settings_page_module.QMessageBox.Yes))

        widget = SettingsPage()
        widget.settings = QSettings(str(tmp_path / "palette.ini"), QSettings.IniFormat)
        # Custom Lists load lazily on first view; select the tab so the fixture
        # exercises the same path the user does.
        widget.tabs.setCurrentIndex(widget.tabs.indexOf(widget.inventory_tab))
        yield widget
        widget.deleteLater()

    @staticmethod
    def _items(list_widget):
        return [list_widget.item(i).text() for i in range(list_widget.count())]

    @staticmethod
    def _combo_items(combo):
        return [combo.itemText(i) for i in range(combo.count())]

    @staticmethod
    def _prompt(monkeypatch, answer, ok=True):
        monkeypatch.setattr(settings_page_module.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: (answer, ok)))

    @staticmethod
    def _select(page, text):
        matches = page.cat_list.findItems(text, Qt.MatchExactly)
        assert matches, "{0} is not listed".format(text)
        page.cat_list.setCurrentItem(matches[0])

    def test_add_is_staged_and_the_database_is_untouched(self, list_page, repos, monkeypatch):
        page = list_page
        self._prompt(monkeypatch, "Vaccines")
        page._stage_add_category()

        assert page._pending_list_ops == [("add_category", "Vaccines")]
        assert "Vaccines" in self._items(page.cat_list)
        assert "Vaccines" not in repos["supply"].get_all_categories()

    def test_save_writes_the_staged_category(self, list_page, repos, monkeypatch):
        page = list_page
        self._prompt(monkeypatch, "Vaccines")
        page._stage_add_category()

        page.save_settings()

        assert "Vaccines" in repos["supply"].get_all_categories()
        assert page._pending_list_ops == []

    def test_cancel_discards_the_staged_category(self, list_page, repos, monkeypatch):
        page = list_page
        self._prompt(monkeypatch, "Vaccines")
        page._stage_add_category()

        page.cancel_settings()

        assert "Vaccines" not in repos["supply"].get_all_categories()
        assert "Vaccines" not in self._items(page.cat_list)
        assert page._pending_list_ops == []

    def test_a_staged_edit_is_lost_when_the_page_is_reopened(self, list_page, repos, monkeypatch):
        page = list_page
        self._prompt(monkeypatch, "Vaccines")
        page._stage_add_category()
        page.deleteLater()

        reopened = SettingsPage()
        try:
            reopened.tabs.setCurrentIndex(
                reopened.tabs.indexOf(reopened.inventory_tab))
            assert "Vaccines" not in self._items(reopened.cat_list)
            assert "Vaccines" not in repos["supply"].get_all_categories()
        finally:
            reopened.deleteLater()

    def test_a_duplicate_category_is_not_staged(self, list_page, repos, monkeypatch):
        repos["supply"].add_category("Medicine")
        warnings = []
        monkeypatch.setattr(settings_page_module.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warnings.append(a[2])))
        self._prompt(monkeypatch, "Medicine")

        list_page._stage_add_category()

        assert list_page._pending_list_ops == []
        assert warnings and "already exists" in warnings[0]

    def test_deleting_a_category_only_lands_on_save(self, list_page, repos):
        page = list_page
        repos["supply"].add_category("Medicine")
        page._refresh_custom_lists()
        self._select(page, "Medicine")

        page._stage_delete_category()

        assert "Medicine" in repos["supply"].get_all_categories()
        assert "Medicine" not in self._items(page.cat_list)

        page.save_settings()
        assert "Medicine" not in repos["supply"].get_all_categories()

    def test_cancel_keeps_a_staged_delete_in_the_database(self, list_page, repos):
        page = list_page
        repos["supply"].add_category("Medicine")
        page._refresh_custom_lists()
        self._select(page, "Medicine")

        page._stage_delete_category()
        page.cancel_settings()

        assert "Medicine" in repos["supply"].get_all_categories()
        assert "Medicine" in self._items(page.cat_list)

    def test_subcategories_follow_the_same_staging_rules(self, list_page, repos, monkeypatch):
        page = list_page
        repos["supply"].add_category("Medicine")
        page._refresh_custom_lists()
        self._select(page, "Medicine")
        self._prompt(monkeypatch, "Antibiotics")

        page._stage_add_subcategory()

        assert ("add_subcategory", "Medicine", "Antibiotics") in page._pending_list_ops
        assert "Antibiotics" not in repos["supply"].get_subcategories_by_category("Medicine")

        page.save_settings()
        assert "Antibiotics" in repos["supply"].get_subcategories_by_category("Medicine")

    def test_species_follow_the_same_staging_rules(self, list_page, repos, monkeypatch):
        page = list_page
        self._prompt(monkeypatch, "Ferret")

        page._stage_add_clinic_item("species", "Species")
        assert "Ferret" in self._combo_items(page.spec_combo)
        assert "Ferret" not in repos["supply"].get_all_species()

        page.save_settings()
        assert "Ferret" in repos["supply"].get_all_species()

    def test_delete_confirmation_uses_its_own_title(self, list_page, repos, monkeypatch):
        page = list_page
        repos["supply"].add_category("Medicine")
        page._refresh_custom_lists()
        self._select(page, "Medicine")

        titles = []
        monkeypatch.setattr(
            settings_page_module.QMessageBox, "question",
            staticmethod(lambda *a, **k: titles.append(a[1]) or
                         settings_page_module.QMessageBox.Yes))
        page._stage_delete_category()

        assert titles == ["Delete Category"]

    def test_a_failed_list_write_is_reported(self, list_page, monkeypatch):
        page = list_page
        page._pending_list_ops.append(("add_category", "Vaccines"))
        monkeypatch.setattr(settings_page_module.supply_repo, "add_category",
                            staticmethod(lambda name: False))
        warnings = []
        monkeypatch.setattr(settings_page_module.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warnings.append(a[2])))

        page.save_settings()

        assert warnings and "Vaccines" in warnings[0]
        assert page._pending_list_ops == []

    def test_the_tab_says_edits_only_reach_the_database_on_save(self, list_page):
        page = list_page

        assert page.list_hint.text() == "Changes are applied when you click Save."

        page.retranslate_ui()
        assert page.list_hint.text() == "Changes are applied when you click Save."

    def test_a_category_with_items_refuses_the_delete(self, list_page, repos, entity_factory,
                                                      monkeypatch):
        page = list_page
        repos["supply"].add_category("Medicine")
        entity_factory["make_supply"](category="Medicine", sub="Antibiotics", name="Amoxil")
        page._refresh_custom_lists()
        self._select(page, "Medicine")

        warnings = []
        monkeypatch.setattr(settings_page_module.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warnings.append(a[2])))
        page._stage_delete_category()

        assert page._pending_list_ops == []
        assert "Medicine" in self._items(page.cat_list)
        assert warnings and "still has items" in warnings[0]

    def test_a_subcategory_with_items_refuses_the_delete(self, list_page, repos, entity_factory,
                                                         monkeypatch):
        page = list_page
        repos["supply"].add_category("Medicine")
        repos["supply"].add_subcategory("Medicine", "Antibiotics")
        entity_factory["make_supply"](category="Medicine", sub="Antibiotics", name="Amoxil")
        page._refresh_custom_lists()
        self._select(page, "Medicine")

        subs = page.sub_list.findItems("Antibiotics", Qt.MatchExactly)
        assert subs
        page.sub_list.setCurrentItem(subs[0])

        warnings = []
        monkeypatch.setattr(settings_page_module.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warnings.append(a[2])))
        page._stage_delete_subcategory()

        assert page._pending_list_ops == []
        assert "Antibiotics" in self._items(page.sub_list)
        assert warnings and "still has items" in warnings[0]

    def test_an_empty_subcategory_can_still_be_deleted(self, list_page, repos):
        page = list_page
        repos["supply"].add_category("Medicine")
        repos["supply"].add_subcategory("Medicine", "Antibiotics")
        page._refresh_custom_lists()
        self._select(page, "Medicine")
        page.sub_list.setCurrentItem(page.sub_list.findItems("Antibiotics", Qt.MatchExactly)[0])

        page._stage_delete_subcategory()
        page.save_settings()

        assert "Antibiotics" not in repos["supply"].get_subcategories_by_category("Medicine")

    def test_a_delete_that_gained_items_before_save_is_reported(self, list_page, repos,
                                                                entity_factory, monkeypatch):
        page = list_page
        repos["supply"].add_category("Medicine")
        page._refresh_custom_lists()
        page._pending_list_ops.append(("delete_category", "Medicine"))
        entity_factory["make_supply"](category="Medicine", sub="Antibiotics", name="Amoxil")

        warnings = []
        monkeypatch.setattr(settings_page_module.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: warnings.append(a[2])))
        page.save_settings()

        assert warnings and "Medicine" in warnings[0]
        assert "Medicine" in repos["supply"].get_all_categories()


class TestInstantApplyOnSave:
    """Saving applies window-mode/language changes without a restart."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, tmp_path, monkeypatch):
        from src.utils.settings_manager import SettingsManager

        monkeypatch.setattr(
            "src.utils.settings_manager.SETTINGS_FILE", tmp_path / "settings.json"
        )
        SettingsManager._cache = None
        yield
        SettingsManager._cache = None

    class _FakeMainWindow:
        def __init__(self):
            self.calls = []

        def update_window_title(self):
            self.calls.append("title")

        def apply_window_mode(self):
            self.calls.append("mode")

        def update_ui_language(self):
            self.calls.append("language")

    def _use_fake_window(self, page, monkeypatch):
        fake = self._FakeMainWindow()
        monkeypatch.setattr(page, "window", lambda fake=fake: fake)
        return fake

    def test_language_change_is_applied_immediately(self, page, monkeypatch):
        fake = self._use_fake_window(page, monkeypatch)
        page.language_combo.setCurrentIndex(page.language_combo.findData("ar"))

        page.apply_settings()

        assert "language" in fake.calls

    def test_window_mode_change_is_applied_immediately(self, page, monkeypatch):
        fake = self._use_fake_window(page, monkeypatch)
        page.window_mode_combo.setCurrentIndex(
            page.window_mode_combo.findData("Fullscreen")
        )

        page.apply_settings()

        assert "mode" in fake.calls

    def test_unchanged_settings_do_not_trigger_a_refresh(self, page, monkeypatch):
        fake = self._use_fake_window(page, monkeypatch)

        page.apply_settings()

        assert "title" in fake.calls
        assert "mode" not in fake.calls
        assert "language" not in fake.calls


def test_custom_lists_i18n_keys_exist_in_english_and_arabic():
    import json
    from pathlib import Path

    translations = Path(__file__).resolve().parent.parent / "assets" / "translations.json"
    data = json.loads(translations.read_text(encoding="utf-8"))

    keys = (
        "Changes are applied when you click Save.",
        "Some list changes could not be saved: {items}",
        "Settings saved successfully.",
        "New Category",
        "Category Name:",
        "Item already exists.",
        "Delete Category",
        "Delete category '{cat}'?",
        "New Sub-Category",
        "Sub-Category Name:",
        "Please select a category first.",
        "Delete Sub-Category",
        "Delete Sub-Category '{val}'?",
        "Delete Species",
        "Delete Service",
        "Delete {title} '{val}'?",
        "New {title}",
        "{title} Name:",
        "This category still has items. Please delete them or move them to another "
        "category before deleting this category.",
        "This sub-category still has items. Please delete them or move them to another "
        "sub-category before deleting this sub-category.",
    )
    for key in keys:
        assert key in data["en"], key
        assert key in data["ar"], key
        assert data["ar"][key] != key, key
