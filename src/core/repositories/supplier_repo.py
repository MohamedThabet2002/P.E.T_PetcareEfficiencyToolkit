"""
Supplier Repository for the PET Application.
Handles CRUD operations for suppliers table.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_suppliers(text=None):
    """Retrieves all suppliers, optionally filtered by name."""
    db = get_connection()
    query = QSqlQuery(db)
    
    if text:
        query.prepare("SELECT supplier_id, supplier_name FROM suppliers WHERE supplier_name LIKE ? ORDER BY supplier_name ASC")
        query.addBindValue(f"%{text}%")
    else:
        query.exec("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name ASC")
    
    results = []
    if query.exec() if text else query:
        while query.next():
            results.append({
                "supplier_id": query.value(0),
                "supplier_name": query.value(1)
            })
    return results


def add_supplier(name):
    """Adds a new supplier."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT INTO suppliers (supplier_name) VALUES (?)")
    query.addBindValue(name.strip())
    if not query.exec():
        logger.error(f"Failed to add supplier '{name}': {query.lastError().text()}")
        return None
    return query.lastInsertId()


def update_supplier(supplier_id, name):
    """Updates a supplier's name."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE suppliers SET supplier_name = ? WHERE supplier_id = ?")
    query.addBindValue(name.strip())
    query.addBindValue(supplier_id)
    return query.exec()


def delete_supplier(supplier_id):
    """Deletes a supplier by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM suppliers WHERE supplier_id = ?")
    query.addBindValue(supplier_id)
    return query.exec()
