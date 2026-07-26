"""
Visit Dialogs for the PET Application.

Provides dialog classes for adding and editing individual medical visits:
- AddVisitDialog: Create a new visit record for an existing client/pet.
"""

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QLineEdit, QListView,
    QMessageBox, QScrollArea, QTextEdit, QCompleter,
    QVBoxLayout, QDoubleSpinBox, QToolButton, QWidget
)
from PyQt5.QtCore import Qt, QDateTime, QSize
from PyQt5.QtGui import QIcon

import src.core.repositories.client_repo as client_repo
import src.core.repositories.pet_repo as pet_repo
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.visit_repo as visit_repo
import src.core.repositories.user_repo as user_repo
from src.config.constants import DEFAULT_CONSULT_FEE
from src.config.paths import ICONS_DIR
from src.modules.receipt_card import build_receipt_card
from src.utils.settings_manager import SettingsManager
from src.utils.i18n import tr
from src.ui.dialogs.base_clinical_dialog import BaseClinicalDialog, ClinicalSectionsMixin, NOTES_BOX_HEIGHT

#==================================== CONSTANTS =======================================================#

ADD_VISIT_DIALOG_WIDTH = 960
ADD_VISIT_DIALOG_HEIGHT = 680

DATE_TIME_FORMAT = "yyyy-MM-dd HH:mm"


class ReceiptDetailsDialog(QDialog):
    """Displays a saved receipt on the shared receipt card.

    Same card as Receipt Details and the Add Visit preview (client copy: no
    payment strip), so a style or feature change made once lands here too.
    ``visit_date`` / ``client_name`` are only fallbacks for an id that is
    not in the database.
    """

    def __init__(self, receipt_id, visit_date, client_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Receipt Details"))
        # The shared card is 480px wide; do not clip it.
        self.setMinimumSize(530, 320)
        self.resize(550, 380)

        header = sales_repo.get_receipt(receipt_id) or {}
        if not header:
            header = {"receipt_date": visit_date, "owner_name": client_name}
        items = sales_repo.get_receipt_line_items(receipt_id)
        card = build_receipt_card(
            header, items,
            float(header.get("discount") or 0),
            float(header.get("total_price") or 0),
            receipt_id=receipt_id,
            client=True,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # The shared card never scrolls internally (fit_receipt_items_table
        # pins a long receipt to its rows), so the surrounding scroll area
        # reaches what sits below the fold - same rule as every other surface.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(card.frame, 0, Qt.AlignHCenter)
        body.addStretch(1)
        scroll.setWidget(content)
        # Force the scroll area to re-measure the full card immediately (a
        # stale extent would paint a long receipt clipped with no scrollbar).
        body.activate()
        content.adjustSize()
        scroll.updateGeometry()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class AddVisitDialog(BaseClinicalDialog, ClinicalSectionsMixin):
    """Dialog for adding a new visit record to an existing client/pet."""

    def __init__(self, parent=None, current_user=None):
        super().__init__(tr("Add Visit"), (ADD_VISIT_DIALOG_WIDTH, ADD_VISIT_DIALOG_HEIGHT), parent)
        self._current_user = current_user
        self._setup_fields()
        self._setup_receipt(self.step_bodies[3])
        self._update_total()
        self._update_save_state()

    def _setup_fields(self):
        self._start_wizard([
            "Patient & Visit",
            "Clinical Exam",
            "Other Supplies",
            "Billing & Review",
        ])

        # ── Step 1 · Patient & Visit ──
        self.visit_date = QDateTimeEdit(calendarPopup=True)
        self.visit_date.setDateTime(QDateTime.currentDateTime())
        self.visit_date.setDisplayFormat(DATE_TIME_FORMAT)

        self.client_selector = QComboBox()
        self.client_selector.setView(QListView())
        self.client_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.client_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.client_selector.setEditable(True)
        self.client_selector.setInsertPolicy(QComboBox.NoInsert)
        self.client_selector.completer().setFilterMode(Qt.MatchContains)
        self.client_selector.setPlaceholderText(tr("Select Client..."))
        for c in client_repo.get_clients():
            display_text = f"{c['owner_name']} ({c['phone_number']})" if c['phone_number'] else c['owner_name']
            self.client_selector.addItem(display_text, c["client_id"])
        self.client_selector.setCurrentIndex(-1)

        self.pet_selector = QComboBox()
        self.pet_selector.setView(QListView())
        self.pet_selector.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.pet_selector.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.pet_selector.setEditable(True)
        self.pet_selector.setInsertPolicy(QComboBox.NoInsert)
        self.pet_selector.completer().setFilterMode(Qt.MatchContains)
        self.pet_selector.setPlaceholderText(tr("Select Pet..."))

        # Icon indicators keep the compact selector rows readable while remaining accessible.
        self.client_status_label = QToolButton()
        self.client_status_label.setAutoRaise(True)
        self.client_status_label.setFixedSize(28, 28)
        self.client_status_label.setIconSize(QSize(20, 20))
        client_row = QHBoxLayout()
        client_row.addWidget(self.client_selector, 1)
        client_row.addWidget(self.client_status_label)

        self.pet_status_label = QToolButton()
        self.pet_status_label.setAutoRaise(True)
        self.pet_status_label.setFixedSize(28, 28)
        self.pet_status_label.setIconSize(QSize(20, 20))
        pet_row = QHBoxLayout()
        pet_row.addWidget(self.pet_selector, 1)
        pet_row.addWidget(self.pet_status_label)

        self.form.addRow(tr("Date:") + ":", self.visit_date)
        self.form.addRow(tr("Owner Name") + "*:", client_row)
        self.form.addRow(tr("Pet Name") + ":", pet_row)

        self._add_section_header("VISIT DETAILS")
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

        self.form.addRow(tr("Reason for Visit") + ":", self.reason)
        self.form.addRow(tr("Diagnosis") + ":", self.diagnosis)
        self.form.addRow(tr("Notes") + ":", self.notes)

        # ── Step 2 · Clinical Exam ──
        self.form = self.step_forms[1]
        fee = SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE)
        self.consult = QCheckBox(f"{tr('Consult Charge Applied?')} (${fee})")
        self._make_toggle_card("Consultation", self.consult, self.step_bodies[1])

        # Add clinical sections below the exam fields
        self._setup_clinical_sections(self.step_bodies[1])

        # ── Step 3 · Other Supplies ──
        self._setup_supplies_section(self.step_bodies[2])
        self._setup_packages_section(self.step_bodies[2])

        # ── Step 4 · Billing & Review (discount, then the receipt) ──
        self.discount_spin = QDoubleSpinBox()
        self.discount_spin.setRange(0.0, 99999.0)
        self.discount_spin.setPrefix("$ ")
        self.step_forms[3].addRow(tr("Discount") + ":", self.discount_spin)

        # Connections
        self.client_selector.currentIndexChanged.connect(self._update_pets)
        self.client_selector.currentIndexChanged.connect(self._update_save_state)
        self.consult.toggled.connect(self._update_total)
        self.discount_spin.valueChanged.connect(self._update_total)

        self._update_pets()

    def _update_save_state(self):
        """Disables proceeding until a client (owner) has been selected on step 1."""
        self._set_save_enabled(self.client_selector.currentData() is not None)

    def _update_pets(self):
        self.pet_selector.clear()
        self.pet_selector.setPlaceholderText(tr("Select Pet..."))
        cid = self.client_selector.currentData()
        if cid:
            self.client_status_label.setIcon(QIcon(str(ICONS_DIR / "check.png")))
            self.client_status_label.setToolTip(tr("Existing client selected"))
            for p in pet_repo.get_pets_for_client(cid):
                self.pet_selector.addItem(p['pet_name'], p["pet_id"])
        else:
            self.client_status_label.setIcon(QIcon(str(ICONS_DIR / "clients.png")))
            self.client_status_label.setToolTip(tr("Select a client"))
        self.pet_selector.setCurrentIndex(-1)
        self._update_pet_status()

    def _update_pet_status(self):
        pid = self.pet_selector.currentData()
        if pid:
            self.pet_status_label.setIcon(QIcon(str(ICONS_DIR / "check.png")))
            self.pet_status_label.setToolTip(tr("Existing pet selected"))
        else:
            self.pet_status_label.setIcon(QIcon(str(ICONS_DIR / "visits.png")))
            self.pet_status_label.setToolTip(tr("Select a pet"))

    def handle_accept(self):
        cid = self.client_selector.currentData()
        pid = self.pet_selector.currentData()
        if not cid:
            QMessageBox.warning(self, tr("Error"), tr("Owner selection is required."))
            return

        items = self.get_final_items()
        is_consult = self.consult.isChecked()
        clinical_data = self.get_clinical_data()

        result = visit_repo.add_visit(
            self.visit_date.dateTime().toString(DATE_TIME_FORMAT),
            self.diagnosis.text().strip().capitalize(),
            1 if is_consult else 0,
            self.notes.toPlainText().strip().capitalize(),
            pet_id=pid,
            items=items,
            client_id=cid,
            reason_for_visit=self.reason.text().strip(),
            health_stats=clinical_data["health_stats"],
            tests=clinical_data["tests"],
            treatments=clinical_data["treatments"],
            vaccinations=clinical_data["vaccinations"],
            medications=clinical_data["medications"],
            doctor_id=user_repo.get_doctor_id(self._current_user),
            discount=self.discount_spin.value() if hasattr(self, "discount_spin") else 0.0,
            audit_user_id=(self._current_user or {}).get("user_id"),
            packages=self.get_final_packages(),
        )

        if not self.handle_stock_error(result):
            if result:
                msg = tr("Record added successfully.")
                if is_consult or items:
                    msg += tr("\n\nReceipt ID: {receipt_id}").format(receipt_id=result)
                    reply = QMessageBox.information(
                        self, tr("Success"), msg + tr("\n\nDo you want to view the receipt?"),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        ReceiptDetailsDialog(
                            result,
                            self.visit_date.dateTime().toString(DATE_TIME_FORMAT),
                            self.client_selector.currentText(),
                            self,
                        ).exec_()
                else:
                    QMessageBox.information(self, tr("Success"), msg)
            else:
                QMessageBox.critical(self, tr("Critical Error"), tr("Failed to save record to database."))
                return
            self.accept()
