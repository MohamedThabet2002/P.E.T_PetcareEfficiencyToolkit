"""
Supply Repository for the PET Application.
Handles persistence, retrieval, and stock management for clinic inventory.
Uses the new schema: supplies with current_stock, separate stocks table for batches.
"""

import datetime

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

_SCHEMA_VERIFIED = False

# --- CRUD Operations ---

def _ensure_schema():
    """Ensures category tables exist."""
    global _SCHEMA_VERIFIED
    if _SCHEMA_VERIFIED:
        return

    db = get_connection()
    query = QSqlQuery(db)

    # Create categories table (for dynamic categorization)
    query.exec("""
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY
        )
    """)

    # Create subcategories table
    query.exec("""
        CREATE TABLE IF NOT EXISTS subcategories (
            category_name TEXT,
            sub_name TEXT,
            PRIMARY KEY (category_name, sub_name),
            FOREIGN KEY (category_name) REFERENCES categories(name) ON DELETE CASCADE
        )
    """)

    # Migration: If categories table is empty, seed it from existing supplies
    check_q = QSqlQuery(db)
    if check_q.exec("SELECT COUNT(*) FROM categories") and check_q.next():
        if check_q.value(0) == 0:
            query.exec("INSERT OR IGNORE INTO categories (name) SELECT DISTINCT category FROM supplies WHERE category IS NOT NULL")
            query.exec("""
                INSERT OR IGNORE INTO subcategories (category_name, sub_name)
                SELECT DISTINCT category, sub_category FROM supplies
                WHERE category IS NOT NULL AND sub_category IS NOT NULL
            """)

    _SCHEMA_VERIFIED = True


def get_all_categories():
    """Retrieves all defined inventory categories from the database."""
    _ensure_schema()
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
    """Retrieves all subcategories mapped to a specific category."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT sub_name FROM subcategories WHERE category_name = ? ORDER BY sub_name ASC")
    query.addBindValue(category_name)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    if not results:
        return ["Other"]
    return results


def add_supply(item_name, category, sub_category, purchase_date=None, expiry_date=None,
               buy_price=0.0, sell_price=0.0, quantity=0, supplier=None, receipt_id=None):
    """
    Adds a new inventory item using the new schema.
    Returns (supply_id, expense_details) for the UI to handle financial logging.
    """
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

        # Create stock batch record if purchase info available
        if purchase_date and quantity > 0:
            stk = QSqlQuery(db)
            stk.prepare("INSERT INTO stocks (supply_id, purchase_date, quantity) VALUES (?, ?, ?)")
            stk.addBindValue(supply_id)
            stk.addBindValue(purchase_date)
            stk.addBindValue(quantity)
            stk.exec()

        expense_details = None
        if quantity > 0:
            expense_details = {
                "supply_id": supply_id,
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "unit_price": buy_price,
                "purchase_date": purchase_date or datetime.date.today().isoformat(),
                "supplier": supplier
            }
        return supply_id, expense_details
    return None, None


def get_existing_supply(item_name, category, sub_category, purchase_date, expiry_date, supplier):
    """Checks if a supply with identifying details already exists."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT supply_id, current_stock, buy_price, sell_price FROM supplies
        WHERE item_name = ? AND category = ? AND sub_category = ?
        AND (expiry_date = ? OR (expiry_date IS NULL AND ? IS NULL))
    """)
    query.addBindValue(item_name)
    query.addBindValue(category)
    query.addBindValue(sub_category)
    query.addBindValue(expiry_date)
    query.addBindValue(expiry_date)

    if query.exec() and query.next():
        return {
            "id": query.value(0),
            "quantity": query.value(1),
            "buy_price": query.value(2),
            "sell_price": query.value(3)
        }
    return None


def update_supply_stock(supply_id, new_quantity, buy_price=None, sell_price=None, purchase_date=None):
    """
    Updates stock levels and pricing for an existing item.
    Returns (success_bool, expense_details).
    """
    db = get_connection()

    # Fetch current state
    old_q_query = QSqlQuery(db)
    old_q_query.prepare("SELECT item_name, category, current_stock, buy_price FROM supplies WHERE supply_id = ?")
    old_q_query.addBindValue(supply_id)

    added_qty, item_name, category, buy_p = 0, "", "", 0.0
    if old_q_query.exec() and old_q_query.next():
        item_name = old_q_query.value(0)
        category = old_q_query.value(1)
        added_qty = new_quantity - (old_q_query.value(2) or 0)
        buy_p = buy_price if buy_price is not None else (old_q_query.value(3) or 0.0)

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
        if added_qty > 0:
            expense_details = {
                "supply_id": supply_id,
                "item_name": item_name,
                "category": category,
                "quantity": added_qty,
                "unit_price": buy_p,
                "purchase_date": purchase_date if purchase_date else datetime.date.today().isoformat(),
                "supplier": None
            }
        return True, expense_details
    return False, None


def update_supply(supply_id, item_name, category, sub_category, purchase_date,
                  expiry_date, buy_price, sell_price, quantity, supplier):
    """Updates all fields of a supply record."""
    db = get_connection()
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
    return query.exec()


def delete_supply(supply_id):
    """Removes a supply item from the database."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM supplies WHERE supply_id = ?")
    query.addBindValue(supply_id)
    return query.exec()


# --- Search & Filter ---

def search_supplies(category=None, text=None, filter_field="All"):
    """Searches for supplies with optional filtering."""
    db = get_connection()
    columns = [
        "supply_id", "item_name", "category", "sub_category",
        "current_stock", "expiry_date", "buy_price", "sell_price"
    ]

    base_query = f"SELECT {', '.join(columns)} FROM supplies"
    conditions, bind_values = [], []

    if category:
        conditions.append("category = ?")
        bind_values.append(category)

    if text:
        search_text = f"%{text}%"
        if filter_field == "All":
            conditions.append("(item_name LIKE ? OR sub_category LIKE ? OR category LIKE ?)")
            bind_values.extend([search_text, search_text, search_text])
        else:
            conditions.append(f"{filter_field.lower().replace(' ', '_')} LIKE ?")
            bind_values.append(search_text)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY item_name ASC"

    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)

    results = []
    if query.exec():
        while query.next():
            results.append({col: query.value(i) for i, col in enumerate(columns)})
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

def get_unique_subcategories(category):
    """Returns a distinct list of subcategories for a given category."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT DISTINCT sub_category FROM supplies WHERE category = ? ORDER BY sub_category ASC")
    query.addBindValue(category)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    return results


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
    """Calculates total stock for each item name."""
    db = get_connection()
    query = QSqlQuery(db)
    results = {}
    if query.exec("SELECT item_name, SUM(current_stock) FROM supplies GROUP BY item_name"):
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

