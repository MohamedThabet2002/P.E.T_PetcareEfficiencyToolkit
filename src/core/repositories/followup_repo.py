"""
Follow-up Repository for the PET Application.
Handles scheduling and tracking of follow-up visits.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection
from src.core.database.seed_data import FOLLOWUP_STATUS_STATES
from src.core.repositories import lookup_repo
from src.core.status_resolver import resolve_status

logger = logging.getLogger(__name__)

# The "Late" window and every other derived-status rule live in
# src/core/status_resolver.py (driven by the auto_cancel_after_hours setting).


def add_followup(visit_id, followup_date, state_id=None, notes="", doctor_id=None):
    """Schedules a follow-up visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO followups (visit_id, doctor_id, followup_date, state_id, notes)
        VALUES (?, COALESCE(?, (SELECT doctor_id FROM visits WHERE visit_id = ?)), ?, ?, ?)
    """)
    query.addBindValue(visit_id)
    query.addBindValue(doctor_id)
    query.addBindValue(visit_id)
    query.addBindValue(followup_date)
    query.addBindValue(state_id)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add followup for visit {visit_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def find_followup_id(visit_id, followup_date):
    """Finds a follow-up for a visit on a date (day precision), or None.

    Lets the spreadsheet importer treat a re-imported follow-up as a duplicate
    instead of scheduling it again.
    """
    if visit_id is None or not followup_date:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT followup_id FROM followups
        WHERE visit_id = ? AND date(followup_date) = date(?)
        ORDER BY followup_id ASC LIMIT 1
    """)
    query.addBindValue(visit_id)
    query.addBindValue(followup_date)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_followups_for_visit(visit_id):
    """Retrieves all follow-ups scheduled for a specific visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT f.followup_id, f.visit_id, f.doctor_id, f.followup_date, f.state_id, f.notes,
               sl.state_value
        FROM followups f
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE f.visit_id = ?
        ORDER BY f.followup_date ASC
    """)
    query.addBindValue(visit_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "followup_id": query.value(0),
                "visit_id": query.value(1),
                "doctor_id": query.value(2),
                "followup_date": query.value(3),
                "state_id": query.value(4),
                "notes": query.value(5),
                "status": query.value(6),
            })
    return results


def get_followup(followup_id):
    """Returns a single follow-up by id, or None when it does not exist.

    ``status`` is the RAW stored state value, not the date-resolved display
    status (see status_resolver.resolve_status), so an editor can preselect
    exactly the state
    that is stored. A NULL state means "Pending".
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT f.followup_id, f.visit_id, f.doctor_id, f.followup_date,
               f.state_id, f.notes, sl.state_value
        FROM followups f
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE f.followup_id = ?
    """)
    query.addBindValue(followup_id)
    if not (query.exec() and query.next()):
        return None
    return {
        "followup_id": query.value(0),
        "visit_id": query.value(1),
        "doctor_id": query.value(2),
        "followup_date": query.value(3),
        "state_id": query.value(4),
        "notes": query.value(5) or "",
        "status": query.value(6),
    }


def get_upcoming_followups(limit=10, doctor_id=None):
    """Returns upcoming scheduled follow-ups."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"""
        SELECT f.followup_id, f.followup_date, f.notes,
             p.pet_name, o.first_name || ' ' || o.last_name AS owner_name,
             f.doctor_id, sl.state_value
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE date(f.followup_date) >= date('now', 'localtime')
        {"AND COALESCE(f.doctor_id, v.doctor_id) = ?" if doctor_id is not None else ""}
        ORDER BY f.followup_date ASC LIMIT ?
    """)
    if doctor_id is not None:
        query.addBindValue(doctor_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            stored = query.value(6)
            sched = query.value(1)
            results.append({
                "followup_id": query.value(0),
                "followup_date": query.value(1),
                "notes": query.value(2),
                "pet_name": query.value(3),
                "owner_name": query.value(4),
                "doctor_id": query.value(5),
                "status": resolve_status(stored, sched),
            })
    return results


def get_completed_followups(limit=1, doctor_id=None):
    """Returns the most recently completed follow-ups, newest first."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"""
        SELECT f.followup_id, f.followup_date, f.notes,
             p.pet_name, o.first_name || ' ' || o.last_name AS owner_name,
             f.doctor_id, sl.state_value
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE sl.state_value = 'Completed'
        {"AND COALESCE(f.doctor_id, v.doctor_id) = ?" if doctor_id is not None else ""}
        ORDER BY f.followup_date DESC LIMIT ?
    """)
    if doctor_id is not None:
        query.addBindValue(doctor_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            stored = query.value(6)
            sched = query.value(1)
            results.append({
                "followup_id": query.value(0),
                "followup_date": query.value(1),
                "notes": query.value(2),
                "pet_name": query.value(3),
                "owner_name": query.value(4),
                "doctor_id": query.value(5),
                "status": resolve_status(stored, sched),
            })
    return results


def get_past_followups(limit=1, doctor_id=None):
    """Returns the most recent (past) follow-ups, newest first."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(f"""
        SELECT f.followup_id, f.followup_date, f.notes,
             p.pet_name, o.first_name || ' ' || o.last_name AS owner_name,
             f.doctor_id, sl.state_value
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE date(f.followup_date) < date('now', 'localtime')
        {"AND COALESCE(f.doctor_id, v.doctor_id) = ?" if doctor_id is not None else ""}
        ORDER BY f.followup_date DESC LIMIT ?
    """)
    if doctor_id is not None:
        query.addBindValue(doctor_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            stored = query.value(6)
            sched = query.value(1)
            results.append({
                "followup_id": query.value(0),
                "followup_date": query.value(1),
                "notes": query.value(2),
                "pet_name": query.value(3),
                "owner_name": query.value(4),
                "doctor_id": query.value(5),
                "status": resolve_status(stored, sched),
            })
    return results


def update_followup(followup_id, followup_date, state_id, notes, doctor_id=None):
    """Updates a follow-up record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE followups SET followup_date = ?, state_id = ?, notes = ?,
            doctor_id = COALESCE(?, doctor_id)
        WHERE followup_id = ?
    """)
    query.addBindValue(followup_date)
    query.addBindValue(state_id)
    query.addBindValue(notes)
    query.addBindValue(doctor_id)
    query.addBindValue(followup_id)
    return query.exec()


def update_followup_status(followup_id, state_id):
    """Updates only the status (state_id) of a follow-up record.

    ``state_id`` may be None to store no state at all, which every follow-up
    query renders as "Pending" (see resolve_status_state_id).
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE followups SET state_id = ? WHERE followup_id = ?")
    query.addBindValue(state_id)
    query.addBindValue(followup_id)
    return query.exec()


def resolve_status_state_id(status):
    """Maps a display status to its ``followup_status`` state id.

    Returns None both for "Pending" on a database whose lookup has no Pending
    row (storing NULL is correct — every follow-up query COALESCEs a missing
    state to "Pending") and for values that are not stored at all, such as the
    derived "Late", a retired status ("Scheduled"/"Missed") or an unknown
    label. Callers that must tell those apart compare the status itself against
    "Pending".
    """
    if not status or status not in FOLLOWUP_STATUS_STATES:
        return None
    return lookup_repo.get_state_id("followup_status", status)


def delete_followup(followup_id):
    """Deletes a follow-up record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM followups WHERE followup_id = ?")
    query.addBindValue(followup_id)
    return query.exec()


def get_followups_for_export():
    """Returns every follow-up joined to its visit/owner/pet, for export.

    ``status`` is the RAW stored state (never the derived "Late"), so the row
    re-imports to exactly the state it was saved with.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               p.pet_name,
               v.visit_date,
               f.followup_date,
               COALESCE(sl.state_value, 'Pending') AS status,
               COALESCE(f.notes, '') AS notes
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        LEFT JOIN entity_contacts ec
               ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY f.followup_date ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "owner_name": query.value(0) or "",
                "phone_number": query.value(1) or "",
                "pet_name": query.value(2) or "",
                "visit_date": query.value(3) or "",
                "follow_up_date": query.value(4) or "",
                "status": query.value(5) or "Pending",
                "notes": query.value(6) or "",
            })
    return results
