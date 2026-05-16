"""
Test Repository for the PET Application.
Handles recording and lookup of diagnostic tests.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_all_tests():
    """Returns all test types from tests_lookup."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT test_id, test_name FROM tests_lookup ORDER BY test_name ASC"):
        while query.next():
            results.append({
                "test_id": query.value(0),
                "test_name": query.value(1),
            })
    return results


def add_test(test_name):
    """Adds a new test type to the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO tests_lookup (test_name) VALUES (?)")
    query.addBindValue(test_name.strip())
    return query.exec()


def delete_test(test_id):
    """Deletes a test type from the lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM tests_lookup WHERE test_id = ?")
    query.addBindValue(test_id)
    return query.exec()


def record_test(visit_id, test_id, state_id=None):
    """Records a diagnostic test performed during a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO tests (visit_id, test_id, state_id)
        VALUES (?, ?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(test_id)
    query.addBindValue(state_id)
    if not query.exec():
        logger.error(f"Failed to record test for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_tests_for_visit(visit_id):
    """Retrieves all tests recorded during a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT t.routine_test_id, t.visit_id, t.test_id, t.state_id,
               tl.test_name, sl.state_value
        FROM tests t
        LEFT JOIN tests_lookup tl ON t.test_id = tl.test_id
        LEFT JOIN states_lookup sl ON t.state_id = sl.state_id
        WHERE t.visit_id = ?
        ORDER BY t.routine_test_id ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "routine_test_id": query.value(0),
                "visit_id": query.value(1),
                "test_id": query.value(2),
                "state_id": query.value(3),
                "test_name": query.value(4),
                "result": query.value(5),
            })
    return results


def update_test_result(routine_test_id, state_id):
    """Updates the result/state of a recorded test."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE tests SET state_id = ? WHERE routine_test_id = ?")
    query.addBindValue(state_id)
    query.addBindValue(routine_test_id)
    return query.exec()


def delete_test_record(routine_test_id):
    """Deletes a test record from a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM tests WHERE routine_test_id = ?")
    query.addBindValue(routine_test_id)
    return query.exec()


def get_or_create_test(test_name):
    """Resolves a test name to its id, creating the lookup row when absent."""
    clean = (test_name or "").strip()
    if not clean:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT test_id FROM tests_lookup WHERE LOWER(test_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    add_test(clean)
    query.prepare("SELECT test_id FROM tests_lookup WHERE LOWER(test_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    return None


def get_tests_for_export():
    """Returns every test joined to its visit/owner/pet, for export."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               p.pet_name,
               v.visit_date,
               COALESCE(tl.test_name, '') AS test_name,
               COALESCE(sl.state_value, '') AS result
        FROM tests t
        JOIN visits v ON t.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN tests_lookup tl ON t.test_id = tl.test_id
        LEFT JOIN states_lookup sl ON t.state_id = sl.state_id
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
                "test_name": query.value(4) or "",
                "result": query.value(5) or "",
            })
    return results
