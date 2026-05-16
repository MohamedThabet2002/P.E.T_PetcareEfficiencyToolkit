"""
Client Repository for the PET Application.
Handles the persistence and retrieval of pet owners (clients).
Uses the new schema: owners (first_name, last_name) and contacts/entity_contacts
for phone numbers and other contact info.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

logger = logging.getLogger(__name__)


def _insert_contact(db, owner_id, phone_number):
    """Helper to insert a phone contact for an owner."""
    phone_number = (phone_number or "").strip()
    if not phone_number:
        return None

    cq = QSqlQuery(db)
    cq.prepare("INSERT INTO contacts (phone_number) VALUES (?)")
    cq.addBindValue(phone_number)
    if not cq.exec():
        logger.error(f"Failed to insert contact: {cq.lastError().text()}")
        return None
    contact_id = cq.lastInsertId()

    eq = QSqlQuery(db)
    eq.prepare("""
        INSERT INTO entity_contacts (entity_type, entity_id, contact_id)
        VALUES ('owner', ?, ?)
    """)
    eq.addBindValue(owner_id)
    eq.addBindValue(contact_id)
    if not eq.exec():
        logger.error(f"Failed to link contact: {eq.lastError().text()}")
        return None
    return contact_id


def add_client(owner_name, phone_number="", *args, notes=None, audit_user_id=None, **kwargs):
    """Adds a new pet owner to the database.

    The new schema splits name into first_name and last_name.
    If the name contains a space, the first word becomes first_name
    and the rest becomes last_name. Phone is stored via contacts tables.
    ``notes`` is optional and lands in ``owners.notes`` (shown/edited by
    OwnerInfoDialog).

    Backward compatible: supports old positional forms where the third
    positional argument was ``audit_user_id`` (int). Also accepts keyword
    arguments for ``notes``/``audit_user_id``.
    """
    # Backward-compat: detect if third positional arg is an audit user id
    # (int) rather than notes (str). Old signature: (name, phone="", audit_user_id=None)
    if len(args) >= 1:
        candidate = args[0]
        if audit_user_id is None and isinstance(candidate, int):
            audit_user_id = candidate
            # Any remaining positional args are ignored
            args = args[1:]
        else:
            # Treat first positional as notes if it's a string (or not int)
            if notes is None:
                notes = candidate if isinstance(candidate, str) else str(candidate) if candidate is not None else ""
            args = args[1:]

    # Also check kwargs for audit_user_id/notes if passed positionally oddly
    if 'audit_user_id' in kwargs and audit_user_id is None:
        audit_user_id = kwargs.pop('audit_user_id')
    if 'notes' in kwargs and notes is None:
        notes = kwargs.pop('notes')

    parts = owner_name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    clean_notes = (notes or "").strip()

    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO owners (first_name, last_name, notes)
        VALUES (?, ?, ?)
    """)
    query.addBindValue(first_name)
    query.addBindValue(last_name)
    query.addBindValue(clean_notes or None)

    if not query.exec():
        logger.error(f"Failed to add owner '{owner_name}': {query.lastError().text()}")
        return None
    owner_id = query.lastInsertId()

    if phone_number:
        _insert_contact(db, owner_id, phone_number)

    if audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        changes = [
            {"field_name": "owner_name", "old_value": "", "new_value": owner_name.strip()},
            {"field_name": "phone_number", "old_value": "", "new_value": (phone_number or "").strip()},
        ]
        if clean_notes:
            changes.append({"field_name": "notes", "old_value": "", "new_value": clean_notes})
        record_action("ADD", "owners", owner_id,
                      changes=changes,
                      user_id=audit_user_id)

    return owner_id


def get_clients(text=None, filter_field="All"):
    """Retrieves a list of owners with their contact info, optionally filtered."""
    db = get_connection()

    # Build the base query with coalesced phone number from contacts
    base_query = """
        SELECT o.owner_id,
               CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               c.phone_number
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
    """
    conditions, bind_values = [], []

    if text:
        search_text = f"%{text}%"
        searchable_fields = [
            "o.first_name || ' ' || o.last_name",
            "c.phone_number"
        ]
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
            bind_values.extend([search_text] * len(searchable_fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "owner_name":
                conditions.append("(o.first_name || ' ' || o.last_name) LIKE ?")
                bind_values.append(search_text)
            elif clean_field == "phone_number":
                conditions.append("c.phone_number LIKE ?")
                bind_values.append(search_text)
            else:
                conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
                bind_values.extend([search_text] * len(searchable_fields))

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


def get_owner_details(client_id):
    """Returns a single owner's full details (contact, notes, member-since date).

    Args:
        client_id: The owner's ID.

    Returns:
        dict with client_id/owner_name/first_name/last_name/phone_number/notes/
        created_at, or None when the owner does not exist.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT o.owner_id,
               CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               o.first_name,
               o.last_name,
               o.notes,
               o.created_at,
               c.phone_number
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        WHERE o.owner_id = ?
    """)
    query.addBindValue(client_id)
    if query.exec() and query.next():
        return {
            "client_id": query.value(0),
            "owner_name": query.value(1),
            "first_name": query.value(2),
            "last_name": query.value(3),
            "notes": query.value(4),
            "created_at": query.value(5),
            "phone_number": query.value(6) or "",
        }
    return None


def get_client_by_name_and_phone(name, phone_number=""):
    """Searches for an owner by full name and phone number."""
    db = get_connection()
    parts = (name or "").strip().split(" ", 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""
    phone = (phone_number or "").strip()

    query = QSqlQuery(db)
    if phone:
        query.prepare("""
            SELECT o.owner_id,
                   CASE WHEN TRIM(COALESCE(o.last_name, '')) = '' THEN TRIM(o.first_name)
                        ELSE TRIM(o.first_name || ' ' || o.last_name)
                   END AS owner_name,
                   c.phone_number
            FROM owners o
            LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
            LEFT JOIN contacts c ON c.contact_id = ec.contact_id
            WHERE LOWER(o.first_name) = LOWER(?) AND LOWER(TRIM(COALESCE(o.last_name, ''))) = LOWER(?)
              AND LOWER(TRIM(COALESCE(c.phone_number, ''))) = LOWER(TRIM(?))
        """)
        query.addBindValue(first_name)
        query.addBindValue(last_name)
        query.addBindValue(phone)
    else:
        query.prepare("""
            SELECT o.owner_id,
                   CASE WHEN TRIM(COALESCE(o.last_name, '')) = '' THEN TRIM(o.first_name)
                        ELSE TRIM(o.first_name || ' ' || o.last_name)
                   END AS owner_name,
                   c.phone_number
            FROM owners o
            LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
            LEFT JOIN contacts c ON c.contact_id = ec.contact_id
            WHERE LOWER(o.first_name) = LOWER(?) AND LOWER(TRIM(COALESCE(o.last_name, ''))) = LOWER(?)
        """)
        query.addBindValue(first_name)
        query.addBindValue(last_name)

    if query.exec() and query.next():
        return {
            "client_id": query.value(0),
            "owner_name": query.value(1),
            "phone_number": query.value(2) or ""
        }
    return None


def get_clients_by_name_exact(name):

    """Searches for owners by exact full name."""
    db = get_connection()

    parts = name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    query = QSqlQuery(db)
    query.prepare("""
        SELECT o.owner_id,
               CASE WHEN TRIM(COALESCE(o.last_name, '')) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               c.phone_number
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        WHERE LOWER(o.first_name) = LOWER(?) AND LOWER(TRIM(COALESCE(o.last_name, ''))) = LOWER(?)
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


def _update_contact_phone(db, owner_id, phone_number):
    """Update or create the phone contact for an owner."""
    phone_number = (phone_number or "").strip()

    # Find existing contact linked to this owner
    eq = QSqlQuery(db)
    eq.prepare("""
        SELECT c.contact_id FROM contacts c
        JOIN entity_contacts ec ON c.contact_id = ec.contact_id
        WHERE ec.entity_type = 'owner' AND ec.entity_id = ?
    """)
    eq.addBindValue(owner_id)
    contact_id = None
    if eq.exec() and eq.next():
        contact_id = eq.value(0)

    if contact_id:
        if phone_number:
            uq = QSqlQuery(db)
            uq.prepare("UPDATE contacts SET phone_number = ? WHERE contact_id = ?")
            uq.addBindValue(phone_number)
            uq.addBindValue(contact_id)
            uq.exec()
        else:
            # Remove contact link and contact row
            dq = QSqlQuery(db)
            dq.prepare("DELETE FROM entity_contacts WHERE entity_type = 'owner' AND entity_id = ?")
            dq.addBindValue(owner_id)
            dq.exec()
            dc = QSqlQuery(db)
            dc.prepare("DELETE FROM contacts WHERE contact_id = ?")
            dc.addBindValue(contact_id)
            dc.exec()
    else:
        _insert_contact(db, owner_id, phone_number)


def update_client(client_id, owner_name, phone_number, notes=None, audit_user_id=None):
    """Updates an owner's information (name + phone, optionally notes).

    When ``notes`` is ``None`` the existing notes value is left untouched,
    keeping the call compatible with callers that only manage name/phone.
    """
    parts = owner_name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    db = get_connection()

    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT o.first_name, o.last_name, c.phone_number, o.notes
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON c.contact_id = ec.contact_id
        WHERE o.owner_id = ?
    """)
    oq.addBindValue(client_id)
    if oq.exec() and oq.next():
        old_full = " ".join(x for x in (oq.value(0), oq.value(1)) if x)
        old_row = {
            "owner_name": old_full,
            "phone_number": oq.value(2) or "",
        }
        if notes is not None:
            old_row["notes"] = oq.value(3) or ""

    sql = "UPDATE owners SET first_name = ?, last_name = ?"
    bind_values = [first_name, last_name]
    if notes is not None:
        sql += ", notes = ?"
        bind_values.append(notes)
    sql += " WHERE owner_id = ?"
    bind_values.append(client_id)

    query = QSqlQuery(db)
    query.prepare(sql)
    for value in bind_values:
        query.addBindValue(value)
    result = query.exec()

    if result:
        _update_contact_phone(db, client_id, phone_number)
        if audit_user_id is not None:
            from src.core.repositories.audit_repo import record_action, field_diffs
            new_row = {
                "owner_name": owner_name.strip(),
                "phone_number": (phone_number or "").strip(),
            }
            if notes is not None:
                new_row["notes"] = (notes or "").strip()
            record_action("UPDATE", "owners", client_id,
                          changes=field_diffs(old_row, new_row) or None,
                          user_id=audit_user_id)

    return result


def get_owners_for_export():
    """Retrieves every owner with the three columns the import template uses.

    Returns:
        list[dict]: ``owner_name``, ``phone_number`` and ``notes`` per owner.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, ''),
               COALESCE(o.notes, '')
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY o.first_name ASC, o.last_name ASC
    """)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "owner_name": query.value(0) or "",
                "phone_number": query.value(1) or "",
                "notes": query.value(2) or "",
            })
    return results


def delete_client(client_id, audit_user_id=None):
    """Removes an owner from the database by ID.

    Also removes associated entity_contacts links (and their contacts).
    """
    from src.core.repositories.undo_repo import capture_snapshot, record_deletion
    snapshot = capture_snapshot("owners", client_id)

    db = get_connection()

    old_name = ""
    old_phone = ""
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT TRIM(o.first_name || ' ' || o.last_name), c.phone_number
        FROM owners o
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON c.contact_id = ec.contact_id
        WHERE o.owner_id = ?
    """)
    oq.addBindValue(client_id)
    if oq.exec() and oq.next():
        old_name = oq.value(0) or ""
        old_phone = oq.value(1) or ""

    # Remove entity_contacts links for this owner
    eq = QSqlQuery(db)
    eq.prepare("DELETE FROM entity_contacts WHERE entity_type = 'owner' AND entity_id = ?")
    eq.addBindValue(client_id)
    eq.exec()

    query = QSqlQuery(db)
    query.prepare("DELETE FROM owners WHERE owner_id = ?")
    query.addBindValue(client_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "owners", client_id,
                      changes=[
                          {"field_name": "owner_name", "old_value": old_name, "new_value": ""},
                          {"field_name": "phone_number", "old_value": old_phone, "new_value": ""},
                      ],
                      user_id=audit_user_id)

    if result and snapshot is not None:
        record_deletion("owners", client_id, snapshot, user_id=audit_user_id)

    return result





