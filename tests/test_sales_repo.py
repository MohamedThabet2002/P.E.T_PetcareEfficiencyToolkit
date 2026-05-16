import pytest
from PyQt5.QtSql import QSqlQuery

from src.core.database.migrations import run_migrations
import src.core.repositories.sales_repo as sales_repo


def _col_exists(db, table, col):
    q = QSqlQuery(db)
    q.exec(f"PRAGMA table_info({table})")
    cols = set()
    while q.next():
        cols.add(q.value(1))
    return col in cols


def test_migration_adds_discount_column(fresh_db):
    run_migrations(fresh_db)
    assert _col_exists(fresh_db, "receipts", "discount")


def test_update_receipt_discount_and_lines(fresh_db, repos, entity_factory):
    run_migrations(fresh_db)
    cid = repos["client"].add_client("Ali", "0500123")
    pid = repos["pet"].add_pet("Rex", "Dog", "Lab", "M", 24, 20.0, cid)
    sid, item_name = entity_factory["make_supply"](quantity=10)

    # Build a receipt via a quick sale.
    # create_sale_receipt_for_quick_purchase needs an item with item_name that maps to a supply.
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )
    assert receipt_id is not None

    line_items = sales_repo.get_receipt_line_items(receipt_id)
    assert len(line_items) >= 1
    supply_line = next(i for i in line_items if i["line_type"] == "Supply")
    items = [
        {"op": "update", "item_type": "Supply", "item_id": supply_line["item_id"],
         "link_id": supply_line["link_id"], "quantity": 5, "unit_price": 12.0},
        {"op": "add", "item_type": "Other", "item_id": None,
         "name": "Extra fee", "quantity": 1, "unit_price": 5.0},
    ]
    ok = sales_repo.update_receipt(receipt_id, 5.0, items)
    assert ok

    header = sales_repo.get_receipt(receipt_id)
    assert header["discount"] == 5.0
    # subtotal = 5*12 + 5 = 65; minus discount 5 = 60
    assert abs(header["total_price"] - 60.0) < 0.001

    updated_lines = sales_repo.get_receipt_line_items(receipt_id)
    other_lines = [i for i in updated_lines if i["line_type"] == "Other"]
    assert len(other_lines) == 1 and other_lines[0]["name"] == "Extra fee"

    # Stock reconciliation: sold 2 initially, then updated the line to 5.
    supply = next(i for i in repos["supply"].search_supplies() if i["supply_id"] == sid)
    assert supply["current_stock"] == 10 - 5


def test_get_owner_financial_summary(fresh_db, repos, entity_factory):
    from src.core import database
    from src.core.repositories import payment_repo
    from src.core.repositories.payment_repo import add_payment
    # payment_repo is not in conftest's patch list, so its get_connection global
    # can point at a stale (closed) connection once imported; rebind to the patch.
    payment_repo.get_connection = database.get_connection

    cid = repos["client"].add_client("Sara", "0501")
    # Owner without receipts: all zeros.
    empty = sales_repo.get_owner_financial_summary(cid)
    assert empty["receipt_count"] == 0
    assert abs(empty["total_billed"] - 0.0) < 1e-6
    assert abs(empty["outstanding"] - 0.0) < 1e-6
    assert empty["open_receipts"] == 0

    _, item_name = entity_factory["make_supply"](quantity=20)
    # paid=False: this scenario needs an outstanding receipt, while quick
    # purchases settle in full by default.
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid=False,
    )
    assert receipt_id is not None

    summary = sales_repo.get_owner_financial_summary(cid)
    assert summary["receipt_count"] == 1
    assert abs(summary["total_billed"] - 20.0) < 1e-6
    assert abs(summary["total_paid"] - 0.0) < 1e-6
    assert abs(summary["outstanding"] - 20.0) < 1e-6
    assert summary["open_receipts"] == 1

    add_payment(int(receipt_id), 5.0)
    summary = sales_repo.get_owner_financial_summary(cid)
    assert abs(summary["total_paid"] - 5.0) < 1e-6
    assert abs(summary["outstanding"] - 15.0) < 1e-6
    assert summary["open_receipts"] == 1

    add_payment(int(receipt_id), 15.0)
    summary = sales_repo.get_owner_financial_summary(cid)
    assert abs(summary["outstanding"] - 0.0) < 1e-6
    assert summary["open_receipts"] == 0


def _receipt_codes(db):
    q = QSqlQuery(db)
    q.exec("SELECT receipt_code FROM receipts WHERE receipt_code LIKE 'EXPENSE%'")
    codes = []
    while q.next():
        codes.append(q.value(0))
    return codes


def test_add_general_expense_allocates_unique_codes(fresh_db):
    """receipt_code is UNIQUE, so repeated expenses must not collide.

    Regression: every add after the first silently failed, which made the
    Add General Expense dialog's OK button appear to do nothing.
    """
    from src.core import database

    for i in range(3):
        assert sales_repo.add_general_expense(
            "2026-09-01", "Utilities", f"Bill {i}", 100.0 + i, "Monthly"
        ), f"expense #{i} failed to insert"

    codes = _receipt_codes(fresh_db)
    assert len(codes) == 3, codes
    assert len(set(codes)) == 3, codes
    assert all(c.startswith("EXPENSE-") for c in codes), codes

    # Each expense lands in the ledger with its own receipt_other line.
    names = {r["item_name"] for r in sales_repo.get_receipt_items()}
    assert {"Bill 0", "Bill 1", "Bill 2"} <= names

    # next_expense_code never returns an already-used code.
    used = {c.upper() for c in codes}
    for _ in range(20):
        assert sales_repo.next_expense_code(database.get_connection()).upper() not in used


def test_add_general_expense_accepts_explicit_code(fresh_db):
    assert sales_repo.add_general_expense(
        "2026-09-01", "Rent", "September rent", 500.0, receipt_code="EXPENSE-CUSTOM"
    )
    assert "EXPENSE-CUSTOM" in _receipt_codes(fresh_db)

    # A collision is reported instead of silently doing nothing.
    assert not sales_repo.add_general_expense(
        "2026-09-01", "Rent", "Duplicate", 1.0, receipt_code="EXPENSE-CUSTOM"
    )


def test_quick_purchase_allocates_unique_codes(fresh_db, repos, entity_factory):
    """receipt_code is UNIQUE, so repeated quick purchases must not collide.

    Regression: every quick purchase after the first failed the UNIQUE
    constraint on the hardcoded ``'Sale'`` code, so the Quick Purchase
    dialog reported "Failed to record purchase." for every purchase but
    the first one ever made in the database.
    """
    from src.core import database

    cid = entity_factory["make_client"]()
    _, item_name = entity_factory["make_supply"](quantity=50)
    items = [{"item_name": item_name, "quantity": 1, "price": 15.0}]

    ids = [
        sales_repo.create_sale_receipt_for_quick_purchase(
            cid, f"2026-09-0{i + 1}", items
        )
        for i in range(3)
    ]
    assert all(ids), f"quick purchases failed to insert: {ids}"
    assert len(set(ids)) == 3, ids

    q = QSqlQuery(fresh_db)
    q.exec("SELECT receipt_code FROM receipts")
    codes = []
    while q.next():
        codes.append(q.value(0))
    assert len(codes) == 3, codes
    assert len(set(codes)) == 3, codes

    # next_retail_code never returns an already-used code.
    used = {c.upper() for c in codes}
    for _ in range(20):
        assert sales_repo.next_retail_code(database.get_connection()).upper() not in used


def test_quick_purchase_reports_stock_error(fresh_db, repos, entity_factory):
    """Insufficient stock is reported as STOCK_ERROR, like add_visit does.

    The Quick Purchase dialog already parses that string to show
    "Not enough stock for <item>"; returning a bare None surfaced the
    generic "Failed to record purchase." message instead.
    """
    _sid, item_name = entity_factory["make_supply"](quantity=1)
    result = sales_repo.create_sale_receipt_for_quick_purchase(
        entity_factory["make_client"](), "2026-09-01",
        [{"item_name": item_name, "quantity": 5, "price": 5.0}],
    )
    assert isinstance(result, str) and result.startswith("STOCK_ERROR"), result
    assert item_name in result


def test_quick_purchase_stock_matches_item_category(fresh_db, repos, entity_factory):
    """Quick purchase checks and deducts stock per (item_name, category).

    Two supplies may share a name across categories; summing by name alone let a
    sale advertise the combined stock and then drain one row negative.
    """
    cid = entity_factory["make_client"]()
    med_sid, name = entity_factory["make_supply"](quantity=3, category="Medicine")
    eq_sid, _ = entity_factory["make_supply"](quantity=5, name=name, category="Equipment")

    # Medicine only holds 3: 4 must fail even though 3 + 5 would have covered it.
    result = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": name, "category": "Medicine", "quantity": 4, "price": 10.0}],
    )
    assert isinstance(result, str) and result.startswith("STOCK_ERROR"), result

    def _stock(sid):
        q = QSqlQuery(fresh_db)
        q.prepare("SELECT current_stock FROM supplies WHERE supply_id = ?")
        q.addBindValue(sid)
        assert q.exec() and q.next()
        return q.value(0)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-02",
        [{"item_name": name, "category": "Medicine", "quantity": 3, "price": 10.0}],
    )
    assert receipt_id is not None
    assert _stock(med_sid) == 0
    assert _stock(eq_sid) == 5



def test_quick_purchase_is_paid_on_spot(fresh_db, repos, entity_factory):
    """A quick purchase is settled at the counter, so it must not land Unpaid.

    The payment row (not just ``payment_status``) is what the ledger, the
    owner finances card and the settle-outstanding flow read, so both are
    asserted here.
    """
    cid = entity_factory["make_client"]()
    _sid, item_name = entity_factory["make_supply"](quantity=20)
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 12.5}],
        payment_notes="Paid at quick purchase",
    )
    assert receipt_id is not None

    header = sales_repo.get_receipt(receipt_id)
    assert header["payment_status"] == "Paid", header
    assert header["total_price"] == pytest.approx(25.0)

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT amount, payment_method, notes FROM payments WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert float(q.value(0)) == pytest.approx(25.0)
    assert q.value(1) == "Cash"
    assert q.value(2) == "Paid at quick purchase"

    # Balance is settled and the owner carries no outstanding amount.
    summary = sales_repo.get_owner_financial_summary(cid)
    assert summary["outstanding"] == pytest.approx(0.0)
    assert summary["open_receipts"] == 0
    assert sales_repo.get_open_receipt_balances_for_owner(cid) == []


def test_quick_purchase_with_zero_total_is_paid(fresh_db, entity_factory):
    """A purchase of supplies priced at 0 still reads as Paid (0 of 0).

    Regression: no payment row is written for a zero total, so the receipt
    kept the schema default 'Unpaid'.
    """
    cid = entity_factory["make_client"]()
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": "Free Sample", "quantity": 3, "price": 0.0}],
    )
    assert receipt_id is not None

    header = sales_repo.get_receipt(receipt_id)
    assert header["total_price"] == pytest.approx(0.0)
    assert header["payment_status"] == "Paid", header

    q = QSqlQuery(fresh_db)
    q.exec("SELECT COUNT(*) FROM payments WHERE receipt_id = "
           + str(int(receipt_id)))
    assert q.next() and q.value(0) == 0

    summary = sales_repo.get_owner_financial_summary(cid)
    assert summary["outstanding"] == pytest.approx(0.0)
    assert summary["open_receipts"] == 0


def test_zero_total_receipt_recalcs_as_paid(fresh_db, repos, entity_factory):
    """Editing a receipt down to zero settles it instead of leaving it Unpaid."""
    from src.core.repositories.payment_repo import update_receipt_payment_status

    cid = entity_factory["make_client"]()
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": "Sample Item", "quantity": 1, "price": 30.0}],
    )

    line = next(i for i in sales_repo.get_receipt_line_items(receipt_id)
                if i["line_type"] == "Other")
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "update", "item_type": "Other", "item_id": line["item_id"],
         "link_id": line["link_id"], "quantity": 1, "unit_price": 0.0},
    ])
    update_receipt_payment_status(receipt_id)

    assert sales_repo.get_receipt(receipt_id)["payment_status"] == "Paid"


def test_quick_purchase_can_stay_unpaid(fresh_db, entity_factory):
    """paid=False keeps the old behavior for callers that need a credit sale."""
    cid = entity_factory["make_client"]()
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": "Unknown Item", "quantity": 1, "price": 40.0}],
        paid=False,
    )
    assert receipt_id is not None
    assert sales_repo.get_receipt(receipt_id)["payment_status"] == "Unpaid"
    summary = sales_repo.get_owner_financial_summary(cid)
    assert summary["outstanding"] == pytest.approx(40.0)


def test_expense_codes_counted_as_cost(fresh_db):
    """Expense rows carry unique codes; profit queries must still match them."""
    assert sales_repo.add_general_expense("2026-09-01", "Utilities", "Power", 250.0)

    _labels, revenue, cost, profit = sales_repo.get_trend_data("revenue", "Year")
    assert any(abs(float(c) - 250.0) < 1e-6 for c in cost), cost
    assert sum(revenue) - sum(cost) == pytest.approx(sum(profit), abs=1e-6)


def test_expense_category_and_notes_are_persisted(fresh_db):
    """The dialog's Category/Notes fields must survive the round trip.

    Regression: both parameters were accepted and silently discarded, so the
    ledger showed a generic "Other" for every expense.
    """
    assert sales_repo.add_general_expense(
        "2026-09-01", "Utilities", "Electricity Bill Jan", 150.0, "Paid in cash"
    )

    row = next(r for r in sales_repo.get_receipt_items()
               if r["item_name"] == "Electricity Bill Jan")
    assert row["item_type"] == "Utilities"
    assert row["notes"] == "Paid in cash"

    header = sales_repo.get_receipt(row["receipt_id"])
    assert header["notes"] == "Paid in cash"


def test_expense_lines_without_category_fall_back_to_other(fresh_db):
    """A blank/NULL category keeps the generic 'Other' bucket."""
    assert sales_repo.add_general_expense(
        "2026-09-01", "", "Uncategorised expense", 10.0
    )

    row = next(r for r in sales_repo.get_receipt_items()
               if r["item_name"] == "Uncategorised expense")
    assert row["item_type"] == "Other"


def test_notes_are_searchable_and_filterable(fresh_db):
    assert sales_repo.add_general_expense(
        "2026-09-01", "Rent", "Shop rent", 800.0, "Paid via bank transfer"
    )

    assert sales_repo.get_receipt_items("bank transfer", "All")
    assert sales_repo.get_receipt_items("bank transfer", "Notes")
    assert not sales_repo.get_receipt_items("bank transfer", "Item Name")
    # Category filtering keeps working now that the category is real.
    assert sales_repo.get_receipt_items("Rent", "Category")


def test_supply_purchase_expense_records_category_and_notes(fresh_db, repos, entity_factory):
    sid, item_name = entity_factory["make_supply"](quantity=5)

    receipt_id = sales_repo.log_supply_purchase_expense(
        sid, item_name, "Medicine", 5, 4.0, "2026-09-01", "Acme Supplies"
    )
    assert receipt_id is not None

    row = next(r for r in sales_repo.get_receipt_items()
               if r["item_name"] == f"{item_name} (Bought)")
    assert row["item_type"] == "Medicine"
    assert row["notes"] == "Restock from Acme Supplies"


def test_quick_purchase_discount_reduces_total_and_payment(fresh_db, repos, entity_factory):
    """The quick purchase discount lands in the header and the payment keeps the new total."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        discount=10.0,
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT total_price, discount, payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert abs(float(q.value(0)) - 10.0) < 1e-6      # 20 subtotal - 10 discount
    assert abs(float(q.value(1)) - 10.0) < 1e-6
    assert q.value(2) == "Paid"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 10.0) < 1e-6


def test_quick_purchase_discount_is_clamped_to_subtotal(fresh_db, repos, entity_factory):
    """Over-generous discounts cap at the subtotal instead of going negative."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        discount=1000.0,
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT total_price, discount FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert abs(float(q.value(0)) - 0.0) < 1e-6
    assert abs(float(q.value(1)) - 20.0) < 1e-6


def test_apply_receipt_discount_lowers_total_and_keeps_lines(fresh_db, repos, entity_factory):
    """Bulk purchase discount amends the shared expense receipt header only."""
    sid, item_name = entity_factory["make_supply"](quantity=5)

    receipt_id = sales_repo.log_supply_purchase_expense(
        sid, item_name, "Medicine", 5, 4.0, "2026-09-01", "Acme Supplies"
    )
    assert receipt_id is not None

    assert sales_repo.apply_receipt_discount(receipt_id, 5.0) is True

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT total_price, discount FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert abs(float(q.value(0)) - 15.0) < 1e-6   # 20 - 5
    assert abs(float(q.value(1)) - 5.0) < 1e-6

    # The line items keep their full cost; only the header changes.
    lines = sales_repo.get_receipt_line_items(receipt_id)
    assert sum(float(l["quantity"]) * float(l["unit_price"]) for l in lines) == pytest.approx(20.0)

    assert sales_repo.apply_receipt_discount(receipt_id, 0.0) is True
    q2 = QSqlQuery(fresh_db)
    q2.prepare("SELECT discount FROM receipts WHERE receipt_id = ?")
    q2.addBindValue(receipt_id)
    assert q2.exec() and q2.next()
    assert abs(float(q2.value(0)) - 5.0) < 1e-6


def test_quick_purchase_partial_payment(fresh_db, repos, entity_factory):
    """A partial amount paid lands the receipt as Partial, not fully settled."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid_amount=5.0,
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT total_price, payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert abs(float(q.value(0)) - 20.0) < 1e-6
    assert q.value(1) == "Partial"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 5.0) < 1e-6


def test_quick_purchase_records_the_chosen_payment_method(fresh_db, repos, entity_factory):
    """The method picked in the dialog lands on the instant payment row."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid_amount=5.0, payment_method="Card",
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.exec("SELECT payment_method FROM payments")
    assert q.next() and q.value(0) == "Card"
    assert not q.next()


def test_quick_purchase_zero_payment(fresh_db, repos, entity_factory):
    """paid_amount=0 records nothing, leaving the receipt Unpaid."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid_amount=0.0,
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert q.value(0) == "Unpaid"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COUNT(*) FROM payments")
    assert q2.next() and q2.value(0) == 0


def test_quick_purchase_paid_amount_is_clamped_to_total(fresh_db, repos, entity_factory):
    """A paid amount larger than the bill settles it fully instead of overpaying."""
    cid = repos["client"].add_client("Noor", "0500")
    _sid, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid_amount=99.0,
    )
    assert receipt_id is not None

    q = QSqlQuery(fresh_db)
    q.prepare("SELECT payment_status FROM receipts WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    assert q.value(0) == "Paid"

    q2 = QSqlQuery(fresh_db)
    q2.exec("SELECT COALESCE(SUM(amount), 0) FROM payments")
    assert q2.next() and abs(float(q2.value(0)) - 20.0) < 1e-6


def test_expense_category_survives_receipt_edit(fresh_db):
    """Editing an expense must not wipe its stored category."""
    sales_repo.add_general_expense("2026-09-01", "Salary", "Front desk pay", 400.0)

    row = next(r for r in sales_repo.get_receipt_items()
               if r["item_name"] == "Front desk pay")
    receipt_id = row["receipt_id"]

    lines = sales_repo.get_receipt_line_items(receipt_id)
    other = next(i for i in lines if i["line_type"] == "Other")
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "update", "item_type": "Other", "item_id": other["item_id"],
         "link_id": other["link_id"], "quantity": 2, "unit_price": 250.0},
    ])

    updated = next(r for r in sales_repo.get_receipt_items()
                   if r["receipt_id"] == receipt_id)
    assert updated["item_type"] == "Salary"
    assert updated["total_price"] == 500.0


def test_get_open_receipt_balances_for_owner(fresh_db, repos, entity_factory):
    from src.core import database
    from src.core.repositories import payment_repo
    from src.core.repositories.payment_repo import add_payment
    payment_repo.get_connection = database.get_connection

    cid = repos["client"].add_client("Sara", "0501")
    assert sales_repo.get_open_receipt_balances_for_owner(cid) == []

    _, item_name = entity_factory["make_supply"](quantity=20)
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
        paid=False,
    ))

    balances = sales_repo.get_open_receipt_balances_for_owner(cid)
    assert len(balances) == 1
    assert balances[0][0] == receipt_id
    assert abs(balances[0][1] - 20.0) < 1e-6

    add_payment(receipt_id, 8.0)
    balances = sales_repo.get_open_receipt_balances_for_owner(cid)
    assert abs(balances[0][1] - 12.0) < 1e-6

    add_payment(receipt_id, 12.0)
    assert sales_repo.get_open_receipt_balances_for_owner(cid) == []


def _movements(db, supply_id):
    """The stock ledger rows for one supply, oldest first."""
    q = QSqlQuery(db)
    q.prepare("SELECT movement_type, quantity, notes, receipt_id FROM stock_movements "
              "WHERE supply_id = ? ORDER BY movement_id")
    q.addBindValue(supply_id)
    q.exec()
    return [{"type": q.value(0), "qty": int(q.value(1)), "notes": q.value(2),
             "receipt_id": q.value(3)}
            for _ in iter(lambda: q.next(), False)]


def test_quick_purchase_writes_a_stock_movement(fresh_db, repos, entity_factory):
    cid = repos["client"].add_client("Walk-In", "0509")
    sid, item_name = entity_factory["make_supply"](quantity=20)
    assert [m["type"] for m in _movements(fresh_db, sid)] == ["purchase"]

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 3, "price": 10.0}],
    )

    moves = _movements(fresh_db, sid)
    assert [m["type"] for m in moves] == ["purchase", "sale"]
    assert moves[-1]["qty"] == -3
    assert int(moves[-1]["receipt_id"]) == int(receipt_id)
    assert f"Receipt #{receipt_id}" in moves[-1]["notes"]


def test_editing_a_receipt_line_writes_a_stock_movement(fresh_db, repos, entity_factory):
    cid = repos["client"].add_client("Ali", "050123")
    sid, item_name = entity_factory["make_supply"](quantity=10)
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-01",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )
    assert _movements(fresh_db, sid)[-1]["qty"] == -2

    def _line():
        return next(i for i in sales_repo.get_receipt_line_items(receipt_id)
                    if i["line_type"] == "Supply")

    # Selling more units must show in the ledger, not just in current_stock.
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "update", "item_type": "Supply", "item_id": _line()["item_id"],
         "link_id": _line()["link_id"], "quantity": 5, "unit_price": 10.0},
    ])
    moves = _movements(fresh_db, sid)
    assert moves[-1]["type"] == "sale"
    assert moves[-1]["qty"] == -3, "5 - 2 = 3 more units left the shelf"

    # Handing units back is the mirror image.
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "update", "item_type": "Supply", "item_id": _line()["item_id"],
         "link_id": _line()["link_id"], "quantity": 1, "unit_price": 10.0},
    ])
    moves = _movements(fresh_db, sid)
    assert moves[-1]["type"] == "sale_return"
    assert moves[-1]["qty"] == 4


def _stock_of(repos, supply_id):
    for s in repos["supply"].search_supplies():
        if int(s["supply_id"]) == int(supply_id):
            return float(s["current_stock"]), float(s["batch_quantity"] or 0)
    raise AssertionError("supply not found")


def _payment_count(fresh_db, receipt_id):
    q = QSqlQuery(fresh_db)
    q.prepare("SELECT COUNT(*) FROM payments WHERE receipt_id = ?")
    q.addBindValue(receipt_id)
    assert q.exec() and q.next()
    n = int(q.value(0))
    q.finish()
    return n


def test_delete_receipt_restores_stock_and_batches(fresh_db, repos, entity_factory):
    """Deleting a sale must give the stock back - sale to the batches too."""
    supply_id, item_name = entity_factory["make_supply"](quantity=10)
    before = _stock_of(repos, supply_id)
    assert before == (10.0, 10.0)

    cid = entity_factory["make_client"]()
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": item_name, "quantity": 3, "price": 10.0}],
    ))
    during = _stock_of(repos, supply_id)
    assert during == (7.0, 7.0)

    assert sales_repo.delete_receipt(receipt_id) is True
    assert sales_repo.get_receipt(receipt_id) is None
    assert _stock_of(repos, supply_id) == (10.0, 10.0)

    # The return is logged as a stock movement, not a silent edit.
    q = QSqlQuery(fresh_db)
    q.prepare("SELECT movement_type, quantity FROM stock_movements "
              "WHERE supply_id = ?")
    q.addBindValue(supply_id)
    rows = []
    if q.exec():
        while q.next():
            rows.append((str(q.value(0)), int(q.value(1))))
    q.finish()
    assert ("sale_return", 3) in rows


def test_delete_receipt_with_payments_removes_the_payments(fresh_db, repos, entity_factory):
    """payments.receipt_id is a cascade FK - no orphans may survive a delete."""
    from src.core.repositories.payment_repo import add_payment, get_total_paid

    cid = entity_factory["make_client"]()
    receipt_id = int(sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-07",
        [{"item_name": "Paid Line", "quantity": 1, "price": 20.0}],
        paid=False,
    ))
    assert add_payment(receipt_id, 12.0, "Cash") is not None
    assert _payment_count(fresh_db, receipt_id) == 1
    assert abs(get_total_paid(receipt_id) - 12.0) < 1e-6

    assert sales_repo.delete_receipt(receipt_id) is True

    assert sales_repo.get_receipt(receipt_id) is None
    assert _payment_count(fresh_db, receipt_id) == 0


def test_delete_missing_receipt_still_reports_true(fresh_db, repos):
    """Historical contract: deleting an unknown id is a no-op, not an error."""
    assert sales_repo.delete_receipt(-1) is True


def test_get_receipt_for_visit_resolves_the_billed_receipt(fresh_db, repos, entity_factory):
    cid = entity_factory["make_client"]()
    pid = entity_factory["make_pet"](cid)
    visit_id = repos["visit"].add_visit(
        "2026-09-08 09:00", "Checkup", 1, "", pet_id=pid, client_id=cid,
    )
    receipt_id = sales_repo.get_receipt_for_visit(visit_id)
    assert receipt_id is not None
    assert sales_repo.get_receipt(receipt_id)["visit_id"] == visit_id
    assert sales_repo.get_receipt_for_visit(None) is None
    assert sales_repo.get_receipt_for_visit(999999) is None


def test_deleting_one_of_two_identical_supply_lines_restores_only_that_line(
        fresh_db, repos, entity_factory):
    """A supply can sit on two lines of one receipt.

    Deleting one line must hand back exactly that line's quantity and leave the
    other line intact. Matching by supply_id (the old behaviour) deleted *every*
    line for that supply and restored only one quantity, so stock drifted.
    """
    cid = entity_factory["make_client"]()
    supply_id, item_name = entity_factory["make_supply"](quantity=10)

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        cid, "2026-09-10",
        [{"item_name": item_name, "quantity": 2, "price": 10.0}],
    )
    assert _stock_of(repos, supply_id)[0] == 8.0

    # Add the same supply again as a separate line (qty 3).
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "add", "item_type": "Supply", "item_id": supply_id,
         "name": item_name, "quantity": 3, "unit_price": 10.0},
    ])
    assert _stock_of(repos, supply_id)[0] == 5.0

    supply_lines = [i for i in sales_repo.get_receipt_line_items(receipt_id)
                    if i["line_type"] == "Supply"]
    assert len(supply_lines) == 2
    assert sorted(int(l["quantity"]) for l in supply_lines) == [2, 3]

    # Delete only the qty-2 line, targeted by its own line PK.
    two = next(l for l in supply_lines if int(l["quantity"]) == 2)
    assert sales_repo.update_receipt(receipt_id, 0.0, [
        {"op": "delete", "item_type": "Supply", "item_id": supply_id,
         "link_id": two["link_id"]},
    ])

    remaining = [i for i in sales_repo.get_receipt_line_items(receipt_id)
                 if i["line_type"] == "Supply"]
    assert len(remaining) == 1, "the untouched line must survive"
    assert int(remaining[0]["quantity"]) == 3
    assert _stock_of(repos, supply_id)[0] == 7.0, "only the deleted line's units return"
