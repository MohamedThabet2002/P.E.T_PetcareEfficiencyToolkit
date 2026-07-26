"""
Follow-up Repository for the PET Application.
Handles scheduling and tracking of follow-up visits.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_followup(visit_id, followup_date, state_id=None, notes=""):
    """Schedules a follow-up visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO followups (visit_id, followup_date, state_id, notes)
        VALUES (?, ?, ?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(followup_date)
    query.addBindValue(state_id)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add followup for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_followups_for_visit(visit_id):
    """Retrieves all follow-ups scheduled for a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT f.followup_id, f.visit_id, f.followup_date, f.state_id, f.notes,
               sl.state_value
        FROM followups f
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE f.visit_id = ?
        ORDER BY f.followup_date ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "followup_id": query.value(0),
                "visit_id": query.value(1),
                "followup_date": query.value(2),
                "state_id": query.value(3),
                "notes": query.value(4),
                "status": query.value(5),
            })
    return results


def get_upcoming_followups(limit=10):
    """Returns upcoming scheduled follow-ups."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT f.followup_id, f.followup_date, f.notes,
               p.pet_name, o.first_name || ' ' || o.last_name AS owner_name
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        WHERE date(f.followup_date) >= date('now', 'localtime')
        ORDER BY f.followup_date ASC LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "followup_id": query.value(0),
                "followup_date": query.value(1),
                "notes": query.value(2),
                "pet_name": query.value(3),
                "owner_name": query.value(4),
            })
    return results


def update_followup(followup_id, followup_date, state_id, notes):
    """Updates a follow-up record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE followups SET followup_date = ?, state_id = ?, notes = ?
        WHERE followup_id = ?
    """)
    query.addBindValue(followup_date)
    query.addBindValue(state_id)
    query.addBindValue(notes)
    query.addBindValue(followup_id)
    return query.exec()


def delete_followup(followup_id):
    """Deletes a follow-up record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM followups WHERE followup_id = ?")
    query.addBindValue(followup_id)
    return query.exec()
