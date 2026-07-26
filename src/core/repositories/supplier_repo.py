"""
Supplier Repository for the PET Application.
Handles CRUD operations for suppliers table.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


_SUPPLIER_COLUMNS = "supplier_id, supplier_name, phone, location, notes"


def get_suppliers(text=None):
    """Retrieves all suppliers, optionally filtered by name."""
    db = get_connection()
    query = QSqlQuery(db)
    
    if text:
        query.prepare(f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers WHERE supplier_name LIKE ? ORDER BY supplier_name ASC")
        query.addBindValue(f"%{text}%")
    else:
        query.exec(f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers ORDER BY supplier_name ASC")
    
    results = []
    if query.exec() if text else query:
        while query.next():
            results.append({
                "supplier_id": query.value(0),
                "supplier_name": query.value(1),
                "phone": query.value(2),
                "location": query.value(3),
                "notes": query.value(4),
            })
    return results


def get_supplier(supplier_id):
    """Returns a single supplier (with contact details) or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"SELECT {_SUPPLIER_COLUMNS} FROM suppliers WHERE supplier_id = ?")
    query.addBindValue(supplier_id)
    if query.exec() and query.next():
        return {
            "supplier_id": query.value(0),
            "supplier_name": query.value(1),
            "phone": query.value(2),
            "location": query.value(3),
            "notes": query.value(4),
        }
    return None


def add_supplier(name, phone=None, location=None, notes=None):
    """Adds a new supplier with optional contact details."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "INSERT INTO suppliers (supplier_name, phone, location, notes) "
        "VALUES (?, ?, ?, ?)"
    )
    query.addBindValue(name.strip())
    query.addBindValue(phone)
    query.addBindValue(location)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add supplier '{name}': {query.lastError().text()}")
        return None
    return query.lastInsertId()


def find_supplier_id(name, phone=None, location=None):
    """Returns the supplier_id matching *name*, or None.

    When *phone* / *location* are given the match requires all three fields
    (``COALESCE``-ed, so a NULL and an empty string count as equal); otherwise
    it matches on the name alone (the Supplies sheet / batch flow only have a
    name). Matching is case-insensitive.
    """
    clean = (name or "").strip()
    if not clean:
        return None

    db = get_connection()
    query = QSqlQuery(db)
    if phone is None and location is None:
        query.prepare("SELECT supplier_id FROM suppliers WHERE LOWER(supplier_name) = LOWER(?)")
        query.addBindValue(clean)
    else:
        query.prepare(
            "SELECT supplier_id FROM suppliers "
            "WHERE LOWER(supplier_name) = LOWER(?) "
            "AND COALESCE(phone, '') = COALESCE(?, '') "
            "AND COALESCE(location, '') = COALESCE(?, '')"
        )
        query.addBindValue(clean)
        query.addBindValue(phone or "")
        query.addBindValue(location or "")
    if query.exec() and query.next():
        return int(query.value(0))
    return None


def get_or_create_supplier(name):
    """Resolves a supplier name to its id, creating the supplier when unknown.

    Returns None for a blank name. Matching is case-insensitive so a supplier
    is never duplicated by casing/spacing differences. The Supplies / batch
    flow only carries a name, so this stays name-only dedup.
    """
    clean = (name or "").strip()
    if not clean:
        return None

    existing = find_supplier_id(clean)
    if existing is not None:
        return existing

    return add_supplier(clean)


def update_supplier(supplier_id, name, phone=None, location=None, notes=None):
    """Updates a supplier.

    Contact fields left as ``None`` keep their current value; pass an empty
    string to clear one.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "UPDATE suppliers SET supplier_name = ?, "
        "phone = COALESCE(?, phone), "
        "location = COALESCE(?, location), "
        "notes = COALESCE(?, notes) "
        "WHERE supplier_id = ?"
    )
    query.addBindValue(name.strip())
    query.addBindValue(phone)
    query.addBindValue(location)
    query.addBindValue(notes)
    query.addBindValue(supplier_id)
    return query.exec()


def delete_supplier(supplier_id):
    """Deletes a supplier by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM suppliers WHERE supplier_id = ?")
    query.addBindValue(supplier_id)
    return query.exec()


def get_suppliers_for_export():
    """Returns every supplier in the import-template shape."""
    return [
        {
            "supplier_name": row.get("supplier_name", ""),
            "phone": row.get("phone", ""),
            "location": row.get("location", ""),
            "notes": row.get("notes", ""),
        }
        for row in get_suppliers()
    ]
