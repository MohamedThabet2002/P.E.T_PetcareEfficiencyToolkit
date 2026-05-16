"""
Analytics Repository for the PET Application.
Provides data aggregation for charts, KPIs, and dashboard widgets.
Uses the new database schema.
"""
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.repositories.analytics_cache import get_cache, invalidate_analytics_cache
from src.core.repositories.sales_repo import get_trend_data as get_sales_trend_data, get_supplies_category_trend, get_subcategory_sales_trend

logger = logging.getLogger(__name__)

_CACHE = get_cache()


def get_trend_data(data_type, period):
    """Dispatcher to handle different types of trend data with different return signatures."""
    cached = _CACHE.get("get_trend_data", data_type, period)
    if cached is not None:
        return cached

    if data_type == 'visits':
        result = get_visits_trend_data(period)
    else:
        result = get_sales_trend_data(data_type, period)

    _CACHE.set(result, "get_trend_data", data_type, period)
    return result


# --- KPI Data Functions ---

def get_total_visits(period="All"):
    """Calculates the total number of visits for a given period."""
    cached = _CACHE.get("get_total_visits", period)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = "SELECT COUNT(*) FROM visits"
    interval = {
        "Day": "0 days",
        "Week": "-6 days",
        "Month": "start of month",
        "Year": "start of year"
    }.get(period)
    if interval:
        sql += " WHERE date(visit_date) >= date('now', ?, 'localtime')"
        query.prepare(sql)
        query.addBindValue(interval)
    else:
        query.prepare(sql)

    if query.exec() and query.next():
        val = query.value(0)
        try:
            result = int(val) if val is not None and val != "" else 0
            _CACHE.set(result, "get_total_visits", period)
            return result
        except (ValueError, TypeError):
            return 0
    logger.error(f"Failed to get total visits for period '{period}': {query.lastError().text()}")
    return 0


def get_total_revenue(period="All"):
    """Calculates total revenue from sales for a given period."""
    cached = _CACHE.get("get_total_revenue", period)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = "SELECT SUM(total_price) FROM receipts WHERE receipt_code = 'Sale'"
    interval = {
        "Day": "0 days",
        "Week": "-6 days",
        "Month": "start of month",
        "Year": "start of year"
    }.get(period)

    if interval:
        sql += " AND date(receipt_date) >= date('now', ?, 'localtime')"
        query.prepare(sql)
        query.addBindValue(interval)
    else:
        query.prepare(sql)

    if query.exec() and query.next():
        val = query.value(0)
        try:
            result = float(val) if val is not None and val != "" else 0.0
            _CACHE.set(result, "get_total_revenue", period)
            return result
        except (ValueError, TypeError):
            return 0.0
    logger.error(f"Failed to get total revenue for period '{period}': {query.lastError().text()}")
    return 0.0


def get_low_stock_supplies():
    """Counts items where current_stock has reached or fallen below reorder_level."""
    cached = _CACHE.get("get_low_stock_supplies")
    if cached is not None and cached != 0:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = """
        SELECT COUNT(*) FROM supplies
        WHERE current_stock = 0
           OR (reorder_level > 0 AND current_stock <= reorder_level)
    """
    if query.exec(sql) and query.next():
        val = query.value(0)
        try:
            result = int(val) if val is not None and val != "" else 0
            _CACHE.set(result, "get_low_stock_supplies")
            return result
        except (ValueError, TypeError):
            pass
    logger.error(f"Failed to get low stock supplies: {query.lastError().text()}")
    return 0


def get_average_revenue_per_visit():
    """Calculates the average receipt total across all sales. Returns 0.0 on failure."""
    cached = _CACHE.get("get_average_revenue_per_visit")
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = "SELECT AVG(total_price) FROM receipts WHERE receipt_code = 'Sale'"
    if query.exec(sql) and query.next():
        val = query.value(0)
        try:
            return round(float(val), 2) if val is not None and val != "" else 0.0
        except (ValueError, TypeError):
            return 0.0
    logger.error(f"Failed to get average revenue per visit: {query.lastError().text()}")
    return 0.0


# --- Distribution & Trend Functions ---

def get_pet_distribution(period="All"):
    """Returns a count of pets grouped by species."""
    cached = _CACHE.get("get_pet_distribution", period)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    interval = {
        "Week": "-6 days",
        "Month": "-29 days",
        "Year": "-364 days"
    }.get(period, "0 days")

    if period == "All":
        sql = """
            SELECT sl.species_name, COUNT(DISTINCT p.pet_id)
            FROM pets p
            LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
            GROUP BY sl.species_name
        """
    else:
        sql = f"""
            SELECT sl.species_name, COUNT(DISTINCT p.pet_id)
            FROM pets p
            LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
            JOIN visits v ON p.pet_id = v.pet_id
            WHERE date(v.visit_date) >= date('now', '{interval}', 'localtime')
            GROUP BY sl.species_name
        """
    results = {}
    if query.exec(sql):
        while query.next():
            species = query.value(0)
            if species:
                results[str(species)] = int(query.value(1) or 0)
        _CACHE.set(results, "get_pet_distribution", period)
        return results

    logger.error(f"Failed to get pet distribution for period '{period}': {query.lastError().text()}")
    return {}


def get_visits_trend_data(period="Week"):
    """Retrieves time-series data for visit volume."""
    cached = _CACHE.get("get_visits_trend_data", period)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)

    if period == "Day":
        sql = "SELECT strftime('%H:00', visit_date) as label, COUNT(*) FROM visits WHERE date(visit_date) = date('now', 'localtime') GROUP BY label ORDER BY label ASC"
    else:
        interval = {
            "Week": "-6 days",
            "Month": "-29 days",
            "Year": "-364 days"
        }.get(period, "-364 days")
        if period == "Year":
            sql = "SELECT strftime('%Y-%m', visit_date) as label, COUNT(*) FROM visits WHERE date(visit_date) >= date('now', '-364 days', 'localtime') GROUP BY label ORDER BY label ASC"
        else:
            sql = f"SELECT date(visit_date) as label, COUNT(*) FROM visits WHERE date(visit_date) >= date('now', '{interval}', 'localtime') GROUP BY label ORDER BY label ASC"

    labels, values = [], []
    if query.exec(sql):
        while query.next():
            labels.append(query.value(0))
            try:
                values.append(int(query.value(1)) if query.value(1) is not None and query.value(1) != "" else 0)
            except (ValueError, TypeError):
                values.append(0)
        _CACHE.set((labels, values), "get_visits_trend_data", period)
        return labels, values

    if query.lastError().isValid():
        logger.error(f"Failed to get visits trend data for period '{period}': {query.lastError().text()}")
    return labels, values


# --- Inventory & Medical Analytics ---

def get_expiring_soon_items(days=30):
    """Retrieves supplies nearing their expiry date."""
    cached = _CACHE.get("get_expiring_soon_items", days)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = f"""
        SELECT item_name, category, expiry_date
        FROM supplies
        WHERE expiry_date >= date('now', 'localtime')
        AND expiry_date <= date('now', '+{days} days', 'localtime')
        ORDER BY expiry_date ASC
    """
    results = []
    if query.exec(sql):
        while query.next():
            results.append({"name": query.value(0), "category": query.value(1), "expiry": query.value(2)})
        _CACHE.set(results, "get_expiring_soon_items", days)
        return results

    logger.error(f"Failed to get expiring soon items ({days} days): {query.lastError().text()}")
    return []


def get_total_supplies_by_category():
    """Returns the total stock quantity available for each category."""
    cached = _CACHE.get("get_total_supplies_by_category")
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    if query.exec("SELECT category, SUM(current_stock) FROM supplies GROUP BY category ORDER BY category ASC"):
        results = []
        while query.next():
            if query.value(0):
                results.append((query.value(0), query.value(1)))
        _CACHE.set(results, "get_total_supplies_by_category")
        return results
    logger.error(f"Failed to get total supplies by category: {query.lastError().text()}")
    _CACHE.set([], "get_total_supplies_by_category")
    return []


def get_top_selling_items(limit=3):
    """Identifies the most frequently sold inventory items."""
    cached = _CACHE.get("get_top_selling_items", limit)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = f"""
        SELECT s.item_name, s.category, SUM(rs.quantity) as total_sold
        FROM receipt_supplies rs
        JOIN supplies s ON rs.supply_id = s.supply_id
        GROUP BY s.item_name, s.category
        ORDER BY total_sold DESC LIMIT ?
    """
    query.prepare(sql)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "name": query.value(0),
                "category": query.value(1),
                "sold": query.value(2)
            })
        _CACHE.set(results, "get_top_selling_items", limit)
    return results


def get_common_diagnoses(limit=3):
    """Aggregates most frequent diagnoses recorded this month."""
    cached = _CACHE.get("get_common_diagnoses", limit)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    sql = f"""
        SELECT diagnosis, COUNT(*) as count
        FROM visits
        WHERE diagnosis IS NOT NULL AND diagnosis != ''
        AND date(visit_date) >= date('now', 'start of month', 'localtime')
        GROUP BY diagnosis
        ORDER BY count DESC LIMIT ?
    """
    query.prepare(sql)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({"diagnosis": query.value(0), "count": query.value(1)})
        _CACHE.set(results, "get_common_diagnoses", limit)
        return results

    logger.error(f"Failed to get common diagnoses (limit={limit}): {query.lastError().text()}")
    return results


def get_supplies_numbers_for_each_category(category):
    """Returns list of (item_name, quantity) pairs for a specific inventory category."""
    cached = _CACHE.get("get_supplies_numbers_for_each_category", category)
    if cached is not None:
        return cached
    db = get_connection()

    query = QSqlQuery(db)
    query.prepare("SELECT item_name, current_stock FROM supplies WHERE category = ? ORDER BY current_stock DESC")
    query.addBindValue(category)
    results = []
    if query.exec():
        while query.next():
            results.append((query.value(0), query.value(1)))
        _CACHE.set(results, "get_supplies_numbers_for_each_category", category)
        return results

    logger.error(f"Failed to get supplies for category '{category}': {query.lastError().text()}")
    return results

