"""
Clinical Analytics Dashboard for the PET Application.
Aggregates key performance indicators (KPIs), upcoming schedules, and 
visual data trends into a consolidated management view.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, 
    QSizePolicy, QGridLayout, QPushButton, QButtonGroup, QTableWidget, 
    QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog
)
from PyQt5.QtCore import Qt, QMargins, QObject, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from datetime import datetime

from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.modules.charts import SplineChart
from src.modules.cards import create_info_card_day
from src.core.repositories.analytics_cache import invalidate_analytics_cache
import src.core.repositories.appointment_repo as appointment_repo
import src.core.repositories.analytics_repo as analytics_repo
import src.core.repositories.followup_repo as followup_repo
import src.core.repositories.user_repo as user_repo
from src.utils.i18n import tr
from src.core.permissions import can, is_admin
from src.core.status_resolver import _DATE_FORMATS

#=========================================== CONSTANTS ===================================================#

# --- Dashboard Tuning Constants ---
TREND_PERIODS = [("Day", "D"), ("Week", "W"), ("Month", "M"), ("Year", "Y")]

DEFAULT_PERIODS = {
    "visits_info": "Month",
    "revenue_chart": "Week"
}

LAYOUT_CONFIG = {
    "chart_min_height": 165
}
ANALYTICS_LIMITS = {
    # Today's Appointments slots shown after the latest completed row:
    # overdue rows first, then the soonest pending rows.
    "late_preview_count": 1,
    "appointment_preview_count": 2
}

CHART_PERIOD_BUTTON_SIZE = (36, 30)
CARD_PERIOD_BUTTON_SIZE = (36, 30)

# Main-window width (px) that turns on the "wide" dashboard affordances: the
# live next-client countdown AND the third action button (the one the current
# role does not treat as a main button) when all three actions are allowed.
WIDE_WINDOW_WIDTH = 1200

#============================================== CODE =====================================================#

class DashboardPage(QWidget):
    def __init__(self, parent=None):
        """Initializes the dashboard page with stats, tables, and charts."""
        super().__init__(parent)

        self._current_user = None

        # Countdown state for the "Next Client Scheduled in" widget.
        # The appointment time is always shown on the right; a live countdown
        # appears in the middle only when the main window is wider than
        # WIDE_WINDOW_WIDTH.
        # `_countdown_expired` latches once the current target's time has
        # passed, so the arrival is handled exactly once (and only re-armed
        # when a genuinely new, future target is read).
        self._next_appointment_time_raw = None
        self._next_appointment_dt = None
        self._countdown_active = False
        self._countdown_expired = False
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start()

        # Guard to prevent expensive repeated refreshes back-to-back.
        self._refresh_pending = False
        
        # State management for period filters
        self.periods = DEFAULT_PERIODS.copy()
        
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
        self.dashboard_layout.setSpacing(10)
        self.dashboard_layout.setContentsMargins(5, 10, 10, 10)
        # Dashboard sections
        self.chart_widgets = [] # To store references to chart widgets for theme updates
        self.period_buttons = []
        self._first_row()
        self._second_row()
        self._charts()
        
        # Add sections to container
        self.dashboard_layout.addWidget(self.first_row_widget)
        self.dashboard_layout.addWidget(self.second_row_widget)
        self.dashboard_layout.addWidget(self.charts_widget)
        
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
        
        self._buttons_connections()
    
    def retranslate_ui(self):
        """Updates all static text on the dashboard when the language changes."""
        self.next_appointment_title.setText(tr("Next Client Scheduled in"))
        self.visits_info_card_title.setText(tr("Monthly Visits"))
        self.upcoming_appointments_table_title.setText(tr("Today's Appointments"))
        self.add_visit_btn.setText(tr("Add Visit"))
        self.bulk_purchase_btn.setText(tr("Add Supplies"))
        self.quick_purchase_btn.setText(tr("Quick Purchase"))
        for btn, label in getattr(self, 'period_buttons', []):
            btn.setText(tr(label))
        
        # Update Table Headers
        self.upcoming_appointments_table.setHorizontalHeaderLabels([tr("Date"), tr("Client"), tr("Pet"), tr("Service"), tr("Status")])
        self.remainders_table_title.setText(tr("Reminders"))
        self.remainders_table.setHorizontalHeaderLabels([tr("Type"), tr("Item / Subject"), tr("Info"), tr("Details")])
        self.remainders_table_view_all_btn.setText(tr("View all"))
        self.upcoming_appointments_table_view_all_btn.setText(tr("View all"))
        
        # Update period buttons (KPIs)
        # Since buttons are recreated or labels are simple keys like 'D', 'W', 
        # we mainly focus on titles. Re-triggering a data refresh updates 
        # status items like 'Pending'/'Completed'.
        self.refresh_data()

    def resizeEvent(self, event):
        """Re-evaluates the widgets that only appear on a wide window.

        Both the live next-client countdown and the wide-only third action
        button use the same threshold (``WIDE_WINDOW_WIDTH``); below it the
        plain appointment time and the role's two main buttons are shown.
        """
        super().resizeEvent(event)
        wide = self.window().width() > WIDE_WINDOW_WIDTH
        if wide != self._countdown_active:
            self._countdown_active = wide
            self.next_appointment_countdown_label.setVisible(wide)
            if wide:
                self._update_countdown()
        self._apply_action_button_visibility()

    def _update_countdown(self):
        """Renders the live countdown to the next appointment (wide windows only).

        The tick doubles as the "appointment time arrived" watcher: the moment
        the current target's time is reached, the schedule is re-read once so
        the widget (and the table below it) move on to the next client instead
        of sitting at ``00:00:00`` forever. That check runs regardless of the
        window width, so a narrow window advances too.
        """
        dt = self._next_appointment_dt
        if dt is not None and not self._countdown_expired:
            if (dt - datetime.now()).total_seconds() <= 0:
                self._countdown_expired = True
                QTimer.singleShot(0, self._advance_schedule)
        if not self._countdown_active:
            return
        label = self.next_appointment_countdown_label
        if dt is None:
            label.setVisible(False)
            return
        total = max(0, int((dt - datetime.now()).total_seconds()))
        if total >= 86400:
            days, rem = divmod(total, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            text = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            hours, rem = divmod(total, 3600)
            minutes, seconds = divmod(rem, 60)
            text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        palette = get_active_palette()
        if total <= 600:
            color = palette.qcolor("state_danger").name()
        elif total < 86400:
            color = palette.qcolor("state_warning").name()
        else:
            color = ""
        label.setStyleSheet(f"color: {color};" if color else "")
        label.setText(text)

    def _advance_schedule(self):
        """Re-reads the next client once the current appointment time arrives.

        The repo compares at minute granularity, so the just-started slot can
        come back for a second or two; in that case the check retries every
        second until the head of the schedule actually moves forward. Once it
        does, the appointments table is rebuilt (a pending row may have just
        turned Late) and the countdown restarts against the new target.
        """
        self._refresh_next_appointment()
        if self._countdown_expired:
            QTimer.singleShot(1000, self._advance_schedule)
            return
        self._refresh_appointments()
        if self._countdown_active:
            self._update_countdown()
    
    def refresh_data(self):
        """Backward-compatible full refresh (stats + appointments + charts)."""
        invalidate_analytics_cache()
        self.refresh_kpis_insights_appointments()
        self.refresh_charts()
    
    def refresh_kpis_insights_appointments(self):
        """Refresh only the KPI/appointments (avoid chart rebuild churn)."""
        self._refresh_stats()
        self._refresh_appointments()
    
    def refresh_charts(self):
        """Refresh only the charts content."""
        self._refresh_charts_content()
        # Ensure chart grid map exists after rebuild.
        self._rebuild_chart_grid_map()
    
    def _refresh_next_appointment(self):
        """Reads the head of the schedule into the "Next Client" widget."""
        doctor_id = user_repo.get_doctor_id(self._current_user)
        if can(self._current_user, "view_own_appointments") and not can(self._current_user, "view_all_appointments"):
            next_time = appointment_repo.get_next_appointment_time(doctor_id=doctor_id)
        else:
            next_time = appointment_repo.get_next_appointment_time()
        self._next_appointment_time_raw = next_time
        self._next_appointment_dt = None
        for fmt in _DATE_FORMATS:
            try:
                self._next_appointment_dt = datetime.strptime(str(next_time).strip(), fmt)
                break
            except (ValueError, TypeError):
                continue
        # Only a future (or empty) target re-arms the arrival watcher; a slot
        # that is still in the past keeps the latch set so `_advance_schedule`
        # retries instead of stacking extra refreshes.
        if self._next_appointment_dt is None or self._next_appointment_dt > datetime.now():
            self._countdown_expired = False
        self.next_appointment_time_label.setText(next_time)
        if self._countdown_active:
            self._update_countdown()

    def _refresh_stats(self):
        """Updates the high-level numeric indicators."""
        self._refresh_next_appointment()
        # info cards
        try:
            mom = analytics_repo.get_month_over_month()
        except Exception:
            mom = {}

        visits_now = mom.get("visits_this_month", 0)
        visits_before = mom.get("visits_last_month", 0)
        self.total_visits_value.setText(str(visits_now))
        self._apply_mom_trend(
            self.visits_trend, visits_now, visits_before, money=False,
        )

        is_admin = can(self._current_user, "view_financials")
        if is_admin:
            rev_now = mom.get("revenue_this_month", 0.0)
            rev_before = mom.get("revenue_last_month", 0.0)
            self.total_revenue_card_title.setText(tr("Monthly Revenue"))
            self.total_revenue_value.setText(f"${rev_now:,.2f}")
            self.revenue_trend["chip"].setVisible(True)
            self._apply_mom_trend(
                self.revenue_trend, rev_now, rev_before, money=True,
            )
        else:
            self.total_revenue_card_title.setText(tr("Daily Revenue"))
            self.total_revenue_value.setText(
                f"${analytics_repo.get_total_revenue('Day'):.2f}"
            )
            self.revenue_trend["chip"].setVisible(False)
        self._refresh_reminders()

    def _apply_mom_trend(self, trend, now, before, money=False):
        """Renders a compact last-month delta pill (arrow + amount + percent)."""
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
            pct_text = tr("new this month")
        else:
            pct_text = "—"

        trend["arrow"].setText(arrow)
        trend["delta"].setText(delta_text)
        trend["pct"].setText(pct_text)
        trend["pct"].setVisible(bool(pct_text))
        trend["caption"].setText(tr("vs last month"))
        trend["chip"].setToolTip(tr("Last month: {value}").format(value=prior_text))

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
            trend[key].setStyleSheet(f"color: {label_color}; background: transparent;")

    def _refresh_reminders(self):
        """Populates the reminders table with live operational alerts."""
        try:
            notifications = analytics_repo.get_notifications(limit=10)
        except Exception:
            notifications = []

        palette = get_active_palette()
        self.remainders_table.setRowCount(0)

        for n in notifications:
            row = self.remainders_table.rowCount()
            self.remainders_table.insertRow(row)

            title_item = QTableWidgetItem(tr(n.get("title", "")))
            title_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            item_item = QTableWidgetItem(n.get("message", ""))
            item_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            info_item = QTableWidgetItem(n.get("info", ""))
            info_item.setTextAlignment(Qt.AlignCenter)

            detail_item = QTableWidgetItem(n.get("details", ""))
            detail_item.setTextAlignment(Qt.AlignCenter)

            severity = n.get("severity", "info")
            if severity == "critical":
                color = palette.qcolor("state_danger")
                for item in (title_item, item_item, info_item, detail_item):
                    item.setForeground(color)
            elif severity == "warning":
                color = palette.qcolor("state_warning")
                for item in (title_item, item_item, info_item, detail_item):
                    item.setForeground(color)

            self.remainders_table.setItem(row, 0, title_item)
            self.remainders_table.setItem(row, 1, item_item)
            self.remainders_table.setItem(row, 2, info_item)
            self.remainders_table.setItem(row, 3, detail_item)
    
    def _refresh_appointments(self):
        """Updates the dashboard's summary view of recent and upcoming appointments.

        The table holds up to four rows, one slot per category:
            1. the most recently completed appointment or follow-up (or, if
               none completed, the most recent past item);
            2. the single Late item closest to its auto-cancellation — the
               earliest scheduled overdue appointment/follow-up;
            3-4. the two soonest pending appointments/follow-ups.
        Empty slots are skipped rather than padded, and duplicates (the past
        fallback can be the very Late item of row 2) are collapsed.
        """
        doctor_id = user_repo.get_doctor_id(self._current_user)
        is_doctor = can(self._current_user, "view_own_appointments") and \
            not can(self._current_user, "view_all_appointments")
        scope_doc = doctor_id if is_doctor else None

        # Most recently completed item (appointment or follow-up) -> first row.
        candidates = list(appointment_repo.get_completed_appointments(
            limit=1, as_table=True, doctor_id=scope_doc))
        completed_followups = followup_repo.get_completed_followups(limit=1, doctor_id=scope_doc)
        if completed_followups:
            fu = completed_followups[0]
            candidates.append((fu["followup_date"], "Follow-up", fu["status"],
                               fu["owner_name"] or "", fu["pet_name"] or ""))
        if candidates:
            first = max(candidates, key=lambda r: str(r[0]))
        else:
            # Fallback: single most recent past item (appointment or follow-up).
            past_rows = list(appointment_repo.get_past_appointments(limit=1, as_table=True, doctor_id=scope_doc))
            past_followups = followup_repo.get_past_followups(limit=1, doctor_id=scope_doc)
            if past_followups:
                fu = past_followups[0]
                past_rows.append((fu["followup_date"], "Follow-up", fu["status"], fu["owner_name"] or "", fu["pet_name"] or ""))
            first = max(past_rows, key=lambda r: str(r[0])) if past_rows else None

        # `fetch_limit` feeds the pending slots; get_past_* has no status
        # filter of its own, so overdue items need a much wider scan.
        fetch_limit = ANALYTICS_LIMITS["appointment_preview_count"] * 3 + 2
        past_scan = fetch_limit * 5
        # Overdue items are part of the schedule too: a "Late" appointment or
        # follow-up is still applicable until it passes the auto-cancel window.
        late_rows = [
            r for r in appointment_repo.get_past_appointments(
                limit=past_scan, as_table=True, doctor_id=scope_doc)
            if r[2] == "Late"
        ]
        pending_rows = [
            r for r in appointment_repo.get_next_appointments(
                limit=fetch_limit, as_table=True, doctor_id=scope_doc)
            if r[2] == "Pending"
        ]
        for followup in followup_repo.get_upcoming_followups(
                limit=fetch_limit, doctor_id=scope_doc):
            row = (followup["followup_date"], "Follow-up", followup["status"],
                   followup["owner_name"] or "", followup["pet_name"] or "")
            # get_upcoming_followups is day-granular, so it also yields
            # follow-ups earlier today — those read back as "Late".
            if followup["status"] == "Late":
                late_rows.append(row)
            elif followup["status"] == "Pending":
                pending_rows.append(row)
        late_rows.extend(
            (followup["followup_date"], "Follow-up", followup["status"],
             followup["owner_name"] or "", followup["pet_name"] or "")
            for followup in followup_repo.get_past_followups(
                limit=past_scan, doctor_id=scope_doc)
            if followup["status"] == "Late"
        )
        # Ascending: the earliest Late row is the one nearest its cancellation.
        late_rows.sort(key=lambda r: str(r[0]))
        pending_rows.sort(key=lambda r: str(r[0]))

        slots = ([first] if first else []) \
            + late_rows[:ANALYTICS_LIMITS["late_preview_count"]] \
            + pending_rows[:ANALYTICS_LIMITS["appointment_preview_count"]]

        # The fallback "first row" (most recent past item) can be the very
        # Late row of slot 2 — show it only once.
        appointments = []
        seen = set()
        for row in slots:
            key = tuple(str(value) for value in row)
            if key in seen:
                continue
            seen.add(key)
            appointments.append(row)

        palette = get_active_palette()
        self.upcoming_appointments_table.setRowCount(len(appointments))
        for row, (date, service, status, client, pet) in enumerate(appointments):
            date_item = QTableWidgetItem(str(date))
            date_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 0, date_item)

            client_item = QTableWidgetItem(str(client) if client else "-")
            client_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 1, client_item)

            pet_item = QTableWidgetItem(str(pet) if pet else "-")
            pet_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 2, pet_item)

            service_item = QTableWidgetItem(tr(str(service)))
            service_item.setTextAlignment(Qt.AlignCenter)
            self.upcoming_appointments_table.setItem(row, 3, service_item)

            status_item = QTableWidgetItem(tr(status))
            status_item.setTextAlignment(Qt.AlignCenter)
            if status == "Pending":
                status_item.setForeground(palette.qcolor("state_warning"))
            elif status == "Completed":
                status_item.setForeground(palette.qcolor("state_success"))
            elif status == "Canceled":
                status_item.setForeground(palette.qcolor("state_danger"))
            elif status == "Late":
                status_item.setForeground(palette.qcolor("state_late"))
            self.upcoming_appointments_table.setItem(row, 4, status_item)
    
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
            # Fallback (shouldn't happen). Keep KPI/appointments intact.
            self._refresh_charts_content()
        
        self._refresh_pending = False
    
    def _first_row(self):
        """Initializes the statistics section (top half of the dashboard)."""
        self.first_row_widget = QWidget()
        self.first_row_layout = QHBoxLayout(self.first_row_widget)
        self.first_row_layout.setContentsMargins(0, 0, 0, 0)
        self.first_row_layout.setSpacing(10)
        
        self.add_visit_btn = QPushButton(tr("Add Visit"))
        self.add_visit_btn.setMinimumSize(160, 48)
        self.first_row_layout.addWidget(self.add_visit_btn, 2)
        
        self.bulk_purchase_btn = QPushButton(tr("Add Supplies"))
        self.bulk_purchase_btn.setMinimumSize(160, 48)
        self.first_row_layout.addWidget(self.bulk_purchase_btn, 2)

        self.quick_purchase_btn = QPushButton(tr("Quick Purchase"))
        self.quick_purchase_btn.setMinimumSize(160, 48)
        self.first_row_layout.addWidget(self.quick_purchase_btn, 2)

        card_visits, self.total_visits_value, self.visits_info_card_title, self.visits_trend = create_info_card_day(
            self, tr("Monthly Visits"), "visits_info",
        )
        self.card_revenue, self.total_revenue_value, self.total_revenue_card_title, self.revenue_trend = create_info_card_day(
            self, tr("Daily Revenue"), "revenue_info",
        )

        self.first_row_layout.addWidget(card_visits, 3)
        self.first_row_layout.addWidget(self.card_revenue, 3)
    
    def _second_row(self):
        """Initializes the statistics section (top half of the dashboard)."""
        self.second_row_widget = QWidget()
        self.second_row_layout = QHBoxLayout(self.second_row_widget)
        self.second_row_layout.setContentsMargins(0, 0, 0, 0)
        self.second_row_layout.setSpacing(10)
        
        # Remainders table(template)
        self.remainders_widget= QFrame()
        self.remainders_widget.setObjectName("dashboard_remainders_card")
        self.remainders_layout= QVBoxLayout(self.remainders_widget)
        self.remainders_layout.setContentsMargins(0, 5, 0, 0)
        
        # Remainders table title with view all button
        self.remainders_table_header_layout = QHBoxLayout()
        self.remainders_table_header_layout.setContentsMargins(10, 0, 10, 0)
        
        self.remainders_table_title = QLabel(tr("Reminders"))
        self.remainders_table_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.remainders_table_header_layout.addWidget(self.remainders_table_title)
        self.remainders_table_header_layout.addStretch(3)

        self.remainders_table_view_all_btn = QPushButton(tr("View all"))
        self.remainders_table_view_all_btn.setProperty("action", "view-all")
        self.remainders_table_view_all_btn.setMinimumSize(80, 24)
        self.remainders_table_header_layout.addWidget(self.remainders_table_view_all_btn, 1)
        self.remainders_layout.addLayout(self.remainders_table_header_layout)
        
        self.remainders_table = QTableWidget()
        self.remainders_table.setObjectName("dashboard_remainders_table")
        self.remainders_table.setColumnCount(4)
        self.remainders_table.setHorizontalHeaderLabels([tr("Type"), tr("Item / Subject"), tr("Info"), tr("Details")])
        self.remainders_table.horizontalHeader().setStretchLastSection(True)
        self.remainders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable columns resizing
        self.remainders_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.remainders_table.setColumnWidth(0, 140)
        self.remainders_table.setColumnWidth(1, 160)
        self.remainders_table.setColumnWidth(2, 130)
        self.remainders_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable rows resizing
        self.remainders_table.verticalHeader().setVisible(False)# Hide index column
        self.remainders_table.verticalHeader().setDefaultSectionSize(32)# set default row height
        self.remainders_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.remainders_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.remainders_table.setMinimumSize(300,100)
        self.remainders_table.setAlternatingRowColors(True)
        
        
        self.remainders_layout.addWidget(self.remainders_table)
        self.second_row_layout.addWidget(self.remainders_widget, 1)
        
        # Right Side:
        right_side_layout = QVBoxLayout()
        right_side_layout.setAlignment(Qt.AlignTop)
        
        # Next Appointment Status
        self.status_widget = QFrame()
        self.status_widget.setProperty("class", "status-card")
        self.status_widget.setMinimumHeight(50)
        self.status_layout = QHBoxLayout(self.status_widget)
        
        self.next_appointment_title = QLabel(tr("Next Client Scheduled in"))
        self.next_appointment_title.setProperty("class", "status-title")
        self.next_appointment_title.setAlignment(Qt.AlignAbsolute | Qt.AlignLeft | Qt.AlignVCenter)
        self.status_layout.addWidget(self.next_appointment_title)
        self.status_layout.addStretch()
        self.next_appointment_countdown_label = QLabel()
        self.next_appointment_countdown_label.setProperty("class", "status-value")
        self.next_appointment_countdown_label.setAlignment(Qt.AlignCenter)
        self.next_appointment_countdown_label.setVisible(False)
        self.status_layout.addWidget(self.next_appointment_countdown_label, 1)
        self.status_layout.addStretch()
        self.next_appointment_time_label = QLabel()
        self.next_appointment_time_label.setProperty("class", "status-value")
        self.next_appointment_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_layout.addWidget(self.next_appointment_time_label)
        
        right_side_layout.addWidget(self.status_widget)
        
        self.upcoming_appointments_widget = QFrame()
        self.upcoming_appointments_widget.setObjectName("dashboard_upcoming_appointments_card")
        self.upcoming_appointments_layout= QVBoxLayout(self.upcoming_appointments_widget)
        self.upcoming_appointments_layout.setContentsMargins(0, 5, 0, 0)
        
        # Upcoming Appointments Table
        self.upcoming_appointments_header_layout = QHBoxLayout()
        self.upcoming_appointments_header_layout.setContentsMargins(10, 0, 10, 0)
        
        self.upcoming_appointments_table_title = QLabel(tr("Today's Appointments"))
        self.upcoming_appointments_table_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.upcoming_appointments_header_layout.addWidget(self.upcoming_appointments_table_title)
        self.upcoming_appointments_header_layout.addStretch(3)

        self.upcoming_appointments_table_view_all_btn = QPushButton(tr("View all"))
        self.upcoming_appointments_table_view_all_btn.setProperty("action", "view-all")
        self.upcoming_appointments_table_view_all_btn.setMinimumSize(80, 24)
        self.upcoming_appointments_header_layout.addWidget(self.upcoming_appointments_table_view_all_btn, 1)
        self.upcoming_appointments_layout.addLayout(self.upcoming_appointments_header_layout)
        
        self.upcoming_appointments_table = QTableWidget()
        self.upcoming_appointments_table.setObjectName("dashboard_upcoming_appointments_table")
        self.upcoming_appointments_table.setColumnCount(5)
        self.upcoming_appointments_table.setHorizontalHeaderLabels([tr("Date"), tr("Client"), tr("Pet"), tr("Service"), tr("Status")])
        self.upcoming_appointments_table.horizontalHeader().setStretchLastSection(True)
        self.upcoming_appointments_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable columns resizing
        self.upcoming_appointments_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.upcoming_appointments_table.setColumnWidth(0, 180)
        self.upcoming_appointments_table.setColumnWidth(1, 120)
        self.upcoming_appointments_table.setColumnWidth(2, 100)
        self.upcoming_appointments_table.setColumnWidth(3, 100)
        self.upcoming_appointments_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)# disable rows resizing
        self.upcoming_appointments_table.verticalHeader().setVisible(False)# Hide index column
        self.upcoming_appointments_table.verticalHeader().setDefaultSectionSize(32)# set default row height
        self.upcoming_appointments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upcoming_appointments_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming_appointments_table.setMinimumSize(300,130)
        self.upcoming_appointments_table.setAlternatingRowColors(True)
        
        self.upcoming_appointments_layout.addWidget(self.upcoming_appointments_table)
        right_side_layout.addWidget(self.upcoming_appointments_widget)
        self.second_row_layout.addLayout(right_side_layout, 1)
        
    def set_current_user(self, user):
        """Gate dashboard action buttons based on the current user's role."""
        self._current_user = user
        self._apply_action_button_visibility()
        self.refresh_data()

    def _apply_action_button_visibility(self):
        """Shows/hides the three action buttons for the current user.

        Every button follows its permission. When a user is allowed all THREE,
        the role's two main buttons stay visible and the third one (Quick
        Purchase for admins, Add Supplies for everyone else) only appears once
        the window is wider than ``WIDE_WINDOW_WIDTH`` — the same threshold as
        the next-client countdown. A partial grant is never width-gated:
        whatever is allowed shows at any width.
        """
        if not hasattr(self, "quick_purchase_btn"):
            return
        granted = {
            "add_visit": can(self._current_user, "add_visit"),
            "add_supplies": can(self._current_user, "add_supplies"),
            "quick_purchase": can(self._current_user, "quick_purchase"),
        }
        wide_only = None
        if all(granted.values()):
            wide_only = "quick_purchase" if is_admin(self._current_user) else "add_supplies"
        wide = self.window().width() > WIDE_WINDOW_WIDTH
        for action, btn in (
            ("add_visit", self.add_visit_btn),
            ("add_supplies", self.bulk_purchase_btn),
            ("quick_purchase", self.quick_purchase_btn),
        ):
            btn.setVisible(granted[action] and (action != wide_only or wide))

    def _open_reminders_dialog(self):
        """Open the full reminders dialog for all roles, or pending changes dialog for admin approvals."""
        from src.ui.dialogs.reminders_dialog import RemindersDialog
        from src.ui.dialogs.pending_changes_dialog import PendingChangesDialog
        if can(self._current_user, "approve_changes"):
            from src.core.repositories.pending_changes_repo import get_pending_count
            if get_pending_count() > 0:
                dialog = PendingChangesDialog(current_user=self._current_user, parent=self)
                dialog.data_changed.connect(self.refresh_data)
                dialog.exec()
                return

        dialog = RemindersDialog(current_user=self._current_user, parent=self)
        dialog.exec()

    def _buttons_connections(self):
        self.add_visit_btn.clicked.connect(self.add_visit)
        self.bulk_purchase_btn.clicked.connect(self.add_bulk_purchase)
        self.quick_purchase_btn.clicked.connect(self.add_quick_purchase)
        self.remainders_table_view_all_btn.clicked.connect(self._open_reminders_dialog)
        self.upcoming_appointments_table_view_all_btn.clicked.connect(self._open_all_appointments)

    def _open_all_appointments(self):
        """Opens the complete appointment list in a modal dialog."""
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog

        dialog = AppointmentsDialog(current_user=self._current_user, parent=self)
        dialog.exec_()
        # Always refresh the dashboard's appointments (today's table)
        # and the next client timer, and also try to refresh visits page
        # appointments if present — without forcing a page jump on close.
        self.refresh_kpis_insights_appointments()
        try:
            main_page = getattr(self.window(), "main_page", None)
            db_page = getattr(main_page, "database_page", None) if main_page else None
            if db_page is not None and hasattr(db_page, "visits_page"):
                db_page.visits_page.refresh_appointments()
        except Exception:
            pass
    
    def add_visit(self):
        from src.ui.dialogs.full_entry_dialog import AddFullEntryDialog

        dialog = AddFullEntryDialog(self, current_user=self._current_user)
        if dialog.exec_():
            # Refresh all pages that depend on visit data by delegating to
            # visits_page, which already has the full data_changed wiring in
            # main_window (clients, supplies, receipts, dashboard, reports).
            main_win = self.window()
            main_page = getattr(main_win, "main_page", None)
            db_page = getattr(main_page, "database_page", None) if main_page is not None else None
            if db_page is not None:
                db_page.visits_page.refresh_visits_table()
                db_page.visits_page.data_changed.emit()
            self.refresh_data()
    
    def add_bulk_purchase(self):
        from src.ui.pages.database_pages.supplies_page import BulkPurchaseDialog, process_bulk_purchase_items

        dialog = BulkPurchaseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            if process_bulk_purchase_items(
                    self, dialog.get_data(),
                    audit_user_id=(self._current_user or {}).get("user_id"),
                    discount=dialog.discount_cash(),
                    paid_amount=dialog.paid_cash(),
                    payment_method=dialog.payment_method(),
                ) > 0:
                self.refresh_kpis_insights_appointments()
                # Notify the rest of the app so inventory/receipt pages stay in sync.
                main_win = self.window()
                main_page = getattr(main_win, "main_page", None)
                database_page = getattr(main_page, "database_page", None) if main_page is not None else None
                supplies_page = getattr(database_page, "supplies_page", None) if database_page is not None else None
                if supplies_page is not None:
                    supplies_page.refresh_all_tabs()
                    supplies_page.data_changed.emit()

    def add_quick_purchase(self):
        from src.ui.dialogs.quick_purchase_dialog import QuickPurchaseDialog

        dialog = QuickPurchaseDialog(self, current_user=self._current_user)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_kpis_insights_appointments()
            # Notify the rest of the app (receipts, supplies, visits) by
            # delegating to visits_page's data_changed, which already has the
            # full fan-out wiring in main_window.
            main_win = self.window()
            main_page = getattr(main_win, "main_page", None)
            db_page = getattr(main_page, "database_page", None) if main_page is not None else None
            if db_page is not None and hasattr(db_page, "visits_page"):
                db_page.visits_page.data_changed.emit()
    
    def _charts(self):
        """Initializes the charts container."""
        self.charts_widget = QWidget()
        self.charts_widget.setObjectName("dashboard_charts_widget")
        self.charts_layout = QGridLayout(self.charts_widget)
        self.charts_layout.setContentsMargins(0, 0, 0, 0)
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
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        
        chart_obj.setMinimumHeight(LAYOUT_CONFIG["chart_min_height"])
        
        # Make the chart view and internal chart transparent to adopt the card's background
        chart_obj.setStyleSheet("background: transparent; border: none;")
        chart_obj.setContentsMargins(0, 0, 0, 0)
        chart_obj.chart().setMargins(QMargins(0, 0, 0, 0))
        chart_obj.chart().setBackgroundVisible(False)
        chart_obj.chart().setPlotAreaBackgroundVisible(False)
        chart_obj.chart().layout().setContentsMargins(0, 0, 0, 0)
        
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
        can_fin = can(self._current_user, "view_financials")

        # 1. Revenue Chart
        rev_labels, rev_vals, cost_vals, net_vals = analytics_repo.get_trend_data('revenue', self.periods["revenue_chart"])
        rev_labels = [tr(label) for label in rev_labels]
        series_data = [(list(range(len(rev_labels))), rev_vals, tr("Revenue"), palette.get("chart_revenue"))]
        if can_fin:
            series_data.extend([
                (list(range(len(rev_labels))), cost_vals, tr("Costs"), palette.get("chart_costs")),
                (list(range(len(rev_labels))), net_vals, tr("Net Income"), palette.get("chart_net")),
            ])
        all_vals = rev_vals + (cost_vals if can_fin else [])
        if can_fin:
            all_vals += net_vals
        if all_vals:
            y_min = min(all_vals) * 1.2
            y_max = max(all_vals) * 1.2
        else:
            y_min = 0; y_max = 100
        revenue_chart = SplineChart(
            series_data=series_data,
            title=tr("Revenue Trend"),
            x_axis_labels=rev_labels,
            y_axis_range=(y_min if y_min < 0 else 0, y_max if y_max > 0 else 100),
            line_width=3,
            palette=palette,
        )
        self._add_chart_to_layout(self._create_chart_with_controls(tr("Revenue Trend"), "revenue_chart", revenue_chart), revenue_chart, 0, 0, 1, 4)
    
    def _add_chart_to_layout(self, chart_container, chart_obj, row, col, row_span, col_span):
        """Helper to add a chart widget to the layout and store its reference."""
        self.charts_layout.addWidget(chart_container, row, col, row_span, col_span)
        if chart_obj:
            self.chart_widgets.append(chart_obj)
    
    def _rebuild_chart_grid_map(self):
        """Rebuild mapping from period keys to grid placements."""
        self._chart_grid_map = {}

        # Fixed chart placements (from _refresh_charts_content).
        self._chart_grid_map["revenue_chart"] = {"row": 0, "col": 0, "row_span": 1, "col_span": 4}

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

        Ensures KPI/appointments remain independent.
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
            series_data = [(list(range(len(x_labels))), rev_vals, tr("Revenue"), palette.get("chart_revenue"))]
            if can(self._current_user, "view_financials"):
                series_data.extend([
                    (list(range(len(x_labels))), cost_vals, tr("Costs"), palette.get("chart_costs")),
                    (list(range(len(x_labels))), net_vals, tr("Net Income"), palette.get("chart_net")),
                ])
            can_fin = can(self._current_user, "view_financials")
            all_vals = rev_vals + (cost_vals if can_fin else [])
            if can_fin:
                all_vals += net_vals
            if all_vals:
                y_min = min(all_vals) * 1.2
                y_max = max(all_vals) * 1.2
            else:
                y_min = 0; y_max = 100
            chart = SplineChart(
                series_data=series_data,
                title="",
                x_axis_labels=x_labels,
                y_axis_range=(y_min if y_min < 0 else 0, y_max if y_max > 0 else 100),
                line_width=3,
                palette=palette,
            )
            container = self._create_chart_with_controls(tr("Revenue Trend"), period_key, chart)
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
