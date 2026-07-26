"""
Audit Log Report tab.
Recent change-history table backed by the audit repository.
"""

from PyQt5.QtWidgets import QTableWidgetItem

import src.core.repositories.audit_repo as audit_repo
from src.utils.i18n import tr
from src.ui.pages.reports_pages.base_tab import BaseReportTab, LAYOUT_CONFIG


class AuditTab(BaseReportTab):
    """Audit report shown on the Audit Log Report tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kpi_titles = True
        self._build_audit_report()

    # ----------------------------------------- sections ---------------------------------------- #

    def _build_audit_report(self):
        """Creates the table used by the Audit Log report category."""
        section_bar, self.audit_section_title = self._make_section_title_bar(tr("Audit Log"))
        self.content_layout.addWidget(section_bar)

        card, self.audit_table, _ = self._make_table_card(
            tr("Audit Log"),
            [tr("ID"), tr("User"), tr("Table"), tr("Record ID"), tr("Changed At"), tr("Details")],
            LAYOUT_CONFIG["analytics_table_height"],
            320,
        )
        # Keep the meta columns narrow; let the Details column take the rest so
        # the change content is visible without clipping.
        header = self.audit_table.horizontalHeader()
        header.setSectionResizeMode(header.Interactive)
        for column, width in ((0, 48), (1, 110), (2, 120), (3, 80), (4, 175)):
            self.audit_table.setColumnWidth(column, width)
        header.setSectionResizeMode(5, header.Stretch)

        self.audit_empty_label = self._card_empty_labels[self.audit_table]
        self.content_layout.addWidget(card)

    # ----------------------------------------- refresh ---------------------------------------- #

    def refresh_report(self):
        """Loads the latest audit entries for the Audit report view."""
        rows = audit_repo.get_recent_changes_with_details(limit=200)
        self.audit_table.setRowCount(len(rows))
        self.audit_empty_label.setVisible(not rows)
        for row_index, entry in enumerate(rows):
            message = audit_repo.format_audit_message(entry)
            values = [
                entry.get("change_header_id", ""),
                entry.get("username", "") or tr("Unknown"),
                entry.get("table_name", ""),
                entry.get("record_id", ""),
                entry.get("changed_at", ""),
                message,
            ]
            for column, value in enumerate(values):
                self.audit_table.setItem(row_index, column, QTableWidgetItem(str(value)))
            summary_item = self.audit_table.item(row_index, 5)
            summary_item.setToolTip(message)

    def refresh_data(self):
        if getattr(self, "viewing_archive", False):
            return
        self.refresh_report()

    # ----------------------------------------- translation ---------------------------------------- #

    def retranslate_ui(self):
        super().retranslate_ui()
        if hasattr(self, "audit_section_title"):
            self.audit_section_title.setText(tr("Audit Log"))
        self._relabel_table_header(
            "audit_table",
            ["ID", "User", "Table", "Record ID", "Changed At", "Details"],
        )
        if hasattr(self, "audit_empty_label"):
            self.audit_empty_label.setText(tr("No audit records available. Changes will appear here after audited actions."))