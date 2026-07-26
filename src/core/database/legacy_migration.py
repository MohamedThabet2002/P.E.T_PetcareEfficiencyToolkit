"""
Legacy data migration module for the PET Application.
Migrates data from old schema to new schema.
"""

import logging

from PyQt5.QtSql import QSqlQuery

logger = logging.getLogger(__name__)


def migrate_from_legacy(db):
    """Migrate data from old schema to new schema."""
    query = QSqlQuery(db)

    # Migrate clients -> owners + contacts
    if query.exec("SELECT id, owner_name, phone_number FROM clients"):
        while query.next():
            old_id = query.value(0)
            full_name = str(query.value(1) or "Unknown")
            phone = str(query.value(2) or "")

            # Split name into first/last
            parts = full_name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            # Check if already migrated
            check = QSqlQuery(db)
            check.prepare("SELECT owner_id FROM owners WHERE first_name = ? AND last_name = ?")
            check.addBindValue(first_name)
            check.addBindValue(last_name)
            if check.exec() and check.next():
                owner_id = check.value(0)
            else:
                ins = QSqlQuery(db)
                ins.prepare("INSERT INTO owners (first_name, last_name) VALUES (?, ?)")
                ins.addBindValue(first_name)
                ins.addBindValue(last_name)
                if ins.exec():
                    owner_id = ins.lastInsertId()
                else:
                    continue

            # Create contact
            if phone:
                cins = QSqlQuery(db)
                cins.prepare("INSERT INTO contacts (phone_number) VALUES (?)")
                cins.addBindValue(phone)
                if cins.exec():
                    contact_id = cins.lastInsertId()
                    ec = QSqlQuery(db)
                    ec.prepare("INSERT INTO entity_contacts (entity_type, entity_id, contact_id) VALUES ('owner', ?, ?)")
                    ec.addBindValue(owner_id)
                    ec.addBindValue(contact_id)
                    ec.exec()

            # Migrate pets
            pquery = QSqlQuery(db)
            pquery.prepare("SELECT id, pet_name, species, breed, gender, age_months, weight FROM pets WHERE client_id = ?")
            pquery.addBindValue(old_id)
            if pquery.exec():
                while pquery.next():
                    # Try to find species_id
                    species_name = str(pquery.value(2) or "")
                    breed_name = str(pquery.value(3) or "")
                    species_id = None
                    breed_id = None

                    if species_name:
                        sq = QSqlQuery(db)
                        sq.prepare("SELECT species_id FROM species_lookup WHERE species_name = ?")
                        sq.addBindValue(species_name)
                        if sq.exec() and sq.next():
                            species_id = sq.value(0)
                        else:
                            # Insert species
                            si = QSqlQuery(db)
                            si.prepare("INSERT INTO species_lookup (species_name) VALUES (?)")
                            si.addBindValue(species_name)
                            if si.exec():
                                species_id = si.lastInsertId()

                    if breed_name and species_id:
                        bq = QSqlQuery(db)
                        bq.prepare("SELECT breed_id FROM breeds_lookup WHERE breed_name = ? AND species_id = ?")
                        bq.addBindValue(breed_name)
                        bq.addBindValue(species_id)
                        if bq.exec() and bq.next():
                            breed_id = bq.value(0)
                        else:
                            bi = QSqlQuery(db)
                            bi.prepare("INSERT INTO breeds_lookup (species_id, breed_name) VALUES (?, ?)")
                            bi.addBindValue(species_id)
                            bi.addBindValue(breed_name)
                            if bi.exec():
                                breed_id = bi.lastInsertId()

                    pi = QSqlQuery(db)
                    pi.prepare("""
                        INSERT INTO pets (owner_id, pet_name, species_id, breed_id, gender, age_in_months, weight_in_kg)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """)
                    pi.addBindValue(owner_id)
                    pi.addBindValue(str(pquery.value(1) or ""))
                    pi.addBindValue(species_id)
                    pi.addBindValue(breed_id)
                    pi.addBindValue(str(pquery.value(4) or ""))
                    pi.addBindValue(pquery.value(5) or 0)
                    pi.addBindValue(float(pquery.value(6) or 0.0))
                    pi.exec()

            # Migrate visits
            vq = QSqlQuery(db)
            vq.prepare("SELECT v.id, v.visit_date, v.diagnosis, v.notes, v.receipt_id FROM visits v WHERE v.client_id = ?")
            vq.addBindValue(old_id)
            if vq.exec():
                while vq.next():
                    # Get new pet_id for this client
                    pet_q = QSqlQuery(db)
                    pet_q.prepare("SELECT pet_id FROM pets WHERE owner_id = ? LIMIT 1")
                    pet_q.addBindValue(owner_id)
                    new_pet_id = None
                    if pet_q.exec() and pet_q.next():
                        new_pet_id = pet_q.value(0)

                    vi = QSqlQuery(db)
                    vi.prepare("""
                        INSERT INTO visits (pet_id, visit_date, diagnosis, notes)
                        VALUES (?, ?, ?, ?)
                    """)
                    vi.addBindValue(new_pet_id)
                    vi.addBindValue(str(vq.value(1) or ""))
                    vi.addBindValue(str(vq.value(2) or ""))
                    vi.addBindValue(str(vq.value(3) or ""))
                    vi.exec()

            # Migrate appointments
            aq = QSqlQuery(db)
            aq.prepare("SELECT id, appointment_date, service, status, notes, pet_id FROM appointments WHERE client_id = ?")
            aq.addBindValue(old_id)
            if aq.exec():
                while aq.next():
                    # Find new pet_id from old pet_id
                    old_pet_id = aq.value(5)
                    new_pet_id = None
                    if old_pet_id:
                        np = QSqlQuery(db)
                        np.prepare("SELECT pet_id FROM pets WHERE pet_id = ?")
                        np.addBindValue(old_pet_id)
                        if np.exec() and np.next():
                            new_pet_id = np.value(0)

                    ai = QSqlQuery(db)
                    ai.prepare("""
                        INSERT INTO appointments (pet_id, appointment_date, status, notes)
                        VALUES (?, ?, ?, ?)
                    """)
                    ai.addBindValue(new_pet_id)
                    ai.addBindValue(str(aq.value(1) or ""))
                    ai.addBindValue(str(aq.value(3) or ""))
                    ai.addBindValue(str(aq.value(4) or ""))
                    ai.exec()

    # Migrate supplies
    if query.exec("SELECT id, item_name, category, sub_category, purchase_date, expiry_date, buy_price, sell_price, quantity, reorder_level, supplier FROM supplies"):
        while query.next():
            supplier_name = str(query.value(10) or "")
            supplier_id = None
            if supplier_name:
                sq = QSqlQuery(db)
                sq.prepare("SELECT supplier_id FROM suppliers WHERE supplier_name = ?")
                sq.addBindValue(supplier_name)
                if sq.exec() and sq.next():
                    supplier_id = sq.value(0)
                else:
                    si = QSqlQuery(db)
                    si.prepare("INSERT INTO suppliers (supplier_name) VALUES (?)")
                    si.addBindValue(supplier_name)
                    if si.exec():
                        supplier_id = si.lastInsertId()

            # Insert into new supplies
            nsi = QSqlQuery(db)
            nsi.prepare("""
                INSERT INTO supplies (item_name, category, sub_category, current_stock, reorder_level, expiry_date, buy_price, sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """)
            nsi.addBindValue(str(query.value(1) or ""))
            nsi.addBindValue(str(query.value(2) or ""))
            nsi.addBindValue(str(query.value(3) or ""))
            nsi.addBindValue(query.value(7) or 0)  # quantity -> current_stock
            nsi.addBindValue(query.value(9) or 0)  # reorder_level
            nsi.addBindValue(str(query.value(5) or ""))
            nsi.addBindValue(float(query.value(6) or 0.0))
            nsi.addBindValue(float(query.value(7) or 0.0))
            if nsi.exec():
                new_supply_id = nsi.lastInsertId()
                # Create stock batch record
                if query.value(4):  # purchase_date
                    stk = QSqlQuery(db)
                    stk.prepare("INSERT INTO stocks (supply_id, supplier_id, purchase_date, quantity) VALUES (?, ?, ?, ?)")
                    stk.addBindValue(new_supply_id)
                    stk.addBindValue(supplier_id)
                    stk.addBindValue(str(query.value(4) or ""))
                    stk.addBindValue(query.value(7) or 0)
                    stk.exec()

    # Migrate receipts
    if query.exec("SELECT id, visit_id, client_id, receipt_date, total_amount, receipt_type, notes FROM receipts"):
        while query.next():
            receipt_id = query.value(0)
            old_visit_id = query.value(1)
            old_client_id = query.value(2)
            receipt_date = str(query.value(3) or "")
            total = float(query.value(4) or 0.0)
            receipt_type = str(query.value(5) or "Sale")
            notes = str(query.value(6) or "")

            # Find new owner_id from old client_id
            owner_id = None
            if old_client_id:
                oq = QSqlQuery(db)
                oq.prepare("""
                    SELECT o.owner_id FROM owners o
                    JOIN pets p ON p.owner_id = o.owner_id
                    WHERE p.pet_id IN (SELECT pet_id FROM pets WHERE pet_id = ?)
                """)
                oq.addBindValue(old_client_id)
                if oq.exec() and oq.next():
                    owner_id = oq.value(0)

            # Find new visit_id
            new_visit_id = None
            if old_visit_id:
                vq2 = QSqlQuery(db)
                vq2.prepare("SELECT visit_id FROM visits ORDER BY visit_id DESC LIMIT 1")
                if vq2.exec() and vq2.next():
                    new_visit_id = vq2.value(0)

            ri = QSqlQuery(db)
            ri.prepare("""
                INSERT INTO receipts (visit_id, owner_id, receipt_date, total_price, receipt_code)
                VALUES (?, ?, ?, ?, ?)
            """)
            ri.addBindValue(new_visit_id)
            ri.addBindValue(owner_id)
            ri.addBindValue(receipt_date)
            ri.addBindValue(total)
            ri.addBindValue(receipt_type[:10])
            if ri.exec():
                new_receipt_id = ri.lastInsertId()

                # Migrate receipt items -> receipt_other
                riq = QSqlQuery(db)
                riq.prepare("SELECT item_name, category, quantity, unit_price, total_price FROM receipt_items WHERE receipt_id = ?")
                riq.addBindValue(receipt_id)
                if riq.exec():
                    while riq.next():
                        ro = QSqlQuery(db)
                        ro.prepare("""
                            INSERT INTO receipt_other (receipt_id, description, amount)
                            VALUES (?, ?, ?)
                        """)
                        ro.addBindValue(new_receipt_id)
                        ro.addBindValue(str(riq.value(0) or ""))
                        ro.addBindValue(float(riq.value(4) or 0.0))
                        ro.exec()

    # Drop old tables after migration
    old_tables = ["clients", "receipt_items", "supply_reorder_levels"]
    for tbl in old_tables:
        query.exec(f"DROP TABLE IF EXISTS {tbl}")

    logger.info("Legacy data migration completed successfully")
