"""
Tests for the payment repository.

Covers the payment_status derivation (Unpaid / Partial / Paid), the amount
validation added in the receipts overhaul, the audit trail every payment
mutation must leave, and the zero-total receipts that owe nothing.
"""

import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.audit_repo as audit_repo
from src.core.repositories.payment_repo import (
    add_payment,
    add_refund,
    update_payment,
    delete_payment,
    get_total_paid,
    get_receipt_balance,
    get_payments_for_receipt,
    update_receipt_payment_status,
)


def _admin():
    return {"user_id": 1, "username": "admin", "roles": ["admin"]}


def _unsettled_sale(repos, entity_factory, price=50.0):
    """A quick purchase left Unpaid so a payment can be recorded against it."""
    cid = entity_factory["make_client"]()
    _, item_name = entity_factory["make_supply"](quantity=10)
    return int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": item_name, "quantity": 1, "price": price}],
        paid=False,
    ))


def _status(receipt_id):
    return sales_repo.get_receipt(receipt_id)["payment_status"]


def test_partial_payment_marks_the_receipt_partial(fresh_db, repos, entity_factory):
    """A payment below the total must land as 'Partial', not stay 'Unpaid'."""
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)
    assert _status(receipt_id) == "Unpaid"

    add_payment(receipt_id, 20.0, "Cash", "deposit")
    assert _status(receipt_id) == "Partial"
    assert abs(get_total_paid(receipt_id) - 20.0) < 1e-6
    assert abs(get_receipt_balance(receipt_id) - 30.0) < 1e-6

    # Settling the rest flips it to Paid.
    add_payment(receipt_id, 30.0, "Cash", "balance")
    assert _status(receipt_id) == "Paid"
    assert abs(get_receipt_balance(receipt_id)) < 1e-6


def test_editing_a_payment_down_recomputes_the_status(fresh_db, repos, entity_factory):
    """update_payment must re-derive payment_status, not just the row."""
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)
    pid = add_payment(receipt_id, 50.0, "Cash")
    assert _status(receipt_id) == "Paid"

    assert update_payment(pid, amount=10.0)
    assert _status(receipt_id) == "Partial"

    assert delete_payment(pid)
    assert _status(receipt_id) == "Unpaid"


def test_delete_payment_clears_the_balance(fresh_db, repos, entity_factory):
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)
    pid = add_payment(receipt_id, 50.0, "Card")
    assert get_receipt_balance(receipt_id) == 0

    assert delete_payment(pid)
    assert abs(get_receipt_balance(receipt_id) - 50.0) < 1e-6
    assert _status(receipt_id) == "Unpaid"


def test_amounts_must_be_positive(fresh_db, repos, entity_factory):
    """0 / negative / None amounts are rejected before touching the DB."""
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)

    assert add_payment(receipt_id, 0) is None
    assert add_payment(receipt_id, -5) is None
    assert add_payment(receipt_id, None) is None
    assert get_total_paid(receipt_id) == 0

    pid = add_payment(receipt_id, 10.0, "Cash")
    assert pid is not None
    assert update_payment(pid, amount=0) is False
    assert update_payment(pid, amount=-1) is False
    # A None amount means "leave this field alone".
    assert update_payment(pid, amount=None, notes="kept")


def test_status_uses_a_small_tolerance(fresh_db, repos, entity_factory):
    """Paying 99.997 of 100.00 is Paid for every practical purpose."""
    cid = entity_factory["make_client"]()
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": "Odd Price", "quantity": 1, "price": 100.0}],
        paid=False,
    ))
    add_payment(receipt_id, 99.997, "Cash")
    assert _status(receipt_id) == "Paid"


def test_zero_total_receipt_is_paid_without_any_payment(fresh_db, repos, entity_factory):
    """A 0.00 receipt owes nothing - no payment row is needed to settle it."""
    cid = entity_factory["make_client"]()
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": "Free Sample", "quantity": 3, "price": 0.0}],
    ))
    assert _status(receipt_id) == "Paid"
    assert get_total_paid(receipt_id) == 0
    assert get_receipt_balance(receipt_id) == 0


def test_receipt_total_change_recomputes_status(fresh_db, repos, entity_factory):
    """recompute_receipt_total must refresh payment_status as well."""
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)
    add_payment(receipt_id, 50.0, "Cash")
    assert _status(receipt_id) == "Paid"

    # Editing the receipt down to 30.00 leaves 20.00 overpaid, still Paid.
    new_total = sales_repo.recompute_receipt_total(receipt_id, discount=20.0)
    assert abs(new_total - 30.0) < 1e-6
    assert _status(receipt_id) == "Paid"

    # The mirror: no payment and a bigger total stays Unpaid.
    receipt2 = _unsettled_sale(repos, entity_factory, price=10.0)
    assert update_receipt_payment_status(receipt2) in (None, True)
    assert _status(receipt2) == "Unpaid"


def test_payment_mutations_are_audited(fresh_db, repos, entity_factory):
    """ADD / EDIT / DELETE on payments show up in the audit log with the user."""
    user_id = _admin()["user_id"]
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)

    pid = add_payment(receipt_id, 20.0, "Cash", "deposit", audit_user_id=user_id)
    assert pid is not None
    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "payments"]
    assert rows and rows[0]["user_id"] == user_id
    details = audit_repo.get_change_details(rows[0]["change_header_id"])
    assert details[0]["field_name"] == "action"
    assert details[0]["new_value"] == "ADD"

    update_payment(pid, amount=25.0, audit_user_id=user_id)
    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "payments"]
    assert len(rows) >= 2

    delete_payment(pid, audit_user_id=user_id)
    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "payments"]
    assert len(rows) >= 3


def test_no_user_id_writes_no_audit_row(fresh_db, repos, entity_factory):
    """Anonymous (None) callers still move money but leave no attribution."""
    receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)
    pid = add_payment(receipt_id, 10.0, "Cash")
    assert pid is not None

    rows = [r for r in audit_repo.get_recent_changes(limit=500)
            if r["table_name"] == "payments"]
    assert rows == []


# ---------------------------------------------------------------------------
# add_refund - giving a credit back (an overpaid / corrected receipt)
# ---------------------------------------------------------------------------
class TestRefund:
    def _overpaid(self, repos, entity_factory, price=50.0, paid=80.0):
        receipt_id = _unsettled_sale(repos, entity_factory, price=price)
        assert add_payment(receipt_id, paid, "Cash") is not None
        return receipt_id

    def test_refund_settles_an_overpaid_receipt(self, fresh_db, repos, entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)  # 50 billed, 80 paid
        assert abs(get_receipt_balance(receipt_id) - (-30.0)) < 1e-6

        pid = add_refund(receipt_id, 30.0, "Card", "giving back the credit")

        assert pid is not None
        rows = get_payments_for_receipt(receipt_id)
        refund = [r for r in rows if float(r["amount"]) < 0]
        assert len(refund) == 1
        assert abs(float(refund[0]["amount"]) - (-30.0)) < 1e-6
        assert refund[0]["payment_method"] == "Card"
        assert abs(get_receipt_balance(receipt_id)) < 1e-6
        assert _status(receipt_id) == "Paid"

    def test_refund_may_be_partial(self, fresh_db, repos, entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)

        assert add_refund(receipt_id, 10.0, "Cash") is not None

        assert abs(get_receipt_balance(receipt_id) - (-20.0)) < 1e-6
        assert _status(receipt_id) == "Paid"

    def test_refund_cannot_exceed_the_credit(self, fresh_db, repos, entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)  # credit of 30

        assert add_refund(receipt_id, 40.0, "Cash") is None

        assert abs(get_receipt_balance(receipt_id) - (-30.0)) < 1e-6
        assert not [r for r in get_payments_for_receipt(receipt_id)
                    if float(r["amount"]) < 0]

    def test_refund_without_a_credit_is_refused(self, fresh_db, repos, entity_factory):
        receipt_id = _unsettled_sale(repos, entity_factory, price=50.0)  # owes 50
        assert add_refund(receipt_id, 10.0, "Cash") is None

        receipt_id = self._overpaid(repos, entity_factory, price=50.0, paid=50.0)
        assert add_refund(receipt_id, 10.0, "Cash") is None, "settled is not credit"
        assert get_payments_for_receipt(receipt_id)

    def test_refund_rejects_non_positive_amounts(self, fresh_db, repos, entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)
        assert add_refund(receipt_id, 0.0, "Cash") is None
        assert add_refund(receipt_id, -10.0, "Cash") is None
        assert add_refund(receipt_id, None, "Cash") is None

    def test_refund_is_audited(self, fresh_db, repos, entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)
        user_id = 1

        pid = add_refund(receipt_id, 30.0, "Cash", audit_user_id=user_id)
        assert pid is not None

        rows = [r for r in audit_repo.get_recent_changes(limit=500)
                if r["table_name"] == "payments"]
        assert rows and rows[0]["user_id"] == user_id
        details = audit_repo.get_change_details(rows[0]["change_header_id"])
        assert details[0]["new_value"] == "REFUND"

    def test_refund_without_a_user_writes_no_audit_row(self, fresh_db, repos,
                                                       entity_factory):
        receipt_id = self._overpaid(repos, entity_factory)
        assert add_refund(receipt_id, 30.0, "Cash") is not None

        rows = [r for r in audit_repo.get_recent_changes(limit=500)
                if r["table_name"] == "payments"]
        assert rows == []
