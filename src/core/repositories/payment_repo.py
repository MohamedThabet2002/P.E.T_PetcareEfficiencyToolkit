"""
Payment Repository for the PET Application.
Handles recording payments against receipts and tracking payment status.

Every mutation accepts an optional ``audit_user_id`` so add/edit/delete of a
payment shows up in Reports -> Audit Log like every other money movement, and
every query is ``finish()``-ed: QtSql refuses to commit a transaction while a
statement is still active.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)

# Floats coming from spinboxes can land a hair under the true total (19.999999
# vs 20.0); compare with a cent-scale epsilon so such a receipt reads Paid.
_EPSILON = 0.004


def _field_diffs(old, new):
    """Builds audit diffs for the payment fields that changed."""
    changes = []
    labels = {"amount": "amount", "payment_method": "method", "notes": "notes"}
    for key, label in labels.items():
        if new.get(key) is not None and str(old.get(key) or "") != str(new.get(key) or ""):
            changes.append({
                "field_name": label,
                "old_value": old.get(key),
                "new_value": new.get(key),
            })
    return changes


def _record_payment_audit(action, payment_id, changes=None, user_id=None):
    if user_id is None:
        return
    from src.core.repositories.audit_repo import record_action
    record_action(action, "payments", payment_id, changes=changes or None,
                  user_id=user_id)


def add_payment(receipt_id, amount, payment_method="Cash", notes="",
                audit_user_id=None, payment_date=None):
    """Records a payment against a receipt. Returns the new payment_id or None.

    ``payment_date`` (an ISO date string) overrides the schema's ``CURRENT_DATE``
    default so an imported payment keeps the date it was recorded on.
    """
    if amount is None or float(amount) <= 0:
        logger.error(f"Rejected payment of {amount} for receipt {receipt_id}")
        return None
    db = get_connection()
    query = QSqlQuery(db)
    if payment_date:
        query.prepare("""
            INSERT INTO payments (receipt_id, amount, payment_method, notes, payment_date)
            VALUES (?, ?, ?, ?, ?)
        """)
    else:
        query.prepare("""
            INSERT INTO payments (receipt_id, amount, payment_method, notes)
            VALUES (?, ?, ?, ?)
        """)
    query.addBindValue(receipt_id)
    query.addBindValue(float(amount))
    query.addBindValue(payment_method)
    query.addBindValue(notes)
    if payment_date:
        query.addBindValue(payment_date)
    if not query.exec():
        logger.error(f"Failed to add payment for receipt {receipt_id}: {query.lastError().text()}")
        query.finish()
        return None
    payment_id = query.lastInsertId()
    query.finish()
    update_receipt_payment_status(receipt_id)
    _record_payment_audit(
        "ADD", payment_id,
        changes=[{"field_name": "amount", "old_value": "", "new_value": amount}],
        user_id=audit_user_id)
    return payment_id


def add_refund(receipt_id, amount, payment_method="Cash", notes="",
               audit_user_id=None, payment_date=None):
    """Hands a credit back on a receipt: money the clinic already over-collected.

    A batch correction can shrink a bill that was already settled in full, so
    ``payments`` ends up holding more than the receipt is worth. The credit is
    released the same way it was taken - a *negative* payment row - which keeps
    ``get_total_paid`` / ``get_receipt_balance`` / every balance screen working
    without a second book.

    ``amount`` is the refund handed back and must be positive; it may not be
    larger than the credit that exists (the receipt must not be pushed from
    overpaid into owing). Returns the new payment_id, or None when refused.

    ``payment_method`` is the physical way the money goes back (the schema only
    allows Cash / Card / Bank Transfer / Other, so "Refund" is not a method -
    the sign of the amount is what marks it).
    """
    if amount is None or float(amount) <= 0:
        logger.error(f"Rejected refund of {amount} for receipt {receipt_id}")
        return None
    credit = -get_receipt_balance(receipt_id)
    if credit <= _EPSILON:
        logger.error(f"Rejected refund of {amount} for receipt {receipt_id}: "
                     f"no credit to give back (credit {credit})")
        return None
    if float(amount) > credit + _EPSILON:
        logger.error(f"Rejected refund of {amount} for receipt {receipt_id}: "
                     f"exceeds the credit of {credit}")
        return None

    db = get_connection()
    query = QSqlQuery(db)
    if payment_date:
        query.prepare("""
            INSERT INTO payments (receipt_id, amount, payment_method, notes, payment_date)
            VALUES (?, ?, ?, ?, ?)
        """)
    else:
        query.prepare("""
            INSERT INTO payments (receipt_id, amount, payment_method, notes)
            VALUES (?, ?, ?, ?)
        """)
    query.addBindValue(receipt_id)
    query.addBindValue(-float(amount))
    query.addBindValue(payment_method)
    query.addBindValue(notes)
    if payment_date:
        query.addBindValue(payment_date)
    if not query.exec():
        logger.error(f"Failed to refund receipt {receipt_id}: {query.lastError().text()}")
        query.finish()
        return None
    payment_id = query.lastInsertId()
    query.finish()
    update_receipt_payment_status(receipt_id)
    _record_payment_audit(
        "REFUND", payment_id,
        changes=[{"field_name": "amount", "old_value": "",
                  "new_value": f"-{float(amount):.2f}"}],
        user_id=audit_user_id)
    return payment_id


def get_payments_for_receipt(receipt_id):
    """Retrieves all payments made against a receipt."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT payment_id, receipt_id, amount, payment_method, payment_date, notes, created_at
        FROM payments
        WHERE receipt_id = ?
        ORDER BY payment_date ASC, payment_id ASC
    """)
    query.addBindValue(receipt_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "payment_id": query.value(0),
                "receipt_id": query.value(1),
                "amount": query.value(2),
                "payment_method": query.value(3),
                "payment_date": query.value(4),
                "notes": query.value(5),
                "created_at": query.value(6),
            })
    query.finish()
    return results


def get_total_paid(receipt_id):
    """Returns the total amount paid for a receipt."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE receipt_id = ?")
    query.addBindValue(receipt_id)
    total = 0.0
    if query.exec() and query.next():
        total = float(query.value(0) or 0)
    query.finish()
    return total


def get_receipt_balance(receipt_id):
    """Returns the remaining balance for a receipt (total - paid)."""
    total_q = QSqlQuery(get_connection())
    total_q.prepare("SELECT total_price FROM receipts WHERE receipt_id = ?")
    total_q.addBindValue(receipt_id)
    total = 0.0
    if total_q.exec() and total_q.next():
        total = float(total_q.value(0) or 0)
    total_q.finish()
    paid = get_total_paid(receipt_id)
    return round(total - paid, 2)


def update_receipt_payment_status(receipt_id):
    """Auto-sets payment_status on the receipt based on total vs paid amount.

    The payments table is the source of truth; this is the single place the
    stored column is derived, so every writer (payment add/edit/delete and
    ``sales_repo.update_receipt``) must call it after a total or payment moves.
    """
    db = get_connection()
    total_q = QSqlQuery(db)
    total_q.prepare("SELECT total_price FROM receipts WHERE receipt_id = ?")
    total_q.addBindValue(receipt_id)
    total = 0.0
    if total_q.exec() and total_q.next():
        total = float(total_q.value(0) or 0)
    total_q.finish()

    paid = get_total_paid(receipt_id)

    # A zero-total receipt has nothing left to collect, so it is Paid (0 of 0).
    if paid + _EPSILON >= total:
        status = "Paid"
    elif paid > _EPSILON:
        status = "Partial"
    else:
        status = "Unpaid"

    uq = QSqlQuery(db)
    uq.prepare("UPDATE receipts SET payment_status = ? WHERE receipt_id = ?")
    uq.addBindValue(status)
    uq.addBindValue(receipt_id)
    ok = uq.exec()
    uq.finish()
    return ok


def update_payment(payment_id, amount=None, payment_method=None, notes=None,
                   audit_user_id=None):
    """Updates an existing payment (only the provided fields) and recalcs status."""
    if amount is not None and float(amount) <= 0:
        logger.error(f"Rejected payment update to {amount} for payment {payment_id}")
        return False
    db = get_connection()
    fields, values = [], []
    if amount is not None:
        fields.append("amount = ?")
        values.append(float(amount))
    if payment_method is not None:
        fields.append("payment_method = ?")
        values.append(payment_method)
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if not fields:
        return True

    q = QSqlQuery(db)
    q.prepare(
        "SELECT receipt_id, amount, payment_method, notes "
        "FROM payments WHERE payment_id = ?"
    )
    q.addBindValue(payment_id)
    receipt_id = None
    old = {}
    if q.exec() and q.next():
        receipt_id = q.value(0)
        old = {"amount": q.value(1), "payment_method": q.value(2), "notes": q.value(3)}
    q.finish()
    if receipt_id is None:
        return False

    uq = QSqlQuery(db)
    uq.prepare("UPDATE payments SET {} WHERE payment_id = ?".format(", ".join(fields)))
    for val in values:
        uq.addBindValue(val)
    uq.addBindValue(payment_id)
    if not uq.exec():
        logger.error(f"Failed to update payment {payment_id}: {uq.lastError().text()}")
        uq.finish()
        return False
    uq.finish()
    update_receipt_payment_status(receipt_id)
    _record_payment_audit("UPDATE", payment_id,
                          changes=_field_diffs(old, {
                              "amount": amount,
                              "payment_method": payment_method,
                              "notes": notes,
                          }),
                          user_id=audit_user_id)
    return True


def delete_payment(payment_id, audit_user_id=None):
    """Deletes a payment and recalculates the receipt payment status."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("SELECT receipt_id, amount, payment_method, notes "
              "FROM payments WHERE payment_id = ?")
    q.addBindValue(payment_id)
    receipt_id = None
    old = {}
    if q.exec() and q.next():
        receipt_id = q.value(0)
        old = {"amount": q.value(1), "payment_method": q.value(2), "notes": q.value(3)}
    q.finish()

    dq = QSqlQuery(db)
    dq.prepare("DELETE FROM payments WHERE payment_id = ?")
    dq.addBindValue(payment_id)
    result = dq.exec()
    dq.finish()

    if result and receipt_id is not None:
        update_receipt_payment_status(receipt_id)
        # Keep the deleted row's data in the audit entry so it can be restored.
        _record_payment_audit(
            "DELETE", payment_id,
            changes=[{"field_name": k, "old_value": v, "new_value": ""}
                     for k, v in (("amount", old.get("amount")),
                                  ("method", old.get("payment_method")))],
            user_id=audit_user_id)
    return result


def get_payments_for_export():
    """Returns every payment linked to its receipt's human code, for export."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COALESCE(r.receipt_code, '') AS receipt_code,
               p.amount,
               p.payment_method,
               COALESCE(p.payment_date, '') AS payment_date,
               COALESCE(p.notes, '') AS notes
        FROM payments p
        JOIN receipts r ON p.receipt_id = r.receipt_id
        ORDER BY p.payment_date ASC, p.payment_id ASC
    """)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "receipt_code": query.value(0) or "",
                "amount": query.value(1),
                "payment_method": query.value(2) or "Cash",
                "payment_date": query.value(3) or "",
                "notes": query.value(4) or "",
            })
    query.finish()
    return results
