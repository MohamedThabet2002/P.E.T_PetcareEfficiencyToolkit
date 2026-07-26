"""
Visit Repository for the PET Application.
Handles recording medical visits, processing associated billing/inventory,
and retrieving clinical history.
Uses the new schema: visits linked to pets, with structured receipt tables.
"""

import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.repositories.supply_repo import update_supply_stock
from src.core.repositories import stock_repo

from src.config.constants import DEFAULT_CONSULT_FEE
from src.utils.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


def add_visit(visit_date, diagnosis, consult, notes, pet_id=None, items=None, client_id=None,
              reason_for_visit="", temperature=None,
              health_stats=None, tests=None, treatments=None, vaccinations=None, medications=None,
              doctor_id=None, appointment_id=None, discount=0.0, audit_user_id=None,
              receipt_code=None, packages=None, paid_amount=None, payment_notes="Paid at entry",
              payment_method="Cash", ids_out=None, clinical_exam=None):
    """
    Logs a medical visit using the new schema.
    Handles inventory validation, stock deduction, and automated billing.
    Returns visit_id on success, or an error string/None on failure.

    When the visit is billable, ``receipt_code`` defaults to a freshly
    allocated unique ``VISIT-<YYYYMM>-####`` code: ``receipts.receipt_code`` is
    UNIQUE, so the old hardcoded ``"Sale"`` only ever inserted the first live
    visit's receipt and silently dropped every later one.

    The return value is the receipt id when the visit was billable and the
    visit id otherwise, so a caller that needs both (or must tell them apart)
    passes an ``ids_out`` dict, which receives ``visit_id`` and ``receipt_id``
    (``None`` when nothing was billed) on success.
    """
    db = get_connection()
    db.transaction()
    items = items or []
    receipt_id = None
    _active_queries = []

    # QtSql/SQLite requires every active QSqlQuery to be finished before a
    # transaction can be committed ("SQL statements in progress"). Track all
    # queries created during this transaction so we can finish them atomically.
    
    # Get current consult fee from settings
    consult_fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))
    
    # 1. Validate aggregate stock before committing
    # Stock is keyed on (item_name, category): names are unique per category
    # (see supply_repo.add_supply), so two items may share a name across
    # categories. Summing by name alone could advertise more stock than the
    # single row the sale later draws from.
    planned_usage = {}
    for itm in items:
        n = itm.get('item_name')
        q = itm.get('quantity', 1)
        if n and q > 0:
            key = (n, itm.get('category') or None)
            planned_usage[key] = planned_usage.get(key, 0) + q
    
    for (name, category), total_qty in planned_usage.items():
        check_q = QSqlQuery(db)
        _active_queries.append(check_q)
        check_q.prepare(
            "SELECT SUM(current_stock) FROM supplies "
            "WHERE item_name = ? AND (? IS NULL OR category = ?)")
        check_q.addBindValue(name)
        check_q.addBindValue(category)
        check_q.addBindValue(category)
        if check_q.exec() and check_q.next():
            curr_qty = check_q.value(0) or 0
            if total_qty > curr_qty:
                logger.warning(f"Stock check failed for '{name}': needs {total_qty}, has {curr_qty}")
                db.rollback()
                return f"STOCK_ERROR|{name}|{curr_qty}"
        else:
            logger.error(f"Stock query failed for '{name}': {check_q.lastError().text()}")
            db.rollback()
            return f"STOCK_ERROR|{name}|0"
    
    # 2. Ensure we have valid IDs
    if pet_id is None:
        db.rollback()
        return None
    
    # Get owner_id from pet
    oq = QSqlQuery(db)
    _active_queries.append(oq)
    oq.prepare("SELECT owner_id FROM pets WHERE pet_id = ?")
    oq.addBindValue(pet_id)
    if not (oq.exec() and oq.next()):
        db.rollback()
        return None
    owner_id = oq.value(0)
    
    # 3. Insert Visit Record
    vq = QSqlQuery(db)
    _active_queries.append(vq)
    vq.prepare("""
        INSERT INTO visits (pet_id, doctor_id, appointment_id, visit_date, diagnosis, notes, reason_for_visit, temperature_in_c)
        VALUES (?, COALESCE(?, (SELECT doctor_id FROM appointments WHERE appointment_id = ?)), ?, ?, ?, ?, ?, ?)
    """)
    vq.addBindValue(pet_id)
    vq.addBindValue(doctor_id)
    vq.addBindValue(appointment_id)
    vq.addBindValue(appointment_id)
    vq.addBindValue(visit_date)
    vq.addBindValue(diagnosis)
    vq.addBindValue(notes)
    vq.addBindValue(reason_for_visit)
    vq.addBindValue(temperature)
    if not vq.exec():
        logger.error(f"Failed to insert visit: {vq.lastError().text()}")
        db.rollback()
        return None
    visit_id = vq.lastInsertId()
    
    # 4. Process Billing and Stock Deductions
    billed_items = []
    total_amount = 0.0
    
    for item_data in items:
        name = item_data.get('item_name')
        qty = item_data.get('quantity', 1)
        custom_price = item_data.get('price')
        
        if name and qty > 0:
            iq = QSqlQuery(db)
            _active_queries.append(iq)
            category = item_data.get('category') or None
            iq.prepare("""
                SELECT supply_id, sell_price, current_stock FROM supplies
                WHERE item_name = ? AND (? IS NULL OR category = ?)
                  AND current_stock > 0
                ORDER BY supply_id LIMIT 1
            """)
            iq.addBindValue(name)
            iq.addBindValue(category)
            iq.addBindValue(category)
            if iq.exec() and iq.next():
                supply_id = iq.value(0)
                db_price = iq.value(1)
                curr_qty = iq.value(2)
                
                price_to_charge = custom_price if custom_price is not None else (db_price or 0)
                
                # Deduct stock
                uq = QSqlQuery(db)
                _active_queries.append(uq)
                uq.prepare("UPDATE supplies SET current_stock = current_stock - ? WHERE supply_id = ?")
                uq.addBindValue(qty)
                uq.addBindValue(supply_id)
                uq.exec()

                # Same units leave the stock batches (oldest first), so the
                # batch total on the supplies page tracks the live stock.
                stock_repo.consume_batches(db, supply_id, qty)
                # The stock_movement row is written further down, once the
                # receipt exists - see the "Add Supply Items" loop - so the
                # ledger row can carry both the acting user and the receipt.

                billed_items.append({
                    "supply_id": supply_id,
                    "name": name,
                    "price": price_to_charge,
                    "qty": qty
                })
                total_amount += (price_to_charge * qty)
    
    # 5. Generate Receipt
    packages = packages or []
    packages_total = sum(
        float(pkg.get("total_price") or 0.0) * int(pkg.get("quantity") or 1)
        for pkg in packages
    )
    if billed_items or consult or packages:
        discount = float(discount or 0)
        receipt_total = total_amount + packages_total + (consult_fee if consult else 0)
        receipt_total = max(0.0, receipt_total - discount)
        # What the client hands over at the counter (optional): recorded as an
        # instant payment in the same transaction, so nothing has to be settled
        # later from the Receipts page.
        paid_cash = 0.0
        if paid_amount is not None:
            paid_cash = round(min(max(float(paid_amount), 0.0), receipt_total), 2)
        initial_status = ("Paid" if receipt_total - paid_cash <= 1e-9
                          else "Partial" if paid_cash > 0 else "Unpaid")
        if receipt_code is None:
            # Local import keeps this module free of a hard dependency on
            # sales_repo at import time (avoids any import cycle).
            from src.core.repositories import sales_repo
            receipt_code = sales_repo.next_visit_code(db)
            if not receipt_code:
                logger.error("Could not allocate a unique receipt code for visit %s", visit_id)
                for _q in _active_queries:
                    _q.finish()
                db.rollback()
                return None
        rq = QSqlQuery(db)
        _active_queries.append(rq)
        rq.prepare("""
            INSERT INTO receipts (visit_id, owner_id, receipt_date, total_price, discount,
                                  receipt_code, receipt_kind, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, 'visit', ?)
        """)
        rq.addBindValue(visit_id)
        rq.addBindValue(owner_id)
        rq.addBindValue(visit_date)
        rq.addBindValue(receipt_total)
        rq.addBindValue(discount)
        rq.addBindValue(receipt_code)
        rq.addBindValue(initial_status)
        
        if rq.exec():
            receipt_id = rq.lastInsertId()
            
            # Add Consultation Service
            if consult:
                sq = QSqlQuery(db)
                _active_queries.append(sq)
                sq.prepare("SELECT service_id FROM services_lookup WHERE service_name = 'Consultation'")
                service_id = None
                if sq.exec() and sq.next():
                    service_id = sq.value(0)
                
                rs = QSqlQuery(db)
                _active_queries.append(rs)
                rs.prepare("""
                    INSERT INTO receipt_services (receipt_id, service_id, quantity, unit_price)
                    VALUES (?, ?, 1, ?)
                """)
                rs.addBindValue(receipt_id)
                rs.addBindValue(service_id)
                rs.addBindValue(consult_fee)
                rs.exec()
            
            # Add Supply Items
            for item in billed_items:
                ri = QSqlQuery(db)
                _active_queries.append(ri)
                ri.prepare("""
                    INSERT INTO receipt_supplies (receipt_id, supply_id, quantity, unit_price)
                    VALUES (?, ?, ?, ?)
                """)
                ri.addBindValue(receipt_id)
                ri.addBindValue(item["supply_id"])
                ri.addBindValue(item["qty"])
                ri.addBindValue(item["price"])
                ri.exec()

                # One canonical way to write the ledger: signed quantity, the
                # acting user and a link back to the receipt that moved it.
                stock_repo.record_movement(
                    db, item["supply_id"], "sale", -int(item["qty"]),
                    notes=f"Visit #{visit_id}", user_id=audit_user_id,
                    receipt_id=receipt_id)

            # Add Packages
            for pkg in packages:
                pq = QSqlQuery(db)
                _active_queries.append(pq)
                pq.prepare("""
                    INSERT INTO receipt_packages (receipt_id, package_id, quantity)
                    VALUES (?, ?, ?)
                """)
                pq.addBindValue(receipt_id)
                pq.addBindValue(pkg["package_id"])
                pq.addBindValue(int(pkg.get("quantity") or 1))
                pq.exec()

            # Record the cash handed over now, so the visit never has to be
            # chased on the Receipts page. A failed payment insert is as fatal
            # as the receipt itself - no visit without its money in this flow.
            if paid_cash > 0 and receipt_total > 0:
                pay_query = QSqlQuery(db)
                _active_queries.append(pay_query)
                pay_query.prepare("""
                    INSERT INTO payments (receipt_id, amount, payment_method, notes)
                    VALUES (?, ?, ?, ?)
                """)
                pay_query.addBindValue(receipt_id)
                pay_query.addBindValue(paid_cash)
                pay_query.addBindValue(payment_method or "Cash")
                pay_query.addBindValue(payment_notes or "")
                if not pay_query.exec():
                    logger.error("Failed to record payment for visit %s: %s",
                                 visit_id, pay_query.lastError().text())
                    for _q in _active_queries:
                        _q.finish()
                    db.rollback()
                    return None
        else:
            # A failed receipt insert must not leave a receipt-less visit behind.
            logger.error("Failed to create receipt for visit %s: %s",
                         visit_id, rq.lastError().text())
            for _q in _active_queries:
                _q.finish()
            db.rollback()
            return None
    
    # 6. Record Health Stats
    if health_stats:
        for hs in health_stats:
            stat_type_id = hs.get('stat_type_id')
            state_id = hs.get('state_id')
            extra_note = hs.get('extra_note', '')
            if stat_type_id:
                hq = QSqlQuery(db)
                _active_queries.append(hq)
                hq.prepare("""
                    INSERT INTO health_stats (pet_id, visit_id, stat_type_id, state_id, extra_note)
                    VALUES (?, ?, ?, ?, ?)
                """)
                hq.addBindValue(pet_id)
                hq.addBindValue(visit_id)
                hq.addBindValue(stat_type_id)
                hq.addBindValue(state_id)
                hq.addBindValue(extra_note)
                if not hq.exec():
                    logger.error(f"Failed to record health stat: {hq.lastError().text()}")
                    db.rollback()
                    return None

    # 7. Record Tests
    if tests:
        for test_item in tests:
            test_id = test_item.get('test_id')
            state_id = test_item.get('state_id')
            if test_id:
                tq = QSqlQuery(db)
                _active_queries.append(tq)
                tq.prepare("""
                    INSERT INTO tests (visit_id, test_id, state_id)
                    VALUES (?, ?, ?)
                """)
                tq.addBindValue(visit_id)
                tq.addBindValue(test_id)
                tq.addBindValue(state_id)
                if not tq.exec():
                    logger.error(f"Failed to record test: {tq.lastError().text()}")
                    db.rollback()
                    return None

    # 8. Record Treatments
    if treatments:
        for treat_id in treatments:
            if treat_id:
                tq = QSqlQuery(db)
                _active_queries.append(tq)
                tq.prepare("""
                    INSERT INTO treatments (visit_id, treatment_id)
                    VALUES (?, ?)
                """)
                tq.addBindValue(visit_id)
                tq.addBindValue(treat_id)
                if not tq.exec():
                    logger.error(f"Failed to record treatment: {tq.lastError().text()}")
                    db.rollback()
                    return None

    # 9. Record Vaccinations
    if vaccinations:
        for vacc_id in vaccinations:
            if vacc_id:
                vq = QSqlQuery(db)
                _active_queries.append(vq)
                vq.prepare("""
                    INSERT INTO vaccinations (visit_id, vaccine_id)
                    VALUES (?, ?)
                """)
                vq.addBindValue(visit_id)
                vq.addBindValue(vacc_id)
                if not vq.exec():
                    logger.error(f"Failed to record vaccination: {vq.lastError().text()}")
                    db.rollback()
                    return None

    # 10. Record Medications
    if medications:
        for med in medications:
            supply_id = med.get('supply_id')
            dosage = med.get('dosage', '')
            instructions = med.get('instructions', '')
            if supply_id:
                mq = QSqlQuery(db)
                _active_queries.append(mq)
                mq.prepare("""
                    INSERT INTO medications (visit_id, supply_id, dosage, instructions)
                    VALUES (?, ?, ?, ?)
                """)
                mq.addBindValue(visit_id)
                mq.addBindValue(supply_id)
                mq.addBindValue(dosage)
                mq.addBindValue(instructions)
                if not mq.exec():
                    logger.error(f"Failed to record medication: {mq.lastError().text()}")
                    db.rollback()
                    return None

    # 11. Record structured clinical exam (normalized record-book tables)
    if clinical_exam:
        from src.core.repositories import clinical_exam_repo
        try:
            clinical_exam_repo.save_clinical_exam(db, visit_id, clinical_exam)
        except Exception as exc:
            logger.error("Failed to record clinical exam for visit %s: %s", visit_id, exc)
            db.rollback()
            return None

    # Finish all active statements so SQLite can commit the transaction.
    # Without this, QtSql reports "cannot commit transaction - SQL statements
    # in progress" whenever a SELECT/INSERT/UPDATE query is still active.
    for _q in _active_queries:
        try:
            _q.finish()
        except Exception:
            pass

    if not db.commit():
        logger.error(f"Transaction commit failed: {db.lastError().text()}")
        db.rollback()
        return None

    if audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("ADD", "visits", visit_id,
                      changes=[{"field_name": "diagnosis", "old_value": "", "new_value": diagnosis or ""}],
                      user_id=audit_user_id)

    if ids_out is not None:
        ids_out["visit_id"] = visit_id
        ids_out["receipt_id"] = receipt_id

    return receipt_id if receipt_id is not None else visit_id


def update_visit(visit_id, diagnosis, notes, visit_date, is_consult,
                 reason_for_visit="", temperature=None, doctor_id=None, audit_user_id=None):
    """Updates clinical details of a visit."""
    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT diagnosis, notes, visit_date, reason_for_visit, temperature_in_c
        FROM visits WHERE visit_id = ?
    """)
    oq.addBindValue(visit_id)
    if oq.exec() and oq.next():
        old_row = {
            "diagnosis": oq.value(0) or "",
            "notes": oq.value(1) or "",
            "visit_date": oq.value(2) or "",
            "reason_for_visit": oq.value(3) or "",
            "temperature_in_c": oq.value(4) or "",
        }
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE visits SET diagnosis = ?, notes = ?, visit_date = ?,
            reason_for_visit = ?, temperature_in_c = ?, doctor_id = COALESCE(?, doctor_id)
        WHERE visit_id = ?
    """)
    query.addBindValue(diagnosis)
    query.addBindValue(notes)
    query.addBindValue(visit_date)
    query.addBindValue(reason_for_visit)
    query.addBindValue(temperature)
    query.addBindValue(doctor_id)
    query.addBindValue(visit_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        record_action("UPDATE", "visits", visit_id,
                      changes=field_diffs(old_row, {
                          "diagnosis": diagnosis or "",
                          "notes": notes or "",
                          "visit_date": visit_date or "",
                          "reason_for_visit": reason_for_visit or "",
                          "temperature_in_c": temperature if temperature is not None else "",
                      }) or None,
                      user_id=audit_user_id)
    return result


def delete_visit(visit_id, audit_user_id=None):
    """Removes a visit record."""
    from src.core.repositories.undo_repo import capture_snapshot, record_deletion
    snapshot = capture_snapshot("visits", visit_id)

    db = get_connection()
    old_diagnosis = ""
    oq = QSqlQuery(db)
    oq.prepare("SELECT diagnosis FROM visits WHERE visit_id = ?")
    oq.addBindValue(visit_id)
    if oq.exec() and oq.next():
        old_diagnosis = oq.value(0) or ""
    query = QSqlQuery(db)
    query.prepare("DELETE FROM visits WHERE visit_id = ?")
    query.addBindValue(visit_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "visits", visit_id,
                      changes=[{"field_name": "diagnosis", "old_value": old_diagnosis, "new_value": ""}],
                      user_id=audit_user_id)

    if result and snapshot is not None:
        record_deletion("visits", visit_id, snapshot, user_id=audit_user_id)
    return result


def get_latest_visit_id_for_client(client_id, visit_date):
    """Returns the newest visit ID for an owner/date pair."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.visit_id
        FROM visits v
        JOIN pets p ON p.pet_id = v.pet_id
        WHERE p.owner_id = ? AND v.visit_date = ?
        ORDER BY v.visit_id DESC LIMIT 1
    """)
    query.addBindValue(client_id)
    query.addBindValue(visit_date)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_visits_for_export():
    """Retrieves every visit with the columns the import template uses.

    Supplies are flattened into the ``Name x2; Other`` form the importer's
    ``parse_items`` understands, and the owner's phone is joined in (the visit
    listing has no contact) so a visit row can be re-imported on its own.

    Returns:
        list[dict]: one entry per visit, newest last.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.visit_date,
               CASE WHEN TRIM(o.last_name) = '' THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, ''),
               p.pet_name,
               COALESCE(v.diagnosis, ''),
               COALESCE(v.reason_for_visit, ''),
               COALESCE(v.notes, ''),
               (SELECT COUNT(*) FROM receipt_services ros
                JOIN receipts r2 ON ros.receipt_id = r2.receipt_id
                JOIN services_lookup sl ON ros.service_id = sl.service_id
                WHERE r2.visit_id = v.visit_id
                  AND sl.service_name = 'Consultation') AS consult_count,
               v.temperature_in_c,
               (SELECT GROUP_CONCAT(
                           CASE WHEN rsq.quantity > 1
                                THEN su.item_name || ' x' || rsq.quantity
                                ELSE su.item_name END, '; ')
                FROM receipts r3
                JOIN receipt_supplies rsq ON rsq.receipt_id = r3.receipt_id
                JOIN supplies su ON su.supply_id = rsq.supply_id
                WHERE r3.visit_id = v.visit_id) AS supplies,
               (SELECT r4.receipt_code
                FROM receipts r4
                WHERE r4.visit_id = v.visit_id
                  AND COALESCE(r4.receipt_kind, 'visit') <> 'expense'
                ORDER BY r4.receipt_id LIMIT 1) AS receipt_code
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        ORDER BY v.visit_date ASC, v.visit_id ASC
    """)

    results = []
    if query.exec():
        while query.next():
            consult = (query.value(7) or 0) > 0
            results.append({
                "visit_date": query.value(0) or "",
                "owner_name": query.value(1) or "",
                "phone_number": query.value(2) or "",
                "pet_name": query.value(3) or "",
                "diagnosis": query.value(4) or "",
                "reason_for_visit": query.value(5) or "",
                "notes": query.value(6) or "",
                "consult": "Yes" if consult else "No",
                "temperature": query.value(8),
                "supplies": query.value(9) or "",
                "receipt_code": query.value(10) or "",
            })
    return results


# --- Retrieval & Reporting ---

def get_visits(text=None, filter_field="All"):
    """Retrieves medical visits with optional text filtering."""
    db = get_connection()
    base_query = """
        SELECT v.visit_id, v.visit_date, 
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name, v.diagnosis, v.notes, v.pet_id,
               (SELECT receipt_id FROM receipts WHERE visit_id = v.visit_id LIMIT 1) as receipt_id,
               (SELECT COUNT(*) FROM receipt_services ros
                JOIN receipts r2 ON ros.receipt_id = r2.receipt_id
                JOIN services_lookup sl ON ros.service_id = sl.service_id
                WHERE r2.visit_id = v.visit_id AND sl.service_name = 'Consultation') as consult_count,
               v.reason_for_visit,
               o.owner_id AS owner_id,
               v.doctor_id,
               d.first_name || ' ' || d.last_name AS doctor_name
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN doctors d ON d.doctor_id = v.doctor_id
    """
    conditions, bind_values = [], []
    searchable_fields = ["v.visit_date", "owner_name", "p.pet_name", "v.diagnosis", "v.notes"]

    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
            bind_values.extend([search_text] * len(searchable_fields))
        else:
            mapping = {
                "visit_date": "v.visit_date",
                "owner_name": "o.first_name || ' ' || o.last_name",
                "pet_name": "p.pet_name",
                "diagnosis": "v.diagnosis",
                "notes": "v.notes",
            }
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "receipt_id":
                conditions.append("(SELECT receipt_id FROM receipts WHERE visit_id = v.visit_id LIMIT 1) LIKE ?")
            else:
                column_sql = mapping.get(clean_field)
                if column_sql is None:
                    column_sql = "v.diagnosis"
                conditions.append(f"{column_sql} LIKE ?")
            bind_values.append(search_text)
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY v.visit_date DESC"
    
    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)
    
    results = []
    if query.exec():
        while query.next():
            results.append({
                "visit_id": query.value(0),
                "visit_date": query.value(1),
                "owner_name": query.value(2),
                "pet_name": query.value(3),
                "diagnosis": query.value(4),
                "consult": 1 if query.value(8) > 0 else 0,
                "notes": query.value(5),
                "pet_id": query.value(6),
                "receipt_id": query.value(7),
                "reason_for_visit": query.value(9) or "",
                "owner_id": query.value(10),
                "doctor_id": query.value(11),
                "doctor_name": query.value(12),
            })
    return results


def get_recent_visits_for_client(client_id, limit=4):
    """Returns the most recent visits for an owner (across all of their pets)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.visit_id, v.visit_date, p.pet_name, v.diagnosis, v.notes,
               (SELECT COUNT(*) FROM receipt_services ros
                JOIN receipts r2 ON ros.receipt_id = r2.receipt_id
                JOIN services_lookup sl ON ros.service_id = sl.service_id
                WHERE r2.visit_id = v.visit_id AND sl.service_name = 'Consultation') as consult_count
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        WHERE p.owner_id = ?
        ORDER BY v.visit_date DESC
        LIMIT ?
    """)
    query.addBindValue(client_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "visit_id": query.value(0),
                "visit_date": query.value(1),
                "pet_name": query.value(2),
                "diagnosis": query.value(3) or "",
                "notes": query.value(4) or "",
                "is_consult": 1 if query.value(5) > 0 else 0,
            })
    return results


def get_recent_visits_for_pet(pet_id, limit=4):
    """Returns the most recent visits for a single pet."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.visit_id, v.visit_date, p.pet_name, v.diagnosis, v.notes,
               (SELECT COUNT(*) FROM receipt_services ros
                JOIN receipts r2 ON ros.receipt_id = r2.receipt_id
                JOIN services_lookup sl ON ros.service_id = sl.service_id
                WHERE r2.visit_id = v.visit_id AND sl.service_name = 'Consultation') as consult_count
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        WHERE p.pet_id = ?
        ORDER BY v.visit_date DESC
        LIMIT ?
    """)
    query.addBindValue(pet_id)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "visit_id": query.value(0),
                "visit_date": query.value(1),
                "pet_name": query.value(2),
                "diagnosis": query.value(3) or "",
                "notes": query.value(4) or "",
                "is_consult": 1 if query.value(5) > 0 else 0,
            })
    return results


def get_visit_stats_for_pet(pet_id):
    """Returns KPI-style visit stats for a single pet.

    Returns:
        dict with visit_count/avg_spend/last_visit_date, or an empty dict when
        the pet has no visits. avg_spend is 0.0 when there is no spend data.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COUNT(*),
               COALESCE(SUM(r.total_price), 0),
               MAX(v.visit_date)
        FROM visits v
        LEFT JOIN receipts r ON r.visit_id = v.visit_id
        WHERE v.pet_id = ?
    """)
    query.addBindValue(pet_id)
    if query.exec() and query.next():
        count = query.value(0) or 0
        total = float(query.value(1) or 0.0)
        return {
            "visit_count": count,
            "avg_spend": (total / count) if count else 0.0,
            "last_visit_date": query.value(2) or "",
        }
    return {}


def get_unique_diagnoses():
    """Returns a distinct list of all recorded diagnoses."""
    db = get_connection()
    query = QSqlQuery(db)
    query.exec("SELECT DISTINCT diagnosis FROM visits WHERE diagnosis IS NOT NULL AND diagnosis != '' ORDER BY diagnosis ASC")
    results = []
    while query.next():
        results.append(query.value(0))
    return results


def get_doctor_visits(doctor_id=None, text=None, filter_field="All"):
    """Retrieves visits for a specific doctor (or all visits if doctor_id is None/unassigned)."""
    db = get_connection()
    columns = [
        "visit_id", "owner_id", "owner_full_name", "phone_number", "pet_name",
        "species_name", "breed_name", "gender", "age_in_months", "weight_in_kg",
        "visit_date", "diagnosis", "notes", "receipt_id"
    ]
    
    searchable_fields = [
        "owner_full_name", "phone_number", "pet_name", "species_name", "breed_name",
        "gender", "age_in_months", "weight_in_kg", "visit_date", "diagnosis", "notes"
    ]

    # `consult` is receipt-driven (there is no `visits.is_consult` column): a
    # visit carries a consultation charge when its receipt has a 'Consultation'
    # service line. Expose it as 0/1 so the list can display it and the Visit
    # Details dialog gets the real value instead of parsing a table cell.
    select_columns = ", ".join(columns) + ", " + (
        "CASE WHEN EXISTS ("
        " SELECT 1 FROM receipt_services rs"
        " JOIN services_lookup srv ON rs.service_id = srv.service_id"
        " WHERE rs.receipt_id = v_home_records.receipt_id"
        "   AND srv.service_name = 'Consultation'"
        ") THEN 1 ELSE 0 END AS consult"
    )
    result_keys = columns + ["consult"]

    base_query = f"SELECT {select_columns} FROM v_home_records"
    conditions, bind_values = [], []

    if doctor_id is not None:
        # Check visits table for doctor_id filter
        conditions.append("visit_id IN (SELECT visit_id FROM visits WHERE doctor_id = ?)")
        bind_values.append(doctor_id)

    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
            bind_values.extend([search_text] * len(searchable_fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "age":
                clean_field = "age_in_months"
            if clean_field == "weight":
                clean_field = "weight_in_kg"
            if clean_field in searchable_fields:
                conditions.append(f"{clean_field} LIKE ?")
                bind_values.append(search_text)
            else:
                conditions.append("(owner_full_name LIKE ? OR pet_name LIKE ?)")
                bind_values.extend([search_text, search_text])

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY visit_date DESC"

    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)

    results = []
    if query.exec():
        while query.next():
            results.append({col: query.value(i) for i, col in enumerate(result_keys)})
    return results


def find_visit_id(client_id, pet_id, visit_date):
    """Finds the newest visit for an owner+pet on a date (day precision).

    Used by the spreadsheet importer to attach clinical records (follow-ups,
    vaccinations, ...) to the visit they belong to. ``visit_date`` may carry a
    time; only the calendar day is compared, and only the owner's pets are
    searched.
    """
    if client_id is None or pet_id is None or not visit_date:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT v.visit_id
        FROM visits v
        JOIN pets p ON p.pet_id = v.pet_id
        WHERE p.owner_id = ? AND v.pet_id = ? AND date(v.visit_date) = date(?)
        ORDER BY v.visit_id DESC LIMIT 1
    """)
    query.addBindValue(client_id)
    query.addBindValue(pet_id)
    query.addBindValue(visit_date)
    if query.exec() and query.next():
        return query.value(0)
    return None

