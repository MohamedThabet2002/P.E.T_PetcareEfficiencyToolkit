"""
Pet Repository for the PET Application.
Handles the persistence and retrieval of animal medical records.
Uses the new schema: pets linked to owners, species_lookup, breeds_lookup.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)

def add_pet(pet_name, species, breed, gender, age_months, weight, client_id):
    """Adds a new pet associated with an owner.
    
    Uses the new schema: resolves species/breed names to IDs.
    """
    db = get_connection()
    
    # Resolve species name to ID
    species_id = _resolve_species_id(db, species)
    breed_id = _resolve_breed_id(db, species_id, breed) if species_id and breed else None
    
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO pets (owner_id, pet_name, species_id, breed_id, gender, age_in_months, weight_in_kg)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(client_id)
    query.addBindValue(pet_name)
    query.addBindValue(species_id)
    query.addBindValue(breed_id)
    query.addBindValue(gender)
    query.addBindValue(age_months)
    query.addBindValue(weight)
    
    if not query.exec():
        logger.error(f"Failed to add pet '{pet_name}' for owner {client_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()

def _resolve_species_id(db, species_name):
    """Resolve species name to ID, creating if not exists."""
    if not species_name:
        return None
    query = QSqlQuery(db)
    query.prepare("SELECT species_id FROM species_lookup WHERE species_name = ?")
    query.addBindValue(species_name)
    if query.exec() and query.next():
        return query.value(0)
    # Create new species
    query.prepare("INSERT INTO species_lookup (species_name) VALUES (?)")
    query.addBindValue(species_name)
    if query.exec():
        return query.lastInsertId()
    return None

def _resolve_breed_id(db, species_id, breed_name):
    """Resolve breed name to ID for a given species, creating if not exists."""
    if not breed_name or not species_id:
        return None
    query = QSqlQuery(db)
    query.prepare("SELECT breed_id FROM breeds_lookup WHERE species_id = ? AND breed_name = ?")
    query.addBindValue(species_id)
    query.addBindValue(breed_name)
    if query.exec() and query.next():
        return query.value(0)
    query.prepare("INSERT INTO breeds_lookup (species_id, breed_name) VALUES (?, ?)")
    query.addBindValue(species_id)
    query.addBindValue(breed_name)
    if query.exec():
        return query.lastInsertId()
    return None

def get_existing_pet(pet_name, species, breed, gender, client_id):
    """Checks if a pet with identifying details already exists for an owner."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT p.pet_id, p.age_in_months, p.weight_in_kg
        FROM pets p
        WHERE p.pet_name = ? AND p.gender = ? AND p.owner_id = ?
    """)
    query.addBindValue(pet_name)
    query.addBindValue(gender)
    query.addBindValue(client_id)
    
    if query.exec() and query.next():
        return {
            "id": query.value(0),
            "age_months": query.value(1),
            "weight": query.value(2)
        }
    return None

def _parse_pet_results(query):
    """Helper to convert QSqlQuery results into a list of pet dictionaries."""
    results = []
    while query.next():
        results.append({
            "pet_id": query.value(0),
            "pet_name": query.value(1),
            "species": query.value(2) or "",
            "breed": query.value(3) or "",
            "gender": query.value(4) or "",
            "age_months": query.value(5),
            "weight": query.value(6),
            "client_id": query.value(7),
            "owner_name": query.value(8) or "",
        })
    return results

def update_pet_details(pet_id, age_months, weight):
    """Updates age and weight for an existing pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE pets SET age_in_months = ?, weight_in_kg = ? WHERE pet_id = ?")
    query.addBindValue(age_months)
    query.addBindValue(weight)
    query.addBindValue(pet_id)
    return query.exec()

def update_pet(pet_id, pet_name, species, breed, gender, age_months, weight, client_id):
    """Updates all details for an existing pet."""
    db = get_connection()
    species_id = _resolve_species_id(db, species)
    breed_id = _resolve_breed_id(db, species_id, breed) if species_id and breed else None
    
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE pets SET pet_name = ?, species_id = ?, breed_id = ?, gender = ?, 
        age_in_months = ?, weight_in_kg = ?, owner_id = ?
        WHERE pet_id = ?
    """)
    query.addBindValue(pet_name)
    query.addBindValue(species_id)
    query.addBindValue(breed_id)
    query.addBindValue(gender)
    query.addBindValue(age_months)
    query.addBindValue(weight)
    query.addBindValue(client_id)
    query.addBindValue(pet_id)
    return query.exec()

def get_pets(text=None, filter_field="All"):
    """Retrieves a list of pets, optionally filtered by search text."""
    db = get_connection()
    base_query = """
        SELECT p.pet_id, p.pet_name, sl.species_name, bl.breed_name, 
               p.gender, p.age_in_months, p.weight_in_kg, p.owner_id,
               o.first_name || ' ' || o.last_name AS owner_name
        FROM pets p
        LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
        LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
        JOIN owners o ON p.owner_id = o.owner_id
    """
    conditions = []
    bind_count = 0
    
    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append("(p.pet_name LIKE ? OR sl.species_name LIKE ? OR bl.breed_name LIKE ? OR p.gender LIKE ?)")
            bind_count = 4
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "age" or clean_field == "age_months":
                conditions.append("CAST(p.age_in_months AS TEXT) LIKE ?")
            elif clean_field == "weight":
                conditions.append("CAST(p.weight_in_kg AS TEXT) LIKE ?")
            elif clean_field == "species":
                conditions.append("sl.species_name LIKE ?")
            elif clean_field == "breed":
                conditions.append("bl.breed_name LIKE ?")
            else:
                conditions.append(f"p.{clean_field} LIKE ?")
            bind_count = 1
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    
    base_query += " ORDER BY p.pet_name"
    
    query = QSqlQuery(db)
    query.prepare(base_query)
    for _ in range(bind_count):
        query.addBindValue(search_text)
    
    return _parse_pet_results(query) if query.exec() else []

def get_pets_for_client(client_id):
    """Retrieves a list of pets for a specific owner."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT p.pet_id, p.pet_name, sl.species_name, bl.breed_name, 
               p.gender, p.age_in_months, p.weight_in_kg, p.owner_id,
               o.first_name || ' ' || o.last_name AS owner_name
        FROM pets p
        LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
        LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
        JOIN owners o ON p.owner_id = o.owner_id
        WHERE p.owner_id = ?
        ORDER BY p.pet_name
    """)
    query.addBindValue(client_id)
    return _parse_pet_results(query) if query.exec() else []

def delete_pet(pet_id):
    """Removes a pet from the database by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM pets WHERE pet_id = ?")
    query.addBindValue(pet_id)
    return query.exec()

def get_unique_breeds():
    """Returns a distinct list of all breeds in the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.exec("SELECT DISTINCT breed_name FROM breeds_lookup WHERE breed_name IS NOT NULL ORDER BY breed_name ASC")
    results = []
    while query.next():
        results.append(query.value(0))
    return results

