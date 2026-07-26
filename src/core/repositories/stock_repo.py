"""
Stock Repository for the PET Application.
Handles batch-level stock tracking via the stocks table.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_stock_batch(supply_id, supplier_id, purchase_date, quantity, notes=""):
    """Records a new stock batch purchase."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO stocks (supply_id, supplier_id, purchase_date, quantity, notes)
        VALUES (?, ?, ?, ?, ?)
    """)
    query.addBindValue(supply_id)
    query.addBindValue(supplier_id)
    query.addBindValue(purchase_date)
    query.addBindValue(quantity)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add stock batch for supply {supply_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_stock_batches(supply_id):
    """Retrieves all stock batches for a given supply."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT st.batch_id, st.supply_id, st.supplier_id, st.purchase_date,
               st.quantity, st.notes, sp.supplier_name
        FROM stocks st
        LEFT JOIN suppliers sp ON st.supplier_id = sp.supplier_id
        WHERE st.supply_id = ?
        ORDER BY st.purchase_date DESC
    """)
    query.addBindValue(supply_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "batch_id": query.value(0),
                "supply_id": query.value(1),
                "supplier_id": query.value(2),
                "purchase_date": query.value(3),
                "quantity": query.value(4),
                "notes": query.value(5),
                "supplier_name": query.value(6),
            })
    return results


def update_stock_batch(batch_id, supplier_id, purchase_date, quantity, notes=""):
    """Updates an existing stock batch record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE stocks SET supplier_id = ?, purchase_date = ?, quantity = ?, notes = ?
        WHERE batch_id = ?
    """)
    query.addBindValue(supplier_id)
    query.addBindValue(purchase_date)
    query.addBindValue(quantity)
    query.addBindValue(notes)
    query.addBindValue(batch_id)
    return query.exec()


def delete_stock_batch(batch_id):
    """Deletes a stock batch record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM stocks WHERE batch_id = ?")
    query.addBindValue(batch_id)
    return query.exec()


def get_total_stock_for_supply(supply_id):
    """Sums all batch quantities for a given supply."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT COALESCE(SUM(quantity), 0) FROM stocks WHERE supply_id = ?")
    query.addBindValue(supply_id)
    if query.exec() and query.next():
        return query.value(0)
    return 0
