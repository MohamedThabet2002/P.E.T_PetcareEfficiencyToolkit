"""
Full Clinical Entry Dialog for the PET Application.

Provides the AddFullEntryDialog, which enables one-stop intake of a new client,
pet, and visit record in a single dialog. It reuses the BaseClinicalDialog
for the supply receipt section and estimated total display.
"""

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel,
    QLineEdit, QListView, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QTextEdit, QCompleter, QToolButton, QVBoxLayout, QWidget
)
from PyQt5.QtCore import Qt, QDateTime, QSize
from PyQt5.QtGui import QIcon

import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.vaccination_repo as vaccination_repo
import src.core.services.clinical_service as clinical_service
from src.config.constants import DEFAULT_CONSULT_FEE
from src.config.paths import ICONS_DIR
from src.utils.formatters import format_currency
from src.utils.settings_manager import SettingsManager
from src.utils.i18n import tr
from src.ui.dialogs.base_clinical_dialog import (
    BaseClinicalDialog, ClinicalSectionsMixin, NOTES_BOX_HEIGHT, STEP_CONTENT_SPACING,
    DELETE_BUTTON_SIZE, DELETE_BUTTON_SYMBOL,
)

#==================================== CONSTANTS =======================================================#

ADD_FULL_ENTRY_DIALOG_WIDTH = 960
# The wizard opens at this height and stays there: every step's content
# stretches down to fill the page (see _pad_step_pages), so a content-driven
# shrink would only put the dead band back.
ADD_FULL_ENTRY_DIALOG_HEIGHT = 720
ADD_FULL_ENTRY_DIALOG_MAX_AGE = 999
ADD_FULL_ENTRY_DIALOG_MAX_WEIGHT = 9999

DATE_TIME_FORMAT = "yyyy-MM-dd HH:mm"

# Record-book clinical exam option sets (step 2). The second element of every
# pair is the exact token `clinical_exam_repo` stores (lowercase, matching the
# DB CHECK constraints); the first is the translated display label. A blank
# label with ``None`` data is the "not recorded" choice.
RECORD_WEIGHT_CONDITIONS = [
    ("", None), ("Underweight", "underweight"),
    ("Normal", "normal"), ("Overweight", "overweight"),
]
RECORD_TEMPERATURE_STATUS = [
    ("", None), ("Low", "low"), ("Normal", "normal"), ("High", "high"),
]
RECORD_TRI_STATE = [
    ("", None), ("Normal", "normal"), ("Increased", "increased"),
    ("Decreased", "decreased"),
]
RECORD_QUAD_STATE = RECORD_TRI_STATE + [("None", "none")]
RECORD_FECES_STATUS = [("", None), ("Normal", "normal"), ("Abnormal", "abnormal")]
RECORD_TEST_RESULTS = [
    ("", None), ("Positive", "positive"), ("Negative", "negative"),
    ("Pending", "pending"),
]
RECORD_RATE_CATEGORY = [
    ("", None), ("Slow", "slow"), ("Normal", "normal"), ("Fast", "fast"),
]
RECORD_GINGIVITIS = [
    ("", None), ("None", "none"), ("Mild", "mild"),
    ("Moderate", "moderate"), ("Severe", "severe"),
]
# (label, record-book key) - the keys are camelCase, the shape
# `clinical_exam_repo.save_clinical_exam` reads back.
RECORD_RECOMMENDED = [
    ("X-rays", "xrays"), ("EKG", "ekg"), ("Urinalysis", "urinalysis"),
    ("Thyroid Level", "thyroidLevel"),
    ("Ultrasonic Teeth Cleaning", "ultrasonicTeethCleaning"),
    ("Drug Monitoring", "drugMonitoring"), ("Blood Screen", "bloodScreen"),
    ("Deep Ear Video", "deepEarVideo"),
]


class AddFullEntryDialog(BaseClinicalDialog, ClinicalSectionsMixin):
    """
    One-stop dialog for entering a complete clinical record:
    Client + Pet + Visit + Supplies in a single form.
    """

    def __init__(self, parent=None, current_user=None):
        super().__init__(
            tr("Add Visit"),
            (ADD_FULL_ENTRY_DIALOG_WIDTH, ADD_FULL_ENTRY_DIALOG_HEIGHT),
            parent
        )
        self._current_user = current_user
        # The wizard opens at its full design height: _pad_step_pages stretches
        # every step's content to the bottom of the page, so _fit_dialog_height
        # has no dead band to shrink away and must not take the height back.
        self._fit_floor = ADD_FULL_ENTRY_DIALOG_HEIGHT
        # Filled by handle_accept: the receipt the visit just created, which
        # the success box prints as a client copy (see _print_receipt).
        self._saved_receipt_id = None
        self._setup_fields()
        self._setup_receipt(self.step_bodies[3])
        # Last additions to step 4: the discount row sits at the bottom of the
        # page, under the receipt, so the receipt keeps the top of the step.
        self._setup_billing_step()
        self._update_total()
        self._found_owner = None
        self._found_pet = None
        self._set_owner_status(False)
        self._set_pet_status(False)
        self._update_save_state()
        # Last, so every step body is complete: stretch the pages and settle the
        # dialog height. Must come after _setup_receipt, which appends to step
        # 4's body, and after _update_total, because the receipt grows with its
        # item rows.
        self._initialise_step_layout()

    def _setup_fields(self):
        self._start_wizard([
            "Patient & Visit",
            "Clinical Exam",
            "Other Supplies",
            "Billing & Review",
        ], bare_steps=(0,))

        self._setup_patient_step()
        self._setup_exam_step()
        self._setup_supplies_step()

        self._update_total()

    def _setup_patient_step(self):
        """Step 1 - who is visiting: identity and visit details side by side."""
        columns = QHBoxLayout()
        columns.setSpacing(STEP_CONTENT_SPACING)
        self.step_bodies[0].addLayout(columns)

        # ── Card 1 · who the patient and the owner are ──
        identity_card, identity_form = self._make_form_card(
            "Client & Pet Details", columns, stretch=1
        )
        self.identity_card = identity_card

        self.owner_name = QLineEdit()
        self.owner_name.textChanged.connect(self._update_save_state)
        self.owner_name.textChanged.connect(self._on_owner_name_changed)
        self.owner_name.editingFinished.connect(self._on_owner_name_finished)
        self.owner_name.returnPressed.connect(self._on_owner_name_finished)
        self.owner_name.setPlaceholderText(tr("Full name of the pet owner"))

        self.phone = QLineEdit()
        self.phone.setPlaceholderText(tr("e.g. 0123 456 7890"))

        self.pet_name = QLineEdit()
        self.pet_name.textChanged.connect(self._on_pet_name_changed)
        self.pet_name.textChanged.connect(self._update_save_state)
        self.pet_name.editingFinished.connect(self._on_pet_name_finished)
        self.pet_name.returnPressed.connect(self._on_pet_name_finished)
        self.pet_name.setPlaceholderText(tr("e.g. Buddy"))

        # Status indicators
        self.owner_status_label = QToolButton()
        self.owner_status_label.setAutoRaise(True)
        self.owner_status_label.setFixedSize(28, 28)
        self.owner_status_label.setIconSize(QSize(20, 20))

        self.pet_status_label = QToolButton()
        self.pet_status_label.setAutoRaise(True)
        self.pet_status_label.setFixedSize(28, 28)
        self.pet_status_label.setIconSize(QSize(20, 20))

        self.species = QComboBox()
        self.species.setView(QListView())
        self.species.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.species.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.species.addItems(supply_repo.get_all_species())

        self.breed = QLineEdit()
        breed_completer = QCompleter(pet_repo.get_unique_breeds())
        breed_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.breed.setCompleter(breed_completer)

        self.gender = QComboBox()
        self.gender.setView(QListView())
        self.gender.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.gender.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        # Store the English value as item data so the DB keeps 'Male'/'Female'/
        # 'Other' whatever the display language; the label is translated only
        # for display.
        for _g in ("Male", "Female", "Other"):
            self.gender.addItem(tr(_g), _g)

        self.age = QSpinBox()
        self.age.setMaximum(ADD_FULL_ENTRY_DIALOG_MAX_AGE)

        # Pet weight is not entered here anymore; it lives on the record-book
        # General Physical Examination section. Existing pets keep their stored
        # weight, new pets start at 0 (see _pet_weight).
        self._pet_weight = 0.0

        owner_row = QHBoxLayout()
        owner_row.addWidget(self.owner_name, 1)
        owner_row.addWidget(self.owner_status_label)
        identity_form.addRow(tr("Owner Name") + "*:", owner_row)
        identity_form.addRow(tr("Phone Number") + ":", self.phone)
        pet_row = QHBoxLayout()
        pet_row.addWidget(self.pet_name, 1)
        pet_row.addWidget(self.pet_status_label)
        identity_form.addRow(tr("Pet Name") + ":", pet_row)
        identity_form.addRow(tr("Species") + ":", self.species)
        identity_form.addRow(tr("Breed") + ":", self.breed)
        identity_form.addRow(tr("Gender") + ":", self.gender)
        identity_form.addRow(tr("Age") + ":", self.age)

        # ── Card 2 · what is happening on this visit ──
        visit_card, visit_form = self._make_form_card(
            "Visit Details", columns, stretch=1
        )
        self.visit_card = visit_card

        self.v_date = QDateTimeEdit(QDateTime.currentDateTime())
        self.v_date.setCalendarPopup(True)
        self.v_date.setDisplayFormat(DATE_TIME_FORMAT)

        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("Reason for visit..."))

        self.diagnosis = QLineEdit()
        diag_completer = QCompleter(visit_repo.get_unique_diagnoses())
        diag_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.diagnosis.setCompleter(diag_completer)
        self.diagnosis.setPlaceholderText(tr("Add diagnosis..."))

        self.notes = QTextEdit()
        self.notes.setFixedHeight(NOTES_BOX_HEIGHT)
        self.notes.setPlaceholderText(tr("Add notes..."))

        visit_form.addRow(tr("Date") + ":", self.v_date)
        visit_form.addRow(tr("Reason for Visit") + ":", self.reason)
        visit_form.addRow(tr("Diagnosis") + ":", self.diagnosis)
        visit_form.addRow(tr("Notes") + ":", self.notes)

        # ── Follow-up · optional, and kept inside the Visit Details card so
        #    step 1 is one tidy row of two cards instead of a third full-width band
        self.followup_group = QGroupBox(tr("Schedule Follow-up"))
        self.followup_group.setObjectName("followupGroup")
        self.followup_group.setCheckable(True)
        self.followup_group.setChecked(False)
        followup_form = self._configure_form_layout(QFormLayout(self.followup_group))
        self.followup_date = QDateTimeEdit(QDateTime.currentDateTime().addDays(7), calendarPopup=True)
        self.followup_date.setDisplayFormat(DATE_TIME_FORMAT)
        self.followup_notes = QLineEdit()
        self.followup_notes.setPlaceholderText(tr("Optional follow-up notes"))
        followup_form.addRow(tr("Date:"), self.followup_date)
        followup_form.addRow(tr("Notes:"), self.followup_notes)
        self._cap_form_labels(followup_form)

        visit_card_layout = self.visit_card.layout()
        # _make_form_card parks a spacer as the card's last item so the slack
        # of a stretched card lands below its fields; the follow-up group is
        # content, so it goes above that spacer.
        visit_card_layout.insertWidget(visit_card_layout.count() - 1,
                                       self.followup_group)

        # Labels are only capped once every row is in place
        self._cap_form_labels(identity_form)
        self._cap_form_labels(visit_form)

    def _setup_exam_step(self):
        """Step 2 - consultation charge plus the collapsible clinical sections."""
        self.form = self.step_forms[1]

        # Billing sits on its own titled one-line card, so the step reads as
        # "what was charged" then "what was found" instead of a lone
        # checkbox floating above five section cards.
        fee = SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE)
        self.consult = QCheckBox(f"{tr('Consult Charge Applied?')} (${fee})")
        self.consult.toggled.connect(self._update_total)
        self._make_toggle_card("Consultation", self.consult, self.step_bodies[1])

        # Record-book clinical sections below the consultation card
        self._setup_record_exam_sections(self.step_bodies[1])

    # ---------------------------------------------------------------- step 2
    # Record-book clinical exam. The sections are the same accordion cards the
    # rest of the wizard uses (_collapsible_group), so the step keeps its
    # "consultation + expandable sections" layout; only the data changed to the
    # normalized record-book structure saved by clinical_exam_repo.

    def _setup_record_exam_sections(self, parent_layout):
        """Builds the six collapsible record-book sections of step 2."""
        self._record_cards = {}
        builders = (
            ("general", "General Physical Examination",
             self._setup_record_general_section),
            ("signs", "Clinical Signs", self._setup_record_clinical_signs_section),
            ("tests", "Routine Tests", self._setup_record_tests_section),
            ("vaccinations", "Vaccinations", self._setup_record_vaccinations_section),
            ("physical", "Physical Exam", self._setup_record_physical_exam_section),
            ("recommended", "Recommended Tests & Treatments",
             self._setup_record_recommended_section),
        )
        for name, title, builder in builders:
            card, content = self._collapsible_group(title, parent_layout)
            builder(content)
            card.toggled.connect(self._refresh_record_summaries)
            self._record_cards[name] = card
        self._refresh_record_summaries()

    def _record_combo(self, options, width=None):
        """A combo whose items carry the record-book data token as item data."""
        combo = QComboBox()
        for label, value in options:
            combo.addItem(tr(label) if label else "", value)
        if width is not None:
            combo.setFixedWidth(width)
        return combo

    def _record_row(self, label_text, *widgets, grow_last=False):
        """One labeled row inside a record-book section.

        A fixed-width label keeps every row's fields aligned; ``grow_last``
        lets the trailing widget (a free-text field) take the spare width.
        """
        row = QWidget()
        row.setProperty("class", "record-row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(8)
        label = QLabel(tr(label_text))
        label.setMinimumWidth(150)
        row_layout.addWidget(label)
        for index, widget in enumerate(widgets):
            if grow_last and index == len(widgets) - 1:
                row_layout.addWidget(widget, 1)
            else:
                row_layout.addWidget(widget)
        if not grow_last:
            row_layout.addStretch(1)
        return row

    def _record_delete_button(self):
        button = QPushButton(DELETE_BUTTON_SYMBOL)
        button.setFixedSize(*DELETE_BUTTON_SIZE)
        button.setProperty("action", "delete")
        return button

    def _setup_record_general_section(self, layout):
        """General Physical Examination: weight, temperature, neutered."""
        self._rec_weight_value = QDoubleSpinBox()
        self._rec_weight_value.setRange(0, ADD_FULL_ENTRY_DIALOG_MAX_WEIGHT)
        self._rec_weight_value.setDecimals(2)
        self._rec_weight_value.setSpecialValueText("—")
        self._rec_weight_value.setSuffix(" kg")
        self._rec_weight_condition = self._record_combo(RECORD_WEIGHT_CONDITIONS)

        self._rec_temperature_value = QDoubleSpinBox()
        self._rec_temperature_value.setRange(0, 200)
        self._rec_temperature_value.setDecimals(2)
        self._rec_temperature_value.setSpecialValueText("—")
        self._rec_temperature_value.setSuffix(" °C")
        self._rec_temperature_status = self._record_combo(RECORD_TEMPERATURE_STATUS)

        self._rec_neutered = QCheckBox(tr("Neutered"))

        layout.addWidget(self._record_row(
            "Weight", self._rec_weight_value, self._rec_weight_condition))
        layout.addWidget(self._record_row(
            "Temperature", self._rec_temperature_value, self._rec_temperature_status))
        layout.addWidget(self._record_row("Neutered", self._rec_neutered))

    def _setup_record_clinical_signs_section(self, layout):
        """Clinical Signs: the standard symptom review."""
        self._rec_energy = self._record_combo(RECORD_TRI_STATE)
        self._rec_appetite = self._record_combo(RECORD_QUAD_STATE)
        self._rec_water = self._record_combo(RECORD_QUAD_STATE)
        self._rec_urination = self._record_combo(RECORD_QUAD_STATE)
        self._rec_feces_status = self._record_combo(RECORD_FECES_STATUS)
        self._rec_feces_notes = QLineEdit()
        self._rec_vomiting_present = QCheckBox(tr("Present"))
        self._rec_vomiting_freq = QLineEdit()
        self._rec_coughing_present = QCheckBox(tr("Present"))
        self._rec_coughing_freq = QLineEdit()
        self._rec_sneezing_present = QCheckBox(tr("Present"))
        self._rec_sneezing_freq = QLineEdit()

        layout.addWidget(self._record_row("Energy", self._rec_energy))
        layout.addWidget(self._record_row("Appetite", self._rec_appetite))
        layout.addWidget(self._record_row("Water Intake", self._rec_water))
        layout.addWidget(self._record_row("Urination", self._rec_urination))
        layout.addWidget(self._record_row(
            "Feces", self._rec_feces_status, self._rec_feces_notes, grow_last=True))
        layout.addWidget(self._record_row(
            "Vomiting", self._rec_vomiting_present, self._rec_vomiting_freq,
            grow_last=True))
        layout.addWidget(self._record_row(
            "Coughing", self._rec_coughing_present, self._rec_coughing_freq,
            grow_last=True))
        layout.addWidget(self._record_row(
            "Sneezing", self._rec_sneezing_present, self._rec_sneezing_freq,
            grow_last=True))

    def _setup_record_tests_section(self, layout):
        """Routine Tests: free-text test rows with a result."""
        self._rec_test_rows = []
        self._rec_tests_layout = QVBoxLayout()
        self._rec_tests_layout.setSpacing(4)
        layout.addLayout(self._rec_tests_layout)
        add_btn = QPushButton(tr("+ Add Test"))
        # clicked(bool) would be handed to name=, so bind it away explicitly.
        add_btn.clicked.connect(lambda: self._add_record_test_row())
        layout.addWidget(add_btn)

    def _add_record_test_row(self, name="", result=None):
        """Adds one routine-test row (test name + result)."""
        row = QWidget()
        row.setProperty("class", "record-row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(8)

        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText(tr("Test"))
        result_combo = self._record_combo(RECORD_TEST_RESULTS)
        if result is not None:
            index = result_combo.findData(result)
            if index >= 0:
                result_combo.setCurrentIndex(index)

        delete_btn = self._record_delete_button()

        def remove_row():
            self._rec_tests_layout.removeWidget(row)
            row.deleteLater()
            self._rec_test_rows = [r for r in self._rec_test_rows if r[0] is not row]
            self._refresh_record_summaries()

        delete_btn.clicked.connect(remove_row)
        row_layout.addWidget(name_edit, 1)
        row_layout.addWidget(result_combo)
        row_layout.addWidget(delete_btn)
        self._rec_tests_layout.addWidget(row)
        self._rec_test_rows.append((row, name_edit, result_combo))
        self._refresh_record_summaries()

    def _setup_record_vaccinations_section(self, layout):
        """Vaccinations: checkbox per vaccine in the lookup."""
        self._rec_vaccine_checkboxes = []
        for vaccine in vaccination_repo.get_all_vaccines():
            checkbox = QCheckBox(vaccine["vaccine_name"])
            checkbox.toggled.connect(self._refresh_record_summaries)
            self._rec_vaccine_checkboxes.append(checkbox)
            layout.addWidget(checkbox)

    def _setup_record_physical_exam_section(self, layout):
        """Physical Exam: one row per body system, only abnormal ones detailed."""
        self._rec_findings = {}
        self._rec_conditions = {}

        self._rec_heart_normal = QCheckBox(tr("Normal"))
        self._rec_heart_normal.setChecked(True)
        self._rec_heart_rate = QSpinBox()
        self._rec_heart_rate.setRange(0, 400)
        self._rec_heart_rate.setSpecialValueText("—")
        self._rec_heart_category = self._record_combo(RECORD_RATE_CATEGORY)
        self._rec_murmur_left = QLineEdit()
        self._rec_murmur_right = QLineEdit()
        layout.addWidget(self._record_row(
            "Heart", self._rec_heart_normal, self._rec_heart_rate,
            self._rec_heart_category))
        layout.addWidget(self._record_row(
            "Murmur Left", self._rec_murmur_left, grow_last=True))
        layout.addWidget(self._record_row(
            "Murmur Right", self._rec_murmur_right, grow_last=True))

        for system, label in (
            ("lungs", "Lungs"), ("eyes", "Eyes"), ("ears", "Ears"),
            ("noseAndThroat", "Nose and Throat"),
        ):
            checkbox = QCheckBox(tr("Normal"))
            checkbox.setChecked(True)
            finding = QLineEdit()
            finding.setPlaceholderText(tr("Findings"))
            setattr(self, "_rec_%s_normal" % system, checkbox)
            self._rec_findings[system] = finding
            layout.addWidget(self._record_row(label, checkbox, finding, grow_last=True))

        self._rec_mouth_normal = QCheckBox(tr("Normal"))
        self._rec_mouth_normal.setChecked(True)
        self._rec_mouth_conditions = QLineEdit()
        self._rec_mouth_conditions.setPlaceholderText(tr("Findings"))
        self._rec_gingivitis = self._record_combo(RECORD_GINGIVITIS)
        self._rec_conditions["mouthTeethGums"] = self._rec_mouth_conditions
        layout.addWidget(self._record_row(
            "Mouth, Teeth, Gums", self._rec_mouth_normal,
            self._rec_mouth_conditions, grow_last=True))
        layout.addWidget(self._record_row("Gingivitis Severity", self._rec_gingivitis))

        self._rec_abdomen_normal = QCheckBox(tr("Normal"))
        self._rec_abdomen_normal.setChecked(True)
        self._rec_abdomen_conditions = QLineEdit()
        self._rec_abdomen_conditions.setPlaceholderText(tr("Findings"))
        self._rec_conditions["abdomen"] = self._rec_abdomen_conditions
        layout.addWidget(self._record_row(
            "Abdomen", self._rec_abdomen_normal,
            self._rec_abdomen_conditions, grow_last=True))

        self._rec_msk_normal = QCheckBox(tr("Normal"))
        self._rec_msk_normal.setChecked(True)
        self._rec_msk_conditions = QLineEdit()
        self._rec_msk_conditions.setPlaceholderText(tr("Findings"))
        self._rec_msk_locations = QLineEdit()
        self._rec_conditions["musculoskeletal"] = self._rec_msk_conditions
        layout.addWidget(self._record_row(
            "Musculoskeletal", self._rec_msk_normal,
            self._rec_msk_conditions, grow_last=True))
        layout.addWidget(self._record_row(
            "Locations", self._rec_msk_locations, grow_last=True))

        self._rec_skin_normal = QCheckBox(tr("Normal"))
        self._rec_skin_normal.setChecked(True)
        self._rec_skin_conditions = QLineEdit()
        self._rec_skin_conditions.setPlaceholderText(tr("Findings"))
        self._rec_conditions["skinHairCoat"] = self._rec_skin_conditions
        layout.addWidget(self._record_row(
            "Skin & Hair Coat", self._rec_skin_normal,
            self._rec_skin_conditions, grow_last=True))

    def _setup_record_recommended_section(self, layout):
        """Recommended Tests & Treatments: checkboxes + follow-up/other notes."""
        self._rec_recommended = {}
        for label, key in RECORD_RECOMMENDED:
            checkbox = QCheckBox(tr(label))
            checkbox.toggled.connect(self._refresh_record_summaries)
            self._rec_recommended[key] = checkbox
            layout.addWidget(checkbox)
        self._rec_other = QLineEdit()
        self._rec_other.setPlaceholderText(tr("Other"))
        layout.addWidget(self._record_row("Other", self._rec_other, grow_last=True))

    def _record_summary_counts(self):
        """How many meaningful values each record-book section holds."""
        general = [
            self._rec_weight_value.value(),
            self._rec_weight_condition.currentData(),
            self._rec_temperature_value.value(),
            self._rec_temperature_status.currentData(),
            self._rec_neutered.isChecked(),
        ]
        signs = [
            self._rec_energy.currentData(),
            self._rec_appetite.currentData(),
            self._rec_water.currentData(),
            self._rec_urination.currentData(),
            self._rec_feces_status.currentData(),
            self._rec_feces_notes.text().strip(),
            self._rec_vomiting_present.isChecked(),
            self._rec_coughing_present.isChecked(),
            self._rec_sneezing_present.isChecked(),
        ]
        system_normals = [
            self._rec_heart_normal, getattr(self, "_rec_lungs_normal"),
            getattr(self, "_rec_eyes_normal"), getattr(self, "_rec_ears_normal"),
            getattr(self, "_rec_noseAndThroat_normal"), self._rec_mouth_normal,
            self._rec_abdomen_normal, self._rec_msk_normal, self._rec_skin_normal,
        ]
        physical = sum(1 for cb in system_normals if not cb.isChecked())
        physical += bool(self._rec_murmur_left.text().strip())
        physical += bool(self._rec_murmur_right.text().strip())
        recommended = sum(1 for cb in self._rec_recommended.values() if cb.isChecked())
        recommended += bool(self._rec_other.text().strip())
        return {
            "general": sum(1 for value in general if value),
            "signs": sum(1 for value in signs if value),
            "tests": len(self._rec_test_rows),
            "vaccinations": sum(1 for cb in self._rec_vaccine_checkboxes if cb.isChecked()),
            "physical": physical,
            "recommended": recommended,
        }

    def _refresh_record_summaries(self):
        """Writes the right-hand count on every step 2 section header."""
        cards = getattr(self, "_record_cards", None)
        if not cards:
            return
        counts = self._record_summary_counts()
        for name, card in cards.items():
            count = counts.get(name, 0)
            key = "{count} selected" if name == "vaccinations" else "{count} recorded"
            card._section_header.set_summary(
                tr(key).format(count=count) if count else tr("None"))

    def get_clinical_exam_data(self):
        """Collects step 2 into the record-book structure saved per visit."""
        def _value(spin):
            return spin.value() if spin.value() > 0 else None

        def _lines(text):
            return [part.strip() for part in (text or "").split(";") if part.strip()]

        routine_tests = []
        for _row, name_edit, result_combo in self._rec_test_rows:
            name = name_edit.text().strip()
            result = result_combo.currentData()
            if name or result:
                routine_tests.append({"testName": name, "result": result})

        return {
            "generalPhysicalExamination": {
                "weight": {
                    "value": _value(self._rec_weight_value),
                    "condition": self._rec_weight_condition.currentData(),
                },
                "temperature": {
                    "value": _value(self._rec_temperature_value),
                    "status": self._rec_temperature_status.currentData(),
                },
                "neutered": self._rec_neutered.isChecked(),
            },
            "clinicalSigns": {
                "energy": self._rec_energy.currentData(),
                "appetite": self._rec_appetite.currentData(),
                "waterIntake": self._rec_water.currentData(),
                "urination": self._rec_urination.currentData(),
                "feces": {
                    "status": self._rec_feces_status.currentData(),
                    "notes": self._rec_feces_notes.text().strip(),
                },
                "vomiting": {
                    "present": self._rec_vomiting_present.isChecked(),
                    "frequency": self._rec_vomiting_freq.text().strip(),
                },
                "coughing": {
                    "present": self._rec_coughing_present.isChecked(),
                    "frequency": self._rec_coughing_freq.text().strip(),
                },
                "sneezing": {
                    "present": self._rec_sneezing_present.isChecked(),
                    "frequency": self._rec_sneezing_freq.text().strip(),
                },
            },
            "routineTests": routine_tests,
            "vaccinations": [
                cb.text() for cb in self._rec_vaccine_checkboxes if cb.isChecked()
            ],
            "physicalExam": {
                "heart": {
                    "normal": self._rec_heart_normal.isChecked(),
                    "heartRate": self._rec_heart_rate.value() or None,
                    "rateCategory": self._rec_heart_category.currentData(),
                    "murmur": {
                        "left": self._rec_murmur_left.text().strip(),
                        "right": self._rec_murmur_right.text().strip(),
                    },
                },
                "lungs": {
                    "normal": getattr(self, "_rec_lungs_normal").isChecked(),
                    "findings": _lines(self._rec_findings["lungs"].text()),
                },
                "eyes": {
                    "normal": getattr(self, "_rec_eyes_normal").isChecked(),
                    "findings": _lines(self._rec_findings["eyes"].text()),
                },
                "ears": {
                    "normal": getattr(self, "_rec_ears_normal").isChecked(),
                    "findings": _lines(self._rec_findings["ears"].text()),
                },
                "noseAndThroat": {
                    "normal": getattr(self, "_rec_noseAndThroat_normal").isChecked(),
                    "findings": _lines(self._rec_findings["noseAndThroat"].text()),
                },
                "mouthTeethGums": {
                    "normal": self._rec_mouth_normal.isChecked(),
                    "conditions": _lines(self._rec_mouth_conditions.text()),
                    "gingivitisSeverity": self._rec_gingivitis.currentData(),
                },
                "abdomen": {
                    "normal": self._rec_abdomen_normal.isChecked(),
                    "conditions": _lines(self._rec_abdomen_conditions.text()),
                },
                "musculoskeletal": {
                    "normal": self._rec_msk_normal.isChecked(),
                    "conditions": _lines(self._rec_msk_conditions.text()),
                    "locations": _lines(self._rec_msk_locations.text()),
                },
                "skinHairCoat": {
                    "normal": self._rec_skin_normal.isChecked(),
                    "conditions": _lines(self._rec_skin_conditions.text()),
                },
            },
            "recommendedTestsTreatments": {
                **{key: cb.isChecked() for key, cb in self._rec_recommended.items()},
                "other": self._rec_other.text().strip(),
            },
        }

    def _setup_supplies_step(self):
        """Step 3 - sellable items and service packages.

        Both lists stretch, and they stretch *equally*, exactly like the Quick
        Purchase dialog builds them (3 and 3), so this page's spare height is
        split between the two lists instead of piling up as a dead band under
        them. The other half of that trick is ``_pad_step_pages`` below, which
        takes this page's bottom spacer out of the running - with a stretch
        factor it would swallow most of the room the lists are meant to grow
        into.
        """
        self._setup_supplies_section(self.step_bodies[2], stretch=3)
        self._setup_packages_section(self.step_bodies[2], stretch=3)

    def _pad_step_pages(self):
        """The step content, not a gap, holds the dialog's spare height.

        The base class parks each page's leftover height in a bottom spacer, so
        the content stops short of the dialog's bottom edge. This dialog opens
        at its full 720px (``_fit_floor``), so on a short step that spacer would
        be a wide mostly-empty band. The spacer therefore stays as the last item
        of every page - the page structure is guarded by tests - and:

        * step 1 is given a factor of 0 on its spacer and 1 on its two-card
          row, so both form cards stretch down to the page's bottom edge;
        * step 2 keeps the base behaviour: its spare height stays in the page's
          bottom spacer, so the consultation and the clinical section cards
          keep their natural height;
        * step 3 zeroes its spacer so its two lists take the whole remainder
          (see _setup_supplies_step);
        * step 4 zeroes its spacer and stretches the receipt card, so the
          billing bar is pinned to the bottom of the page while the card grows
          into the room.
        """
        super()._pad_step_pages()

        step_one = self.step_bodies[0]
        step_one.setStretch(0, 1)
        step_one.setStretch(step_one.count() - 1, 0)

        supplies = self.step_bodies[2]
        supplies.setStretch(supplies.count() - 1, 0)

        self._stretch_receipt_to_fill_the_step()

    def _stretch_receipt_to_fill_the_step(self):
        """Makes the receipt card the item that absorbs the billing step's room.

        The billing bar and the hint above it keep their natural height, so the
        bar lands on the bottom edge of the page instead of floating above it.
        """
        body = self.step_bodies[3]
        body.setStretch(body.count() - 1, 0)
        index = body.indexOf(self.receipt_frame)
        if index != -1:
            body.setStretch(index, 1)

    def _rebuild_receipt_card(self, *args, **kwargs):
        """Re-applies the receipt's stretch: a rebuild swaps in a new card.

        ``_rebuild_receipt_card`` inserts the fresh frame with a stretch of 0,
        which would hand the billing step's spare height back to the (now
        zero-stretch) spacer - and with nowhere to go, a gap under the billing
        bar.
        """
        super()._rebuild_receipt_card(*args, **kwargs)
        if getattr(self, "_step_pages_padded", False):
            self._stretch_receipt_to_fill_the_step()

    def _setup_billing_step(self):
        """Step 4 - the discount bar at the bottom of the page, under the receipt.

        It is a percentage, the same control the Edit Receipt dialog uses, so
        the two places a discount is typed always read alike; the receipt still
        shows the money it works out to. The spin is therefore not called
        ``discount_spin`` - the base class would read that as a cash amount and
        subtract the percentage figure as if it were dollars.
        """
        row = QHBoxLayout()
        row.setSpacing(STEP_CONTENT_SPACING)

        self.discount_percent_spin = QDoubleSpinBox()
        self.discount_percent_spin.setRange(0.0, 100.0)
        self.discount_percent_spin.setDecimals(2)
        self.discount_percent_spin.setSuffix(" %")
        self.discount_percent_spin.setSpecialValueText(tr("No discount"))
        self.discount_percent_spin.valueChanged.connect(self._update_total)
        row.addWidget(QLabel(tr("Discount:")))
        row.addWidget(self.discount_percent_spin)

        row.addSpacing(STEP_CONTENT_SPACING)

        # The amount actually handed over, defaulting to the (discounted) total
        # so an entry settles at the counter instead of on the Receipts page.
        self._paid_touched = False
        self.amount_paid_spin = QDoubleSpinBox()
        self.amount_paid_spin.setPrefix("$ ")
        self.amount_paid_spin.setRange(0.0, 999999.99)
        self.amount_paid_spin.setDecimals(2)
        self.amount_paid_spin.setFixedWidth(120)
        self.amount_paid_spin.valueChanged.connect(self._on_paid_changed)
        row.addWidget(QLabel(tr("Amount Paid:")))
        row.addWidget(self.amount_paid_spin)

        row.addSpacing(STEP_CONTENT_SPACING)

        row.addWidget(QLabel(tr("Method:")))
        self.pay_method_combo = QComboBox()
        self.pay_method_combo.addItems([tr("Cash"), tr("Card"), tr("Bank Transfer"), tr("Other")])
        self.pay_method_combo.setFixedWidth(110)
        row.addWidget(self.pay_method_combo)

        row.addStretch(1)

        row.addWidget(QLabel(tr("Total After Discount") + ":"))
        self.billing_total_label = QLabel(format_currency(0.0))
        self.billing_total_label.setProperty("class", "receipt-total")
        row.addWidget(self.billing_total_label)

        self.step_bodies[3].addLayout(row)

        self._billing_subtotal = 0.0
        self._billing_discount = 0.0
        self._billing_total = 0.0

    def _discount_cash(self, subtotal):
        """The percentage typed by the user expressed as money (to the cent)."""
        return round(subtotal * (self.discount_percent_spin.value() / 100.0), 2)

    def _on_paid_changed(self, _value):
        """Remembers a custom paid amount so the total stops overriding it."""
        self._paid_touched = True

    def payment_method(self):
        """The stored method for the combo (display index -> English value)."""
        return {0: "Cash", 1: "Card", 2: "Bank Transfer", 3: "Other"}.get(
            self.pay_method_combo.currentIndex(), "Cash")

    def _update_receipt(self, subtotal, discount, total):
        """Shared receipt refresh, plus the billing row under it.

        ``subtotal`` is everything billed. This dialog holds a percentage
        rather than the cash amount the base class would subtract, so the
        percentage is turned into money here.
        """
        subtotal = float(subtotal)
        cash = self._discount_cash(subtotal)
        total = max(0.0, subtotal - cash)
        super()._update_receipt(subtotal, cash, total)
        self._billing_subtotal = subtotal
        self._billing_discount = cash
        self._billing_total = total
        self.billing_total_label.setText(format_currency(total))

        if hasattr(self, "amount_paid_spin"):
            if not self._paid_touched:
                # Default: whatever the total is, that is what was paid.
                self.amount_paid_spin.blockSignals(True)
                self.amount_paid_spin.setMaximum(total)
                self.amount_paid_spin.setValue(total)
                self.amount_paid_spin.blockSignals(False)
            else:
                self.amount_paid_spin.setMaximum(total)

    def _update_save_state(self):
        self._found_owner = getattr(self, "_found_owner", None)
        self._found_pet = getattr(self, "_found_pet", None)
        """Disables proceeding until an owner name has been entered on step 1."""
        self._set_save_enabled(bool(self.owner_name.text().strip()))


    def _set_owner_status(self, exists):
        if exists:
            self.owner_status_label.setIcon(QIcon(str(ICONS_DIR / "caution.png")))
            self.owner_status_label.setToolTip(tr("Existing owner"))
        else:
            self.owner_status_label.setIcon(QIcon(str(ICONS_DIR / "new.png")))
            self.owner_status_label.setToolTip(tr("New owner"))

    def _set_pet_status(self, exists):
        if exists:
            self.pet_status_label.setIcon(QIcon(str(ICONS_DIR / "caution.png")))
            self.pet_status_label.setToolTip(tr("Existing pet"))
        else:
            self.pet_status_label.setIcon(QIcon(str(ICONS_DIR / "new.png")))
            self.pet_status_label.setToolTip(tr("New pet"))


    def _confirm_if_data_will_change(self):
        """Show confirmation if owner or pet data will be updated."""
        changed = False
        changes = []
        if getattr(self, '_found_owner', None):
            owner = self._found_owner
            new_name = self.owner_name.text().strip().title()
            new_phone = self.phone.text().strip()
            if new_name and new_name != owner.get('owner_name', '').title():
                changes.append(tr('Owner name will be updated'))
                changed = True
            if new_phone != (owner.get('phone_number') or ''):
                changes.append(tr('Owner phone will be updated'))
                changed = True
        if getattr(self, '_found_pet', None):
            pet = self._found_pet
            pet_name = self.pet_name.text().strip()
            if pet_name and pet_name != pet.get('pet_name', ''):
                changes.append(tr('Pet name will be updated'))
                changed = True
            # Check other pet fields
            if self.species.currentText() != (pet.get('species') or ''):
                changes.append(tr('Pet species will be updated'))
                changed = True
            if self.breed.text() != (pet.get('breed') or ''):
                changes.append(tr('Pet breed will be updated'))
                changed = True
            if (self.gender.currentData() or self.gender.currentText()) != (pet.get('gender') or ''):
                changes.append(tr('Pet gender will be updated'))
                changed = True
            try:
                old_age = int(pet.get('age_months') or 0)
                new_age = self.age.value()
                if old_age != new_age:
                    changes.append(tr('Pet age will be updated'))
                    changed = True
            except (TypeError, ValueError):
                pass
        if changed and changes:
            msg = tr("The following changes will be applied to existing records:") + "\n\n- " + "\n- ".join(changes) + "\n\n" + tr("Do you want to proceed?")
            reply = QMessageBox.question(self, tr("Confirm Update"), msg, QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return False
        return True


    def _on_owner_name_changed(self):
        self._set_owner_status(False)
        self._found_owner = None

    def _on_pet_name_changed(self):
        self._set_pet_status(False)
        self._found_pet = None

    def _on_owner_name_finished(self):
        name = self.owner_name.text().strip()
        if not name:
            self._set_owner_status(False)
            return
        # Try to find owner by name (exact match preferred) and maybe fill phone
        existing = client_repo.get_clients_by_name_exact(name)
        if existing:
            # If multiple with different phones, fill with the first or if single
            owner = existing[0]
            self._found_owner = owner
            self._set_owner_status(True)
            if not self.phone.text().strip() and owner.get("phone_number"):
                self.phone.setText(owner.get("phone_number"))
            # Update pet completer for this owner's pets
            client_id = owner.get("client_id")
            if client_id:
                pet_names = [p["pet_name"] for p in pet_repo.get_pets_for_client(client_id)]
                pet_completer = QCompleter(pet_names)
                pet_completer.setCaseSensitivity(Qt.CaseInsensitive)
                self.pet_name.setCompleter(pet_completer)
            # Also try to find matching pet if pet name is entered
            if self.pet_name.text().strip():
                self._on_pet_name_finished()
        else:
            self._set_owner_status(False)
            # Clear pet completer
            self.pet_name.setCompleter(None)

    def _on_pet_name_finished(self):
        pet_name = self.pet_name.text().strip()
        owner_name = self.owner_name.text().strip()
        if not pet_name or not owner_name:
            self._set_pet_status(False)
            return
        # Find client id
        client_id = None
        if self._found_owner:
            client_id = self._found_owner.get("client_id")
        else:
            existing = client_repo.get_clients_by_name_exact(owner_name)
            if existing:
                client_id = existing[0].get("client_id")
                self._found_owner = existing[0]
                self._set_owner_status(True)
                pet_names = [p["pet_name"] for p in pet_repo.get_pets_for_client(client_id)]
                pet_completer = QCompleter(pet_names)
                pet_completer.setCaseSensitivity(Qt.CaseInsensitive)
                self.pet_name.setCompleter(pet_completer)
        if not client_id:
            self._set_pet_status(False)
            return
        pets = pet_repo.get_pets_by_name_for_client(client_id, pet_name)
        if pets:
            pet = pets[0]
            self._found_pet = pet
            self._set_pet_status(True)
            # Fill pet fields - always overwrite when selecting existing pet
            if pet.get("species"):
                idx = self.species.findText(pet.get("species"))
                if idx >= 0:
                    self.species.setCurrentIndex(idx)
                else:
                    self.species.setCurrentText(pet.get("species"))
            if pet.get("breed"):
                self.breed.setText(pet.get("breed"))
            if pet.get("gender"):
                idx = self.gender.findData(pet.get("gender"))
                if idx >= 0:
                    self.gender.setCurrentIndex(idx)
                else:
                    self.gender.setCurrentText(pet.get("gender"))
            pet_age = pet.get("age_months")
            if pet_age is not None:
                try:
                    self.age.setValue(int(pet_age))
                except (TypeError, ValueError):
                    pass
            pet_weight = pet.get("weight")
            if pet_weight is not None:
                try:
                    self._pet_weight = float(pet_weight)
                except (TypeError, ValueError):
                    self._pet_weight = 0.0
        else:
            self._set_pet_status(False)

    def handle_accept(self):
        """Validates input, then calls the clinical service to persist everything."""
        if not self.owner_name.text():
            QMessageBox.warning(self, tr("Error"), tr("Owner name is required."))
            return

        if not self.pet_name.text().strip():
            QMessageBox.warning(self, tr("Error"), tr("No pet selected."))
            return

        # Refresh the totals so the discount written below is the one on the
        # receipt the user is looking at.
        self._update_total()

        name_input = self.owner_name.text().strip().title()
        phone_input = self.phone.text().strip()

        merge_id = None

        # Check for exact match (Name + Phone) to offer merging
        existing_clients = client_repo.get_clients_by_name_exact(name_input)
        for client in existing_clients:
            if client['phone_number'] == phone_input:
                msg = tr(
                    "Owner '{owner}' with phone '{phone}' already exists. "
                    "Do you want to merge this entry into their existing record?"
                ).format(owner=name_input, phone=phone_input)
                if QMessageBox.question(
                    self, tr("Duplicate Owner Name"), msg,
                    QMessageBox.Yes | QMessageBox.No
                ) == QMessageBox.Yes:
                    merge_id = client['client_id']
                    break
                else:
                    return  # Cancel addition

        # Only prepare pet details if a name is provided
        pet_name_input = self.pet_name.text().strip()
        pet_data = None
        if pet_name_input:
            pet_data = {
                'name': pet_name_input,
                'species': self.species.currentText(),
                'breed': self.breed.text(),
                'gender': self.gender.currentData() or self.gender.currentText(),
                'age': self.age.value(),
                'weight': self._pet_weight
            }

        clinical_exam = self.get_clinical_exam_data()

        # Call the Service
        visit_date_str = self.v_date.dateTime().toString(DATE_TIME_FORMAT)
        saved_ids = {}
        success, result = clinical_service.process_full_clinical_entry(
            owner_data={
                'name': name_input,
                'phone': phone_input,
                'merge_id': merge_id,
            },
            pet_data=pet_data,
            visit_data={
                'date': visit_date_str,
                'reason_for_visit': self.reason.text().strip(),
                'diagnosis': self.diagnosis.text(),
                'is_consult': 1 if self.consult.isChecked() else 0,
                'notes': self.notes.toPlainText(),
                'discount': self._billing_discount,
                'paid_amount': self.amount_paid_spin.value(),
                'payment_notes': tr("Paid at entry"),
                'payment_method': self.payment_method(),
            },
            items=self.get_final_items(),
            clinical_exam=clinical_exam,
            current_user=self._current_user,
            packages=self.get_final_packages(),
            ids_out=saved_ids,
        )

        # Remember what to print from the success box; None when the visit
        # was not billable, so no receipt exists to show.
        self._saved_receipt_id = saved_ids.get("receipt_id")

        if not success:
            if not self.handle_stock_error(result):
                QMessageBox.critical(self, tr("Error"), str(result))
            return

        if self.followup_group.isChecked() and pet_data:
            followup_id = clinical_service.schedule_followup_after_entry(
                name_input,
                phone_input,
                visit_date_str,
                self.followup_date.dateTime().toString(DATE_TIME_FORMAT),
                notes=self.followup_notes.text().strip(),
            )
            if not followup_id:
                QMessageBox.warning(
                    self,
                    tr("Follow-up Warning"),
                    tr("The visit was saved, but the follow-up could not be scheduled."),
                )

        msg = tr("Record added successfully.")
        if result and isinstance(result, dict) and 'receipt_id' in result:
            msg += tr("\n\nReceipt ID: {receipt_id}").format(receipt_id=result['receipt_id'])
        self._show_success(msg)
        self.accept()

    def _show_success(self, msg):
        """Confirmation after a successful save.

        Offers OK to close and Print, which prints the client copy of the
        saved receipt (see _print_receipt).
        """
        box = QMessageBox(QMessageBox.Information, tr("Success"), str(msg),
                          QMessageBox.Ok, self)
        print_btn = box.addButton(tr("Print"), QMessageBox.ActionRole)
        box.setDefaultButton(QMessageBox.Ok)
        box.exec_()
        if box.clickedButton() is print_btn:
            self._print_receipt()

    def _print_receipt(self):
        """Prints the saved receipt exactly like Print for Client does.

        Delegates to ``ReceiptInfoDialog.print_for_client`` so the wizard
        hands out the same client copy under the same rule: a receipt that
        is not fully paid is refused with the Receipts page's message and
        nothing is printed. A visit with no receipt (nothing billed) falls
        back to the step-4 preview.
        """
        if not self._saved_receipt_id:
            super(AddFullEntryDialog, self)._print_receipt()
            return
        # Local import: the receipt page pulls in the whole pages package,
        # and the wizard must not drag that in at import time.
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        info = ReceiptInfoDialog(self._saved_receipt_id, parent=self,
                                 current_user=self._current_user)
        try:
            info.print_for_client(parent=self)
        finally:
            info.setParent(None)
            info.deleteLater()


    def _go_next_step(self):
        if self._current_step == 0:
            if not self._confirm_if_data_will_change():
                return
        # Collapse the Clinical Exam accordion when leaving step 2, so step 3
        # opens tidy instead of inheriting six expanded record-book sections.
        if self._current_step == 1:
            cards = getattr(self, "_record_cards", None)
            if cards:
                for card in cards.values():
                    card.setChecked(False)
                # The collapsed page is about to be hidden; hidden pages do not
                # relayout, so its cached height would keep the stacked widget
                # tall until the page is visited again. Force the still-visible
                # page to re-measure now, or the sections only *look* collapsed
                # after the user steps back to them.
                page = self._steps_widget.widget(self._current_step)
                page.layout().invalidate()
                page.adjustSize()
        super(AddFullEntryDialog, self)._go_next_step()
