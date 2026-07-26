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
