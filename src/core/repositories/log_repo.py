"""
Log Repository for the PET Application.
Handles activity logging across the application via the logs and log_types_lookup tables.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_log_types():
    """Returns all log action types from log_types_lookup."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT log_type_id, log_action FROM log_types_lookup ORDER BY log_action ASC"):
        while query.next():
            results.append({
                "log_type_id": query.value(0),
                "log_action": query.value(1),
            })
    return results


def add_log_type(log_action):
    """Adds a new log action type to the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO log_types_lookup (log_action) VALUES (?)")
    query.addBindValue(log_action.strip())
    return query.exec()


def delete_log_type(log_type_id):
    """Deletes a log action type from the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM log_types_lookup WHERE log_type_id = ?")
    query.addBindValue(log_type_id)
    return query.exec()


def add_log(user_id, log_type_id, entity_type, entity_id, details=""):
    """Records an activity log entry.

    Args:
        user_id: The user who performed the action (or None for system).
        log_type_id: ID from log_types_lookup (e.g., CREATE, UPDATE, DELETE).
        entity_type: String identifying the entity type (e.g., 'visit', 'supply').
        entity_id: The ID of the affected entity record.
        details: Optional free-text details about the action.

    Returns:
        log_id on success, None on failure.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO logs (user_id, log_type_id, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
    """)
    query.addBindValue(user_id)
    query.addBindValue(log_type_id)
    query.addBindValue(entity_type)
    query.addBindValue(entity_id)
    query.addBindValue(details)
    if not query.exec():
        logger.error(f"Failed to add log entry: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_logs(limit=100, offset=0, entity_type=None, entity_id=None):
    """Retrieves log entries with optional filtering.

    Args:
        limit: Maximum number of entries to return.
        offset: Number of entries to skip (for pagination).
        entity_type: Optional filter by entity type.
        entity_id: Optional filter by entity ID.

    Returns:
        List of log entry dicts.
    """
    db = get_connection()
    query = QSqlQuery(db)

    sql = """
        SELECT l.log_id, l.user_id, l.log_type_id, l.entity_type, l.entity_id,
               l.timestamp, l.details, u.username, lt.log_action
        FROM logs l
        LEFT JOIN users u ON l.user_id = u.user_id
        LEFT JOIN log_types_lookup lt ON l.log_type_id = lt.log_type_id
        WHERE 1=1
    """
    params = []

    if entity_type:
        sql += " AND l.entity_type = ?"
        params.append(entity_type)
    if entity_id is not None:
        sql += " AND l.entity_id = ?"
        params.append(entity_id)

    sql += " ORDER BY l.timestamp DESC LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)

    query.prepare(sql)
    for p in params:
        query.addBindValue(p)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "log_id": query.value(0),
                "user_id": query.value(1),
                "log_type_id": query.value(2),
                "entity_type": query.value(3),
                "entity_id": query.value(4),
                "timestamp": query.value(5),
                "details": query.value(6),
                "username": query.value(7),
                "log_action": query.value(8),
            })
    return results


def get_logs_for_entity(entity_type, entity_id, limit=50):
    """Convenience method to get logs for a specific entity record."""
    return get_logs(limit=limit, entity_type=entity_type, entity_id=entity_id)


def get_recent_activity(limit=20):
    """Returns the most recent activity logs across all entities."""
    return get_logs(limit=limit)


def delete_log(log_id):
    """Deletes a log entry by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM logs WHERE log_id = ?")
    query.addBindValue(log_id)
    return query.exec()


def clear_logs(before_date=None):
    """Clears log entries, optionally only those before a given date.

    Args:
        before_date: Optional date string (YYYY-MM-DD). If None, clears all logs.
    """
    db = get_connection()
    query = QSqlQuery(db)
    if before_date:
        query.prepare("DELETE FROM logs WHERE date(timestamp) < ?")
        query.addBindValue(before_date)
    else:
        query.exec("DELETE FROM logs")
    return True
