"""
Overview Analytics report tab.
Executive snapshot: KPI rows (with previous-period trend pills), Top Clients
table and the trend charts (their only owner across the reports center).
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel

from src.utils.i18n import tr
import src.core.repositories.analytics_repo as analytics_repo
from src.ui.pages.reports_pages.base_tab import BaseReportTab


class OverviewTab(BaseReportTab):
    """Executive snapshot: KPI cards + Top Clients table + the trend charts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kpi_titles = True
        self._build_kpis()
        self._build_top_clients()
        self.content_layout.addWidget(self.trend_charts_widget)

    # ----------------------------------------- sections ---------------------------------------- #

    def _build_kpis(self):
        """Business Overview: two rows of KPI cards with trend pills."""
        section_bar, self.overview_section_title = self._make_section_title_bar(tr("Business Overview"))
        self.content_layout.addWidget(section_bar)

        # --- Row 1: core volume KPIs ---
        cards_row1 = QWidget()
        cards_row1.setObjectName("reports_cards_widget")
        row1_layout = QHBoxLayout(cards_row1)
        row1_layout.setContentsMargins(4, 0, 4, 0)
        row1_layout.setSpacing(16)

        card_visits, self.total_visits_value, self.visits_info_card_title = self._create_kpi_card(
            tr("Total Visits"), value_key="total_visits_value", icon="◉")
        card_revenue, self.total_revenue_value, self.total_revenue_card_title = self._create_kpi_card(
            tr("Total Revenue"), value_key="total_revenue_value", icon="$")
        card_supplies, self.total_supplies_value, self.supplies_card_title = self._create_kpi_card(
            tr("Supplies Used"), value_key="total_supplies_value", icon="≡")
        card_avg, self.avg_revenue_value, self.avg_rev_card_title = self._create_kpi_card(
            tr("Avg Revenue / Visit"), value_key="avg_revenue_value", icon="◈")

        row1_layout.addWidget(card_visits)
        row1_layout.addWidget(card_revenue)
        row1_layout.addWidget(card_supplies)
        row1_layout.addWidget(card_avg)
        self.first_row_widget = cards_row1
        self.content_layout.addWidget(cards_row1)

        # --- Row 2: profitability + busiest client ---
        cards_row2 = QWidget()
        cards_row2.setObjectName("reports_cards_widget")
        row2_layout = QHBoxLayout(cards_row2)
        row2_layout.setContentsMargins(4, 0, 4, 0)
        row2_layout.setSpacing(16)

        card_net, self.net_profit_value, self.net_profit_card_title = self._create_kpi_card(
            tr("Net Profit"), value_key="net_profit_value", icon="◆")
        card_costs, self.total_costs_value, self.total_costs_card_title = self._create_kpi_card(
            tr("Total Costs"), value_key="total_costs_value", icon="▣")
        card_client, self.busiest_client_value, self.busiest_client_card_title = self._create_kpi_card(
            tr("Busiest Client"), icon="★")

        row2_layout.addWidget(card_net)
        row2_layout.addWidget(card_costs)
        row2_layout.addWidget(card_client)
        self.content_layout.addWidget(cards_row2)

    def _build_top_clients(self):
        """Top Clients table: the rank-by-revenue summary for the selected period."""
        card, self.top_clients_table, self.top_clients_title = self._create_analytics_table_card(
            tr("Top Clients"), [tr("Client"), tr("Visits"), tr("Revenue")]
        )
        self.content_layout.addWidget(card)

    # ----------------------------------------- refresh ---------------------------------------- #

    def _refresh_busiest_client(self):
        """Fills the Busiest Client card with the top owner name for the range."""
        start, end = self.current_range()
        try:
            top = analytics_repo.get_top_clients_range(start, end, limit=1)
        except Exception:
            top = []
        self.busiest_client_value.setText(str(top[0][1]) if top else "—")

    def _refresh_this_tab_charts(self):
        self._refresh_charts_content()

    def refresh_data(self):
        if getattr(self, "viewing_archive", False):
            return
        self._refresh_stats()
        self._refresh_busiest_client()
        self._refresh_this_tab_charts()
        self._rebuild_chart_grid_map()