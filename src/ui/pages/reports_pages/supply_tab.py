"""
Supply Report tab.
KPI cards, supply usage analytics, inventory insights and supplies charts.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from src.utils.i18n import tr
from src.ui.pages.reports_pages.base_tab import BaseReportTab


class SupplyTab(BaseReportTab):
    """Supply report: Supply Usage + inventory insights + supplies charts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kpi_titles = True
        self._build_performance()
        self._build_insights()
        self.content_layout.addWidget(self.supply_charts_widget)

    # ----------------------------------------- sections ---------------------------------------- #

    def _build_performance(self):
        """Supply Usage row — Supply Usage table."""
        section_bar, self.performance_section_title = self._make_section_title_bar(tr("Supply Usage"))
        self.content_layout.addWidget(section_bar)

        tables_row = QHBoxLayout()
        tables_row.setContentsMargins(4, 0, 4, 0)
        tables_row.setSpacing(16)

        usage_card, self.supply_usage_table, self.supply_usage_title = self._create_analytics_table_card(
            tr("Supply Usage"), [tr("Item"), tr("Category"), tr("Quantity")]
        )

        tables_row.addWidget(usage_card)
        card_holder = QWidget()
        card_holder.setObjectName("reports_cards_widget")
        card_holder.setLayout(tables_row)
        self.second_row_widget = card_holder
        self.content_layout.addWidget(card_holder)

    def _build_insights(self):
        """Inventory Insights row — low stock, expiring and top sellers."""
        section_bar, self.insights_section_title = self._make_section_title_bar(tr("Operational Insights"))
        self.content_layout.addWidget(section_bar)

        tables_row = QHBoxLayout()
        tables_row.setContentsMargins(4, 0, 4, 0)
        tables_row.setSpacing(16)

        card_low, self.low_stock_value, self.low_stock_card_title = self._create_kpi_card(tr("Low Stock Supplies"))
        exp_card, self.expiring_table, self.expiring_title = self._create_insight_table_card(tr("Expiring Soon (30d)"), [tr("Item"), tr("Category"), tr("Date")])
        top_card, self.top_selling_table, self.top_selling_title = self._create_insight_table_card(tr("Top Selling Items"), [tr("Item"), tr("Category"), tr("Sold")])

        tables_row.addWidget(card_low)
        tables_row.addWidget(exp_card)
        tables_row.addWidget(top_card)
        card_holder = QWidget()
        card_holder.setObjectName("reports_cards_widget")
        card_holder.setLayout(tables_row)
        self.third_row_widget = card_holder
        self.content_layout.addWidget(card_holder)

    # ----------------------------------------- refresh ---------------------------------------- #

    def _refresh_this_tab_charts(self):
        self._refresh_supply_charts_content()

    def refresh_data(self):
        if getattr(self, "viewing_archive", False):
            return
        self._refresh_performance_widgets()
        self._refresh_insights()
        self._refresh_this_tab_charts()
        self._rebuild_chart_grid_map()

    # ----------------------------------------- translation ---------------------------------------- #

    def retranslate_ui(self):
        super().retranslate_ui()
        if hasattr(self, "performance_section_title"):
            self.performance_section_title.setText(tr("Supply Usage"))