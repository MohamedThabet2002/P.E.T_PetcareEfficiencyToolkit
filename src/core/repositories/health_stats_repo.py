"""
Health Stats Repository for the PET Application.
Handles recording and retrieval of health statistics (temperature, weight, vitals).
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_health_stat(pet_id, visit_id, stat_type_id, state_id, extra_note=""):
    """Records a health statistic for a pet during a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO health_stats (pet_id, visit_id, stat_type_id, state_id, extra_note)
        VALUES (?, ?, ?, ?, ?)
    """)
    query.addBindValue(pet_id)
    query.addBindValue(visit_id)
    query.addBindValue(stat_type_id)
    query.addBindValue(state_id)
    query.addBindValue(extra_note)
    if not query.exec():
        logger.error(f"Failed to add health stat for pet {pet_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_health_stats_for_visit(visit_id):
    """Retrieves all health stats recorded during a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT hs.health_stat_id, hs.pet_id, hs.visit_id, hs.stat_type_id,
               hs.state_id, hs.extra_note,
               st.stat_name, sys.system_name, sl.state_value
        FROM health_stats hs
        LEFT JOIN stat_types_lookup st ON hs.stat_type_id = st.stat_type_id
        LEFT JOIN systems_lookup sys ON st.system_id = sys.system_id
        LEFT JOIN states_lookup sl ON hs.state_id = sl.state_id
        WHERE hs.visit_id = ?
        ORDER BY hs.health_stat_id ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "health_stat_id": query.value(0),
                "pet_id": query.value(1),
                "visit_id": query.value(2),
                "stat_type_id": query.value(3),
                "state_id": query.value(4),
                "extra_note": query.value(5),
                "stat_name": query.value(6),
                "system_name": query.value(7),
                "state_value": query.value(8),
            })
    return results


def get_health_stats_for_pet(pet_id, limit=20):
    """Retrieves the most recent health stats for a pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT hs.health_stat_id, hs.visit_id, hs.stat_type_id,
               hs.state_id, hs.extra_note, v.visit_date,
               st.stat_name, sys.system_name, sl.state_value
        FROM health_stats hs
        JOIN visits v ON hs.visit_id = v.visit_id
        LEFT JOIN stat_types_lookup st ON hs.stat_type_id = st.stat_type_id
        LEFT JOIN systems_lookup sys ON st.system_id = sys.system_id
        LEFT JOIN states_lookup sl ON hs.state_id = sl.state_id
        WHERE hs.pet_id = ?
        ORDER BY v.visit_date DESC LIMIT ?
    """)
    query.addBindValue(pet_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "health_stat_id": query.value(0),
                "visit_id": query.value(1),
                "stat_type_id": query.value(2),
                "state_id": query.value(3),
                "extra_note": query.value(4),
                "visit_date": query.value(5),
                "stat_name": query.value(6),
                "system_name": query.value(7),
                "state_value": query.value(8),
            })
    return results


def delete_health_stat(health_stat_id):
    """Deletes a health stat record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM health_stats WHERE health_stat_id = ?")
    query.addBindValue(health_stat_id)
    return query.exec()
