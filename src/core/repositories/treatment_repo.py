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


def get_or_create_treatment(treatment_name):
    """Resolves a treatment name to its id, creating the lookup row when absent."""
    clean = (treatment_name or "").strip()
    if not clean:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT treatment_id FROM treatments_lookup "
                  "WHERE LOWER(treatment_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    add_treatment(clean)
    query.prepare("SELECT treatment_id FROM treatments_lookup "
                  "WHERE LOWER(treatment_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    return None


def get_treatments_for_export():
    """Returns every treatment joined to its visit/owner/pet, for export."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               p.pet_name,
               v.visit_date,
               COALESCE(tl.treatment_name, '') AS treatment_name
        FROM treatments tr
        JOIN visits v ON tr.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN treatments_lookup tl ON tr.treatment_id = tl.treatment_id
        LEFT JOIN entity_contacts ec
               ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY v.visit_date ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "owner_name": query.value(0) or "",
                "phone_number": query.value(1) or "",
                "pet_name": query.value(2) or "",
                "visit_date": query.value(3) or "",
                "treatment_name": query.value(4) or "",
            })
    return results
