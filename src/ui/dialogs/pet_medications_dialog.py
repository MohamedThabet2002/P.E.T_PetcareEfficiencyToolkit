"""
Pet Medications Dialog for the PET Application.
Displays a pet's prescribed medications grouped by visit, one section per visit.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QWidget,
)

import src.core.repositories.medication_repo as medication_repo
from src.ui.themes.color_palettes import get_active_palette
from src.utils.i18n import tr


class PetMedicationsDialog(QDialog):
    """Read-only dialog showing the medications history grouped by visit."""

    def __init__(self, pet_id, pet_name, parent=None):
        super().__init__(parent)
        self._pet_id = pet_id
        self._pet_name = pet_name or tr("Pet")
        self.setWindowTitle(tr("Pet Medications — {name}").format(name=self._pet_name))
        self.setMinimumSize(660, 560)
        self._setup_ui()
        self._load_medications()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel(tr("Medications for <b>{name}</b>").format(name=self._pet_name))
        title.setProperty("class", "dialog-title")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(10)
        self._body.addStretch()
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _load_medications(self):
        rows = medication_repo.get_medication_history_by_visit(self._pet_id)

        if not rows:
            empty = QLabel(tr("No medications recorded"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setProperty("class", "empty-label")
            self._body.insertWidget(0, empty)
            return

        sections = {}
        for med in rows:
            visit_id = med.get("visit_id")
            sections.setdefault(visit_id, []).append(med)

        first = True
        for visit_id, meds in sections.items():
            if not first:
                self._body.insertWidget(self._body.count() - 1, self._spacer())
            section = self._build_section(visit_id, meds)
            self._body.insertWidget(self._body.count() - 1, section)
            first = False

    @staticmethod
    def _spacer():
        return QWidget()

    def _build_section(self, visit_id, meds):
        palette = get_active_palette()
        accent = palette.get("brand_500", "#4A90E2")

        card = QFrame()
        card.setProperty("class", "info-card")
        card.setObjectName("medSection")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        first = meds[0]
        date = str(first.get("visit_date") or "")[:10] or tr("N/A")
        diagnosis = first.get("diagnosis") or ""
        header_text = date
        if diagnosis:
            header_text += "  ·  " + diagnosis
        header = QLabel(header_text)
        header.setStyleSheet("font-weight: bold; font-size: 11pt; color: %s;" % accent)
        layout.addWidget(header)

        visit_line = QLabel(tr("Visit #{visit_id}").format(visit_id=visit_id))
        visit_line.setProperty("class", "muted-label")
        layout.addWidget(visit_line)

        for med in meds:
            item_name = med.get("item_name") or tr("Medication")
            dosage = med.get("dosage") or ""
            instructions = med.get("instructions") or ""

            name_label = QLabel("<b>%s</b>" % item_name)
            layout.addWidget(name_label)

            detail_parts = []
            if dosage:
                detail_parts.append(tr("Dosage: {value}").format(value=dosage))
            if instructions:
                detail_parts.append(tr("Instructions: {value}").format(value=instructions))
            if detail_parts:
                detail = QLabel("  ·  ".join(detail_parts))
                detail.setWordWrap(True)
                detail.setProperty("class", "muted-label")
                layout.addWidget(detail)

        return card