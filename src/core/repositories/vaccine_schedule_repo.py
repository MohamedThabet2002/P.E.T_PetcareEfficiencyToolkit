"""
Vaccine Schedule Repository for the PET Application.
Manages vaccination schedules per species and generates reminders for due vaccinations.
"""

import logging
from datetime import datetime, timedelta
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def add_schedule(vaccine_id, species_id, interval_days, notes=""):
    """Adds a vaccination schedule for a vaccine+species combination."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO vaccine_schedules (vaccine_id, species_id, interval_days, notes)
        VALUES (?, ?, ?, ?)
    """)
    query.addBindValue(vaccine_id)
    query.addBindValue(species_id)
    query.addBindValue(interval_days)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add vaccine schedule: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_all_schedules():
    """Retrieves all vaccine schedules with vaccine and species names."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT vs.schedule_id, vs.vaccine_id, vl.vaccine_name,
               vs.species_id, sl.species_name, vs.interval_days, vs.notes
        FROM vaccine_schedules vs
        LEFT JOIN vaccines_lookup vl ON vs.vaccine_id = vl.vaccine_id
        LEFT JOIN species_lookup sl ON vs.species_id = sl.species_id
        ORDER BY sl.species_name, vl.vaccine_name
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "schedule_id": query.value(0),
                "vaccine_id": query.value(1),
                "vaccine_name": query.value(2),
                "species_id": query.value(3),
                "species_name": query.value(4),
                "interval_days": query.value(5),
                "notes": query.value(6),
            })
    return results


def get_schedules_for_species(species_id):
    """Retrieves vaccination schedules for a specific species."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT vs.schedule_id, vs.vaccine_id, vl.vaccine_name,
               vs.interval_days, vs.notes
        FROM vaccine_schedules vs
        LEFT JOIN vaccines_lookup vl ON vs.vaccine_id = vl.vaccine_id
        WHERE vs.species_id = ?
        ORDER BY vl.vaccine_name
    """)
    query.addBindValue(species_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "schedule_id": query.value(0),
                "vaccine_id": query.value(1),
                "vaccine_name": query.value(2),
                "interval_days": query.value(3),
                "notes": query.value(4),
            })
    return results


def update_schedule(schedule_id, interval_days, notes=""):
    """Updates an existing vaccination schedule."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE vaccine_schedules SET interval_days = ?, notes = ?
        WHERE schedule_id = ?
    """)
    query.addBindValue(interval_days)
    query.addBindValue(notes)
    query.addBindValue(schedule_id)
    return query.exec()


def delete_schedule(schedule_id):
    """Deletes a vaccination schedule."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM vaccine_schedules WHERE schedule_id = ?")
    query.addBindValue(schedule_id)
    return query.exec()


def generate_reminders_for_pet(pet_id):
    """Generates vaccination reminders for a pet based on schedules and past vaccinations."""
    db = get_connection()

    pet_q = QSqlQuery(db)
    pet_q.prepare("SELECT species_id FROM pets WHERE pet_id = ?")
    pet_q.addBindValue(pet_id)
    if not (pet_q.exec() and pet_q.next()):
        return 0
    species_id = pet_q.value(0)
    if not species_id:
        return 0

    sched_q = QSqlQuery(db)
    sched_q.prepare("""
        SELECT vs.vaccine_id, vs.interval_days
        FROM vaccine_schedules vs
        WHERE vs.species_id = ?
    """)
    sched_q.addBindValue(species_id)
    schedules = []
    if sched_q.exec():
        while sched_q.next():
            schedules.append((sched_q.value(0), sched_q.value(1)))

    created = 0
    today = datetime.now().date()
    for vaccine_id, interval_days in schedules:
        last_q = QSqlQuery(db)
        last_q.prepare("""
            SELECT MAX(v.visit_date) FROM vaccinations v
            JOIN visits vis ON v.visit_id = vis.visit_id
            WHERE vis.pet_id = ? AND v.vaccine_id = ?
        """)
        last_q.addBindValue(pet_id)
        last_q.addBindValue(vaccine_id)

        last_date = None
        if last_q.exec() and last_q.next():
            raw = last_q.value(0)
            if raw:
                try:
                    last_date = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

        if last_date:
            due = last_date + timedelta(days=interval_days)
        else:
            due = today

        if due <= today + timedelta(days=90):
            exists_q = QSqlQuery(db)
            exists_q.prepare("""
                SELECT reminder_id FROM vaccination_reminders
                WHERE pet_id = ? AND vaccine_id = ? AND status = 'pending'
                AND due_date >= ?
            """)
            exists_q.addBindValue(pet_id)
            exists_q.addBindValue(vaccine_id)
            exists_q.addBindValue((today - timedelta(days=7)).isoformat())
            if exists_q.exec() and exists_q.next():
                continue

            iq = QSqlQuery(db)
            iq.prepare("""
                INSERT INTO vaccination_reminders (pet_id, vaccine_id, due_date, status)
                VALUES (?, ?, ?, 'pending')
            """)
            iq.addBindValue(pet_id)
            iq.addBindValue(vaccine_id)
            iq.addBindValue(due.isoformat())
            if iq.exec():
                created += 1

    return created


def get_due_reminders(limit=20, include_completed=False):
    """Returns upcoming or overdue vaccination reminders."""
    db = get_connection()
    query = QSqlQuery(db)
    status_filter = "" if include_completed else "AND vr.status = 'pending'"
    query.prepare(f"""
        SELECT vr.reminder_id, vr.pet_id, p.pet_name,
               vr.vaccine_id, vl.vaccine_name,
               o.first_name || ' ' || o.last_name AS owner_name,
               vr.due_date, vr.status, vr.notes
        FROM vaccination_reminders vr
        JOIN pets p ON vr.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN vaccines_lookup vl ON vr.vaccine_id = vl.vaccine_id
        WHERE 1=1 {status_filter}
        ORDER BY vr.due_date ASC
        LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "reminder_id": query.value(0),
                "pet_id": query.value(1),
                "pet_name": query.value(2),
                "vaccine_id": query.value(3),
                "vaccine_name": query.value(4),
                "owner_name": query.value(5),
                "due_date": query.value(6),
                "status": query.value(7),
                "notes": query.value(8),
            })
    return results


def complete_reminder(reminder_id):
    """Marks a vaccination reminder as completed."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE vaccination_reminders SET status = 'completed' WHERE reminder_id = ?")
    query.addBindValue(reminder_id)
    return query.exec()


def skip_reminder(reminder_id):
    """Marks a vaccination reminder as skipped."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE vaccination_reminders SET status = 'skipped' WHERE reminder_id = ?")
    query.addBindValue(reminder_id)
    return query.exec()


def delete_reminder(reminder_id):
    """Deletes a vaccination reminder."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM vaccination_reminders WHERE reminder_id = ?")
    query.addBindValue(reminder_id)
    return query.exec()


def get_all_pets_with_species():
    """Returns all pets with their species_id for reminder generation."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT p.pet_id, p.pet_name, p.species_id
        FROM pets p
        ORDER BY p.pet_name
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "pet_id": query.value(0),
                "pet_name": query.value(1),
                "species_id": query.value(2),
            })
    return results


def generate_reminders_for_all_pets():
    """Generates vaccination reminders for all pets based on schedules."""
    pets = get_all_pets_with_species()
    total = 0
    for pet in pets:
        if pet.get("species_id"):
            total += generate_reminders_for_pet(pet["pet_id"])
    return total
