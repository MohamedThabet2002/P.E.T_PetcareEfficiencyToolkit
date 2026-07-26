"""
Receipt Adjustment Repository for the PET Application.

Records and retrieves cumulative billing adjustments applied to a single sale
receipt. When a visit's receipt is edited in a way that changes its total, an
adjustment row is appended so the Receipt Details dialog can show the original
amount alongside every change (a revision trail).
"""

import json
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_adjustment(receipt_id, visit_id=None, adjusted_by=None,
                   description="", old_total=0.0, new_total=0.0, details=None):
    """Records a single cumulative receipt adjustment.

    Args:
        receipt_id: The receipt that was changed.
        visit_id:   The related visit (if any).
        adjusted_by: The user_id that performed the adjustment.
        description: Short human-readable summary of what changed.
        old_total:  Receipt total before the adjustment.
        new_total:  Receipt total after the adjustment.
        details:    Optional list of per-line delta dicts (stored as JSON).

    Returns:
        The new adjustment_id, or None on failure.
    """
    db = get_connection()
    # Qt hands back '' for a NULL foreign key; re-binding it as '' violates
    # the constraint. An empty string means "absent" here (same rule the
    # undo/restore engine applies), so let the column take a real NULL.
    if not visit_id:
        visit_id = None
    if not adjusted_by:
        adjusted_by = None
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO receipt_adjustments
            (receipt_id, visit_id, adjusted_by, description,
             old_total, new_total, delta, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(receipt_id)
    query.addBindValue(visit_id)
    query.addBindValue(adjusted_by)
    query.addBindValue(description or "")
    query.addBindValue(float(old_total or 0.0))
    query.addBindValue(float(new_total or 0.0))
    query.addBindValue(float(new_total or 0.0) - float(old_total or 0.0))
    try:
        query.addBindValue(json.dumps(details or [], ensure_ascii=False))
    except (TypeError, ValueError):
        query.addBindValue("[]")
    if query.exec():
        return int(query.lastInsertId())
    logger.error(f"Failed to record receipt adjustment: {query.lastError().text()}")
    return None


def get_adjustments_for_receipt(receipt_id):
    """Returns all cumulative adjustments for a receipt, oldest first.

    Each dict has: adjustment_id, receipt_id, visit_id, adjusted_by,
    description, old_total, new_total, delta, details(list), created_at.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT adjustment_id, receipt_id, visit_id, adjusted_by,
               description, old_total, new_total, delta, details, created_at
        FROM receipt_adjustments
        WHERE receipt_id = ?
        ORDER BY adjustment_id ASC
    """)
    query.addBindValue(receipt_id)
    results = []
    if query.exec():
        while query.next():
            details = []
            raw = query.value(8) or ""
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        details = parsed
                except (ValueError, TypeError):
                    details = []
            results.append({
                "adjustment_id": query.value(0),
                "receipt_id": query.value(1),
                "visit_id": query.value(2),
                "adjusted_by": query.value(3),
                "description": query.value(4) or "",
                "old_total": query.value(5),
                "new_total": query.value(6),
                "delta": query.value(7),
                "details": details,
                "created_at": query.value(9) or "",
            })
    return results


def get_adj_writer_name(adjusted_by):
    """Returns a display name for an adjuster user_id, or an empty string."""
    if adjusted_by is None:
        return ""
    from src.core.repositories import user_repo
    try:
        user = user_repo.get_user_by_id(adjusted_by)
        if user:
            return user.get("username") or ""
    except Exception:
        pass
    return ""


def delete_adjustments_for_receipt(receipt_id):
    """Removes all adjustments for a receipt (used on receipt deletion)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM receipt_adjustments WHERE receipt_id = ?")
    query.addBindValue(receipt_id)
    return query.exec()
