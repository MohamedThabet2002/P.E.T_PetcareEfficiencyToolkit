"""Tests for the CompareReportsDialog (side-by-side saved-report comparison)."""

from PyQt5.QtWidgets import QDialog

from src.ui.dialogs.compare_reports_dialog import CompareReportsDialog


def _snap(kind, start, end, **kpis):
    base = {
        "visits": 4,
        "revenue": 200.0,
        "supplies_used": 3,
        "avg_revenue": 50.0,
        "costs": 80.0,
        "net_profit": 120.0,
        "low_stock": 1,
        "busiest_client": "Alice",
    }
    base.update(kpis)
    return {
        "archive_id": 1,
        "report_kind": kind,
        "period_start": start,
        "period_end": end,
        "data": {"kpis": base},
    }


def test_builds_metric_rows_for_both_reports(qapp):
    a = _snap("Overview Analytics", "2026-09-01", "2026-09-05")
    b = _snap("Overview Analytics", "2026-10-01", "2026-10-05", visits=6, revenue=150.0)

    dialog = CompareReportsDialog([a, b])
    assert dialog.windowTitle() == "Compare Reports"
    table = dialog.table

    # Ordered metrics: Total Visits is the first row.
    assert table.item(0, 1).text() == "4"
    assert table.item(0, 2).text() == "6"
    assert table.item(0, 3).text() == "+2"

    # Total Revenue is money formatted, delta signed.
    assert table.item(1, 1).text() == "$200.00"
    assert table.item(1, 2).text() == "$150.00"
    assert table.item(1, 3).text() == "-$50.00"


def test_text_metric_has_no_delta(qapp):
    a = _snap("Overview Analytics", "2026-09-01", "2026-09-05", busiest_client="Alice")
    b = _snap("Overview Analytics", "2026-10-01", "2026-10-05", busiest_client="Bob")

    dialog = CompareReportsDialog([a, b])
    table = dialog.table
    client_row = table.rowCount() - 1  # Busiest Client is the last metric
    assert table.item(client_row, 1).text() == "Alice"
    assert table.item(client_row, 2).text() == "Bob"
    assert table.item(client_row, 3).text() == "—"


def test_dialog_is_modal_and_closable(qapp):
    a = _snap("Overview Analytics", "2026-09-01", "2026-09-05")
    b = _snap("Overview Analytics", "2026-10-01", "2026-10-05")
    dialog = CompareReportsDialog([a, b])
    assert dialog.isModal() is True
    dialog.accept()
    assert dialog.result() == QDialog.Accepted
