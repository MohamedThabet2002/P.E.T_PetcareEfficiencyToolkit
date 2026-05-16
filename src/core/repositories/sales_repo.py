"""
Sales Repository for the PET Application.
Handles data operations related to sales, expenses, and revenue analytics.
Uses the new schema: receipt_services, receipt_supplies, receipt_packages, receipt_other.
"""

import datetime
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
import src.core.repositories.supply_repo as supply_repo
from src.config import SUPPLY_CATEGORIES

logger = logging.getLogger(__name__)


def _get_period_config(period):
    """Helper to return SQL intervals and date formats based on period."""
    configs = {
        "Day": (1, "0 days", "%d/%m"),
        "Week": (7, "-6 days", "%a"),
        "Month": (30, "-29 days", "%d/%m"),
        "Year": (365, "-364 days", "%b"),
    }
    return configs.get(period, configs["Week"])


def _generate_date_series(days_back):
    """Generates a list of date objects for the last N days."""
    end = datetime.date.today()
    return [end - datetime.timedelta(days=days_back - 1 - i) for i in range(days_back)]


def get_receipt_items(text=None, filter_field="All"):
    """Retrieves receipt item records from the v_receipt_summary view."""
    db = get_connection()
    base_query = """
        SELECT receipt_id, receipt_date, owner_name, item_type, item_name,
               quantity, unit_price, line_total, total_price, receipt_code
        FROM v_receipt_summary
    """
    conditions, bind_values = [], []

    if text:
        search_text = f"%{text}%"
        fields = ["receipt_date", "item_name", "item_type", "receipt_code", "owner_name"]
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'CAST({f} AS TEXT) LIKE ?' for f in fields])})")
            bind_values.extend([search_text] * len(fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            mapping = {
                "date": "receipt_date",
                "item name": "item_name",
                "type": "item_type",
                "receipt id": "receipt_id",
                "total price": "total_price",
            }
            field = mapping.get(clean_field, clean_field)
            conditions.append(f"CAST({field} AS TEXT) LIKE ?")
            bind_values.append(search_text)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY receipt_date DESC"

    query = QSqlQuery(db)
    query.prepare(base_query)
    for val in bind_values:
        query.addBindValue(val)

    results = []
    if query.exec():
        while query.next():
            results.append({
                "id": query.value(0),
                "receipt_date": query.value(1),
                "owner_name": query.value(2),
                "item_type": query.value(3),
                "item_name": query.value(4),
                "quantity": query.value(5),
                "unit_price": query.value(6),
                "total_price": query.value(7),
                "total_amount": query.value(8),
                "receipt_id": query.value(0),
                "receipt_type": query.value(9),
                "notes": "",
            })
    return results


def add_general_expense(date, category, item_name, amount, notes=""):
    """Adds a general business expense to the ledger."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO receipts (receipt_date, total_price, receipt_code)
        VALUES (?, ?, 'Expense')
    """)
    query.addBindValue(date)
    query.addBindValue(amount)

    if query.exec():
        rid = query.lastInsertId()
        item_query = QSqlQuery(db)
        item_query.prepare("""
            INSERT INTO receipt_other (receipt_id, description, amount)
            VALUES (?, ?, ?)
        """)
        item_query.addBindValue(rid)
        item_query.addBindValue(item_name)
        item_query.addBindValue(amount)
        return item_query.exec()
    return False


def delete_receipt(receipt_id):
    """Deletes a receipt (cascade handles items)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM receipts WHERE receipt_id = ?")
    query.addBindValue(receipt_id)
    return query.exec()


def create_sale_receipt_for_quick_purchase(owner_id, receipt_date_sql, items):
    """Creates a 'Sale' receipt for the Quick Purchase flow."""
    if not items:
        return None

    db = get_connection()
    db.transaction()

    try:
        total_amount = sum([it["quantity"] * it["price"] for it in items])

        rq = QSqlQuery(db)
        rq.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code)
            VALUES (?, ?, ?, 'Sale')
        """)
        rq.addBindValue(owner_id)
        rq.addBindValue(receipt_date_sql)
        rq.addBindValue(total_amount)

        if not rq.exec():
            db.rollback()
            return None

        receipt_id = int(rq.lastInsertId())

        for it in items:
            # Check if item is a supply
            sq = QSqlQuery(db)
            sq.prepare("SELECT supply_id, sell_price FROM supplies WHERE item_name = ? LIMIT 1")
            sq.addBindValue(it["item_name"])
            if sq.exec() and sq.next():
                supply_id = sq.value(0)
                iq = QSqlQuery(db)
                iq.prepare("""
                    INSERT INTO receipt_supplies (receipt_id, supply_id, quantity, unit_price)
                    VALUES (?, ?, ?, ?)
                """)
                iq.addBindValue(receipt_id)
                iq.addBindValue(supply_id)
                iq.addBindValue(it["quantity"])
                iq.addBindValue(it["price"])
                if not iq.exec():
                    db.rollback()
                    return None

                # Deduct stock
                uq = QSqlQuery(db)
                uq.prepare("UPDATE supplies SET current_stock = current_stock - ? WHERE supply_id = ?")
                uq.addBindValue(it["quantity"])
                uq.addBindValue(supply_id)
                uq.exec()
            else:
                # Non-supply item - add to receipt_other
                oq = QSqlQuery(db)
                oq.prepare("""
                    INSERT INTO receipt_other (receipt_id, description, amount)
                    VALUES (?, ?, ?)
                """)
                oq.addBindValue(receipt_id)
                oq.addBindValue(it["item_name"])
                oq.addBindValue(it["quantity"] * it["price"])
                if not oq.exec():
                    db.rollback()
                    return None

        if not db.commit():
            db.rollback()
            return None

        return receipt_id
    except Exception as e:
        logger.error(f"Failed to create sale receipt: {e}")
        db.rollback()
        return None


def get_trend_data(data_type, period="Week"):
    """Retrieves time-series data for line charts from receipts."""
    db = get_connection()
    query = QSqlQuery(db)
    days_back, interval, date_format = _get_period_config(period)

    if data_type == "visits":
        sql = (
            "SELECT date(visit_date) as d, COUNT(*) "
            "FROM visits WHERE date(visit_date) >= date('now', '{interval}', 'localtime') "
            "GROUP BY d"
        ).format(interval=interval)
    elif data_type == "revenue":
        sql = f"""
            SELECT date(receipt_date) as d,
                   SUM(CASE WHEN receipt_code = 'Sale' THEN total_price ELSE 0 END) as revenue,
                   SUM(CASE WHEN receipt_code = 'Expense' THEN total_price ELSE 0 END) as cost
            FROM receipts
            WHERE date(receipt_date) >= date('now', '{interval}', 'localtime')
            GROUP BY d
        """
    else:
        return [], []

    data_map = {}
    if query.exec(sql):
        while query.next():
            d = query.value(0)
            data_map[d] = (
                (query.value(1) or 0, query.value(2) or 0)
                if data_type == "revenue"
                else query.value(1) or 0
            )

    labels, s1, s2, s3 = [], [], [], []

    for curr in _generate_date_series(days_back):
        ds = curr.strftime("%Y-%m-%d")
        labels.append(curr.strftime(date_format))
        if data_type == "revenue":
            rev, cost = data_map.get(ds, (0, 0))
            s1.append(rev)
            s2.append(cost)
            s3.append(rev - cost)
        else:
            s1.append(data_map.get(ds, 0))

    return (labels, s1, s2, s3) if data_type == "revenue" else (labels, s1)


def get_supplies_category_trend(period="Week"):
    """Retrieves supplies sold trend data broken down by category."""
    db = get_connection()
    query = QSqlQuery(db)
    days_back, interval, date_format = _get_period_config(period)

    sql = (
        "SELECT date(r.receipt_date) as d, s.category, SUM(rs.quantity) "
        "FROM receipt_supplies rs "
        "JOIN receipts r ON rs.receipt_id = r.receipt_id "
        "JOIN supplies s ON rs.supply_id = s.supply_id "
        "WHERE date(r.receipt_date) >= date('now', '{interval}', 'localtime') "
        "GROUP BY d, s.category"
    ).format(interval=interval)

    data_map = {}
    if query.exec(sql):
        while query.next():
            d = query.value(0)
            cat = query.value(1)
            qty = query.value(2)
            data_map.setdefault(d, {})[cat] = qty or 0

    labels = []
    categories = supply_repo.get_all_categories() or SUPPLY_CATEGORIES
    series_dict = {cat: [] for cat in categories}

    for curr in _generate_date_series(days_back):
        ds = curr.strftime("%Y-%m-%d")
        labels.append(curr.strftime(date_format))
        day_data = data_map.get(ds, {})
        for cat in categories:
            series_dict[cat].append(day_data.get(cat, 0))

    return labels, series_dict


def get_subcategory_sales_trend(category, period="Week"):
    """Retrieves subcategory sales trend data."""
    db = get_connection()
    query = QSqlQuery(db)
    days_back, interval, date_format = _get_period_config(period)

    sql = (
        "SELECT date(r.receipt_date) as d, s.sub_category, SUM(rs.quantity) "
        "FROM receipt_supplies rs "
        "JOIN receipts r ON rs.receipt_id = r.receipt_id "
        "JOIN supplies s ON rs.supply_id = s.supply_id "
        "WHERE s.category = ? "
        "AND date(r.receipt_date) >= date('now', '{interval}', 'localtime') "
        "GROUP BY d, s.sub_category"
    ).format(interval=interval)

    query.prepare(sql)
    query.addBindValue(category)

    data_map, subcategories = {}, set()
    if query.exec():
        while query.next():
            d = query.value(0)
            subcat = query.value(1) or "Other"
            subcategories.add(subcat)
            data_map.setdefault(d, {})[subcat] = query.value(2) or 0

    labels = []
    series_dict = {sc: [] for sc in subcategories}

    for curr in _generate_date_series(days_back):
        ds = curr.strftime("%Y-%m-%d")
        labels.append(curr.strftime(date_format))
        day_data = data_map.get(ds, {})
        for sc in subcategories:
            series_dict[sc].append(day_data.get(sc, 0))

    return labels, series_dict


def log_supply_purchase_expense(supply_id, item_name, category, quantity, unit_price, purchase_date, supplier, receipt_id=None):
    """Creates or updates an expense receipt when supplies are bought or restocked."""
    db = get_connection()
    total = quantity * unit_price

    if receipt_id is None:
        notes = f"Restock from {supplier}" if supplier else "Restock"
        rq = QSqlQuery(db)
        rq.prepare("""
            INSERT INTO receipts (receipt_date, total_price, receipt_code)
            VALUES (?, ?, 'Expense')
        """)
        rq.addBindValue(purchase_date)
        rq.addBindValue(total)
        if not rq.exec():
            return None
        receipt_id = int(rq.lastInsertId())
    else:
        uq = QSqlQuery(db)
        uq.prepare("UPDATE receipts SET total_price = total_price + ? WHERE receipt_id = ?")
        uq.addBindValue(total)
        uq.addBindValue(receipt_id)
        uq.exec()

    riq = QSqlQuery(db)
    riq.prepare("""
        INSERT INTO receipt_other (receipt_id, description, amount)
        VALUES (?, ?, ?)
    """)
    riq.addBindValue(receipt_id)
    riq.addBindValue(f"{item_name} (Bought)")
    riq.addBindValue(total)

    if riq.exec():
        return receipt_id
    return None


def sync_supply_metadata_to_receipts(supply_id, receipt_id, item_name, category, buy_price, sell_price, date, supplier):
    """Synchronizes metadata changes from a supply item to its associated ledger entries."""
    # In the new schema, supply prices are stored in the supplies table,
    # and receipt_supplies records store unit_price at time of sale.
    # This function is kept for compatibility but simplified.
    pass

