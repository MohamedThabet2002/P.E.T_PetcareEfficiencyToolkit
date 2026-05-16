"""
Audit Repository for the PET Application.
Tracks data changes via change_header and change_detail tables for auditing purposes.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def record_change(table_name, record_id, changes, user_id=None):
    """Records a data change in the audit log.
    
    Args:
        table_name: The table that was changed.
        record_id: The ID of the affected record.
        changes: List of dicts with 'field_name', 'old_value', 'new_value'.
        user_id: Optional user ID who made the change.
    
    Returns:
        change_header_id on success, None on failure.
    """
    db = get_connection()
    
    # Create change header
    hq = QSqlQuery(db)
    hq.prepare("""
        INSERT INTO change_header (user_id, table_name, record_id)
        VALUES (?, ?, ?)
    """)
    hq.addBindValue(user_id)
    hq.addBindValue(table_name)
    hq.addBindValue(record_id)
    
    if not hq.exec():
        logger.error(f"Failed to create change header: {hq.lastError().text()}")
        return None
    
    header_id = hq.lastInsertId()
    
    # Record each field change
    for change in changes:
        dq = QSqlQuery(db)
        dq.prepare("""
            INSERT INTO change_detail (change_header_id, field_name, old_value, new_value)
            VALUES (?, ?, ?, ?)
        """)
        dq.addBindValue(header_id)
        dq.addBindValue(change.get("field_name", ""))
        dq.addBindValue(str(change.get("old_value", "")))
        dq.addBindValue(str(change.get("new_value", "")))
        if not dq.exec():
            logger.error(f"Failed to record change detail: {dq.lastError().text()}")
    
    return header_id


def record_action(action, table_name, record_id, changes=None, user_id=None):
    """Records a high-level action (ADD/UPDATE/DELETE/SUBMIT_*) in the audit log.

    Uses a single detail row so every add/edit/delete/submit performed by any
    user shows up in the Audit Log report even when no field-level diff exists.

    Args:
        action: Action label, e.g. "ADD", "UPDATE", "DELETE", "SUBMIT_UPDATE".
        table_name: The table that was changed (e.g. 'owners', 'pets').
        record_id: The ID of the affected record (may be None for inserts).
        changes: Optional list of dicts with 'field_name', 'old_value',
                 'new_value'. Defaults to a single action detail row.
        user_id: Optional user ID who performed the action.

    Returns:
        change_header_id on success, None on failure.
    """
    if not changes:
        changes = [{"field_name": "action", "old_value": "", "new_value": action}]
    else:
        # Keep the action label as the first detail row so add/edit/delete
        # entries always know what happened, even when field diffs exist.
        changes = [{"field_name": "action", "old_value": "", "new_value": action}] + list(changes)
    return record_change(table_name, record_id, changes, user_id=user_id)


def get_recent_changes(limit=50):
    """Retrieves the most recent data changes."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT ch.change_header_id, ch.user_id, ch.table_name, ch.record_id,
               ch.changed_at, u.username
        FROM change_header ch
        LEFT JOIN users u ON ch.user_id = u.user_id
        ORDER BY ch.changed_at DESC LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "change_header_id": query.value(0),
                "user_id": query.value(1),
                "table_name": query.value(2),
                "record_id": query.value(3),
                "changed_at": query.value(4),
                "username": query.value(5),
            })
    return results


def field_diffs(old_row, new_row):
    """Builds field-level change dicts for values that differ between two rows."""
    changes = []
    for field, new_value in (new_row or {}).items():
        old_value = (old_row or {}).get(field)
        if str(old_value or "") != str(new_value or ""):
            changes.append({
                "field_name": field,
                "old_value": "" if old_value is None else str(old_value),
                "new_value": "" if new_value is None else str(new_value),
            })
    return changes


def get_recent_changes_with_details(limit=50):
    """Retrieves the most recent changes, each carrying its field details.

    Unlike ``get_recent_changes`` this also returns the per-change detail rows
    (field_name / old_value / new_value) so UIs can show exactly what changed.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT h.change_header_id, h.user_id, h.table_name, h.record_id,
               h.changed_at, u.username, d.field_name, d.old_value, d.new_value
        FROM (
            SELECT change_header_id, user_id, table_name, record_id, changed_at
            FROM change_header
            ORDER BY changed_at DESC LIMIT ?
        ) h
        LEFT JOIN users u ON h.user_id = u.user_id
        LEFT JOIN change_detail d ON d.change_header_id = h.change_header_id
        ORDER BY h.changed_at DESC
    """)
    query.addBindValue(limit)
    results = []
    by_id = {}
    order = []
    if query.exec():
        while query.next():
            header_id = query.value(0)
            if header_id not in by_id:
                by_id[header_id] = {
                    "change_header_id": header_id,
                    "user_id": query.value(1),
                    "table_name": query.value(2),
                    "record_id": query.value(3),
                    "changed_at": query.value(4),
                    "username": query.value(5),
                    "details": [],
                }
                order.append(header_id)
            if query.value(6) is not None:
                by_id[header_id]["details"].append({
                    "field_name": query.value(6),
                    "old_value": query.value(7) or "",
                    "new_value": query.value(8) or "",
                })
    return [by_id[header_id] for header_id in order]


_TABLE_LABELS = {
    "owners": "owner",
    "pets": "pet",
    "visits": "visit",
    "appointments": "appointment",
    "supplies": "supply",
    "stocks": "stock batch",
    "receipts": "receipt",
    "pending_changes": "change request",
}


def format_audit_message(entry, max_length=400):
    """Describes what an audit entry actually changed, for restoration.

    Unlike a narrative sentence, this is a compact record of the edit itself:

    - ADD:    ``added``
    - UPDATE: ``edited owner name from 'mohamed' to 'Mohamed'``,
              ``edited pet weight from '1' to '1.2'``
    - DELETE: ``deleted owner name 'Mohamed' with phone number '01230231'``

    The stored details hold the capturable data so entries can be used to
    rebuild a record if it was lost or accidentally changed.
    """
    table = (entry or {}).get("table_name") or ""
    label = _TABLE_LABELS.get(table, table)
    details = entry.get("details") or []

    action = ""
    diffs = []
    for detail in details:
        field = detail.get("field_name") or ""
        if field == "action":
            action = detail.get("new_value") or ""
        else:
            diffs.append((field, detail.get("old_value") or "", detail.get("new_value") or ""))

    if table == "pending_changes":
        return _format_review(diffs, entry)

    if action == "ADD":
        return "added"

    if action == "DELETE":
        values = [(field, old_value or new_value) for field, old_value, new_value in diffs]
        phrases = [f"{_display_field(field, label)} '{value}'" for field, value in values if value]
        if not phrases:
            return "deleted"
        message = f"deleted {label} "
        if len(phrases) == 1:
            message += phrases[0]
        else:
            message += ", ".join(phrases[:-1]) + " with " + phrases[-1]
        return _truncate(message, max_length)

    if action.startswith("SUBMIT_"):
        return "submitted " + action.split("_", 1)[1].lower()

    phrases = []
    for field, old_value, new_value in diffs:
        display_field = _display_field(field, label)
        if old_value and not new_value:
            phrases.append(f"{display_field} cleared")
        elif old_value and new_value:
            phrases.append(f"{display_field} from '{old_value}' to '{new_value}'")
        elif new_value:
            phrases.append(f"{display_field} to '{new_value}'")
    if phrases:
        message = f"edited {label} " + ", ".join(phrases)
        return _truncate(message, max_length)
    return "changed"


def _format_review(diffs, entry):
    """Formats a pending-change review (approve / reject) entry."""
    review_status = next((value for field, _, value in diffs if field == "status"), "")
    record_id = entry.get("record_id")
    ref = ""
    if record_id is not None and record_id != "":
        ref = f" (id {record_id})"
    message = f"{review_status or 'reviewed'} change request{ref}"
    extra = [
        f"{_pretty(field)}: {value}"
        for field, _, value in diffs if field != "status" and value
    ]
    if extra:
        message += " (" + ", ".join(extra) + ")"
    return message


def _pretty(field):
    """Turns snake_case field names into readable labels."""
    return field.replace("_", " ")


_FIELD_ALIASES = {
    "weight_in_kg": "weight",
    "age_in_months": "age",
    "current_stock": "stock",
    "temperature_in_c": "temperature",
    "visit_date": "date",
    "appointment_date": "date",
}


def _display_field(field, label):
    """Readable field name that skips the duplicate table prefix.

    e.g. for label ``owner``, field ``owner_name`` renders as ``name`` so the
    final text reads ``edited owner name from ...``.
    """
    prefix = label.replace(" ", "_") + "_"
    if field.startswith(prefix) and len(field) > len(prefix):
        field = field[len(prefix):]
    field = _FIELD_ALIASES.get(field, field)
    return field.replace("_", " ")


def _truncate(text, max_length):
    """Truncates a message with an ellipsis when it exceeds max_length."""
    if len(text) > max_length:
        text = text[: max_length - 1] + "\u2026"
    return text


def get_change_details(change_header_id):
    """Retrieves the individual field changes for a given change header."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT change_detail_id, field_name, old_value, new_value
        FROM change_detail
        WHERE change_header_id = ?
        ORDER BY change_detail_id ASC
    """)
    query.addBindValue(change_header_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "change_detail_id": query.value(0),
                "field_name": query.value(1),
                "old_value": query.value(2),
                "new_value": query.value(3),
            })
    return results


def get_changes_for_record(table_name, record_id, limit=20):
    """Retrieves all changes made to a specific record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT ch.change_header_id, ch.user_id, ch.changed_at, u.username
        FROM change_header ch
        LEFT JOIN users u ON ch.user_id = u.user_id
        WHERE ch.table_name = ? AND ch.record_id = ?
        ORDER BY ch.changed_at DESC LIMIT ?
    """)
    query.addBindValue(table_name)
    query.addBindValue(record_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            header_id = query.value(0)
            details = get_change_details(header_id)
            results.append({
                "change_header_id": header_id,
                "user_id": query.value(1),
                "changed_at": query.value(2),
                "username": query.value(3),
                "details": details,
            })
    return results
