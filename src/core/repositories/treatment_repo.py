"""
Treatment Repository for the PET Application.
Handles recording and lookup of medical treatments.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_all_treatments():
    """Returns all treatment types from treatments_lookup."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT treatment_id, treatment_name FROM treatments_lookup ORDER BY treatment_name ASC"):
        while query.next():
            results.append({
                "treatment_id": query.value(0),
                "treatment_name": query.value(1),
            })
    return results


def add_treatment(treatment_name):
    """Adds a new treatment type to the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO treatments_lookup (treatment_name) VALUES (?)")
    query.addBindValue(treatment_name.strip())
    return query.exec()


def delete_treatment(treatment_id):
    """Deletes a treatment type from the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM treatments_lookup WHERE treatment_id = ?")
    query.addBindValue(treatment_id)
    return query.exec()


def record_treatment(visit_id, treatment_id):
    """Records a treatment performed during a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO treatments (visit_id, treatment_id)
        VALUES (?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(treatment_id)
    if not query.exec():
        logger.error(f"Failed to record treatment for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_treatments_for_visit(visit_id):
    """Retrieves all treatments recorded during a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT tr.treatment_record_id, tr.visit_id, tr.treatment_id,
               tl.treatment_name
        FROM treatments tr
        LEFT JOIN treatments_lookup tl ON tr.treatment_id = tl.treatment_id
        WHERE tr.visit_id = ?
        ORDER BY tr.treatment_record_id ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "treatment_record_id": query.value(0),
                "visit_id": query.value(1),
                "treatment_id": query.value(2),
                "treatment_name": query.value(3),
            })
    return results


def delete_treatment_record(treatment_record_id):
    """Deletes a treatment record from a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM treatments WHERE treatment_record_id = ?")
    query.addBindValue(treatment_record_id)
    return query.exec()
