"""
Patient Report tab.
Visit-by-doctor analytics, diagnosis insights, clinical summary and trend charts.
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout

import src.core.repositories.analytics_repo as analytics_repo
from src.utils.i18n import tr
from src.ui.pages.reports_pages.base_tab import BaseReportTab, LAYOUT_CONFIG


class PatientTab(BaseReportTab):
    """Patient report: Visits by Doctor + Monthly Diagnoses + Clinical Activity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kpi_titles = True
        self._build_performance()
        self._build_insights()
        self._build_clinical()

    # ----------------------------------------- sections ---------------------------------------- #

    def _build_performance(self):
        """Doctor Performance row — Visits by Doctor table."""
        section_bar, self.performance_section_title = self._make_section_title_bar(tr("Visits by Doctor"))
        self.content_layout.addWidget(section_bar)

        tables_row = QHBoxLayout()
        tables_row.setContentsMargins(4, 0, 4, 0)
        tables_row.setSpacing(16)

        doctor_card, self.visits_by_doctor_table, self.visits_by_doctor_title = self._create_analytics_table_card(
            tr("Visits by Doctor"), [tr("Doctor"), tr("Visits")]
        )

        tables_row.addWidget(doctor_card)
        card_holder = QWidget()
        card_holder.setObjectName("reports_cards_widget")
        card_holder.setLayout(tables_row)
        self.second_row_widget = card_holder
        self.content_layout.addWidget(card_holder)

    def _build_insights(self):
        """Diagnoses row — Monthly Diagnoses table."""
        section_bar, self.insights_section_title = self._make_section_title_bar(tr("Monthly Diagnoses"))
        self.content_layout.addWidget(section_bar)

        tables_row = QHBoxLayout()
        tables_row.setContentsMargins(4, 0, 4, 0)
        tables_row.setSpacing(16)

        diag_card, self.diagnosis_table, self.diagnosis_title = self._create_insight_table_card(tr("Monthly Diagnoses"), [tr("Diagnosis"), tr("Count")])

        tables_row.addWidget(diag_card)
        card_holder = QWidget()
        card_holder.setObjectName("reports_cards_widget")
        card_holder.setLayout(tables_row)
        self.third_row_widget = card_holder
        self.content_layout.addWidget(card_holder)

    def _build_clinical(self):
        """Clinical activity table summarizing visits/follow-ups per doctor."""
        section_bar, self.clinical_section_title = self._make_section_title_bar(tr("Clinical Activity By Doctor"))
        self.content_layout.addWidget(section_bar)

        card, self.clinical_table, _ = self._make_table_card(
            tr("Clinical Activity By Doctor"),
            [tr("Doctor"), tr("Visits"), tr("Follow-ups"), tr("Unassigned Visits")],
            LAYOUT_CONFIG["analytics_table_height"],
            260,
        )
        self.clinical_empty_label = self._card_empty_labels[self.clinical_table]
        self.content_layout.addWidget(card)

    def _refresh_clinical(self):
        """Loads visit and follow-up totals grouped by assigned doctor."""
        rows = analytics_repo.get_clinical_activity_summary()
        self._set_table_rows(self.clinical_table, rows)

    # ----------------------------------------- refresh ---------------------------------------- #

    def refresh_data(self):
        if getattr(self, "viewing_archive", False):
            return
        self._refresh_performance_widgets()
        self._refresh_insights()
        self._refresh_clinical()

    # ----------------------------------------- translation ---------------------------------------- #

    def retranslate_ui(self):
        super().retranslate_ui()
        if hasattr(self, "performance_section_title"):
            self.performance_section_title.setText(tr("Visits by Doctor"))
        if hasattr(self, "insights_section_title"):
            self.insights_section_title.setText(tr("Monthly Diagnoses"))
        if hasattr(self, "clinical_section_title"):
            self.clinical_section_title.setText(tr("Clinical Activity By Doctor"))
        self._relabel_table_header(
            "clinical_table",
            ["Doctor", "Visits", "Follow-ups", "Unassigned Visits"],
        )
        if hasattr(self, "clinical_empty_label"):
            self.clinical_empty_label.setText(tr("No clinical activity available."))