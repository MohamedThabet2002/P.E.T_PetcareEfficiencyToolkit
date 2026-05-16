"""
Visit Repository for the PET Application.
Handles recording medical visits, processing associated billing/inventory,
and retrieving clinical history.
Uses the new schema: visits linked to pets, with structured receipt tables.
"""

import logging

from PyQt5.QtSql import QSqlQuery
from PyQt5.QtCore import QSettings

from src.core.database import get_connection
from src.core.repositories.supply_repo import update_supply_stock

from src.config import SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE, SETTINGS_ORG, SETTINGS_APP

logger = logging.getLogger(__name__)


def add_visit(visit_date, diagnosis, consult, notes, pet_id=None, items=None, client_id=None,
              reason_for_visit="", temperature=None):
    """
    Logs a medical visit using the new schema.
    Handles inventory validation, stock deduction, and automated billing.
    Returns visit_id on success, or an error string/None on failure.
    """
    db = get_connection()
    db.transaction()
    items = items or []
    receipt_id = None
    
    # Get current consult fee from settings
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    consult_fee = float(settings.value(SETTING_CONSULT_FEE_LABEL, DEFAULT_CONSULT_FEE))
    
    # 1. Validate aggregate stock before committing
    planned_usage = {}
    for itm in items:
        n = itm.get('item_name')
        q = itm.get('quantity', 1)
        if n and q > 0:
            key = n
            planned_usage[key] = planned_usage.get(key, 0) + q
    
    for name, total_qty in planned_usage.items():
        check_q = QSqlQuery(db)
        check_q.prepare("SELECT SUM(current_stock) FROM supplies WHERE item_name = ?")
        check_q.addBindValue(name)
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
    oq.prepare("SELECT owner_id FROM pets WHERE pet_id = ?")
    oq.addBindValue(pet_id)
    if not (oq.exec() and oq.next()):
        db.rollback()
        return None
    owner_id = oq.value(0)
    
    # 3. Insert Visit Record
    vq = QSqlQuery(db)
    vq.prepare("""
        INSERT INTO visits (pet_id, visit_date, diagnosis, notes, reason_for_visit, temperature_in_c)
        VALUES (?, ?, ?, ?, ?, ?)
    """)
    vq.addBindValue(pet_id)
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
            iq.prepare("""
                SELECT supply_id, sell_price, current_stock FROM supplies
                WHERE item_name = ? AND current_stock > 0 LIMIT 1
            """)
            iq.addBindValue(name)
            if iq.exec() and iq.next():
                supply_id = iq.value(0)
                db_price = iq.value(1)
                curr_qty = iq.value(2)
                
                price_to_charge = custom_price if custom_price is not None else (db_price or 0)
                
                # Deduct stock
                uq = QSqlQuery(db)
                uq.prepare("UPDATE supplies SET current_stock = current_stock - ? WHERE supply_id = ?")
                uq.addBindValue(qty)
                uq.addBindValue(supply_id)
                uq.exec()
                
                # Log stock movement
                mq = QSqlQuery(db)
                mq.prepare("""
                    INSERT INTO stock_movements (supply_id, movement_type, quantity, notes)
                    VALUES (?, 'sale', ?, 'Visit #' || ?)
                """)
                mq.addBindValue(supply_id)
                mq.addBindValue(-qty)
                mq.addBindValue(visit_id)
                mq.exec()
                
                billed_items.append({
                    "supply_id": supply_id,
                    "name": name,
                    "price": price_to_charge,
                    "qty": qty
                })
                total_amount += (price_to_charge * qty)
    
    # 5. Generate Receipt
    if billed_items or consult:
        receipt_total = total_amount + (consult_fee if consult else 0)
        rq = QSqlQuery(db)
        rq.prepare("""
            INSERT INTO receipts (visit_id, owner_id, receipt_date, total_price, receipt_code)
            VALUES (?, ?, ?, ?, 'Sale')
        """)
        rq.addBindValue(visit_id)
        rq.addBindValue(owner_id)
        rq.addBindValue(visit_date)
        rq.addBindValue(receipt_total)
        
        if rq.exec():
            receipt_id = rq.lastInsertId()
            
            # Add Consultation Service
            if consult:
                sq = QSqlQuery(db)
                sq.prepare("SELECT service_id FROM services_lookup WHERE service_name = 'Consultation'")
                service_id = None
                if sq.exec() and sq.next():
                    service_id = sq.value(0)
                
                rs = QSqlQuery(db)
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
                ri.prepare("""
                    INSERT INTO receipt_supplies (receipt_id, supply_id, quantity, unit_price)
                    VALUES (?, ?, ?, ?)
                """)
                ri.addBindValue(receipt_id)
                ri.addBindValue(item["supply_id"])
                ri.addBindValue(item["qty"])
                ri.addBindValue(item["price"])
                ri.exec()
    
    if not db.commit():
        logger.error(f"Transaction commit failed: {db.lastError().text()}")
        db.rollback()
        return None
    
    return receipt_id if receipt_id is not None else visit_id


def update_visit(visit_id, diagnosis, notes, visit_date, is_consult):
    """Updates clinical details of a visit."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE visits SET diagnosis = ?, notes = ?, visit_date = ?
        WHERE visit_id = ?
    """)
    query.addBindValue(diagnosis)
    query.addBindValue(notes)
    query.addBindValue(visit_date)
    query.addBindValue(visit_id)
    return query.exec()


def delete_visit(visit_id):
    """Removes a visit record."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM visits WHERE visit_id = ?")
    query.addBindValue(visit_id)
    return query.exec()


# --- Retrieval & Reporting ---

def get_visits(text=None, filter_field="All"):
    """Retrieves medical visits with optional text filtering."""
    db = get_connection()
    base_query = """
        SELECT v.visit_id, v.visit_date, 
               o.first_name || ' ' || o.last_name AS owner_name,
               p.pet_name, v.diagnosis, v.notes, v.pet_id,
               (SELECT receipt_id FROM receipts WHERE visit_id = v.visit_id LIMIT 1) as receipt_id
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
    """
    conditions, bind_values = [], []
    searchable_fields = ["v.visit_date", "owner_name", "p.pet_name", "v.diagnosis", "v.notes"]

    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'{f} LIKE ?' for f in searchable_fields])})")
            bind_values.extend([search_text] * len(searchable_fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            if clean_field == "receipt_id":
                conditions.append("(SELECT receipt_id FROM receipts WHERE visit_id = v.visit_id LIMIT 1) LIKE ?")
            else:
                conditions.append(f"{clean_field} LIKE ?")
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
                "consult": 0,
                "notes": query.value(5),
                "pet_id": query.value(6),
                "receipt_id": query.value(7),
            })
    return results


def get_home_clients(text=None, filter_field="All"):
    """Retrieves combined owner and visit data for the home dashboard view."""
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

    base_query = f"SELECT {', '.join(columns)} FROM v_home_records"
    conditions, bind_values = [], []
    
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
            results.append({col: query.value(i) for i, col in enumerate(columns)})
    return results


def get_unique_diagnoses():
    """Returns a distinct list of all recorded diagnoses."""
    db = get_connection()
    query = QSqlQuery(db)
    query.exec("SELECT DISTINCT diagnosis FROM visits WHERE diagnosis IS NOT NULL AND diagnosis != '' ORDER BY diagnosis ASC")
    results = []
    while query.next():
        results.append(query.value(0))
    return results

