"""
Pet Health Timeline Repository for the PET Application.
Retrieves chronological clinical events for a pet from the v_pet_health_timeline view.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_pet_health_timeline(pet_id, limit=50):
    """Retrieves a chronological timeline of all clinical events for a pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT event_type, event_id, event_date, summary, detail_1, detail_2, source_visit_id
        FROM v_pet_health_timeline
        WHERE pet_id = ?
        ORDER BY event_date DESC, event_type ASC
        LIMIT ?
    """)
    query.addBindValue(pet_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "event_type": query.value(0),
                "event_id": query.value(1),
                "event_date": query.value(2),
                "summary": query.value(3),
                "detail_1": query.value(4),
                "detail_2": query.value(5),
                "source_visit_id": query.value(6),
            })
    else:
        logger.error(f"Failed to get health timeline for pet {pet_id}: {query.lastError().text()}")
    return results


def get_pet_event_counts(pet_id):
    """Returns a count of events by type for a pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT event_type, COUNT(*) as cnt
        FROM v_pet_health_timeline
        WHERE pet_id = ?
        GROUP BY event_type
    """)
    query.addBindValue(pet_id)
    results = {}
    if query.exec():
        while query.next():
            results[query.value(0)] = query.value(1)
    return results
