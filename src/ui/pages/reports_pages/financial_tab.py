"""
Financial Report tab.
Outstanding-balance KPIs, unpaid receipts tracking, and a revenue-by-category
breakdown (table + donut chart). No page owns more than one copy of the shared
Revenue by Category table, and this tab owns it exclusively.
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from src.utils.i18n import tr
from src.utils.formatters import format_currency
from src.core.repositories import analytics_repo
from src.ui.themes.color_palettes import get_active_palette
from src.modules.charts import PieChart
from src.ui.pages.reports_pages.base_tab import BaseReportTab


class FinancialTab(BaseReportTab):
    """Revenue report: owns Revenue by Category and Unpaid Receipts tables."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kpi_titles = True
        self._donut_layout = None
        self._build_unpaid_kpis()
        self._build_unpaid()
        self._build_revenue()
        self._refresh_this_tab_charts()

    # ----------------------------------------- sections ---------------------------------------- #

    def _build_unpaid_kpis(self):
        """KPI row for outstanding balance overview."""
        section_bar, self.unpaid_section_title = self._make_section_title_bar(tr("Unpaid Receipts"))
        self.content_layout.addWidget(section_bar)

        cards_widget = QWidget()
        cards_widget.setObjectName("reports_cards_widget")
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(4, 0, 4, 0)
        cards_layout.setSpacing(16)

        card_total, self.outstanding_value, self.outstanding_title = self._create_kpi_card(
            tr("Total Outstanding"))
        card_count, self.unpaid_count_value, self.unpaid_count_title = self._create_kpi_card(
            tr("Unpaid Receipts"))
        card_avg, self.avg_outstanding_value, self.avg_outstanding_title = self._create_kpi_card(
            tr("Avg Outstanding"))

        cards_layout.addWidget(card_total)
        cards_layout.addWidget(card_count)
        cards_layout.addWidget(card_avg)
        self.unpaid_kpi_widget = cards_widget
        self.content_layout.addWidget(cards_widget)

    def _build_unpaid(self):
        """Unpaid Receipts table showing outstanding balances."""
        unpaid_card, self.unpaid_receipts_table, self.unpaid_table_title = self._create_analytics_table_card(
            tr("Unpaid Receipts"),
            [tr("Receipt"), tr("Owner"), tr("Date"), tr("Total"), tr("Paid"), tr("Outstanding")],
        )
        self.content_layout.addWidget(unpaid_card)

    def _build_revenue(self):
        """Revenue Analysis row — Revenue by Category table + donut chart."""
        section_bar, self.performance_section_title = self._make_section_title_bar(tr("Revenue by Category"))
        self.content_layout.addWidget(section_bar)

        tables_row = QHBoxLayout()
        tables_row.setContentsMargins(4, 0, 4, 0)
        tables_row.setSpacing(16)

        rev_card, self.revenue_by_category_table, self.revenue_by_category_title = self._create_analytics_table_card(
            tr("Revenue by Category"), [tr("Category"), tr("Revenue")]
        )
        tables_row.addWidget(rev_card)

        # Donut slot: the chart container is rebuilt on every refresh/theme change.
        self._donut_holder = QWidget()
        self._donut_holder.setObjectName("reports_charts_widget")
        self._donut_layout = QVBoxLayout(self._donut_holder)
        self._donut_layout.setContentsMargins(0, 0, 0, 0)
        self._donut_layout.setSpacing(0)
        tables_row.addWidget(self._donut_holder)

        cards_widget = QWidget()
        cards_widget.setObjectName("reports_cards_widget")
        cards_widget.setLayout(tables_row)
        self.second_row_widget = cards_widget
        self.content_layout.addWidget(cards_widget)

    # ----------------------------------------- refresh ---------------------------------------- #

    def _refresh_this_tab_charts(self):
        """Rebuilds the Revenue Split donut for the active range/theme."""
        if self._donut_layout is None:
            return
        self.setUpdatesEnabled(False)
        try:
            self.chart_widgets.clear()
            while self._donut_layout.count():
                item = self._donut_layout.takeAt(0)
                if item.widget():
                    self._detach_orphan_widget(item.widget())

            start, end = self.current_range()
            rows = analytics_repo.get_revenue_by_category_range(start, end)
            data = {str(cat): float(amount) for cat, amount in rows}

            chart = PieChart(data=data, title="", palette=get_active_palette(), hole_size=0.45)
            container = self._create_chart_with_controls(tr("Revenue Split"), chart)
            self._donut_layout.addWidget(container)
            self.chart_widgets.append(chart)
            self._chart_container_map["revenue_donut"] = container
        finally:
            self.setUpdatesEnabled(True)
            if self.layout():
                self.layout().activate()

    def refresh_data(self):
        if getattr(self, "viewing_archive", False):
            return
        self._refresh_performance_widgets()
        self._refresh_unpaid()
        self._refresh_this_tab_charts()

    def _refresh_unpaid(self):
        start, end = self.current_range()
        rows = analytics_repo.get_unpaid_receipts_range(start, end)

        total_outstanding = sum(r[5] for r in rows)
        avg_outstanding = (total_outstanding / len(rows)) if rows else 0.0
        self.outstanding_value.setText(format_currency(total_outstanding))
        self.unpaid_count_value.setText(str(len(rows)))
        self.avg_outstanding_value.setText(format_currency(avg_outstanding))

        formatted = [
            [
                f"#{r[0]}",
                r[1],
                r[2],
                format_currency(r[3]),
                format_currency(r[4]),
                format_currency(r[5]),
            ]
            for r in rows
        ]
        self._set_table_rows(self.unpaid_receipts_table, formatted)

    # ----------------------------------------- translation ---------------------------------------- #

    def retranslate_ui(self):
        super().retranslate_ui()
        if hasattr(self, "unpaid_section_title"):
            self.unpaid_section_title.setText(tr("Unpaid Receipts"))
        if hasattr(self, "outstanding_title"):
            self.outstanding_title.setText(tr("Total Outstanding"))
        if hasattr(self, "unpaid_count_title"):
            self.unpaid_count_title.setText(tr("Unpaid Receipts"))
        if hasattr(self, "avg_outstanding_title"):
            self.avg_outstanding_title.setText(tr("Avg Outstanding"))
        if hasattr(self, "performance_section_title"):
            self.performance_section_title.setText(tr("Revenue by Category"))
        if hasattr(self, "unpaid_table_title"):
            self.unpaid_table_title.setText(tr("Unpaid Receipts"))