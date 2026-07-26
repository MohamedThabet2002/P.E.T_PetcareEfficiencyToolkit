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
