"""
Tests for supply inventory rules:
  * item names are unique per category (a repeat purchase restocks, never duplicates)
  * restocking records a stock batch with the purchase date and supplier
  * the supplier name is surfaced for the item details dialog
"""

from datetime import date, timedelta

import src.core.repositories.stock_repo as stock_repo
import src.core.repositories.supply_repo as supply_repo
import src.core.repositories.supplier_repo as supplier_repo


def _add(sid_or_name, category="Medicine", sub="Antibiotics", quantity=10,
         supplier=None, purchase_date="2026-01-01", expiry="2027-01-01",
         buy=5.0, sell=10.0):
    return supply_repo.add_supply(
        sid_or_name, category, sub, purchase_date=purchase_date, expiry_date=expiry,
        buy_price=buy, sell_price=sell, quantity=quantity, supplier=supplier,
    )


def test_get_existing_supply_matches_on_name_and_category_only(fresh_db, repos):
    sid, _ = _add("Amoxicillin")
    # Different sub-category, purchase date and expiry still resolve to the same item.
    found = supply_repo.get_existing_supply("amoxicillin", "Medicine", "Vaccines", "2026-09-09", "2030-01-01", None)
    assert found["supply_id"] == sid
    assert found["current_stock"] == 10

    # A different category is a different item.
    assert supply_repo.get_existing_supply("Amoxicillin", "Food") is None


def test_repeat_add_restockes_instead_of_duplicating(fresh_db, repos):
    first_id, _ = _add("Amoxicillin", quantity=10)
    second_id, expense = _add("Amoxicillin", sub="Vaccines", quantity=7,
                              purchase_date="2026-02-01", expiry="2028-02-01")

    assert second_id == first_id, "same name in the same category must reuse the row"
    rows = [r for r in supply_repo.search_supplies() if r["item_name"] == "Amoxicillin"]
    assert len(rows) == 1
    assert rows[0]["current_stock"] == 17
    assert expense["quantity"] == 7
    assert expense["purchase_date"] == "2026-02-01"


def test_same_name_in_another_category_creates_a_new_item(fresh_db, repos):
    first_id, _ = _add("Amoxicillin", category="Medicine", quantity=10)
    second_id, _ = _add("Amoxicillin", category="Food", sub="Dry Food", quantity=3)
    assert second_id != first_id
    assert supply_repo.get_existing_supply("Amoxicillin", "Food")["current_stock"] == 3


def test_restock_records_a_batch_with_the_supplier(fresh_db, repos):
    sid, _ = _add("Bandage", quantity=10, supplier="VetSupply Co")
    sid2, _ = _add("Bandage", quantity=5, supplier="Cairo Animal Care",
                   purchase_date="2026-03-01")

    assert sid2 == sid
    batches = repos["stock"].get_stock_batches(sid)
    assert sorted(b["quantity"] for b in batches) == [5, 10]
    latest = next(b for b in batches if b["purchase_date"] == "2026-03-01")
    assert latest["supplier_name"] == "Cairo Animal Care"
    assert repos["stock"].get_total_stock_for_supply(sid) == 15


def test_supplier_is_reported_for_the_item_details_dialog(fresh_db, repos):
    sid, _ = _add("Syringe", quantity=4, supplier="PetMed Distributors")
    _add("Syringe", quantity=2, supplier="PetMed Distributors", purchase_date="2026-05-05")

    details = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert details["supplier"] == "PetMed Distributors"
    assert details["purchase_date"] == "2026-05-05"


def test_supplier_is_created_once_per_name(fresh_db, repos):
    supplier_id = supplier_repo.get_or_create_supplier("  Acme Vet Co ")
    again = supplier_repo.get_or_create_supplier("acme vet co")
    assert supplier_id is not None
    assert again == supplier_id
    assert supplier_repo.get_or_create_supplier("   ") is None
    assert [s["supplier_name"] for s in supplier_repo.get_suppliers()].count("Acme Vet Co") == 1


def test_update_supply_stock_without_added_quantity_adds_no_batch(fresh_db, repos):
    sid, _ = _add("Gloves", quantity=10, supplier="VetSupply Co")
    ok, expense = supply_repo.update_supply_stock(sid, 10)
    assert ok
    assert expense is None
    assert len(repos["stock"].get_stock_batches(sid)) == 1


# ---------------------------------------------------------------------------
# Per-batch expiry date and buy price (each batch owns its own values)
# ---------------------------------------------------------------------------
def test_a_new_batch_inherits_the_item_price_and_expiry(fresh_db, repos):
    stock_repo = repos["stock"]
    sid, _ = _add("Catheter", quantity=4, buy=3.5, expiry="2028-01-01")

    inherited = stock_repo.get_stock_batches(sid)[0]
    assert inherited["buy_price"] == 3.5
    assert inherited["expiry_date"] == "2028-01-01"

    # A restock records a batch carrying the same item values...
    supply_repo.update_supply_stock(sid, 9, purchase_date="2026-06-06")
    restocked = next(b for b in stock_repo.get_stock_batches(sid)
                     if b["purchase_date"] == "2026-06-06")
    assert restocked["buy_price"] == 3.5
    assert restocked["expiry_date"] == "2028-01-01"

    # ...and editing one batch never touches the item or its siblings.
    stock_repo.update_stock_batch(restocked["batch_id"], restocked["supplier_id"],
                                  restocked["purchase_date"], 5, "",
                                  expiry_date="2030-12-31", buy_price=9.75)
    edited = stock_repo.get_stock_batch(restocked["batch_id"])
    assert (edited["expiry_date"], edited["buy_price"]) == ("2030-12-31", 9.75)
    assert stock_repo.get_stock_batch(inherited["batch_id"])["buy_price"] == 3.5
    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert row["buy_price"] == 3.5
    assert row["expiry_date"] == "2028-01-01"


def test_batch_without_expiry_or_price_reads_back_as_none(fresh_db, repos):
    stock_repo = repos["stock"]
    sid, _ = _add("Nitrile Gloves", category="Tools", sub="Consumables",
                  quantity=2, buy=None, expiry=None)
    batch = stock_repo.get_stock_batches(sid)[0]
    assert batch["expiry_date"] is None
    assert batch["buy_price"] is None
    assert stock_repo.get_stock_batch(batch["batch_id"])["expiry_date"] is None


def test_get_stock_batch_returns_none_for_an_unknown_id(fresh_db, repos):
    assert repos["stock"].get_stock_batch(-1) is None


# ---------------------------------------------------------------------------
# Expiring batches (the reorder dialog lists one row per batch, not per item)
# ---------------------------------------------------------------------------
def test_expiring_batches_are_listed_per_batch_with_their_own_quantity(fresh_db, repos):
    stock = repos["stock"]
    today = date.today()
    soon = (today + timedelta(days=10)).isoformat()
    later = (today + timedelta(days=40)).isoformat()

    sid, _ = _add("Vaccine A", expiry="2030-01-01")          # far out: not listed
    # A second purchase of the same item that expires much sooner.
    supply_repo.update_supply_stock(sid, 6, purchase_date=today.isoformat())
    batch = stock.get_stock_batches(sid)[0]
    stock.update_stock_batch(batch["batch_id"], batch["supplier_id"],
                             today.isoformat(), 6, "",
                             expiry_date=soon, buy_price=7.0)

    rows = stock.get_expiring_batches()
    assert [r["batch_id"] for r in rows] == [batch["batch_id"]]
    row = rows[0]
    assert row["item_name"] == "Vaccine A"
    assert row["quantity"] == 6, "the row must show the batch quantity, not the item stock"
    assert row["expiry_date"] == soon
    assert row["days_left"] == 10

    # ... and the later-dated item only shows once its own window arrives.
    stock.update_stock_batch(batch["batch_id"], batch["supplier_id"],
                             today.isoformat(), 6, "",
                             expiry_date=later, buy_price=7.0)
    assert stock.get_expiring_batches()[0]["days_left"] == 40
    assert stock.get_expiring_batches(days_ahead=20) == []


def test_a_batch_without_its_own_expiry_falls_back_to_the_item_default(fresh_db, repos):
    stock = repos["stock"]
    item_expiry = (date.today() + timedelta(days=5)).isoformat()
    sid, _ = _add("Syrup", expiry=item_expiry)
    batch = stock.get_stock_batches(sid)[0]
    stock.update_stock_batch(batch["batch_id"], batch["supplier_id"],
                             batch["purchase_date"], 5, "", expiry_date=None)

    rows = stock.get_expiring_batches()
    assert len(rows) == 1
    assert rows[0]["batch_id"] == batch["batch_id"]
    assert rows[0]["expiry_date"] == item_expiry


def test_expired_and_undated_batches_are_left_out(fresh_db, repos):
    stock = repos["stock"]
    _add("Old Vaccine", expiry=(date.today() - timedelta(days=3)).isoformat())
    _add("Gauze", category="Tools", sub="Consumables", expiry=None)

    assert stock.get_expiring_batches() == []


# ---------------------------------------------------------------------------
# Quantity column: the total across the item's batches
# ---------------------------------------------------------------------------
def test_search_supplies_reports_the_batch_total_next_to_the_live_stock(fresh_db, repos):
    """The supplies page shows the batch total; current_stock stays the live stock."""
    sid, _ = _add("Drip Set", quantity=10, supplier="VetSupply Co")
    supply_repo.update_supply_stock(sid, 25, purchase_date="2026-04-01")

    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert row["batch_quantity"] == 25          # 10 + 15 purchased
    assert row["current_stock"] == 25
    assert supply_repo.get_total_quantities_by_item()["Drip Set"] == 25


def test_items_without_batches_report_a_zero_batch_total(fresh_db, repos):
    """An item with stock but no batch rows (legacy data) shows a zero total."""
    sid, _ = _add("Scissors", category="Tools", sub="Instruments", quantity=0)
    supply_repo.update_supply_quantity(sid, 3)

    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert row["batch_quantity"] == 0
    assert row["current_stock"] == 3
    assert supply_repo.get_total_quantities_by_item()["Scissors"] == 0


# ---------------------------------------------------------------------------
# Partial updates (used by the item-details expiry editor and the edit dialog)
# ---------------------------------------------------------------------------
def test_update_supply_details_only_touches_given_fields(fresh_db, repos):
    sid, _ = _add("Suture Kit", quantity=12, buy=4.0, sell=9.0, expiry="2027-01-01")
    assert supply_repo.update_supply_details(sid, expiry_date="2029-06-30") is True

    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert row["expiry_date"] == "2029-06-30"
    assert row["buy_price"] == 4.0
    assert row["sell_price"] == 9.0
    assert row["current_stock"] == 12, "stock is owned by batches, not by this editor"

    assert supply_repo.update_supply_details(
        sid, item_name="Suture Kit Pro", sub_category="Surgical", buy_price=5.0, sell_price=11.0)
    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert (row["item_name"], row["sub_category"], row["buy_price"], row["sell_price"]) == (
        "Suture Kit Pro", "Surgical", 5.0, 11.0)
    assert row["expiry_date"] == "2029-06-30"


def test_update_supply_details_is_a_noop_without_fields(fresh_db, repos):
    sid, _ = _add("Forceps", quantity=3)
    assert supply_repo.update_supply_details(sid) is True


def test_update_supply_details_rejects_duplicate_name(fresh_db, repos):
    first, _ = _add("Bandage Roll", quantity=5)
    second, _ = _add("Bandage Roll Large", quantity=5)

    # Same name kept is fine, colliding with another item in the category is not.
    assert supply_repo.update_supply_details(second, item_name="Bandage Roll Large") is True
    assert supply_repo.update_supply_details(second, item_name="Bandage Roll") is False
    assert supply_repo.update_supply_details(first, sell_price=7.0) is True

    # The same name is still allowed in another category.
    other_cat, _ = _add("Bandage Roll", category="Food", sub="Dry Food", quantity=2)
    assert supply_repo.update_supply_details(other_cat, item_name="Bandage Roll") is True


def test_update_supply_details_moves_the_item_to_another_category(fresh_db, repos):
    sid, _ = _add("Thermometer", quantity=4)

    assert supply_repo.update_supply_details(
        sid, category="Equipment", sub_category="Diagnostics") is True

    row = next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)
    assert (row["category"], row["sub_category"]) == ("Equipment", "Diagnostics")
    assert row["current_stock"] == 4, "moving an item must not touch its stock"
    assert all(r["supply_id"] != sid
               for r in supply_repo.search_supplies(category="Medicine"))


def test_moving_into_a_category_that_already_has_that_name_is_rejected(fresh_db, repos):
    first, _ = _add("Bandage Roll", quantity=5)
    _add("Bandage Roll", category="Food", sub="Dry Food", quantity=2)

    # With or without an explicit rename, the target category must stay unique.
    assert supply_repo.update_supply_details(first, category="Food") is False
    assert supply_repo.update_supply_details(
        first, category="Food", item_name="Bandage Roll") is False
    assert next(r for r in supply_repo.search_supplies() if r["supply_id"] == first)[
        "category"] == "Medicine"

    # A category that does not have the name yet accepts it.
    assert supply_repo.update_supply_details(first, category="Equipment") is True


# ---------------------------------------------------------------------------
# Batch depletion: a sale takes units out of the oldest batches first
# ---------------------------------------------------------------------------
def _batch_totals(sid):
    """``[(purchase_date, quantity)]`` oldest first, the order FIFO uses."""
    return sorted((b["purchase_date"], b["quantity"])
                  for b in stock_repo.get_stock_batches(sid))


def _item(sid):
    return next(r for r in supply_repo.search_supplies() if r["supply_id"] == sid)


def _owner(entity_factory):
    """A real owner row - visits and receipts point at it by FK."""
    return entity_factory["make_client"]()


def _pet_owner(entity_factory):
    """A visit needs a pet, and the pet needs an owner."""
    return entity_factory["make_pet"](entity_factory["make_client"]())


def test_a_sale_depletes_the_batches_oldest_first(fresh_db, repos, entity_factory):
    """Batches keep their history but lose the units the sale consumed."""
    sid, _ = _add("Amoxicillin", quantity=10, purchase_date="2026-01-01")
    _add("Amoxicillin", quantity=7, purchase_date="2026-05-01")

    repos["visit"].add_visit(
        visit_date="2026-06-01 10:00", diagnosis="Dental", consult=False, notes="",
        pet_id=_pet_owner(entity_factory),
        items=[{"item_name": "Amoxicillin", "quantity": 14}],
    )

    assert _batch_totals(sid) == [("2026-01-01", 0), ("2026-05-01", 3)]
    assert (_item(sid)["current_stock"], _item(sid)["batch_quantity"]) == (3, 3)


def test_a_batch_keeps_its_row_when_it_runs_out(fresh_db, repos, entity_factory):
    sid, _ = _add("Vitamin", quantity=4, purchase_date="2026-02-02")

    repos["visit"].add_visit(
        visit_date="2026-06-01 10:00", diagnosis="Checkup", consult=False, notes="",
        pet_id=_pet_owner(entity_factory),
        items=[{"item_name": "Vitamin", "quantity": 4}],
    )

    batches = stock_repo.get_stock_batches(sid)
    assert len(batches) == 1, "the purchase record stays visible"
    assert batches[0]["quantity"] == 0


def test_quick_purchase_depletes_batches_and_editing_a_receipt_gives_units_back(
        fresh_db, repos, entity_factory):
    """A counter sale drains the oldest batch; deleting its line restores stock."""
    sales_repo = repos["sales"]
    sid, _ = _add("Surgical Gloves", category="Tools", sub="Instruments",
                  quantity=6, purchase_date="2026-01-15")
    _add("Surgical Gloves", category="Tools", sub="Instruments",
         quantity=4, purchase_date="2026-04-15")

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        _owner(entity_factory), "2026-06-01",
        [{"item_name": "Surgical Gloves", "quantity": 5, "price": 20.0}])
    assert receipt_id
    assert _batch_totals(sid) == [("2026-01-15", 1), ("2026-04-15", 4)]

    # Deleting the line puts the 5 units back into the newest batch.
    sales_repo.update_receipt(
        receipt_id, 0.0,
        [{"op": "delete", "item_type": "Supply", "item_id": sid}])
    assert _batch_totals(sid) == [("2026-01-15", 1), ("2026-04-15", 9)]
    assert (_item(sid)["current_stock"], _item(sid)["batch_quantity"]) == (10, 10)


def test_editing_a_receipt_line_to_a_bigger_quantity_drains_more_batches(
        fresh_db, repos, entity_factory):
    """Selling one more unit of an old receipt pulls it from the oldest batch."""
    sales_repo = repos["sales"]
    sid, _ = _add("Catheter", category="Tools", sub="Instruments",
                  quantity=2, purchase_date="2026-01-01")
    _add("Catheter", category="Tools", sub="Instruments",
         quantity=5, purchase_date="2026-07-01")

    receipt_id = sales_repo.create_sale_receipt_for_quick_purchase(
        _owner(entity_factory), "2026-06-01",
        [{"item_name": "Catheter", "quantity": 1, "price": 30.0}])
    line_id = sales_repo.get_receipt_line_items(receipt_id)[0]["link_id"]

    sales_repo.update_receipt(
        receipt_id, 0.0,
        [{"op": "update", "item_type": "Supply", "item_id": sid,
          "link_id": line_id, "quantity": 3, "unit_price": 30.0}])

    assert _batch_totals(sid) == [("2026-01-01", 0), ("2026-07-01", 4)]


def test_get_all_species_with_ids_matches_names_alphabetically(fresh_db, repos):
    """Vaccine schedules store the real species_id, not comboIndex+1.

    The combo lists species by name, which is NOT the seed insertion order, so
    a positional id would point at the wrong animal. ``get_all_species_with_ids``
    returns the authoritative (id, name) pairs to bind as combo data.
    """
    pairs = supply_repo.get_all_species_with_ids()
    names = [name for _, name in pairs]

    assert names == sorted(names)
    assert names == supply_repo.get_all_species()
    assert len({sid for sid, _ in pairs}) == len(pairs)
    assert all(isinstance(sid, int) for sid, _ in pairs)
