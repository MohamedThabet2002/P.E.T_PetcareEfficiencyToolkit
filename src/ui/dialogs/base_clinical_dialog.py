"""
Base Clinical Dialogs for the PET Application.

Provides the foundational UI components for clinical data entry:
- SupplyReceiptMixin: Reusable supply receipt UI across dialogs
- BaseClinicalDialog: Base class with split-form layout and supplies section

These components are used by AddVisitDialog and AddFullEntryDialog.
"""

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListView, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
    QVBoxLayout, QWidget, QFrame, QAbstractSpinBox
)
from PyQt5.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter

import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.package_repo as package_repo
import src.core.repositories.health_stats_repo as health_stats_repo
import src.core.repositories.test_repo as test_repo
import src.core.repositories.treatment_repo as treatment_repo
import src.core.repositories.vaccination_repo as vaccination_repo
import src.core.repositories.medication_repo as medication_repo
import src.core.repositories.lookup_repo as lookup_repo
from src.modules.receipt_card import build_receipt_card
from src.config.constants import DEFAULT_CONSULT_FEE
from src.utils.settings_manager import SettingsManager
from src.utils.i18n import tr


#==================================== CONSTANTS =======================================================#

NOTES_BOX_HEIGHT = 60
SUPPLIES_QUANTITY_MAX = 9999
DELETE_BUTTON_SIZE = (36, 36)
SUPPLY_COLUMN_WIDTHS = {
    "category": 110,
    "sub_category": 130,
    "item_name": 150,
    "quantity": 70,
    "price": 90
}

BASE_DIALOG_WIDTH = 960
BASE_DIALOG_HEIGHT = 680

# Lower bound so the compact two-column step pages can never be squeezed
# into an unreadable size by the user dragging the window. Deliberately well
# below the tallest step so _fit_dialog_height() can remove the dead band
# instead of being pinned at it.
BASE_DIALOG_MIN_WIDTH = 820
BASE_DIALOG_MIN_HEIGHT = 430

LEFT_CONTAINER_MIN_WIDTH = 320

# Compact rhythm for every wizard page / card form.
STEP_CONTENT_MARGIN = (6, 6, 6, 6)
STEP_CONTENT_SPACING = 12
CARD_CONTENT_MARGIN = (14, 10, 14, 14)
CARD_SPACING = 8
FORM_ROW_SPACING = 8
FORM_LABEL_SPACING = 10
# Spare height the height-fit leaves on top of the tallest step, so the wizard
# does not sit flush against its content. Small on purpose - enough to breathe,
# not enough to read as another band of dead space.
WIZARD_HEIGHT_BREATHING_ROOM = 32
# A label wider than this is capped (and allowed to wrap) so a large system
# font or a long translation cannot push a step into a horizontal scroll.
FORM_LABEL_MAX_WIDTH = 150
NAV_BUTTON_MIN_WIDTH = 112

SUPPLIES_RECEIPT_CONTAINER_MIN_WIDTH = 450
SUPPLIES_RECEIPT_CONTAINER_MAX_WIDTH = 650
# Vertical gap between item rows inside the SUPPLIES RECEIPT / SERVICE PACKAGES
# lists, and the padding each of those rows carries top and bottom. Both used to
# come from the style (6px gap + 2+2px padding = 10px of whitespace between two
# rows); together they are halved, so a list of rows reads as one tight block.
LIST_ROW_SPACING = 3
LIST_ROW_MARGIN = 1

# UI Symbols
DELETE_BUTTON_SYMBOL = "✕"

# Accordion header of a clinical section: the chevron swaps when it opens, so
# the collapsed state needs no words.
SECTION_CHEVRON_CLOSED = "›"
SECTION_CHEVRON_OPEN = "⌄"


def _count_layout_rows(layout):
    """Number of widget rows held by a layout (spacers and layouts ignored)."""
    if layout is None:
        return 0
    return sum(
        1 for index in range(layout.count())
        if layout.itemAt(index).widget() is not None
    )

# Clinical Section Constants
CLINICAL_SECTION_WIDTHS = {
    "stat_type": 180,
    "state": 150,
    "extra_note": 200,
    "test": 180,
    "treatment": 180,
    "vaccine": 180,
    "supply": 180,
    "dosage": 120,
    "instructions": 200,
}


class ClinicalSectionHeader(QWidget):
    """Clickable header of a clinical section: chevron, title, live summary.

    The owning card is a plain box (see the ``clinical-card`` QSS) with no
    title line of its own, so this row has room for the whole story: a chevron
    that flips on expand, the section name and a right-aligned summary. The
    summary keeps a *collapsed* section informative - "Tests - 2 selected"
    instead of a bare title - which is what makes the section list read as a
    record rather than five empty bars.
    """

    clicked = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setProperty("class", "clinical-card-header")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(8)

        self.chevron = QLabel(SECTION_CHEVRON_CLOSED)
        self.chevron.setProperty("class", "clinical-card-chevron")

        self.title_label = QLabel(tr(title))
        self.title_label.setProperty("class", "clinical-card-title")

        self.summary_label = QLabel()
        self.summary_label.setProperty("class", "clinical-card-summary")
        self.summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self.chevron)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.summary_label)

    def set_expanded(self, expanded):
        self.chevron.setText(SECTION_CHEVRON_OPEN if expanded else SECTION_CHEVRON_CLOSED)

    def set_summary(self, text):
        self.summary_label.setText(text)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ClinicalSectionCard(QGroupBox):
    """One collapsible clinical section, drawn as an accordion card.

    A plain checkable ``QGroupBox`` cannot carry this design: while it is
    unticked Qt *force-disables* every child, so a header drawn inside it is
    painted as nothing at all - which is what left the collapsed sections
    reading as empty grey bars with no title. This subclass therefore stays
    non-checkable and tracks the expanded state itself, keeping the
    ``setChecked`` / ``isChecked`` / ``toggled`` API its callers and tests
    already use.

    Children:

    - ``_section_header`` - the clickable chevron/title/summary row.
    - ``_section_content`` - the rows, hidden (and disabled) while collapsed so
      a closed card is exactly one line tall.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setProperty("class", "clinical-card")
        self._expanded = False

        header = ClinicalSectionHeader(title, self)
        header.clicked.connect(self.toggle)

        content = QWidget(self)
        content.setProperty("class", "clinical-card-content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 0, 12, 10)
        content_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(content)

        # Remembered by name because the callers (and their tests) reach for
        # these directly.
        self._section_header = header
        self._section_content = content
        self.content_layout = content_layout

        self.set_expanded(False)

    def isChecked(self):
        return self._expanded

    def setChecked(self, checked):
        checked = bool(checked)
        if checked == self._expanded:
            return
        self._expanded = checked
        self.set_expanded(checked)
        self.toggled.emit(checked)

    def toggle(self):
        self.setChecked(not self._expanded)

    def set_expanded(self, expanded):
        """Applies the collapsed/expanded look without emitting ``toggled``."""
        self._section_content.setVisible(expanded)
        self._section_content.setEnabled(expanded)
        self._section_header.set_expanded(expanded)


class ClinicalSectionsMixin:
    """Mixin to provide collapsible clinical data entry sections.

    Adds sections for:
    - Health Stats (stat_type + state + note)
    - Tests (multi-select from tests_lookup)
    - Treatments (multi-select from treatments_lookup)
    - Vaccinations (multi-select from vaccines_lookup)
    - Medications (supply + dosage + instructions rows)
    """

    def _collapsible_group(self, title, parent_layout):
        """Creates a collapsed-by-default accordion section that really collapses.

        Hiding the rows while collapsed (rather than only disabling them) keeps
        a closed section exactly one line tall, which is what a collapsed
        section should look like.

        Returns:
            tuple[ClinicalSectionCard, QVBoxLayout]: the card and the layout
            its content must be added to.
        """
        card = ClinicalSectionCard(title)
        parent_layout.addWidget(card)
        return card, card.content_layout

    def _refresh_section_summaries(self):
        """Writes the right-hand count on every section header.

        Called after any row is added/removed and on every checkbox toggle, so a
        collapsed section always says what it holds.
        """
        rows = {
            "health_stats_group": _count_layout_rows(getattr(self, "hs_layout", None)),
            "medications_group": _count_layout_rows(getattr(self, "med_layout", None)),
        }
        checked = {
            "tests_group": sum(1 for cb in getattr(self, "_test_checkboxes", []) if cb.isChecked()),
            "treatments_group": sum(1 for cb in getattr(self, "_treatment_checkboxes", []) if cb.isChecked()),
            "vaccinations_group": sum(1 for cb in getattr(self, "_vaccination_checkboxes", []) if cb.isChecked()),
        }
        keys = {
            "health_stats_group": "{count} recorded",
            "medications_group": "{count} prescribed",
            "tests_group": "{count} selected",
            "treatments_group": "{count} selected",
            "vaccinations_group": "{count} selected",
        }
        for name, key in keys.items():
            group = getattr(self, name, None)
            if group is None:
                continue
            count = rows.get(name, checked.get(name, 0))
            group._section_header.set_summary(
                tr(key).format(count=count) if count else tr("None")
            )

    def _setup_clinical_sections(self, parent_layout):
        """Creates collapsible clinical sections in the left form area."""
        self._health_stat_rows = []
        self._test_checkboxes = []
        self._treatment_checkboxes = []
        self._vaccination_checkboxes = []
        self._medication_rows = []

        # Health Stats Section
        self.health_stats_group, hs_layout = self._collapsible_group(
            "Health Stats", parent_layout
        )

        hs_add_btn = QPushButton(tr("+ Add Health Stat"))
        hs_add_btn.clicked.connect(self._add_health_stat_row)
        hs_layout.addWidget(hs_add_btn)

        self.hs_scroll = QScrollArea()
        self.hs_scroll.setWidgetResizable(True)
        self.hs_widget = QWidget()
        self.hs_layout = QVBoxLayout(self.hs_widget)
        self.hs_layout.setAlignment(Qt.AlignTop)
        self.hs_scroll.setWidget(self.hs_widget)
        self.hs_scroll.setMaximumHeight(160)
        hs_layout.addWidget(self.hs_scroll)

        # Tests Section
        self.tests_group, tests_layout = self._collapsible_group(
            "Tests", parent_layout
        )
        self._populate_test_checkboxes(tests_layout)

        # Treatments Section
        self.treatments_group, treatments_layout = self._collapsible_group(
            "Treatments", parent_layout
        )
        self._populate_treatment_checkboxes(treatments_layout)

        # Vaccinations Section
        self.vaccinations_group, vaccinations_layout = self._collapsible_group(
            "Vaccinations", parent_layout
        )
        self._populate_vaccination_checkboxes(vaccinations_layout)

        # Medications Section
        self.medications_group, med_layout = self._collapsible_group(
            "Medications", parent_layout
        )

        med_add_btn = QPushButton(tr("+ Add Medication"))
        med_add_btn.clicked.connect(self._add_medication_row)
        med_layout.addWidget(med_add_btn)

        self.med_scroll = QScrollArea()
        self.med_scroll.setWidgetResizable(True)
        self.med_widget = QWidget()
        self.med_layout = QVBoxLayout(self.med_widget)
        self.med_layout.setAlignment(Qt.AlignTop)
        self.med_scroll.setWidget(self.med_widget)
        self.med_scroll.setMaximumHeight(160)
        med_layout.addWidget(self.med_scroll)

        # Every section starts out empty, so their headers open on "None"
        self._refresh_section_summaries()

    def _add_health_stat_row(self):
        """Adds a health stat row with stat_type, state, and note fields."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)

        stat_type = QComboBox()
        stat_type.setFixedWidth(CLINICAL_SECTION_WIDTHS["stat_type"])
        # Populate stat types from the lookup repository
        for stat_type_id, stat_name in lookup_repo.get_stat_types():
            stat_type.addItem(stat_name, stat_type_id)

        state = QComboBox()
        state.setFixedWidth(CLINICAL_SECTION_WIDTHS["state"])
        # Populate states from states_lookup (category_id=1 for health states)
        for state_id, state_value in lookup_repo.get_states(category_id=1):
            state.addItem(state_value, state_id)

        note = QLineEdit()
        note.setPlaceholderText(tr("Extra note..."))
        note.setFixedWidth(CLINICAL_SECTION_WIDTHS["extra_note"])

        del_btn = QPushButton(DELETE_BUTTON_SYMBOL)
        del_btn.setFixedSize(*DELETE_BUTTON_SIZE)
        del_btn.setProperty("action", "delete")

        def remove_row():
            self.hs_layout.removeWidget(row_widget)
            row_widget.deleteLater()
            self._refresh_section_summaries()

        del_btn.clicked.connect(remove_row)

        row_layout.addWidget(stat_type)
        row_layout.addWidget(state)
        row_layout.addWidget(note)
        row_layout.addWidget(del_btn)
        self.hs_layout.addWidget(row_widget)
        self._refresh_section_summaries()

    def _populate_test_checkboxes(self, layout):
        """Populates test checkboxes from tests_lookup."""
        tests = test_repo.get_all_tests()
        for test in tests:
            cb = QCheckBox(test["test_name"])
            cb.test_id = test["test_id"]
            cb.toggled.connect(self._refresh_section_summaries)
            self._test_checkboxes.append(cb)
            layout.addWidget(cb)

    def _populate_treatment_checkboxes(self, layout):
        """Populates treatment checkboxes from treatments_lookup."""
        treatments = treatment_repo.get_all_treatments()
        for treatment in treatments:
            cb = QCheckBox(treatment["treatment_name"])
            cb.treatment_id = treatment["treatment_id"]
            cb.toggled.connect(self._refresh_section_summaries)
            self._treatment_checkboxes.append(cb)
            layout.addWidget(cb)

    def _populate_vaccination_checkboxes(self, layout):
        """Populates vaccination checkboxes from vaccines_lookup."""
        vaccines = vaccination_repo.get_all_vaccines()
        for vaccine in vaccines:
            cb = QCheckBox(vaccine["vaccine_name"])
            cb.vaccine_id = vaccine["vaccine_id"]
            cb.toggled.connect(self._refresh_section_summaries)
            self._vaccination_checkboxes.append(cb)
            layout.addWidget(cb)

    def _add_medication_row(self):
        """Adds a medication row with supply selector, dosage, and instructions."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)

        supply = QComboBox()
        supply.setFixedWidth(CLINICAL_SECTION_WIDTHS["supply"])
        # Populate supplies that can be used as medications
        for s in supply_repo.search_supplies():
            supply.addItem(str(s.get("item_name") or ""), s.get("supply_id"))

        dosage = QLineEdit()
        dosage.setPlaceholderText(tr("Dosage (e.g. 5mg)"))
        dosage.setFixedWidth(CLINICAL_SECTION_WIDTHS["dosage"])

        instructions = QLineEdit()
        instructions.setPlaceholderText(tr("Instructions..."))
        instructions.setFixedWidth(CLINICAL_SECTION_WIDTHS["instructions"])

        del_btn = QPushButton(DELETE_BUTTON_SYMBOL)
        del_btn.setFixedSize(*DELETE_BUTTON_SIZE)
        del_btn.setProperty("action", "delete")

        def remove_row():
            self.med_layout.removeWidget(row_widget)
            row_widget.deleteLater()
            self._refresh_section_summaries()

        del_btn.clicked.connect(remove_row)

        row_layout.addWidget(supply)
        row_layout.addWidget(dosage)
        row_layout.addWidget(instructions)
        row_layout.addWidget(del_btn)
        self.med_layout.addWidget(row_widget)
        self._refresh_section_summaries()

    def get_clinical_data(self):
        """Collects all clinical data from the sections.

        Returns:
            dict: With keys health_stats, tests, treatments, vaccinations, medications
        """
        data = {
            "health_stats": [],
            "tests": [],
            "treatments": [],
            "vaccinations": [],
            "medications": [],
        }

        # Collect health stats
        if self.health_stats_group.isChecked():
            for i in range(self.hs_layout.count()):
                item = self.hs_layout.itemAt(i)
                if item and item.widget():
                    row = item.widget()
                    combos = row.findChildren(QComboBox)
                    if len(combos) >= 2:
                        stat_type_id = combos[0].currentData()
                        state_id = combos[1].currentData()
                        note_edit = row.findChildren(QLineEdit)
                        extra_note = note_edit[0].text() if note_edit else ""
                        if stat_type_id:
                            data["health_stats"].append({
                                "stat_type_id": stat_type_id,
                                "state_id": state_id,
                                "extra_note": extra_note,
                            })

        # Collect tests
        if self.tests_group.isChecked():
            for cb in self._test_checkboxes:
                if cb.isChecked():
                    data["tests"].append({"test_id": cb.test_id})

        # Collect treatments
        if self.treatments_group.isChecked():
            for cb in self._treatment_checkboxes:
                if cb.isChecked():
                    data["treatments"].append(cb.treatment_id)

        # Collect vaccinations
        if self.vaccinations_group.isChecked():
            for cb in self._vaccination_checkboxes:
                if cb.isChecked():
                    data["vaccinations"].append(cb.vaccine_id)

        # Collect medications
        if self.medications_group.isChecked():
            for i in range(self.med_layout.count()):
                item = self.med_layout.itemAt(i)
                if item and item.widget():
                    row = item.widget()
                    combos = row.findChildren(QComboBox)
                    edits = row.findChildren(QLineEdit)
                    if combos:
                        supply_id = combos[0].currentData()
                        dosage = edits[0].text() if len(edits) > 0 else ""
                        instructions = edits[1].text() if len(edits) > 1 else ""
                        if supply_id:
                            data["medications"].append({
                                "supply_id": supply_id,
                                "dosage": dosage,
                                "instructions": instructions,
                            })

        return data


class SupplyReceiptMixin:
    """Mixin to provide consistent Supply Receipt UI across dialogs."""

    def _setup_supplies_section(self, parent_layout, stretch=3, min_width=None):
        """Creates the supply receipt section with add/remove rows and auto-price.

        Args:
            parent_layout: Layout the section is added to.
            stretch: Stretch factor in ``parent_layout``.
            min_width: Overrides the default minimum width (used when the
                section shares a row with another section).
        """
        self._supply_rows = []
        container = QWidget()
        container.setMinimumWidth(
            SUPPLIES_RECEIPT_CONTAINER_MIN_WIDTH if min_width is None else min_width
        )
        layout = QVBoxLayout(container)
        layout.setSpacing(6)

        # Store reference to the header for potential retranslation
        self.supplies_header_label = self._section_heading(tr("SUPPLIES RECEIPT"))
        layout.addWidget(self.supplies_header_label)

        self.add_item_btn = QPushButton(tr("+ Add Supply Item"))
        layout.addWidget(self.add_item_btn)

        # Column Headers Frame
        self.headers_frame = QFrame()
        h_layout = QHBoxLayout(self.headers_frame)
        h_layout.setContentsMargins(0, 5, 0, 5)
        h_layout.setSpacing(5)

        for text, width in [
            ("Category", SUPPLY_COLUMN_WIDTHS["category"]),
            ("Sub-Category", SUPPLY_COLUMN_WIDTHS["sub_category"]),
            ("Item Name", SUPPLY_COLUMN_WIDTHS["item_name"]),
            ("Quantity", SUPPLY_COLUMN_WIDTHS["quantity"]),
            ("Price", SUPPLY_COLUMN_WIDTHS["price"])
        ]:
            lbl = QLabel(f"<b>{tr(text)}</b>")
            lbl.setFixedWidth(width)
            lbl.setAlignment(Qt.AlignCenter)
            h_layout.addWidget(lbl)

        # Pins the delete column to the trailing edge of the section
        h_layout.addStretch(0)
        layout.addWidget(self.headers_frame)

        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_widget = QWidget()
        self.items_layout = QVBoxLayout(self.items_widget)
        self.items_layout.setAlignment(Qt.AlignTop)
        self.items_layout.setSpacing(LIST_ROW_SPACING)
        self.items_scroll.setWidget(self.items_widget)
        layout.addWidget(self.items_scroll)

        # Connections
        self.add_item_btn.clicked.connect(self._add_supply_row)

        parent_layout.addWidget(container, stretch)

    def _section_heading(self, text):
        """Builds a section heading label shared by the supplies/packages lists."""
        label = QLabel(text)
        label.setProperty("class", "form-card-title")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return label

    def _add_supply_row(self):
        """Adds a single supply item row with cascading category/subcategory/item combos."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, LIST_ROW_MARGIN, 0, LIST_ROW_MARGIN)
        row_layout.setSpacing(5)

        cat = QComboBox()
        cat.setView(QListView())
        cat.view().window().setAttribute(Qt.WA_TranslucentBackground)
        cat.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        cat.setEditable(True)
        cat.setInsertPolicy(QComboBox.NoInsert)
        cat.completer().setFilterMode(Qt.MatchContains)
        cat.addItems(supply_repo.get_all_categories())
        cat.setFixedWidth(SUPPLY_COLUMN_WIDTHS["category"])

        sub = QComboBox()
        sub.setView(QListView())
        sub.view().window().setAttribute(Qt.WA_TranslucentBackground)
        sub.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        sub.setFixedWidth(SUPPLY_COLUMN_WIDTHS["sub_category"])
        sub.setEditable(True)
        sub.setInsertPolicy(QComboBox.NoInsert)
        sub.completer().setFilterMode(Qt.MatchContains)

        item = QComboBox()
        item.setView(QListView())
        item.view().window().setAttribute(Qt.WA_TranslucentBackground)
        item.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        item.setEditable(True)
        item.setInsertPolicy(QComboBox.NoInsert)
        item.completer().setFilterMode(Qt.MatchContains)
        item.setFixedWidth(SUPPLY_COLUMN_WIDTHS["item_name"])

        qty = QSpinBox()
        qty.setRange(1, SUPPLIES_QUANTITY_MAX)
        qty.setFixedWidth(SUPPLY_COLUMN_WIDTHS["quantity"])

        price = QDoubleSpinBox()
        price.setRange(0.0, 99999.99)
        price.setSuffix(" $")
        price.setFixedWidth(SUPPLY_COLUMN_WIDTHS["price"])
        price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        price.setReadOnly(True)  # price is managed from the supplies page only

        del_b = QPushButton(DELETE_BUTTON_SYMBOL)
        del_b.setFixedSize(*DELETE_BUTTON_SIZE)
        del_b.setProperty("action", "delete")

        row_entry = (cat, item, qty, price)

        def remove_row():
            """Removes this row from the supply list."""
            if row_entry in self._supply_rows:
                self._supply_rows.remove(row_entry)
            self.items_layout.removeWidget(row_widget)
            row_widget.deleteLater()
            self._update_total()

        del_b.clicked.connect(remove_row)

        # Cascading dropdown logic
        def update_items():
            """Updates item list when category or subcategory changes."""
            item.clear()
            item.addItems(supply_repo.get_items_by_subcategory(cat.currentText(), sub.currentText()))
            update_price()
            self._update_total()

        def update_price():
            """Auto-fills price when an item is selected."""
            name = item.currentText()
            category = cat.currentText()
            if name:
                sell_price = supply_repo.get_sell_price(name, category)
                if sell_price is not None:
                    price.setValue(sell_price)
            else:
                price.setValue(0.0)

        def update_subs():
            """Updates subcategory list when category changes."""
            sub.clear()
            sub.addItems(supply_repo.get_subcategories_by_category(cat.currentText()))
            update_items()

        cat.currentTextChanged.connect(update_subs)
        sub.currentTextChanged.connect(update_items)
        item.currentIndexChanged.connect(update_price)

        qty.valueChanged.connect(self._update_total)
        price.valueChanged.connect(self._update_total)

        # Initialize values
        update_subs()
        for w in [cat, sub, item, qty, price]:
            row_layout.addWidget(w)
        # Push the delete button to the trailing edge, matching the headers
        row_layout.addStretch(0)
        row_layout.addWidget(del_b)
        self.items_layout.addWidget(row_widget)
        self._supply_rows.append(row_entry)
        self._update_total()

    def get_final_items(self):
        """Extracts selected supply items for database processing.

        Returns:
            list[dict]: Each dict has keys: category, item_name, quantity, price.
        """
        final_items = []
        for c, i, q, p in self._supply_rows:
            if i.currentText():
                final_items.append({
                    "category": c.currentText(),
                    "item_name": i.currentText(),
                    "quantity": q.value(),
                    "price": p.value()
                })
        return final_items

    # ── Package section ──────────────────────────────────────────────────────

    def _setup_packages_section(self, parent_layout, stretch=0, min_width=None):
        """Creates a package selection section below the supplies section.

        ``stretch`` lets a dialog share the spare height with the supplies
        section (pass a non-zero value where both lists should grow together).
        ``min_width`` overrides the default minimum width for side-by-side use.
        """
        self._package_rows = []

        container = QWidget()
        container.setMinimumWidth(
            SUPPLIES_RECEIPT_CONTAINER_MIN_WIDTH if min_width is None else min_width
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, STEP_CONTENT_SPACING, 0, 0)
        layout.setSpacing(6)

        self.packages_header_label = self._section_heading(tr("SERVICE PACKAGES"))
        layout.addWidget(self.packages_header_label)

        self.add_package_btn = QPushButton(tr("+ Add Package"))
        layout.addWidget(self.add_package_btn)

        # Column headers
        pkg_headers_frame = QFrame()
        ph_layout = QHBoxLayout(pkg_headers_frame)
        ph_layout.setContentsMargins(0, 5, 0, 5)
        ph_layout.setSpacing(5)
        for text, width in [
            (tr("Package Name"), 260),
            (tr("Quantity"),     70),
            (tr("Price"),        90),
        ]:
            lbl = QLabel(f"<b>{text}</b>")
            lbl.setFixedWidth(width)
            lbl.setAlignment(Qt.AlignCenter)
            ph_layout.addWidget(lbl)
        # Pins the delete column to the trailing edge, matching the rows
        ph_layout.addStretch(0)
        layout.addWidget(pkg_headers_frame)

        self.pkg_items_scroll = QScrollArea()
        self.pkg_items_scroll.setWidgetResizable(True)
        self.pkg_items_widget = QWidget()
        self.pkg_items_layout = QVBoxLayout(self.pkg_items_widget)
        self.pkg_items_layout.setAlignment(Qt.AlignTop)
        self.pkg_items_layout.setSpacing(LIST_ROW_SPACING)
        self.pkg_items_scroll.setWidget(self.pkg_items_widget)
        self.pkg_items_scroll.setMaximumHeight(160)
        layout.addWidget(self.pkg_items_scroll)

        self.add_package_btn.clicked.connect(self._add_package_row)

        parent_layout.addWidget(container, stretch)

    def _add_package_row(self):
        """Adds a package selection row (combo + qty + read-only price + delete)."""
        all_packages = package_repo.get_all_packages()
        if not all_packages:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                tr("No Packages"),
                tr("No service packages have been created yet. Add some in the Supplies page."),
            )
            return

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, LIST_ROW_MARGIN, 0, LIST_ROW_MARGIN)
        row_layout.setSpacing(5)

        pkg_combo = QComboBox()
        pkg_combo.setView(QListView())
        pkg_combo.view().window().setAttribute(Qt.WA_TranslucentBackground)
        pkg_combo.view().window().setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        pkg_combo.setFixedWidth(260)
        for pkg in all_packages:
            pkg_combo.addItem(pkg["package_name"], pkg)

        qty_spin = QSpinBox()
        qty_spin.setRange(1, 99)
        qty_spin.setFixedWidth(70)

        price_spin = QDoubleSpinBox()
        price_spin.setRange(0.0, 999999.99)
        price_spin.setSuffix(" $")
        price_spin.setFixedWidth(90)
        price_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        price_spin.setReadOnly(True)

        def _refresh_price():
            pkg_data = pkg_combo.currentData()
            if pkg_data:
                price_spin.setValue(float(pkg_data.get("total_price") or 0.0))
            else:
                price_spin.setValue(0.0)
            self._update_total()

        pkg_combo.currentIndexChanged.connect(_refresh_price)
        qty_spin.valueChanged.connect(self._update_total)
        _refresh_price()

        del_b = QPushButton(DELETE_BUTTON_SYMBOL)
        del_b.setFixedSize(*DELETE_BUTTON_SIZE)
        del_b.setProperty("action", "delete")

        row_entry = (pkg_combo, qty_spin, price_spin)

        def remove_row():
            if row_entry in self._package_rows:
                self._package_rows.remove(row_entry)
            self.pkg_items_layout.removeWidget(row_widget)
            row_widget.deleteLater()
            self._update_total()

        del_b.clicked.connect(remove_row)

        for w in [pkg_combo, qty_spin, price_spin]:
            row_layout.addWidget(w)
        # Push the delete button to the trailing edge, matching the headers
        row_layout.addStretch(0)
        row_layout.addWidget(del_b)

        self.pkg_items_layout.addWidget(row_widget)
        self._package_rows.append(row_entry)
        self._update_total()

    def get_final_packages(self):
        """Extracts selected packages for database processing.

        Returns:
            list[dict]: Each dict has keys: package_id, package_name, total_price, quantity.
        """
        result = []
        if not hasattr(self, '_package_rows'):
            return result
        for pkg_combo, qty_spin, price_spin in self._package_rows:
            pkg_data = pkg_combo.currentData()
            if pkg_data:
                result.append({
                    "package_id":   pkg_data["package_id"],
                    "package_name": pkg_data["package_name"],
                    "total_price":  float(pkg_data.get("total_price") or 0.0),
                    "quantity":     qty_spin.value(),
                })
        return result


class BaseClinicalDialog(QDialog, SupplyReceiptMixin):
    """Base class for clinical data-entry (add visit) dialogs.

    Provides a professional stepper layout:
    - a step indicator strip at the top,
    - one scrollable step page at a time (QStackedWidget),
    - Back / Next / Save navigation in the footer,
    - a printable receipt preview (see _setup_receipt) on the last step.
    """

    def __init__(self, title, size=(BASE_DIALOG_WIDTH, BASE_DIALOG_HEIGHT), parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self._design_size = size
        self._design_height = size[1]
        # _fit_dialog_height never sizes the dialog below this. The default is
        # the hard minimum; a wizard whose step content stretches to fill the
        # page (see AddFullEntryDialog) raises it to its design height instead,
        # because there is then no dead band left to shrink away.
        self._fit_floor = BASE_DIALOG_MIN_HEIGHT
        self.setMinimumSize(BASE_DIALOG_MIN_WIDTH, BASE_DIALOG_MIN_HEIGHT)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 14, 16, 14)
        self.main_layout.setSpacing(10)

        # Step indicator strip (populated by _start_wizard)
        self.step_indicator_row = QFrame()
        self.step_indicator_row.setObjectName("wizardStepper")
        self.step_indicator_row.setVisible(False)
        self.step_indicator_layout = QHBoxLayout(self.step_indicator_row)
        self.step_indicator_layout.setContentsMargins(12, 7, 12, 7)
        self.step_indicator_layout.setSpacing(6)
        self.main_layout.addWidget(self.step_indicator_row)

        # Scrollable area holding the stacked wizard pages
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setMinimumWidth(LEFT_CONTAINER_MIN_WIDTH)

        self._steps_widget = QStackedWidget()
        self.left_scroll.setWidget(self._steps_widget)

        self.content_layout = QHBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addWidget(self.left_scroll, 2)
        self.main_layout.addLayout(self.content_layout)

        # Hairline that separates the working area from the action footer
        self.footer_divider = QFrame()
        self.footer_divider.setObjectName("dialogFooterDivider")
        self.footer_divider.setFixedHeight(1)
        self.main_layout.addWidget(self.footer_divider)

        # Footer: wizard navigation (right-aligned)
        self.footer_layout = QHBoxLayout()
        self.footer_layout.setContentsMargins(2, 2, 2, 0)
        self.footer_layout.setSpacing(8)
        self.footer_layout.addStretch()

        self.back_button = QPushButton(tr("Back"))
        self.cancel_button = QPushButton(tr("Cancel"))
        self.next_button = QPushButton(tr("Next"))
        self.save_button = QPushButton(tr("Save Visit"))
        self.save_button.setProperty("class", "primary-action")
        for btn in (self.back_button, self.cancel_button, self.next_button, self.save_button):
            btn.setMinimumWidth(NAV_BUTTON_MIN_WIDTH)
        self.back_button.clicked.connect(self._go_previous_step)
        self.cancel_button.clicked.connect(self.reject)
        self.next_button.clicked.connect(self._go_next_step)
        self.save_button.clicked.connect(self.handle_accept)

        self.footer_layout.addWidget(self.back_button)
        self.footer_layout.addWidget(self.cancel_button)
        self.footer_layout.addWidget(self.next_button)
        self.footer_layout.addWidget(self.save_button)
        self.main_layout.addLayout(self.footer_layout)

        # Wizard state (filled by _start_wizard)
        self.step_forms = []
        self.step_bodies = []
        self._step_labels = []
        self._step_badges = []
        self._step_items = []
        self._step_index_by_item = {}
        self.step_counter_label = None
        self._wizard_titles = []
        self._current_step = 0
        self._max_step = 0
        self.form = None
        self.body = None

    def _pad_step_pages(self):
        """Pushes each step's spare height to the bottom of its page.

        Without this the leftover height is handed to the content boxes, so the
        supplies list, the receipt card and the form cards all stretch to fill
        the viewport and end up as tall mostly-empty boxes. The stretch is added
        last, so a step that *wants* the room (the supplies list, added with a
        stretch factor) still absorbs it first.
        """
        if getattr(self, "_step_pages_padded", False):
            return
        self._step_pages_padded = True
        for body in self.step_bodies:
            body.addStretch(1)

    def _tallest_page_hint(self):
        """Height needed by the step whose natural content is tallest."""
        tallest = 0
        for index in range(self._steps_widget.count()):
            page = self._steps_widget.widget(index)
            if page.layout() is not None:
                page.layout().activate()
            tallest = max(tallest, page.sizeHint().height())
        return tallest

    def _fit_dialog_height(self):
        """Sizes the dialog to its tallest step instead of a fixed height.

        Keeping a hard 640px while the tallest step needs ~380px is what left a
        band of dead space under the content. The dialog now sizes itself to the
        tallest step plus the measured chrome plus
        ``WIZARD_HEIGHT_BREATHING_ROOM``, clamped between ``_fit_floor`` and the
        design height, so it is still impossible to drag it into an unreadable
        size - and a dialog that raises its floor to the design height simply
        keeps that height while its content stretches into it.
        """
        if self._steps_widget is None:
            return
        stepper = self.step_indicator_row.sizeHint().height()
        footer = max(
            btn.sizeHint().height()
            for btn in (self.back_button, self.cancel_button,
                        self.next_button, self.save_button)
        )
        # main_layout holds stepper / content / divider / footer = 4 items
        layout = self.main_layout
        margins = layout.contentsMargins()
        chrome = (margins.top() + margins.bottom() + footer +
                  self.footer_divider.height() + stepper +
                  layout.spacing() * (layout.count() - 1))
        content = self._tallest_page_hint()
        self._fitted_content_height = content
        self._fitted_chrome_height = chrome
        # Clamped against the design height, not the current one: the pre-show
        # estimate is allowed to come up short, and the showEvent re-fit must be
        # able to grow the dialog back to what the tallest step needs.
        target = max(self._fit_floor,
                     min(content + chrome + WIZARD_HEIGHT_BREATHING_ROOM,
                         self._design_height))
        self._fitted_height = target
        if target != self.height():
            self.resize(self.width(), target)

    def _configure_form_layout(self, form):
        """Applies the compact row rhythm shared by every field form."""
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(FORM_LABEL_SPACING)
        form.setVerticalSpacing(FORM_ROW_SPACING)
        return form

    def _cap_form_labels(self, form):
        """Caps over-wide field labels so the form never outgrows its page.

        Call once after a form's rows are in place. Labels narrower than
        FORM_LABEL_MAX_WIDTH keep their natural width; wider ones are capped and
        allowed to wrap, which is what keeps a two-column step page usable with a
        large system font or a long translation.
        """
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            label = item.widget() if item is not None else None
            if not isinstance(label, QLabel):
                continue
            if label.sizeHint().width() > FORM_LABEL_MAX_WIDTH:
                label.setWordWrap(True)
                label.setMaximumWidth(FORM_LABEL_MAX_WIDTH)

    def _start_wizard(self, titles, bare_steps=()):
        """Builds the stepped layout and returns the list of per-step QFormLayouts.

        Args:
            titles: Step titles, in order.
            bare_steps: Indices of steps that build their own layout (e.g. a
                grid of cards). Their QFormLayout is created but left detached
                from the page, so ``step_forms[i]`` stays a usable layout while
                the page body stays empty for the subclass to fill.
        """
        self._wizard_titles = list(titles)
        bare = set(bare_steps)

        self._steps_widget = QStackedWidget()
        self.step_forms = []
        self.step_bodies = []
        for index, title in enumerate(titles):
            page = QWidget()
            body = QVBoxLayout(page)
            body.setContentsMargins(*STEP_CONTENT_MARGIN)
            body.setSpacing(STEP_CONTENT_SPACING)
            form = self._configure_form_layout(QFormLayout())
            if index not in bare:
                body.addLayout(form)
            self.step_forms.append(form)
            self.step_bodies.append(body)
            self._steps_widget.addWidget(page)
        self.left_scroll.setWidget(self._steps_widget)

        self._build_step_indicator(titles)
        self.step_indicator_row.setVisible(True)

        self._current_step = 0
        self._max_step = 0
        self.form = self.step_forms[0]
        self.body = self.step_bodies[0]
        self._refresh_navigation()
        # The subclass fills the step bodies *after* this returns, so the page
        # padding and the height fit have to wait for it. The timer covers any
        # subclass; a subclass may also call _initialise_step_layout() itself to
        # get a deterministic size before the first paint.
        self._step_pages_padded = False
        QTimer.singleShot(0, self._initialise_step_layout)
        return self.step_forms

    def _initialise_step_layout(self):
        """Pads the step pages and sizes the dialog - once content exists."""
        self._pad_step_pages()
        self._fit_dialog_height()

    def _clear_step_indicator(self):
        """Removes every widget from the step indicator strip."""
        while self.step_indicator_layout.count():
            item = self.step_indicator_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._step_index_by_item = {}

    def showEvent(self, event):
        """Re-fits the height once the layout has real measurements.

        A pre-show ``sizeHint()`` is only an estimate, so the fit done in
        ``__init__`` can come up short and leave the last step a few pixels
        scrollable. This runs before the first paint, so the correction is never
        visible as a jump.
        """
        super().showEvent(event)
        self._pad_step_pages()
        self._fit_dialog_height()

    def eventFilter(self, watched, event):
        """Lets an already-reached step in the indicator be clicked to return to."""
        index = self._step_index_by_item.get(watched)
        if index is not None and event.type() == QEvent.MouseButtonRelease:
            self._go_to_step(index)
            return True
        return super().eventFilter(watched, event)

    def _build_step_indicator(self, titles):
        """Rebuilds the strip as numbered badges + titles + a step counter."""
        self._clear_step_indicator()
        self._step_labels = []
        self._step_badges = []
        self._step_items = []
        self.step_counter_label = None

        for index, title in enumerate(titles):
            if index:
                arrow = QLabel("›")
                arrow.setProperty("class", "step-arrow")
                self.step_indicator_layout.addWidget(arrow)

            item = QWidget()
            # The global QWidget rule paints this grey on the white strip
            item.setProperty("class", "wizard-step-item")
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(4, 0, 4, 0)
            item_layout.setSpacing(6)

            badge = QLabel(str(index + 1))
            badge.setProperty("class", "step-badge")
            badge.setProperty("state", "pending")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(18, 18)

            label = QLabel(tr(title))
            label.setProperty("class", "step-title")
            label.setProperty("state", "pending")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            item_layout.addWidget(badge)
            item_layout.addWidget(label)
            self.step_indicator_layout.addWidget(item)

            self._step_index_by_item[item] = index
            for clickable in (item, badge, label):
                clickable.installEventFilter(self)

            self._step_badges.append(badge)
            self._step_labels.append(label)
            self._step_items.append(item)

        self.step_indicator_layout.addStretch(1)
        self.step_counter_label = QLabel()
        self.step_counter_label.setProperty("class", "step-counter")
        self.step_indicator_layout.addWidget(self.step_counter_label)

    def _refresh_navigation(self):
        """Updates the buttons and indicator for the current step."""
        is_last = self._current_step >= len(self.step_forms) - 1
        self.back_button.setEnabled(self._current_step > 0)
        self.next_button.setVisible(not is_last)
        self.save_button.setVisible(is_last)
        if is_last:
            self.save_button.setDefault(True)
            self.next_button.setDefault(False)
        else:
            self.next_button.setDefault(True)
            self.save_button.setDefault(False)

        for idx, lbl in enumerate(self._step_labels):
            state = self._step_state(idx)
            lbl.setProperty("state", state)
            badge = self._step_badges[idx]
            badge.setProperty("state", state)
            # Only steps already reached can be jumped back to.
            self._step_items[idx].setCursor(
                Qt.PointingHandCursor if idx <= self._max_step else Qt.ArrowCursor
            )
            for widget in (lbl, badge, self._step_items[idx]):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        if self.step_counter_label is not None:
            self.step_counter_label.setText(
                tr("Step {current} of {total}").format(
                    current=self._current_step + 1, total=len(self.step_forms)
                )
            )

    def _step_state(self, index):
        """Returns the indicator state for a step: active / done / pending."""
        if index == self._current_step:
            return "active"
        return "done" if index < self._current_step else "pending"

    def _go_next_step(self):
        self._current_step = min(self._current_step + 1, len(self.step_forms) - 1)
        self._max_step = max(self._max_step, self._current_step)
        self._sync_step()

    def _go_previous_step(self):
        self._current_step = max(self._current_step - 1, 0)
        self._sync_step()

    def _go_to_step(self, index):
        """Moves to a step the user has already reached.

        Steps beyond the furthest one reached are ignored, so the per-step
        validation gate (which only Next can clear) cannot be skipped. Jumping
        forward to an already-visited step is allowed so the user can return to
        it after reviewing an earlier one.
        """
        if index == self._current_step or not 0 <= index <= self._max_step:
            return
        self._current_step = index
        self._sync_step()

    def _sync_step(self):
        self.form = self.step_forms[self._current_step]
        self.body = self.step_bodies[self._current_step]
        self._steps_widget.setCurrentIndex(self._current_step)
        self._refresh_scroll_extent()
        self._refresh_navigation()
        # Returning to a step must re-apply its own validation state.
        revalidate = getattr(self, "_update_save_state", None)
        if callable(revalidate):
            revalidate()

    def _refresh_scroll_extent(self):
        """Keeps the left scroll area sized to the visible step's real height.

        Qt does not reliably re-query a QStackedWidget's size hint when the
        current page changes (or when a page grows, e.g. a receipt gaining
        lines): the surrounding scroll area keeps the previous extent, so a
        long receipt is painted clipped with no scrollbar to reach the rest.
        Pinning the stack's minimum to the current page's minimum the moment it
        becomes visible makes the scroll extent correct immediately.
        """
        if getattr(self, "_steps_widget", None) is None:
            return
        page = self._steps_widget.currentWidget()
        if page is None:
            return
        if page.layout() is not None:
            page.layout().activate()
        frame = getattr(self, "receipt_frame", None)
        if frame is not None:
            table = frame.findChild(QTableWidget, "receiptItems")
            # Only when the receipt's own step is the current one: a hidden
            # page has no real column widths, and re-pinning off those would
            # store a wrong height (it is re-pinned again when the step shows).
            if table is not None and table.width() > 0:
                from src.modules.receipt_card import refit_receipt_items_table
                refit_receipt_items_table(table)
                if page.layout() is not None:
                    page.layout().activate()
        self._steps_widget.setMinimumHeight(page.minimumSizeHint().height())
        self._steps_widget.updateGeometry()
        self.left_scroll.updateGeometry()

    def _make_form_card(self, title, parent_layout, stretch=0):
        """Builds a titled surface card holding a compact field form.

        Args:
            title: Card heading (already-localised text is passed through tr()).
            parent_layout: Layout the card is added to.
            stretch: Stretch factor for the card in ``parent_layout``.

        Returns:
            tuple[QFrame, QFormLayout]: the card frame and its field form.
        """
        frame = QFrame()
        frame.setProperty("class", "form-card")
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(*CARD_CONTENT_MARGIN)
        card_layout.setSpacing(CARD_SPACING)

        heading = QLabel(tr(title))
        heading.setProperty("class", "form-card-title")
        heading.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        heading.setWordWrap(True)
        card_layout.addWidget(heading)

        form = self._configure_form_layout(QFormLayout())
        card_layout.addLayout(form)
        # A card can be stretched to fill a whole step page (see
        # AddFullEntryDialog._pad_step_pages). This spacer keeps the fields
        # compact at the top of the card and lets the slack land as empty card
        # space below them: without it the card's own layout spreads it, which
        # put a ~260px band under the heading of one card and left the fields
        # of another floating ~100px apart.
        card_layout.addStretch(1)

        parent_layout.addWidget(frame, stretch)
        return frame, form

    def _make_toggle_card(self, title, widget, parent_layout):
        """Builds a single-line titled surface card around one control.

        Same visual language as ``_make_form_card`` and the clinical accordion
        cards, but on one line: a heading costs a whole extra row, and this
        dialog only has height for what the current step needs. Used for the
        consultation charge on the Clinical Exam step.

        Args:
            title: Card heading (already-localised text is passed through tr()).
            widget: The control (checkbox, spin box, ...) to show on the right.
            parent_layout: Layout the card is added to.

        Returns:
            QFrame: The card frame, so callers can assert on it.
        """
        frame = QFrame()
        frame.setProperty("class", "toggle-card")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(8)

        heading = QLabel(tr(title))
        heading.setProperty("class", "form-card-title")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addStretch(1)
        layout.addWidget(widget)

        parent_layout.addWidget(frame)
        return frame

    def _add_section_header(self, text):
        """Adds a stylized section header to the form."""
        label = QLabel(tr(text))
        label.setProperty("class", "dialog-section-title")
        self.form.addRow(label)

    def _setup_receipt(self, parent_layout):
        """Builds the professional, printable receipt for the final Billing & Review step.

        The card itself comes from ``src.modules.receipt_card`` - the very card
        the Receipt Details dialog shows - so this preview can never drift from
        the receipt the clinic later opens or prints for the client.

        Args:
            parent_layout: The step body (QVBoxLayout) to add the receipt into.
        """
        # Guidance line so the empty receipt never looks unfinished
        self.receipt_hint_label = QLabel(
            tr("Review the receipt below, then save the visit.")
        )
        self.receipt_hint_label.setProperty("class", "form-card-hint")
        self.receipt_hint_label.setWordWrap(True)
        parent_layout.addWidget(self.receipt_hint_label)

        # Header row for the receipt card; printing lives in the post-save
        # success dialog (Save Visit stays the only action on this step).
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.receipt_title_header = self._section_heading(tr("Receipt Preview"))
        toolbar.addWidget(self.receipt_title_header)
        toolbar.addStretch()
        parent_layout.addLayout(toolbar)

        # Kept so later refreshes can swap the card in place (see
        # _rebuild_receipt_card) without disturbing the hint or the
        # billing bar below it.
        self._receipt_parent_layout = parent_layout
        self._rebuild_receipt_card("", "", "", "", [], 0.0, 0.0)

    def _rebuild_receipt_card(self, date_str, owner, pet, phone, items,
                              discount, total):
        """Builds the shared receipt card and swaps it into the step layout.

        The preview passes ``client=True``: it is the client copy - payment
        details left out, thank-you footer in - because a receipt nobody has
        paid for must not show a payment strip, and there is no receipt
        number to print before the visit is saved. Everything else is the
        exact card Receipt Details renders.
        """
        card = build_receipt_card(
            {
                "receipt_date": date_str,
                "receipt_kind": "visit",
                "owner_name": owner,
                "pet_name": pet,
                "owner_phone": phone,
            },
            items, discount, total,
            client=True,
        )
        layout = self._receipt_parent_layout
        old = getattr(self, "receipt_frame", None)
        if old is not None:
            # Swap at the old frame's own index so the hint above and the
            # billing bar below never move (their positions are guarded
            # by tests).
            idx = layout.indexOf(old)
            layout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
            layout.insertWidget(idx, card.frame, 0, Qt.AlignHCenter)
        else:
            layout.addWidget(card.frame, 0, Qt.AlignHCenter)

        # Aliases: the rest of the wizard (and its tests) reads the receipt
        # through these names, so they must point at the fresh card.
        self.receipt_frame = card.frame
        self.receipt_items_table = card.table
        self.receipt_date = card.date
        self.receipt_owner = card.owner
        self.receipt_pet = card.pet
        self.receipt_phone = card.phone
        self.receipt_subtotal = card.subtotal
        self.receipt_discount = card.discount
        self.receipt_total = card.total
        self.receipt_clinic_label = card.clinic
        self.receipt_logo_label = card.logo
        self.receipt_title_label = card.title
        self.receipt_footer_label = card.footer

        # The card just changed height (more/fewer lines): grow the step's
        # scroll extent right away so no line is painted clipped.
        self._refresh_scroll_extent()

    def _set_save_enabled(self, enabled):
        """Enables/disables the proceed button for the current step (Next or Save)."""
        self.next_button.setEnabled(bool(enabled))
        self.save_button.setEnabled(bool(enabled))

    def handle_stock_error(self, result):
        """Common logic to display insufficient stock warnings.

        Args:
            result: The result string from a repository call.

        Returns:
            bool: True if it was a stock error, False otherwise.
        """
        if isinstance(result, str) and result.startswith("STOCK_ERROR"):
            _, name, max_qty = result.split("|")
            QMessageBox.warning(
                self, tr("Stock Error"),
                tr("Insufficient stock for {name}. Maximum available: {max_qty}").format(
                    name=name, max_qty=max_qty
                )
            )
            return True
        return False

    def _update_total(self):
        """Recalculates visit totals and refreshes the receipt preview."""
        total = 0.0

        # 1. Add Consultation Fee if applicable
        if hasattr(self, 'consult') and self.consult.isChecked():
            total += float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))

        # 2. Add Supply Item totals
        if hasattr(self, '_supply_rows'):
            for cat_cb, item_cb, qty_sb, price_sb in self._supply_rows:
                if item_cb.currentText():
                    total += qty_sb.value() * price_sb.value()

        # 3. Add Package totals
        if hasattr(self, '_package_rows'):
            for pkg_combo, qty_spin, price_spin in self._package_rows:
                if pkg_combo.currentData():
                    total += qty_spin.value() * price_spin.value()

        # 4. Subtract discount if the dialog has one
        discount = self.discount_spin.value() if hasattr(self, 'discount_spin') else 0.0
        # The receipt's Subtotal is everything billed, so it has to be taken
        # before the discount comes off - otherwise Subtotal - Discount would
        # not equal Total (the consultation fee used to be missing from it).
        subtotal = total
        total = max(0.0, total - discount)

        if hasattr(self, 'receipt_frame'):
            self._update_receipt(subtotal, discount, total)

    def _update_receipt(self, subtotal, discount, total):
        """Refreshes the receipt preview meta info, line items, and totals.

        ``subtotal`` is kept in the signature for callers but is not passed on:
        the shared builder sums its own line items, which is the same figure
        (supplies + consultation + packages, before the discount).
        """
        if hasattr(self, 'v_date'):
            date_str = self.v_date.dateTime().toString(self.v_date.displayFormat())
            owner = self.owner_name.text().strip().title() if hasattr(self, 'owner_name') else ""
            phone = self.phone.text().strip() if hasattr(self, 'phone') else ""
            pet = self.pet_name.text().strip() if hasattr(self, 'pet_name') else ""
        elif hasattr(self, 'visit_date'):
            date_str = self.visit_date.dateTime().toString(self.visit_date.displayFormat())
            owner = self.client_selector.currentText() if hasattr(self, 'client_selector') else ""
            idx = owner.find(" (")
            owner = owner[:idx] if idx > 0 else owner
            pet = self.pet_selector.currentText() if hasattr(self, 'pet_selector') else ""
            phone = ""
        else:
            date_str = ""
            owner = pet = phone = ""

        # Itemized lines in the order get_receipt_line_items prints them for
        # the saved receipt: supplies, then the consultation service, then
        # packages.
        items = []
        if hasattr(self, '_supply_rows'):
            for cat_cb, item_cb, qty_sb, price_sb in self._supply_rows:
                if item_cb.currentText():
                    items.append({
                        "name": item_cb.currentText(),
                        "quantity": qty_sb.value(),
                        "unit_price": price_sb.value(),
                    })
        if hasattr(self, 'consult') and self.consult.isChecked():
            fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
            # The saved receipt carries services_lookup's raw service name, so
            # the preview prints the same one - deliberately untranslated.
            items.append({"name": "Consultation", "quantity": 1, "unit_price": fee})
        if hasattr(self, '_package_rows'):
            for pkg_combo, qty_spin, price_spin in self._package_rows:
                pkg_data = pkg_combo.currentData()
                if pkg_data:
                    items.append({
                        "name": pkg_data["package_name"],
                        "quantity": qty_spin.value(),
                        "unit_price": price_spin.value(),
                    })

        self._rebuild_receipt_card(date_str, owner, pet, phone, items,
                                   discount, total)

    def _render_receipt_pixmap(self):
        """Renders the receipt card to an image suitable for print/PDF.

        The card is first grown to its full content height so a stale layout
        can never hand ``grab`` a clipped viewport (which would print a receipt
        missing its lower lines).
        """
        if not hasattr(self, 'receipt_frame'):
            return None
        frame = self.receipt_frame
        if frame.layout() is not None:
            frame.layout().activate()
        table = frame.findChild(QTableWidget, "receiptItems")
        if table is not None:
            from src.modules.receipt_card import refit_receipt_items_table
            refit_receipt_items_table(table)
            if frame.layout() is not None:
                frame.layout().activate()
        frame.resize(frame.width(),
                     max(frame.height(), frame.minimumSizeHint().height()))
        pix = frame.grab()
        return pix if not pix.isNull() else None

    def _paint_pixmap_on_printer(self, printer, pix):
        """Draws the receipt pixmap centered and scaled to fit a printer page."""
        painter = QPainter(printer)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        painter.fillRect(page_rect, Qt.white)
        scale = min(page_rect.width() / pix.width(), page_rect.height() / pix.height(), 2.0)
        target_w = int(pix.width() * scale)
        target_h = int(pix.height() * scale)
        x = (page_rect.width() - target_w) // 2
        y = (page_rect.height() - target_h) // 2
        painter.drawPixmap(x, y, target_w, target_h, pix)
        painter.end()

    def _print_receipt(self):
        """Opens the system print dialog to print the receipt."""
        pix = self._render_receipt_pixmap()
        if pix is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._paint_pixmap_on_printer(printer, pix)

    def handle_accept(self):
        """Should be overridden by child classes."""
        raise NotImplementedError
