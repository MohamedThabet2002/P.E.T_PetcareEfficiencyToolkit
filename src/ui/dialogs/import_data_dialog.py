"""Import data dialog for the PET Application.

Opened from Settings -> Database Backup. Reads an Excel / CSV file, lets the
user pick which entity it holds (or, for a workbook, every data sheet at once),
previews the mapped columns, optionally creates a safety backup, then writes the
rows through :mod:`src.core.importer`.
"""

import logging
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)

from src.config.paths import BACKUPS_DIR
from src.core import importer
from src.core.backup_manager import create_backup
from src.core.database import get_user_db_path
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

#: Rows previewed before the grid is cut off. The cap only exists so a huge
#: sheet cannot lock the UI up, and the taller dialog fits a good part of it.
PREVIEW_MAX_ROWS = 100
FILE_FILTER = (
    "Excel / CSV (*.xlsx *.xlsm *.csv *.tsv *.txt);;"
    "Excel (*.xlsx *.xlsm);;"
    "CSV / Text (*.csv *.tsv *.txt);;"
    "All Files (*)"
)


class ImportDataDialog(QDialog):
    """Guided Excel / CSV import with a preview, a dry run and a safety backup."""

    data_changed = pyqtSignal(str)

    def __init__(self, parent=None, current_user=None):
        super().__init__(parent)
        self._current_user = current_user or {}

        self._table = None
        self._plan = None  # importer.WorkbookPlan, workbooks only
        self._loaded_path = ""
        self._all_sheets_touched = False
        self._all_sheets_available = False  # the workbook has importable sheets
        self._syncing_sheet = False  # guards sheet <-> type auto-selection
        self.last_summary = None

        self.setWindowTitle(tr("Import Data"))
        self.setMinimumSize(880, 620)
        self._setup_ui()

    # ------------------------------------------------------------------ UI --
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self._title = QLabel(tr("Import Data from Excel or CSV"))
        self._title.setProperty("class", "dialog-title")
        layout.addWidget(self._title)

        self._intro = QLabel(tr(
            "Pick a file, choose what it contains, then validate before importing. "
            "A workbook holding several data types is imported sheet by sheet. "
            "Existing records are skipped, not overwritten."
        ))
        self._intro.setProperty("class", "dialog-subtitle")
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        layout.addWidget(self._build_file_group())
        layout.addWidget(self._build_type_group())
        layout.addWidget(self._build_preview_group(), 1)

        layout.addLayout(self._build_footer())
        self._update_controls()

    def _build_file_group(self):
        self.file_group = QGroupBox(tr("1. Source File"))
        box = QVBoxLayout(self.file_group)

        row = QHBoxLayout()
        self.browse_btn = QPushButton(tr("Choose File..."))
        self.browse_btn.clicked.connect(self._browse_for_file)
        row.addWidget(self.browse_btn)

        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(tr("No file selected"))
        row.addWidget(self.path_edit, 1)

        self.sheet_label = QLabel(tr("Sheet:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setVisible(False)
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        row.addWidget(self.sheet_label)
        row.addWidget(self.sheet_combo)
        box.addLayout(row)

        self.all_sheets_check = QCheckBox(
            tr("Import every data sheet in this workbook"))
        self.all_sheets_check.setVisible(False)
        self.all_sheets_check.toggled.connect(self._on_all_sheets_toggled)
        box.addWidget(self.all_sheets_check)
        return self.file_group

    def _build_type_group(self):
        self.type_group = QGroupBox(tr("2. Data To Import"))
        row = QHBoxLayout(self.type_group)

        self.type_combo = QComboBox()
        for entity_key in importer.IMPORT_KEYS:
            self.type_combo.addItem(tr(importer.get_spec(entity_key).label_key), entity_key)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(self.type_combo, 1)
        return self.type_group

    def _build_preview_group(self):
        self.preview_group = QGroupBox(tr("3. Preview"))
        box = QVBoxLayout(self.preview_group)

        self.columns_label = QLabel("")
        self.columns_label.setWordWrap(True)
        box.addWidget(self.columns_label)

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        box.addWidget(self.preview_table, 1)

        self.backup_check = QCheckBox(tr("Create a safety backup before importing"))
        self.backup_check.setChecked(True)
        box.addWidget(self.backup_check)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        box.addWidget(self.status_label)
        return self.preview_group

    def _build_footer(self):
        row = QHBoxLayout()

        self.validate_btn = QPushButton(tr("Validate"))
        self.validate_btn.clicked.connect(self._on_validate)
        row.addWidget(self.validate_btn)

        self.import_btn = QPushButton(tr("Import"))
        self.import_btn.clicked.connect(self._on_import)
        row.addWidget(self.import_btn)

        row.addStretch()

        self.close_btn = QPushButton(tr("Close"))
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.close_btn)
        return row

    # -------------------------------------------------------------- Access --
    @property
    def entity_key(self):
        return self.type_combo.currentData()

    def _has_file(self):
        return self._table is not None

    def _is_instructions_only(self):
        """True when the selected sheet is the template's documentation sheet."""
        if self._table is None:
            return False
        return importer.is_instructions_sheet(self._table.sheet_name)

    def _missing_required(self):
        if not self._has_file():
            return []
        spec = importer.get_spec(self.entity_key)
        return importer.missing_required_columns(self._table.headers, spec)

    def _all_sheets_mode(self):
        """True when the whole workbook is imported instead of one sheet."""
        return self._all_sheets_available and self.all_sheets_check.isChecked()

    def _update_all_sheets_option(self):
        """Offers the all-sheets import when the workbook holds several sheets.

        Checked by default as soon as two sheets carry recognisable columns -
        that is exactly the shape of an export written by this app - but the
        user can turn it off and drive the sheet/type selectors by hand.
        """
        plan = self._plan
        recognized = len(plan.plans) if plan is not None else 0
        # State, not ``isVisible()``: a dialog that has not been shown yet must
        # still know the workbook holds several sheets.
        self._all_sheets_available = recognized >= 1
        self.all_sheets_check.setVisible(self._all_sheets_available)
        if self._all_sheets_touched:
            return
        self.all_sheets_check.blockSignals(True)  # an auto-switch is not a choice
        self.all_sheets_check.setChecked(recognized >= 2)
        self.all_sheets_check.blockSignals(False)

    def _on_all_sheets_toggled(self, _checked):
        self._all_sheets_touched = True
        self._refresh_preview()

    def _update_controls(self):
        all_sheets = self._all_sheets_mode()
        self.type_combo.setEnabled(not all_sheets)
        self.sheet_combo.setEnabled(not all_sheets)

        if all_sheets:
            ready = self._plan is not None and bool(self._plan.plans)
        else:
            ready = (self._has_file() and not self._missing_required()
                     and not self._is_instructions_only())
        # A workbook whose sheets carry no known columns is worth naming,
        # whichever mode the selectors ended up in.
        empty_workbook = self._plan is not None and not self._plan.plans
        self.validate_btn.setEnabled(ready and not empty_workbook)
        self.import_btn.setEnabled(ready and not empty_workbook)

        if empty_workbook:
            self.status_label.setText(tr(
                "This workbook has no sheet the app can import."
            ))
        elif all_sheets:
            self.status_label.setText(tr(
                "Every data sheet is imported at once: {sheets}."
            ).format(sheets=self._sheet_names_text()))
        elif self._is_instructions_only():
            self.status_label.setText(tr(
                "This sheet only explains how to fill the template in. "
                "Switch to the data sheet to import - nothing is read from here."
            ))
        elif not ready:
            self.status_label.setText(tr("Choose a file to begin."))
        else:
            self.status_label.setText("")

    def _sheet_names_text(self):
        """Readable list of the sheet names that will be imported."""
        return ", ".join(
            "{name} ({label})".format(
                name=plan.sheet_name,
                label=tr(importer.get_spec(plan.entity).label_key),
            )
            for plan in self._plan.plans
        )

    # --------------------------------------------------------------- File ---
    def _browse_for_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select File to Import"), "", FILE_FILTER
        )
        if path:
            self.load_file(path)

    def load_file(self, path, sheet=None):
        """Reads ``path`` into the preview. Returns ``True`` on success."""
        try:
            table = importer.read_table(path, sheet)
        except Exception as exc:
            logger.exception("Import: failed to read %s", path)
            self._table = None
            self._plan = None
            self._update_all_sheets_option()
            self._update_controls()
            QMessageBox.critical(
                self, tr("Import Data"),
                tr("Could not read the file.\n{error}").format(error=str(exc)),
            )
            return False

        if not table.headers:
            self._table = None
            self._plan = None
            self._update_all_sheets_option()
            self._update_controls()
            QMessageBox.warning(
                self, tr("Import Data"), tr("The file has no header row.")
            )
            return False

        self._table = table
        if str(path) != self._loaded_path:
            # A different file re-decides the default; picking another sheet of
            # the same workbook keeps whatever the user chose.
            self._loaded_path = str(path)
            self._all_sheets_touched = False
        self.path_edit.setText(str(path))
        self.path_edit.setToolTip(str(path))
        self._populate_sheets(path, table.sheet_name)
        self._plan = self._plan_workbook(path)
        self._update_all_sheets_option()
        self._autodetect_type()
        self._refresh_preview()
        return True

    def _plan_workbook(self, path):
        """Detects the data type of every sheet; ``None`` for text files."""
        if Path(path).suffix.lower() not in importer.EXCEL_EXTENSIONS:
            return None
        try:
            plan = importer.plan_workbook(path)
        except Exception:
            logger.exception("Import: failed to plan the sheets of %s", path)
            return None
        logger.info("Import: %s holds %s importable sheet(s) %s, ignoring %s",
                    path, len(plan.plans), plan.entities, plan.ignored)
        return plan

    def _populate_sheets(self, path, current_sheet):
        try:
            sheets = importer.list_sheets(path)
        except Exception:
            logger.exception("Import: failed to list sheets of %s", path)
            sheets = []

        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        if current_sheet:
            index = self.sheet_combo.findText(current_sheet)
            if index >= 0:
                self.sheet_combo.setCurrentIndex(index)
        self.sheet_combo.blockSignals(False)
        self.sheet_combo.setVisible(len(sheets) > 1)
        self.sheet_label.setVisible(len(sheets) > 1)

    def _on_sheet_changed(self, sheet_name):
        if not self.path_edit.text() or not sheet_name:
            return
        self.load_file(self.path_edit.text(), sheet_name)

    def _autodetect_type(self):
        detected = importer.detect_entity(self._table.headers)
        if detected is None:
            # A single-column sheet (e.g. Suppliers) can never reach the
            # two-column detection threshold, so fall back to its sheet name.
            detected = importer._entity_from_sheet_name(self._table.sheet_name)
        index = self.type_combo.findData(detected) if detected else -1
        if index >= 0 and self.type_combo.currentIndex() != index:
            self.type_combo.setCurrentIndex(index)  # triggers _refresh_preview
            return
        self._refresh_preview()

    # ------------------------------------------------------------ Preview ---
    def _on_type_changed(self, *_args):
        if not self._all_sheets_mode() and self._has_file():
            self._select_sheet_for_entity(self.entity_key)
        self._refresh_preview()

    def _select_sheet_for_entity(self, entity_key):
        """Points the sheet combo at the sheet that holds ``entity_key``.

        In single-sheet mode the type and sheet selectors describe the same
        thing, so switching one must carry the other - otherwise the required
        columns are checked against a sheet of a different type and the buttons
        stay disabled.
        """
        if self._syncing_sheet or not entity_key:
            return
        target = importer.entity_sheet_name(entity_key)
        index = self.sheet_combo.findText(target)
        if index < 0 or index == self.sheet_combo.currentIndex():
            return
        self._syncing_sheet = True
        try:
            self.sheet_combo.setCurrentIndex(index)  # loads that sheet
        finally:
            self._syncing_sheet = False

    def _refresh_preview(self):
        if self._all_sheets_mode():
            self._refresh_sheet_overview()
            return

        spec = importer.get_spec(self.entity_key)
        column_map = importer.match_columns(self._table.headers, spec)
        mapped = [name for name in spec.fields if column_map.get(name) is not None]
        missing = self._missing_required()

        self.columns_label.setText(
            tr("Required columns: {fields}").format(
                fields=", ".join(spec.field_label(name) for name in spec.required)
            )
        )
        if missing:
            self.columns_label.setText(self.columns_label.text() + "  " + tr(
                "Missing: {fields}"
            ).format(fields=", ".join(spec.field_label(name) for name in missing)))
        else:
            self.columns_label.setText(self.columns_label.text() + "  " + tr(
                "Matched columns: {count}/{total}"
            ).format(count=len(mapped), total=len(spec.fields)))

        rows = self._table.rows[:PREVIEW_MAX_ROWS]
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(mapped))
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setHorizontalHeaderLabels(
            [spec.field_label(name) for name in mapped]
        )

        for row_index, row in enumerate(rows):
            for col_index, field_name in enumerate(mapped):
                source_index = column_map[field_name]
                text = row[source_index] if source_index < len(row) else ""
                self.preview_table.setItem(
                    row_index, col_index, QTableWidgetItem(text)
                )

        self._update_controls()

    def _refresh_sheet_overview(self):
        """Lists the sheets of the workbook and the type each one will import as."""
        plan = self._plan
        self.columns_label.setText(tr(
            "Every data sheet is imported at once. Sheets are matched by their "
            "columns, so their names and order do not matter."
        ))
        if plan.ignored:
            self.columns_label.setText(self.columns_label.text() + "  " + tr(
                "Ignored sheets: {names}"
            ).format(names=", ".join(plan.ignored)))

        rows = [
            (sheet_plan.sheet_name,
             tr(importer.get_spec(sheet_plan.entity).label_key),
             str(sheet_plan.row_count))
            for sheet_plan in plan.plans
        ]

        self.preview_table.clear()
        self.preview_table.setColumnCount(3)
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setHorizontalHeaderLabels(
            [tr("Sheet"), tr("Data Type"), tr("Rows")]
        )
        for row_index, row in enumerate(rows):
            for col_index, text in enumerate(row):
                self.preview_table.setItem(row_index, col_index, QTableWidgetItem(text))

        self._update_controls()

    # ------------------------------------------------------------- Import ---
    def _planned_row_count(self):
        """Rows the current selection would hand to the importer."""
        if self._all_sheets_mode():
            return self._plan.row_count if self._plan is not None else 0
        return len(self._table.rows) if self._has_file() else 0

    def _run(self, dry_run):
        user_id = (self._current_user or {}).get("user_id")

        if self._all_sheets_mode():
            # One pass over the whole workbook; the sheets share the owner/pet
            # caches, so an owner added by one sheet is found by the next.
            summary = importer.import_workbook(self.path_edit.text(), user_id=user_id,
                                               dry_run=dry_run, plan=self._plan)
        else:
            summary = importer.import_table(
                self.entity_key,
                self._table.headers,
                self._table.rows,
                self._table.row_numbers,
                user_id=user_id,
                dry_run=dry_run,
            )

        self.last_summary = summary
        logger.info(
            "Import %s (%s): imported=%s skipped=%s failed=%s",
            "workbook" if self._all_sheets_mode()
            else importer.get_spec(self.entity_key).label_key,
            "validate" if dry_run else "commit",
            summary.imported, summary.skipped, summary.failed,
        )
        return summary

    def _on_validate(self):
        summary = self._run(dry_run=True)
        self.status_label.setText(
            tr("Validation: {ok} to add, {skip} already exist, {bad} invalid.").format(
                ok=summary.imported, skip=summary.skipped, bad=summary.failed
            )
        )
        if summary.problems():
            self._show_results(summary, tr("Validation Issues"))

    def _on_import(self):
        target = self._sheet_names_text() if self._all_sheets_mode() else tr(
            importer.get_spec(self.entity_key).label_key)
        reply = QMessageBox.question(
            self,
            tr("Import Data"),
            tr(
                "About to import {count} row(s) from {entity} into the database.\n\n"
                "Existing records are skipped. Continue?"
            ).format(count=self._planned_row_count(), entity=target),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        if self.backup_check.isChecked():
            if not self._create_safety_backup():
                return

        summary = self._run(dry_run=False)

        if self._all_sheets_mode():
            for entity_key in summary.entities:
                self.data_changed.emit(entity_key)
        elif summary.imported:
            self.data_changed.emit(self.entity_key)

        if summary.failed:
            self._show_results(summary, tr("Rows Not Imported"))
            QMessageBox.warning(
                self, tr("Import Data"),
                tr("Import finished with problems: {ok} added, {skip} skipped, {bad} failed.").format(
                    ok=summary.imported, skip=summary.skipped, bad=summary.failed
                ),
            )
            return

        QMessageBox.information(
            self, tr("Import Data"),
            tr("Import complete: {ok} added, {skip} skipped.").format(
                ok=summary.imported, skip=summary.skipped
            ),
        )
        self.accept()

    def _create_safety_backup(self):
        """Snapshots the database before writing. Returns False when it fails."""
        try:
            db_path = get_user_db_path()
            if not db_path.exists():
                logger.info("Import: database file missing, skipping safety backup")
                return True
            create_backup(db_path=db_path, backups_dir=BACKUPS_DIR, backup_kind="manual")
            return True
        except Exception as exc:
            logger.exception("Import: safety backup failed")
            QMessageBox.critical(
                self, tr("Import Data"),
                tr("Could not create a safety backup. Import cancelled.\n{error}").format(
                    error=str(exc)
                ),
            )
            return False

    def _show_results(self, summary, title):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning if summary.failed else QMessageBox.Information)
        box.setText(tr("{total} row(s): {ok} added, {skip} skipped, {bad} failed.").format(
            total=summary.total, ok=summary.imported, skip=summary.skipped,
            bad=summary.failed,
        ))
        # Workbook summaries are prefixed with their sheet, so the row numbers
        # of two sheets never look like the same row.
        box.setDetailedText(importer.result_details(summary))
        # Let the user drag the issue list bigger; a long import can report many
        # rows and the default detail box is cramped.
        box.setSizeGripEnabled(True)
        box.setMinimumSize(640, 420)
        details = box.findChild(QTextEdit)
        if details is not None:
            details.setMinimumHeight(240)
            details.setLineWrapMode(QTextEdit.NoWrap)
        box.exec_()

    # --------------------------------------------------------- Translation --
    def retranslate_ui(self):
        """Relabels the dialog when the language changes."""
        self.setWindowTitle(tr("Import Data"))
        self._title.setText(tr("Import Data from Excel or CSV"))
        self._intro.setText(tr(
            "Pick a file, choose what it contains, then validate before importing. "
            "A workbook holding several data types is imported sheet by sheet. "
            "Existing records are skipped, not overwritten."
        ))
        self.file_group.setTitle(tr("1. Source File"))
        self.browse_btn.setText(tr("Choose File..."))
        self.path_edit.setPlaceholderText(tr("No file selected"))
        self.sheet_label.setText(tr("Sheet:"))
        self.all_sheets_check.setText(tr("Import every data sheet in this workbook"))
        self.type_group.setTitle(tr("2. Data To Import"))
        self.preview_group.setTitle(tr("3. Preview"))
        self.backup_check.setText(tr("Create a safety backup before importing"))
        self.validate_btn.setText(tr("Validate"))
        self.import_btn.setText(tr("Import"))
        self.close_btn.setText(tr("Close"))

        current = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        for entity_key in importer.IMPORT_KEYS:
            self.type_combo.addItem(tr(importer.get_spec(entity_key).label_key), entity_key)
        index = self.type_combo.findData(current)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.type_combo.blockSignals(False)

        if self._has_file():
            self._refresh_preview()
        self._update_controls()