"""
Analytics Repository for the PET Application.
Provides data aggregation for charts, KPIs, and dashboard widgets.
Uses the new database schema.
"""
import logging

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.repositories.analytics_cache import get_cache, invalidate_analytics_cache
from src.core.repositories.sales_repo import (
    _trend_bucket,
    _trend_date_series,
    get_revenue_trend_range,
    get_supplies_category_trend_range,
    get_subcategory_sales_trend_range,
    get_trend_data as get_sales_trend_data,
    get_supplies_category_trend,
    get_subcategory_sales_trend,
)
from src.utils.i18n import tr

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
    sql = "SELECT SUM(total_price) FROM receipts WHERE COALESCE(receipt_kind, 'retail') <> 'expense'"
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


def get_month_over_month():
    """Calculates this month vs last month totals for visits and revenue.

    Uses calendar months (start of month .. now for the current month; the
    full previous calendar month for comparison). Revenue counts all receipts
    whose kind is not ``expense``. Returns a dict with
    keys ``visits_this_month`` / ``visits_last_month`` and
    ``revenue_this_month`` / ``revenue_last_month``.
    """
    db = get_connection()

    query = QSqlQuery(db)
    sql = """
        SELECT
            SUM(CASE WHEN date(visit_date) >= date('now', 'start of month', 'localtime')
                     THEN 1 ELSE 0 END) AS this_month,
            SUM(CASE WHEN date(visit_date) >= date('now', 'start of month', '-1 month', 'localtime')
                     AND date(visit_date) < date('now', 'start of month', 'localtime')
                     THEN 1 ELSE 0 END) AS last_month
        FROM visits
    """
    result = {
        "visits_this_month": 0,
        "visits_last_month": 0,
        "revenue_this_month": 0.0,
        "revenue_last_month": 0.0,
    }
    if query.exec(sql) and query.next():
        try:
            result["visits_this_month"] = int(query.value(0) or 0)
            result["visits_last_month"] = int(query.value(1) or 0)
        except (ValueError, TypeError):
            pass

    query2 = QSqlQuery(db)
    sql2 = """
        SELECT
            COALESCE(SUM(CASE WHEN date(receipt_date) >= date('now', 'start of month', 'localtime')
                     THEN total_price ELSE 0 END), 0) AS this_month,
            COALESCE(SUM(CASE WHEN date(receipt_date) >= date('now', 'start of month', '-1 month', 'localtime')
                     AND date(receipt_date) < date('now', 'start of month', 'localtime')
                     THEN total_price ELSE 0 END), 0) AS last_month
        FROM receipts
        WHERE COALESCE(receipt_kind, 'retail') <> 'expense'
    """
    if query2.exec(sql2) and query2.next():
        try:
            result["revenue_this_month"] = float(query2.value(0) or 0.0)
            result["revenue_last_month"] = float(query2.value(1) or 0.0)
        except (ValueError, TypeError):
            pass
    return result


def get_low_stock_supplies():
    """Counts items where current_stock has reached or fallen below reorder_level."""
    cached = _CACHE.get("get_low_stock_supplies")
    if cached is not None:
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
    sql = "SELECT AVG(total_price) FROM receipts WHERE COALESCE(receipt_kind, 'retail') <> 'expense'"
    if query.exec(sql) and query.next():
        val = query.value(0)
        try:
            result = round(float(val), 2) if val is not None and val != "" else 0.0
        except (ValueError, TypeError):
            result = 0.0
        _CACHE.set(result, "get_average_revenue_per_visit")
        return result
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


def get_visits_trend_range(start="", end=""):
    """Time-series of visit counts within an explicit date range."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("visit_date", start, end)
    if where:
        where = where.replace("AND ", "WHERE ", 1)
    bucket = _trend_bucket(start, end)
    if bucket == "hourly":
        select = "strftime('%H:00', visit_date)"
    elif bucket == "monthly":
        select = "strftime('%Y-%m', visit_date)"
    else:
        select = "date(visit_date)"
    sql = f"SELECT {select} as label, COUNT(*) FROM visits {where} GROUP BY label ORDER BY label ASC"
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)

    data = {}
    if query.exec():
        while query.next():
            data[query.value(0)] = int(query.value(1) or 0)

    labels, values = [], []
    for key, label in _trend_date_series(start, end):
        labels.append(label)
        values.append(data.get(key, 0))
    return labels, values


def get_pet_distribution_range(start="", end=""):
    """Pets visited within [start, end], grouped by species."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("v.visit_date", start, end)
    if where:
        where = where.replace("AND ", "WHERE ", 1)
    sql = (
        "SELECT sl.species_name, COUNT(DISTINCT p.pet_id) "
        "FROM pets p "
        "LEFT JOIN species_lookup sl ON p.species_id = sl.species_id "
        "JOIN visits v ON p.pet_id = v.pet_id"
        + where
        + " GROUP BY sl.species_name"
    )
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)

    results = {}
    if query.exec():
        while query.next():
            species = query.value(0)
            if species:
                results[str(species)] = int(query.value(1) or 0)
    return results


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


def get_clinical_activity_summary():
    """Returns per-doctor clinical activity rows used by the Patient report.

    Each row is a list of ``[doctor_name, visits, followups, unassigned_visits]``.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COALESCE(d.first_name || ' ' || d.last_name, ?),
               COUNT(DISTINCT v.visit_id),
               COUNT(DISTINCT f.followup_id),
               CASE WHEN v.doctor_id IS NULL THEN COUNT(DISTINCT v.visit_id) ELSE 0 END
        FROM visits v
        LEFT JOIN doctors d ON d.doctor_id = v.doctor_id
        LEFT JOIN followups f ON f.doctor_id = v.doctor_id
        GROUP BY v.doctor_id, d.first_name, d.last_name
        ORDER BY d.last_name, d.first_name
    """)
    query.addBindValue(tr("Unassigned"))
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(i) for i in range(4)])
    return rows


def _period_interval(period):
    """SQL interval suffix for 'now' used by the period-aware report queries."""
    return {
        "Day": "0 days",
        "Week": "-6 days",
        "Month": "start of month",
        "Year": "start of year",
    }.get(period)


def get_total_supplies_used(period="All"):
    """Returns total quantity of inventory sold through sales receipts.

    "period" may be Day/Week/Month/Year; anything else (e.g. "All") means all time.
    """
    cached = _CACHE.get("get_total_supplies_used", period)
    if cached is not None:
        return cached
    db = get_connection()
    query = QSqlQuery(db)
    sql = """
        SELECT COALESCE(SUM(rs.quantity), 0)
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        WHERE COALESCE(r.receipt_kind, 'retail') <> 'expense'
    """
    interval = _period_interval(period)
    if interval:
        sql += " AND date(r.receipt_date) >= date('now', ?, 'localtime')"
        query.prepare(sql)
        query.addBindValue(interval)
    else:
        query.prepare(sql)

    if query.exec() and query.next():
        val = query.value(0)
        try:
            result = int(val) if val is not None and val != "" else 0
            _CACHE.set(result, "get_total_supplies_used", period)
            return result
        except (ValueError, TypeError):
            return 0
    logger.error(f"Failed to get total supplies used for period '{period}': {query.lastError().text()}")
    return 0


def get_visits_by_doctor(period="All"):
    """Returns rows of [doctor_name, visit_count] for a period (or all time).

    Unassigned visits roll up under a single translated "Unassigned" doctor.
    """
    db = get_connection()
    query = QSqlQuery(db)
    sql = """
        SELECT COALESCE(d.first_name || ' ' || d.last_name, ?), COUNT(DISTINCT v.visit_id)
        FROM visits v
        LEFT JOIN doctors d ON d.doctor_id = v.doctor_id
    """
    interval = _period_interval(period)
    if interval:
        sql += " WHERE date(v.visit_date) >= date('now', ?, 'localtime')"
    sql += " GROUP BY v.doctor_id, d.first_name, d.last_name ORDER BY 2 DESC, 1 ASC"
    query.prepare(sql)
    query.addBindValue(tr("Unassigned"))
    if interval:
        query.addBindValue(interval)
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), int(query.value(1) or 0)])
    return rows


def get_revenue_by_category(period="All"):
    """Returns rows of [category, amount] describing revenue composition.

    Supply lines are bucketed by inventory category; services, packages and
    other line items get their own fixed buckets.
    """
    db = get_connection()
    query = QSqlQuery(db)
    interval = _period_interval(period)
    where = ""
    if interval:
        where = "AND date(receipt_date) >= date('now', ?, 'localtime')"
    sql = """
        WITH sale_r AS (
            SELECT receipt_id, receipt_date FROM receipts
            WHERE COALESCE(receipt_kind, 'retail') <> 'expense' {where}
        )
        SELECT category, SUM(line_total) FROM (
            SELECT COALESCE(s.category, ?) AS category,
                   rs.quantity * rs.unit_price AS line_total
            FROM receipt_supplies rs
            JOIN sale_r r ON rs.receipt_id = r.receipt_id
            LEFT JOIN supplies s ON rs.supply_id = s.supply_id
            UNION ALL
            SELECT ?, rs.quantity * rs.unit_price
            FROM receipt_services rs
            JOIN sale_r r ON rs.receipt_id = r.receipt_id
            UNION ALL
            SELECT ?, rp.quantity * pkg.total_price
            FROM receipt_packages rp
            JOIN sale_r r ON rp.receipt_id = r.receipt_id
            JOIN packages pkg ON rp.package_id = pkg.package_id
            UNION ALL
            SELECT ?, ro.quantity * ro.unit_price
            FROM receipt_other ro
            JOIN sale_r r ON ro.receipt_id = r.receipt_id
        ) GROUP BY category ORDER BY SUM(line_total) DESC
    """.format(where=where)
    query.prepare(sql)
    if interval:
        query.addBindValue(interval)
    query.addBindValue(tr("Unknown Category"))
    query.addBindValue(tr("Services"))
    query.addBindValue(tr("Packages"))
    query.addBindValue(tr("Other"))
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), float(query.value(1) or 0.0)])
    return rows


def get_supply_usage(period="All", limit=8):
    """Returns rows of [item_name, category, quantity] of the most-used inventory.

    Limit applies to the number of top items returned, not quantities.
    """
    db = get_connection()
    query = QSqlQuery(db)
    sql = """
        SELECT s.item_name, s.category, SUM(rs.quantity) AS qty
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        JOIN supplies s ON rs.supply_id = s.supply_id
        WHERE COALESCE(r.receipt_kind, 'retail') <> 'expense'
    """
    interval = _period_interval(period)
    if interval:
        sql += " AND date(r.receipt_date) >= date('now', ?, 'localtime')"
    sql += " GROUP BY s.item_name, s.category ORDER BY qty DESC, s.item_name ASC LIMIT ?"
    query.prepare(sql)
    if interval:
        query.addBindValue(interval)
    query.addBindValue(limit)
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), query.value(1), int(query.value(2) or 0)])
    return rows


# --- Date-range variants (calendar-powered reports) ---

def _date_conditions(column, start, end):
    """Builds (where_clause, binds) restricting ``date(<column>)`` to [start, end].

    start/end are 'YYYY-MM-DD' strings (or empty for unbounded). Returns an empty
    clause when neither bound is given.
    """
    conds, binds = [], []
    if start:
        conds.append(f"date({column}) >= date(?)")
        binds.append(start)
    if end:
        conds.append(f"date({column}) <= date(?)")
        binds.append(end)
    if not conds:
        return "", []
    where = " AND " + " AND ".join(conds)
    return where, binds


def get_total_visits_range(start="", end=""):
    """Total visits count within an explicit date range (or all time when unbounded)."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("visit_date", start, end)
    if where:
        where = where.replace("AND ", "WHERE ", 1)
    query.prepare("SELECT COUNT(*) FROM visits" + where)
    for bind in binds:
        query.addBindValue(bind)
    if query.exec() and query.next():
        val = query.value(0)
        try:
            return int(val) if val is not None and val != "" else 0
        except (ValueError, TypeError):
            return 0
    logger.error(f"Failed to get total visits range {start}..{end}: {query.lastError().text()}")
    return 0


def get_total_revenue_range(start="", end=""):
    """Total sale revenue within an explicit date range (or all time when unbounded)."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("receipt_date", start, end)
    sql = "SELECT SUM(total_price) FROM receipts WHERE COALESCE(receipt_kind, 'retail') <> 'expense'"
    if where:
        sql += where
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    if query.exec() and query.next():
        val = query.value(0)
        try:
            return float(val) if val is not None and val != "" else 0.0
        except (ValueError, TypeError):
            return 0.0
    logger.error(f"Failed to get total revenue range {start}..{end}: {query.lastError().text()}")
    return 0.0


def get_total_supplies_used_range(start="", end=""):
    """Total inventory quantity sold through sale receipts within a date range."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("r.receipt_date", start, end)
    sql = """
        SELECT COALESCE(SUM(rs.quantity), 0)
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        WHERE COALESCE(r.receipt_kind, 'retail') <> 'expense'
    """
    if where:
        sql += where
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    if query.exec() and query.next():
        val = query.value(0)
        try:
            return int(val) if val is not None and val != "" else 0
        except (ValueError, TypeError):
            return 0
    logger.error(f"Failed to get total supplies used range {start}..{end}: {query.lastError().text()}")
    return 0


def get_visits_by_doctor_range(start="", end=""):
    """Rows of [doctor_name, visit_count] within an explicit date range."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("v.visit_date", start, end)
    sql = """
        SELECT COALESCE(d.first_name || ' ' || d.last_name, ?), COUNT(DISTINCT v.visit_id)
        FROM visits v
        LEFT JOIN doctors d ON d.doctor_id = v.doctor_id
    """
    if where:
        sql += where.replace("AND ", "WHERE ", 1)
    sql += " GROUP BY v.doctor_id, d.first_name, d.last_name ORDER BY 2 DESC, 1 ASC"
    query.prepare(sql)
    query.addBindValue(tr("Unassigned"))
    for bind in binds:
        query.addBindValue(bind)
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), int(query.value(1) or 0)])
    return rows


def get_revenue_by_category_range(start="", end=""):
    """Rows of [category, amount] describing revenue within an explicit date range."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("receipt_date", start, end)
    sql = """
        WITH sale_r AS (
            SELECT receipt_id, receipt_date FROM receipts
            WHERE COALESCE(receipt_kind, 'retail') <> 'expense' {where}
        )
        SELECT category, SUM(line_total) FROM (
            SELECT COALESCE(s.category, ?) AS category,
                   rs.quantity * rs.unit_price AS line_total
            FROM receipt_supplies rs
            JOIN sale_r r ON rs.receipt_id = r.receipt_id
            LEFT JOIN supplies s ON rs.supply_id = s.supply_id
            UNION ALL
            SELECT ?, rs.quantity * rs.unit_price
            FROM receipt_services rs
            JOIN sale_r r ON rs.receipt_id = r.receipt_id
            UNION ALL
            SELECT ?, rp.quantity * pkg.total_price
            FROM receipt_packages rp
            JOIN sale_r r ON rp.receipt_id = r.receipt_id
            JOIN packages pkg ON rp.package_id = pkg.package_id
            UNION ALL
            SELECT ?, ro.quantity * ro.unit_price
            FROM receipt_other ro
            JOIN sale_r r ON ro.receipt_id = r.receipt_id
        ) GROUP BY category ORDER BY SUM(line_total) DESC
    """.format(where=where or "")
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    query.addBindValue(tr("Unknown Category"))
    query.addBindValue(tr("Services"))
    query.addBindValue(tr("Packages"))
    query.addBindValue(tr("Other"))
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), float(query.value(1) or 0.0)])
    return rows


def get_supply_usage_range(start="", end="", limit=8):
    """Rows of [item_name, category, quantity] of the most-used inventory in a range."""
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("r.receipt_date", start, end)
    sql = """
        SELECT s.item_name, s.category, SUM(rs.quantity) AS qty
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        JOIN supplies s ON rs.supply_id = s.supply_id
        WHERE COALESCE(r.receipt_kind, 'retail') <> 'expense'
    """
    if where:
        sql += where
    sql += " GROUP BY s.item_name, s.category ORDER BY qty DESC, s.item_name ASC LIMIT ?"
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    query.addBindValue(limit)
    rows = []
    if query.exec():
        while query.next():
            rows.append([query.value(0), query.value(1), int(query.value(2) or 0)])
    return rows


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


def get_unpaid_receipts_range(start="", end=""):
    """Unpaid/partially-paid sale receipts within a date range.

    Returns a list of [receipt_id, owner_name, receipt_date, total_price,
    amount_paid, outstanding] rows (oldest first).  Only receipts where
    total_price > amount_paid are included.
    """
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("r.receipt_date", start, end)
    sql = """
        SELECT r.receipt_id,
               COALESCE(o.first_name || ' ' || o.last_name, 'Walk-in') AS owner_name,
               r.receipt_date,
               COALESCE(r.total_price, 0) AS total_price,
               COALESCE(p.paid, 0)        AS amount_paid,
               COALESCE(r.total_price, 0) - COALESCE(p.paid, 0) AS outstanding
        FROM receipts r
        LEFT JOIN owners o ON r.owner_id = o.owner_id
        LEFT JOIN (
            SELECT receipt_id, SUM(amount) AS paid
            FROM payments GROUP BY receipt_id
        ) p ON r.receipt_id = p.receipt_id
        WHERE COALESCE(r.receipt_kind, 'retail') <> 'expense'
          AND COALESCE(r.total_price, 0) > COALESCE(p.paid, 0)
    """
    if where:
        sql += where
    sql += " ORDER BY r.receipt_date ASC, r.receipt_id ASC"
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    rows = []
    if query.exec():
        while query.next():
            rows.append([
                int(query.value(0)),
                query.value(1),
                query.value(2),
                float(query.value(3) or 0.0),
                float(query.value(4) or 0.0),
                float(query.value(5) or 0.0),
            ])
    return rows


def get_total_costs_range(start="", end=""):
    """Total expense (cost) within an explicit date range (or all time).

    Mirrors the revenue query but keeps only expense receipts, so
    ``net profit = get_total_revenue_range - get_total_costs_range``.
    """
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("receipt_date", start, end)
    sql = "SELECT SUM(total_price) FROM receipts WHERE COALESCE(receipt_kind, 'retail') = 'expense'"
    if where:
        sql += where
    query.prepare(sql)
    for bind in binds:
        query.addBindValue(bind)
    if query.exec() and query.next():
        val = query.value(0)
        try:
            return float(val) if val is not None and val != "" else 0.0
        except (ValueError, TypeError):
            return 0.0
    logger.error(f"Failed to get total costs range {start}..{end}: {query.lastError().text()}")
    return 0.0


def get_top_clients_range(start="", end="", limit=5):
    """Top owners by visits (and revenue) within an explicit date range.

    Returns rows of [owner_id, owner_name, visits, revenue]; revenue only
    counts sales receipts linked to the owner's visits. Ordered by revenue
    (then visits) descending.
    """
    db = get_connection()
    query = QSqlQuery(db)
    where, binds = _date_conditions("v.visit_date", start, end)
    sql = """
        SELECT o.owner_id,
               COALESCE(o.first_name || ' ' || o.last_name, ?) AS owner_name,
               COUNT(DISTINCT v.visit_id) AS visits,
               COALESCE(SUM(CASE WHEN COALESCE(r.receipt_kind, 'visit') <> 'expense'
                                 THEN r.total_price END), 0) AS revenue
        FROM visits v
        JOIN pets p ON v.pet_id = p.pet_id
        JOIN owners o ON p.owner_id = o.owner_id
        LEFT JOIN receipts r ON r.visit_id = v.visit_id
    """
    if where:
        sql += where.replace("AND ", "WHERE ", 1)
    sql += " GROUP BY o.owner_id, o.first_name, o.last_name ORDER BY 4 DESC, 3 DESC, 2 ASC LIMIT ?"
    query.prepare(sql)
    query.addBindValue(tr("Unknown Owner"))
    for bind in binds:
        query.addBindValue(bind)
    query.addBindValue(limit)
    rows = []
    if query.exec():
        while query.next():
            rows.append([
                int(query.value(0) or 0),
                query.value(1),
                int(query.value(2) or 0),
                float(query.value(3) or 0.0),
            ])
    return rows


# --- Notifications ---

def get_notifications(limit=20):
    """Returns a consolidated list of operational alerts.

    Sources:
      - Low-stock supplies (current_stock <= reorder_level, or zero stock)
      - Supplies expiring within 30 days
      - Sale receipts with a balance owing (unpaid or partially paid)
      - Expense receipts that are not settled in both directions: money still
        owed on a purchase, or a credit the clinic has to get back (a batch
        correction can leave a receipt overpaid)
      - Pending change requests and vaccination reminders due

    Results are sorted by importance (money owed first, then critical, then
    warning, then info) and truncated to ``limit`` — so the dashboard's
    10-row card always leads with what costs/earns the clinic money.

    Each notification is a dict:
            {
                "type": "low_stock" | "expiring" | "unpaid_receipt",
        "severity": "critical" | "warning" | "info",
        "message": str,       # user-facing message (already translatable key/string)
        "details": str        # secondary info (dates/quantities)
      }
    """
    results = []

    # --- 1. Low-stock supplies ---
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT item_name, current_stock, reorder_level, category
        FROM supplies
        WHERE current_stock = 0
           OR (reorder_level > 0 AND current_stock <= reorder_level)
        ORDER BY current_stock ASC
        LIMIT 10
    """)
    if query.exec():
        while query.next():
            item = query.value(0) or "?"
            stock = int(query.value(1) or 0)
            reorder = int(query.value(2) or 0)
            category = query.value(3) or ""
            results.append({
                "type": "low_stock",
                "severity": "critical" if stock == 0 else "warning",
                "title": "Low Stock",
                "message": f"{item}",
                "details": f"{stock} left (reorder at {reorder}) — {category}",
                "item": item,
                "info": category,
                "category": category,
                "quantity": stock,
                "reorder_level": reorder,
            })
    else:
        logger.error(f"Failed to query low-stock supplies for notifications: {query.lastError().text()}")

    # --- 2. Supplies expiring within 30 days ---
    query = QSqlQuery(db)
    query.prepare("""
        SELECT item_name, category, expiry_date
        FROM supplies
        WHERE expiry_date IS NOT NULL AND expiry_date != ''
          AND date(expiry_date) >= date('now', 'localtime')
          AND date(expiry_date) <= date('now', '+30 days', 'localtime')
        ORDER BY expiry_date ASC
        LIMIT 10
    """)
    if query.exec():
        while query.next():
            results.append({
                "type": "expiring",
                "severity": "warning",
                "title": "Expiring Soon",
                "message": f"{query.value(0)}",
                "details": f"{query.value(2)} — {query.value(1)}",
                "item": query.value(0),
                "info": query.value(1),
                "category": query.value(1),
                "expiry_date": query.value(2),
            })
    else:
        logger.error(f"Failed to query expiring supplies for notifications: {query.lastError().text()}")

    # --- 3. Sale receipts with money still owed (unpaid + partially paid) ---
    # Same definition as the Reports page's "Unpaid Receipts" table
    # (total > paid, read from the payments table) so the two screens always
    # agree; a status string on its own carries no balance information.
    # Deliberately no per-section LIMIT: the priority sort + `results[:limit]`
    # at the bottom decide what the caller keeps (the dashboard's card takes
    # the top 10, the "View all" dialog asks for 100).
    from src.utils.formatters import format_currency

    for (receipt_id, owner_name, receipt_date, _total, _paid,
         outstanding) in get_unpaid_receipts_range():
        owner_name = owner_name or "Walk-in"
        label = tr("Receipt #{id}").format(id=receipt_id)
        results.append({
            "type": "unpaid_receipt",
            "severity": "warning",
            "title": "Unpaid Receipt",
            "message": label,
            "details": "{date} — {owner} — {amount}".format(
                date=str(receipt_date or "")[:10],
                owner=owner_name,
                amount=format_currency(outstanding)),
            "item": label,
            "info": owner_name,
            "client": owner_name,
            "amount": outstanding,
        })

    # --- 4. Expense receipts that are not settled (both directions) ---
    # The stay on the dashboard until they are paid off: a positive balance is
    # money the clinic still owes on a purchase, a negative one is a credit
    # (an overpayment or a batch correction that shrank the bill) that has to
    # be refunded back.
    from src.utils.formatters import format_currency
    query = QSqlQuery(db)
    query.prepare("""
        SELECT r.receipt_id, r.receipt_date, r.total_price,
               COALESCE((SELECT SUM(p.amount) FROM payments p
                         WHERE p.receipt_id = r.receipt_id), 0) AS paid
        FROM receipts r
        WHERE COALESCE(r.receipt_kind, 'retail') = 'expense'
          AND ABS(COALESCE(r.total_price, 0) -
                  COALESCE((SELECT SUM(p.amount) FROM payments p
                            WHERE p.receipt_id = r.receipt_id), 0)) > 0.004
        ORDER BY date(r.receipt_date) ASC, r.receipt_id ASC
        LIMIT 10
    """)
    if query.exec():
        while query.next():
            receipt_id = int(query.value(0))
            receipt_date = str(query.value(1) or "")[:10]
            total = float(query.value(2) or 0.0)
            paid = float(query.value(3) or 0.0)
            balance = paid - total  # > 0 : credit to refund, < 0 : still owed
            if balance < 0:
                results.append({
                    "type": "expense_balance",
                    "severity": "warning",
                    "title": "Expense Unpaid",
                    "message": tr("Receipt #{id}").format(id=receipt_id),
                    "info": format_currency(-balance),
                    "details": "{date} — {note}".format(
                        date=receipt_date,
                        note=tr("paid {paid} of {total}").format(
                            paid=format_currency(paid),
                            total=format_currency(total))),
                    "receipt_id": receipt_id,
                    "balance": balance,
                })
            else:
                results.append({
                    "type": "expense_balance",
                    "severity": "info",
                    "title": "Refund Due",
                    "message": tr("Receipt #{id}").format(id=receipt_id),
                    "info": format_currency(balance),
                    "details": "{date} — {note}".format(
                        date=receipt_date,
                        note=tr("overpaid by {amount}").format(
                            amount=format_currency(balance))),
                    "receipt_id": receipt_id,
                    "balance": balance,
                })
    else:
        logger.error(f"Failed to query expense balances for notifications: {query.lastError().text()}")

    # --- 5. Pending change requests (admin reminders) ---
    # Import here to avoid a circular import at module level.
    try:
        from src.core.repositories.pending_changes_repo import get_pending_count
        pending = get_pending_count()
        if pending > 0:
            results.insert(0, {
                "type":     "pending_changes",
                "severity": "warning",
                "title":    "Pending Approvals",
                "message":  tr("Edits awaiting approval") if pending > 1 else tr("Edit awaiting approval"),
                "details":  str(pending),
                "item":     str(pending),
                "info":     str(pending),
            })
    except Exception:
        pass  # Table may not exist on very old DBs; fail silently

    # --- 6. Vaccination reminders due ---
    try:
        vr_q = QSqlQuery(db)
        vr_q.prepare("""
            SELECT vr.reminder_id, p.pet_name, vl.vaccine_name, vr.due_date
            FROM vaccination_reminders vr
            JOIN pets p ON vr.pet_id = p.pet_id
            LEFT JOIN vaccines_lookup vl ON vr.vaccine_id = vl.vaccine_id
            WHERE vr.status = 'pending'
              AND date(vr.due_date) <= date('now', '+14 days', 'localtime')
            ORDER BY vr.due_date ASC
            LIMIT 5
        """)
        if vr_q.exec():
            while vr_q.next():
                due = vr_q.value(3) or ""
                pet = vr_q.value(1) or "?"
                vaccine = vr_q.value(2) or "?"
                results.append({
                    "type": "vaccination_due",
                    "severity": "warning",
                    "title": "Vaccination Due",
                    "message": f"{pet} — {vaccine}",
                    "details": due,
                    "item": f"{pet}",
                    "info": vaccine,
                    "expiry_date": due,
                })
    except Exception:
        pass  # Table may not exist on very old DBs; fail silently

    # Sort LAST, now that every section has contributed: what the clinic is
    # owed (or owes) first, then by severity, then by detail string. Unpaid
    # details lead with the receipt date, so the oldest arrears stay on top
    # of the dashboard's 10-row card; `pending_changes` keeps its historic
    # first slot.
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    priority_order = {"pending_changes": 0, "unpaid_receipt": 1,
                      "expense_balance": 2}
    results.sort(key=lambda n: (
        priority_order.get(n["type"], 3),
        severity_order.get(n["severity"], 3),
        n["details"] or "",
    ))

    return results[:limit]

