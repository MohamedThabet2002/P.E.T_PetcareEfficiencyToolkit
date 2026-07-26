"""
Tests for the receipt adjustment repository and the consultation reconcile
helpers that power the visit "Adjust" flow.

A receipt adjustment is a cumulative revision-trail row (old_total -> new_total
plus optional per-line deltas) recorded whenever a visit's receipt total
changes after the fact.
"""

from src.core.repositories import user_repo, sales_repo, client_repo, pet_repo, visit_repo
from src.core.repositories.receipt_adjustment_repo import (
    add_adjustment,
    get_adjustments_for_receipt,
    get_adj_writer_name,
    delete_adjustments_for_receipt,
)


def _make_receipt(entity_factory):
    client_id = entity_factory["make_client"](name="Adjust Owner")
    sid, item_name = entity_factory["make_supply"](
        quantity=10, name="Adjustment Syrup", sell_price=8.0, buy_price=3.0
    )
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        client_id, "2026-09-05 10:00:00",
        [{"item_name": item_name, "quantity": 2, "price": 8.0}],
    )
    assert receipt_id
    return receipt_id


def test_add_and_get_adjustments(fresh_db, repos, entity_factory):
    client_id = entity_factory["make_client"](name="Adjust Owner")
    pet_id = entity_factory["make_pet"](client_id, name="Adjust Pet")
    visit_id = visit_repo.add_visit(
        "2026-09-05", "Flu", 0, "notes", pet_id=pet_id, client_id=client_id,
    )
    assert visit_id and not isinstance(visit_id, str)
    entity_factory["make_supply"](quantity=10, name="Adjustment Syrup", sell_price=8.0, buy_price=3.0)
    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        client_id, "2026-09-05 10:00:00",
        [{"item_name": "Adjustment Syrup", "quantity": 1, "price": 8.0}],
    )
    assert receipt_id

    details = [
        {"item": "Adjustment Syrup", "old_value": "2 x $ 8.00", "new_value": "4 x $ 8.00"},
        {"item": "Discount", "old_value": "$ 0.00", "new_value": "$ 4.00"},
    ]
    aid = add_adjustment(
        receipt_id, visit_id=visit_id, adjusted_by=None,
        description="Receipt adjusted: total $ 16.00 -> $ 28.00",
        old_total=16.0, new_total=28.0, details=details,
    )
    assert aid is not None

    rows = get_adjustments_for_receipt(receipt_id)
    assert len(rows) == 1
    adj = rows[0]
    assert adj["receipt_id"] == receipt_id
    assert adj["visit_id"] == visit_id
    assert adj["description"].startswith("Receipt adjusted")
    assert abs(adj["old_total"] - 16.0) < 1e-6
    assert abs(adj["new_total"] - 28.0) < 1e-6
    assert abs(adj["delta"] - 12.0) < 1e-6
    assert len(adj["details"]) == 2
    assert adj["details"][0]["item"] == "Adjustment Syrup"


def test_delta_and_order(fresh_db, repos, entity_factory):
    receipt_id = _make_receipt(entity_factory)
    add_adjustment(receipt_id, old_total=16.0, new_total=14.0)
    add_adjustment(receipt_id, old_total=14.0, new_total=20.0)
    rows = get_adjustments_for_receipt(receipt_id)
    assert len(rows) == 2
    assert abs(rows[0]["delta"] - (-2.0)) < 1e-6
    assert abs(rows[1]["delta"] - 6.0) < 1e-6
    # Oldest first (cumulative stacking order).
    assert rows[0]["adjustment_id"] < rows[1]["adjustment_id"]


def test_delete_adjustments_for_receipt(fresh_db, repos, entity_factory):
    receipt_id = _make_receipt(entity_factory)
    add_adjustment(receipt_id, old_total=16.0, new_total=18.0)
    assert len(get_adjustments_for_receipt(receipt_id)) == 1
    assert delete_adjustments_for_receipt(receipt_id)
    assert get_adjustments_for_receipt(receipt_id) == []


def test_writer_name_resolved(fresh_db, repos):
    uid = user_repo.add_user("dr_adjust", "pw12345", "admin")
    assert get_adj_writer_name(uid) == "dr_adjust"
    assert get_adj_writer_name(None) == ""
    assert get_adj_writer_name(999999) == ""


def test_consultation_reconcile_changes_total(fresh_db, repos, entity_factory):
    """Reconciling the consultation line on/off must move the receipt total."""
    receipt_id = _make_receipt(entity_factory)
    before = sales_repo.get_receipt(receipt_id)["total_price"]
    assert not sales_repo.has_consultation_service(receipt_id)

    changed = sales_repo.reconcile_consultation(receipt_id, True, 50.0)
    assert changed is True
    assert sales_repo.has_consultation_service(receipt_id)
    after_on = sales_repo.recompute_receipt_total(receipt_id)
    assert after_on is not None
    assert abs(after_on - (float(before) + 50.0)) < 1e-6

    # Toggling off again removes the line and shrinks the total back.
    changed = sales_repo.reconcile_consultation(receipt_id, False, 50.0)
    assert changed is True
    assert not sales_repo.has_consultation_service(receipt_id)
    after_off = sales_repo.recompute_receipt_total(receipt_id)
    assert after_off is not None
    assert abs(after_off - float(before)) < 1e-6


def test_update_receipt_recomputes_totals(fresh_db, repos, entity_factory):
    """update_receipt feeds on the immutable line items; totals follow."""
    receipt_id = _make_receipt(entity_factory)
    line = sales_repo.get_receipt_line_items(receipt_id)[0]
    assert sales_repo.update_receipt(
        receipt_id, 0.0,
        [{"op": "update", "item_type": line["line_type"],
          "item_id": line["item_id"], "link_id": line["link_id"],
          "quantity": 3, "unit_price": line["unit_price"]}],
        audit_user_id=None,
    )
    header = sales_repo.get_receipt(receipt_id)
    assert abs(float(header["total_price"]) - 24.0) < 1e-6