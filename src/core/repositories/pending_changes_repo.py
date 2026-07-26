"""
Pending-Changes Repository for the PET Application.

Non-admin users submit change requests instead of writing directly to the DB.
Admins review, approve, or reject them via the approval dialog.

Workflow
--------
1. Non-admin calls ``submit_change(...)`` after collecting form data.
2. Admin sees a count badge in the dashboard reminders table.
3. Admin opens the approval dialog, calls ``get_pending()``, then
   ``approve_change()`` or ``reject_change()`` per row.
4. On approve, ``apply_pending_change(row_dict)`` is called to write the
   payload to the live table transactionally.
"""

from __future__ import annotations
import json
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Apply helper — called by the approval dialog after approve_change() succeeds
# ---------------------------------------------------------------------------

def apply_pending_change(row: dict, reviewer_id: int | None = None) -> bool:
    """Apply an approved pending change to the live table.

    Dispatches based on ``row["table_name"]`` and ``row["operation"]``.
    Only UPDATE is currently supported for the four user-editable tables.

    Args:
        row: A dict as returned by ``get_pending()``, including keys
             ``table_name``, ``record_id``, ``operation``, and ``payload``.
        reviewer_id: Optional user ID of the approving admin; used to credit
                     the live-table write in the audit log.

    Returns:
        True if the live-table write succeeded, False otherwise.
    """
    # Import lazily to avoid circular deps (repos import get_connection, not each other).
    import src.core.repositories.client_repo      as client_repo
    import src.core.repositories.pet_repo         as pet_repo
    import src.core.repositories.visit_repo       as visit_repo
    import src.core.repositories.supply_repo      as supply_repo
    import src.core.repositories.appointment_repo as appointment_repo
    import src.core.repositories.followup_repo    as followup_repo

    table     = row.get("table_name", "")
    operation = row.get("operation",  "")
    record_id = row.get("record_id")
    payload   = row.get("payload", {})

    if not isinstance(payload, dict):
        logger.error("apply_pending_change: payload is not a dict for pending_id=%s", row.get("pending_id"))
        return False

    try:
        if operation == "UPDATE":
            if table == "owners":
                return bool(client_repo.update_client(
                    record_id,
                    payload.get("owner_name", ""),
                    payload.get("phone_number", ""),
                    notes=payload.get("notes"),
                    audit_user_id=reviewer_id,
                ))
            if table == "pets":
                return bool(pet_repo.update_pet(
                    record_id,
                    payload.get("pet_name", ""),
                    payload.get("species", ""),
                    payload.get("breed", ""),
                    payload.get("gender", ""),
                    payload.get("age_months", 0),
                    payload.get("weight", 0.0),
                    payload.get("client_id"),
                    audit_user_id=reviewer_id,
                    notes=payload.get("notes"),
                    health_status=payload.get("health_status"),
                ))
            if table == "visits":
                return bool(visit_repo.update_visit(
                    record_id,
                    payload.get("diagnosis", ""),
                    payload.get("notes", ""),
                    payload.get("visit_date", ""),
                    payload.get("is_consult", 0),
                    audit_user_id=reviewer_id,
                ))
            if table == "supplies":
                return bool(supply_repo.update_supply(
                    record_id,
                    payload.get("item_name", ""),
                    payload.get("category", ""),
                    payload.get("sub_category", ""),
                    payload.get("purchase_date", ""),
                    payload.get("expiry_date", ""),
                    payload.get("buy_price", 0.0),
                    payload.get("sell_price", 0.0),
                    payload.get("quantity", 0),
                    payload.get("supplier", ""),
                    audit_user_id=reviewer_id,
                ))
            if table == "appointments":
                return bool(appointment_repo.update_appointment(
                    record_id,
                    payload.get("appointment_date", ""),
                    payload.get("service", ""),
                    payload.get("status", "Pending"),
                    payload.get("notes", ""),
                    payload.get("client_id"),
                    payload.get("pet_id"),
                    user_id=reviewer_id,
                ))
            if table == "followups":
                return bool(followup_repo.update_followup(
                    record_id,
                    payload.get("followup_date", ""),
                    payload.get("state_id"),
                    payload.get("notes", ""),
                    doctor_id=payload.get("doctor_id"),
                ))
            logger.warning("apply_pending_change: unhandled table '%s'", table)
            return False

        # INSERT / DELETE submitted from this workflow are not yet supported.
        logger.warning(
            "apply_pending_change: unsupported operation '%s' for table '%s'",
            operation, table,
        )
        return False

    except Exception:
        logger.exception(
            "apply_pending_change raised for pending_id=%s table=%s op=%s",
            row.get("pending_id"), table, operation,
        )
        return False


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def submit_change(user_id, table_name, record_id, operation, payload: dict) -> int | None:
    """Insert a new pending change request.

    Args:
        user_id:    ID of the requesting user.
        table_name: Target table (e.g. 'owners', 'pets').
        record_id:  PK of the row to change, or None for INSERT.
        operation:  'UPDATE', 'INSERT', or 'DELETE'.
        payload:    Dict of ``{field: new_value}`` for UPDATE/INSERT;
                    empty dict for DELETE.

    Returns:
        ``pending_id`` on success, ``None`` on failure.
    """
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("""
        INSERT INTO pending_changes
            (user_id, table_name, record_id, operation, payload)
        VALUES (?, ?, ?, ?, ?)
    """)
    q.addBindValue(user_id)
    q.addBindValue(table_name)
    q.addBindValue(record_id)
    q.addBindValue(operation)
    q.addBindValue(json.dumps(payload, ensure_ascii=False))
    if q.exec():
        pending_id = q.lastInsertId()
        try:
            from src.core.repositories import audit_repo
            changes = None
            if isinstance(payload, dict) and payload:
                changes = [
                    {"field_name": str(k), "old_value": "", "new_value": v}
                    for k, v in payload.items()
                ]
            audit_repo.record_action(
                "SUBMIT_" + operation,
                table_name,
                record_id if record_id is not None else pending_id,
                changes=changes,
                user_id=user_id,
            )
        except Exception:
            logger.exception("Failed to audit submitted change (table=%s)", table_name)
        return pending_id
    logger.error("submit_change failed: %s", q.lastError().text())
    return None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def get_pending(status: str = "pending") -> list[dict]:
    """Return pending-change rows joined with the requesting username.

    Args:
        status: Filter by status ('pending', 'approved', 'rejected', or 'all').

    Returns:
        List of dicts with keys:
        pending_id, user_id, username, table_name, record_id,
        operation, payload (parsed dict), status, submitted_at,
        reviewer_id, reviewed_at, review_notes.
    """
    db = get_connection()
    q = QSqlQuery(db)
    if status == "all":
        q.prepare("""
            SELECT pc.pending_id, pc.user_id, u.username,
                   pc.table_name, pc.record_id, pc.operation, pc.payload,
                   pc.status, pc.submitted_at,
                   pc.reviewer_id, pc.reviewed_at, pc.review_notes
            FROM pending_changes pc
            LEFT JOIN users u ON pc.user_id = u.user_id
            ORDER BY pc.submitted_at DESC
        """)
    else:
        q.prepare("""
            SELECT pc.pending_id, pc.user_id, u.username,
                   pc.table_name, pc.record_id, pc.operation, pc.payload,
                   pc.status, pc.submitted_at,
                   pc.reviewer_id, pc.reviewed_at, pc.review_notes
            FROM pending_changes pc
            LEFT JOIN users u ON pc.user_id = u.user_id
            WHERE pc.status = ?
            ORDER BY pc.submitted_at DESC
        """)
        q.addBindValue(status)

    results = []
    if q.exec():
        while q.next():
            raw_payload = q.value(6)
            try:
                parsed = json.loads(raw_payload) if raw_payload else {}
            except (ValueError, TypeError):
                parsed = {}
            results.append({
                "pending_id":   q.value(0),
                "user_id":      q.value(1),
                "username":     q.value(2) or "?",
                "table_name":   q.value(3),
                "record_id":    q.value(4),
                "operation":    q.value(5),
                "payload":      parsed,
                "status":       q.value(7),
                "submitted_at": q.value(8),
                "reviewer_id":  q.value(9),
                "reviewed_at":  q.value(10),
                "review_notes": q.value(11),
            })
    else:
        logger.error("get_pending failed: %s", q.lastError().text())
    return results


def get_pending_count() -> int:
    """Return the number of requests currently in 'pending' status."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT COUNT(*) FROM pending_changes WHERE status = 'pending'")
    if q.exec() and q.next():
        return int(q.value(0) or 0)
    return 0


# ---------------------------------------------------------------------------
# Approve / Reject
# ---------------------------------------------------------------------------

def _record_review_audit(pending_id: int, reviewer_id: int, status: str, notes: str):
    """Record a review outcome without making audit availability block review."""
    try:
        from src.core.repositories import audit_repo
        audit_repo.record_change(
            "pending_changes",
            pending_id,
            [{"field_name": "status", "old_value": "pending", "new_value": status},
             {"field_name": "review_notes", "old_value": "", "new_value": notes}],
            user_id=reviewer_id,
        )
    except Exception:
        logger.exception("Failed to audit pending change review %s", pending_id)

def approve_change(pending_id: int, reviewer_id: int, notes: str = "") -> bool:
    """Mark a pending change as approved.

    The caller is responsible for actually applying the payload to the live
    table after this returns True.

    Args:
        pending_id:  Row to approve.
        reviewer_id: Admin user_id performing the review.
        notes:       Optional reviewer comment.

    Returns:
        True on success.
    """
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("""
        UPDATE pending_changes
        SET status       = 'approved',
            reviewer_id  = ?,
            reviewed_at  = datetime('now', 'localtime'),
            review_notes = ?
        WHERE pending_id = ? AND status = 'pending'
    """)
    q.addBindValue(reviewer_id)
    q.addBindValue(notes)
    q.addBindValue(pending_id)
    if q.exec():
        _record_review_audit(pending_id, reviewer_id, "approved", notes)
        return True
    logger.error("approve_change(%s) failed: %s", pending_id, q.lastError().text())
    return False


def reject_change(pending_id: int, reviewer_id: int, notes: str = "") -> bool:
    """Mark a pending change as rejected.

    Args:
        pending_id:  Row to reject.
        reviewer_id: Admin user_id performing the review.
        notes:       Reason for rejection (shown to the requester in future).

    Returns:
        True on success.
    """
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("""
        UPDATE pending_changes
        SET status       = 'rejected',
            reviewer_id  = ?,
            reviewed_at  = datetime('now', 'localtime'),
            review_notes = ?
        WHERE pending_id = ? AND status = 'pending'
    """)
    q.addBindValue(reviewer_id)
    q.addBindValue(notes)
    q.addBindValue(pending_id)
    if q.exec():
        _record_review_audit(pending_id, reviewer_id, "rejected", notes)
        return True
    logger.error("reject_change(%s) failed: %s", pending_id, q.lastError().text())
    return False
