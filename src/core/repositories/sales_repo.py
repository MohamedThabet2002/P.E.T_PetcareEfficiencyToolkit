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
import src.core.repositories.stock_repo as stock_repo
from src.config.constants import SUPPLY_CATEGORIES
from src.utils.i18n import tr

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
               quantity, unit_price, line_total, total_price, receipt_code, notes,
               receipt_kind
        FROM v_receipt_summary
    """
    conditions, bind_values = [], []

    if text:
        search_text = f"%{text}%"
        fields = ["receipt_date", "item_name", "item_type", "receipt_code", "owner_name",
                  "notes", "receipt_kind"]
        if filter_field == "All":
            conditions.append(f"({' OR '.join([f'CAST({f} AS TEXT) LIKE ?' for f in fields])})")
            bind_values.extend([search_text] * len(fields))
        else:
            clean_field = filter_field.lower().replace(' ', '_')
            mapping = {
                "id": "receipt_id",
                "receipt_id": "receipt_id",
                "date": "receipt_date",
                "receipt_date": "receipt_date",
                "item_name": "item_name",
                "category": "item_type",
                "item_type": "item_type",
                "type": "receipt_kind",
                "receipt_kind": "receipt_kind",
                "notes": "notes",
                "total_price": "total_price",
                "line_total": "line_total",
                "owner_name": "owner_name",
                "unit_price": "unit_price",
                "quantity": "quantity",
                "receipt_code": "receipt_code",
            }
            field = mapping.get(clean_field, "item_name")
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
                # view order: ... unit_price, line_total, total_price ...
                "line_total": query.value(7),
                "total_price": query.value(8),
                "total_amount": query.value(8),
                "receipt_id": query.value(0),
                "receipt_code": query.value(9),
                "receipt_kind": query.value(11) or "",
                "notes": query.value(10) or "",
            })
    query.finish()
    return results


def _next_unique_code(db, prefix, width=4):
    """Returns a unique ``<PREFIX>-<YYYYMM>-####`` receipt code.

    ``receipts.receipt_code`` is UNIQUE, so a hardcoded code only ever inserts
    one row; every later insert fails the constraint. The month is part of the
    code so the numbers stay short and human-scannable while remaining unique
    against seeded/legacy/pre-month rows. Existing codes are upper-cased before
    comparison because SQLite ``LIKE`` is case-insensitive, which keeps a legacy
    bare-code row from colliding with a generated one.

    The scan is deliberately self-healing (it derives the next number from the
    rows actually present) rather than a counter table, so it can never drift.
    """
    month = datetime.date.today().strftime("%Y%m")
    stem = f"{prefix}-{month}-"
    query = QSqlQuery(db)
    query.prepare("SELECT receipt_code FROM receipts WHERE receipt_code LIKE ?")
    query.addBindValue(f"{stem}%")
    used = set()
    if query.exec():
        while query.next():
            used.add((query.value(0) or "").upper())
    query.finish()

    for num in range(1, 1000000):
        code = f"{stem}{num:0{width}d}"
        if code not in used:
            return code
    return None


def next_expense_code(db):
    """Returns a unique ``EXPENSE-<YYYYMM>-####`` receipt code."""
    return _next_unique_code(db, "EXPENSE")


def next_retail_code(db):
    """Returns a unique ``RETAIL-<YYYYMM>-####`` code for walk-in retail sales."""
    return _next_unique_code(db, "RETAIL")


def next_visit_code(db):
    """Returns a unique ``VISIT-<YYYYMM>-####`` code for a visit's receipt."""
    return _next_unique_code(db, "VISIT")


def add_general_expense(date, category, item_name, amount, notes="", audit_user_id=None,
                        receipt_code=None):
    """Adds a general business expense to the ledger (receipt + line atomically)."""
    db = get_connection()
    code = receipt_code or next_expense_code(db)
    if not code:
        logger.error("Could not allocate a unique receipt code for a general expense")
        return False

    db.transaction()
    active = []
    try:
        query = QSqlQuery(db)
        active.append(query)
        query.prepare("""
            INSERT INTO receipts (receipt_date, total_price, receipt_code, receipt_kind, notes)
            VALUES (?, ?, ?, 'expense', ?)
        """)
        query.addBindValue(date)
        query.addBindValue(amount)
        query.addBindValue(code)
        query.addBindValue(notes or None)
        if not query.exec():
            raise RuntimeError(f"receipt insert: {query.lastError().text()}")
        rid = query.lastInsertId()
        query.finish()

        item_query = QSqlQuery(db)
        active.append(item_query)
        item_query.prepare("""
            INSERT INTO receipt_other (receipt_id, description, amount, quantity, unit_price, category)
            VALUES (?, ?, ?, 1, ?, ?)
        """)
        item_query.addBindValue(rid)
        item_query.addBindValue(item_name)
        item_query.addBindValue(amount)
        item_query.addBindValue(amount)
        item_query.addBindValue(category or None)
        if not item_query.exec():
            raise RuntimeError(f"expense line insert: {item_query.lastError().text()}")
        item_query.finish()

        for qq in active:
            qq.finish()
        if not db.commit():
            db.rollback()
            return False
    except Exception as e:
        logger.error(f"Failed to add general expense '{item_name}': {e}")
        for qq in active:
            qq.finish()
        db.rollback()
        return False

    if audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("ADD", "receipts", rid,
                      changes=[
                          {"field_name": "description", "old_value": "", "new_value": item_name or ""},
                          {"field_name": "amount", "old_value": "", "new_value": amount},
                          {"field_name": "category", "old_value": "", "new_value": category or ""},
                      ],
                      user_id=audit_user_id)
    return True


def delete_receipt(receipt_id, audit_user_id=None):
    """Deletes a receipt (cascade handles items) and hands sold stock back.

    Supply lines on the receipt are re-added to ``current_stock`` and to their
    batches (newest first), and a compensating ``sale_return`` movement is
    logged - otherwise every deleted sale permanently understated stock.
    ``undo_repo.restore_deleted_record`` performs the mirror image when the
    delete is restored.
    """
    from src.core.repositories import undo_repo
    db = get_connection()
    # Capture snapshot before delete so line items, payments, adjustments are preserved.
    snapshot = undo_repo.capture_snapshot("receipts", receipt_id)

    # Read the supply lines BEFORE the cascade removes them.
    sold = []
    sq = QSqlQuery(db)
    sq.prepare("SELECT supply_id, quantity FROM receipt_supplies WHERE receipt_id = ?")
    sq.addBindValue(receipt_id)
    if sq.exec():
        while sq.next():
            if sq.value(0) is not None:
                sold.append((sq.value(0), int(sq.value(1) or 0)))
    sq.finish()

    db.transaction()
    active = []
    try:
        query = QSqlQuery(db)
        active.append(query)
        query.prepare("DELETE FROM receipts WHERE receipt_id = ?")
        query.addBindValue(receipt_id)
        if not query.exec():
            raise RuntimeError(query.lastError().text())
        query.finish()

        for supply_id, qty in sold:
            if qty <= 0:
                continue
            uq = QSqlQuery(db)
            active.append(uq)
            uq.prepare("UPDATE supplies SET current_stock = current_stock + ? "
                       "WHERE supply_id = ?")
            uq.addBindValue(qty)
            uq.addBindValue(supply_id)
            if not uq.exec():
                raise RuntimeError(uq.lastError().text())
            uq.finish()
            stock_repo.return_to_batch(db, supply_id, qty)
            stock_repo.record_movement(
                db, supply_id, "sale_return", qty,
                notes=f"Receipt #{receipt_id} deleted",
                user_id=audit_user_id, receipt_id=None)

        for qq in active:
            qq.finish()
        if not db.commit():
            db.rollback()
            return False
    except Exception as e:
        logger.error(f"Failed to delete receipt {receipt_id}: {e}")
        for qq in active:
            qq.finish()
        db.rollback()
        return False

    if snapshot is not None:
        undo_repo.record_deletion("receipts", receipt_id, snapshot, user_id=audit_user_id)
    if audit_user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "receipts", receipt_id, user_id=audit_user_id)
    return True


def create_sale_receipt_for_quick_purchase(owner_id, receipt_date_sql, items, user_id=None,
                                            receipt_code=None, paid=True,
                                            payment_method="Cash", payment_notes="",
                                            packages=None, discount=0.0, paid_amount=None):
    """Creates a walk-in retail sale receipt for the Quick Purchase flow.

    ``packages`` is an optional list of service packages (same shape as the add
    visit flow: ``package_id`` / ``package_name`` / ``total_price`` /
    ``quantity``). Package lines are billed at the package price and land in
    ``receipt_packages`` - exactly like ``visit_repo.add_visit`` does - so a
    package-only basket is valid on its own.

    ``receipt_code`` defaults to a freshly allocated unique
    ``RETAIL-<YYYYMM>-####`` code: ``receipts.receipt_code`` is UNIQUE, so a
    hardcoded code only ever inserted the first purchase made in the whole
    database.

    ``paid`` defaults to True because a quick purchase is settled at the
    counter: a full payment is recorded inside the same transaction, which
    flips ``payment_status`` to ``Paid`` and leaves a zero balance (owner
    outstanding totals and the ledger both read the ``payments`` table).
    Pass ``paid=False`` to leave the receipt ``Unpaid``.

    ``discount`` is a cash amount taken off the basket subtotal: the stored
    ``receipts.discount`` keeps it separate from the line items while
    ``total_price`` (and the payment recorded for ``paid=True``) reflects the
    discounted figure.

    ``paid_amount`` lets the caller record what was actually handed over on the
    spot instead of a blanket full payment: more than zero but less than the
    total leaves the receipt ``Partial``, zero records nothing (``Unpaid``),
    and the full total (or more) settles it as ``Paid``. When it is ``None``
    (backward compatible) the ``paid`` flag decides - ``True`` pays the whole
    discounted total, ``False`` records nothing.

    Returns the new receipt_id, a ``STOCK_ERROR|name|stock`` string when
    there is not enough stock, or None on failure.
    """
    if not items and not packages:
        return None

    items = items or []
    packages = packages or []
    packages_total = sum(
        float(pkg.get("total_price") or 0.0) * int(pkg.get("quantity") or 1)
        for pkg in packages
    )

    db = get_connection()
    code = receipt_code or next_retail_code(db)
    if not code:
        logger.error("Could not allocate a unique receipt code for a quick purchase")
        return None

    db.transaction()
    active = []  # queries kept open in this transaction, finished pre-commit

    try:
        # Stock is keyed on (item_name, category): names are unique per category
        # (see supply_repo.add_supply), so two items may share a name across
        # categories. Summing by name alone could advertise more stock than the
        # single row the sale later draws from.
        requested = {}
        for item in items:
            name = item.get("item_name")
            quantity = item.get("quantity", 1)
            if name and quantity > 0:
                key = (name, item.get("category") or None)
                requested[key] = requested.get(key, 0) + quantity

        for (name, category), quantity in requested.items():
            stock_query = QSqlQuery(db)
            active.append(stock_query)
            stock_query.prepare(
                "SELECT COUNT(*), COALESCE(SUM(current_stock), 0) "
                "FROM supplies WHERE item_name = ? AND (? IS NULL OR category = ?)"
            )
            stock_query.addBindValue(name)
            stock_query.addBindValue(category)
            stock_query.addBindValue(category)
            if stock_query.exec() and stock_query.next():
                current_stock = stock_query.value(1) or 0
                if stock_query.value(0) > 0 and quantity > current_stock:
                    logger.warning(
                        f"Stock check failed for '{name}': needs {quantity}, has {current_stock}"
                    )
                    stock_query.finish()
                    db.rollback()
                    return f"STOCK_ERROR|{name}|{current_stock}"
            else:
                logger.error(f"Stock query failed for '{name}': {stock_query.lastError().text()}")
                stock_query.finish()
                db.rollback()
                return f"STOCK_ERROR|{name}|0"
            stock_query.finish()

        subtotal = sum([it["quantity"] * it["price"] for it in items]) + packages_total
        discount = round(min(max(float(discount or 0.0), 0.0), subtotal), 2)
        total_amount = round(subtotal - discount, 2)

        if paid_amount is None:
            # Backward-compatible default: the paid flag covers the whole bill.
            effective_paid = round(total_amount, 2) if paid else 0.0
        else:
            effective_paid = round(min(max(float(paid_amount or 0.0), 0.0), total_amount), 2)
        if total_amount - effective_paid <= 1e-9:
            initial_status = "Paid"
        elif effective_paid > 0:
            initial_status = "Partial"
        else:
            initial_status = "Unpaid"

        rq = QSqlQuery(db)
        active.append(rq)
        rq.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, discount, receipt_code,
                                  receipt_kind, payment_status)
            VALUES (?, ?, ?, ?, ?, 'retail', ?)
        """)
        rq.addBindValue(owner_id)
        rq.addBindValue(receipt_date_sql)
        rq.addBindValue(total_amount)
        rq.addBindValue(discount)
        rq.addBindValue(code)
        rq.addBindValue(initial_status)

        if not rq.exec():
            logger.error(
                f"Failed to insert quick purchase receipt '{code}': {rq.lastError().text()}"
            )
            rq.finish()
            db.rollback()
            return None
        # Capture before finish(): Qt clears lastInsertId once the query is done.
        receipt_id = int(rq.lastInsertId())
        rq.finish()

        for it in items:
            # Check if item is a supply
            sq = QSqlQuery(db)
            active.append(sq)
            category = it.get("category") or None
            sq.prepare("SELECT supply_id, sell_price FROM supplies "
                       "WHERE item_name = ? AND (? IS NULL OR category = ?) "
                       "ORDER BY supply_id LIMIT 1")
            sq.addBindValue(it["item_name"])
            sq.addBindValue(category)
            sq.addBindValue(category)
            found = sq.exec() and sq.next()
            supply_id = sq.value(0) if found else None
            sq.finish()
            if found:
                iq = QSqlQuery(db)
                active.append(iq)
                iq.prepare("""
                    INSERT INTO receipt_supplies (receipt_id, supply_id, quantity, unit_price)
                    VALUES (?, ?, ?, ?)
                """)
                iq.addBindValue(receipt_id)
                iq.addBindValue(supply_id)
                iq.addBindValue(it["quantity"])
                iq.addBindValue(it["price"])
                if not iq.exec():
                    iq.finish()
                    db.rollback()
                    return None
                iq.finish()
                # Deduct stock
                uq = QSqlQuery(db)
                active.append(uq)
                uq.prepare("UPDATE supplies SET current_stock = current_stock - ? WHERE supply_id = ?")
                uq.addBindValue(it["quantity"])
                uq.addBindValue(supply_id)
                if not uq.exec():
                    uq.finish()
                    db.rollback()
                    return None
                uq.finish()
                # The same units leave the stock batches (oldest first).
                stock_repo.consume_batches(db, supply_id, it["quantity"])
                # Log the trail: without this the ledger only ever knew about
                # purchases, so a retail sale left no trace in stock movements.
                stock_repo.record_movement(
                    db, supply_id, "sale", -int(it["quantity"]),
                    notes=f"Receipt #{receipt_id}", user_id=user_id,
                    receipt_id=receipt_id)
            else:
                # Non-supply item - add to receipt_other (quantity/unit_price
                # are stored too: an edit reads them back, and a NULL unit_price
                # would rewrite the line as 0).
                oq = QSqlQuery(db)
                active.append(oq)
                oq.prepare("""
                    INSERT INTO receipt_other (receipt_id, description, amount,
                                               quantity, unit_price)
                    VALUES (?, ?, ?, ?, ?)
                """)
                oq.addBindValue(receipt_id)
                oq.addBindValue(it["item_name"])
                oq.addBindValue(it["quantity"] * it["price"])
                oq.addBindValue(it["quantity"])
                oq.addBindValue(it["price"])
                if not oq.exec():
                    oq.finish()
                    db.rollback()
                    return None
                oq.finish()

        # Add Packages (read-only lines, priced from the package itself)
        for pkg in packages:
            pq = QSqlQuery(db)
            active.append(pq)
            pq.prepare("""
                INSERT INTO receipt_packages (receipt_id, package_id, quantity)
                VALUES (?, ?, ?)
            """)
            pq.addBindValue(receipt_id)
            pq.addBindValue(pkg["package_id"])
            pq.addBindValue(int(pkg.get("quantity") or 1))
            if not pq.exec():
                pq.finish()
                db.rollback()
                return None
            pq.finish()

        if effective_paid > 0 and total_amount > 0:
            # Walk-in retail is settled at the counter, so record the payment in
            # the same transaction instead of leaving the receipt Unpaid. A
            # failure MUST abort: committing 'Paid' with no payment row would
            # report the full amount as outstanding everywhere.
            from src.core.repositories.payment_repo import add_payment
            if add_payment(receipt_id, effective_paid,
                           payment_method or "Cash", payment_notes,
                           audit_user_id=user_id) is None:
                logger.error(f"Failed to record payment for quick purchase receipt {receipt_id}")
                for qq in active:
                    qq.finish()
                db.rollback()
                return None

        # QtSql refuses to commit while a statement is still active.
        for qq in active:
            qq.finish()

        if not db.commit():
            db.rollback()
            return None

        if user_id is not None:
            from src.core.repositories.audit_repo import record_action
            names = [str(it.get("item_name", "")) for it in items if it.get("item_name")]
            names += [
                f"{pkg.get('package_name', '')} x{pkg.get('quantity', 1)}"
                for pkg in packages if pkg.get("package_name")
            ]
            summary = "; ".join(names)
            record_action(
                "ADD", "receipts", receipt_id,
                changes=[{"field_name": "items", "old_value": "", "new_value": summary}],
                user_id=user_id,
            )

        return receipt_id
    except Exception as e:
        logger.error(f"Failed to create sale receipt: {e}")
        for qq in active:
            qq.finish()
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
                   SUM(CASE WHEN COALESCE(receipt_kind, 'retail') <> 'expense' THEN total_price ELSE 0 END) as revenue,
                   SUM(CASE WHEN COALESCE(receipt_kind, 'retail') = 'expense' THEN total_price ELSE 0 END) as cost
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


def _trend_bucket(start, end):
    """Chooses the SQL/date bucketing for a [start, end] report range.

    ``hourly`` when the range is a single day, ``monthly`` for ranges longer
    than ~5 weeks, otherwise ``daily``.
    """
    if start and end and start == end:
        return "hourly"
    if start and end:
        try:
            delta = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
        except ValueError:
            return "daily"
        return "monthly" if delta > 35 else "daily"
    return "daily"


def _trend_date_series(start, end):
    """(key, label) pairs covering [start, end] for the chosen bucket.

    Keys match the SQL GROUP BY label for the corresponding bucket so chart
    series can be zero-filled across the whole range.
    """
    bucket = _trend_bucket(start, end)
    if bucket == "hourly":
        return [(f"{h:02d}:00", f"{h:02d}:00") for h in range(24)]
    try:
        s = datetime.date.fromisoformat(start) if start else datetime.date.today()
        e = datetime.date.fromisoformat(end) if end else s
    except ValueError:
        s = e = datetime.date.today()
    if bucket == "monthly":
        pairs, cur = [], s.replace(day=1)
        while cur <= e:
            pairs.append((cur.strftime("%Y-%m"), cur.strftime("%b %y")))
            nxt_month = cur.month % 12 + 1
            nxt_year = cur.year + (1 if cur.month == 12 else 0)
            cur = cur.replace(year=nxt_year, month=nxt_month, day=1)
        return pairs
    pairs, cur = [], s
    while cur <= e:
        pairs.append((cur.isoformat(), cur.strftime("%d/%m")))
        cur += datetime.timedelta(days=1)
    return pairs


def get_revenue_trend_range(start="", end=""):
    """Revenue/cost/net time-series within an explicit date range."""
    db = get_connection()
    query = QSqlQuery(db)
    conds, binds = [], []
    if start:
        conds.append("date(receipt_date) >= date(?)")
        binds.append(start)
    if end:
        conds.append("date(receipt_date) <= date(?)")
        binds.append(end)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    bucket = _trend_bucket(start, end)
    if bucket == "hourly":
        select = "strftime('%H:00', receipt_date)"
    elif bucket == "monthly":
        select = "strftime('%Y-%m', receipt_date)"
    else:
        select = "date(receipt_date)"

    sql = f"""
        SELECT {select} as d,
               SUM(CASE WHEN COALESCE(receipt_kind, 'retail') <> 'expense' THEN total_price ELSE 0 END) as revenue,
               SUM(CASE WHEN COALESCE(receipt_kind, 'retail') = 'expense' THEN total_price ELSE 0 END) as cost
        FROM receipts {where}
        GROUP BY d
    """
    query.prepare(sql)
    for b in binds:
        query.addBindValue(b)

    data_map = {}
    if query.exec():
        while query.next():
            data_map[query.value(0)] = (query.value(1) or 0, query.value(2) or 0)

    labels, s1, s2, s3 = [], [], [], []
    for key, label in _trend_date_series(start, end):
        rev, cost = data_map.get(key, (0, 0))
        labels.append(label)
        s1.append(rev)
        s2.append(cost)
        s3.append(rev - cost)
    return labels, s1, s2, s3


def get_supplies_category_trend_range(start="", end=""):
    """Supplies sold time-series broken down by category, within [start, end]."""
    db = get_connection()
    query = QSqlQuery(db)
    conds, binds = [], []
    if start:
        conds.append("date(r.receipt_date) >= date(?)")
        binds.append(start)
    if end:
        conds.append("date(r.receipt_date) <= date(?)")
        binds.append(end)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    bucket = _trend_bucket(start, end)
    if bucket == "hourly":
        select = "strftime('%H:00', r.receipt_date)"
    elif bucket == "monthly":
        select = "strftime('%Y-%m', r.receipt_date)"
    else:
        select = "date(r.receipt_date)"

    sql = f"""
        SELECT {select} as d, s.category, SUM(rs.quantity)
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        JOIN supplies s ON rs.supply_id = s.supply_id
        {where}
        GROUP BY d, s.category
    """
    query.prepare(sql)
    for b in binds:
        query.addBindValue(b)

    data_map = {}
    if query.exec():
        while query.next():
            data_map.setdefault(query.value(0), {})[query.value(1)] = query.value(2) or 0

    categories = supply_repo.get_all_categories() or SUPPLY_CATEGORIES
    series_dict = {cat: [] for cat in categories}
    labels = []
    for key, label in _trend_date_series(start, end):
        labels.append(label)
        day_data = data_map.get(key, {})
        for cat in categories:
            series_dict[cat].append(day_data.get(cat, 0))
    return labels, series_dict


def get_subcategory_sales_trend_range(category, start="", end=""):
    """Subcategory sales trend for one category within [start, end]."""
    db = get_connection()
    query = QSqlQuery(db)
    conds, binds = ["s.category = ?"], [category]
    if start:
        conds.append("date(r.receipt_date) >= date(?)")
        binds.append(start)
    if end:
        conds.append("date(r.receipt_date) <= date(?)")
        binds.append(end)
    where = "WHERE " + " AND ".join(conds)
    bucket = _trend_bucket(start, end)
    if bucket == "hourly":
        select = "strftime('%H:00', r.receipt_date)"
    elif bucket == "monthly":
        select = "strftime('%Y-%m', r.receipt_date)"
    else:
        select = "date(r.receipt_date)"

    sql = f"""
        SELECT {select} as d, s.sub_category, SUM(rs.quantity)
        FROM receipt_supplies rs
        JOIN receipts r ON rs.receipt_id = r.receipt_id
        JOIN supplies s ON rs.supply_id = s.supply_id
        {where}
        GROUP BY d, s.sub_category
    """
    query.prepare(sql)
    for b in binds:
        query.addBindValue(b)

    data_map, subcategories = {}, set()
    if query.exec():
        while query.next():
            subcat = query.value(1) or "Other"
            subcategories.add(subcat)
            data_map.setdefault(query.value(0), {})[subcat] = query.value(2) or 0

    series_dict = {sc: [] for sc in subcategories}
    labels = []
    for key, label in _trend_date_series(start, end):
        labels.append(label)
        day_data = data_map.get(key, {})
        for sc in subcategories:
            series_dict[sc].append(day_data.get(sc, 0))
    return labels, series_dict


def log_supply_purchase_expense(supply_id, item_name, category, quantity, unit_price,
                                purchase_date, supplier, receipt_id=None, batch_id=None):
    """Creates or updates an expense receipt when supplies are bought or restocked.

    ``batch_id`` names the stock batch this purchase created, so the receipt is
    stored on the batch: a later quantity correction then folds into this same
    receipt instead of adding a second expense row for one purchase.
    """
    db = get_connection()
    total = quantity * unit_price
    active = []

    def _exec(q, what):
        if not q.exec():
            raise RuntimeError(f"{what}: {q.lastError().text()}")

    db.transaction()
    try:
        if receipt_id is None:
            notes = f"Restock from {supplier}" if supplier else "Restock"
            code = next_expense_code(db)
            if code is None:
                db.rollback()
                return None
            rq = QSqlQuery(db)
            active.append(rq)
            rq.prepare("""
                INSERT INTO receipts (receipt_date, total_price, receipt_code, receipt_kind, notes)
                VALUES (?, ?, ?, 'expense', ?)
            """)
            rq.addBindValue(purchase_date)
            rq.addBindValue(total)
            rq.addBindValue(code)
            rq.addBindValue(notes)
            _exec(rq, "restock receipt insert")
            receipt_id = int(rq.lastInsertId())
            rq.finish()
        else:
            uq = QSqlQuery(db)
            active.append(uq)
            uq.prepare("UPDATE receipts SET total_price = total_price + ? WHERE receipt_id = ?")
            uq.addBindValue(total)
            uq.addBindValue(receipt_id)
            _exec(uq, "restock receipt total update")
            uq.finish()

        riq = QSqlQuery(db)
        active.append(riq)
        riq.prepare("""
            INSERT INTO receipt_other (receipt_id, description, amount, quantity,
                                       unit_price, category)
            VALUES (?, ?, ?, ?, ?, ?)
        """)
        riq.addBindValue(receipt_id)
        riq.addBindValue(f"{item_name} (Bought)")
        riq.addBindValue(total)
        riq.addBindValue(int(quantity or 0))
        riq.addBindValue(float(unit_price or 0.0))
        riq.addBindValue(category or None)
        _exec(riq, "restock line insert")
        riq.finish()

        for qq in active:
            qq.finish()
        if not db.commit():
            db.rollback()
            return None
    except Exception as e:
        logger.error(f"Failed to log supply purchase expense: {e}")
        for qq in active:
            qq.finish()
        db.rollback()
        return None

    stock_repo.stamp_batch_receipt(batch_id, receipt_id)
    return receipt_id


def apply_receipt_discount(receipt_id, discount):
    """Stores a cash discount on an existing receipt and lowers its total.

    Used by the bulk purchase flow after the shared expense receipt is
    written: the stock lines keep their full cost on the ledger while the
    ``discount`` header reduces what the clinic actually paid (expense cost
    comes from ``total_price``, so the discount shows up as savings).
    """
    db = get_connection()
    discount = round(max(float(discount or 0.0), 0.0), 2)
    if discount <= 0.0:
        return True
    q = QSqlQuery(db)
    q.prepare("""
        UPDATE receipts
        SET discount = ?,
            total_price = MAX(0.0, total_price - ?)
        WHERE receipt_id = ?
    """)
    q.addBindValue(discount)
    q.addBindValue(discount)
    q.addBindValue(receipt_id)
    if not q.exec():
        logger.error(f"apply_receipt_discount: {q.lastError().text()}")
        q.finish()
        return False
    q.finish()
    return True


def log_stock_adjustment(supply_id, item_name, category, quantity, unit_price,
                         adjustment_date, notes="", receipt_id=None,
                         user_id=None, adjustment=None):
    """Records a stock quantity correction as an expense.

    ``quantity`` is **signed**: an upward correction (stock that was never
    counted) adds cost, a downward correction reverses it. The entry is
    ``receipt_kind = 'expense'``, so it lands in the same cost bucket as a
    restock and profit reports reconcile - a batch logged as 100 and corrected
    to 10 nets out to the real 10.

    When ``receipt_id`` points at the receipt the batch was **bought on**, the
    correction is folded into that receipt (its total moves and a "(Adjusted)"
    line is appended) rather than minting a new ``EXPENSE-###`` row for every
    edit. If that receipt has since been deleted, or no link exists yet, the
    correction is posted on its own.

    Because an existing receipt really changed, two extra things happen:
    a revision row is written to ``receipt_adjustments`` (+ an ``ADJUST``
    audit) so the Receipt Details dialog lists it exactly like a hand edit,
    and the receipt's payment status is re-derived - a purchase that is no
    longer fully paid must stop claiming to be Paid.

    ``adjustment`` is ``{"description": str, "details": [ ... ]}`` describing
    the batch change for that revision row (None when the caller has nothing
    to add).

    Returns the receipt_id, or None on failure.
    """
    db = get_connection()
    total = float(quantity or 0) * float(unit_price or 0.0)
    active = []
    # Total of an *existing* receipt this call amends; None for a receipt
    # created here (a brand-new entry is not an edit of anything).
    old_total = None

    def _exec(q, what):
        if not q.exec():
            raise RuntimeError(f"{what}: {q.lastError().text()}")

    db.transaction()
    try:
        if receipt_id is not None:
            tq = QSqlQuery(db)
            active.append(tq)
            tq.prepare("SELECT total_price FROM receipts WHERE receipt_id = ?")
            tq.addBindValue(receipt_id)
            if tq.exec() and tq.next():
                old_total = float(tq.value(0) or 0.0)
            tq.finish()

            uq = QSqlQuery(db)
            active.append(uq)
            # MAX(0, ...): repeated negative corrections must never drive an
            # expense receipt below zero.
            uq.prepare("UPDATE receipts SET total_price = MAX(0, total_price + ?) "
                       "WHERE receipt_id = ?")
            uq.addBindValue(total)
            uq.addBindValue(receipt_id)
            _exec(uq, "adjustment receipt total update")
            if uq.numRowsAffected() == 0:
                # The purchase receipt no longer exists: fall back to a new one.
                receipt_id = None
                old_total = None
            uq.finish()

        if receipt_id is None:
            code = next_expense_code(db)
            if code is None:
                logger.error("Could not allocate a receipt code for a stock adjustment")
                db.rollback()
                return None
            rq = QSqlQuery(db)
            active.append(rq)
            rq.prepare("""
                INSERT INTO receipts (receipt_date, total_price, receipt_code, receipt_kind, notes)
                VALUES (?, ?, ?, 'expense', ?)
            """)
            rq.addBindValue(adjustment_date)
            rq.addBindValue(total)
            rq.addBindValue(code)
            rq.addBindValue(notes or None)
            _exec(rq, "adjustment receipt insert")
            receipt_id = int(rq.lastInsertId())
            rq.finish()

        riq = QSqlQuery(db)
        active.append(riq)
        # quantity/unit_price mirror the correction itself: an edit later reads
        # them back, and amount is the signed total (quantity * unit_price).
        qty = int(quantity or 0)
        riq.prepare("""
            INSERT INTO receipt_other (receipt_id, description, amount, quantity,
                                       unit_price, category)
            VALUES (?, ?, ?, ?, ?, ?)
        """)
        riq.addBindValue(receipt_id)
        riq.addBindValue(f"{item_name} (Adjusted)")
        riq.addBindValue(total)
        riq.addBindValue(qty)
        riq.addBindValue(float(unit_price or 0.0))
        riq.addBindValue(category or None)
        _exec(riq, "adjustment line insert")
        riq.finish()

        for qq in active:
            qq.finish()
        if not db.commit():
            db.rollback()
            return None
    except Exception as e:
        logger.error("Failed to log stock adjustment: %s", e)
        for qq in active:
            qq.finish()
        db.rollback()
        return None

    if receipt_id is None:
        return None

    if old_total is not None:
        _record_stock_adjustment_trail(
            db, receipt_id, old_total, user_id=user_id, adjustment=adjustment)

    # The total moved, so the Paid / Partial / Unpaid label may be stale now.
    try:
        from src.core.repositories.payment_repo import update_receipt_payment_status
        update_receipt_payment_status(receipt_id)
    except Exception as e:
        logger.error("Could not refresh payment status for receipt %s: %s",
                     receipt_id, e)
    return receipt_id


def _record_stock_adjustment_trail(db, receipt_id, old_total, user_id=None,
                                   adjustment=None):
    """Writes the revision row + ADJUST audit for a batch correction.

    Called only when an *existing* receipt was amended, so the Receipt Details
    dialog shows a stock correction in its Adjustments list exactly like a
    hand edit. Failures are logged, never allowed to undo the ledger entry.
    """
    try:
        new_q = QSqlQuery(db)
        new_q.prepare("SELECT total_price, visit_id FROM receipts "
                      "WHERE receipt_id = ?")
        new_q.addBindValue(receipt_id)
        new_total = old_total
        visit_id = None
        if new_q.exec() and new_q.next():
            new_total = float(new_q.value(0) or 0.0)
            visit_id = new_q.value(1)
        new_q.finish()

        if abs(new_total - old_total) <= 0.004:
            return  # nothing actually moved (e.g. floored at zero)

        from src.utils.formatters import format_currency
        from src.core.repositories.receipt_adjustment_repo import add_adjustment
        from src.core.repositories.audit_repo import record_action

        changes = [{
            "field_name": "total_price",
            "old_value": format_currency(old_total),
            "new_value": format_currency(new_total),
        }]
        description = (adjustment or {}).get("description")
        if not description:
            description = tr("Stock adjustment: total {old} -> {new}").format(
                old=format_currency(old_total), new=format_currency(new_total))

        add_adjustment(
            receipt_id, visit_id=visit_id, adjusted_by=user_id,
            description=description, old_total=old_total, new_total=new_total,
            details=(adjustment or {}).get("details") or [],
        )
        record_action("ADJUST", "receipts", receipt_id, changes=changes,
                      user_id=user_id)
    except Exception as e:
        logger.error("Could not record the adjustment trail for receipt %s: %s",
                     receipt_id, e)


def get_owner_financial_summary(client_id):
    """Aggregates billing and payment totals for all of an owner's receipts.

    Returns a dict with receipt_count, open_receipts (receipts that still
    carry an outstanding balance), total_billed, total_paid and outstanding.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COUNT(*),
               COALESCE(SUM(r.total_price), 0),
               COALESCE((SELECT SUM(p.amount) FROM payments p
                         WHERE p.receipt_id IN
                               (SELECT receipt_id FROM receipts WHERE owner_id = ?)), 0)
        FROM receipts r
        WHERE r.owner_id = ?
    """)
    query.addBindValue(client_id)
    query.addBindValue(client_id)
    receipt_count = 0
    total_billed = 0.0
    total_paid = 0.0
    if query.exec() and query.next():
        receipt_count = int(query.value(0) or 0)
        total_billed = float(query.value(1) or 0)
        total_paid = float(query.value(2) or 0)

    open_receipts = 0
    if receipt_count:
        oq = QSqlQuery(db)
        oq.prepare("""
            SELECT COUNT(*)
            FROM (
                SELECT r.receipt_id
                FROM receipts r
                LEFT JOIN payments p ON p.receipt_id = r.receipt_id
                WHERE r.owner_id = ?
                GROUP BY r.receipt_id
                HAVING COALESCE(r.total_price, 0) > COALESCE(SUM(p.amount), 0)
            )
        """)
        oq.addBindValue(client_id)
        if oq.exec() and oq.next():
            open_receipts = int(oq.value(0) or 0)

    return {
        "receipt_count": receipt_count,
        "open_receipts": open_receipts,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "outstanding": round(max(total_billed - total_paid, 0.0), 2),
    }


def get_open_receipt_balances_for_owner(client_id):
    """Returns (receipt_id, outstanding_amount) pairs for an owner's unsettled receipts."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT r.receipt_id,
               COALESCE(r.total_price, 0),
               COALESCE(SUM(p.amount), 0)
        FROM receipts r
        LEFT JOIN payments p ON p.receipt_id = r.receipt_id
        WHERE r.owner_id = ?
        GROUP BY r.receipt_id
        HAVING COALESCE(r.total_price, 0) > COALESCE(SUM(p.amount), 0)
        ORDER BY r.receipt_id
    """)
    query.addBindValue(client_id)
    results = []
    if query.exec():
        while query.next():
            receipt_id = query.value(0)
            total = float(query.value(1) or 0)
            paid = float(query.value(2) or 0)
            results.append((int(receipt_id), round(max(total - paid, 0.0), 2)))
    return results


def get_receipt_for_visit(visit_id):
    """Returns the (newest) receipt id billed for a visit, or None.

    Used by the Visit Details dialog to resolve billing when it was opened
    from a context that only carried the visit id (pet/owner dialogs).
    """
    if visit_id is None:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "SELECT receipt_id FROM receipts WHERE visit_id = ? "
        "ORDER BY receipt_id DESC LIMIT 1"
    )
    query.addBindValue(visit_id)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_receipt(receipt_id):
    """Returns a single receipt header (with discount) or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT r.receipt_id, r.receipt_date, r.total_price,
               r.discount, r.receipt_code, r.owner_id, r.visit_id,
               o.first_name || ' ' || o.last_name AS owner_name,
               c.phone_number AS owner_phone,
               COALESCE(r.payment_status, 'Unpaid') AS payment_status,
               r.notes AS notes, r.receipt_kind,
               p.pet_name AS pet_name
        FROM receipts r
        LEFT JOIN owners o ON r.owner_id = o.owner_id
        LEFT JOIN entity_contacts ec
               ON ec.entity_type = 'owner' AND ec.entity_id = r.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        LEFT JOIN visits v ON r.visit_id = v.visit_id
        LEFT JOIN pets p ON v.pet_id = p.pet_id
        WHERE r.receipt_id = ?
    """)
    query.addBindValue(receipt_id)
    if query.exec() and query.next():
        return {
            "receipt_id": query.value(0),
            "receipt_date": query.value(1),
            "total_price": query.value(2),
            "discount": query.value(3) or 0,
            "receipt_code": query.value(4),
            "owner_id": query.value(5),
            "visit_id": query.value(6),
            "owner_name": query.value(7) or "",
            "owner_phone": query.value(8) or "",
            "payment_status": query.value(9) or "Unpaid",
            "notes": query.value(10) or "",
            "receipt_kind": query.value(11) or "",
            "pet_name": query.value(12) or "",
        }
    return None


def get_receipt_line_items(receipt_id):
    """Returns editable line items for a receipt.

    Each item has: line_type ("Supply"/"Service"/"Package"/"Other"),
    link_id (the line PK), item_id, name, quantity, unit_price.
    Supplies/services/other are editable; packages are shown read-only.
    """
    db = get_connection()
    items = []

    q = QSqlQuery(db)
    # LEFT JOINs on the catalog: a deleted supply/service/package must not hide
    # its receipt line (the money is still in receipts.total_price).
    q.prepare("""
        SELECT rs.receipt_supply_id, rs.supply_id, s.item_name,
               rs.quantity, rs.unit_price, s.category, s.sub_category
        FROM receipt_supplies rs
        LEFT JOIN supplies s ON rs.supply_id = s.supply_id
        WHERE rs.receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec():
        while q.next():
            items.append({
                "line_type": "Supply",
                "link_id": q.value(0),
                "item_id": q.value(1),
                "name": q.value(2) or tr("(deleted item)"),
                "quantity": q.value(3),
                "unit_price": q.value(4),
                "category": q.value(5),
                "sub_category": q.value(6),
            })

    q.prepare("""
        SELECT rs.receipt_service_id, rs.service_id, srv.service_name,
               rs.quantity, rs.unit_price
        FROM receipt_services rs
        LEFT JOIN services_lookup srv ON rs.service_id = srv.service_id
        WHERE rs.receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec():
        while q.next():
            items.append({
                "line_type": "Service",
                "link_id": q.value(0),
                "item_id": q.value(1),
                "name": q.value(2) or tr("(deleted service)"),
                "quantity": q.value(3),
                "unit_price": q.value(4),
            })

    q.prepare("""
        SELECT ro.receipt_other_id, ro.description, ro.quantity, ro.unit_price,
               ro.amount
        FROM receipt_other ro
        WHERE ro.receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec():
        while q.next():
            qty = q.value(2) if q.value(2) is not None else 1
            unit_price = q.value(3)
            if unit_price is None:
                # Legacy rows (pre quantity/unit_price) only carry `amount`;
                # deriving the unit price keeps an edit from rewriting the
                # line as 0.
                unit_price = (q.value(4) or 0) / qty if qty else (q.value(4) or 0)
            items.append({
                "line_type": "Other",
                "link_id": q.value(0),
                "item_id": q.value(0),
                "name": q.value(1),
                "quantity": qty,
                "unit_price": unit_price,
            })

    q.prepare("""
        SELECT rp.receipt_package_id, rp.package_id, pkg.package_name,
               rp.quantity, pkg.total_price
        FROM receipt_packages rp
        LEFT JOIN packages pkg ON rp.package_id = pkg.package_id
        WHERE rp.receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec():
        while q.next():
            items.append({
                "line_type": "Package",
                "link_id": q.value(0),
                "item_id": q.value(1),
                "name": q.value(2) or tr("(deleted package)"),
                "quantity": q.value(3),
                # A deleted package has no price to read; keep the line's
                # own share of the total rather than 0.
                "unit_price": q.value(4),
            })
    q.finish()
    return items


def update_receipt(receipt_id, discount, items, audit_user_id=None):
    """Updates a receipt's discount and line items.

    Args:
        receipt_id: The receipt to update.
        discount: The discount amount (dollar) to apply to the new total.
        items: A list of dicts with keys:
            - op: "update" | "add" | "delete" (Package lines support only
              "delete" — they are otherwise read-only)
            - item_type: "Supply" | "Service" | "Package" | "Other"
            - item_id: The supply_id / service_id / package_id / receipt_other_id
            - quantity: int
            - unit_price: float
            - name: display name (used when adding)
            - link_id: The original line PK (receipt_supply_id / receipt_service_id /
                       receipt_package_id / receipt_other_id). Supply and Package
                       deletes use it to target a single line when the same id
                       appears on more than one line of the receipt.

    Returns True on success, False on failure. Stock is reconciled for supplies.
    Every statement is checked and finished before the commit (QtSql refuses to
    commit while a statement is still active), and ``payment_status`` is
    recomputed afterwards so a total change can never leave a stale Paid/Partial
    label on the receipt.
    """
    db = get_connection()
    active = []  # every query created in this transaction, finished pre-commit

    def _new_query():
        q = QSqlQuery(db)
        active.append(q)
        return q

    def _exec(q, what):
        if not q.exec():
            raise RuntimeError(f"{what}: {q.lastError().text()}")

    def _delta_stock(supply_id, delta):
        q = _new_query()
        q.prepare("UPDATE supplies SET current_stock = current_stock + ? WHERE supply_id = ?")
        q.addBindValue(delta)
        q.addBindValue(supply_id)
        _exec(q, "stock update")
        # Keep the batch total in step with the live stock: units go back into
        # the newest batch when a line is restored, or leave the oldest batches
        # when the receipt is changed to sell more.
        if delta > 0:
            stock_repo.return_to_batch(db, supply_id, delta)
        elif delta < 0:
            stock_repo.consume_batches(db, supply_id, -delta)
        if delta:
            # Same trail as the visit/quick-purchase sales: an edited receipt
            # that sells more (or hands back) units must show in the ledger.
            stock_repo.record_movement(
                db, supply_id, "sale" if delta < 0 else "sale_return",
                delta, notes=f"Receipt #{receipt_id} edited",
                user_id=audit_user_id, receipt_id=receipt_id)

    db.transaction()
    try:
        # 0. Handle package deletions (packages are otherwise read-only).
        for it in items:
            if it["item_type"] == "Package" and it["op"] == "delete":
                # Target the exact line (receipt_package_id) when the caller
                # gives it; fall back to package_id for legacy callers.
                link_id = it.get("link_id")
                q = _new_query()
                if link_id is not None:
                    q.prepare("DELETE FROM receipt_packages "
                              "WHERE receipt_id = ? AND receipt_package_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(link_id)
                else:
                    q.prepare("DELETE FROM receipt_packages WHERE receipt_id = ? AND package_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(it["item_id"])
                _exec(q, "package delete")

        # 1. Reconcile stock for deleted/updated supply lines.
        for it in items:
            if it["item_type"] != "Supply":
                continue
            if it["op"] == "delete":
                # Delete exactly the line the caller removed. A supply can
                # appear on more than one line of the same receipt, so match on
                # the line PK (link_id) when present — matching by supply_id
                # would delete every line and restore the wrong quantity.
                link_id = it.get("link_id")
                q = _new_query()
                if link_id is not None:
                    q.prepare("SELECT quantity FROM receipt_supplies "
                              "WHERE receipt_id = ? AND receipt_supply_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(link_id)
                else:
                    q.prepare("SELECT quantity FROM receipt_supplies "
                              "WHERE receipt_id = ? AND supply_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(it["item_id"])
                _exec(q, "supply line lookup")
                if q.next():
                    # Restore the stored quantity to stock.
                    _delta_stock(it["item_id"], int(q.value(0)))
                q.finish()
                q = _new_query()
                if link_id is not None:
                    q.prepare("DELETE FROM receipt_supplies "
                              "WHERE receipt_id = ? AND receipt_supply_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(link_id)
                else:
                    q.prepare("DELETE FROM receipt_supplies WHERE receipt_id = ? AND supply_id = ?")
                    q.addBindValue(receipt_id)
                    q.addBindValue(it["item_id"])
                _exec(q, "supply line delete")
            elif it["op"] == "update":
                q = _new_query()
                q.prepare("SELECT quantity FROM receipt_supplies WHERE receipt_supply_id = ?")
                q.addBindValue(it["link_id"])
                _exec(q, "supply line lookup")
                old_qty = 0
                if q.next():
                    old_qty = int(q.value(0))
                q.finish()
                _delta_stock(it["item_id"], old_qty - int(it["quantity"]))
                q = _new_query()
                q.prepare("UPDATE receipt_supplies SET quantity = ?, unit_price = ? WHERE receipt_supply_id = ?")
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                q.addBindValue(it["link_id"])
                _exec(q, "supply line update")
            elif it["op"] == "add":
                q = _new_query()
                q.prepare("INSERT INTO receipt_supplies (receipt_id, supply_id, quantity, unit_price) VALUES (?, ?, ?, ?)")
                q.addBindValue(receipt_id)
                q.addBindValue(it["item_id"])
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                _exec(q, "supply line insert")
                _delta_stock(it["item_id"], -int(it["quantity"]))

        # 2. Handle services.
        for it in items:
            if it["item_type"] != "Service":
                continue
            if it["op"] == "delete":
                q = _new_query()
                q.prepare("DELETE FROM receipt_services WHERE receipt_id = ? AND service_id = ?")
                q.addBindValue(receipt_id)
                q.addBindValue(it["item_id"])
                _exec(q, "service line delete")
            elif it["op"] == "update":
                q = _new_query()
                q.prepare("UPDATE receipt_services SET quantity = ?, unit_price = ? WHERE receipt_service_id = ?")
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                q.addBindValue(it["link_id"])
                _exec(q, "service line update")
            elif it["op"] == "add":
                q = _new_query()
                q.prepare("INSERT INTO receipt_services (receipt_id, service_id, quantity, unit_price) VALUES (?, ?, ?, ?)")
                q.addBindValue(receipt_id)
                q.addBindValue(it["item_id"])
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                _exec(q, "service line insert")

        # 3. Handle "other" lines.
        for it in items:
            if it["item_type"] != "Other":
                continue
            if it["op"] == "delete":
                q = _new_query()
                q.prepare("DELETE FROM receipt_other WHERE receipt_id = ? AND receipt_other_id = ?")
                q.addBindValue(receipt_id)
                q.addBindValue(it["item_id"])
                _exec(q, "other line delete")
            elif it["op"] == "update":
                q = _new_query()
                q.prepare("UPDATE receipt_other SET description = ?, amount = ?, quantity = ?, unit_price = ? WHERE receipt_other_id = ?")
                q.addBindValue(it.get("name", ""))
                q.addBindValue(float(it["unit_price"]) * int(it["quantity"]))
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                q.addBindValue(it["link_id"])
                _exec(q, "other line update")
            elif it["op"] == "add":
                q = _new_query()
                q.prepare("INSERT INTO receipt_other (receipt_id, description, amount, quantity, unit_price) VALUES (?, ?, ?, ?, ?)")
                q.addBindValue(receipt_id)
                q.addBindValue(it.get("name", ""))
                q.addBindValue(float(it["unit_price"]) * int(it["quantity"]))
                q.addBindValue(int(it["quantity"]))
                q.addBindValue(float(it["unit_price"]))
                _exec(q, "other line insert")

        # 4. Recompute total from remaining line items and apply the discount.
        subtotal = _compute_receipt_subtotal(db, receipt_id)
        new_total = max(0.0, subtotal - float(discount))
        q = _new_query()
        q.prepare("UPDATE receipts SET total_price = ?, discount = ? WHERE receipt_id = ?")
        q.addBindValue(new_total)
        q.addBindValue(float(discount))
        q.addBindValue(receipt_id)
        _exec(q, "receipt total update")

        # QtSql refuses to commit while a statement is still active.
        for qq in active:
            qq.finish()

        if not db.commit():
            db.rollback()
            return False
        if audit_user_id is not None:
            from src.core.repositories.audit_repo import record_action
            record_action("UPDATE", "receipts", receipt_id, user_id=audit_user_id)
        # The total moved: the stored Paid/Partial/Unpaid label must follow it,
        # otherwise a receipt edited down to its balance still reads Paid.
        from src.core.repositories.payment_repo import update_receipt_payment_status
        update_receipt_payment_status(receipt_id)
        return True
    except Exception as e:
        logger.error(f"Failed to update receipt {receipt_id}: {e}")
        for qq in active:
            qq.finish()
        db.rollback()
        return False


def _compute_receipt_subtotal(db, receipt_id):
    """Returns the sum of all line items (before discount) for a receipt."""
    subtotal = 0.0
    q = QSqlQuery(db)
    q.prepare("""
        SELECT COALESCE(SUM(quantity * unit_price), 0)
        FROM receipt_supplies WHERE receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec() and q.next():
        subtotal += q.value(0) or 0.0

    q.prepare("""
        SELECT COALESCE(SUM(quantity * unit_price), 0)
        FROM receipt_services WHERE receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec() and q.next():
        subtotal += q.value(0) or 0.0

    q.prepare("""
        SELECT COALESCE(SUM(amount), 0)
        FROM receipt_other WHERE receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec() and q.next():
        subtotal += q.value(0) or 0.0

    q.prepare("""
        SELECT COALESCE(SUM(rp.quantity * pkg.total_price), 0)
        FROM receipt_packages rp
        JOIN packages pkg ON rp.package_id = pkg.package_id
        WHERE rp.receipt_id = ?
    """)
    q.addBindValue(receipt_id)
    if q.exec() and q.next():
        subtotal += q.value(0) or 0.0
    q.finish()
    return subtotal


def has_consultation_service(receipt_id):
    """Returns True if the receipt already carries a 'Consultation' service line."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("""
        SELECT COUNT(*) FROM receipt_services rs
        JOIN services_lookup sl ON rs.service_id = sl.service_id
        WHERE rs.receipt_id = ? AND sl.service_name = 'Consultation'
    """)
    q.addBindValue(receipt_id)
    found = False
    if q.exec() and q.next():
        found = int(q.value(0)) > 0
    q.finish()
    return found


def reconcile_consultation(receipt_id, consult_on, consult_fee):
    """Adds or removes the 'Consultation' service line on a receipt.

    Consult is modelled as a dedicated service line on the sale receipt (see
    visit_repo.add_visit). This helper keeps that line in sync when a visit's
    consultation setting is toggled during an adjustment.

    Returns True if the consultation state changed and the receipt totals should
    be recomputed, False otherwise.
    """
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT service_id FROM services_lookup WHERE service_name = 'Consultation'")
    service_id = None
    if q.exec() and q.next():
        service_id = q.value(0)
    q.finish()
    has = has_consultation_service(receipt_id)

    if consult_on and service_id is not None and not has:
        ins = QSqlQuery(db)
        ins.prepare("""
            INSERT INTO receipt_services (receipt_id, service_id, quantity, unit_price)
            VALUES (?, ?, 1, ?)
        """)
        ins.addBindValue(receipt_id)
        ins.addBindValue(service_id)
        ins.addBindValue(float(consult_fee or 0.0))
        ok = ins.exec()
        ins.finish()
        return ok
    if not consult_on and has:
        dq = QSqlQuery(db)
        if service_id is not None:
            dq.prepare("DELETE FROM receipt_services WHERE receipt_id = ? AND service_id = ?")
            dq.addBindValue(receipt_id)
            dq.addBindValue(service_id)
        else:
            dq.prepare("""
                DELETE FROM receipt_services WHERE receipt_id = ?
                  AND receipt_service_id IN (
                      SELECT rs.receipt_service_id FROM receipt_services rs
                      JOIN services_lookup sl ON rs.service_id = sl.service_id
                      WHERE rs.receipt_id = ? AND sl.service_name = 'Consultation'
                  )
            """)
            dq.addBindValue(receipt_id)
            dq.addBindValue(receipt_id)
        ok = dq.exec()
        dq.finish()
        return ok
    return False


def recompute_receipt_total(receipt_id, discount=None):
    """Recomputes a receipt's total_price from its line items and stored discount.

    Useful after the consultation line is reconciled (which update_receipt does
    not handle). When discount is None, the currently stored discount is reused.
    Also re-derives payment_status, so a total change is reflected immediately.
    Returns the new total, or None on failure.
    """
    db = get_connection()
    if discount is None:
        dq = QSqlQuery(db)
        dq.prepare("SELECT discount FROM receipts WHERE receipt_id = ?")
        dq.addBindValue(receipt_id)
        discount = 0.0
        if dq.exec() and dq.next():
            discount = dq.value(0) or 0.0
        dq.finish()
    subtotal = _compute_receipt_subtotal(db, receipt_id)
    new_total = max(0.0, subtotal - float(discount))
    q = QSqlQuery(db)
    q.prepare("UPDATE receipts SET total_price = ?, discount = ? WHERE receipt_id = ?")
    q.addBindValue(new_total)
    q.addBindValue(float(discount))
    q.addBindValue(receipt_id)
    ok = q.exec()
    q.finish()
    if not ok:
        return None
    from src.core.repositories import payment_repo
    payment_repo.update_receipt_payment_status(receipt_id)
    return new_total


def get_receipt_id_by_code(receipt_code):
    """Returns the receipt id for a human receipt code (case-insensitive)."""
    code = (receipt_code or "").strip()
    if not code:
        return None
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT receipt_id FROM receipts WHERE UPPER(receipt_code) = UPPER(?)")
    q.addBindValue(code)
    receipt_id = None
    if q.exec() and q.next():
        receipt_id = q.value(0)
    q.finish()
    return receipt_id


def get_expenses_for_export():
    """Returns every general expense line in the import-template shape."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COALESCE(r.receipt_date, '') AS expense_date,
               COALESCE(ro.category, '') AS category,
               COALESCE(ro.description, '') AS item_name,
               COALESCE(ro.amount, 0) AS amount,
               COALESCE(r.notes, '') AS notes,
               COALESCE(r.receipt_code, '') AS receipt_code
        FROM receipts r
        JOIN receipt_other ro ON ro.receipt_id = r.receipt_id
        WHERE COALESCE(r.receipt_kind, 'retail') = 'expense'
        ORDER BY r.receipt_date ASC, ro.receipt_other_id ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "expense_date": query.value(0) or "",
                "category": query.value(1) or "",
                "item_name": query.value(2) or "",
                "amount": query.value(3),
                "notes": query.value(4) or "",
                "receipt_code": query.value(5) or "",
            })
    query.finish()
    return results


def get_retail_sales_for_export():
    """Returns every standalone retail (quick-purchase) receipt for export.

    Supplies are flattened into the ``Name x2; Other`` form the importer's
    ``parse_items`` understands, so a retail receipt and the payments linked to
    its ``receipt_code`` round-trip together.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COALESCE(r.receipt_code, '') AS receipt_code,
               COALESCE(r.receipt_date, '') AS receipt_date,
               CASE WHEN o.owner_id IS NULL THEN ''
                    WHEN TRIM(COALESCE(o.last_name, '')) = ''
                    THEN TRIM(o.first_name)
                    ELSE TRIM(o.first_name || ' ' || o.last_name)
               END AS owner_name,
               COALESCE(c.phone_number, '') AS phone_number,
               (SELECT GROUP_CONCAT(
                           CASE WHEN rs.quantity > 1
                                THEN su.item_name || ' x' || rs.quantity
                                ELSE su.item_name END, '; ')
                FROM receipt_supplies rs
                JOIN supplies su ON su.supply_id = rs.supply_id
                WHERE rs.receipt_id = r.receipt_id) AS items,
               COALESCE(r.discount, 0) AS discount,
               COALESCE(r.notes, '') AS notes
        FROM receipts r
        LEFT JOIN owners o ON r.owner_id = o.owner_id
        LEFT JOIN entity_contacts ec
               ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
        LEFT JOIN contacts c ON ec.contact_id = c.contact_id
        WHERE COALESCE(r.receipt_kind, 'retail') = 'retail'
          AND EXISTS (SELECT 1 FROM receipt_supplies rs2
                      WHERE rs2.receipt_id = r.receipt_id)
        ORDER BY r.receipt_date ASC, r.receipt_id ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "receipt_code": query.value(0) or "",
                "receipt_date": query.value(1) or "",
                "owner_name": query.value(2) or "",
                "phone_number": query.value(3) or "",
                "items": query.value(4) or "",
                "discount": query.value(5),
                "notes": query.value(6) or "",
            })
    query.finish()
    return results


