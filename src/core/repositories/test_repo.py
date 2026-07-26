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
