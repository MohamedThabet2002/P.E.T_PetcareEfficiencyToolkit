"""
Legacy data migration module for the PET Application.
Migrates data from old schema to new schema.
"""

import logging

from PyQt5.QtSql import QSqlQuery

logger = logging.getLogger(__name__)

# Legacy tables whose name/primary-key/column layout changed in v2.0.0.
# `initialize_schema` creates the new-shaped `pets`/`visits`/`appointments`/
# `supplies`/`receipts` with CREATE TABLE IF NOT EXISTS, which is a no-op
# against a genuine v1.0.0 database, so the old tables would survive with their
# legacy columns and every new-schema INSERT in `migrate_from_legacy` would fail
# silently. They are copied to `_legacy_<name>` first (see
# archive_legacy_tables) so the new tables can be created cleanly.
_ARCHIVED_LEGACY_TABLES = ("pets", "visits", "appointments", "supplies", "receipts")


def _table_exists(db, table_name):
    q = QSqlQuery(db)
    q.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?")
    q.addBindValue(table_name)
    exists = bool(q.exec() and q.next())
    q.finish()
    return exists


def _table_columns(db, table_name):
    q = QSqlQuery(db)
    columns = set()
    if q.exec(f"PRAGMA table_info({table_name})"):
        while q.next():
            columns.add(q.value(1))
    q.finish()
    return columns


def archive_legacy_tables(db):
    """Preserve a genuine v1.0.0 schema before the new-shaped tables are made.

    A real v1.0.0 install stores `clients` plus old-shaped `pets`, `visits`,
    `appointments`, `supplies` and `receipts` (columns `id`, `client_id`,
    `quantity`, `total_amount`, `receipt_type`, ...). The new schema creates
    those five with CREATE TABLE IF NOT EXISTS, which leaves the old ones
    untouched telling SQLite not to create the new shape. Each conflicting
    legacy table is copied to a constraint-free `_legacy_<name>` table and then
    dropped, so `initialize_schema` creates the new shape and
    `migrate_from_legacy` reads from the archived copies. The copies are removed
    once the migration finishes.

    Detection is deliberately strict: only a database that still has `clients`
    and an old-shaped `pets` table (no `pet_id`) is archived. An already-new or
    hybrid `pets` (which carries `pet_id`) is left alone.
    """
    if not _table_exists(db, "clients"):
        return
    if "pet_id" in _table_columns(db, "pets"):
        return

    toggles = QSqlQuery(db)
    toggles.exec("PRAGMA foreign_keys = OFF;")
    toggles.finish()
    try:
        for table in _ARCHIVED_LEGACY_TABLES:
            if not _table_exists(db, table):
                continue
            # Drop any stale archive left by a previously aborted upgrade so
            # the copy below cannot fail with "table already exists".
            stale = QSqlQuery(db)
            stale.exec(f"DROP TABLE IF EXISTS _legacy_{table}")
            stale.finish()
            copy = QSqlQuery(db)
            copy.exec(f"CREATE TABLE _legacy_{table} AS SELECT * FROM {table}")
            copy.finish()
            drop = QSqlQuery(db)
            drop.exec(f"DROP TABLE {table}")
            drop.finish()
        logger.info(
            "Archived pre-v2 legacy tables for upgrade: %s",
            ", ".join(_ARCHIVED_LEGACY_TABLES),
        )
    finally:
        reenable = QSqlQuery(db)
        reenable.exec("PRAGMA foreign_keys = ON;")
        reenable.finish()


def _source_table(db, table_name):
    """Return the archived `_legacy_<name>` copy when one exists, else the name."""
    archived = f"_legacy_{table_name}"
    return archived if _table_exists(db, archived) else table_name


def migrate_from_legacy(db):
    """Migrate data from old schema to new schema."""
    query = QSqlQuery(db)
    queries = [query]

    # Old -> new id maps so related records stay linked after remapping.
    owner_map = {}  # legacy clients.id      -> new owners.owner_id
    pet_map = {}    # legacy pets.id         -> new pets.pet_id
    visit_map = {}  # legacy visits.id       -> new visits.visit_id

    # Read from the archived `_legacy_<name>` copies when a genuine v1.0.0
    # database was archived (see archive_legacy_tables); a hybrid database
    # reads the live tables. Writes always go to the new-shaped tables.
    pets_src = _source_table(db, "pets")
    visits_src = _source_table(db, "visits")
    appointments_src = _source_table(db, "appointments")
    supplies_src = _source_table(db, "supplies")
    receipts_src = _source_table(db, "receipts")

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
            queries.append(check)
            check.prepare("SELECT owner_id FROM owners WHERE first_name = ? AND last_name = ?")
            check.addBindValue(first_name)
            check.addBindValue(last_name)
            if check.exec() and check.next():
                owner_id = check.value(0)
            else:
                ins = QSqlQuery(db)
                queries.append(ins)
                ins.prepare("INSERT INTO owners (first_name, last_name) VALUES (?, ?)")
                ins.addBindValue(first_name)
                ins.addBindValue(last_name)
                if ins.exec():
                    owner_id = ins.lastInsertId()
                else:
                    continue

            owner_map[old_id] = owner_id

            # Create contact
            if phone:
                cins = QSqlQuery(db)
                queries.append(cins)
                cins.prepare("INSERT INTO contacts (phone_number) VALUES (?)")
                cins.addBindValue(phone)
                if cins.exec():
                    contact_id = cins.lastInsertId()
                    ec = QSqlQuery(db)
                    queries.append(ec)
                    ec.prepare("INSERT INTO entity_contacts (entity_type, entity_id, contact_id) VALUES ('owner', ?, ?)")
                    ec.addBindValue(owner_id)
                    ec.addBindValue(contact_id)
                    ec.exec()

            # Migrate pets
            pquery = QSqlQuery(db)
            queries.append(pquery)
            pquery.prepare(f"SELECT id, pet_name, species, breed, gender, age_months, weight FROM {pets_src} WHERE client_id = ?")
            pquery.addBindValue(old_id)
            if pquery.exec():
                while pquery.next():
                    old_pet_id = pquery.value(0)
                    # Try to find species_id
                    species_name = str(pquery.value(2) or "")
                    breed_name = str(pquery.value(3) or "")
                    species_id = None
                    breed_id = None

                    if species_name:
                        sq = QSqlQuery(db)
                        queries.append(sq)
                        sq.prepare("SELECT species_id FROM species_lookup WHERE species_name = ?")
                        sq.addBindValue(species_name)
                        if sq.exec() and sq.next():
                            species_id = sq.value(0)
                        else:
                            # Insert species
                            si = QSqlQuery(db)
                            queries.append(si)
                            si.prepare("INSERT INTO species_lookup (species_name) VALUES (?)")
                            si.addBindValue(species_name)
                            if si.exec():
                                species_id = si.lastInsertId()

                    if breed_name and species_id:
                        bq = QSqlQuery(db)
                        queries.append(bq)
                        bq.prepare("SELECT breed_id FROM breeds_lookup WHERE breed_name = ? AND species_id = ?")
                        bq.addBindValue(breed_name)
                        bq.addBindValue(species_id)
                        if bq.exec() and bq.next():
                            breed_id = bq.value(0)
                        else:
                            bi = QSqlQuery(db)
                            queries.append(bi)
                            bi.prepare("INSERT INTO breeds_lookup (species_id, breed_name) VALUES (?, ?)")
                            bi.addBindValue(species_id)
                            bi.addBindValue(breed_name)
                            if bi.exec():
                                breed_id = bi.lastInsertId()

                    pi = QSqlQuery(db)
                    queries.append(pi)
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
                    if pi.exec():
                        pet_map[old_pet_id] = pi.lastInsertId()

            # Migrate visits
            vq = QSqlQuery(db)
            queries.append(vq)
            vq.prepare(f"SELECT v.id, v.visit_date, v.diagnosis, v.notes, v.receipt_id, v.pet_id FROM {visits_src} v WHERE v.client_id = ?")
            vq.addBindValue(old_id)
            if vq.exec():
                while vq.next():
                    old_visit_id = vq.value(0)
                    # Prefer the visit's own legacy pet link (v1.0.0 stored a
                    # pet_id on visits); fall back to the owner's first pet only
                    # when it is missing (the pre-pet_id legacy state).
                    new_pet_id = pet_map.get(vq.value(5))
                    if new_pet_id is None:
                        pet_q = QSqlQuery(db)
                        queries.append(pet_q)
                        pet_q.prepare("SELECT pet_id FROM pets WHERE owner_id = ? LIMIT 1")
                        pet_q.addBindValue(owner_id)
                        if pet_q.exec() and pet_q.next():
                            new_pet_id = pet_q.value(0)

                    vi = QSqlQuery(db)
                    queries.append(vi)
                    vi.prepare("""
                        INSERT INTO visits (pet_id, visit_date, diagnosis, notes)
                        VALUES (?, ?, ?, ?)
                    """)
                    vi.addBindValue(new_pet_id)
                    vi.addBindValue(str(vq.value(1) or ""))
                    vi.addBindValue(str(vq.value(2) or ""))
                    vi.addBindValue(str(vq.value(3) or ""))
                    if vi.exec():
                        visit_map[old_visit_id] = vi.lastInsertId()

            # Migrate appointments
            aq = QSqlQuery(db)
            queries.append(aq)
            aq.prepare(f"SELECT id, appointment_date, service, status, notes, pet_id FROM {appointments_src} WHERE client_id = ?")
            aq.addBindValue(old_id)
            if aq.exec():
                while aq.next():
                    # Translate the legacy pet id through the old->new map.
                    old_pet_id = aq.value(5)
                    new_pet_id = pet_map.get(old_pet_id)

                    ai = QSqlQuery(db)
                    queries.append(ai)
                    ai.prepare("""
                        INSERT INTO appointments (pet_id, appointment_date, status, notes)
                        VALUES (?, ?, ?, ?)
                    """)
                    ai.addBindValue(new_pet_id)
                    ai.addBindValue(str(aq.value(1) or ""))
                    ai.addBindValue(str(aq.value(3) or ""))
                    ai.addBindValue(str(aq.value(4) or ""))
                    ai.exec()

        # Release the clients SELECT before the write-heavy blocks below.
        query.finish()

    # Migrate supplies.
    # IMPORTANT: snapshot the legacy rows first. The migration INSERTs into the
    # same table the SELECT iterates, so re-reading while writing would
    # re-migrate the newly created rows forever.
    if query.exec(f"SELECT id, item_name, category, sub_category, purchase_date, expiry_date, buy_price, sell_price, quantity, reorder_level, supplier FROM {supplies_src}"):
        old_supplies = []
        while query.next():
            old_supplies.append([query.value(i) for i in range(query.record().count())])
        query.finish()

        for row in old_supplies:
            supplier_name = str(row[10] or "")
            supplier_id = None
            if supplier_name:
                sq = QSqlQuery(db)
                queries.append(sq)
                sq.prepare("SELECT supplier_id FROM suppliers WHERE supplier_name = ?")
                sq.addBindValue(supplier_name)
                if sq.exec() and sq.next():
                    supplier_id = sq.value(0)
                else:
                    si = QSqlQuery(db)
                    queries.append(si)
                    si.prepare("INSERT INTO suppliers (supplier_name) VALUES (?)")
                    si.addBindValue(supplier_name)
                    if si.exec():
                        supplier_id = si.lastInsertId()

            # Insert into new supplies
            nsi = QSqlQuery(db)
            queries.append(nsi)
            nsi.prepare("""
                INSERT INTO supplies (item_name, category, sub_category, current_stock, reorder_level, expiry_date, buy_price, sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """)
            nsi.addBindValue(str(row[1] or ""))
            nsi.addBindValue(str(row[2] or ""))
            nsi.addBindValue(str(row[3] or ""))
            nsi.addBindValue(row[8] or 0)  # quantity -> current_stock
            nsi.addBindValue(row[9] or 0)  # reorder_level
            nsi.addBindValue(str(row[5] or ""))
            nsi.addBindValue(float(row[6] or 0.0))
            nsi.addBindValue(float(row[7] or 0.0))
            if nsi.exec():
                new_supply_id = nsi.lastInsertId()
                # Create stock batch record
                if row[4]:  # purchase_date
                    stk = QSqlQuery(db)
                    queries.append(stk)
                    stk.prepare("INSERT INTO stocks (supply_id, supplier_id, purchase_date, quantity) VALUES (?, ?, ?, ?)")
                    stk.addBindValue(new_supply_id)
                    stk.addBindValue(supplier_id)
                    stk.addBindValue(str(row[4] or ""))
                    stk.addBindValue(row[8] or 0)
                    stk.exec()

    # Migrate receipts (snapshot first for the same reason as supplies).
    if query.exec(f"SELECT id, visit_id, client_id, receipt_date, total_amount, receipt_type, notes FROM {receipts_src}"):
        old_receipts = []
        while query.next():
            old_receipts.append([query.value(i) for i in range(query.record().count())])
        query.finish()

        for row in old_receipts:
            receipt_id = row[0]
            old_visit_id = row[1]
            old_client_id = row[2]
            receipt_date = str(row[3] or "")
            total = float(row[4] or 0.0)
            receipt_type = str(row[5] or "Sale")
            notes = str(row[6] or "")

            # Translate legacy client/visit ids through the old->new maps.
            owner_id = owner_map.get(old_client_id)
            new_visit_id = visit_map.get(old_visit_id)

            if receipt_type.upper().startswith("EXPENSE"):
                receipt_kind = "expense"
            elif new_visit_id:
                receipt_kind = "visit"
            else:
                receipt_kind = "retail"

            # Build a unique human code. The old code reused `receipt_type`
            # ("Sale"/"Expense" for every receipt), which collides with the
            # UNIQUE `receipt_code` column as soon as a database has more than
            # one receipt of a kind. Prefix by kind and suffix the legacy id.
            code_prefix = {"expense": "EXPENSE", "visit": "VISIT"}.get(
                receipt_kind, "RETAIL"
            )
            receipt_code = f"{code_prefix}-{int(receipt_id):04d}"

            ri = QSqlQuery(db)
            queries.append(ri)
            ri.prepare("""
                INSERT INTO receipts (visit_id, owner_id, receipt_date, total_price,
                                      receipt_code, receipt_kind, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """)
            ri.addBindValue(new_visit_id)
            ri.addBindValue(owner_id)
            ri.addBindValue(receipt_date)
            ri.addBindValue(total)
            ri.addBindValue(receipt_code)
            ri.addBindValue(receipt_kind)
            ri.addBindValue(notes or None)
            if ri.exec():
                new_receipt_id = ri.lastInsertId()

                # Migrate receipt items -> receipt_other.
                # Snapshot the items (with the SELECT finished) before any
                # INSERT so no active statement locks the connection.
                riq = QSqlQuery(db)
                queries.append(riq)
                riq.prepare("SELECT item_name, category, quantity, unit_price, total_price FROM receipt_items WHERE receipt_id = ?")
                riq.addBindValue(receipt_id)
                item_rows = []
                if riq.exec():
                    while riq.next():
                        item_rows.append((str(riq.value(0) or ""), float(riq.value(4) or 0.0)))
                riq.finish()

                for (item_name, amount) in item_rows:
                    ro = QSqlQuery(db)
                    queries.append(ro)
                    ro.prepare("""
                        INSERT INTO receipt_other (receipt_id, description, amount)
                        VALUES (?, ?, ?)
                    """)
                    ro.addBindValue(new_receipt_id)
                    ro.addBindValue(item_name)
                    ro.addBindValue(amount)
                    ro.exec()

    # Release every statement before dropping old tables. SQLite only allows
    # one active statement per connection; any SELECT left open (e.g. the
    # id-lookups that just read a single row) still holds a shared lock, and
    # DROP TABLE needs an exclusive lock -> 'database table is locked'.
    for q in queries:
        q.finish()

    # Drop old tables after migration. The `_legacy_*` archives are plain
    # copies (no foreign keys), so dropping them first is always safe.
    old_tables = [
        "_legacy_pets",
        "_legacy_visits",
        "_legacy_appointments",
        "_legacy_supplies",
        "_legacy_receipts",
        "clients",
        "receipt_items",
        "supply_reorder_levels",
    ]
    for tbl in old_tables:
        drop_q = QSqlQuery(db)
        if not drop_q.exec(f"DROP TABLE IF EXISTS {tbl}"):
            logger.warning(f"Failed to drop legacy table '{tbl}': {drop_q.lastError().text()}")
        drop_q.finish()

    logger.info("Legacy data migration completed successfully")
