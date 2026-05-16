"""
Appointment Repository for the PET Application.
Handles scheduling, retrieval, and management of clinic appointments.
Uses the new schema: appointments linked to pets, with status history.
"""

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.status_resolver import resolve_status
from src.utils.i18n import tr

# The "Late" window and every other derived-status rule live in
# src/core/status_resolver.py (driven by the auto_cancel_after_hours setting).


def add_appointment(appointment_date, service, status, notes, client_id, pet_id,
                    doctor_id=None, user_id=None):
    """Schedules a new appointment for an owner's pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO appointments (pet_id, doctor_id, appointment_date, service, status, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(pet_id)
    query.addBindValue(doctor_id)
    query.addBindValue(appointment_date)
    query.addBindValue(service)
    query.addBindValue(status)
    query.addBindValue(notes)
    if not query.exec():
        return False

    # Log status history
    appointment_id = query.lastInsertId()
    sh = QSqlQuery(db)
    sh.prepare("""
        INSERT INTO appointment_status_history (appointment_id, user_id, status)
        VALUES (?, ?, ?)
    """)
    sh.addBindValue(appointment_id)
    sh.addBindValue(user_id)
    sh.addBindValue(status)
    sh.exec()
    if user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("ADD", "appointments", appointment_id,
                      changes=[{"field_name": "service", "old_value": "", "new_value": service or ""}],
                      user_id=user_id)
    return True


def find_appointment_id(client_id, pet_id, appointment_date):
    """Finds an appointment for an owner's pet at the same minute, or None.

    Used by the spreadsheet importer so a re-imported appointment is skipped
    instead of scheduled again. Minute precision keeps two appointments that
    share a day but differ in time distinct.
    """
    if client_id is None or pet_id is None or not appointment_date:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT a.appointment_id
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        WHERE p.owner_id = ? AND a.pet_id = ?
          AND strftime('%Y-%m-%d %H:%M', a.appointment_date)
              = strftime('%Y-%m-%d %H:%M', ?)
        ORDER BY a.appointment_id ASC LIMIT 1
    """)
    query.addBindValue(client_id)
    query.addBindValue(pet_id)
    query.addBindValue(appointment_date)
    if query.exec() and query.next():
        return query.value(0)
    return None


def update_appointment(appointment_id, appointment_date, service, status, notes, client_id, pet_id,
                       doctor_id=None, user_id=None):
    """Updates an existing appointment."""
    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT appointment_date, service, status, notes
        FROM appointments WHERE appointment_id = ?
    """)
    oq.addBindValue(appointment_id)
    if oq.exec() and oq.next():
        old_row = {
            "appointment_date": oq.value(0) or "",
            "service": oq.value(1) or "",
            "status": oq.value(2) or "",
            "notes": oq.value(3) or "",
        }

    query = QSqlQuery(db)
    query.prepare("""
        UPDATE appointments SET appointment_date = ?, doctor_id = COALESCE(?, doctor_id),
            service = ?, status = ?, notes = ?
        WHERE appointment_id = ?
    """)
    query.addBindValue(appointment_date)
    query.addBindValue(doctor_id)
    query.addBindValue(service)
    query.addBindValue(status)
    query.addBindValue(notes)
    query.addBindValue(appointment_id)

    if query.exec():
        # Log status change if status changed
        sh = QSqlQuery(db)
        sh.prepare("""
            INSERT INTO appointment_status_history (appointment_id, user_id, status)
            VALUES (?, ?, ?)
        """)
        sh.addBindValue(appointment_id)
        sh.addBindValue(user_id)
        sh.addBindValue(status)
        sh.exec()
        if user_id is not None:
            from src.core.repositories.audit_repo import record_action, field_diffs
            record_action("UPDATE", "appointments", appointment_id,
                          changes=field_diffs(old_row, {
                              "appointment_date": appointment_date or "",
                              "service": service or "",
                              "status": status or "",
                              "notes": notes or "",
                          }) or None,
                          user_id=user_id)
        return True
    return False


def update_appointment_status(appointment_id, status, user_id=None):
    """Updates only the status field of an appointment and logs the change."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE appointments SET status = ? WHERE appointment_id = ?")
    query.addBindValue(status)
    query.addBindValue(appointment_id)
    if not query.exec():
        return False

    sh = QSqlQuery(db)
    sh.prepare("""
        INSERT INTO appointment_status_history (appointment_id, user_id, status)
        VALUES (?, ?, ?)
    """)
    sh.addBindValue(appointment_id)
    sh.addBindValue(user_id)
    sh.addBindValue(status)
    sh.exec()
    return True


def get_appointments(text=None, filter_field="All", doctor_id=None):
    """Retrieves scheduled appointments and standalone follow-up rows.

    Appointments are returned first, then follow-up entries (rows where
    ``row_type == 'followup'``).  The caller can use ``row_type`` to apply
    different visual styling.

    Args:
        text:         Optional search string.
        filter_field: Column to apply *text* against (``"All"`` = multi-column).
        doctor_id:    When supplied only rows belonging to that doctor are
                      returned (strict match on the relevant doctor column).
    """
    # "Late" is derived at read time and never stored, so no SQL LIKE on
    # a.status can ever match it.  An exact "late" search on Status/All is
    # therefore resolved in Python after the rows are derived.
    late_probe = (
        bool(text)
        and str(text).strip().lower() == "late"
        and filter_field in ("All", "Status")
    )
    db = get_connection()

    # ------------------------------------------------------------------
    # Part 1 – scheduled appointments
    # ------------------------------------------------------------------
    appt_query = """
        SELECT a.appointment_id, a.appointment_date,
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name, a.service, a.status, a.notes, p.owner_id, a.pet_id,
               'appointment' AS row_type
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
    """
    appt_mapping = {
        "owner_name":        "o.first_name || ' ' || o.last_name",
        "pet_name":          "p.pet_name",
        "appointment_date":  "a.appointment_date",
        "status":            "a.status",
        "notes":             "a.notes",
        "client_id":         "p.owner_id",
        "service":           "a.service",
    }
    appt_conditions = []
    appt_values = []

    if doctor_id is not None:
        appt_conditions.append("a.doctor_id = ?")
        appt_values.append(doctor_id)

    if text and not late_probe:
        pattern = f"%{text}%"
        if filter_field == "All":
            appt_conditions.append(
                "(a.appointment_date LIKE ? OR "
                "o.first_name || ' ' || o.last_name LIKE ? OR "
                "p.pet_name LIKE ? OR a.status LIKE ? OR a.notes LIKE ?)"
            )
            appt_values.extend([pattern] * 5)
        else:
            clean = filter_field.lower().replace(" ", "_")
            field = appt_mapping.get(clean, "a.appointment_date")
            appt_conditions.append(f"{field} LIKE ?")
            appt_values.append(pattern)

    if appt_conditions:
        appt_query += " WHERE " + " AND ".join(appt_conditions)
    appt_query += " ORDER BY a.appointment_date DESC"

    q1 = QSqlQuery(db)
    q1.prepare(appt_query)
    for v in appt_values:
        q1.addBindValue(v)

    results = []
    if q1.exec():
        while q1.next():
            stored = q1.value(5)
            sched = q1.value(1)
            results.append({
                "appointment_id": q1.value(0),
                "appointment_date": sched,
                "owner_name":      q1.value(2),
                "pet_name":        q1.value(3),
                "service":         q1.value(4) or "",
                "status":          resolve_status(stored, sched),
                "notes":           q1.value(6),
                "client_id":       q1.value(7),
                "pet_id":          q1.value(8),
                "row_type":        "appointment",
            })

    # ------------------------------------------------------------------
    # Part 2 – standalone follow-up rows
    # Each follow-up surfaces as a virtual row: service = "Follow-up",
    # status = the follow-up's state value, date = followup_date.
    # ------------------------------------------------------------------
    fu_query = """
        SELECT f.followup_id,
               f.followup_date,
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name,
               'Follow-up'                        AS service,
               COALESCE(sl.state_value, 'Pending') AS status,
               f.notes,
               p.owner_id,
               v.pet_id,
               'followup'                         AS row_type
        FROM followups f
        JOIN visits v  ON f.visit_id  = v.visit_id
        JOIN pets p    ON v.pet_id    = p.pet_id
        JOIN owners o  ON p.owner_id  = o.owner_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
    """
    fu_mapping = {
        "owner_name":       "o.first_name || ' ' || o.last_name",
        "pet_name":         "p.pet_name",
        "appointment_date": "f.followup_date",
        "status":           "sl.state_value",
        "notes":            "f.notes",
        "client_id":        "p.owner_id",
        "service":          "'Follow-up'",
    }
    fu_conditions = []
    fu_values = []

    if doctor_id is not None:
        # Use the same COALESCE logic as followup_repo so null doctor_id
        # falls back to the parent visit's doctor.
        fu_conditions.append("COALESCE(f.doctor_id, v.doctor_id) = ?")
        fu_values.append(doctor_id)

    if text and not late_probe:
        pattern = f"%{text}%"
        if filter_field == "All":
            fu_conditions.append(
                "(f.followup_date LIKE ? OR "
                "o.first_name || ' ' || o.last_name LIKE ? OR "
                "p.pet_name LIKE ? OR sl.state_value LIKE ? OR f.notes LIKE ?)"
            )
            fu_values.extend([pattern] * 5)
        else:
            clean = filter_field.lower().replace(" ", "_")
            field = fu_mapping.get(clean, "f.followup_date")
            fu_conditions.append(f"{field} LIKE ?")
            fu_values.append(pattern)

    if fu_conditions:
        fu_query += " WHERE " + " AND ".join(fu_conditions)
    fu_query += " ORDER BY f.followup_date DESC"

    q2 = QSqlQuery(db)
    q2.prepare(fu_query)
    for v in fu_values:
        q2.addBindValue(v)

    if q2.exec():
        while q2.next():
            stored = q2.value(5)
            sched = q2.value(1)
            results.append({
                "appointment_id": q2.value(0),   # followup_id re-used for row id
                "appointment_date": sched,
                "owner_name":      q2.value(2),
                "pet_name":        q2.value(3),
                "service":         q2.value(4),
                "status":          resolve_status(stored, sched),
                "notes":           q2.value(6) or "",
                "client_id":       q2.value(7),
                "pet_id":          q2.value(8),
                "row_type":        "followup",
            })

    # Sort combined results by date descending so the table stays chronological.
    results.sort(key=lambda r: r.get("appointment_date") or "", reverse=True)
    if late_probe:
        results = [r for r in results if r.get("status") == "Late"]
    return results


def get_next_appointment_time(doctor_id=None):
    """Retrieves the date/time of the very next item (appointment or follow-up).

    Strictly in the future: an item whose time has arrived is no longer "next",
    so the dashboard widget rolls on to the following client at that moment.
    """
    db = get_connection()
    now_sql = "strftime('%Y-%m-%d %H:%M', 'now', 'localtime')"
    candidates = []

    # Next appointment
    query = QSqlQuery(db)
    sql = f"""
        SELECT appointment_date FROM appointments
        WHERE appointment_date > {now_sql}
          AND status NOT IN ('Completed', 'Canceled')
    """
    params = []
    if doctor_id is not None:
        sql += " AND doctor_id = ?"
        params.append(doctor_id)
    sql += " ORDER BY appointment_date ASC LIMIT 1"
    query.prepare(sql)
    for value in params:
        query.addBindValue(value)
    if query.exec() and query.next():
        candidates.append(query.value(0))

    # Next follow-up (doctor falls back to the parent visit's doctor)
    query = QSqlQuery(db)
    sql = f"""
        SELECT f.followup_date
        FROM followups f
        JOIN visits v ON f.visit_id = v.visit_id
        LEFT JOIN states_lookup sl ON f.state_id = sl.state_id
        WHERE f.followup_date > {now_sql}
          AND COALESCE(sl.state_value, '') NOT IN ('Completed', 'Canceled')
    """
    params = []
    if doctor_id is not None:
        sql += " AND COALESCE(f.doctor_id, v.doctor_id) = ?"
        params.append(doctor_id)
    sql += " ORDER BY f.followup_date ASC LIMIT 1"
    query.prepare(sql)
    for value in params:
        query.addBindValue(value)
    if query.exec() and query.next() and query.value(0) is not None:
        candidates.append(query.value(0))

    if not candidates:
        return tr("No appointments")
    return min(candidates)



def delete_appointment(appointment_id, audit_user_id=None):
    """Deletes an appointment by ID."""
    from src.core.repositories.undo_repo import capture_snapshot, record_deletion
    snapshot = capture_snapshot("appointments", appointment_id)

    db = get_connection()
    old_service = ""
    oq = QSqlQuery(db)
    oq.prepare("SELECT service FROM appointments WHERE appointment_id = ?")
    oq.addBindValue(appointment_id)
    if oq.exec() and oq.next():
        old_service = oq.value(0) or ""
    query = QSqlQuery(db)
    query.prepare("DELETE FROM appointments WHERE appointment_id = ?")
    query.addBindValue(appointment_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "appointments", appointment_id,
                      changes=[{"field_name": "service", "old_value": old_service, "new_value": ""}],
                      user_id=audit_user_id)

    if result and snapshot is not None:
        record_deletion("appointments", appointment_id, snapshot, user_id=audit_user_id)
    return result


def _query_appointments_by_time(limit, is_past=False, as_table=False, doctor_id=None):
    """Helper to fetch appointments relative to the current time."""
    db = get_connection()
    query = QSqlQuery(db)
    operator = "<" if is_past else ">="
    ordering = "DESC" if is_past else "ASC"

    sql = f"""
        SELECT a.appointment_date, a.service, a.status,
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        WHERE a.appointment_date {operator} strftime('%Y-%m-%d %H:%M', 'now', 'localtime')
    """
    params = []
    if doctor_id is not None:
        sql += " AND a.doctor_id = ?"
        params.append(doctor_id)
    sql += f" ORDER BY a.appointment_date {ordering} LIMIT ?"
    params.append(limit)

    query.prepare(sql)
    for value in params:
        query.addBindValue(value)

    results = []
    if query.exec():
        while query.next():
            date_val = query.value(0)
            service_val = query.value(1) or "Appointment"
            stored = query.value(2)
            status_val = resolve_status(stored, date_val)
            owner_val = query.value(3) or ""
            pet_val = query.value(4) or ""
            val = (date_val, service_val, status_val, owner_val, pet_val)
            if not as_table:
                val = {
                    "appointment_date": date_val,
                    "service": service_val,
                    "status": status_val,
                    "owner_name": owner_val,
                    "pet_name": pet_val,
                }
            results.append(val)
    return results


def get_completed_appointments(limit=1, as_table=False, doctor_id=None):
    """Retrieves the most recently completed appointments (any scheduled date)."""
    db = get_connection()
    query = QSqlQuery(db)

    sql = """
        SELECT a.appointment_date, a.service, a.status,
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        WHERE a.status = 'Completed'
    """
    params = []
    if doctor_id is not None:
        sql += " AND a.doctor_id = ?"
        params.append(doctor_id)
    sql += " ORDER BY a.appointment_date DESC LIMIT ?"
    params.append(limit)

    query.prepare(sql)
    for value in params:
        query.addBindValue(value)

    results = []
    if query.exec():
        while query.next():
            date_val = query.value(0)
            service_val = query.value(1) or "Appointment"
            stored = query.value(2)
            status_val = resolve_status(stored, date_val)
            owner_val = query.value(3) or ""
            pet_val = query.value(4) or ""
            val = (date_val, service_val, status_val, owner_val, pet_val)
            if not as_table:
                val = {
                    "appointment_date": date_val,
                    "service": service_val,
                    "status": status_val,
                    "owner_name": owner_val,
                    "pet_name": pet_val,
                }
            results.append(val)
    return results


def get_past_appointments(limit=1, as_table=False, doctor_id=None):
    """Retrieves the most recent past appointments."""
    return _query_appointments_by_time(limit, is_past=True, as_table=as_table, doctor_id=doctor_id)


def get_next_appointments(limit=2, as_table=False, doctor_id=None):
    """Retrieves the upcoming appointments."""
    return _query_appointments_by_time(limit, is_past=False, as_table=as_table, doctor_id=doctor_id)


def get_appointments_for_export():
    """Returns every appointment joined to its owner/pet, in template columns.

    ``status`` is the raw stored value (Pending/Completed/Canceled), never the
    date-derived "Late", so the row re-imports to the state it was saved with.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT a.appointment_date,
               CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               p.pet_name,
               COALESCE(a.service, '') AS service,
               COALESCE(a.status, 'Pending') AS status,
               COALESCE(a.notes, '') AS notes
        FROM appointments a
        JOIN pets p ON a.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN entity_contacts ec
               ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY a.appointment_date ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "appointment_date": query.value(0) or "",
                "owner_name": query.value(1) or "",
                "phone_number": query.value(2) or "",
                "pet_name": query.value(3) or "",
                "service": query.value(4) or "",
                "status": query.value(5) or "Pending",
                "notes": query.value(6) or "",
            })
    return results

