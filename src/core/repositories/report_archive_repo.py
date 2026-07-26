"""
Report Archive Repository for the PET Application.

Persists report snapshots that a user explicitly saves ("Save Report"). Every
save is a new history entry, so the archive doubles as an audit-friendly log of
"how the numbers looked when this report was filed" rather than a single mutable
row per period. The Reports page's side panel reads this log; the calendar tints
the day each saved report's window ends on.
"""

import json
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)


def _row_to_dict(query):
    """Builds an archive dict (with parsed data_json) from a positioned query row."""
    try:
        data = json.loads(query.value(7) or "{}")
    except (ValueError, TypeError):
        data = {}
    return {
        "archive_id": query.value(0),
        "report_kind": query.value(1),
        "period_type": query.value(2),
        "period_start": query.value(3),
        "period_end": query.value(4),
        "generated_at": query.value(5),
        "generated_by": query.value(6),
        "data": data,
    }


def _row_meta(query):
    """Builds an archive metadata dict (no data_json) from a positioned query row."""
    return {
        "archive_id": query.value(0),
        "report_kind": query.value(1),
        "period_type": query.value(2),
        "period_start": query.value(3),
        "period_end": query.value(4),
        "generated_at": query.value(5),
        "generated_by": query.value(6),
    }


_META_COLUMNS = (
    "archive_id, report_kind, period_type, period_start, period_end, "
    "generated_at, generated_by"
)


def save_snapshot(report_kind, period_type, data, period_start="", period_end="", generated_by=""):
    """Saves a report snapshot as a new history entry.

    Unlike the earlier period-keyed upsert, every call inserts a fresh row: a
    "Save Report" is a deliberate point-in-time record, so filing the same window
    twice keeps both snapshots (numbers can change retroactively, e.g. late
    payments). Use :func:`delete_archive` to prune entries.

    Args:
        report_kind: One of the report category names (e.g. "Financial Report").
        period_type: Period selector value (e.g. "Month", "Custom").
        data: Snapshot dict with "kpis" and "tables" payloads.
        period_start / period_end: The report window this snapshot covers.
        generated_by: Username that generated the report.

    Returns:
        archive_id on success, None on failure.
    """
    db = get_connection()
    payload = json.dumps(data, ensure_ascii=False)
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO report_archives (report_kind, period_type, period_start, period_end,
                                     generated_by, data_json, generated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
    """)
    query.addBindValue(report_kind)
    query.addBindValue(period_type)
    query.addBindValue(period_start)
    query.addBindValue(period_end)
    query.addBindValue(generated_by)
    query.addBindValue(payload)
    if query.exec():
        return int(query.lastInsertId())
    logger.error("Failed to save report snapshot: %s", query.lastError().text())
    return None


def list_archives(limit=100):
    """Returns the most recent report snapshots, newest first."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"""
        SELECT {_META_COLUMNS}
        FROM report_archives
        ORDER BY generated_at DESC, archive_id DESC LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append(_row_meta(query))
    query.finish()
    return results


def search_archives(text="", limit=300):
    """Returns saved-report metadata matching a free-text query, newest first.

    The query is matched (case-insensitively) against the report kind, the period
    type and the saved-by user — everything the history panel displays. An empty
    query lists everything.
    """
    db = get_connection()
    query = QSqlQuery(db)
    term = (text or "").strip()
    if term:
        sql = f"""
            SELECT {_META_COLUMNS}
            FROM report_archives
            WHERE report_kind LIKE ? OR period_type LIKE ?
               OR COALESCE(generated_by, '') LIKE ?
               OR COALESCE(period_start, '') LIKE ? OR COALESCE(period_end, '') LIKE ?
            ORDER BY generated_at DESC, archive_id DESC LIMIT ?
        """
        query.prepare(sql)
        like = f"%{term}%"
        for _ in range(5):
            query.addBindValue(like)
        query.addBindValue(limit)
    else:
        query.prepare(f"""
            SELECT {_META_COLUMNS}
            FROM report_archives
            ORDER BY generated_at DESC, archive_id DESC LIMIT ?
        """)
        query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append(_row_meta(query))
    query.finish()
    return results


def get_archive(archive_id):
    """Returns a single snapshot (with parsed data_json) or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT archive_id, report_kind, period_type, period_start, period_end,
               generated_at, generated_by, data_json
        FROM report_archives
        WHERE archive_id = ?
    """)
    query.addBindValue(archive_id)
    row = None
    if query.exec() and query.next():
        row = _row_to_dict(query)
    query.finish()
    return row


def delete_archive(archive_id):
    """Removes a saved report snapshot. Returns True on success."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM report_archives WHERE archive_id = ?")
    query.addBindValue(archive_id)
    ok = query.exec()
    query.finish()
    return ok


def clear_archives():
    """Removes every saved report snapshot. Returns True on success."""
    db = get_connection()
    query = QSqlQuery(db)
    ok = query.exec("DELETE FROM report_archives")
    query.finish()
    return ok


def list_archive_days(limit=400):
    """Returns list of (day, count) for report windows that have saved snapshots.

    ``day`` is the window's anchor day — its ``period_end`` (the calendar day the
    report window is anchored on), falling back to ``generated_at`` for legacy
    rows. Sorted newest first so the calendar can mark days with saved reports.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COALESCE(NULLIF(period_end, ''), date(generated_at)) AS day,
               COUNT(*) AS cnt
        FROM report_archives
        GROUP BY day
        ORDER BY day DESC LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append((query.value(0), int(query.value(1) or 0)))
    query.finish()
    return results


def list_archives_for_day(day):
    """Returns snapshots whose window is anchored on a given 'YYYY-MM-DD' day.

    The anchor is the window's ``period_end`` (fallback: ``generated_at``), so a
    saved Day report for 2026-10-07 is returned for 2026-10-07 — not for the day
    it happened to be generated. Newest first.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"""
        SELECT {_META_COLUMNS}
        FROM report_archives
        WHERE COALESCE(NULLIF(period_end, ''), date(generated_at)) = date(?)
        ORDER BY generated_at DESC, archive_id DESC
    """)
    query.addBindValue(day)
    results = []
    if query.exec():
        while query.next():
            results.append(_row_meta(query))
    query.finish()
    return results
