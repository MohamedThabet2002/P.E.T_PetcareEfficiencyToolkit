"""
Pet Repository for the PET Application.
Handles the persistence and retrieval of animal medical records.
Uses the new schema: pets linked to owners, species_lookup, breeds_lookup.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)

def add_pet(pet_name, species, breed, gender, age_months, weight, client_id, notes=None, audit_user_id=None, **kwargs):
    """Adds a new pet associated with an owner.

    Uses the new schema: resolves species/breed names to IDs.
    ``notes`` is optional and lands in ``pets.notes`` (shown/edited by
    PetInfoDialog). Backward compatible with old signature (audit as last kw).
    """
    # Backward compatibility: if audit_user_id not passed by name but is
    # the 8th positional-equivalent kw? Or handle common case: old called
    # with audit_user_id as keyword at end; if notes is not given and audit_user_id
    # was passed positionally as 7th? But current calls pass audit_user_id by kw.
    if 'audit_user_id' in kwargs and audit_user_id is None:
        audit_user_id = kwargs.pop('audit_user_id')
    if notes is None and 'notes' in kwargs:
        notes = kwargs.pop('notes')

    # If someone passes audit_user_id as a positional-int-like value in notes position? Not common here
    if notes is not None and isinstance(notes, int) and audit_user_id is None:
        audit_user_id = notes
        notes = ""

    db = get_connection()

    # Resolve species name to ID
    species_id = _resolve_species_id(db, species)
    breed_id = _resolve_breed_id(db, species_id, breed) if species_id and breed else None
    clean_notes = (notes or "").strip()

    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO pets (owner_id, pet_name, species_id, breed_id, gender, age_in_months, weight_in_kg, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(client_id)
    query.addBindValue(pet_name)
    query.addBindValue(species_id)
    query.addBindValue(breed_id)
    query.addBindValue(gender)
    query.addBindValue(age_months)
    query.addBindValue(weight)
    query.addBindValue(clean_notes or None)

    if not query.exec():
        logger.error(f"Failed to add pet '{pet_name}' for owner {client_id}: {query.lastError().text()}")
        return None
    pet_id = query.lastInsertId()
    if audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        changes = [{"field_name": "pet_name", "old_value": "", "new_value": pet_name or ""}]
        if clean_notes:
            changes.append({"field_name": "notes", "old_value": "", "new_value": clean_notes})
        record_action("ADD", "pets", pet_id,
                      changes=changes,
                      user_id=audit_user_id)

    return pet_id

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

def update_pet_details(pet_id, age_months, weight, audit_user_id=None):
    """Updates age and weight for an existing pet."""
    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("SELECT age_in_months, weight_in_kg FROM pets WHERE pet_id = ?")
    oq.addBindValue(pet_id)
    if oq.exec() and oq.next():
        old_row = {
            "age_in_months": oq.value(0) or "",
            "weight_in_kg": oq.value(1) or "",
        }
    query = QSqlQuery(db)
    query.prepare("UPDATE pets SET age_in_months = ?, weight_in_kg = ? WHERE pet_id = ?")
    query.addBindValue(age_months)
    query.addBindValue(weight)
    query.addBindValue(pet_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        record_action("UPDATE", "pets", pet_id,
                      changes=field_diffs(old_row, {
                          "age_in_months": age_months,
                          "weight_in_kg": weight,
                      }) or None,
                      user_id=audit_user_id)
    return result

def update_pet(pet_id, pet_name, species, breed, gender, age_months, weight, client_id, audit_user_id=None, notes=None, health_status=None):
    """Updates all details for an existing pet (notes/health_status optional)."""
    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT pet_name, species_id, breed_id, gender, age_in_months, weight_in_kg, owner_id, notes, health_status
        FROM pets WHERE pet_id = ?
    """)
    oq.addBindValue(pet_id)
    if oq.exec() and oq.next():
        old_row = {
            "pet_name": oq.value(0) or "",
            "species_id": oq.value(1) or "",
            "breed_id": oq.value(2) or "",
            "gender": oq.value(3) or "",
            "age_in_months": oq.value(4) or "",
            "weight_in_kg": oq.value(5) or "",
            "owner_id": oq.value(6) or "",
            "notes": oq.value(7) or "",
            "health_status": oq.value(8) or "",
        }

    species_id = _resolve_species_id(db, species)
    breed_id = _resolve_breed_id(db, species_id, breed) if species_id and breed else None

    effective_notes = notes if notes is not None else (old_row.get("notes") or "")
    effective_health = health_status if health_status is not None else (old_row.get("health_status") or "")

    query = QSqlQuery(db)
    query.prepare("""
        UPDATE pets SET pet_name = ?, species_id = ?, breed_id = ?, gender = ?, 
        age_in_months = ?, weight_in_kg = ?, owner_id = ?, notes = ?, health_status = ?
        WHERE pet_id = ?
    """)
    query.addBindValue(pet_name)
    query.addBindValue(species_id)
    query.addBindValue(breed_id)
    query.addBindValue(gender)
    query.addBindValue(age_months)
    query.addBindValue(weight)
    query.addBindValue(client_id)
    query.addBindValue(effective_notes)
    query.addBindValue(effective_health or None)
    query.addBindValue(pet_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        record_action("UPDATE", "pets", pet_id,
                      changes=field_diffs(old_row, {
                          "pet_name": pet_name,
                          "species_id": species_id or "",
                          "breed_id": breed_id or "",
                          "gender": gender or "",
                          "age_in_months": age_months,
                          "weight_in_kg": weight,
                          "owner_id": client_id,
                          "notes": effective_notes,
                          "health_status": effective_health or "",
                      }) or None,
                      user_id=audit_user_id)
    return result

def get_pet_details(pet_id):
    """Returns a pet's full details including owner info and notes.

    Args:
        pet_id: The pet's ID.

    Returns:
        dict with pet_id/pet_name/species/breed/gender/age_months/weight/
        client_id/owner_name/owner_phone/created_at/notes, or None when the
        pet does not exist.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT p.pet_id, p.pet_name, sl.species_name, bl.breed_name,
               p.gender, p.age_in_months, p.weight_in_kg, p.owner_id,
               o.first_name || ' ' || o.last_name AS owner_name,
               c.phone_number,
               p.created_at,
               o.created_at AS owner_created_at,
               p.notes,
               p.health_status
        FROM pets p
        LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
        LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        WHERE p.pet_id = ?
    """)
    query.addBindValue(pet_id)
    if query.exec() and query.next():
        return {
            "pet_id": query.value(0),
            "pet_name": query.value(1),
            "species": query.value(2) or "",
            "breed": query.value(3) or "",
            "gender": query.value(4) or "",
            "age_months": query.value(5),
            "weight": query.value(6),
            "client_id": query.value(7),
            "owner_name": query.value(8) or "",
            "owner_phone": query.value(9) or "",
            "created_at": query.value(10),
            "owner_created_at": query.value(11),
            "notes": query.value(12) or "",
            "health_status": query.value(13) or "",
        }
    return None

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
                bind_count = 1
            elif clean_field == "weight":
                conditions.append("CAST(p.weight_in_kg AS TEXT) LIKE ?")
                bind_count = 1
            elif clean_field == "species":
                conditions.append("sl.species_name LIKE ?")
                bind_count = 1
            elif clean_field == "breed":
                conditions.append("bl.breed_name LIKE ?")
                bind_count = 1
            elif clean_field == "pet_name":
                conditions.append("p.pet_name LIKE ?")
                bind_count = 1
            else:
                conditions.append("(p.pet_name LIKE ? OR sl.species_name LIKE ? OR bl.breed_name LIKE ? OR p.gender LIKE ?)")
                bind_count = 4
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    
    base_query += " ORDER BY p.pet_name"
    
    query = QSqlQuery(db)
    query.prepare(base_query)
    for _ in range(bind_count):
        query.addBindValue(search_text)
    
    return _parse_pet_results(query) if query.exec() else []

def get_pets_for_export():
    """Retrieves every pet with the columns the import template uses.

    The owner phone is joined in (the pet listing has no contact) so the rows
    can be re-imported on their own.

    Returns:
        list[dict]: ``pet_name``, ``owner_name``, ``phone_number``, ``species``,
        ``breed``, ``gender``, ``age_months`` and ``weight`` per pet.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT p.pet_name,
               CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, ''),
               COALESCE(sl.species_name, ''),
               COALESCE(bl.breed_name, ''),
               COALESCE(p.gender, ''),
               p.age_in_months,
               p.weight_in_kg
        FROM pets p
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
        LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY p.pet_name ASC
    """)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "pet_name": query.value(0) or "",
                "owner_name": query.value(1) or "",
                "phone_number": query.value(2) or "",
                "species": query.value(3) or "",
                "breed": query.value(4) or "",
                "gender": query.value(5) or "",
                "age_months": query.value(6),
                "weight": query.value(7),
            })
    return results


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



def get_pets_by_name_for_client(client_id, pet_name):
    """Finds pets by name for a specific owner (case-insensitive)."""
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
        WHERE p.owner_id = ? AND LOWER(TRIM(p.pet_name)) = LOWER(TRIM(?))
        ORDER BY p.pet_id
    """)
    query.addBindValue(client_id)
    query.addBindValue(pet_name or "")
    return _parse_pet_results(query) if query.exec() else []

def delete_pet(pet_id, audit_user_id=None):
    """Removes a pet from the database by ID."""
    from src.core.repositories.undo_repo import capture_snapshot, record_deletion
    snapshot = capture_snapshot("pets", pet_id)

    db = get_connection()
    old_name = ""
    oq = QSqlQuery(db)
    oq.prepare("SELECT pet_name FROM pets WHERE pet_id = ?")
    oq.addBindValue(pet_id)
    if oq.exec() and oq.next():
        old_name = oq.value(0) or ""
    query = QSqlQuery(db)
    query.prepare("DELETE FROM pets WHERE pet_id = ?")
    query.addBindValue(pet_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "pets", pet_id,
                      changes=[{"field_name": "pet_name", "old_value": old_name, "new_value": ""}],
                      user_id=audit_user_id)

    if result and snapshot is not None:
        record_deletion("pets", pet_id, snapshot, user_id=audit_user_id)
    return result

def get_unique_breeds():
    """Returns a distinct list of all breeds in the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.exec("SELECT DISTINCT breed_name FROM breeds_lookup WHERE breed_name IS NOT NULL ORDER BY breed_name ASC")
    results = []
    while query.next():
        results.append(query.value(0))
    return results

