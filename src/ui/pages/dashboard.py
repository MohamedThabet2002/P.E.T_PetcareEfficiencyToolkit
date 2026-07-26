"""
Clinical Analytics Dashboard for the PET Application.
Aggregates key performance indicators (KPIs), upcoming schedules, and 
visual data trends into a consolidated management view.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, 
    QSizePolicy, QGridLayout, QPushButton, QButtonGroup, QTableWidget, 
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt5.QtCore import Qt, QMargins, QObject, QThread, pyqtSignal
from PyQt5.QtGui import QColor

from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.ui.widgets.charts import LineChart, PieChart, BarChart, SplineChart
from src.core.repositories.analytics_cache import invalidate_analytics_cache
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.analytics_repo as analytics_repo
import src.core.repositories.supply_repo as supply_repo
from src.utils.i18n import tr

#=========================================== CONSTANTS ===================================================#

# --- Dashboard Tuning Constants ---
TREND_PERIODS = [("Day", "D"), ("Week", "W"), ("Month", "M"), ("Year", "Y")]
PIE_PERIODS = [("Week", "W"), ("Month", "M"), ("Year", "Y"), ("All", "All")]

DEFAULT_PERIODS = {
    "visits_info": "Month",
    "revenue_info": "Month",
    "revenue_chart": "Month",
    "visits_chart": "Month",
    "supplies_chart": "Month",
    "pets_chart": "Month"
}

DEFAULT_SUPPLY_SALES_CHART_PERIODS = "Month"

LAYOUT_CONFIG = {
    "kpi_info_card_height": 100,
    "insight_table_height": 132,
    "chart_min_height": 350
}
ANALYTICS_LIMITS = {
    "expiring_days": 30,
    "top_selling_count": 3,
    "common_diagnoses_count": 3,
    "appointment_preview_count": 3
}

CHART_PERIOD_BUTTON_SIZE = (36, 30)
CARD_PERIOD_BUTTON_SIZE = (36, 30)

#============================================== CODE =====================================================#

class DashboardPage(QWidget):
    def __init__(self, parent=None):
        """Initializes the dashboard page with stats, tables, and charts."""
        super().__init__(parent)
        
        # Guard to prevent expensive repeated refreshes back-to-back.
        self._refresh_pending = False
        
        # State management for period filters
        self.periods = DEFAULT_PERIODS.copy()
        
        # Initialize subcategory periods
        self._supply_categories = supply_repo.get_all_categories()
        for cat in self._supply_categories:
            self.periods[f"{cat.lower()}_sales"] = DEFAULT_SUPPLY_SALES_CHART_PERIODS
        
        # Chart grid mapping for per-chart refresh.
        # Populated after initial chart build in _refresh_charts_content().
        # Structure: {period_key: {row, col, row_span, col_span}}.
        self._chart_grid_map = {}
        
        # Scroll area
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # Container widget for all dashboard content
        container = QWidget()
        self.dashboard_layout = QVBoxLayout(container)
        self.dashboard_layout.setSpacing(0)
        self.dashboard_layout.setContentsMargins(0, 0, 0, 0)
        # Dashboard sections
        self.chart_widgets = [] # To store references to chart widgets for theme updates
        self.period_buttons = []
        self._first_row()
        self._second_row()
        self._third_row()
        self._charts()
        
        # Add sections to container
        self.dashboard_layout.addWidget(self.first_row_widget)
        self.dashboard_layout.addWidget(self.second_row_widget)
        self.dashboard_layout.addWidget(self.third_row_widget)
        self.dashboard_layout.addWidget(self.charts_widget)
        self.dashboard_layout.addStretch()
        
        # Put container inside scroll area
        scroll.setWidget(container)
        # Final layout for DashboardPage
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(scroll)
        
        # Initial data load
        self.refresh_data()
        
        # Connect to global theme changes
        ThemeManager.instance().theme_changed.connect(self.update_chart_theme)
    
    def retranslate_ui(self):
        """Updates all static text on the dashboard when the language changes."""
        self.next_appointment_title.setText(tr("Next Client Scheduled in"))
        self.visits_info_card_title.setText(tr("Total Visits"))
        self.total_revenue_card_title.setText(tr("Total Revenue"))
        self.low_stock_card_title.setText(tr("Low Stock Supplies"))
        self.avg_rev_card_title.setText(tr("Avg Revenue / Visit"))
        self.table_title.setText(tr("Appointments"))
        for btn, label in getattr(self, 'period_buttons', []):
            btn.setText(tr(label))
        
        # Update Table Headers
        self.upcoming_appointments_table.setHorizontalHeaderLabels([tr("Date"), tr("Service"), tr("Status")])
        self.expiring_table.setHorizontalHeaderLabels([tr("Item"), tr("Category"), tr("Date")])
        self.top_selling_table.setHorizontalHeaderLabels([tr("Item"), tr("Category"), tr("Sold")])
        self.diagnosis_table.setHorizontalHeaderLabels([tr("Diagnosis"), tr("Count")])
        
        # Update Insight Table Titles
        self.expiring_title.setText(f"<b>{tr('Expiring Soon (30d)')}</b>")
        self.top_selling_title.setText(f"<b>{tr('Top Selling Items')}</b>")
        self.diagnosis_title.setText(f"<b>{tr('Monthly Diagnoses')}</b>")
        
        # Update period buttons (KPIs)
        # Since buttons are recreated or labels are simple keys like 'D', 'W', 
        # we mainly focus on titles. Re-triggering a data refresh updates 
        # status items like 'Pending'/'Completed'.
        self.refresh_data()
    
    def refresh_data(self):
        """Backward-compatible full refresh (stats + insights + appointments + charts)."""
        invalidate_analytics_cache()
        self.refresh_kpis_insights_appointments()
        self.refresh_charts()
    
    def refresh_kpis_insights_appointments(self):
        """Refresh only the KPI/insights/appointments (avoid chart rebuild churn)."""
        self._refresh_stats()
        self._refresh_insights()
        self._refresh_appointments()
    
    def refresh_charts(self):
        """Refresh only the charts content."""
        self._refresh_charts_content()
        # Ensure chart grid map exists after rebuild.
        self._rebuild_chart_grid_map()
    
    def _refresh_stats(self):
        """Updates the high-level numeric indicators."""
        self.next_appointment_time_label.setText(appointment_repo.get_next_appointment_time())
        # info cards
        self.total_visits_value.setText(str(analytics_repo.get_total_visits(self.periods["visits_info"])))
        self.total_revenue_value.setText(f"${analytics_repo.get_total_revenue(self.periods['revenue_info']):.2f}")
        # kpi cards
        low_stock = analytics_repo.get_low_stock_supplies()
        self.low_stock_value.setText(str(low_stock))
        self.low_stock_value.setProperty("state", "negative" if low_stock > 0 else "neutral")
        
        self.low_stock_value.style().unpolish(self.low_stock_value)
        self.low_stock_value.style().polish(self.low_stock_value)
        
        self.avg_revenue_value.setText(f"${analytics_repo.get_average_revenue_per_visit():.2f}")
    
    def _refresh_insights(self):
        """Updates the mini-tables for expiring items, top sellers, and diagnoses."""
        # 1. Expiring Soon
        expiring = analytics_repo.get_expiring_soon_items(days=ANALYTICS_LIMITS["expiring_days"])
        self.expiring_table.setRowCount(len(expiring))
        for i, item in enumerate(expiring):
            for col, key in enumerate(['name', 'category', 'expiry']):
                cell_item = QTableWidgetItem(str(item[key]))
                cell_item.setTextAlignment(Qt.AlignCenter)
                self.expiring_table.setItem(i, col, cell_item)
        
        # 2. Top Selling
        top_selling = analytics_repo.get_top_selling_items(limit=ANALYTICS_LIMITS["top_selling_count"])
        self.top_selling_table.setRowCount(len(top_selling))
        for i, item in enumerate(top_selling):
            for col, key in enumerate(['name', 'category', 'sold']):
                cell_item = QTableWidgetItem(str(item[key]))
                cell_item.setTextAlignment(Qt.AlignCenter)
                self.top_selling_table.setItem(i, col, cell_item)
        
        # 3. Common Diagnoses
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
    
    def _refresh_appointments(self):
        """Updates the dashboard's summary view of recent and upcoming appointments."""
        past_appointments = appointment_repo.get_past_appointments(limit=1, as_table=True)
        upcoming_appointments = appointment_repo.get_next_appointments(limit=ANALYTICS_LIMITS["appointment_preview_count"], as_table=True)
        appointments = past_appointments + upcoming_appointments
        
        palette = get_active_palette()
        self.upcoming_appointments_table.setRowCount(len(appointments))
        for row, (date, service, status) in enumerate(appointments):
            date_item = QTableWidgetItem(str(date))
            date_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 0, date_item)
            
            service_item = QTableWidgetItem(tr(str(service)))
            service_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 1, service_item)
            
            status_item = QTableWidgetItem(tr(status))
            status_item.setTextAlignment(Qt.AlignCenter)
            if status == "Pending":
                status_item.setForeground(palette.qcolor("state_warning"))
            elif status == "Completed":
                status_item.setForeground(palette.qcolor("state_success"))
            elif status == "Canceled":
                status_item.setForeground(palette.qcolor("state_danger"))
            self.upcoming_appointments_table.setItem(row, 2, status_item)
    
    def _on_info_card_period_changed(self, period_key, new_period, label_obj, repo_func, formatter=str):
        """Unified handler for updating KPI values based on period selection."""
        self.periods[period_key] = new_period
        label_obj.setText(formatter(repo_func(new_period)))
    
    def _on_chart_period_changed(self, period_key, new_period):
        """Unified handler for updating chart state and triggering a redraw."""
        self.periods[period_key] = new_period
        
        # Throttle: if user clicks rapidly between period buttons,
        # avoid stacking expensive chart rebuilds back-to-back.
        if self._refresh_pending:
            return
        self._refresh_pending = True
        
        # Refresh only the affected chart(s) instead of rebuilding everything.
        try:
            self._refresh_single_chart(period_key, new_period)
        except Exception:
            # Fallback (shouldn't happen). Keep KPI/insights/appointments intact.
            # Fallback (shouldn't happen). Keep KPI/insights/appointments intact.
            self._refresh_charts_content()
        
        self._refresh_pending = False
    # info cards (left of the appointments table)
    def _create_info_card_with_periods(self, title_text: str, period_key: str, callback):
        """Helper to create a KPI card with period selection buttons (Day, Week, etc)."""
        card = QFrame()
        card.setProperty("class", "info-card")
        layout = QGridLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QWidget()
        header.setProperty("class", "info-card-header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        
        title = QLabel(title_text)
        title.setProperty("class", "info-card-title")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        value_label = QLabel("0")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setFixedHeight(LAYOUT_CONFIG["kpi_info_card_height"])
        value_label.setProperty("class", "info-card-value")
        
        period_container = QFrame()
        period_container.setProperty("class", "timestamp-button-group")
        period_layout = QHBoxLayout(period_container)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(0)
        
        group = QButtonGroup(self)
        period_buttons = []
        for period_name, label in [("Day", "D"), ("Week", "W"), ("Month", "M"), ("Year", "Y"), ("All", "All")]:
            btn = QPushButton(tr(label))
            btn.setCheckable(True)
            btn.setFixedSize(*CARD_PERIOD_BUTTON_SIZE)
            btn.setProperty("class", "timestamp-button-group")
            btn.setCursor(Qt.PointingHandCursor)
            if self.periods.get(period_key) == period_name: btn.setChecked(True)
            group.addButton(btn)
            period_layout.addWidget(btn)
            btn.clicked.connect(lambda _, p=period_name, k=period_key, l=value_label: callback(k, p, l))
            period_buttons.append((btn, label))
        self.period_buttons.extend(period_buttons)
        
        header_layout.addWidget(period_container, alignment=Qt.AlignRight)
        layout.addWidget(header, 0, 0, 1, 2)
        layout.addWidget(value_label, 1, 0, 1, 2)
        return card, value_label, title
    # creates the info cards 
    def _create_kpi_card(self, title_text: str):
        """Helper to create a stylized information card with a title and value label."""
        card = QFrame()
        card.setProperty("class", "kpi-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(0)
        
        title = QLabel(title_text)
        title.setProperty("class", "kpi-title")
        
        value_label = QLabel("0")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setFixedHeight(LAYOUT_CONFIG["kpi_info_card_height"])
        value_label.setProperty("class", "kpi-value")
        value_label.setProperty("state", "positive") # Default state
        
        layout.addWidget(title)
        layout.addWidget(value_label)
        return card, value_label, title
    
    def _create_insight_table_card(self, title_text: str, headers: list):
        """Helper to create a card containing a small informational table."""
        card = QFrame()
        card.setProperty("class", "insight-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title = QLabel(f"<b>{title_text}</b>")
        title.setProperty("class", "insight-title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        table = QTableWidget()
        table.setProperty("class", "insight-table")
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setShowGrid(False)
        table.setFixedHeight(LAYOUT_CONFIG["insight_table_height"])
        
        layout.addWidget(table)
        return card, table, title
    
    def _first_row(self):
        """Initializes the statistics section (top half of the dashboard)."""
        self.first_row_widget = QWidget()
        self.first_row_layout = QHBoxLayout(self.first_row_widget)
        
        # Left Side: Status and Cards
        self.status_cards_widget = QWidget()
        self.status_cards_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.status_cards_layout = QVBoxLayout(self.status_cards_widget)
        self.status_cards_layout.setContentsMargins(0, 0, 10, 0)
        self.status_cards_layout.setAlignment(Qt.AlignTop)
        self.status_cards_layout.setSpacing(10)
        
        # Next Appointment Status
        self.status_widget = QFrame()
        self.status_widget.setProperty("class", "status-card")
        self.status_widget.setMinimumHeight(80)
        self.status_layout = QHBoxLayout(self.status_widget)
        
        self.next_appointment_title = QLabel(tr("Next Client Scheduled in"))
        self.next_appointment_title.setProperty("class", "status-title")
        self.next_appointment_title.setAlignment(Qt.AlignAbsolute | Qt.AlignLeft | Qt.AlignVCenter)
        self.status_layout.addWidget(self.next_appointment_title)
        self.status_layout.addStretch()
        self.next_appointment_time_label = QLabel()
        self.next_appointment_time_label.setProperty("class", "status-value")
        self.next_appointment_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_layout.addWidget(self.next_appointment_time_label)
        
        self.status_cards_layout.addWidget(self.status_widget)
        
        # Info Cards (Visits, Revenue)
        self.cards_widget = QWidget()
        self.cards_widget.setObjectName("dashboard_cards_widget")
        self.cards_layout = QHBoxLayout(self.cards_widget)
        
        card_visits, self.total_visits_value, self.visits_info_card_title = self._create_info_card_with_periods(
            tr("Total Visits"), "visits_info", 
            lambda i, n, f: self._on_info_card_period_changed(i, n, f, analytics_repo.get_total_visits)
        )
        card_revenue, self.total_revenue_value, self.total_revenue_card_title = self._create_info_card_with_periods(
            tr("Total Revenue"), "revenue_info", 
            lambda i, n, f: self._on_info_card_period_changed(i, n, f, analytics_repo.get_total_revenue, formatter=lambda v: f"${v:.2f}")
        )
        
        self.cards_layout.addWidget(card_visits)
        self.cards_layout.addWidget(card_revenue)
        self.status_cards_layout.addWidget(self.cards_widget)
        self.first_row_layout.addWidget(self.status_cards_widget, alignment=Qt.AlignTop)
        
        # Right Side: Upcoming Appointments Table
        self.upcoming_appointments_table = QTableWidget()
        self.upcoming_appointments_table.setObjectName("dashboard_upcoming_appointments_table")
        self.upcoming_appointments_table.setColumnCount(3)
        self.upcoming_appointments_table.setHorizontalHeaderLabels([tr("Date"), tr("Service"), tr("Status")])
        self.upcoming_appointments_table.horizontalHeader().setStretchLastSection(True)
        self.upcoming_appointments_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable columns resizing
        self.upcoming_appointments_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.upcoming_appointments_table.setColumnWidth(0, 150)
        self.upcoming_appointments_table.setColumnWidth(1, 200)
        self.upcoming_appointments_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable rows resizing
        self.upcoming_appointments_table.verticalHeader().setVisible(False)# Hide index column
        self.upcoming_appointments_table.verticalHeader().setDefaultSectionSize(35)# set default row height
        self.upcoming_appointments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upcoming_appointments_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming_appointments_table.setFixedSize(500,186)
        self.upcoming_appointments_table.setAlternatingRowColors(True)
        
        right_side_layout = QVBoxLayout()
        right_side_layout.setAlignment(Qt.AlignTop)
        right_side_layout.setSpacing(10)
        
        self.table_title = QLabel(tr("Appointments"))
        self.table_title.setObjectName("dashboard_upcoming_appointments_title")
        self.table_title.setFixedHeight(40)
        self.table_title.setAlignment(Qt.AlignCenter)
        
        right_side_layout.addWidget(self.table_title)
        right_side_layout.addWidget(self.upcoming_appointments_table)
        self.first_row_layout.addLayout(right_side_layout)
    
    def _second_row(self):
        self.second_row_widget = QWidget()
        self.second_row_layout = QHBoxLayout(self.second_row_widget)
        self.second_row_layout.setContentsMargins(10, 0, 10, 10)
        self.second_row_layout.setSpacing(20)
        
        card_supplies, self.low_stock_value, self.low_stock_card_title = self._create_kpi_card(tr("Low Stock Supplies"))
        self.second_row_layout.addWidget(card_supplies)
        card_avg_rev, self.avg_revenue_value, self.avg_rev_card_title = self._create_kpi_card(tr("Avg Revenue / Visit"))
        self.second_row_layout.addWidget(card_avg_rev)
    
    def _third_row(self):
        """Initializes the middle section with small tables for deep-dives."""
        self.third_row_widget = QWidget()
        self.third_row_layout = QHBoxLayout(self.third_row_widget)
        self.third_row_layout.setContentsMargins(10, 0, 10, 10)
        self.third_row_layout.setSpacing(20)
        
        exp_card, self.expiring_table, self.expiring_title = self._create_insight_table_card(tr("Expiring Soon (30d)"), [tr("Item"), tr("Category"), tr("Date")])
        top_card, self.top_selling_table, self.top_selling_title = self._create_insight_table_card(tr("Top Selling Items"), [tr("Item"), tr("Category"), tr("Sold")])
        diag_card, self.diagnosis_table, self.diagnosis_title = self._create_insight_table_card(tr("Monthly Diagnoses"), [tr("Diagnosis"), tr("Count")])
        
        self.third_row_layout.addWidget(exp_card)
        self.third_row_layout.addWidget(top_card)
        self.third_row_layout.addWidget(diag_card)
    
    def _charts(self):
        """Initializes the charts container."""
        self.charts_widget = QWidget()
        self.charts_widget.setObjectName("dashboard_charts_widget")
        self.charts_layout = QGridLayout(self.charts_widget)
        self.charts_layout.setVerticalSpacing(20)
        self.charts_layout.setHorizontalSpacing(20)
        for i in range(4): # 4 is the number of columns i want the grid to be
            self.charts_layout.setColumnStretch(i, 1)
    
    def _create_chart_with_controls(self, title, period_key, chart_obj, periods=None):
        """Helper to wrap a chart with an external title and optional period controls."""
        if periods is None:
            periods = [("Week", "W"), ("Month", "M"), ("Year", "Y")]
            
        container = QFrame()
        container.setProperty("class", "chart-card")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header widget to allow QSS styling
        header_widget = QWidget()
        header_widget.setProperty("class", "chart-card-header")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 2, 0, 2)
        header_layout.setSpacing(0)
        
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setProperty("class", "chart-card-title")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        period_container = QFrame()
        period_container.setProperty("class", "timestamp-button-group")
        period_layout = QHBoxLayout(period_container)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(0)
        
        if periods and period_key:
            group = QButtonGroup(container)
            for p_name, label in periods: # periods already contains translated labels
                btn = QPushButton(tr(label))
                btn.setCheckable(True)
                btn.setFixedSize(*CHART_PERIOD_BUTTON_SIZE)
                btn.setProperty("class", "timestamp-button-group")
                btn.setCursor(Qt.PointingHandCursor)
                if self.periods.get(period_key) == p_name: 
                    btn.setChecked(True)
                group.addButton(btn)
                header_layout.addWidget(btn)
                btn.clicked.connect(lambda _, p=p_name, k=period_key: self._on_chart_period_changed(k, p))
        
        header_layout.addWidget(period_container, alignment=Qt.AlignRight)
        layout.addWidget(header_widget)
        chart_obj.setMinimumHeight(LAYOUT_CONFIG["chart_min_height"])
        
        # Make the chart view and internal chart transparent to adopt the card's background
        chart_obj.setStyleSheet("background: transparent; border: none;")
        chart_obj.setContentsMargins(0, 0, 0, 0)
        chart_obj.chart().setMargins(QMargins(0, 0, 0, 0))
        chart_obj.chart().setBackgroundVisible(False)
        chart_obj.chart().setPlotAreaBackgroundVisible(False)
        
        layout.addWidget(chart_obj)
        return container
    
    def _refresh_charts_content(self):
        """Clears and rebuilds the chart widgets with updated data."""
        self.chart_widgets.clear() # Fix: Clear references to avoid memory leak
        # Clear existing charts in layout
        while self.charts_layout.count():
            child = self.charts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        palette = get_active_palette()

        # NOTE: Supplies sold trend must use the *dynamic* data model used in supplies page.
        # The old implementation relied on legacy hardcoded/incorrect fields, so we rebuild it
        # exclusively from receipt_items joined against receipts/supplies (see sales_repo).

        
        # 1. Revenue Chart
        rev_labels, rev_vals, cost_vals, net_vals = analytics_repo.get_trend_data('revenue', self.periods["revenue_chart"])
        rev_labels = [tr(label) for label in rev_labels]
        
        revenue_chart = SplineChart(

            series_data=[   (list(range(len(rev_labels))), rev_vals, tr("Revenue"), palette.get("chart_revenue")),
                            (list(range(len(rev_labels))), cost_vals, tr("Costs"), palette.get("chart_costs")),
                            (list(range(len(rev_labels))), net_vals, tr("Net Income"), palette.get("chart_net"))
                            ],
            title="",
            x_axis_labels=rev_labels,
            y_axis_range=(0, max(rev_vals + cost_vals + [100]) * 1.2),
            line_width=3,
            palette=palette,
        )
        self._add_chart_to_layout(self._create_chart_with_controls(tr("Revenue Trend"), "revenue_chart", revenue_chart), revenue_chart, 0, 0, 1, 4)
        
        # 2. Visits Trend Chart
        v_labels, v_vals = analytics_repo.get_trend_data('visits', self.periods["visits_chart"])
        v_labels = [tr(label) for label in v_labels]
        
        visits_chart = LineChart(

            series_data=[(list(range(len(v_labels))), v_vals, tr("Visits"))],
            title="",
            x_axis_labels=v_labels,
            y_axis_range=(0, max(v_vals + [5]) * 1.2),
            palette=palette,
        )
        self._add_chart_to_layout(self._create_chart_with_controls(tr("Visits Trend"), "visits_chart", visits_chart, periods=TREND_PERIODS), visits_chart, 1, 0, 1, 3)
        
        
        # 4. Pet Distribution Pie Chart
        pet_dist = analytics_repo.get_pet_distribution(self.periods["pets_chart"])
        pet_dist = {tr(name): qty for name, qty in pet_dist.items()}
        pets_chart = PieChart(
            data=pet_dist,
            title="",
            palette=palette,
            )
        self._add_chart_to_layout(self._create_chart_with_controls(tr("Pet Distribution"), "pets_chart", pets_chart, periods=PIE_PERIODS), pets_chart, 1, 3, 1, 1)
        
        grid_start_row = 2
        
        # --- New Supplies Sales Section (Subcategories) ---
        supplies_sales_title_widget = QWidget()
        supplies_sales_title_widget.setObjectName("dashboard_supplies_sales_title_widget")
        supplies_sales_title_widget.setMinimumHeight(80)
        supplies_sales_title_layout = QHBoxLayout(supplies_sales_title_widget)
        
        title_sales = QLabel(tr("Supplies Sales"))
        title_sales.setProperty("class", "section-title")
        title_sales.setAlignment(Qt.AlignCenter)
        supplies_sales_title_layout.addWidget(title_sales)
        
        self._add_chart_to_layout(supplies_sales_title_widget, None, grid_start_row, 0, 1, 4)
        # Supplies line Chart
        # Add a new bar chart for total supplies sales by category
        s_labels, s_series_dict = analytics_repo.get_supplies_category_trend(self.periods["supplies_chart"])
        s_labels = [tr(label) for label in s_labels]
        supp_series_data = []
        max_s_val = 5
        for cat, vals in s_series_dict.items():
            supp_series_data.append((list(range(len(s_labels))), vals, cat))
            if vals: max_s_val = max(max_s_val, max(vals))
            
        supplies_trend_chart = LineChart(
            series_data=supp_series_data,
            title="",
            x_axis_labels=s_labels,
            y_axis_range=(0, max_s_val * 1.2),
            palette=palette,
        )
        sales_chart_widget = self._create_chart_with_controls(tr("Supplies Sold Trend"), "supplies_chart", supplies_trend_chart, periods=TREND_PERIODS)
        self.charts_layout.addWidget(sales_chart_widget, grid_start_row + 1, 0, 1, 4)
        
        categories = supply_repo.get_all_categories()
        num_sales_rows = (len(categories) + 1) // 2
        for index, category in enumerate(categories):
            period_key = f"{category.lower()}_sales"
            # Use .get() to handle categories added mid-session that aren't in the initial periods dict
            active_period = self.periods.get(period_key, DEFAULT_SUPPLY_SALES_CHART_PERIODS)
            sub_labels, sub_series_dict = analytics_repo.get_subcategory_sales_trend(category, active_period)
            sub_labels = [tr(label) for label in sub_labels]
            
            sub_series_data = []
            sub_max_y = 5
            for subcat, vals in sub_series_dict.items():
                sub_series_data.append((list(range(len(sub_labels))), vals, subcat))
                if vals: sub_max_y = max(sub_max_y, max(vals))
                
            sub_chart = LineChart(
                series_data=sub_series_data,
                title="",
                x_axis_labels=sub_labels,
                y_axis_range=(0, sub_max_y * 1.2),
                palette=palette,
                )
            
            row = (grid_start_row + 2) + (index // 2)
            col = (index % 2) * 2
            sales_title = tr("{category} Sales").format(category=tr(category))
            self._add_chart_to_layout(self._create_chart_with_controls(sales_title, period_key, sub_chart, periods=TREND_PERIODS), sub_chart, row, col, 1, 2)
            
        stock_start_row = grid_start_row + 2 + num_sales_rows
        
        # --- Supplies Stock section ---
        supplies_title_widget = QWidget()
        supplies_title_widget.setObjectName("dashboard_supplies_charts_title_widget")
        supplies_title_widget.setMinimumHeight(80)
        supplies_title_layout = QHBoxLayout(supplies_title_widget)
        
        title_label = QLabel(tr("Supplies Stock"))
        title_label.setProperty("class", "section-title")
        title_label.setAlignment(Qt.AlignCenter)
        supplies_title_layout.addWidget(title_label)
        
        self._add_chart_to_layout(supplies_title_widget, None, stock_start_row, 0, 1, 4)
        
        # Supplies Bar Charts
        # Add a new bar chart for total supplies by category
        total_supplies_data = analytics_repo.get_total_supplies_by_category()
        x_labels_total = [name for name, qty in total_supplies_data]
        y_values_total = [qty for name, qty in total_supplies_data]
        x_labels_total = [tr(label) for label in x_labels_total]
        total_supplies_chart = BarChart(
            x_labels=x_labels_total,
            y_values=y_values_total,
            title="", 
            series_name=tr("Total Quantity"),
            rotate_x_labels=False, # Explicitly disable rotation for this categorical bar chart
            palette=palette,
        )
        chart_widget = self._create_chart_with_controls(tr("Total Supplies by Category"), None, total_supplies_chart, periods=[]) # No period controls for this chart
        self.charts_layout.addWidget(chart_widget, stock_start_row + 1, 0, 1, 4)
        
        # Adjust the starting row for individual category charts
        individual_charts_start_row = stock_start_row + 2
        for index, category in enumerate(categories):
            supplies_data = analytics_repo.get_supplies_numbers_for_each_category(category)
            if supplies_data:
                x_labels = [name for name, qty in supplies_data]
                y_values = [qty for name, qty in supplies_data]
                x_labels = [tr(label) for label in x_labels]
                chart = BarChart(
                    x_labels=x_labels,
                    y_values=y_values,
                    title="", # Move title to external header
                    series_name=tr("Quantity"),
                    rotate_x_labels=False, # Explicitly disable rotation for these categorical bar charts
                    palette=palette,
                )
                stock_title = tr("{category} Stocks").format(category=tr(category))
                chart_widget = self._create_chart_with_controls(stock_title, None, chart, periods=[])
                row = individual_charts_start_row + (index // 2)
                col = (index % 2) * 2 # Place charts in two columns
                self._add_chart_to_layout(chart_widget, chart, row, col, 1, 2)
    
    def _add_chart_to_layout(self, chart_container, chart_obj, row, col, row_span, col_span):
        """Helper to add a chart widget to the layout and store its reference."""
        self.charts_layout.addWidget(chart_container, row, col, row_span, col_span)
        if chart_obj:
            self.chart_widgets.append(chart_obj)
    
    def _rebuild_chart_grid_map(self):
        """Rebuild mapping from period keys to grid placements.

        This must run after _refresh_charts_content() because the category order/row indices
        depend on the supply categories list.
        """
        self._chart_grid_map = {}

        # Fixed chart placements (from _refresh_charts_content).
        self._chart_grid_map["revenue_chart"] = {"row": 0, "col": 0, "row_span": 1, "col_span": 4}
        self._chart_grid_map["visits_chart"] = {"row": 1, "col": 0, "row_span": 1, "col_span": 3}
        self._chart_grid_map["pets_chart"] = {"row": 1, "col": 3, "row_span": 1, "col_span": 1}
        # Supplies Sold Trend Chart sits at row 3 (under the title at row 2)
        self._chart_grid_map["supplies_chart"] = {"row": 3, "col": 0, "row_span": 1, "col_span": 4}

        # Dynamic {category}_sales placements.
        grid_start_row = 2
        categories = self._supply_categories if getattr(self, "_supply_categories", None) else supply_repo.get_all_categories()
        for index, category in enumerate(categories):
            period_key = f"{category.lower()}_sales"
            row = (grid_start_row + 2) + (index // 2)
            col = (index % 2) * 2
            self._chart_grid_map[period_key] = {"row": row, "col": col, "row_span": 1, "col_span": 2}

    def _clear_grid_region(self, row, col, row_span, col_span):
        """Remove widgets that intersect a specific grid region."""
        # Iterate by current layout items.
        for i in reversed(range(self.charts_layout.count())):
            item = self.charts_layout.itemAt(i)
            w = item.widget() if item else None
            if not w:
                continue

            # Layout returns exact position for the widget.
            r = self.charts_layout.getItemPosition(i)[0]
            c = self.charts_layout.getItemPosition(i)[1]
            rs = self.charts_layout.getItemPosition(i)[2]
            cs = self.charts_layout.getItemPosition(i)[3]

            # Overlap check.
            if (r < row + row_span and r + rs > row and c < col + col_span and c + cs > col):
                self.charts_layout.takeAt(i)
                w.deleteLater()

    def _refresh_single_chart(self, period_key, new_period):
        """Refresh only the chart subsection for the given period key.

        Ensures KPI/insights/appointments remain independent.
        """
        if not self._chart_grid_map:
            self._rebuild_chart_grid_map()

        placement = self._chart_grid_map.get(period_key)
        if not placement:
            self._refresh_charts_content()
            return

        row = placement["row"]
        col = placement["col"]
        row_span = placement["row_span"]
        col_span = placement["col_span"]

        palette = get_active_palette()

        # Clear only this region.
        self._clear_grid_region(row, col, row_span, col_span)

        # Recreate chart container + chart widget.
        if period_key == "revenue_chart":
            labels, rev_vals, cost_vals, net_vals = analytics_repo.get_trend_data('revenue', new_period)
            x_labels = [tr(label) for label in labels]
            chart = SplineChart(

                series_data=[
                    (list(range(len(x_labels))), rev_vals, tr("Revenue"), palette.get("chart_revenue")),
                    (list(range(len(x_labels))), cost_vals, tr("Costs"), palette.get("chart_costs")),
                    (list(range(len(x_labels))), net_vals, tr("Net Income"), palette.get("chart_net")),
                ],
                title="",
                x_axis_labels=x_labels,
                y_axis_range=(0, max(rev_vals + cost_vals + [100]) * 1.2),
                line_width=3,
                palette=palette,
            )
            container = self._create_chart_with_controls(tr("Revenue Trend"), period_key, chart)
            self._add_chart_to_layout(container, chart, row, col, row_span, col_span)
            return

        if period_key == "visits_chart":
            labels, vals = analytics_repo.get_trend_data('visits', new_period)
            x_labels = [tr(label) for label in labels]
            chart = LineChart(

                series_data=[(list(range(len(x_labels))), vals, tr("Visits"))],
                title="",
                x_axis_labels=x_labels,
                y_axis_range=(0, max(vals + [5]) * 1.2),
                palette=palette,
            )
            container = self._create_chart_with_controls(tr("Visits Trend"), period_key, chart, periods=TREND_PERIODS)
            self._add_chart_to_layout(container, chart, row, col, row_span, col_span)
            return

        if period_key == "supplies_chart":
            s_labels, s_series_dict = analytics_repo.get_supplies_category_trend(new_period)
            x_labels = [tr(label) for label in s_labels]

            supp_series_data = []
            max_s_val = 5
            for cat, vals in s_series_dict.items():
                supp_series_data.append((list(range(len(x_labels))), vals, cat))
                if vals:
                    max_s_val = max(max_s_val, max(vals))

            chart = LineChart(
                series_data=supp_series_data,
                title="",
                x_axis_labels=x_labels,
                y_axis_range=(0, max_s_val * 1.2),
                palette=palette,
            )
            container = self._create_chart_with_controls(tr("Supplies Sold Trend"), period_key, chart, periods=TREND_PERIODS)
            self._add_chart_to_layout(container, chart, row, col, row_span, col_span)
            return

        if period_key == "pets_chart":
            pet_dist = analytics_repo.get_pet_distribution(new_period)
            pet_dist = {tr(name): qty for name, qty in pet_dist.items()}
            chart = PieChart(
                data=pet_dist,
                title="",
                palette=palette,
            )
            container = self._create_chart_with_controls(tr("Pet Distribution"), period_key, chart, periods=PIE_PERIODS)
            self._add_chart_to_layout(container, chart, row, col, row_span, col_span)
            return

        if period_key.endswith("_sales"):
            # Expected format: {category_lower}_sales
            category_lower = period_key[: -len("_sales")]
            # Use original category name for repo calls.
            # supply_repo.get_all_categories() returns display names.
            categories = self._supply_categories if getattr(self, "_supply_categories", None) else supply_repo.get_all_categories()
            category = next((c for c in categories if c.lower() == category_lower), category_lower)

            x_labels, sub_series_dict = analytics_repo.get_subcategory_sales_trend(category, new_period)
            x_labels = [tr(label) for label in x_labels]

            sub_series_data = []
            sub_max_y = 5
            for subcat, vals in sub_series_dict.items():
                sub_series_data.append((list(range(len(x_labels))), vals, subcat))
                if vals:
                    sub_max_y = max(sub_max_y, max(vals))

            chart = LineChart(
                series_data=sub_series_data,
                title="",
                x_axis_labels=x_labels,
                y_axis_range=(0, sub_max_y * 1.2),
                palette=palette,
            )
            title = tr("{category} Sales").format(category=tr(category))
            container = self._create_chart_with_controls(title, period_key, chart, periods=TREND_PERIODS)
            self._add_chart_to_layout(container, chart, row, col, row_span, col_span)
            return

        # Fallback
        self._refresh_charts_content()

    def update_chart_theme(self, palette=None):
        """Update chart theme without rebuilding charts every toggle.

        The original implementation rebuilt all charts, which caused heavy DB work
        and UI churn during theme/language changes. We keep a simple guard to
        rebuild once per session; subsequent theme events avoid full rebuild.
        """
        # Always refresh chart colors on theme switch.
        # Charts currently cache palette-derived colors at construction time; if we avoid
        # rebuilding, axes/text/colors can remain on the previous theme until restart.
        self._refresh_charts_content()

