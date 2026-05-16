"""
Appointment Repository for the PET Application.
Handles scheduling, retrieval, and management of clinic appointments.
Uses the new schema: appointments linked to pets, with status history.
"""

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.utils.i18n import tr


def add_appointment(appointment_date, service, status, notes, client_id, pet_id):
    """Schedules a new appointment for an owner's pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO appointments (pet_id, appointment_date, status, notes)
        VALUES (?, ?, ?, ?)
    """)
    query.addBindValue(pet_id)
    query.addBindValue(appointment_date)
    query.addBindValue(status)
    query.addBindValue(notes)
    if not query.exec():
        return False

    # Log status history
    appointment_id = query.lastInsertId()
    sh = QSqlQuery(db)
    sh.prepare("""
        INSERT INTO appointment_status_history (appointment_id, status)
        VALUES (?, ?)
    """)
    sh.addBindValue(appointment_id)
    sh.addBindValue(status)
    sh.exec()
    return True


def update_appointment(appointment_id, appointment_date, service, status, notes, client_id, pet_id):
    """Updates an existing appointment."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE appointments SET appointment_date = ?, status = ?, notes = ?
        WHERE appointment_id = ?
    """)
    query.addBindValue(appointment_date)
    query.addBindValue(status)
    query.addBindValue(notes)
    query.addBindValue(appointment_id)

    if query.exec():
        # Log status change if status changed
        sh = QSqlQuery(db)
        sh.prepare("""
            INSERT INTO appointment_status_history (appointment_id, status)
            VALUES (?, ?)
        """)
        sh.addBindValue(appointment_id)
        sh.addBindValue(status)
        sh.exec()
        return True
    return False


def get_appointments(text=None, filter_field="All"):
    """Retrieves appointments, optionally filtered."""
    db = get_connection()
    base_query = """
        SELECT a.appointment_id, a.appointment_date,
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name, a.status, a.notes, p.owner_id, a.pet_id
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
    """
    mapping = {
        "owner_name": "o.first_name || ' ' || o.last_name",
        "pet_name": "p.pet_name",
        "appointment_date": "a.appointment_date",
        "status": "a.status",
        "notes": "a.notes",
        "client_id": "p.owner_id",
    }
    conditions = []
    bind_values = []
    if text:
        search_pattern = f"%{text}%"
        if filter_field == "All":
            conditions.append("(a.appointment_date LIKE ? OR o.first_name || ' ' || o.last_name LIKE ? OR p.pet_name LIKE ? OR a.status LIKE ? OR a.notes LIKE ?)")
            bind_values.extend([search_pattern] * 5)
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            field = mapping.get(clean_field, clean_field)
            conditions.append(f"{field} LIKE ?")
            bind_values.append(search_pattern)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY a.appointment_date DESC"

    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "appointment_id": query.value(0),
                "appointment_date": query.value(1),
                "owner_name": query.value(2),
                "pet_name": query.value(3),
                "service": "",
                "status": query.value(4),
                "notes": query.value(5),
                "client_id": query.value(6),
                "pet_id": query.value(7),
            })
    return results


def get_next_appointment_time():
    """Retrieves the date/time of the very next appointment."""
    db = get_connection()
    query = QSqlQuery(db)
    query.exec("""
        SELECT appointment_date FROM appointments
        WHERE appointment_date >= strftime('%Y-%m-%d %H:%M', 'now', 'localtime')
        ORDER BY appointment_date ASC LIMIT 1
    """)
    if query.next():
        return query.value(0)
    return tr("No upcoming appointments")


def delete_appointment(appointment_id):
    """Deletes an appointment by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM appointments WHERE appointment_id = ?")
    query.addBindValue(appointment_id)
    return query.exec()


def _query_appointments_by_time(limit, is_past=False, as_table=False):
    """Helper to fetch appointments relative to the current time."""
    db = get_connection()
    query = QSqlQuery(db)
    operator = "<" if is_past else ">="
    ordering = "DESC" if is_past else "ASC"

    sql = f"""
        SELECT appointment_date, status
        FROM appointments
        WHERE appointment_date {operator} strftime('%Y-%m-%d %H:%M', 'now', 'localtime')
        ORDER BY appointment_date {ordering} LIMIT ?
    """
    query.prepare(sql)
    query.addBindValue(limit)

    results = []
    if query.exec():
        while query.next():
            val = (query.value(0), "Appointment", query.value(1))
            if not as_table:
                val = {"appointment_date": val[0], "service": val[1], "status": val[2]}
            results.append(val)
    return results


def get_past_appointments(limit=1, as_table=False):
    """Retrieves the most recent past appointments."""
    return _query_appointments_by_time(limit, is_past=True, as_table=as_table)


def get_next_appointments(limit=3, as_table=False):
    """Retrieves the upcoming appointments."""
    return _query_appointments_by_time(limit, is_past=False, as_table=as_table)

