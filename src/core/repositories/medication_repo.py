"""
Medication Repository for the PET Application.
Handles medication prescriptions linked to visits and supplies inventory.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def prescribe_medication(visit_id, supply_id, dosage, instructions):
    """Records a medication prescription during a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO medications (visit_id, supply_id, dosage, instructions)
        VALUES (?, ?, ?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(supply_id)
    query.addBindValue(dosage)
    query.addBindValue(instructions)
    if not query.exec():
        logger.error(f"Failed to prescribe medication for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_medications_for_visit(visit_id):
    """Retrieves all medications prescribed during a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT m.medication_id, m.visit_id, m.supply_id, m.dosage, m.instructions,
               s.item_name
        FROM medications m
        LEFT JOIN supplies s ON m.supply_id = s.supply_id
        WHERE m.visit_id = ?
        ORDER BY m.medication_id ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "medication_id": query.value(0),
                "visit_id": query.value(1),
                "supply_id": query.value(2),
                "dosage": query.value(3),
                "instructions": query.value(4),
                "item_name": query.value(5),
            })
    return results


def get_medication_history(pet_id, limit=10):
    """Retrieves the medication history for a specific pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT m.medication_id, m.dosage, m.instructions, s.item_name,
               vis.visit_date
        FROM medications m
        JOIN visits vis ON m.visit_id = vis.visit_id
        JOIN pets p ON vis.pet_id = p.pet_id
        LEFT JOIN supplies s ON m.supply_id = s.supply_id
        WHERE p.pet_id = ?
        ORDER BY vis.visit_date DESC LIMIT ?
    """)
    query.addBindValue(pet_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "medication_id": query.value(0),
                "dosage": query.value(1),
                "instructions": query.value(2),
                "item_name": query.value(3),
                "visit_date": query.value(4),
            })
    return results


def update_medication(medication_id, dosage, instructions):
    """Updates a medication prescription."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE medications SET dosage = ?, instructions = ? WHERE medication_id = ?")
    query.addBindValue(dosage)
    query.addBindValue(instructions)
    query.addBindValue(medication_id)
    return query.exec()


def delete_medication(medication_id):
    """Deletes a medication prescription record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM medications WHERE medication_id = ?")
    query.addBindValue(medication_id)
    return query.exec()
