"""
Shared building blocks for the report category tabs.

Each report tab (Overview/Financial/Patient/Supply/Audit) is its own widget in
``src/ui/pages/reports_pages``. This module provides the common layout helpers,
KPI/table/chart construction, refresh machinery, and archive restoration used
by every tab so they stay independent files without duplicating logic.
"""

from PyQt5.QtCore import Qt, QMargins
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QGridLayout, QTableWidget, QScrollArea,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy
)

import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.analytics_repo as analytics_repo
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette
from src.modules.charts import LineChart, PieChart, BarChart, SplineChart

#=========================================== CONSTANTS ===================================================#

TREND_PERIODS = [("Day", "D"), ("Week", "W"), ("Month", "M"), ("Year", "Y")]
PIE_PERIODS = [("Week", "W"), ("Month", "M"), ("Year", "Y"), ("All", "All")]

DEFAULT_PERIODS = {
    "revenue_chart": "Month",
    "visits_chart": "Month",
    "supplies_chart": "Month",
    "pets_chart": "Month",
}

DEFAULT_SUPPLY_SALES_CHART_PERIODS = "Month"

LAYOUT_CONFIG = {
    "kpi_info_card_height": 100,
    "insight_table_height": 132,
    "analytics_table_height": 176,
    "chart_min_height": 220,
    "chart_max_height": 250,
    "calendar_width": 280,
    "calendar_height": 240
}
ANALYTICS_LIMITS = {
    "expiring_days": 30,
    "top_selling_count": 3,
    "common_diagnoses_count": 3,
    "supply_usage_count": 8
}

CHART_PERIOD_BUTTON_SIZE = (36, 30)

#============================================== CODE =====================================================#

class BaseReportTab(QWidget):
    """Common layout + refresh machinery shared by all report category tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_date = ""
        self._end_date = ""
        self.viewing_archive = False
        self._cards = []

        # Trend chips live under KPI values, keyed by the value attribute name.
        self._kpi_trends = {}
        # Empty-state labels attached to report tables (toggled by _set_table_rows).
        self._card_empty_labels = {}

        # Chart state
        self.chart_widgets = []          # References kept for theme updates
        self._chart_container_map = {}   # {key: container widget}
        self._chart_grid_map = {}        # {period_key: {row, col, row_span, col_span, grid}}

        # Each tab scrolls its own content inside a per-tab scroll area, so the
        # QTabWidget itself never resizes and short/long tabs don't stretch.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("reportsTabScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setSpacing(12)
        self.content_layout.setContentsMargins(14, 12, 14, 14)
        self._scroll.setWidget(content_widget)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self._scroll)

        # Empty chart grids; each tab adds the ones it actually uses.
        self.trend_charts_widget = QWidget()
        self.trend_charts_widget.setObjectName("reports_charts_widget")
        self.trend_charts_layout = QGridLayout(self.trend_charts_widget)
        self.trend_charts_layout.setVerticalSpacing(20)
        self.trend_charts_layout.setHorizontalSpacing(20)
        for i in range(4):
            self.trend_charts_layout.setColumnStretch(i, 1)

        self.supply_charts_widget = QWidget()
        self.supply_charts_widget.setObjectName("reports_supply_charts_widget")
        self.supply_charts_layout = QGridLayout(self.supply_charts_widget)
        self.supply_charts_layout.setVerticalSpacing(20)
        self.supply_charts_layout.setHorizontalSpacing(20)
        for i in range(4):
            self.supply_charts_layout.setColumnStretch(i, 1)

    # ----------------------------------------- range ---------------------------------------- #

    def update_range(self, start, end):
        """Stores the active date window used by range-driven report queries."""
        self._start_date = start or ""
        self._end_date = end or ""

    def current_range(self):
        """Returns the active (start, end) 'YYYY-MM-DD' window."""
        return self._start_date, self._end_date

    def scroll_to_top(self):
        """Scrolls this tab's internal content view back to the top."""
        self._scroll.verticalScrollBar().setValue(0)

    def _previous_window(self, start, end):
        """Returns the (start, end) window of equal length ending the day before.

        Used to build the ▲/▼ comparison pill ("vs previous period") under each
        KPI. Falls back to empty bounds (meaning "no previous data") on bad input.
        """
        try:
            from datetime import datetime, timedelta
            s = datetime.strptime(start, "%Y-%m-%d")
            e = datetime.strptime(end, "%Y-%m-%d")
            days = (e - s).days + 1
            prev_end = s - timedelta(days=1)
            prev_start = prev_end - timedelta(days=days - 1)
            return prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return "", ""

    # ----------------------------------------- sections ---------------------------------------- #

    def _make_section_title_bar(self, title_text, subtitle_text=None):
        """Returns a styled header bar (accent + title + optional subtitle)."""
        bar = QWidget()
        bar.setProperty("class", "reports-section-header")
        bar.setMinimumHeight(38)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        accent = QFrame()
        accent.setFixedSize(4, 22)
        accent.setProperty("class", "reports-section-accent")
        layout.addWidget(accent)

        title = QLabel(title_text)
        title.setProperty("class", "reports-section-title")
        layout.addWidget(title)

        layout.addStretch()

        subtitle = QLabel(subtitle_text or "")
        subtitle.setProperty("class", "reports-section-subtitle")
        subtitle.setVisible(bool(subtitle_text))
        layout.addWidget(subtitle)
        return bar, title

    def _create_kpi_card(self, title_text: str, value_key=None, icon="", caption=None):
        """Helper to create a professional KPI card with icon, value and trend pill.

        Returns ``(card, value_label, title_label)``. When ``value_key`` is given
        (the attribute name that will hold this card's value), a comparison pill
        (▲/▼ vs the previous period) is attached and refreshed automatically.
        """
        card = QFrame()
        card.setProperty("class", "reports-kpi-card")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        if icon:
            icon_label = QLabel(icon)
            icon_label.setProperty("class", "reports-kpi-icon")
            header.addWidget(icon_label)
        title = QLabel(title_text)
        title.setProperty("class", "reports-kpi-title")
        title.setWordWrap(True)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        value_label = QLabel("0")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setMinimumHeight(LAYOUT_CONFIG["kpi_info_card_height"])
        value_label.setProperty("class", "reports-kpi-value")
        # Give the value all spare vertical space so a taller neighbouring card
        # never stretches the header/title label (stretch 0 keeps its natural height).
        layout.addWidget(value_label, 1)

        has_trend = value_key is not None
        if caption is not None or has_trend:
            sub_row = QVBoxLayout()
            sub_row.setSpacing(2)
            if caption is not None:
                cap_label = QLabel(caption)
                cap_label.setProperty("class", "reports-kpi-caption")
                sub_row.addWidget(cap_label)
            if has_trend:
                trend = self._build_trend_chip()
                self._kpi_trends[value_key] = trend
                sub_row.addWidget(trend["chip"])
            layout.addLayout(sub_row)

        self._cards.append(card)  # keep a strong ref so shiboken never frees the card
        return card, value_label, title

    def _build_trend_chip(self):
        """Builds the compact "vs previous period" pill (arrow + amount + %)."""
        chip = QFrame()
        chip.setProperty("class", "trend-chip")
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(6)

        pill = QFrame()
        pill.setFrameShape(QFrame.NoFrame)
        pill.setProperty("class", "trend-pill")
        pill.setProperty("state", "neutral")
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(8, 2, 8, 2)
        pill_layout.setSpacing(4)

        arrow = QLabel("●")
        arrow.setProperty("class", "trend-arrow")
        arrow.setProperty("state", "neutral")
        delta = QLabel("")
        delta.setProperty("class", "trend-delta")
        delta.setProperty("state", "neutral")
        pct = QLabel("")
        pct.setProperty("class", "trend-pct")
        pct.setProperty("state", "neutral")
        pill_layout.addWidget(arrow)
        pill_layout.addWidget(delta)
        pill_layout.addWidget(pct)

        caption = QLabel(tr("vs previous period"))
        caption.setProperty("class", "trend-caption")

        chip_layout.addWidget(pill)
        chip_layout.addWidget(caption)
        chip_layout.addStretch()

        trend = {
            "chip": chip,
            "pill": pill,
            "arrow": arrow,
            "delta": delta,
            "pct": pct,
            "caption": caption,
        }
        return trend

    def _create_insight_table_card(self, title_text: str, headers: list, subtitle=None):
        """Helper to create a card containing a small informational table."""
        min_h = LAYOUT_CONFIG["insight_table_height"]
        return self._make_table_card(title_text, headers, min_h, 296, subtitle)

    def _create_analytics_table_card(self, title_text: str, headers: list, subtitle=None):
        """Helper to create a taller card for the period-aware analytics tables."""
        min_h = LAYOUT_CONFIG["analytics_table_height"]
        # Cap the height so long analytics tables scroll internally instead of
        # inflating the report page to an unrealistic size.
        return self._make_table_card(title_text, headers, min_h, min_h + 120, subtitle)

    def _make_table_card(self, title_text, headers, min_height, max_height, subtitle=None):
        """Shared table-card builder: header row + polished gridless table."""
        card = QFrame()
        card.setProperty("class", "reports-table-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setProperty("class", "reports-table-header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 6)
        header_layout.setSpacing(8)

        title = QLabel(title_text)
        title.setProperty("class", "reports-table-title")
        title.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addStretch()
        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("class", "reports-section-subtitle")
            sub.setWordWrap(True)
            header_layout.addWidget(sub)
        layout.addWidget(header)

        table = QTableWidget()
        table.setProperty("class", "reports-table")
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(min_height)
        table.setMaximumHeight(max_height)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Give the table the card's spare vertical space (stretch 1) so a taller
        # neighbouring card stretches the table, not the header/title label.
        layout.addWidget(table, 1)

        empty_label = QLabel(tr("No data for this period."))
        empty_label.setProperty("class", "reports-empty")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setWordWrap(True)
        empty_label.setVisible(False)
        layout.addWidget(empty_label)
        self._card_empty_labels[table] = empty_label

        self._cards.append(card)  # keep a strong ref so shiboken never frees the card
        return card, table, title

    # ----------------------------------------- charts ---------------------------------------- #

    def _create_chart_with_controls(self, title, chart_obj):
        """Helper to wrap a chart with an external title header.

        Charts are always driven by the calendar date range, so no per-chart
        period buttons are created.
        """
        container = QFrame()
        container.setProperty("class", "chart-card")
        # Cap the card so a freshly-inserted QChartView (whose natural sizeHint is
        # far larger) can never inflate the page even before the layout pass.
        container.setMaximumHeight(LAYOUT_CONFIG["chart_max_height"] + 36)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header widget to allow QSS styling
        header_widget = QWidget()
        header_widget.setProperty("class", "chart-card-header")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 2, 10, 2)
        header_layout.setSpacing(0)

        title_label = QLabel(f"<b>{title}</b>")
        title_label.setProperty("class", "chart-card-title")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        layout.addWidget(header_widget)
        chart_obj.setMinimumHeight(LAYOUT_CONFIG["chart_min_height"])
        # Cap the height so charts never inflate the report page after refresh,
        # matching the fixed-height behavior of the report tables.
        chart_obj.setMaximumHeight(LAYOUT_CONFIG["chart_max_height"])

        # Make the chart view and internal chart transparent to adopt the card's background
        chart_obj.setStyleSheet("background: transparent; border: none;")
        chart_obj.setContentsMargins(0, 0, 0, 0)
        chart_obj.chart().setMargins(QMargins(0, 0, 0, 0))
        chart_obj.chart().setBackgroundVisible(False)
        chart_obj.chart().setPlotAreaBackgroundVisible(False)

        layout.addWidget(chart_obj)
        return container

    def _add_chart_to_layout(self, layout, chart_container, chart_obj, row, col, row_span, col_span, key=None):
        """Helper to add a chart widget to a grid layout and store its reference."""
        layout.addWidget(chart_container, row, col, row_span, col_span)
        if chart_obj:
            self.chart_widgets.append(chart_obj)
        if key:
            self._chart_container_map[key] = chart_container

    def _detach_orphan_widget(self, widget):
        """Immediately removes a replaced widget from the UI and drops stale refs.

        Using only ``deleteLater()`` leaves the old widget visible until the
        event loop runs, so during a refresh the stale chart cards briefly paint
        on top of the new ones (a flash of oversized widgets). Detaching from its
        parent here means the orphan is never drawn again.
        """
        widget.setParent(None)
        widget.deleteLater()
        self._cards = [c for c in self._cards if c is not widget]

    def _refresh_this_tab_charts(self):
        """Refreshes only the chart section(s) belonging to this tab."""
        pass

    def refresh_charts(self):
        """Refreshes this tab's chart content and rebuilds the grid map."""
        self._refresh_this_tab_charts()
        self._rebuild_chart_grid_map()

    def _refresh_charts_content(self):
        """Clears and rebuilds the trend chart widgets (revenue/visits/pets)."""
        # Rebuilding inserts fresh QChartViews whose provisional layout size is
        # much larger than the enforced cap; suspend updates so that oversized
        # frame is never painted, then lay out before repainting.
        self.setUpdatesEnabled(False)
        try:
            self._refresh_charts_content_impl()
        finally:
            self.setUpdatesEnabled(True)
            if self.layout():
                self.layout().activate()

    def _refresh_charts_content_impl(self):
        self.chart_widgets.clear()  # Fix: Clear references to avoid memory leak
        self._chart_container_map = {}
        # Clear existing charts in layout
        while self.trend_charts_layout.count():
            child = self.trend_charts_layout.takeAt(0)
            if child.widget():
                self._detach_orphan_widget(child.widget())

        palette = get_active_palette()

        # Clears and rebuilds the trend chart widgets (revenue/visits/pets) for the
        # calendar-selected range.
        start, end = self.current_range()

        # 1. Revenue Chart
        rev_labels, rev_vals, cost_vals, net_vals = analytics_repo.get_revenue_trend_range(start, end)
        rev_labels = [tr(label) for label in rev_labels]

        all_vals = rev_vals + cost_vals + net_vals
        if all_vals:
            y_min = min(all_vals) * 1.2
            y_max = max(all_vals) * 1.2
            if y_max < 0: y_max = 0
            if y_min > 0: y_min = 0
        else:
            y_min = 0; y_max = 100
        revenue_chart = SplineChart(
            series_data=[(list(range(len(rev_labels))), rev_vals, tr("Revenue"), palette.get("chart_revenue")),
                         (list(range(len(rev_labels))), cost_vals, tr("Costs"), palette.get("chart_costs")),
                         (list(range(len(rev_labels))), net_vals, tr("Net Income"), palette.get("chart_net"))],
            title="",
            x_axis_labels=rev_labels,
            y_axis_range=(y_min, y_max),
            line_width=3,
            palette=palette,
        )
        self._add_chart_to_layout(self.trend_charts_layout,
                                  self._create_chart_with_controls(tr("Revenue Trend"), revenue_chart),
                                  revenue_chart, 0, 0, 1, 4, key="revenue_chart")

        # 2. Visits Trend Chart
        v_labels, v_vals = analytics_repo.get_visits_trend_range(start, end)
        v_labels = [tr(label) for label in v_labels]

        all_v = v_vals
        if all_v:
            y_min = min(all_v) * 1.2 if min(all_v) < 0 else 0
            y_max = max(all_v) * 1.2
            if y_max < 0: y_max = 0
        else:
            y_min = 0; y_max = 5
        visits_chart = LineChart(
            series_data=[(list(range(len(v_labels))), v_vals, tr("Visits"))],
            title="",
            x_axis_labels=v_labels,
            y_axis_range=(y_min, y_max),
            palette=palette,
        )
        self._add_chart_to_layout(self.trend_charts_layout,
                                  self._create_chart_with_controls(tr("Visits Trend"), visits_chart),
                                  visits_chart, 1, 0, 1, 3, key="visits_chart")

        # 3. Pet Distribution Pie Chart
        pet_dist = analytics_repo.get_pet_distribution_range(start, end)
        pet_dist = {tr(name): qty for name, qty in pet_dist.items()}
        pets_chart = PieChart(
            data=pet_dist,
            title="",
            palette=palette,
        )
        self._add_chart_to_layout(self.trend_charts_layout,
                                  self._create_chart_with_controls(tr("Pet Distribution"), pets_chart),
                                  pets_chart, 1, 3, 1, 1, key="pets_chart")

    def _refresh_supply_charts_content(self):
        """Clears and rebuilds the supplies sales + stock charts."""
        self.setUpdatesEnabled(False)
        try:
            self._refresh_supply_charts_content_impl()
        finally:
            self.setUpdatesEnabled(True)
            if self.layout():
                self.layout().activate()

    def _refresh_supply_charts_content_impl(self):
        self._chart_container_map = {
            k: v for k, v in self._chart_container_map.items()
            if k in ("supplies_sales_section", "supplies_stock_section")
        }
        # Clear existing charts in layout
        while self.supply_charts_layout.count():
            child = self.supply_charts_layout.takeAt(0)
            if child.widget():
                self._detach_orphan_widget(child.widget())

        palette = get_active_palette()

        grid_start_row = 0

        # --- Supplies Sales Section (Subcategories) ---
        sales_section_bar, _ = self._make_section_title_bar(tr("Supplies Sales"))
        self._add_chart_to_layout(self.supply_charts_layout, sales_section_bar, None,
                                  grid_start_row, 0, 1, 4, key="supplies_sales_section")

        # Supplies line Chart — total supplies sales by category.
        start, end = self.current_range()
        s_labels, s_series_dict = analytics_repo.get_supplies_category_trend_range(start, end)
        s_labels = [tr(label) for label in s_labels]
        supp_series_data = []
        max_s_val = 5
        s_vals_all = []
        for cat, vals in s_series_dict.items():
            supp_series_data.append((list(range(len(s_labels))), vals, cat))
            if vals:
                s_vals_all.extend(vals)
                max_s_val = max(max_s_val, max(vals))

        if s_vals_all:
            sy_min = min(s_vals_all) * 1.2
            sy_max = max(s_vals_all) * 1.2
        else:
            sy_min = 0; sy_max = max_s_val * 1.2
        supplies_trend_chart = LineChart(
            series_data=supp_series_data,
            title="",
            x_axis_labels=s_labels,
            y_axis_range=(sy_min if sy_min < 0 else 0, sy_max if sy_max > 0 else max_s_val * 1.2),
            palette=palette,
        )
        self._add_chart_to_layout(self.supply_charts_layout,
                                  self._create_chart_with_controls(tr("Supplies Sold Trend"), supplies_trend_chart),
                                  supplies_trend_chart, grid_start_row + 1, 0, 1, 4, key="supplies_chart")

        categories = supply_repo.get_all_categories()
        self._supply_categories = categories
        num_sales_rows = (len(categories) + 1) // 2
        for index, category in enumerate(categories):
            period_key = f"{category.lower()}_sales"
            sub_labels, sub_series_dict = analytics_repo.get_subcategory_sales_trend_range(category, start, end)
            sub_labels = [tr(label) for label in sub_labels]

            sub_series_data = []
            sub_max_y = 5
            for subcat, vals in sub_series_dict.items():
                sub_series_data.append((list(range(len(sub_labels))), vals, subcat))
                if vals:
                    sub_max_y = max(sub_max_y, max(vals))

            # Compute subchart y range
            sub_all = []
            for _, vals in sub_series_dict.items():
                sub_all.extend(vals or [])
            if sub_all:
                sub_ymin = min(sub_all) * 1.2
                sub_ymax = max(sub_all) * 1.2
            else:
                sub_ymin = 0; sub_ymax = sub_max_y * 1.2
            sub_chart = LineChart(
                series_data=sub_series_data,
                title="",
                x_axis_labels=sub_labels,
                y_axis_range=(sub_ymin if sub_ymin < 0 else 0, sub_ymax if sub_ymax > 0 else sub_max_y * 1.2),
                palette=palette,
            )

            row = (grid_start_row + 2) + (index // 2)
            col = (index % 2) * 2
            sales_title = tr("{category} Sales").format(category=tr(category))
            self._add_chart_to_layout(self.supply_charts_layout,
                                      self._create_chart_with_controls(sales_title, sub_chart),
                                      sub_chart, row, col, 1, 2, key=period_key)

        stock_start_row = grid_start_row + 2 + num_sales_rows

        # --- Supplies Stock section ---
        stock_section_bar, _ = self._make_section_title_bar(tr("Supplies Stock"))
        self._add_chart_to_layout(self.supply_charts_layout, stock_section_bar, None,
                                  stock_start_row, 0, 1, 4, key="supplies_stock_section")

        # Total supplies by category —— no period controls.
        total_supplies_data = analytics_repo.get_total_supplies_by_category()
        x_labels_total = [tr(name) for name, qty in total_supplies_data]
        y_values_total = [qty for name, qty in total_supplies_data]
        total_supplies_chart = BarChart(
            x_labels=x_labels_total,
            y_values=y_values_total,
            title="",
            series_name=tr("Total Quantity"),
            rotate_x_labels=False,  # Explicitly disable rotation for this categorical bar chart
            palette=palette,
        )
        chart_widget = self._create_chart_with_controls(tr("Total Supplies by Category"), total_supplies_chart)
        self._add_chart_to_layout(self.supply_charts_layout, chart_widget, total_supplies_chart,
                                  stock_start_row + 1, 0, 1, 4, key="total_stock_chart")

        # Individual category stock charts —— no period controls.
        individual_charts_start_row = stock_start_row + 2
        for index, category in enumerate(categories):
            supplies_data = analytics_repo.get_supplies_numbers_for_each_category(category)
            if supplies_data:
                x_labels = [tr(name) for name, qty in supplies_data]
                y_values = [qty for name, qty in supplies_data]
                chart = BarChart(
                    x_labels=x_labels,
                    y_values=y_values,
                    title="",  # Move title to external header
                    series_name=tr("Quantity"),
                    rotate_x_labels=False,  # Explicitly disable rotation for these categorical bar charts
                    palette=palette,
                )
                stock_title = tr("{category} Stocks").format(category=tr(category))
                chart_widget = self._create_chart_with_controls(stock_title, chart)
                row = individual_charts_start_row + (index // 2)
                col = (index % 2) * 2  # Place charts in two columns
                stock_key = f"{category.lower()}_stock_chart"
                self._add_chart_to_layout(self.supply_charts_layout, chart_widget, chart, row, col, 1, 2, key=stock_key)

    def _rebuild_chart_grid_map(self):
        """Rebuild mapping from period keys to grid placements.

        This must run after the chart content refresh because the category
        order/row indices depend on the supply categories list.
        """
        self._chart_grid_map = {}

        trend = self.trend_charts_layout
        # Fixed trend placements (from _refresh_charts_content).
        self._chart_grid_map["revenue_chart"] = {"row": 0, "col": 0, "row_span": 1, "col_span": 4, "grid": trend}
        self._chart_grid_map["visits_chart"] = {"row": 1, "col": 0, "row_span": 1, "col_span": 3, "grid": trend}
        self._chart_grid_map["pets_chart"] = {"row": 1, "col": 3, "row_span": 1, "col_span": 1, "grid": trend}

        supply = self.supply_charts_layout
        # Supplies sales section: bar at row 0, sold trend at row 1, then 2 per row.
        self._chart_grid_map["supplies_chart"] = {"row": 1, "col": 0, "row_span": 1, "col_span": 4, "grid": supply}

        # Dynamic {category}_sales placements.
        categories = self._supply_categories if getattr(self, "_supply_categories", None) else supply_repo.get_all_categories()
        for index, category in enumerate(categories):
            period_key = f"{category.lower()}_sales"
            row = 2 + (index // 2)
            col = (index % 2) * 2
            self._chart_grid_map[period_key] = {"row": row, "col": col, "row_span": 1, "col_span": 2, "grid": supply}

        num_sales_rows = (len(categories) + 1) // 2
        stock_start_row = 2 + num_sales_rows
        # Static stock chart placements.
        self._chart_grid_map["total_stock_chart"] = {"row": stock_start_row + 1, "col": 0, "row_span": 1, "col_span": 4, "grid": supply}
        for index, category in enumerate(categories):
            period_key = f"{category.lower()}_stock_chart"
            row = stock_start_row + 2 + (index // 2)
            col = (index % 2) * 2
            self._chart_grid_map[period_key] = {"row": row, "col": col, "row_span": 1, "col_span": 2, "grid": supply}

    def update_chart_theme(self, palette=None):
        """Rebuild charts after theme toggles.

        Charts cache palette-derived colors at construction time, so a full rebuild
        is required to re-render axes/text/colors on the new theme.
        """
        self._refresh_this_tab_charts()
        self._rebuild_chart_grid_map()

    # ----------------------------------------- data refresh ---------------------------------------- #

    def _set_table_rows(self, table, rows):
        """Fills a QTableWidget from a list of row lists (clear before fill).

        Also toggles the card's empty-state label when no rows are provided.
        """
        if table is None:
            return
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value if value is not None else ""))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)
        empty = self._card_empty_labels.get(table)
        if empty is not None:
            empty.setVisible(not rows)

    def _set_low_stock(self, value):
        """Updates the low-stock KPI value and its visual state."""
        if not hasattr(self, "low_stock_value"):
            return
        self.low_stock_value.setText(str(value))
        palette = get_active_palette()
        color = palette.get("state_danger", "#E74C3C") if value > 0 else palette.get("text_secondary", "#636E72")
        self.low_stock_value.setStyleSheet(f"color: {color}; background: transparent;")

    def _apply_trend(self, trend, now, before, money=False):
        """Renders a compact "vs previous period" delta pill on a KPI card."""
        delta = now - before
        if money:
            flat = abs(delta) < 0.005
        else:
            flat = delta == 0

        if flat:
            state, arrow = "neutral", "●"
        elif delta > 0:
            state, arrow = "positive", "▲"
        else:
            state, arrow = "negative", "▼"

        if money:
            sign = "+" if delta >= 0 else "-"
            delta_text = f"{sign}${abs(delta):,.2f}"
            prior_text = f"${before:,.2f}"
        else:
            delta_text = f"{int(delta):+d}"
            prior_text = str(int(before))

        if before:
            pct = (delta / before) * 100
            if abs(pct) >= 10 or abs(pct - round(pct)) < 0.05:
                pct_text = f"{pct:+.0f}%"
            else:
                pct_text = f"{pct:+.1f}%"
        elif now and not flat:
            pct_text = tr("new this period")
        else:
            pct_text = "—"

        trend["arrow"].setText(arrow)
        trend["delta"].setText(delta_text)
        trend["pct"].setText(pct_text)
        trend["pct"].setVisible(bool(pct_text))
        trend["caption"].setText(tr("vs previous period"))
        trend["chip"].setToolTip(tr("Previous period: {value}").format(value=prior_text))

        # Update pill background via state property (QSS background tint)
        pill = trend["pill"]
        pill.setProperty("state", state)
        pill.style().unpolish(pill)
        pill.style().polish(pill)
        pill.update()

        # Set label text colors directly — avoids re-polishing transparent labels
        # which would inherit the pill's alpha background and render a tinted rectangle.
        palette = get_active_palette()
        if state == "positive":
            label_color = palette.get("state_success", "#2ECC71")
        elif state == "negative":
            label_color = palette.get("state_danger", "#E74C3C")
        else:
            label_color = palette.get("text_secondary", "#636E72")
        for key in ("arrow", "delta", "pct"):
            lbl = trend[key]
            lbl.setProperty("state", state)
            lbl.setStyleSheet(f"color: {label_color}; background: transparent;")

    def _apply_trend_to(self, value_key, now, before, money=False):
        """Applies a delta pill to a KPI card registered under ``value_key``."""
        trend = self._kpi_trends.get(value_key)
        if trend is not None:
            self._apply_trend(trend, now, before, money=money)

    def _refresh_stats(self):
        """Updates the high-level numeric indicators (+ trend pills) for the range."""
        start, end = self.current_range()
        prev_start, prev_end = self._previous_window(start, end) if start else ("", "")

        def _val(fn, s, e):
            try:
                return fn(s, e)
            except Exception:
                return 0.0

        if hasattr(self, "total_visits_value"):
            now = _val(analytics_repo.get_total_visits_range, start, end)
            before = _val(analytics_repo.get_total_visits_range, prev_start, prev_end)
            self.total_visits_value.setText(str(int(now)))
            self._apply_trend_to("total_visits_value", now, before, money=False)

        if hasattr(self, "total_revenue_value"):
            now = _val(analytics_repo.get_total_revenue_range, start, end)
            before = _val(analytics_repo.get_total_revenue_range, prev_start, prev_end)
            self.total_revenue_value.setText(f"${now:,.2f}")
            self._apply_trend_to("total_revenue_value", now, before, money=True)

        if hasattr(self, "total_supplies_value"):
            now = _val(analytics_repo.get_total_supplies_used_range, start, end)
            before = _val(analytics_repo.get_total_supplies_used_range, prev_start, prev_end)
            self.total_supplies_value.setText(str(int(now)))
            self._apply_trend_to("total_supplies_value", now, before, money=False)

        if hasattr(self, "avg_revenue_value"):
            revenues = _val(analytics_repo.get_total_revenue_range, start, end)
            visits = _val(analytics_repo.get_total_visits_range, start, end)
            avg = (revenues / visits) if visits else 0.0
            revenues_before = _val(analytics_repo.get_total_revenue_range, prev_start, prev_end)
            visits_before = _val(analytics_repo.get_total_visits_range, prev_start, prev_end)
            avg_before = (revenues_before / visits_before) if visits_before else 0.0
            self.avg_revenue_value.setText(f"${avg:,.2f}")
            self._apply_trend_to("avg_revenue_value", avg, avg_before, money=True)

        if hasattr(self, "total_costs_value"):
            now = _val(analytics_repo.get_total_costs_range, start, end)
            before = _val(analytics_repo.get_total_costs_range, prev_start, prev_end)
            self.total_costs_value.setText(f"${now:,.2f}")
            self._apply_trend_to("total_costs_value", now, before, money=True)

        if hasattr(self, "net_profit_value"):
            revenues = _val(analytics_repo.get_total_revenue_range, start, end)
            costs = _val(analytics_repo.get_total_costs_range, start, end)
            net = revenues - costs
            revenues_before = _val(analytics_repo.get_total_revenue_range, prev_start, prev_end)
            costs_before = _val(analytics_repo.get_total_costs_range, prev_start, prev_end)
            net_before = revenues_before - costs_before
            self.net_profit_value.setText(f"${net:,.2f}")
            palette = get_active_palette()
            color = palette.get("state_success", "#2ECC71") if net >= 0 else palette.get("state_danger", "#E74C3C")
            self.net_profit_value.setStyleSheet(f"color: {color}; background: transparent;")
            self._apply_trend_to("net_profit_value", net, net_before, money=True)

        if hasattr(self, "low_stock_value"):
            self._set_low_stock(analytics_repo.get_low_stock_supplies())

    def _refresh_performance_widgets(self):
        """Updates the Visits by Doctor / Revenue by Category / Supply Usage tables."""
        start, end = self.current_range()
        if hasattr(self, "visits_by_doctor_table"):
            self._set_table_rows(self.visits_by_doctor_table, analytics_repo.get_visits_by_doctor_range(start, end))
        if hasattr(self, "revenue_by_category_table"):
            self._set_table_rows(
                self.revenue_by_category_table,
                [[cat, f"${amount:,.2f}"] for cat, amount in analytics_repo.get_revenue_by_category_range(start, end)],
            )
        if hasattr(self, "supply_usage_table"):
            self._set_table_rows(
                self.supply_usage_table,
                analytics_repo.get_supply_usage_range(start, end, limit=ANALYTICS_LIMITS["supply_usage_count"]),
            )

    def _refresh_insights(self):
        """Updates the mini-tables for expiring items, top sellers, and diagnoses."""
        # 1. Expiring Soon
        if hasattr(self, "expiring_table"):
            expiring = analytics_repo.get_expiring_soon_items(days=ANALYTICS_LIMITS["expiring_days"])
            self.expiring_table.setRowCount(len(expiring))
            for i, item in enumerate(expiring):
                for col, key in enumerate(['name', 'category', 'expiry']):
                    cell_item = QTableWidgetItem(str(item[key]))
                    cell_item.setTextAlignment(Qt.AlignCenter)
                    self.expiring_table.setItem(i, col, cell_item)
            empty = self._card_empty_labels.get(self.expiring_table)
            if empty is not None:
                empty.setVisible(not expiring)

        # 2. Top Selling
        if hasattr(self, "top_selling_table"):
            top_selling = analytics_repo.get_top_selling_items(limit=ANALYTICS_LIMITS["top_selling_count"])
            self.top_selling_table.setRowCount(len(top_selling))
            for i, item in enumerate(top_selling):
                for col, key in enumerate(['name', 'category', 'sold']):
                    cell_item = QTableWidgetItem(str(item[key]))
                    cell_item.setTextAlignment(Qt.AlignCenter)
                    self.top_selling_table.setItem(i, col, cell_item)
            empty = self._card_empty_labels.get(self.top_selling_table)
            if empty is not None:
                empty.setVisible(not top_selling)

        # 3. Common Diagnoses
        if hasattr(self, "diagnosis_table"):
            diagnoses = analytics_repo.get_common_diagnoses(limit=ANALYTICS_LIMITS["common_diagnoses_count"])
            self.diagnosis_table.setRowCount(len(diagnoses))
            for i, item in enumerate(diagnoses):
                diag_item = QTableWidgetItem(item['diagnosis'])
                diag_item.setToolTip(item['diagnosis'])
                diag_item.setTextAlignment(Qt.AlignCenter)
                self.diagnosis_table.setItem(i, 0, diag_item)
                count_item = QTableWidgetItem(str(item['count']))
                count_item.setTextAlignment(Qt.AlignCenter)
                self.diagnosis_table.setItem(i, 1, count_item)
            empty = self._card_empty_labels.get(self.diagnosis_table)
            if empty is not None:
                empty.setVisible(not diagnoses)

    def refresh_data(self):
        """Refreshes this tab's report content. Overridden per tab."""
        pass

    # ----------------------------------------- archive ---------------------------------------- #

    def load_archive(self, data):
        """Restores a saved report snapshot into this tab's widgets."""
        kpis = data.get("kpis", {}) or {}
        if hasattr(self, "total_visits_value"):
            self.total_visits_value.setText(str(kpis.get("visits", 0)))
        if hasattr(self, "total_revenue_value"):
            self.total_revenue_value.setText(f"${float(kpis.get('revenue', 0)):,.2f}")
        if hasattr(self, "total_supplies_value"):
            self.total_supplies_value.setText(str(kpis.get("supplies_used", 0)))
        if hasattr(self, "avg_revenue_value"):
            self.avg_revenue_value.setText(f"${float(kpis.get('avg_revenue', 0)):,.2f}")
        if hasattr(self, "total_costs_value"):
            self.total_costs_value.setText(f"${float(kpis.get('costs', 0)):,.2f}")
        if hasattr(self, "net_profit_value"):
            self.net_profit_value.setText(f"${float(kpis.get('net_profit', 0)):,.2f}")
        if hasattr(self, "low_stock_value"):
            self._set_low_stock(int(kpis.get("low_stock", 0) or 0))
        if hasattr(self, "busiest_client_value"):
            self.busiest_client_value.setText(str(kpis.get("busiest_client", "") or "—"))

        tables = data.get("tables", {}) or {}
        if hasattr(self, "visits_by_doctor_table"):
            self._set_table_rows(self.visits_by_doctor_table, tables.get("visits_by_doctor", []))
        if hasattr(self, "revenue_by_category_table"):
            self._set_table_rows(self.revenue_by_category_table, tables.get("revenue_by_category", []))
        if hasattr(self, "supply_usage_table"):
            self._set_table_rows(self.supply_usage_table, tables.get("supply_usage", []))
        if hasattr(self, "top_clients_table"):
            self._set_table_rows(self.top_clients_table, tables.get("top_clients", []))
        if hasattr(self, "clinical_table"):
            self._set_table_rows(self.clinical_table, tables.get("clinical", []))
            self.clinical_empty_label.setVisible(not tables.get("clinical", []))

    # ----------------------------------------- translation ---------------------------------------- #

    def _relabel_table_header(self, attr_name, headers):
        """Re-labels a table's header in place if the widget exists."""
        table = getattr(self, attr_name, None)
        if table is not None:
            table.setHorizontalHeaderLabels([tr(h) for h in headers])

    def retranslate_ui(self):
        """Relabels this tab's section titles, table headers, and insight titles.

        Only overview + operational-insights fall here (their tabs don't override
        them); every other tab re-sets its own section titles after this call.
        """
        titles = {
            "overview_section_title": "Business Overview",
            "insights_section_title": "Operational Insights",
        }
        for attr, text in titles.items():
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(tr(text))

        self._relabel_table_header("visits_by_doctor_table", ["Doctor", "Visits"])
        self._relabel_table_header("revenue_by_category_table", ["Category", "Revenue"])
        self._relabel_table_header("supply_usage_table", ["Item", "Category", "Quantity"])
        self._relabel_table_header("expiring_table", ["Item", "Category", "Date"])
        self._relabel_table_header("top_selling_table", ["Item", "Category", "Sold"])
        self._relabel_table_header("diagnosis_table", ["Diagnosis", "Count"])
        self._relabel_table_header("top_clients_table", ["Client", "Visits", "Revenue"])

        if hasattr(self, "expiring_title"):
            self.expiring_title.setText(tr("Expiring Soon (30d)"))
        if hasattr(self, "top_selling_title"):
            self.top_selling_title.setText(tr("Top Selling Items"))
        if hasattr(self, "diagnosis_title"):
            self.diagnosis_title.setText(tr("Monthly Diagnoses"))
        if hasattr(self, "visits_by_doctor_title"):
            self.visits_by_doctor_title.setText(tr("Visits by Doctor"))
        if hasattr(self, "revenue_by_category_title"):
            self.revenue_by_category_title.setText(tr("Revenue by Category"))
        if hasattr(self, "supply_usage_title"):
            self.supply_usage_title.setText(tr("Supply Usage"))
        if hasattr(self, "top_clients_title"):
            self.top_clients_title.setText(tr("Top Clients"))

        if hasattr(self, "kpi_titles"):
            kpi_titles = {
                "visits_info_card_title": "Total Visits",
                "total_revenue_card_title": "Total Revenue",
                "supplies_card_title": "Supplies Used",
                "avg_rev_card_title": "Avg Revenue / Visit",
                "low_stock_card_title": "Low Stock Supplies",
                "total_costs_card_title": "Total Costs",
                "net_profit_card_title": "Net Profit",
                "busiest_client_card_title": "Busiest Client",
            }
            for attr, text in kpi_titles.items():
                label = getattr(self, attr, None)
                if label is not None:
                    label.setText(tr(text))

        # Re-trigger a refresh so translated values are rebuilt.
        self.refresh_data()