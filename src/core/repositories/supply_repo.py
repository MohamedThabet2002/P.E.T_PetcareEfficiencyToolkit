"""
Supply Repository for the PET Application.
Handles persistence, retrieval, and stock management for clinic inventory.
Uses the new schema: supplies with current_stock, separate stocks table for batches.
"""

import datetime

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.repositories import stock_repo, supplier_repo

# --- CRUD Operations ---

def get_all_categories():
    """Retrieves all defined inventory categories from the database."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT name FROM categories ORDER BY name ASC"):
        while query.next():
            results.append(query.value(0))
    if not results and query.exec("SELECT DISTINCT category FROM supplies"):
        while query.next():
            results.append(query.value(0))
    return results


def add_category(name):
    """Adds a new category to the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO categories (name) VALUES (?)")
    query.addBindValue(name)
    return query.exec()


def delete_category(name):
    """Removes a category and its subcategory mappings."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM categories WHERE name = ?")
    query.addBindValue(name)
    return query.exec()


def add_subcategory(category_name, sub_name):
    """Adds a new subcategory mapping to the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO subcategories (category_name, sub_name) VALUES (?, ?)")
    query.addBindValue(category_name)
    query.addBindValue(sub_name)
    return query.exec()


def delete_subcategory(category_name, sub_name):
    """Removes a subcategory mapping from the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM subcategories WHERE category_name = ? AND sub_name = ?")
    query.addBindValue(category_name)
    query.addBindValue(sub_name)
    return query.exec()


def get_subcategories_by_category(category_name):
    """Retrieves all subcategories mapped to a specific category.

    The generic "Other" bucket is always included so items saved without an
    explicit sub-category (or before one was added) never become unreachable
    once a category gains its own sub-categories.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT sub_name FROM subcategories WHERE category_name = ? ORDER BY sub_name ASC")
    query.addBindValue(category_name)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    if "Other" not in results:
        results.append("Other")
    return results


def add_supply(item_name, category, sub_category, purchase_date=None, expiry_date=None,
               buy_price=0.0, sell_price=0.0, quantity=0, supplier=None, receipt_id=None,
               audit_user_id=None):
    """
    Adds a new inventory item using the new schema.
    Returns (supply_id, expense_details) for the UI to handle financial logging.

    Item names are unique per category: when the item already exists the quantity
    is added as an extra stock batch instead of creating a duplicate row.
    """
    existing = get_existing_supply(item_name, category)
    if existing:
        updated, expense_details = update_supply_stock(
            existing["supply_id"], (existing["current_stock"] or 0) + quantity,
            buy_price=buy_price, sell_price=sell_price,
            purchase_date=purchase_date, supplier=supplier,
        )
        if not updated:
            return None, None
        if audit_user_id is not None:
            from src.core.repositories.audit_repo import record_action
            record_action("RESTOCK", "supplies", existing["supply_id"],
                          changes=[{"field_name": "quantity", "old_value": str(existing["current_stock"] or 0),
                                    "new_value": str((existing["current_stock"] or 0) + quantity)}],
                          user_id=audit_user_id)
        return existing["supply_id"], expense_details

    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO supplies (item_name, category, sub_category, current_stock, expiry_date, buy_price, sell_price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(item_name)
    query.addBindValue(category)
    query.addBindValue(sub_category)
    query.addBindValue(quantity)
    query.addBindValue(expiry_date)
    query.addBindValue(buy_price)
    query.addBindValue(sell_price)

    if query.exec():
        supply_id = int(query.lastInsertId())
        if audit_user_id is not None:
            from src.core.repositories.audit_repo import record_action
            record_action("ADD", "supplies", supply_id,
                          changes=[{"field_name": "item_name", "old_value": "", "new_value": item_name or ""}],
                          user_id=audit_user_id)

        # Create stock batch record if purchase info available
        batch_id = None
        if quantity > 0:
            batch_id = _add_stock_batch(db, supply_id, quantity,
                                        purchase_date or datetime.date.today().isoformat(), supplier,
                                        expiry_date=expiry_date, buy_price=buy_price)

        expense_details = None
        if quantity > 0:
            expense_details = {
                "supply_id": supply_id,
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "unit_price": buy_price,
                "purchase_date": purchase_date or datetime.date.today().isoformat(),
                "supplier": supplier,
                # Lets the receipt log link back to the batch it bought, so a
                # later quantity correction folds into the same receipt.
                "batch_id": batch_id,
            }
        return supply_id, expense_details
    return None, None


def get_existing_supply(item_name, category, sub_category=None, purchase_date=None,
                        expiry_date=None, supplier=None):
    """Finds an existing supply by item name within a category.

    Item names are unique per category, so only ``item_name`` + ``category`` are
    matched (case-insensitively). The remaining arguments are kept for backward
    compatibility and are ignored.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT supply_id, current_stock, buy_price, sell_price, sub_category, expiry_date
        FROM supplies
        WHERE LOWER(item_name) = LOWER(?) AND category = ?
        ORDER BY supply_id ASC LIMIT 1
    """)
    query.addBindValue((item_name or "").strip())
    query.addBindValue(category)

    if query.exec() and query.next():
        return {
            "supply_id": query.value(0),
            "current_stock": query.value(1),
            "buy_price": query.value(2),
            "sell_price": query.value(3),
            "sub_category": query.value(4),
            "expiry_date": query.value(5),
        }
    return None


def _add_stock_batch(db, supply_id, quantity, purchase_date, supplier,
                     expiry_date=None, buy_price=None):
    """Records a stock batch for a purchase, linking the supplier when known.

    The batch inherits the item's expiry date and buy price so it can be edited
    per batch afterwards (each batch owns its own values).
    """
    stk = QSqlQuery(db)
    stk.prepare("""
        INSERT INTO stocks (supply_id, supplier_id, purchase_date, expiry_date, buy_price, quantity)
        VALUES (?, ?, ?, ?, ?, ?)
    """)
    stk.addBindValue(supply_id)
    stk.addBindValue(supplier_repo.get_or_create_supplier(supplier))
    stk.addBindValue(purchase_date)
    stk.addBindValue(expiry_date)
    stk.addBindValue(buy_price)
    stk.addBindValue(quantity)
    if not stk.exec():
        return None
    # Every batch that reaches the shelf leaves a trace in the ledger, so a
    # movement log is not missing the purchases the app itself made.
    stock_repo.record_movement(
        db, supply_id, "purchase", quantity,
        notes=f"Purchase from {supplier}".strip() if supplier else "Purchase")
    # The caller still has to create the expense receipt; handing back the
    # batch id lets it link the two (see sales_repo.log_supply_purchase_expense).
    return int(stk.lastInsertId())


def update_supply_stock(supply_id, new_quantity, buy_price=None, sell_price=None,
                        purchase_date=None, supplier=None):
    """
    Updates stock levels and pricing for an existing item, recording the added
    quantity as a new stock batch so purchase history (and supplier) is kept.
    Returns (success_bool, expense_details).
    """
    db = get_connection()

    # Fetch current state
    old_q_query = QSqlQuery(db)
    old_q_query.prepare(
        "SELECT item_name, category, current_stock, buy_price, expiry_date "
        "FROM supplies WHERE supply_id = ?")
    old_q_query.addBindValue(supply_id)

    added_qty, item_name, category, buy_p = 0, "", "", 0.0
    expiry_p = None
    if old_q_query.exec() and old_q_query.next():
        item_name = old_q_query.value(0)
        category = old_q_query.value(1)
        added_qty = new_quantity - (old_q_query.value(2) or 0)
        buy_p = buy_price if buy_price is not None else (old_q_query.value(3) or 0.0)
        expiry_p = old_q_query.value(4)

    fields = ["current_stock = ?"]
    values = [new_quantity]
    if buy_price is not None:
        fields.append("buy_price = ?")
        values.append(buy_price)
    if sell_price is not None:
        fields.append("sell_price = ?")
        values.append(sell_price)

    query = QSqlQuery(db)
    query.prepare(f"UPDATE supplies SET {', '.join(fields)} WHERE supply_id = ?")
    for v in values:
        query.addBindValue(v)
    query.addBindValue(supply_id)

    if query.exec():
        expense_details = None
        batch_id = None
        if added_qty > 0:
            purchase_day = purchase_date or datetime.date.today().isoformat()
            batch_id = _add_stock_batch(db, supply_id, added_qty, purchase_day, supplier,
                                        expiry_date=expiry_p, buy_price=buy_p)
            expense_details = {
                "supply_id": supply_id,
                "item_name": item_name,
                "category": category,
                "quantity": added_qty,
                "unit_price": buy_p,
                "purchase_date": purchase_day,
                "supplier": (supplier or "").strip() or None,
                "batch_id": batch_id,
            }
        return True, expense_details
    return False, None


def update_supply(supply_id, item_name, category, sub_category, purchase_date,
                  expiry_date, buy_price, sell_price, quantity, supplier, audit_user_id=None):
    """Updates all fields of a supply record."""
    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT item_name, category, sub_category, current_stock, expiry_date, buy_price, sell_price
        FROM supplies WHERE supply_id = ?
    """)
    oq.addBindValue(supply_id)
    if oq.exec() and oq.next():
        old_row = {
            "item_name": oq.value(0) or "",
            "category": oq.value(1) or "",
            "sub_category": oq.value(2) or "",
            "current_stock": oq.value(3) or "",
            "expiry_date": oq.value(4) or "",
            "buy_price": oq.value(5) or "",
            "sell_price": oq.value(6) or "",
        }

    query = QSqlQuery(db)
    query.prepare("""
        UPDATE supplies SET item_name = ?, category = ?, sub_category = ?,
        current_stock = ?, expiry_date = ?, buy_price = ?, sell_price = ?
        WHERE supply_id = ?
    """)
    query.addBindValue(item_name)
    query.addBindValue(category)
    query.addBindValue(sub_category)
    query.addBindValue(quantity)
    query.addBindValue(expiry_date)
    query.addBindValue(buy_price)
    query.addBindValue(sell_price)
    query.addBindValue(supply_id)
    result = query.exec()
    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        record_action("UPDATE", "supplies", supply_id,
                      changes=field_diffs(old_row, {
                          "item_name": item_name or "",
                          "category": category or "",
                          "sub_category": sub_category or "",
                          "current_stock": quantity or "",
                          "expiry_date": expiry_date or "",
                          "buy_price": buy_price or "",
                          "sell_price": sell_price or "",
                      }) or None,
                      user_id=audit_user_id)
    return result


def update_supply_details(supply_id, item_name=None, category=None, sub_category=None,
                          expiry_date=None, buy_price=None, sell_price=None,
                          audit_user_id=None):
    """Updates only the supplied fields of a supply record.

    ``None`` means "leave unchanged", so a narrow editor (e.g. the item details
    expiry date) never clobbers the other columns. ``category`` moves the item
    to another category tab. Returns success_bool.
    """
    updates = {
        "item_name": item_name,
        "category": category,
        "sub_category": sub_category,
        "expiry_date": expiry_date,
        "buy_price": buy_price,
        "sell_price": sell_price,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return True

    db = get_connection()
    old_row = {}
    oq = QSqlQuery(db)
    oq.prepare("""
        SELECT item_name, sub_category, expiry_date, buy_price, sell_price, category
        FROM supplies WHERE supply_id = ?
    """)
    oq.addBindValue(supply_id)
    if oq.exec() and oq.next():
        old_row = {
            "item_name": oq.value(0) or "",
            "sub_category": oq.value(1) or "",
            "expiry_date": oq.value(2) or "",
            "buy_price": oq.value(3) or 0.0,
            "sell_price": oq.value(4) or 0.0,
            "category": oq.value(5) or "",
        }
        # The resulting (name, category) pair must stay unique: renaming, or
        # moving the item into a category that already has that name, collides.
        if "item_name" in updates or "category" in updates:
            target_category = updates.get("category") or old_row.get("category")
            target_name = updates.get("item_name") or old_row.get("item_name")
            clash = get_existing_supply(target_name, target_category)
            if clash and clash["supply_id"] != supply_id:
                return False

    assignments = ", ".join(f"{column} = ?" for column in updates)
    query = QSqlQuery(db)
    query.prepare(f"UPDATE supplies SET {assignments} WHERE supply_id = ?")
    for value in updates.values():
        query.addBindValue(value)
    query.addBindValue(supply_id)
    result = query.exec()

    if result and audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        new_row = dict(old_row)
        new_row.update(updates)
        record_action("UPDATE", "supplies", supply_id,
                      changes=field_diffs(old_row, new_row) or None,
                      user_id=audit_user_id)
    return result


def delete_supply(supply_id, audit_user_id=None):
    """Removes a supply item from the database."""
    from src.core.repositories import undo_repo
    db = get_connection()
    old_name = ""
    oq = QSqlQuery(db)
    oq.prepare("SELECT item_name FROM supplies WHERE supply_id = ?")
    oq.addBindValue(supply_id)
    if oq.exec() and oq.next():
        old_name = oq.value(0) or ""
    # Capture snapshot before delete so the full subtree is preserved.
    snapshot = undo_repo.capture_snapshot("supplies", supply_id)
    query = QSqlQuery(db)
    query.prepare("DELETE FROM supplies WHERE supply_id = ?")
    query.addBindValue(supply_id)
    result = query.exec()
    if result:
        if snapshot is not None:
            undo_repo.record_deletion("supplies", supply_id, snapshot, user_id=audit_user_id)
        if audit_user_id is not None:
            from src.core.repositories.audit_repo import record_action
            record_action("DELETE", "supplies", supply_id,
                          changes=[{"field_name": "item_name", "old_value": old_name, "new_value": ""}],
                          user_id=audit_user_id)
    return result


# --- Search & Filter ---

def search_supplies(category=None, text=None, filter_field="All"):
    """Searches for supplies with optional filtering.

    Every row carries both stock numbers: ``current_stock`` is the live stock
    (what is left after sales) and ``batch_quantity`` is the total across the
    item's stock batches (what has been purchased). The supplies page shows the
    batch total so it always matches the Stock Batches dialog.
    """
    db = get_connection()
    base_query = """
        SELECT s.supply_id, s.item_name, s.category, s.sub_category,
               s.current_stock, s.expiry_date, s.buy_price, s.sell_price,
               (SELECT st2.purchase_date FROM stocks st2 WHERE st2.supply_id = s.supply_id ORDER BY st2.purchase_date DESC LIMIT 1) AS purchase_date,
               (SELECT sup2.supplier_name FROM stocks st3 LEFT JOIN suppliers sup2 ON st3.supplier_id = sup2.supplier_id WHERE st3.supply_id = s.supply_id ORDER BY st3.purchase_date DESC LIMIT 1) AS supplier_name,
               (SELECT COALESCE(SUM(st4.quantity), 0) FROM stocks st4 WHERE st4.supply_id = s.supply_id) AS batch_quantity
        FROM supplies s
    """
    conditions, bind_values = [], []

    if category:
        conditions.append("s.category = ?")
        bind_values.append(category)

    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append("(s.item_name LIKE ? OR s.sub_category LIKE ? OR s.category LIKE ?)")
            bind_values.extend([search_text, search_text, search_text])
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            allowed_columns = {
                "item_name": "s.item_name",
                "category": "s.category",
                "sub_category": "s.sub_category",
                "current_stock": "s.current_stock",
                "expiry_date": "s.expiry_date",
                "buy_price": "s.buy_price",
                "sell_price": "s.sell_price",
            }
            column_sql = allowed_columns.get(clean_field)
            if column_sql is None:
                conditions.append("s.sub_category = ?")
                bind_values.append(filter_field)
            else:
                conditions.append(f"{column_sql} LIKE ?")
                bind_values.append(search_text)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY s.item_name ASC"

    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "supply_id": query.value(0),
                "item_name": query.value(1),
                "category": query.value(2),
                "sub_category": query.value(3),
                "current_stock": query.value(4),
                "expiry_date": query.value(5),
                "buy_price": query.value(6),
                "sell_price": query.value(7),
                "purchase_date": query.value(8),
                "supplier": query.value(9),
                # Sum of the item's stock batches (total purchased).
                "batch_quantity": query.value(10) or 0,
            })
    return results


def update_supply_quantity(supply_id, new_quantity):
    """Directly updates the quantity of a specific supply item."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE supplies SET current_stock = ? WHERE supply_id = ?")
    query.addBindValue(new_quantity)
    query.addBindValue(supply_id)
    return query.exec()


# --- Specialized Lookups ---

def get_all_reorder_levels():
    """Retrieves all per-item reorder levels."""
    db = get_connection()
    query = QSqlQuery(db)
    results = {}
    if query.exec("SELECT item_name, reorder_level FROM supplies WHERE reorder_level > 0"):
        while query.next():
            results[query.value(0)] = query.value(1)
    return results


def get_total_quantities_by_item():
    """Calculates the total batch quantity for each item name.

    Mirrors the Quantity column (the batch total, not the live stock) so the
    out-of-stock / low-stock row highlighting matches the number on screen.
    """
    db = get_connection()
    query = QSqlQuery(db)
    results = {}
    sql = """
        SELECT s.item_name, COALESCE(SUM(st.quantity), 0)
        FROM supplies s LEFT JOIN stocks st ON st.supply_id = s.supply_id
        GROUP BY s.item_name
    """
    if query.exec(sql):
        while query.next():
            results[query.value(0)] = query.value(1)
    return results


def set_reorder_level(item_name, level):
    """Sets or updates the reorder level for a specific item name."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE supplies SET reorder_level = ? WHERE item_name = ?")
    query.addBindValue(level)
    query.addBindValue(item_name)
    return query.exec()


def update_supply_receipt(supply_id, receipt_id):
    """No longer needed in new schema - kept for compatibility."""
    return True


def get_items_by_subcategory(category, sub_category):
    """Returns available item names filtered by subcategory."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT DISTINCT item_name FROM supplies WHERE category = ? AND sub_category = ? ORDER BY item_name ASC")
    query.addBindValue(category)
    query.addBindValue(sub_category)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    return results


def resolve_supply_id(item_name, category=None):
    """Returns the supply_id matching an item name (and optional category), or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "SELECT supply_id FROM supplies WHERE item_name = ? "
        "AND (? IS NULL OR category = ?) ORDER BY supply_id LIMIT 1"
    )
    query.addBindValue(item_name)
    query.addBindValue(category)
    query.addBindValue(category)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_sell_price(item_name, category=None):
    """Returns the current sell price for an item name (within a category if given)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "SELECT sell_price FROM supplies "
        "WHERE item_name = ? AND (? IS NULL OR category = ?) LIMIT 1"
    )
    query.addBindValue(item_name)
    query.addBindValue(category)
    query.addBindValue(category)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_unique_supply_names(category):
    """Returns all unique item names within a category."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT DISTINCT item_name FROM supplies WHERE category = ? ORDER BY item_name ASC")
    query.addBindValue(category)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    return results


def get_all_unique_item_names():
    """Returns a distinct list of all item names."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT DISTINCT item_name, category, sub_category FROM supplies ORDER BY category, sub_category, item_name"):
        while query.next():
            results.append((query.value(0), query.value(1), query.value(2)))
    return results


# --- Species & Services (Legacy compatibility wrappers) ---

def get_all_species():
    """Get all species from species_lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    res = []
    if query.exec("SELECT species_name FROM species_lookup ORDER BY species_name ASC"):
        while query.next():
            res.append(query.value(0))
    return res


def get_all_species_with_ids():
    """Get all species as ``(species_id, species_name)`` ordered by name.

    Combos that must store the real ``species_id`` (e.g. vaccine schedules)
    need the id, not just the name - see ``get_all_species``.
    """
    db = get_connection()
    query = QSqlQuery(db)
    res = []
    if query.exec("SELECT species_id, species_name FROM species_lookup ORDER BY species_name ASC"):
        while query.next():
            res.append((query.value(0), query.value(1)))
    return res


def add_species(name):
    """Add a new species."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO species_lookup (species_name) VALUES (?)")
    query.addBindValue(name)
    return query.exec()


def delete_species(name):
    """Delete a species."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM species_lookup WHERE species_name = ?")
    query.addBindValue(name)
    return query.exec()


def get_all_services():
    """Get all services from services_lookup table."""
    db = get_connection()
    query = QSqlQuery(db)
    res = []
    if query.exec("SELECT service_name FROM services_lookup ORDER BY service_name ASC"):
        while query.next():
            res.append(query.value(0))
    return res


def add_service(name):
    """Add a new service."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("INSERT OR IGNORE INTO services_lookup (service_name) VALUES (?)")
    query.addBindValue(name)
    return query.exec()


def delete_service(name):
    """Delete a service."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM services_lookup WHERE service_name = ?")
    query.addBindValue(name)
    return query.exec()


def get_or_create_service(name):
    """Resolves a service name to its id, creating the lookup row when absent."""
    clean = (name or "").strip()
    if not clean:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT service_id FROM services_lookup WHERE LOWER(service_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    add_service(clean)
    query.prepare("SELECT service_id FROM services_lookup WHERE LOWER(service_name) = LOWER(?)")
    query.addBindValue(clean)
    if query.exec() and query.next():
        return int(query.value(0))
    return None

