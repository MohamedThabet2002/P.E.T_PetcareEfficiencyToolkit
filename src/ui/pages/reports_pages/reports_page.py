"""
Interactive reports workspace (compact period bar, calendar popup, exports, history).

This module hosts the reports page wrapper. The pinned header is a slim toolbar:
title and actions on the first row, period trigger / nudge / granularity on the
second. The restyled :class:`QCalendarWidget` (and quick presets) live in a popup
opened from the period trigger — clicking a day always shows **live** data for
that window. The report categories live in a ``QTabWidget`` and a collapsible
**Report History** panel on the right lists the snapshots a user explicitly
saved ("Save Report"), letting a decision-maker reopen, compare, export or
delete them.

Each category tab is self-contained and handles its own visibility, refresh and
translation; every tab scrolls its own content so the tabs widget never resizes.
"""

import csv
import logging
from html import escape
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QButtonGroup, QTableWidgetItem, QFileDialog, QMessageBox,
    QCalendarWidget, QTabWidget, QSizePolicy, QStyle, QLineEdit, QTreeWidget,
    QTreeWidgetItem, QAbstractItemView, QApplication,
)
from PyQt5.QtCore import Qt, QDateTime, QDate, QEvent, QPoint
from PyQt5.QtGui import QColor, QBrush, QTextCharFormat, QTextDocument, QFont
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

from src.ui.themes.color_palettes import get_active_palette, ThemeManager
import src.core.repositories.analytics_repo as analytics_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.audit_repo as audit_repo
import src.core.repositories.client_repo as client_repo
import src.core.repositories.report_archive_repo as report_archive_repo
from src.core.repositories.analytics_cache import invalidate_analytics_cache
from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager
from src.core.permissions import can

from src.ui.pages.reports_pages.base_tab import (
    BaseReportTab, TREND_PERIODS, PIE_PERIODS, DEFAULT_PERIODS,
    DEFAULT_SUPPLY_SALES_CHART_PERIODS, LAYOUT_CONFIG, ANALYTICS_LIMITS,
    CHART_PERIOD_BUTTON_SIZE,
)
from src.ui.pages.reports_pages.overview_tab import OverviewTab
from src.ui.pages.reports_pages.financial_tab import FinancialTab
from src.ui.pages.reports_pages.patient_tab import PatientTab
from src.ui.pages.reports_pages.supply_tab import SupplyTab
from src.ui.pages.reports_pages.audit_tab import AuditTab
from src.ui.dialogs.compare_reports_dialog import CompareReportsDialog

logger = logging.getLogger(__name__)

#=========================================== CONSTANTS ===================================================#

GRANULARITY_KEYS = ["Day", "Week", "Month", "Quarter", "Year", "Custom"]

REPORT_KIND_KEYS = [
    "Overview Analytics",
    "Financial Report",
    "Client Report",
    "Supply Report",
    "Audit Log Report",
]

REPORT_TAB_CLASSES = [
    OverviewTab,
    FinancialTab,
    PatientTab,
    SupplyTab,
    AuditTab,
]

GRANULARITY_BUTTON_SIZE = (50, 30)
AUDIT_TAB_INDEX = len(REPORT_KIND_KEYS) - 1

# (i18n label key, resolver key) for the quick period presets.
PRESET_KEYS = [
    ("Today", "today"),
    ("This Week", "this_week"),
    ("Last Week", "last_week"),
    ("This Month", "this_month"),
    ("Last Month", "last_month"),
    ("This Quarter", "this_quarter"),
    ("Year to Date", "ytd"),
]

# KPI keys exported from a saved snapshot ("Metric", kpis key).
_SNAPSHOT_KPI_EXPORT = [
    ("Total Visits", "visits"),
    ("Total Revenue", "revenue"),
    ("Supplies Used", "supplies_used"),
    ("Avg Revenue / Visit", "avg_revenue"),
    ("Total Costs", "costs"),
    ("Net Profit", "net_profit"),
    ("Low Stock Supplies", "low_stock"),
    ("Busiest Client", "busiest_client"),
]


#=========================================== PERIOD HELPERS ==============================================#

def _fmt(qdate):
    """Formats a QDate as 'YYYY-MM-DD'."""
    return qdate.toString("yyyy-MM-dd")


def _week_bounds(qdate):
    """Returns the Monday..Sunday window containing ``qdate``."""
    monday = qdate.addDays(-(qdate.dayOfWeek() - 1))
    return monday, monday.addDays(6)


def _month_bounds(qdate):
    """Returns the first..last day of ``qdate``'s month."""
    first = QDate(qdate.year(), qdate.month(), 1)
    return first, first.addMonths(1).addDays(-1)


def _quarter_bounds(qdate):
    """Returns the first..last day of ``qdate``'s calendar quarter."""
    q = (qdate.month() - 1) // 3
    first = QDate(qdate.year(), q * 3 + 1, 1)
    return first, first.addMonths(3).addDays(-1)


def _last_week_bounds(qdate):
    """Returns the Monday..Sunday window before ``qdate``'s week."""
    monday, _ = _week_bounds(qdate)
    return monday.addDays(-7), monday.addDays(-1)


def _last_month_bounds(qdate):
    """Returns the calendar month before ``qdate``'s month."""
    first, _ = _month_bounds(qdate)
    return _month_bounds(first.addDays(-1))


def _preset_window(key, today=None):
    """Returns (start, end) QDates for a preset key (calendar-aligned windows)."""
    t = today or QDate.currentDate()
    if key == "today":
        return t, t
    if key == "this_week":
        return _week_bounds(t)
    if key == "last_week":
        return _last_week_bounds(t)
    if key == "this_month":
        return _month_bounds(t)
    if key == "last_month":
        return _last_month_bounds(t)
    if key == "this_quarter":
        return _quarter_bounds(t)
    if key == "ytd":
        return QDate(t.year(), 1, 1), t
    return t, t


def _window_str(start, end):
    """Formats a window as a single day or 'start — end'."""
    if start and end and start != end:
        return f"{start} — {end}"
    return start or end


#============================================== CODE =====================================================#

class ReportsPage(QWidget):
    """Interactive reports workspace with a compact period bar, calendar popup and history panel.

    Layout (top to bottom):
        1. Slim header card — title + live summary + History/Save/Refresh/export
           on the first row; period trigger, nudge arrows and granularity on the
           second. The calendar and quick presets open from the period trigger.
        2. Saved-report banner while reviewing a snapshot.
        3. A horizontal split: the report category tabs (left) and the collapsible
           Report History panel (right).

    The calendar only navigates periods — clicking a day always shows live data.
    Saved reports come exclusively from the explicit "Save Report" action, so the
    history is a deliberate, decision-maker-friendly log rather than noise.
    """

    def __init__(self, parent=None):
        """Initializes the reports page with period bar, calendar, tabs and history."""
        super().__init__(parent)
        self._current_user = None
        self._viewing_archive = None

        # State management for the calendar range.
        self._granularity = "Day"
        self._selected_date = QDate.currentDate()
        self.granularity_buttons = []
        self._custom_range = None      # (start, end) 'YYYY-MM-DD' from presets / two-click
        self._custom_pending = None    # start date chosen on the calendar, awaiting the end date

        # Page header (compact period bar; calendar opens from the trigger)
        self._setup_report_toolbar()

        # Saved-report banner (hidden by default)
        self._setup_archive_banner()

        # Report category tabs; each tab scrolls its own content.
        self.tabs = QTabWidget()
        self.tabs.setObjectName("reportsTabs")
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        self.report_tabs = []
        for tab_key, tab_cls in zip(REPORT_KIND_KEYS, REPORT_TAB_CLASSES):
            self._add_report_tab(tab_key, tab_cls)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Right-side Report History panel.
        self._setup_history_panel()

        # Body: tabs (stretch) + history panel (fixed width on the right).
        body = QHBoxLayout()
        body.setContentsMargins(14, 8, 14, 12)
        body.setSpacing(10)
        body.addWidget(self.tabs, 1)
        body.addWidget(self.history_panel, 0)

        # Final layout: pinned header, banner, then the tabs + history body. No
        # outer scroll — each tab scrolls itself so the tabs widget stays fixed.
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.header_widget)
        main_layout.addWidget(self.archive_banner_frame)
        main_layout.addLayout(body, 1)

        # Named per-tab attributes for convenient access/import.
        self.overview_tab, self.financial_tab, self.patient_tab, self.supply_tab, self.audit_tab = self.report_tabs

        self.tabs.setCurrentIndex(0)

        # Connect to global theme changes
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        # Initial data load for the first tab.
        self._refresh_range_label()
        self.refresh_data()

    # ----------------------------------------- header ----------------------------------------- #

    def _setup_report_toolbar(self):
        """Builds the compact page header: actions, period trigger, exports."""
        self.header_widget = QFrame()
        self.header_widget.setProperty("class", "reports-header-card")
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        header_root = QVBoxLayout(self.header_widget)
        header_root.setContentsMargins(12, 8, 12, 8)
        header_root.setSpacing(6)

        # --- Title row: page title + summary, then page / export actions ---
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.page_title_label = QLabel(tr("Reports & Analytics"))
        self.page_title_label.setProperty("class", "reports-page-title")
        subtitle = tr(
            "Analyze clinic performance, finances, inventory and activity across the selected period."
        )
        self.page_subtitle_label = QLabel(subtitle)
        self.page_subtitle_label.hide()
        self.page_title_label.setToolTip(subtitle)
        title_row.addWidget(self.page_title_label)
        title_row.addStretch()

        self.summary_line_label = QLabel()
        self.summary_line_label.setProperty("class", "reports-summary-line")
        self.summary_line_label.setAlignment(Qt.AlignVCenter)
        title_row.addWidget(self.summary_line_label)

        self.history_toggle_btn = QPushButton(tr("Report History"))
        self.history_toggle_btn.setCheckable(True)
        self.history_toggle_btn.setChecked(True)
        self.history_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.history_toggle_btn.setProperty("class", "secondary-action")
        self.history_toggle_btn.toggled.connect(self._toggle_history_panel)
        title_row.addWidget(self.history_toggle_btn)

        self.save_report_btn = QPushButton(tr("Save Report"))
        self.save_report_btn.setProperty("class", "primary-action")
        self.save_report_btn.setCursor(Qt.PointingHandCursor)
        self.save_report_btn.clicked.connect(self._save_current_report)
        title_row.addWidget(self.save_report_btn)

        self.refresh_btn = QPushButton(tr("Refresh"))
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_btn.setProperty("class", "secondary-action")
        self.refresh_btn.clicked.connect(self.refresh_data)
        title_row.addWidget(self.refresh_btn)

        self.export_excel_btn = QPushButton(tr("Export Excel"))
        self.export_excel_btn.setProperty("class", "secondary-action")
        self.export_excel_btn.clicked.connect(self._export_current_report_excel)
        self.export_csv_btn = QPushButton(tr("Export CSV"))
        self.export_csv_btn.setProperty("class", "secondary-action")
        self.export_csv_btn.clicked.connect(self._export_current_report_csv)
        self.print_pdf_btn = QPushButton(tr("Print / PDF"))
        self.print_pdf_btn.setProperty("class", "secondary-action")
        self.print_pdf_btn.clicked.connect(self._print_current_report)
        title_row.addWidget(self.export_excel_btn)
        title_row.addWidget(self.export_csv_btn)
        title_row.addWidget(self.print_pdf_btn)
        header_root.addLayout(title_row)

        # --- Period row: nudge + date trigger + granularity ---
        period_row = QHBoxLayout()
        period_row.setSpacing(8)

        self.nudge_back_btn = QPushButton("\u2039")
        self.nudge_back_btn.setProperty("class", "reports-nudge")
        self.nudge_back_btn.setCursor(Qt.PointingHandCursor)
        self.nudge_back_btn.setFixedSize(28, 28)
        self.nudge_back_btn.setToolTip(tr("Previous period"))
        self.nudge_back_btn.clicked.connect(lambda: self._nudge(-1))
        period_row.addWidget(self.nudge_back_btn)

        self.period_trigger = QFrame()
        self.period_trigger.setProperty("class", "reports-period-trigger")
        self.period_trigger.setCursor(Qt.PointingHandCursor)
        self.period_trigger.setToolTip(tr("Select dates"))
        self.period_trigger.installEventFilter(self)
        trigger_layout = QHBoxLayout(self.period_trigger)
        trigger_layout.setContentsMargins(10, 4, 8, 4)
        trigger_layout.setSpacing(8)
        trigger_text = QVBoxLayout()
        trigger_text.setContentsMargins(0, 0, 0, 0)
        trigger_text.setSpacing(0)
        self.report_granularity_label = QLabel()
        self.report_granularity_label.setProperty("class", "reports-range-title")
        self.report_granularity_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.report_range_label = QLabel()
        self.report_range_label.setProperty("class", "reports-range-value")
        self.report_range_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        trigger_text.addWidget(self.report_granularity_label)
        trigger_text.addWidget(self.report_range_label)
        trigger_layout.addLayout(trigger_text, 1)
        self._period_chevron = QLabel("\u25be")
        self._period_chevron.setProperty("class", "reports-period-chevron")
        self._period_chevron.setAttribute(Qt.WA_TransparentForMouseEvents)
        trigger_layout.addWidget(self._period_chevron)
        period_row.addWidget(self.period_trigger, 0)

        self.nudge_fwd_btn = QPushButton("\u203a")
        self.nudge_fwd_btn.setProperty("class", "reports-nudge")
        self.nudge_fwd_btn.setCursor(Qt.PointingHandCursor)
        self.nudge_fwd_btn.setFixedSize(28, 28)
        self.nudge_fwd_btn.setToolTip(tr("Next period"))
        self.nudge_fwd_btn.clicked.connect(lambda: self._nudge(1))
        period_row.addWidget(self.nudge_fwd_btn)

        granularity_frame = QFrame()
        granularity_frame.setProperty("class", "timestamp-button-group")
        granularity_layout = QHBoxLayout(granularity_frame)
        granularity_layout.setContentsMargins(0, 0, 0, 0)
        granularity_layout.setSpacing(2)

        self.granularity_group = QButtonGroup(granularity_frame)
        for g_name in GRANULARITY_KEYS:
            g_btn = QPushButton(tr(g_name))
            g_btn.setCheckable(True)
            g_btn.setFixedSize(GRANULARITY_BUTTON_SIZE[0], CHART_PERIOD_BUTTON_SIZE[1])
            g_btn.setProperty("class", "timestamp-button-group")
            g_btn.setCursor(Qt.PointingHandCursor)
            if self._granularity == g_name:
                g_btn.setChecked(True)
            self.granularity_group.addButton(g_btn)
            granularity_layout.addWidget(g_btn)
            g_btn.clicked.connect(lambda _, g=g_name: self._on_granularity_changed(g))
            self.granularity_buttons.append((g_btn, g_name))
        period_row.addWidget(granularity_frame)
        period_row.addStretch()
        header_root.addLayout(period_row)

        self._setup_calendar_popup()

    def _setup_calendar_popup(self):
        """Builds the dropdown that holds quick presets and the navigator calendar."""
        self._calendar_popup = QFrame(self, Qt.Popup)
        self._calendar_popup.setProperty("class", "reports-calendar-popup")

        pop = QHBoxLayout(self._calendar_popup)
        pop.setContentsMargins(10, 10, 10, 10)
        pop.setSpacing(10)

        presets_col = QVBoxLayout()
        presets_col.setSpacing(4)
        presets_col.setContentsMargins(0, 0, 0, 0)
        self.preset_buttons = []
        for label_key, resolver in PRESET_KEYS:
            chip = QPushButton(tr(label_key))
            chip.setProperty("class", "reports-preset-chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            chip.clicked.connect(lambda _, r=resolver: self._apply_preset(r))
            presets_col.addWidget(chip)
            self.preset_buttons.append((chip, label_key))
        presets_col.addStretch()
        pop.addLayout(presets_col, 0)

        cal_col = QVBoxLayout()
        cal_col.setSpacing(6)
        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("reportsCalendar")
        self.calendar.setFixedSize(
            LAYOUT_CONFIG["calendar_width"], LAYOUT_CONFIG["calendar_height"]
        )
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar_font = self.calendar.font()
        calendar_font.setPointSize(9)
        self.calendar.setFont(calendar_font)
        self.calendar.setSelectedDate(self._selected_date)
        self.calendar.clicked.connect(self._on_calendar_clicked)
        cal_inner_layout = self.calendar.layout()
        if cal_inner_layout is not None:
            cal_inner_layout.setContentsMargins(0, 0, 0, 0)
            cal_inner_layout.setSpacing(0)
        cal_col.addWidget(self.calendar)

        self.calendar_hint_label = QLabel(tr("Pick two dates to set a range"))
        self.calendar_hint_label.setProperty("class", "reports-calendar-hint")
        self.calendar_hint_label.setWordWrap(True)
        self.calendar_hint_label.hide()
        cal_col.addWidget(self.calendar_hint_label)
        pop.addLayout(cal_col, 0)

    def eventFilter(self, obj, event):
        """Opens the calendar popup when the period trigger is clicked."""
        if obj is getattr(self, "period_trigger", None) and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self._toggle_calendar_popup()
                return True
        return super().eventFilter(obj, event)

    def _toggle_calendar_popup(self):
        """Shows or hides the period calendar dropdown."""
        if self._calendar_popup.isVisible():
            self._hide_calendar_popup()
            return
        self._show_calendar_popup()

    def _show_calendar_popup(self):
        """Anchors the calendar dropdown under the period trigger."""
        self._refresh_calendar()
        if self._selected_date.isValid():
            self.calendar.setSelectedDate(self._selected_date)
        self._sync_calendar_hint()
        self._calendar_popup.adjustSize()

        origin = self.period_trigger.mapToGlobal(
            QPoint(0, self.period_trigger.height() + 4)
        )
        screen = QApplication.desktop().availableGeometry(self)
        popup_size = self._calendar_popup.sizeHint()
        x = min(origin.x(), screen.right() - popup_size.width() - 8)
        y = origin.y()
        if y + popup_size.height() > screen.bottom():
            y = self.period_trigger.mapToGlobal(QPoint(0, 0)).y() - popup_size.height() - 4
        self._calendar_popup.move(max(screen.left() + 8, x), max(screen.top() + 8, y))
        self._calendar_popup.show()
        self._calendar_popup.raise_()

    def _hide_calendar_popup(self):
        """Closes the period calendar dropdown if it is open."""
        if hasattr(self, "_calendar_popup") and self._calendar_popup.isVisible():
            self._calendar_popup.hide()

    def _sync_calendar_hint(self):
        """Shows the two-click custom-range hint only while that mode is active."""
        if not hasattr(self, "calendar_hint_label"):
            return
        if self._granularity != "Custom":
            self.calendar_hint_label.hide()
            return
        if self._custom_pending:
            self.calendar_hint_label.setText(tr("Select end date…"))
        else:
            self.calendar_hint_label.setText(tr("Pick two dates to set a range"))
        self.calendar_hint_label.show()

    def _add_report_tab(self, tab_key, tab_cls):
        """Creates a tab page hosting a self-contained report widget.

        Each tab is its own scrollable widget (see ``BaseReportTab``); the tabs
        widget itself stays a fixed size so a short tab never stretches.
        """
        tab_widget = tab_cls()
        tab_widget.setObjectName(f"reportsPage_{tab_key.replace(' ', '_')}")
        # Short tabs (financial/audit) must not expand their widgets to fill the
        # viewport; the trailing stretch keeps them at their natural size.
        tab_widget.content_layout.addStretch(1)
        self.tabs.addTab(tab_widget, tr(tab_key))
        self.report_tabs.append(tab_widget)

    # ----------------------------------------- history panel ---------------------------------------- #

    def _setup_history_panel(self):
        """Builds the right-side Report History panel (search + grouped tree)."""
        self.history_panel = QFrame()
        self.history_panel.setProperty("class", "reports-history-panel")
        self.history_panel.setMinimumWidth(250)
        self.history_panel.setMaximumWidth(360)

        lay = QVBoxLayout(self.history_panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        head.setProperty("class", "reports-history-header")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 8, 10)
        hl.setSpacing(6)
        self.history_title = QLabel(tr("Report History"))
        self.history_title.setProperty("class", "reports-history-title")
        hl.addWidget(self.history_title)
        hl.addStretch()
        self.history_count_label = QLabel("0")
        self.history_count_label.setProperty("class", "reports-history-count")
        hl.addWidget(self.history_count_label)
        self.history_collapse_btn = QPushButton("\u00bb")
        self.history_collapse_btn.setProperty("class", "reports-history-collapse")
        self.history_collapse_btn.setCursor(Qt.PointingHandCursor)
        self.history_collapse_btn.setToolTip(tr("Hide"))
        self.history_collapse_btn.clicked.connect(lambda: self._toggle_history_panel(False))
        hl.addWidget(self.history_collapse_btn)
        lay.addWidget(head)

        search_wrap = QWidget()
        swl = QHBoxLayout(search_wrap)
        swl.setContentsMargins(10, 4, 10, 6)
        self.history_search = QLineEdit()
        self.history_search.setProperty("class", "reports-history-search")
        self.history_search.setPlaceholderText(tr("Search reports…"))
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self._refresh_history_panel)
        swl.addWidget(self.history_search)
        lay.addWidget(search_wrap)

        self.history_tree = QTreeWidget()
        self.history_tree.setProperty("class", "reports-history-tree")
        self.history_tree.setHeaderHidden(True)
        self.history_tree.setColumnCount(1)
        self.history_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.history_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_tree.setUniformRowHeights(True)
        self.history_tree.itemSelectionChanged.connect(self._on_history_selection_changed)
        self.history_tree.itemDoubleClicked.connect(
            lambda item, _col: self._open_history_item(item)
        )
        lay.addWidget(self.history_tree, 1)

        actions = QWidget()
        actions.setProperty("class", "reports-history-actions")
        al = QHBoxLayout(actions)
        al.setContentsMargins(10, 8, 10, 10)
        al.setSpacing(6)
        self.history_open_btn = QPushButton(tr("Open"))
        self.history_compare_btn = QPushButton(tr("Compare"))
        self.history_export_btn = QPushButton(tr("Export CSV"))
        self.history_delete_btn = QPushButton(tr("Delete"))
        pairs = (
            (self.history_open_btn, self._open_selected_history),
            (self.history_compare_btn, self._compare_history_items),
            (self.history_export_btn, self._export_history_item),
            (self.history_delete_btn, self._delete_history_item),
        )
        for btn, slot in pairs:
            btn.setProperty("class", "reports-history-action")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            al.addWidget(btn)
        lay.addWidget(actions)

    def _toggle_history_panel(self, visible):
        """Shows/hides the history panel and keeps the header toggle in sync."""
        self.history_panel.setVisible(visible)
        if hasattr(self, "history_toggle_btn") and self.history_toggle_btn.isChecked() != visible:
            self.history_toggle_btn.blockSignals(True)
            self.history_toggle_btn.setChecked(visible)
            self.history_toggle_btn.blockSignals(False)

    def _history_child_items(self):
        """Yields every leaf (saved-report) item in the history tree."""
        for i in range(self.history_tree.topLevelItemCount()):
            parent = self.history_tree.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent.child(j)

    def _selected_history_ids(self):
        """Returns the set of archive ids currently selected in the history tree."""
        if not hasattr(self, "history_tree"):
            return set()
        ids = set()
        for item in self.history_tree.selectedItems():
            value = item.data(0, Qt.UserRole)
            if value is not None:
                ids.add(value)
        return ids

    def _refresh_history_panel(self):
        """Rebuilds the history tree from saved snapshots, grouped by saved day."""
        if not hasattr(self, "history_tree"):
            return
        term = self.history_search.text() if hasattr(self, "history_search") else ""
        rows = report_archive_repo.search_archives(term, limit=300)
        selected = self._selected_history_ids()

        self.history_tree.blockSignals(True)
        self.history_tree.clear()

        groups = {}
        for row in rows:
            day = (row.get("generated_at") or "")[:10]
            groups.setdefault(day, []).append(row)

        for day in sorted(groups.keys(), reverse=True):
            parent = QTreeWidgetItem([self._history_group_label(day)])
            parent.setFlags(Qt.ItemIsEnabled)
            font = QFont()
            font.setBold(True)
            parent.setFont(0, font)
            self.history_tree.addTopLevelItem(parent)
            for row in groups[day]:
                label = "{} · {}".format(
                    tr(row.get("report_kind", "")),
                    _window_str(row.get("period_start", ""), row.get("period_end", "")) or "—",
                )
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.UserRole, row.get("archive_id"))
                child.setToolTip(0, "{} {} · {}".format(
                    tr("Saved"), row.get("generated_at", "") or "", row.get("generated_by", "") or ""
                ))
                parent.addChild(child)
            parent.setExpanded(True)

        if not rows:
            empty = QTreeWidgetItem([
                tr("No reports match your search.") if term else tr("No saved reports yet.")
            ])
            empty.setFlags(Qt.ItemIsEnabled)
            self.history_tree.addTopLevelItem(empty)

        self.history_tree.blockSignals(False)
        self.history_count_label.setText(str(len(rows)))
        self._reselect_history(selected)

    def _history_group_label(self, day_str):
        """Friendly label for a history date group ('Today' or the ISO day)."""
        if day_str == QDate.currentDate().toString("yyyy-MM-dd"):
            return tr("Today")
        return day_str

    def _reselect_history(self, ids):
        """Re-selects leaf items by archive id (selection survives a rebuild)."""
        ids = set(ids or [])
        if ids:
            self.history_tree.blockSignals(True)
            for child in self._history_child_items():
                if child.data(0, Qt.UserRole) in ids:
                    child.setSelected(True)
            self.history_tree.blockSignals(False)
        self._on_history_selection_changed()

    def _on_history_selection_changed(self):
        """Enables history actions according to the current selection."""
        if not hasattr(self, "history_open_btn"):
            return
        count = len(self._selected_history_ids())
        self.history_open_btn.setEnabled(count == 1)
        self.history_export_btn.setEnabled(count == 1)
        self.history_delete_btn.setEnabled(count >= 1)
        self.history_compare_btn.setEnabled(count == 2)

    def _open_history_item(self, item):
        """Opens a saved report when its leaf row is double-clicked."""
        archive_id = item.data(0, Qt.UserRole)
        if archive_id is not None:
            self._open_archive_by_id(archive_id)

    def _open_selected_history(self):
        """Opens the single selected saved report."""
        ids = self._selected_history_ids()
        if len(ids) == 1:
            self._open_archive_by_id(next(iter(ids)))

    def _open_archive_by_id(self, archive_id):
        """Loads a snapshot by id and shows it in its owning tab."""
        row = report_archive_repo.get_archive(archive_id)
        if row:
            self._open_archive(row)

    def _compare_history_items(self):
        """Opens a side-by-side comparison of the two selected saved reports."""
        ids = sorted(self._selected_history_ids())
        if len(ids) != 2:
            QMessageBox.information(self, tr("Compare Reports"), tr("Select two reports to compare."))
            return
        snapshots = [report_archive_repo.get_archive(i) for i in ids]
        snapshots = [s for s in snapshots if s]
        if len(snapshots) == 2:
            CompareReportsDialog(snapshots, self).exec_()

    def _export_history_item(self):
        """Exports the selected saved snapshot's KPIs to a CSV file."""
        ids = self._selected_history_ids()
        if len(ids) != 1:
            return
        row = report_archive_repo.get_archive(next(iter(ids)))
        if not row:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export CSV"), "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            kpis = (row.get("data", {}) or {}).get("kpis", {}) or {}
            with open(path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([tr("Metric"), tr("Value")])
                for label_key, key in _SNAPSHOT_KPI_EXPORT:
                    writer.writerow([tr(label_key), kpis.get(key, "")])
            QMessageBox.information(self, tr("Export Successful"), tr("Report successfully exported to CSV."))
        except Exception as e:
            QMessageBox.critical(self, tr("Export Error"), str(e))

    def _delete_history_item(self):
        """Deletes the selected saved report(s) after a single confirmation."""
        ids = sorted(self._selected_history_ids())
        if not ids:
            return
        reply = QMessageBox.question(
            self,
            tr("Delete"),
            tr("Delete this saved report?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for archive_id in ids:
            report_archive_repo.delete_archive(archive_id)
        if self._viewing_archive in ids:
            self._clear_archive_view()
            self.refresh_data()
        else:
            self._refresh_history_panel()
            self._refresh_calendar()

    # ----------------------------------------- range / calendar ---------------------------------------- #

    def _granularity_range(self):
        """Returns (start, end) 'YYYY-MM-DD' for the selected date + granularity.

        The clicked calendar day is the **end** of the window: Day = that day;
        Week = the 6 preceding days; Month = one month back; Quarter = three months
        back; Year = one year back. Custom returns the explicit two-click / preset
        window (empty when not yet chosen).
        """
        if self._granularity == "Custom":
            return self._custom_range if self._custom_range else (None, None)
        d = self._selected_date
        if self._granularity == "Day":
            return _fmt(d), _fmt(d)
        if self._granularity == "Week":
            return _fmt(d.addDays(-6)), _fmt(d)
        if self._granularity == "Month":
            return _fmt(d.addMonths(-1)), _fmt(d)
        if self._granularity == "Quarter":
            return _fmt(d.addMonths(-3)), _fmt(d)
        return _fmt(d.addYears(-1)), _fmt(d)

    def _current_range(self):
        """Alias used by refresh/snapshot paths — returns the active date window."""
        return self._granularity_range()

    def _period_title(self):
        """Returns a friendly title for the active window (preset-aware)."""
        start, end = self._current_range()
        if not start:
            return tr("Custom Range")
        today = QDate.currentDate()
        named = [
            ("Today", (today, today)),
            ("This Week", _week_bounds(today)),
            ("Last Week", _last_week_bounds(today)),
            ("This Month", _month_bounds(today)),
            ("Last Month", _last_month_bounds(today)),
            ("This Quarter", _quarter_bounds(today)),
            ("Year to Date", (QDate(today.year(), 1, 1), today)),
        ]
        for label_key, (s, e) in named:
            if (start, end) == (_fmt(s), _fmt(e)):
                return tr(label_key)
        return {
            "Day": tr("Daily Report"),
            "Week": tr("Weekly Report"),
            "Month": tr("Monthly Report"),
            "Quarter": tr("Quarterly Report"),
            "Year": tr("Yearly Report"),
        }.get(self._granularity, tr("Custom Range"))

    def _refresh_range_label(self):
        """Refreshes the header window title + values from the active range."""
        if not hasattr(self, "report_range_label"):
            return
        self.report_granularity_label.setText(self._period_title())
        start, end = self._current_range()
        if not start:
            self.report_range_label.setText(tr("Pick two dates to set a range"))
            return
        self.report_range_label.setText(start if start == end else f"{start} — {end}")

    def _refresh_summary_line(self):
        """Refreshes the compact live-data summary pill below the range label."""
        if self._viewing_archive is not None:
            self.summary_line_label.hide()
            return
        start, end = self._current_range()
        if not start:
            self.summary_line_label.hide()
            return
        try:
            visits = analytics_repo.get_total_visits_range(start, end)
            revenue = analytics_repo.get_total_revenue_range(start, end)
            costs = analytics_repo.get_total_costs_range(start, end)
        except Exception:
            self.summary_line_label.hide()
            return
        self.summary_line_label.setText(tr(
            "{visits} visits • {revenue} revenue • {profit} net profit"
        ).format(
            visits=int(visits),
            revenue=f"${revenue:,.2f}",
            profit=f"${revenue - costs:,.2f}",
        ))
        self.summary_line_label.show()

    def _apply_preset(self, resolver):
        """Applies a quick preset as a Custom window and refreshes the view."""
        start, end = _preset_window(resolver)
        self._granularity = "Custom"
        self._custom_range = (_fmt(start), _fmt(end))
        self._custom_pending = None
        for btn, g_name in self.granularity_buttons:
            btn.setChecked(g_name == "Custom")
        self._clear_archive_view()
        self._refresh_range_label()
        self._hide_calendar_popup()
        self.refresh_data()

    def _nudge(self, direction):
        """Steps the active window back/forward by one period."""
        if self._granularity == "Custom":
            start, end = self._custom_range or (None, None)
            if not start:
                return
            s = QDate.fromString(start, "yyyy-MM-dd")
            e = QDate.fromString(end, "yyyy-MM-dd")
            if not s.isValid() or not e.isValid():
                return
            shift = (s.daysTo(e) + 1) * direction
            self._custom_range = (_fmt(s.addDays(shift)), _fmt(e.addDays(shift)))
        else:
            d = self._selected_date
            if self._granularity == "Day":
                d = d.addDays(direction)
            elif self._granularity == "Week":
                d = d.addDays(7 * direction)
            elif self._granularity == "Month":
                d = d.addMonths(direction)
            elif self._granularity == "Quarter":
                d = d.addMonths(3 * direction)
            elif self._granularity == "Year":
                d = d.addYears(direction)
            self._selected_date = d
            self.calendar.setSelectedDate(d)
        self._clear_archive_view()
        self._refresh_range_label()
        self.refresh_data()

    def _on_granularity_changed(self, granularity):
        """Switches between Day / Week / Month / Quarter / Year / Custom reports."""
        self._granularity = granularity
        for btn, g_name in self.granularity_buttons:
            btn.setChecked(g_name == granularity)
        self._clear_archive_view()
        if granularity == "Custom":
            # Enter two-click range mode; the calendar picks start + end.
            self._custom_range = None
            self._custom_pending = None
            self.report_granularity_label.setText(tr("Custom Range"))
            self.report_range_label.setText(tr("Pick two dates to set a range"))
            self._refresh_summary_line()
            self._refresh_calendar()
            self._show_calendar_popup()
            return
        # Standard granularities: clear any custom window and use the selected day.
        self._custom_range = None
        self._custom_pending = None
        self._hide_calendar_popup()
        self._refresh_range_label()
        self.refresh_data()

    def _on_calendar_clicked(self, date):
        """Clicking a calendar day navigates the period (never opens an archive)."""
        self._clear_archive_view()
        if self._granularity == "Custom":
            self._handle_custom_click(date)
            if self._custom_range:
                self._hide_calendar_popup()
            else:
                self._sync_calendar_hint()
        else:
            self._selected_date = date
            self._refresh_range_label()
            self._hide_calendar_popup()
            self.refresh_data()

    def _handle_custom_click(self, date):
        """Two-click range selection: first click = start, second click = end."""
        day = _fmt(date)
        if self._custom_pending is None:
            self._custom_pending = day
            self._custom_range = None
            self.calendar.setSelectedDate(date)
            self.report_granularity_label.setText(tr("Custom Range"))
            self.report_range_label.setText(tr("Select end date…"))
            self._refresh_summary_line()
            self._refresh_calendar()
            return
        start, end = self._custom_pending, day
        if end < start:
            start, end = end, start
        self._custom_pending = None
        self._custom_range = (start, end)
        self._refresh_range_label()
        self.refresh_data()

    def _clear_archive_view(self):
        """Leaves any archived snapshot and returns the page to live-data mode."""
        self._viewing_archive = None
        self.archive_banner_frame.hide()
        for tab in self.report_tabs:
            tab.viewing_archive = False

    def _refresh_calendar(self):
        """Marks days that have saved reports and tints the active custom span."""
        if not hasattr(self, "calendar"):
            return
        for d in list(self.calendar.dateTextFormat().keys()):
            self.calendar.setDateTextFormat(d, QTextCharFormat())

        palette = get_active_palette()
        base = QColor(palette.get("brand_500", "#4A90E2"))

        # Light tint across the two-click custom range so the whole span is visible.
        if self._custom_range:
            span = QColor(base)
            span.setAlpha(45)
            s = QDate.fromString(self._custom_range[0], "yyyy-MM-dd")
            e = QDate.fromString(self._custom_range[1], "yyyy-MM-dd")
            if s.isValid() and e.isValid():
                cur = s
                while cur <= e:
                    span_fmt = QTextCharFormat()
                    span_fmt.setBackground(QBrush(span))
                    self.calendar.setDateTextFormat(cur, span_fmt)
                    cur = cur.addDays(1)

        # Days with saved reports: subtle brand-coloured, bold day number.
        for day, _count in report_archive_repo.list_archive_days(limit=400):
            date = QDate.fromString(day, "yyyy-MM-dd")
            if not date.isValid():
                continue
            fmt = QTextCharFormat()
            fmt.setForeground(QBrush(base))
            fmt.setFontWeight(QFont.Bold)
            self.calendar.setDateTextFormat(date, fmt)

        # Keep today clearly marked (filled), painted last so it wins.
        today_fmt = QTextCharFormat()
        today_fmt.setBackground(QBrush(base))
        today_fmt.setForeground(QBrush(QColor(255, 255, 255)))
        today_fmt.setFontWeight(QFont.Bold)
        self.calendar.setDateTextFormat(QDate.currentDate(), today_fmt)

    # ----------------------------------------- archives ---------------------------------------- #

    def _maybe_daily_checkpoint(self):
        """Auto-saves a 'Day' snapshot per report category, once per calendar day.

        This is the safety net behind explicit saves: reports are always computed
        live, but a checkpoint freezes the just-completed day's numbers so the
        Report History always has a per-day record even when nobody presses Save
        Report. It captures *yesterday* (a complete day) and is a cheap no-op
        after the first run of each day (one settings read).
        """
        if self._current_user is None or not can(self._current_user, "view_reports"):
            return
        target = _fmt(QDate.currentDate().addDays(-1))
        if SettingsManager.get("last_report_checkpoint") == target:
            return

        ok = True
        for kind in range(AUDIT_TAB_INDEX):
            try:
                data = self._build_snapshot_data(kind, target, target, period="Day")
                report_archive_repo.save_snapshot(
                    REPORT_KIND_KEYS[kind], "Day", data, target, target, self._username()
                )
            except Exception:
                ok = False
                logger.exception("Daily report checkpoint failed for %s", REPORT_KIND_KEYS[kind])

        if not ok:
            return  # leave the marker unset so the next refresh retries
        SettingsManager.set("last_report_checkpoint", target)
        self._refresh_history_panel()
        self._refresh_calendar()

    def _save_current_report(self):
        """Saves the active tab's report as a new history snapshot."""
        if self._current_user is None or not can(self._current_user, "view_reports"):
            return
        kind = self.tabs.currentIndex()
        if kind == AUDIT_TAB_INDEX:
            QMessageBox.information(
                self, tr("Save Report"),
                tr("Audit log is live data and cannot be saved."),
            )
            return
        start, end = self._current_range()
        if not start:
            QMessageBox.information(self, tr("Save Report"), tr("Pick a period first."))
            return

        data = self._build_snapshot_data(kind, start, end)
        report_archive_repo.save_snapshot(
            REPORT_KIND_KEYS[kind], self._granularity, data, start, end, self._username()
        )
        self._refresh_history_panel()
        self._refresh_calendar()
        QMessageBox.information(
            self, tr("Save Report"), tr("Report saved to history.")
        )

    def _build_snapshot_data(self, kind, start, end, period=None):
        """Gathers the KPI + table payload for the active report kind."""
        revenues = analytics_repo.get_total_revenue_range(start, end)
        visits = analytics_repo.get_total_visits_range(start, end)
        costs = analytics_repo.get_total_costs_range(start, end)
        avg = (revenues / visits) if visits else 0.0
        top_rows = analytics_repo.get_top_clients_range(start, end, limit=10)
        return {
            "meta": {"category": REPORT_KIND_KEYS[kind], "period": period or self._granularity,
                     "start": start, "end": end},
            "kpis": {
                "visits": visits,
                "revenue": revenues,
                "supplies_used": analytics_repo.get_total_supplies_used_range(start, end),
                "avg_revenue": avg,
                "low_stock": analytics_repo.get_low_stock_supplies(),
                "costs": costs,
                "net_profit": revenues - costs,
                "busiest_client": top_rows[0][1] if top_rows else "",
            },
            "tables": {
                "visits_by_doctor": analytics_repo.get_visits_by_doctor_range(start, end),
                "revenue_by_category": [
                    [cat, round(float(amount), 2)]
                    for cat, amount in analytics_repo.get_revenue_by_category_range(start, end)
                ],
                "supply_usage": analytics_repo.get_supply_usage_range(
                    start, end, limit=ANALYTICS_LIMITS["supply_usage_count"]),
                "clinical": analytics_repo.get_clinical_activity_summary(),
                "top_clients": [[r[1], r[2], round(float(r[3]), 2)] for r in top_rows],
            },
        }

    def _username(self):
        """Returns the current username ('' when not logged in)."""
        user = self._current_user
        return user.get("username", "") if isinstance(user, dict) else ""

    def _open_archive(self, archive):
        """Restores a saved report snapshot into its owning category tab."""
        self._viewing_archive = archive["archive_id"]
        data = archive.get("data", {}) or {}

        kind_key = archive.get("report_kind", "")
        period = archive.get("period_type", "")
        generated = archive.get("generated_at", "") or ""
        generated_by = archive.get("generated_by", "") or ""
        window = _window_str(archive.get("period_start", ""), archive.get("period_end", ""))

        banner = "{} — {} · {}".format(escape(tr("Viewing archived report")),
                                       escape(tr(kind_key)), escape(tr(period)))
        if window:
            banner += f" · {escape(window)}"
        if generated:
            banner += f" · {escape(str(generated)[:16])}"
        if generated_by:
            banner += f" · {escape(generated_by)}"
        self.archive_banner_label.setText(banner)
        self.archive_banner_frame.show()
        self.summary_line_label.hide()

        target_index = REPORT_KIND_KEYS.index(kind_key) if kind_key in REPORT_KIND_KEYS else 0
        target_index = max(0, min(target_index, self.tabs.count() - 1))
        if self.tabs.currentIndex() != target_index:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(target_index)
            self.tabs.blockSignals(False)

        for tab in self.report_tabs:
            tab.viewing_archive = True
        self.report_tabs[target_index].load_archive(data)
        self._refresh_calendar()

    def _exit_archive_view(self):
        """Returns the page to live reporting data."""
        self._clear_archive_view()
        # Custom mode with no completed selection has no live window to show;
        # fall back to Day so "Back to Live Data" always refreshes.
        if self._granularity == "Custom" and not self._custom_range:
            self._granularity = "Day"
            for btn, g_name in self.granularity_buttons:
                btn.setChecked(g_name == "Day")
            self._refresh_range_label()
        self.refresh_data()

    def _setup_archive_banner(self):
        """Banner shown while an archived report is being reviewed."""
        self.archive_banner_frame = QFrame()
        self.archive_banner_frame.setProperty("class", "status-card")
        banner_layout = QHBoxLayout(self.archive_banner_frame)
        banner_layout.setContentsMargins(14, 8, 14, 8)
        banner_layout.setSpacing(10)

        self.archive_banner_label = QLabel()
        self.archive_banner_label.setProperty("class", "status-title")
        banner_layout.addWidget(self.archive_banner_label, stretch=1)

        self.back_to_live_btn = QPushButton(tr("Back to Live Data"))
        self.back_to_live_btn.setCursor(Qt.PointingHandCursor)
        self.back_to_live_btn.clicked.connect(self._exit_archive_view)
        banner_layout.addWidget(self.back_to_live_btn)
        self.archive_banner_frame.hide()

    # ----------------------------------------- actions ---------------------------------------- #

    def set_current_user(self, user):
        """Applies report access to the page controls."""
        self._current_user = user
        allowed = can(user, "view_reports")
        self.tabs.setEnabled(allowed)
        self.export_excel_btn.setEnabled(allowed)
        self.export_csv_btn.setEnabled(allowed)
        self.print_pdf_btn.setEnabled(allowed)
        self.refresh_btn.setEnabled(allowed)
        self.save_report_btn.setEnabled(allowed)
        self.history_toggle_btn.setEnabled(allowed)
        self.history_panel.setEnabled(allowed)

    # ----------------------------------------- refresh ---------------------------------------- #

    def refresh_data(self):
        """Refreshes the active report tab, history panel and calendar marks."""
        if self._viewing_archive is not None:
            return
        invalidate_analytics_cache()
        self._maybe_daily_checkpoint()
        self._refresh_history_panel()
        self._refresh_calendar()

        start, end = self._granularity_range()
        if not start:
            return  # Custom mode without a completed two-click selection.
        for tab in self.report_tabs:
            tab.update_range(start, end)
        self.current_tab().refresh_data()
        self._refresh_summary_line()

    def _refresh_audit_report(self):
        """Refreshes the audit table for the Audit Log report view."""
        if self._viewing_archive is not None:
            return
        self.audit_tab.refresh_report()

    # ----------------------------------------- exports / print ---------------------------------------- #

    def _active_value(self, attr):
        """Reads a KPI label's text from the active tab ('' when not present)."""
        tab = self.current_tab()
        widget = getattr(tab, attr, None)
        return widget.text() if widget is not None else ""

    def _export_current_report_csv(self):
        """Exports data of the current report kind to a CSV file."""
        kind = self.tabs.currentIndex()
        path, _ = QFileDialog.getSaveFileName(self, tr("Save CSV"), "", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if kind == 1:  # Financial
                    writer.writerow([tr("ID"), tr("Date"), tr("Item"), tr("Category"),
                                     tr("Quantity"), tr("Total Price"), tr("Type")])
                    for r in sales_repo.get_receipt_items():
                        writer.writerow([r.get("id"), r.get("receipt_date"), r.get("item_name"), r.get("item_type"), r.get("quantity"), r.get("total_price"), r.get("receipt_kind")])
                elif kind == 2:  # Patient
                    writer.writerow([tr("Client ID"), tr("Owner Name"), tr("Phone Number")])
                    for c in client_repo.get_clients():
                        writer.writerow([c.get("client_id"), c.get("owner_name"), c.get("phone_number")])
                elif kind == 3:  # Supply
                    writer.writerow([tr("ID"), tr("Item Name"), tr("Category"),
                                     tr("Sub-Category"), tr("Stock"), tr("Buy Price"),
                                     tr("Sell Price"), tr("Expiry Date")])
                    for s in supply_repo.search_supplies():
                        writer.writerow([s.get("supply_id"), s.get("item_name"), s.get("category"), s.get("sub_category"), s.get("current_stock"), s.get("buy_price"), s.get("sell_price"), s.get("expiry_date")])
                elif kind == 4:  # Audit
                    writer.writerow([tr("ID"), tr("User"), tr("Table"), tr("Record ID"),
                                     tr("Changed At"), tr("Details")])
                    for a in audit_repo.get_recent_changes_with_details(limit=200):
                        writer.writerow([a.get("change_header_id"), a.get("username"), a.get("table_name"), a.get("record_id"), a.get("changed_at"), audit_repo.format_audit_message(a)])
                else:  # Overview
                    writer.writerow([tr("Metric"), tr("Value")])
                    writer.writerow([tr("Total Visits"), self._active_value("total_visits_value")])
                    writer.writerow([tr("Total Revenue"), self._active_value("total_revenue_value")])
                    writer.writerow([tr("Supplies Used"), self._active_value("total_supplies_value")])
                    writer.writerow([tr("Avg Revenue / Visit"), self._active_value("avg_revenue_value")])
                    writer.writerow([tr("Total Costs"), self._active_value("total_costs_value")])
                    writer.writerow([tr("Net Profit"), self._active_value("net_profit_value")])

            QMessageBox.information(self, tr("Export Successful"), tr("Report successfully exported to CSV."))
        except Exception as e:
            QMessageBox.critical(self, tr("Export Error"), str(e))

    def _section_from_table(self, title, table):
        """Builds an exportable section dict from a QTableWidget."""
        headers = []
        for c in range(table.columnCount()):
            hitem = table.horizontalHeaderItem(c)
            headers.append(hitem.text() if hitem else "")
        rows = []
        for r in range(table.rowCount()):
            rows.append([
                (table.item(r, c).text() if table.item(r, c) else "")
                for c in range(table.columnCount())
            ])
        return {"title": title, "headers": headers, "rows": rows, "summary": []}

    def _build_excel_sections(self):
        """Gathers the current report into reusable Excel/exportable sections.

        Each report tab owns exclusive content, so exports only include the
        sections belonging to the currently active tab.
        """
        kind = self.tabs.currentIndex()
        sections = []

        if kind == 0:  # Overview — business overview KPIs (trends are charts).
            sections.append({
                "title": tr("Business Overview"),
                "headers": [tr("Metric"), tr("Value")],
                "rows": [
                    [tr("Total Visits"), self._active_value("total_visits_value")],
                    [tr("Total Revenue"), self._active_value("total_revenue_value")],
                    [tr("Supplies Used"), self._active_value("total_supplies_value")],
                    [tr("Avg Revenue / Visit"), self._active_value("avg_revenue_value")],
                    [tr("Total Costs"), self._active_value("total_costs_value")],
                    [tr("Net Profit"), self._active_value("net_profit_value")],
                ],
                "summary": [],
            })
            if hasattr(self.overview_tab, "top_clients_table"):
                sections.append(self._section_from_table(tr("Top Clients"), self.overview_tab.top_clients_table))
        elif kind == 1:  # Financial — revenue by category.
            sections.append(self._section_from_table(tr("Revenue by Category"), self.financial_tab.revenue_by_category_table))
        elif kind == 2:  # Patient — doctor performance, diagnoses, clinical activity.
            sections.append(self._section_from_table(tr("Visits by Doctor"), self.patient_tab.visits_by_doctor_table))
            sections.append(self._section_from_table(tr("Monthly Diagnoses"), self.patient_tab.diagnosis_table))
            sections.append(self._section_from_table(tr("Clinical Activity By Doctor"), self.clinical_table))
        elif kind == 3:  # Supply — inventory usage + insights.
            low_stock = getattr(self.supply_tab, "low_stock_value", None)
            sections.append({
                "title": tr("Operational Insights"),
                "headers": [tr("Metric"), tr("Value")],
                "rows": [
                    [
                        tr("Low Stock Supplies"),
                        low_stock.text() if low_stock is not None else str(analytics_repo.get_low_stock_supplies()),
                    ],
                ],
                "summary": [],
            })
            sections.append(self._section_from_table(tr("Supply Usage"), self.supply_tab.supply_usage_table))
            sections.append(self._section_from_table(tr("Expiring Soon (30d)"), self.supply_tab.expiring_table))
            sections.append(self._section_from_table(tr("Top Selling Items"), self.supply_tab.top_selling_table))
        elif kind == 4:  # Audit — change history.
            sections.append(self._section_from_table(tr("Audit Log"), self.audit_table))
        return sections

    def _export_current_report_excel(self):
        """Exports the current report to a styled .xlsx workbook via openpyxl."""
        try:
            from src.utils.excel_export import HAS_OPENPYXL, write_report_workbook
        except ImportError:
            HAS_OPENPYXL = False

        if not HAS_OPENPYXL:
            QMessageBox.critical(self, tr("Export Error"), tr("Excel export requires the openpyxl package."))
            return

        kind = self.tabs.currentIndex()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export Excel"), "", "Excel Workbooks (*.xlsx)"
        )
        if not path:
            return

        try:
            kind_key = REPORT_KIND_KEYS[kind] if 0 <= kind < len(REPORT_KIND_KEYS) else self.tabs.tabText(kind)
            stamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm")
            subtitle = f"{tr(kind_key)} — {self.report_range_label.text()} — {tr('Generated: {time}').format(time=stamp)}"
            ok = write_report_workbook(path, tr(kind_key), subtitle, self._build_excel_sections())
            if ok:
                QMessageBox.information(self, tr("Export Successful"), tr("Report successfully exported to Excel."))
            else:
                QMessageBox.critical(self, tr("Export Error"), tr("Failed to export the report to Excel."))
        except Exception as e:
            QMessageBox.critical(self, tr("Export Error"), str(e))

    def _html_table(self, title, headers, table):
        """Turns a QTableWidget into an HTML table block for printing."""
        head = "".join(f"<th>{escape(tr(h))}</th>" for h in headers)
        rows = []
        for r in range(table.rowCount()):
            cells = []
            for c in range(table.columnCount()):
                item = table.item(r, c)
                cells.append(f"<td>{escape(item.text() if item else '')}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f"<h3>{escape(title)}</h3>"
            f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _print_current_report(self):
        """Prints or renders the current report to PDF using QPrinter."""
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QPrintDialog.Accepted:
            return

        kind = self.tabs.currentIndex()
        if 0 <= kind < len(REPORT_KIND_KEYS):
            title = tr(REPORT_KIND_KEYS[kind])
        else:
            title = self.tabs.tabText(kind)
        generated = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm")

        parts = [
            "<html><head><style>"
            "body { font-family: 'Segoe UI', sans-serif; }"
            "h1 { color: #2C3E50; }"
            "table { border-collapse: collapse; width: 100%; }"
            "th, td { border: 1px solid #DCDDE1; padding: 6px; text-align: left; }"
            "th { background-color: #EFEFEF; }"
            "</style></head><body>",
            f"<h1>{escape(title)}</h1>",
            f"<p><em>{escape(tr('Generated: {time}').format(time=generated))}</em></p>",
            "<hr/>",
        ]

        if kind == 0:  # Overview — KPIs + top clients.
            parts.append(f"<p><b>{escape(tr('Total Visits'))}:</b> {self._active_value('total_visits_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Total Revenue'))}:</b> {self._active_value('total_revenue_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Supplies Used'))}:</b> {self._active_value('total_supplies_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Avg Revenue / Visit'))}:</b> {self._active_value('avg_revenue_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Total Costs'))}:</b> {self._active_value('total_costs_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Net Profit'))}:</b> {self._active_value('net_profit_value')}</p>")
            if hasattr(self.overview_tab, "top_clients_table"):
                parts.append(self._html_table(
                    tr("Top Clients"),
                    [tr("Client"), tr("Visits"), tr("Revenue")],
                    self.overview_tab.top_clients_table,
                ))
        elif kind == 1:  # Financial — revenue by category.
            parts.append(self._html_table(
                tr("Revenue by Category"),
                [tr("Category"), tr("Revenue")],
                self.financial_tab.revenue_by_category_table,
            ))
        elif kind == 2:  # Patient — doctor performance, diagnoses, clinical activity.
            parts.append(self._html_table(
                tr("Visits by Doctor"),
                [tr("Doctor"), tr("Visits")],
                self.patient_tab.visits_by_doctor_table,
            ))
            parts.append(f"<p><b>{escape(tr('Monthly Diagnoses'))}:</b> {self.patient_tab.diagnosis_table.rowCount()}</p>")
            parts.append(self._html_table(
                tr("Clinical Activity By Doctor"),
                [tr("Doctor"), tr("Visits"), tr("Follow-ups"), tr("Unassigned Visits")],
                self.clinical_table,
            ))
        elif kind == 3:  # Supply — inventory usage + insights.
            parts.append(f"<p><b>{escape(tr('Low Stock Supplies'))}:</b> {self._active_value('low_stock_value')}</p>")
            parts.append(f"<p><b>{escape(tr('Expiring Soon (30d)'))}:</b> {self.supply_tab.expiring_table.rowCount()}</p>")
            parts.append(self._html_table(
                tr("Top Selling Items"),
                [tr("Item"), tr("Category"), tr("Sold")],
                self.supply_tab.top_selling_table,
            ))
            parts.append(self._html_table(
                tr("Supply Usage"),
                [tr("Item"), tr("Category"), tr("Quantity")],
                self.supply_tab.supply_usage_table,
            ))
        else:  # Audit — change history.
            parts.append(f"<p><b>{escape(tr('Audit Entries'))}:</b> {self.audit_table.rowCount()}</p>")
            parts.append(self._html_table(
                tr("Audit Log"),
                [tr("ID"), tr("User"), tr("Table"), tr("Record ID"), tr("Changed At")],
                self.audit_table,
            ))

        parts.append("</body></html>")

        doc = QTextDocument()
        doc.setHtml("".join(parts))
        doc.print_(printer)

    # ----------------------------------------- theme / translation ---------------------------------------- #

    def update_chart_theme(self, palette=None):
        """Rebuilds charts on all report tabs after a theme toggle."""
        for tab in self.report_tabs:
            tab.update_chart_theme(palette)
        self._refresh_calendar()

    def _on_theme_changed(self, palette=None):
        """Theme-only refresh: rebuild charts and calendar tints without re-running queries."""
        active = self.current_tab()
        if active is not None:
            active.update_chart_theme(palette)
        self._refresh_calendar()

    def retranslate_ui(self):
        """Updates all static text on the reports when the language changes."""
        self.export_excel_btn.setText(tr("Export Excel"))
        self.export_csv_btn.setText(tr("Export CSV"))
        self.print_pdf_btn.setText(tr("Print / PDF"))
        self.page_title_label.setText(tr("Reports & Analytics"))
        subtitle = tr(
            "Analyze clinic performance, finances, inventory and activity across the selected period."
        )
        self.page_subtitle_label.setText(subtitle)
        self.page_title_label.setToolTip(subtitle)
        self.period_trigger.setToolTip(tr("Select dates"))
        self.refresh_btn.setText(tr("Refresh"))
        self.save_report_btn.setText(tr("Save Report"))
        self.history_toggle_btn.setText(tr("Report History"))

        # History panel chrome.
        self.history_title.setText(tr("Report History"))
        self.history_search.setPlaceholderText(tr("Search reports…"))
        self.history_open_btn.setText(tr("Open"))
        self.history_compare_btn.setText(tr("Compare"))
        self.history_export_btn.setText(tr("Export CSV"))
        self.history_delete_btn.setText(tr("Delete"))

        # Period bar.
        for chip, label_key in self.preset_buttons:
            chip.setText(tr(label_key))
        for g_btn, g_name in self.granularity_buttons:
            g_btn.setText(tr(g_name))
        self.nudge_back_btn.setToolTip(tr("Previous period"))
        self.nudge_fwd_btn.setToolTip(tr("Next period"))
        self._sync_calendar_hint()
        self._refresh_range_label()

        self.back_to_live_btn.setText(tr("Back to Live Data"))

        # Re-label the report category tabs, preserving the current selection.
        for i, tab_key in enumerate(REPORT_KIND_KEYS):
            if i < self.tabs.count():
                self.tabs.setTabText(i, tr(tab_key))

        # Propagate to each report tab (also refreshes translated values).
        for tab in self.report_tabs:
            tab.viewing_archive = self._viewing_archive is not None
            tab.retranslate_ui()

        # Re-translate the history entries (kind + group labels).
        self._refresh_history_panel()

    def _on_tab_changed(self, index):
        """Refreshes the report data when the active category tab changes."""
        self.current_tab().scroll_to_top()
        self.refresh_data()

    def current_tab(self):
        """Returns the currently active report tab widget."""
        index = self.tabs.currentIndex()
        if 0 <= index < len(self.report_tabs):
            return self.report_tabs[index]
        return self.report_tabs[0]

    # ----------------------------------------- delegated test/compat access ---------------------------------------- #

    @property
    def audit_table(self):
        """Delegates to the Audit tab's table (kept for tests/compat)."""
        return self.audit_tab.audit_table

    @property
    def audit_empty_label(self):
        """Delegates to the Audit tab's empty-state label."""
        return self.audit_tab.audit_empty_label

    @property
    def clinical_table(self):
        """Delegates to the Patient tab's clinical summary table."""
        return self.patient_tab.clinical_table

    @property
    def clinical_empty_label(self):
        """Delegates to the Patient tab's clinical empty-state label."""
        return self.patient_tab.clinical_empty_label
