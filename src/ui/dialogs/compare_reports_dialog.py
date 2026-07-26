"""
Side-by-side comparison of two saved report snapshots.

Opened from the Reports page's "Report History" panel: the decision-maker picks
two saved reports and sees their headline KPIs against each other, with the delta
(B − A) highlighted so movement is obvious at a glance.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from src.ui.themes.color_palettes import get_active_palette
from src.utils.i18n import tr

# (i18n label key, kpis key, kind) — kind drives formatting and the delta rule.
_METRICS = [
    ("Total Visits", "visits", "int"),
    ("Total Revenue", "revenue", "money"),
    ("Supplies Used", "supplies_used", "int"),
    ("Avg Revenue / Visit", "avg_revenue", "money"),
    ("Total Costs", "costs", "money"),
    ("Net Profit", "net_profit", "money"),
    ("Low Stock Supplies", "low_stock", "int"),
    ("Busiest Client", "busiest_client", "text"),
]


def _format(value, kind):
    """Formats a KPI value for display according to its kind."""
    if kind == "text":
        return str(value) if value not in (None, "") else "—"
    if kind == "money":
        try:
            return f"${float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return "$0.00"
    try:
        return str(int(float(value or 0)))
    except (TypeError, ValueError):
        return "0"


def _period_label(row):
    """Builds a compact 'Kind · start — end' label for a snapshot column header."""
    kind = tr(row.get("report_kind", ""))
    start = row.get("period_start", "") or ""
    end = row.get("period_end", "") or ""
    if start and end and start != end:
        window = f"{start} — {end}"
    else:
        window = start or end
    return f"{kind}\n{window}" if window else kind


class CompareReportsDialog(QDialog):
    """Shows two saved snapshots' KPIs side by side with a delta column."""

    def __init__(self, snapshots, parent=None):
        """``snapshots`` is a list of exactly two archive dicts (with ``data``)."""
        super().__init__(parent)
        self._snapshots = list(snapshots)
        self.setWindowTitle(tr("Compare Reports"))
        self.setModal(True)
        self.resize(640, 460)
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        left, right = self._snapshots[0], self._snapshots[1]
        heading = QLabel(tr("Compare Reports"))
        heading.setProperty("class", "reports-page-title")
        root.addWidget(heading)

        subtitle = QLabel(f"{_period_label(left).replace(chr(10), ' ')}   vs   "
                          f"{_period_label(right).replace(chr(10), ' ')}")
        subtitle.setProperty("class", "reports-page-subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.table = QTableWidget(len(_METRICS), 4)
        self.table.setProperty("class", "reports-table")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels(
            [tr("Metric"), tr("Report A"), tr("Report B"), tr("Difference")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self._populate(left, right)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.setProperty("class", "secondary-action")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _populate(self, left, right):
        """Fills the table for the two snapshots (left = A, right = B)."""
        kpis_a = (left.get("data", {}) or {}).get("kpis", {}) or {}
        kpis_b = (right.get("data", {}) or {}).get("kpis", {}) or {}
        palette = get_active_palette()
        up = QColor(palette.get("state_success", "#2ECC71"))
        down = QColor(palette.get("state_danger", "#E74C3C"))

        for row, (label_key, key, kind) in enumerate(_METRICS):
            a_val = kpis_a.get(key)
            b_val = kpis_b.get(key)
            self.table.setItem(row, 0, QTableWidgetItem(tr(label_key)))
            self.table.setItem(row, 1, QTableWidgetItem(_format(a_val, kind)))
            self.table.setItem(row, 2, QTableWidgetItem(_format(b_val, kind)))

            diff_item = QTableWidgetItem(self._diff_text(a_val, b_val, kind))
            if kind != "text":
                delta = self._delta(a_val, b_val)
                if delta > 0:
                    diff_item.setForeground(up)
                elif delta < 0:
                    diff_item.setForeground(down)
            self.table.setItem(row, 3, diff_item)

    @staticmethod
    def _delta(a_val, b_val):
        """Returns B − A as a float (0.0 when either side is non-numeric)."""
        try:
            return float(b_val or 0) - float(a_val or 0)
        except (TypeError, ValueError):
            return 0.0

    def _diff_text(self, a_val, b_val, kind):
        """Renders the delta cell (money/int with sign; em-dash for text)."""
        if kind == "text":
            return "—"
        delta = self._delta(a_val, b_val)
        sign = "+" if delta > 0 else ("-" if delta < 0 else "")
        if kind == "money":
            return f"{sign}${abs(delta):,.2f}"
        return f"{sign}{int(round(abs(delta)))}"
