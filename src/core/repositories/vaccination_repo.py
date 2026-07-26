"""
Vaccination Repository for the PET Application.
Handles recording and lookup of pet vaccinations.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_all_vaccines():
    """Returns all vaccine types from vaccines_lookup."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT vaccine_id, vaccine_name FROM vaccines_lookup ORDER BY vaccine_name ASC"):
        while query.next():
            results.append({
                "vaccine_id": query.value(0),
                "vaccine_name": query.value(1),
            })
    return results


def add_vaccine(vaccine_name):
    """Adds a new vaccine type to the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO vaccines_lookup (vaccine_name) VALUES (?)")
    query.addBindValue(vaccine_name.strip())
    return query.exec()


def delete_vaccine(vaccine_id):
    """Deletes a vaccine type from the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM vaccines_lookup WHERE vaccine_id = ?")
    query.addBindValue(vaccine_id)
    return query.exec()


def record_vaccination(visit_id, vaccine_id):
    """Records a vaccination administered during a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO vaccinations (visit_id, vaccine_id)
        VALUES (?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(vaccine_id)
    if not query.exec():
        logger.error(f"Failed to record vaccination for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_vaccinations_for_visit(visit_id):
    """Retrieves all vaccinations recorded during a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.vaccination_id, v.visit_id, v.vaccine_id, vl.vaccine_name
        FROM vaccinations v
        LEFT JOIN vaccines_lookup vl ON v.vaccine_id = vl.vaccine_id
        WHERE v.visit_id = ?
        ORDER BY v.vaccination_id ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "vaccination_id": query.value(0),
                "visit_id": query.value(1),
                "vaccine_id": query.value(2),
                "vaccine_name": query.value(3),
            })
    return results


def get_vaccination_history(pet_id, limit=10):
    """Retrieves the vaccination history for a specific pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.vaccination_id, v.vaccine_id, vl.vaccine_name,
               vis.visit_date
        FROM vaccinations v
        JOIN visits vis ON v.visit_id = vis.visit_id
        JOIN pets p ON vis.pet_id = p.pet_id
        LEFT JOIN vaccines_lookup vl ON v.vaccine_id = vl.vaccine_id
        WHERE p.pet_id = ?
        ORDER BY vis.visit_date DESC LIMIT ?
    """)
    query.addBindValue(pet_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "vaccination_id": query.value(0),
                "vaccine_id": query.value(1),
                "vaccine_name": query.value(2),
                "visit_date": query.value(3),
            })
    return results


def delete_vaccination_record(vaccination_id):
    """Deletes a vaccination record from a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM vaccinations WHERE vaccination_id = ?")
    query.addBindValue(vaccination_id)
    return query.exec()


def get_or_create_vaccine(vaccine_name):
    """Resolves a vaccine name to its id, creating the lookup row when absent."""
    clean = (vaccine_name or "").strip()
    if not clean:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT vaccine_id FROM vaccines_lookup "
                  "WHERE LOWER(vaccine_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    add_vaccine(clean)
    query.prepare("SELECT vaccine_id FROM vaccines_lookup "
                  "WHERE LOWER(vaccine_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    return None


def get_vaccinations_for_export():
    """Returns every vaccination joined to its visit/owner/pet, for export."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               p.pet_name,
               v.visit_date,
               COALESCE(vl.vaccine_name, '') AS vaccine_name
        FROM vaccinations vc
        JOIN visits v ON vc.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN vaccines_lookup vl ON vc.vaccine_id = vl.vaccine_id
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
                "vaccine_name": query.value(4) or "",
            })
    return results
