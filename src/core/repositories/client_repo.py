"""
Client Repository for the PET Application.
Handles the persistence and retrieval of pet owners (clients).
Uses the new schema: owners (first_name, last_name, phone_number, etc.) and contacts.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_client(owner_name, phone_number=""):
    """Adds a new pet owner to the database.
    
    The new schema splits name into first_name and last_name.
    If the name contains a space, the first word becomes first_name
    and the rest becomes last_name.
    """
    parts = owner_name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO owners (first_name, last_name, phone_number)
        VALUES (?, ?, ?)
    """)
    query.addBindValue(first_name)
    query.addBindValue(last_name)
    query.addBindValue(phone_number)
    
    if not query.exec():
        logger.error(f"Failed to add owner '{owner_name}': {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_clients(text=None, filter_field="All"):
    """Retrieves a list of owners with their contact info, optionally filtered."""
    db = get_connection()
    
    # Build the base query with coalesced phone number
    base_query = """
        SELECT o.owner_id, 
               o.first_name || ' ' || o.last_name AS owner_name,
               o.phone_number
        FROM owners o
    """
    conditions, bind_values = [], []
    
    if text:
        search_text = f"%{text}%"
        searchable_fields = [
            "o.first_name || ' ' || o.last_name",
            "o.phone_number"
        ]
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
            bind_values.extend([search_text] * len(searchable_fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "owner_name":
                conditions.append("(o.first_name || ' ' || o.last_name) LIKE ?")
            else:
                conditions.append(f"o.{clean_field} LIKE ?")
            bind_values.append(search_text)
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    
    base_query += " ORDER BY o.first_name ASC"
    
    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)
    
    results = []
    if query.exec():
        while query.next():
            results.append({
                "client_id": query.value(0),
                "owner_name": query.value(1),
                "phone_number": query.value(2) or ""
            })
    return results


def get_clients_by_name_exact(name):
    """Searches for owners by exact full name."""
    db = get_connection()
    
    parts = name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    
    query = QSqlQuery(db)
    query.prepare("""
        SELECT o.owner_id, o.first_name || ' ' || o.last_name AS owner_name, o.phone_number
        FROM owners o
        WHERE LOWER(o.first_name) = LOWER(?) AND LOWER(o.last_name) = LOWER(?)
    """)
    query.addBindValue(first_name)
    query.addBindValue(last_name)
    
    results = []
    if query.exec():
        while query.next():
            results.append({
                "client_id": query.value(0),
                "owner_name": query.value(1),
                "phone_number": query.value(2) or ""
            })
    return results


def update_client(client_id, owner_name, phone_number):
    """Updates an owner's information."""
    parts = owner_name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE owners SET first_name = ?, last_name = ?, phone_number = ?
        WHERE owner_id = ?
    """)
    query.addBindValue(first_name)
    query.addBindValue(last_name)
    query.addBindValue(phone_number)
    query.addBindValue(client_id)
    return query.exec()


def delete_client(client_id):
    """Removes an owner from the database by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM owners WHERE owner_id = ?")
    query.addBindValue(client_id)
    return query.exec()

