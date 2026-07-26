"""
Stock Repository for the PET Application.
Handles batch-level stock tracking via the stocks table.

Every batch carries its own expiry date and buy price: the same item can be
bought twice at different prices and expire on different dates.
"""

import logging
from datetime import date

from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection
from src.utils.i18n import tr

logger = logging.getLogger(__name__)

_BATCH_SELECT = """
    SELECT st.batch_id, st.supply_id, st.supplier_id, st.purchase_date,
           st.expiry_date, st.buy_price, st.quantity, st.notes, sp.supplier_name,
           st.receipt_id
    FROM stocks st
    LEFT JOIN suppliers sp ON st.supplier_id = sp.supplier_id
"""

# How a batch change is described in the movement ledger / adjustment receipt.
_MOVEMENT_LABELS = {
    "purchase": "Stock batch added",
    "adjustment": "Stock batch quantity corrected",
    "removal": "Stock batch deleted",
}


def _batch_row(query):
    """Maps the current row of *query* to a batch dict.

    The driver reports NULL as an empty string, so the optional values are
    normalized back to None: a batch can have no supplier, no expiry date and no
    buy price, and re-binding '' into a foreign key would fail the update.
    """
    expiry_date = query.value(4)
    buy_price = query.value(5)
    supplier_id = query.value(2)
    return {
        "batch_id": query.value(0),
        "supply_id": query.value(1),
        "supplier_id": supplier_id or None,
        "purchase_date": query.value(3),
        "expiry_date": expiry_date or None,
        "buy_price": buy_price if isinstance(buy_price, (int, float)) else None,
        "quantity": query.value(6),
        "notes": query.value(7),
        "supplier_name": query.value(8),
        # The expense receipt this batch was bought on (NULL for batches
        # created before the link existed, or whose receipt was deleted).
        "receipt_id": query.value(9) or None,
    }


def _supply_context(db, supply_id):
    """Returns ``(item_name, category, buy_price)`` for the item behind a batch."""
    query = QSqlQuery(db)
    query.prepare(
        "SELECT item_name, category, buy_price FROM supplies WHERE supply_id = ?")
    query.addBindValue(supply_id)
    if query.exec() and query.next():
        return query.value(0) or "", query.value(1) or "", query.value(2)
    return "", "", None


def record_movement(db, supply_id, movement_type, quantity, notes="",
                    user_id=None, receipt_id=None):
    """Writes one row to the stock movement ledger (the quantity trail).

    Takes the caller's connection so it runs inside the caller's transaction,
    like :func:`consume_batches`. Returns the new movement_id, or None.
    """
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO stock_movements (supply_id, movement_type, quantity, notes,
                                     user_id, receipt_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(supply_id)
    query.addBindValue(movement_type)
    query.addBindValue(int(quantity or 0))
    query.addBindValue(notes or None)
    query.addBindValue(user_id)
    query.addBindValue(receipt_id)
    if not query.exec():
        logger.error("Could not record a %s movement for supply %s: %s",
                     movement_type, supply_id, query.lastError().text())
        return None
    # Must be finished: callers such as update_receipt commit right after this,
    # and QtSql refuses to commit while a statement is still active.
    movement_id = int(query.lastInsertId())
    query.finish()
    return movement_id


def stamp_batch_receipt(batch_id, receipt_id):
    """Points a batch at the receipt its stock was bought on.

    Written straight (not via a repo method) because the receipt is created by
    whichever layer did the buying - sometimes after the batch row already
    exists. A NULL receipt_id clears nothing useful, so it is skipped.
    """
    if batch_id is None or receipt_id is None:
        return
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE stocks SET receipt_id = ? WHERE batch_id = ?")
    query.addBindValue(receipt_id)
    query.addBindValue(batch_id)
    if not query.exec():
        logger.warning("Could not link batch %s to receipt %s: %s",
                       batch_id, receipt_id, query.lastError().text())
    query.finish()


def _settle_batch_change(db, supply_id, delta, movement_type, unit_price, note,
                         receipt_date, user_id=None, receipt_id=None,
                         adjustment=None):
    """Keeps the item's live stock and the ledger in step with a batch change.

    - ``supplies.current_stock`` is *recomputed* from the batch total rather
      than incremented, so an item that had drifted earlier is repaired instead
      of carrying the drift forward.
    - A ``stock_movements`` row records the signed quantity that moved.
    - The financial effect (``delta * unit_price``) is posted as an expense
      entry so the correction also shows up in the profit reports. When
      ``receipt_id`` is given that entry is folded into the batch's own
      purchase receipt instead of creating another one - and because that
      receipt really changed, ``adjustment`` (``{"description": ..,
      "details": [..]}``) is handed along so the same revision row a receipt
      edit writes lands in its Adjustments list.

    Returns the receipt_id the entry landed on, or None when nothing was posted.
    """
    delta = int(delta or 0)

    sync = QSqlQuery(db)
    sync.prepare("""
        UPDATE supplies
        SET current_stock = (SELECT COALESCE(SUM(quantity), 0)
                             FROM stocks WHERE supply_id = ?)
        WHERE supply_id = ?
    """)
    sync.addBindValue(supply_id)
    sync.addBindValue(supply_id)
    if not sync.exec():
        logger.error("Could not re-sync current_stock for supply %s: %s",
                     supply_id, sync.lastError().text())
    sync.finish()

    if delta == 0:
        # A price/date/notes-only edit moves no stock: nothing to bill, and a
        # zero-quantity movement row would be noise in the ledger.
        return None

    item_name, category, item_price = _supply_context(db, supply_id)
    price = item_price if unit_price is None else unit_price
    posted_on = None
    if price:
        # Local import: sales_repo imports this module at import time.
        from src.core.repositories import sales_repo
        posted_on = sales_repo.log_stock_adjustment(
            supply_id, item_name, category, delta, price, receipt_date,
            notes=note, receipt_id=receipt_id, user_id=user_id,
            adjustment=adjustment)

    record_movement(db, supply_id, movement_type, delta, notes=note,
                    user_id=user_id, receipt_id=posted_on)
    return posted_on


def add_stock_batch(supply_id, supplier_id, purchase_date, quantity, notes="",
                    expiry_date=None, buy_price=None, user_id=None):
    """Records a new stock batch purchase.

    Adding a batch puts stock on the shelf, so the item's live stock, the
    movement ledger and the expense receipt are all brought up to date here -
    the batch dialog must not have to remember to do it.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO stocks (supply_id, supplier_id, purchase_date, expiry_date,
                            buy_price, quantity, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """)
    query.addBindValue(supply_id)
    query.addBindValue(supplier_id)
    query.addBindValue(purchase_date)
    query.addBindValue(expiry_date)
    query.addBindValue(buy_price)
    query.addBindValue(quantity)
    query.addBindValue(notes)
    if not query.exec():
        logger.error(f"Failed to add stock batch for supply {supply_id}: {query.lastError().text()}")
        return None
    batch_id = query.lastInsertId()

    item_name = _supply_context(db, supply_id)[0]
    note = f"{_MOVEMENT_LABELS['purchase']}: {item_name} +{int(quantity or 0)}"
    # The receipt this creates *is* the batch's purchase record, so store it on
    # the batch: every later correction folds into it instead of adding another
    # EXPENSE row to the ledger.
    receipt_id = _settle_batch_change(db, supply_id, quantity, "purchase",
                                      buy_price, note, purchase_date,
                                      user_id=user_id)
    stamp_batch_receipt(batch_id, receipt_id)

    if user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("ADD", "stocks", batch_id,
                      changes=[{"field_name": "quantity", "old_value": "",
                                "new_value": str(int(quantity or 0))}],
                      user_id=user_id)
    return batch_id


def get_stock_batches(supply_id):
    """Retrieves all stock batches for a given supply, newest purchase first."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(_BATCH_SELECT + " WHERE st.supply_id = ? ORDER BY st.purchase_date DESC")
    query.addBindValue(supply_id)
    results = []
    if query.exec():
        while query.next():
            results.append(_batch_row(query))
    return results


def get_stock_batch(batch_id):
    """Retrieves a single stock batch by its id, or None when it is gone."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(_BATCH_SELECT + " WHERE st.batch_id = ?")
    query.addBindValue(batch_id)
    if query.exec() and query.next():
        return _batch_row(query)
    return None


def update_stock_batch(batch_id, supplier_id, purchase_date, quantity, notes="",
                       expiry_date=None, buy_price=None, user_id=None):
    """Updates an existing stock batch record.

    Correcting a batch's quantity is a stock correction: the item's live stock
    is re-derived from the batches, the movement is logged and the financial
    effect of the difference is posted as an expense receipt.
    """
    db = get_connection()
    before = get_stock_batch(batch_id)

    query = QSqlQuery(db)
    query.prepare("""
        UPDATE stocks SET supplier_id = ?, purchase_date = ?, expiry_date = ?,
                          buy_price = ?, quantity = ?, notes = ?
        WHERE batch_id = ?
    """)
    query.addBindValue(supplier_id)
    query.addBindValue(purchase_date)
    query.addBindValue(expiry_date)
    query.addBindValue(buy_price)
    query.addBindValue(quantity)
    query.addBindValue(notes)
    query.addBindValue(batch_id)
    if not query.exec():
        return False

    if before is None:
        # Unknown batch: the UPDATE matched nothing, so there is no stock to
        # settle. Keep the historical "True" contract the callers rely on.
        return True

    delta = int(quantity or 0) - int(before.get("quantity") or 0)
    item_name = _supply_context(db, before["supply_id"])[0]
    old_qty = int(before.get("quantity") or 0)
    new_qty = int(quantity or 0)
    note = (f"{_MOVEMENT_LABELS['adjustment']}: {item_name} "
            f"{old_qty} -> {new_qty}")
    # The revision row shown in the receipt's Adjustments list: what this edit
    # did to the batch, in the same shape a receipt edit would report.
    details = [{"item": tr("Quantity"),
                "old_value": str(old_qty), "new_value": str(new_qty)}]
    old_price = float(before.get("buy_price") or 0.0)
    new_price = float(buy_price or 0.0)
    if abs(new_price - old_price) > 0.004:
        details.append({"item": tr("Buy Price"),
                        "old_value": f"{old_price:.2f}",
                        "new_value": f"{new_price:.2f}"})
    adjustment = {
        "description": tr("Stock batch corrected: {item} quantity {old} -> {new}"
                          ).format(item=item_name, old=old_qty, new=new_qty),
        "details": details,
    }
    # A correction happens *now*, so it is billed on the correction date, not
    # on the batch's (possibly historical) purchase date.
    posted_on = _settle_batch_change(db, before["supply_id"], delta, "adjustment",
                                     buy_price, note, date.today().isoformat(),
                                     user_id=user_id,
                                     receipt_id=before.get("receipt_id"),
                                     adjustment=adjustment)
    if before.get("receipt_id") is None:
        # Batch from before the link existed (or its receipt was deleted): the
        # entry just posted becomes its receipt, so the *next* edit appends
        # to it instead of starting yet another one.
        stamp_batch_receipt(batch_id, posted_on)

    if user_id is not None:
        from src.core.repositories.audit_repo import record_action, field_diffs
        changes = field_diffs(
            {"quantity": before.get("quantity"),
             "buy_price": before.get("buy_price"),
             "purchase_date": before.get("purchase_date")},
            {"quantity": quantity, "buy_price": buy_price,
             "purchase_date": purchase_date})
        record_action("UPDATE", "stocks", batch_id, changes=changes or None,
                      user_id=user_id)
    return True


_EXPIRING_SELECT = """
    SELECT st.batch_id, st.supply_id, sp.item_name, sp.category, sp.sub_category,
           st.purchase_date,
           COALESCE(NULLIF(st.expiry_date, ''), NULLIF(sp.expiry_date, '')) AS expiry_date,
           COALESCE(st.quantity, 0) AS quantity
    FROM stocks st
    JOIN supplies sp ON sp.supply_id = st.supply_id
    WHERE COALESCE(NULLIF(st.expiry_date, ''), NULLIF(sp.expiry_date, '')) IS NOT NULL
      AND COALESCE(st.quantity, 0) > 0
    ORDER BY expiry_date ASC, st.batch_id ASC
"""


def get_expiring_batches(days_ahead=90):
    """Lists the stock batches that expire within *days_ahead* days, soonest first.

    Expiry is batch-driven: the same item can be bought twice and expire on two
    different dates, so every row is one batch and the quantity is that batch's
    own stock. A batch without its own expiry date falls back to the item default
    (``supplies.expiry_date``) instead of silently dropping out of the list.
    Fully used batches (quantity 0) are skipped - there is nothing to expire.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(_EXPIRING_SELECT)
    results = []
    today = date.today()
    if query.exec():
        while query.next():
            expiry_date = query.value(6)
            try:
                days_left = (date.fromisoformat(str(expiry_date)[:10]) - today).days
            except (ValueError, TypeError):
                continue
            if not 0 <= days_left <= days_ahead:
                continue
            results.append({
                "batch_id": query.value(0),
                "supply_id": query.value(1),
                "item_name": query.value(2),
                "category": query.value(3),
                "sub_category": query.value(4),
                "purchase_date": query.value(5),
                "expiry_date": expiry_date,
                "quantity": query.value(7),
                "days_left": days_left,
            })
    return results


def delete_stock_batch(batch_id, user_id=None):
    """Deletes a stock batch record.

    The batch's units leave the shelf with it, so the item's live stock is
    re-derived, the removal is logged and its value is reversed in the ledger.
    """
    db = get_connection()
    before = get_stock_batch(batch_id)

    query = QSqlQuery(db)
    query.prepare("DELETE FROM stocks WHERE batch_id = ?")
    query.addBindValue(batch_id)
    if not query.exec():
        return False

    if before is None:
        # Nothing was deleted (unknown id): no stock to settle.
        return True

    item_name = _supply_context(db, before["supply_id"])[0]
    old_qty = int(before.get("quantity") or 0)
    note = (f"{_MOVEMENT_LABELS['removal']}: {item_name} -{old_qty}")
    adjustment = {
        "description": tr("Stock batch deleted: {item} quantity {old} -> 0"
                          ).format(item=item_name, old=old_qty),
        "details": [{"item": tr("Quantity"),
                     "old_value": str(old_qty), "new_value": "0"}],
    }
    # The reversal lands on the same receipt as the purchase, so buying 20 and
    # then deleting that batch nets the entry back out to zero.
    _settle_batch_change(db, before["supply_id"],
                         -old_qty, "removal",
                         before.get("buy_price"), note,
                         date.today().isoformat(), user_id=user_id,
                         receipt_id=before.get("receipt_id"),
                         adjustment=adjustment)

    if user_id is not None:
        from src.core.repositories.audit_repo import record_action
        record_action("DELETE", "stocks", batch_id,
                      changes=[{"field_name": "quantity",
                                "old_value": str(int(before.get("quantity") or 0)),
                                "new_value": ""}],
                      user_id=user_id)
    return True


# --- Batch depletion -------------------------------------------------------
#
# Sales take stock out of the batches (oldest purchase first), so an item's
# batch total always matches its live stock. Both helpers run on the caller's
# connection *inside the caller's transaction*: pass the very same `db` the
# receipt/visit write is using, or the write blocks on the open transaction.
# Both return the movement they performed; ``None`` means "nothing to move".

def consume_batches(db, supply_id, quantity):
    """Draws *quantity* out of the item's batches, oldest purchase first (FIFO).

    Batches are left in place with the quantity that is left, so the purchase
    history (date, supplier, buy price, expiry) survives a sale.
    """
    quantity = int(quantity or 0)
    if quantity <= 0:
        return None

    query = QSqlQuery(db)
    query.prepare("""
        SELECT batch_id, COALESCE(quantity, 0) FROM stocks
        WHERE supply_id = ?
        ORDER BY (purchase_date IS NULL), purchase_date ASC, batch_id ASC
    """)
    query.addBindValue(supply_id)
    batches = []
    if query.exec():
        while query.next():
            batches.append((int(query.value(0)), int(query.value(1) or 0)))
    query.finish()

    remaining = quantity
    updates = []
    for batch_id, available in batches:
        if remaining <= 0:
            break
        if available <= 0:
            continue
        taken = min(available, remaining)
        remaining -= taken
        updates.append((batch_id, available - taken))
    if remaining > 0:
        # No batches left to draw from: the stock check already rejected this,
        # so leave the batches alone rather than making them negative.
        logger.warning(
            "Batch stock for supply %s is short by %s; batches left untouched",
            supply_id, remaining)
        return None

    update = QSqlQuery(db)
    for batch_id, left in updates:
        update.prepare("UPDATE stocks SET quantity = ? WHERE batch_id = ?")
        update.addBindValue(left)
        update.addBindValue(batch_id)
        if not update.exec():
            logger.error("Failed to deplete stock batch %s: %s",
                         batch_id, update.lastError().text())
            update.finish()
            return None
    # QtSql refuses to commit while a statement is still active.
    update.finish()
    return quantity - remaining


def return_to_batch(db, supply_id, quantity):
    """Puts *quantity* back into the item's most recent batch (newest first).

    Used when a receipt line is edited or removed and the stock has to go back.
    """
    quantity = int(quantity or 0)
    if quantity <= 0:
        return None

    query = QSqlQuery(db)
    query.prepare("""
        SELECT batch_id FROM stocks WHERE supply_id = ?
        ORDER BY (purchase_date IS NULL), purchase_date DESC, batch_id DESC
        LIMIT 1
    """)
    query.addBindValue(supply_id)
    batch_id = None
    if query.exec() and query.next():
        batch_id = int(query.value(0))
    query.finish()
    if batch_id is None:
        logger.warning("No stock batch to return %s to for supply %s", quantity, supply_id)
        return None

    update = QSqlQuery(db)
    update.prepare("UPDATE stocks SET quantity = COALESCE(quantity, 0) + ? WHERE batch_id = ?")
    update.addBindValue(quantity)
    update.addBindValue(batch_id)
    if not update.exec():
        logger.error("Failed to restock batch %s: %s", batch_id, update.lastError().text())
        update.finish()
        return None
    update.finish()
    return quantity


def get_total_stock_for_supply(supply_id):
    """Sums all batch quantities for a given supply."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT COALESCE(SUM(quantity), 0) FROM stocks WHERE supply_id = ?")
    query.addBindValue(supply_id)
    if query.exec() and query.next():
        return query.value(0)
    return 0