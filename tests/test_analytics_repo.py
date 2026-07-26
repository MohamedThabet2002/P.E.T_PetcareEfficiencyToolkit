"""Tests for src/core/repositories/analytics_repo.py"""

import datetime

import pytest

from src.core.repositories.analytics_cache import invalidate_analytics_cache


def _today() -> str:
    """Return today's date as a string (YYYY-MM-DD) for analytics date filters."""
    return datetime.date.today().strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _fresh_analytics_cache():
    """Ensure the global analytics cache is empty before each test."""
    invalidate_analytics_cache()
    yield
    invalidate_analytics_cache()


class TestEmptyDatabase:
    def test_total_visits_zero(self, fresh_db, repos):
        assert repos["analytics"].get_total_visits() == 0
        assert repos["analytics"].get_total_visits("Week") == 0

    def test_total_revenue_zero(self, fresh_db, repos):
        assert repos["analytics"].get_total_revenue() == 0.0

    def test_average_revenue_zero(self, fresh_db, repos):
        assert repos["analytics"].get_average_revenue_per_visit() == 0.0

    def test_low_stock_empty(self, fresh_db, repos):
        assert repos["analytics"].get_low_stock_supplies() == 0

    def test_pet_distribution_empty(self, fresh_db, repos):
        assert repos["analytics"].get_pet_distribution() == {}

    def test_trend_data_empty(self, fresh_db, repos):
        labels, values = repos["analytics"].get_visits_trend_data("Week")
        assert labels == []
        assert values == []

    def test_expiring_soon_empty(self, fresh_db, repos):
        assert repos["analytics"].get_expiring_soon_items() == []

    def test_top_selling_empty(self, fresh_db, repos):
        assert repos["analytics"].get_top_selling_items() == []

    def test_common_diagnoses_empty(self, fresh_db, repos):
        assert repos["analytics"].get_common_diagnoses() == []

    def test_supplies_by_category_empty(self, fresh_db, repos):
        assert repos["analytics"].get_total_supplies_by_category() == []

    def test_notifications_empty(self, fresh_db, repos):
        assert repos["analytics"].get_notifications() == []


class TestKpis:
    def test_total_visits_counts_all(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=50)

        # Create two visits (each creates one Sale receipt).
        # Use today's date so the "Year" period filter (start of year) includes them.
        for i in range(2):
            result = repos["visit"].add_visit(
                visit_date=_today(),
                diagnosis="Checkup",
                consult=True,
                notes="",
                pet_id=pid,
                items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
            )
            assert result is not None and isinstance(result, int)

        assert repos["analytics"].get_total_visits() == 2
        assert repos["analytics"].get_total_visits("Year") == 2

    def test_total_revenue_sums_sale_receipts(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=50)

        result = repos["visit"].add_visit(
            visit_date="2025-05-10",
            diagnosis="Checkup",
            consult=True,
            notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 3, "price": 10.0}],
        )
        assert result is not None

        # 3 items * 10 = 30 in receipt_supplies + consult fee (default 50) => 80 total
        assert repos["analytics"].get_total_revenue() == pytest.approx(80.0)

    def test_average_revenue_per_visit(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=50)

        # Two visits with consult => each 50 + (1 item * 10) = 60 each.
        for _ in range(2):
            repos["visit"].add_visit(
                visit_date="2025-05-10",
                diagnosis="Checkup",
                consult=True,
                notes="",
                pet_id=pid,
                items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
            )

        assert repos["analytics"].get_average_revenue_per_visit() == pytest.approx(60.0)

    def test_low_stock_supplies(self, fresh_db, repos, entity_factory):
        # No stock -> low stock.
        sid0, _ = entity_factory["make_supply"](quantity=0)
        # At reorder level -> low stock (reorder_level=5, stock=5).
        sid1, _ = entity_factory["make_supply"](quantity=5, reorder_level=5)
        # Above reorder level -> not low stock (reorder=3, stock=10).
        entity_factory["make_supply"](quantity=10, reorder_level=3)

        assert repos["analytics"].get_low_stock_supplies() == 2


class TestDistributionAndTrends:
    def test_pet_distribution_by_species(self, fresh_db, repos, entity_factory):
        cat_owner = entity_factory["make_client"](name="Cat Owner")
        dog_owner = entity_factory["make_client"](name="Dog Owner")
        entity_factory["make_pet"](cat_owner, name="Whiskers", species="Cat", breed="Persian")
        entity_factory["make_pet"](cat_owner, name="Milo", species="Cat", breed="Persian")
        entity_factory["make_pet"](dog_owner, name="Rex", species="Dog", breed="Labrador Retriever")

        dist = repos["analytics"].get_pet_distribution()
        assert dist.get("Cat") == 2
        assert dist.get("Dog") == 1

    def test_visits_trend_structure(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)

        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=pid,
        )

        labels, values = repos["analytics"].get_visits_trend_data("Week")
        # Returns (labels, values) tuples — values should contain at least one non-zero entry.
        assert len(labels) == len(values)
        assert sum(values) >= 1

    def test_supplies_by_category_aggregation(self, fresh_db, repos, entity_factory):
        entity_factory["make_supply"](quantity=10, category="Medicine", name="MedA")
        entity_factory["make_supply"](quantity=5, category="Food", name="FoodA")

        result = repos["analytics"].get_total_supplies_by_category()
        result_dict = dict(result)
        assert result_dict.get("Medicine") == 10
        assert result_dict.get("Food") == 5


class TestInventoryAnalytics:
    def test_expiring_soon_items(self, fresh_db, repos, entity_factory):
        # Supply expiring within 30 days (use a far-future expiry for non-expiring).
        entity_factory["make_supply"](quantity=5, expiry="2099-12-31", name="LongShelf")
        assert repos["analytics"].get_expiring_soon_items(days=30) == []

    def test_top_selling_items(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100, name="BestSeller")

        repos["visit"].add_visit(
            visit_date="2025-05-10", diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 5, "price": 10.0}],
        )

        top = repos["analytics"].get_top_selling_items(limit=3)
        assert len(top) >= 1
        assert top[0]["name"] == item_name
        assert int(top[0]["sold"]) == 5

    def test_common_diagnoses(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)

        for _ in range(3):
            repos["visit"].add_visit(
                visit_date=_today(), diagnosis="Cough", consult=False, notes="",
                pet_id=pid,
            )

        diagnoses = repos["analytics"].get_common_diagnoses(limit=3)
        assert any(d["diagnosis"] == "Cough" and d["count"] == 3 for d in diagnoses)

    def test_supplies_numbers_for_category(self, fresh_db, repos, entity_factory):
        entity_factory["make_supply"](quantity=7, category="Medicine", name="MedA")
        entity_factory["make_supply"](quantity=3, category="Medicine", name="MedB")

        rows = repos["analytics"].get_supplies_numbers_for_each_category("Medicine")
        assert ("MedA", 7) in rows
        assert ("MedB", 3) in rows


class TestNotifications:
    def test_low_stock_notification(self, fresh_db, repos, entity_factory):
        entity_factory["make_supply"](quantity=0, name="ZeroStock")
        notifications = repos["analytics"].get_notifications()
        low_stock = [n for n in notifications if n["type"] == "low_stock"]
        assert low_stock
        assert low_stock[0]["severity"] == "critical"

    def test_expiring_notification_uses_dynamic_dates(self, fresh_db, repos, entity_factory):
        # Creating a supply with a 2099 expiry won't trigger expiring-soon notification.
        entity_factory["make_supply"](quantity=5, expiry="2099-12-31", name="DoesNotExpire")
        notifications = repos["analytics"].get_notifications()
        assert not any(n["type"] == "expiring" for n in notifications)

    def test_severity_sorting(self, fresh_db, repos, entity_factory):
        # A zero-stock item (critical) should sort before any info-level notification.
        entity_factory["make_supply"](quantity=0, name="CriticalItem")
        notifications = repos["analytics"].get_notifications()
        assert notifications[0]["type"] == "low_stock"
        assert notifications[0]["severity"] == "critical"

    def test_followups_are_not_reminder_notifications(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        appt_id = repos["appointment"].add_appointment(
            "2099-09-02 10:00", "Consultation", "Pending", "", cid, pid
        )
        assert appt_id is not None

        db = fresh_db
        q = pytest.importorskip("PyQt5.QtSql").QSqlQuery(db)
        q.prepare("INSERT INTO visits (pet_id, appointment_id, visit_date, diagnosis, notes) VALUES (?, ?, ?, ?, ?)")
        q.addBindValue(pid)
        q.addBindValue(appt_id)
        q.addBindValue("2099-09-01 09:00")
        q.addBindValue("Checkup")
        q.addBindValue("Initial visit")
        assert q.exec()
        visit_id = q.lastInsertId()

        repos["followup"].add_followup(visit_id, "2099-09-09", None, "Recheck in 7 days")
        notifications = repos["analytics"].get_notifications()
        assert not any(n["type"] == "followup" for n in notifications)

    def test_unpaid_sale_receipt_notification(self, fresh_db, repos, entity_factory):
        client_id = entity_factory["make_client"](name="Unpaid Client")
        db = fresh_db
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(db)
        query.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code)
            VALUES (?, ?, ?, 'Sale')
        """)
        query.addBindValue(client_id)
        query.addBindValue(_today())
        query.addBindValue(125.0)
        assert query.exec()

        notifications = repos["analytics"].get_notifications()
        unpaid = [n for n in notifications if n["type"] == "unpaid_receipt"]
        assert len(unpaid) == 1
        assert unpaid[0]["severity"] == "warning"
        assert "Unpaid Client" in unpaid[0]["details"]

    def test_paid_sale_receipt_is_not_unpaid_notification(self, fresh_db, repos, entity_factory):
        from src.core.repositories.payment_repo import add_payment

        client_id = entity_factory["make_client"]()
        db = fresh_db
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(db)
        query.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code, payment_status)
            VALUES (?, ?, ?, 'Sale', 'Paid')
        """)
        query.addBindValue(client_id)
        query.addBindValue(_today())
        query.addBindValue(125.0)
        assert query.exec()
        receipt_id = int(query.lastInsertId())
        query.finish()
        # "Unpaid" means money outstanding, read from the payments table —
        # a bare status string carries no balance, so settle it for real.
        assert add_payment(receipt_id, 125.0, "Cash") is not None

        notifications = repos["analytics"].get_notifications()
        assert not any(n["type"] == "unpaid_receipt" for n in notifications)

    def test_partially_paid_receipt_reports_the_remaining_balance(
            self, fresh_db, repos, entity_factory):
        from src.core.repositories.payment_repo import add_payment

        client_id = entity_factory["make_client"]()
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        query.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code, payment_status)
            VALUES (?, ?, ?, 'Sale', 'Partial')
        """)
        query.addBindValue(client_id)
        query.addBindValue(_today())
        query.addBindValue(100.0)
        assert query.exec()
        receipt_id = int(query.lastInsertId())
        query.finish()
        assert add_payment(receipt_id, 40.0, "Cash") is not None

        unpaid = [n for n in repos["analytics"].get_notifications()
                  if n["type"] == "unpaid_receipt"]
        assert len(unpaid) == 1
        assert abs(unpaid[0]["amount"] - 60.0) < 1e-6
        assert "60" in unpaid[0]["details"]

    def test_unpaid_receipts_outrank_other_alerts(
            self, fresh_db, repos, entity_factory):
        """The dashboard keeps only the top 10 rows — money owed must win."""
        entity_factory["make_supply"](quantity=0, name="ZeroStock")
        client_id = entity_factory["make_client"]()
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        query.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code)
            VALUES (?, ?, ?, 'Sale')
        """)
        query.addBindValue(client_id)
        query.addBindValue(_today())
        query.addBindValue(50.0)
        assert query.exec()
        query.finish()

        types = [n["type"] for n in repos["analytics"].get_notifications()]
        assert "unpaid_receipt" in types
        assert "low_stock" in types
        assert types.index("unpaid_receipt") < types.index("low_stock")

    # --- expense balances (owed / refund, from the stock-ledger corrections) ---

    @staticmethod
    def _expense_receipt(db, total, code="EXPENSE-001"):
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(db)
        query.prepare("""
            INSERT INTO receipts (receipt_date, total_price, receipt_code, receipt_kind)
            VALUES (?, ?, ?, 'expense')
        """)
        query.addBindValue(_today())
        query.addBindValue(total)
        query.addBindValue(code)
        assert query.exec()
        return int(query.lastInsertId())

    def test_unpaid_expense_receipt_reports_what_is_still_owed(self, fresh_db, repos):
        receipt_id = self._expense_receipt(fresh_db, 200.0)

        balances = [n for n in repos["analytics"].get_notifications()
                    if n["type"] == "expense_balance"]

        assert len(balances) == 1
        assert balances[0]["title"] == "Expense Unpaid"
        assert balances[0]["severity"] == "warning"
        assert "200" in balances[0]["info"]
        assert balances[0]["receipt_id"] == receipt_id
        assert balances[0]["balance"] < 0

    def test_overpaid_expense_receipt_reports_a_refund(self, fresh_db, repos):
        from src.core.repositories.payment_repo import add_payment

        receipt_id = self._expense_receipt(fresh_db, 100.0)
        assert add_payment(receipt_id, 150.0, "Cash") is not None

        balances = [n for n in repos["analytics"].get_notifications()
                    if n["type"] == "expense_balance"]

        assert len(balances) == 1
        assert balances[0]["title"] == "Refund Due"
        assert balances[0]["severity"] == "info"
        assert "50" in balances[0]["info"]
        assert abs(balances[0]["balance"] - 50.0) < 1e-6

    def test_settled_expense_receipt_is_not_reported(self, fresh_db, repos):
        from src.core.repositories.payment_repo import add_payment

        receipt_id = self._expense_receipt(fresh_db, 100.0, "EXPENSE-002")
        assert add_payment(receipt_id, 100.0, "Cash") is not None

        notifications = repos["analytics"].get_notifications()
        assert not any(n["type"] == "expense_balance" for n in notifications)

    def test_a_sale_receipt_balance_is_not_reported_as_a_supplier_balance(
            self, fresh_db, repos, entity_factory):
        """Sales have their own Unpaid Receipt reminder; kind is what splits them."""
        client_id = entity_factory["make_client"]()
        query = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        query.prepare("""
            INSERT INTO receipts (owner_id, receipt_date, total_price, receipt_code)
            VALUES (?, ?, ?, 'Sale')
        """)
        query.addBindValue(client_id)
        query.addBindValue(_today())
        query.addBindValue(75.0)
        assert query.exec()

        notifications = repos["analytics"].get_notifications()
        assert not any(n["type"] == "expense_balance" for n in notifications)
        assert any(n["type"] == "unpaid_receipt" for n in notifications)


class TestPeriodPerformanceWidgets:
    """Period-aware analytics backing the Reports page performance widgets."""

    def test_total_supplies_used_empty(self, fresh_db, repos):
        assert repos["analytics"].get_total_supplies_used() == 0

    def test_total_supplies_used_counts_sales_only(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100, category="Medicine")

        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 3, "price": 5.0}],
        )
        assert repos["analytics"].get_total_supplies_used() == 3
        assert repos["analytics"].get_total_supplies_used("Year") == 3
        assert repos["analytics"].get_total_supplies_used("Week") == 3

    def test_visits_by_doctor_empty(self, fresh_db, repos):
        assert repos["analytics"].get_visits_by_doctor() == []

    def test_visits_by_doctor_groups_and_unassigned(self, fresh_db, repos, entity_factory):
        from src.utils.i18n import tr

        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)

        q = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        assert q.exec("INSERT INTO doctors (first_name, last_name) VALUES ('Grace', 'Hopper')")
        doctor_id = int(q.lastInsertId())

        for _ in range(2):
            q2 = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
            q2.prepare("INSERT INTO visits (pet_id, doctor_id, visit_date) VALUES (?, ?, ?)")
            q2.addBindValue(pid)
            q2.addBindValue(doctor_id)
            q2.addBindValue(_today())
            assert q2.exec()

        q3 = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        q3.prepare("INSERT INTO visits (pet_id, visit_date) VALUES (?, ?)")
        q3.addBindValue(pid)
        q3.addBindValue(_today())
        assert q3.exec()

        rows = {name: count for name, count in repos["analytics"].get_visits_by_doctor()}
        assert rows.get("Grace Hopper") == 2
        assert rows.get(tr("Unassigned")) == 1

    def test_revenue_by_category_buckets(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100, category="Medicine")

        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 2, "price": 10.0}],
        )

        q = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        assert q.exec(
            "SELECT receipt_id FROM receipts WHERE receipt_kind = 'visit' "
            "ORDER BY receipt_id DESC LIMIT 1"
        )
        assert q.next()
        receipt_id = int(q.value(0))
        q.prepare("INSERT INTO receipt_other (receipt_id, description, quantity, unit_price) VALUES (?, ?, 1, ?)")
        q.addBindValue(receipt_id)
        q.addBindValue("Misc fee")
        q.addBindValue(25.0)
        assert q.exec()

        rows = {name: amount for name, amount in repos["analytics"].get_revenue_by_category()}
        assert rows.get("Medicine") == pytest.approx(20.0)
        assert rows.get("Other") == pytest.approx(25.0)
        assert sum(rows.values()) == pytest.approx(45.0)

    def test_supply_usage_ranks_by_quantity(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        s1, item_a = entity_factory["make_supply"](quantity=100, name="Item A", category="Meds")
        s2, item_b = entity_factory["make_supply"](quantity=100, name="Item B", category="Meds")

        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_a, "quantity": 5, "price": 5.0},
                   {"item_name": item_b, "quantity": 2, "price": 5.0}],
        )
        rows = repos["analytics"].get_supply_usage(limit=8)
        usage = {name: qty for name, _, qty in rows}
        assert usage[item_a] == 5
        assert usage[item_b] == 2
        assert rows[0][0] == item_a  # highest quantity first

    def test_total_costs_sums_expense_receipts_only(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100, category="Medicine")

        # A billable visit contributes to REVENUE, never to COSTS.
        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
        )
        assert repos["sales"].add_general_expense(_today(), "Medicine", "Syringe pack", 40.0)
        assert repos["sales"].add_general_expense(_today(), "Other", "Boiler room fan", 25.0)
        assert repos["sales"].add_general_expense("2000-01-01", "Other", "Old invoice", 99.0)

        assert repos["analytics"].get_total_costs_range(_today(), _today()) == pytest.approx(65.0)
        assert repos["analytics"].get_total_costs_range("", "") == pytest.approx(164.0)
        # Net profit combines both: today's revenue (10) minus today's costs (65).
        revenue = repos["analytics"].get_total_revenue_range(_today(), _today())
        assert revenue == pytest.approx(10.0)
        costs = repos["analytics"].get_total_costs_range(_today(), _today())
        assert revenue - costs == pytest.approx(-55.0)

    def test_top_clients_ranked_by_revenue(self, fresh_db, repos, entity_factory):
        low_cid = entity_factory["make_client"](name="Low Spender", phone="0500000001")
        low_pid = entity_factory["make_pet"](low_cid, name="Pip")
        high_cid = entity_factory["make_client"](name="High Spender", phone="0500000002")
        high_pid = entity_factory["make_pet"](high_cid, name="Max")
        sid, item_name = entity_factory["make_supply"](quantity=100, category="Medicine")

        # High spender: two visits -> 30 revenue.
        for price in (12.0, 18.0):
            repos["visit"].add_visit(
                visit_date=_today(), diagnosis="X", consult=False, notes="",
                pet_id=high_pid,
                items=[{"item_name": item_name, "quantity": 1, "price": price}],
            )
        # Low spender: one visit -> 5 revenue.
        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="X", consult=False, notes="",
            pet_id=low_pid,
            items=[{"item_name": item_name, "quantity": 1, "price": 5.0}],
        )

        rows = repos["analytics"].get_top_clients_range(_today(), _today(), limit=5)
        assert len(rows) == 2
        top, second = rows
        assert top[1] == "High Spender"
        assert top[2] == 2                     # visits
        assert top[3] == pytest.approx(30.0)
        assert second[1] == "Low Spender"
        assert second[2] == 1
        assert second[3] == pytest.approx(5.0)
        # A day with no visits yields an empty ranking, not a crash.
        assert repos["analytics"].get_top_clients_range("2000-01-01", "2000-01-02") == []


class TestMonthOverMonth:
    def _previous_month(self):
        today = datetime.date.today()
        if today.month == 1:
            return today.replace(year=today.year - 1, month=12, day=1)
        return today.replace(month=today.month - 1, day=1)

    def test_mom_empty_database_zeros(self, fresh_db, repos):
        mom = repos["analytics"].get_month_over_month()
        assert mom["visits_this_month"] == 0
        assert mom["visits_last_month"] == 0
        assert mom["revenue_this_month"] == 0.0
        assert mom["revenue_last_month"] == 0.0

    def test_mom_totals_current_vs_last_month(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100)

        # One visit this month (today) and two last month.
        repos["visit"].add_visit(
            visit_date=_today(), diagnosis="Checkup", consult=True, notes="",
            pet_id=pid, items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
            receipt_code="MOM-CUR",
        )
        prev = self._previous_month().strftime("%Y-%m-%d")
        for i in range(2):
            repos["visit"].add_visit(
                visit_date=prev, diagnosis="Checkup", consult=True, notes="",
                pet_id=pid, items=[{"item_name": item_name, "quantity": 1, "price": 10.0}],
                receipt_code=f"MOM-PREV-{i}",
            )

        mom = repos["analytics"].get_month_over_month()
        assert mom["visits_this_month"] == 1
        assert mom["visits_last_month"] == 2
        # This month: 50 consult + 10 = 60; last month: 2 * 60 = 120.
        assert mom["revenue_this_month"] == pytest.approx(60.0)
        assert mom["revenue_last_month"] == pytest.approx(120.0)


class TestTrendDispatcher:
    def test_visits_trend_dispatch(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        repos["visit"].add_visit(
            visit_date="2025-05-10", diagnosis="X", consult=False, notes="",
            pet_id=pid,
        )
        labels, values = repos["analytics"].get_trend_data("visits", "Week")
        assert len(labels) == len(values)

    def test_sales_trend_dispatch(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        sid, item_name = entity_factory["make_supply"](quantity=100)

        repos["visit"].add_visit(
            visit_date="2025-05-10", diagnosis="X", consult=False, notes="",
            pet_id=pid,
            items=[{"item_name": item_name, "quantity": 2, "price": 10.0}],
        )

        # sales_repo.get_trend_data returns (labels, values) for revenue.
        result = repos["analytics"].get_trend_data("revenue", "Month")
        assert isinstance(result, tuple)

    def test_appointments_include_followup_details(self, fresh_db, repos, entity_factory):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        appt_id = repos["appointment"].add_appointment(
            "2099-09-02 10:00", "Consultation", "Pending", "", cid, pid
        )
        assert appt_id is not None

        q = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(fresh_db)
        q.prepare("INSERT INTO visits (pet_id, appointment_id, visit_date, diagnosis, notes) VALUES (?, ?, ?, ?, ?)")
        q.addBindValue(pid)
        q.addBindValue(appt_id)
        q.addBindValue("2099-09-01 09:00")
        q.addBindValue("Checkup")
        q.addBindValue("Initial visit")
        assert q.exec()
        visit_id = q.lastInsertId()

        repos["followup"].add_followup(visit_id, "2099-09-09", None, "Recheck in 7 days")
        results = repos["appointment"].get_appointments()
        # The follow-up is surfaced as a separate standalone row in the
        # appointments table (service column = "Follow-up", light blue styling).
        row = next(r for r in results if r["row_type"] == "followup")
        assert row["appointment_date"] == "2099-09-09"
        assert row["service"] == "Follow-up"
        assert row["status"] == "Pending"
        assert row["notes"] == "Recheck in 7 days"
        assert row["pet_id"] == pid
