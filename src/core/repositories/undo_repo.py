"""
Undo/redo journal for top-level deletes (owners, pets, visits, appointments,
supplies, receipts).

Deleting an entity cascades through SQLite FKs, so a usable undo must capture a
full, FK-ordered snapshot of every row that will be removed plus any SET NULL
links that survive the delete, then re-insert them on restore.  Journal rows
live in `deleted_records`; the UI restores from the dashboard (Restore Deleted
Records), the Supplies page, and the Receipts page.
"""

import json

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection

# Child tables per parent, keyed by (child.column -> parent.column).  Order
# within a list matters only for dependency-tolerant capture; restore order is
# fixed per top-level entity below.
_CASCADE = {
    "owners": [
        ("pets", "owner_id", "owner_id"),
        ("receipts", "owner_id", "owner_id"),
    ],
    "pets": [
        ("appointments", "pet_id", "pet_id"),
        ("visits", "pet_id", "pet_id"),
        ("health_stats", "pet_id", "pet_id"),
        ("vaccination_reminders", "pet_id", "pet_id"),
    ],
    "appointments": [
        ("appointment_status_history", "appointment_id", "appointment_id"),
    ],
    "visits": [
        ("followups", "visit_id", "visit_id"),
        ("health_stats", "visit_id", "visit_id"),
        ("medications", "visit_id", "visit_id"),
        ("tests", "visit_id", "visit_id"),
        ("treatments", "visit_id", "visit_id"),
        ("vaccinations", "visit_id", "visit_id"),
    ],
    "receipts": [
        ("receipt_services", "receipt_id", "receipt_id"),
        ("receipt_supplies", "receipt_id", "receipt_id"),
        ("receipt_packages", "receipt_id", "receipt_id"),
        ("receipt_other", "receipt_id", "receipt_id"),
        ("receipt_adjustments", "receipt_id", "receipt_id"),
        ("payments", "receipt_id", "receipt_id"),
    ],
    # Supplies: only CASCADE children need snapshotting.
    # stocks and stock_movements cascade-delete; package_items/receipt_supplies
    # use SET NULL so their rows survive (we relink them on restore).
    "supplies": [
        ("stocks", "supply_id", "supply_id"),
        ("stock_movements", "supply_id", "supply_id"),
    ],
}

# Fixed, FK-safe re-insertion order per top-level entity (parents first).
_RESTORE_ORDER = {
    "owners": [
        "owners", "entity_contacts", "pets", "appointments",
        "appointment_status_history", "visits", "followups", "health_stats",
        "medications", "tests", "treatments", "vaccinations",
        "vaccination_reminders", "receipts", "receipt_services",
        "receipt_supplies", "receipt_packages", "receipt_other",
        "receipt_adjustments", "payments",
    ],
    "pets": [
        "pets", "appointments", "appointment_status_history", "visits",
        "followups", "health_stats", "medications", "tests", "treatments",
        "vaccinations", "vaccination_reminders",
    ],
    "visits": [
        "visits", "followups", "health_stats", "medications", "tests",
        "treatments", "vaccinations",
    ],
    "appointments": [
        "appointments", "appointment_status_history",
    ],
    # Stand-alone supply restore (only the supply row + its cascade children).
    "supplies": [
        "supplies", "stocks", "stock_movements",
    ],
    # Stand-alone receipt restore (receipt row + all its cascade children).
    "receipts": [
        "receipts", "receipt_services", "receipt_supplies",
        "receipt_packages", "receipt_other", "receipt_adjustments", "payments",
    ],
}

_PK_COLUMN = {
    "owners": "owner_id", "pets": "pet_id", "appointments": "appointment_id",
    "visits": "visit_id", "receipts": "receipt_id",
    "appointment_status_history": "status_history_id",
    "followups": "followup_id", "health_stats": "health_stat_id",
    "medications": "medication_id", "tests": "routine_test_id",
    "treatments": "treatment_record_id", "vaccinations": "vaccination_id",
    "vaccination_reminders": "reminder_id",
    "receipt_services": "receipt_service_id",
    "receipt_supplies": "receipt_supply_id",
    "receipt_packages": "receipt_package_id",
    "receipt_other": "receipt_other_id",
    "receipt_adjustments": "adjustment_id", "payments": "payment_id",
    "entity_contacts": "entity_contact_id",
    # Supply children
    "supplies": "supply_id",
    "stocks": "batch_id",
    "stock_movements": "movement_id",
}


def _columns(db, table):
    q = QSqlQuery(db)
    q.exec(f"PRAGMA table_info({table})")
    cols = []
    while q.next():
        cols.append(q.value(1))
    return cols


def _fetch_row(db, table, pk_value):
    """Return the full row as {col: value} or None if missing."""
    cols = _columns(db, table)
    q = QSqlQuery(db)
    q.prepare(f"SELECT * FROM {table} WHERE {_PK_COLUMN[table]} = ?")
    q.addBindValue(pk_value)
    if not q.exec() or not q.next():
        return None
    return {c: q.value(i) for i, c in enumerate(cols)}


def _fetch_rows_by(db, table, column, values):
    """Return rows matching `column IN (values)` as a list of dicts."""
    if not values:
        return []
    cols = _columns(db, table)
    marks = ", ".join(["?"] * len(values))
    q = QSqlQuery(db)
    q.prepare(f"SELECT * FROM {table} WHERE {column} IN ({marks})")
    for v in values:
        q.addBindValue(v)
    rows = []
    if q.exec():
        while q.next():
            rows.append({c: q.value(i) for i, c in enumerate(cols)})
    return rows


def _children_of(db, parent_table, parent_rows):
    """Gather cascade-child rows for a set of parent rows (children first)."""
    collected = []
    for child_table, child_col, parent_col in _CASCADE.get(parent_table, ()):
        ids = {r[parent_col] for r in parent_rows if r.get(parent_col) is not None}
        child_rows = _fetch_rows_by(db, child_table, child_col, list(ids))
        if child_rows:
            collected.append((child_table, child_rows))
            collected.extend(_children_of(db, child_table, child_rows))
    return collected


def _capture_tree(db, table, pk_value):
    """Capture the top row + full cascade subtree, FK-ordered (parents first)."""
    top = _fetch_row(db, table, pk_value)
    if top is None:
        return None
    rows_by_table = {table: [top]}
    children = _children_of(db, table, [top])
    for child_table, child_rows in children:
        rows_by_table.setdefault(child_table, []).extend(child_rows)
    # Dedupe across overlapping cascade paths (e.g. health_stats via pet AND visit).
    for tbl, rows in rows_by_table.items():
        seen, unique = set(), []
        pk = _PK_COLUMN[tbl]
        for r in rows:
            key = (tbl, r.get(pk))
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        rows_by_table[tbl] = unique
    return rows_by_table


def _owner_entity_contacts(db, owner_id):
    cols = _columns(db, "entity_contacts")
    q = QSqlQuery(db)
    q.prepare("SELECT * FROM entity_contacts WHERE entity_type = 'owner' AND entity_id = ?")
    q.addBindValue(owner_id)
    rows = []
    if q.exec():
        while q.next():
            rows.append({c: q.value(i) for i, c in enumerate(cols)})
    return rows


def _visit_relink(db, visit_rows):
    """SET NULL links that survive a delete: receipts/adjustments .visit_id."""
    relink = []
    for table, col in (("receipts", "visit_id"), ("receipt_adjustments", "visit_id")):
        for v in (visit_rows or []):
            vid = v.get("visit_id")
            if vid is None:
                continue
            rows = _fetch_rows_by(db, table, "visit_id", [vid])
            if rows:
                relink.append({
                    "table": table,
                    "column": col,
                    "value": vid,
                    "ids": [r[_PK_COLUMN[table]] for r in rows],
                })
    return relink


def _appointment_relink(db, appointment_rows):
    """Visits whose appointment_id is SET NULL when an appointment is deleted."""
    relink = []
    for a in (appointment_rows or []):
        aid = a.get("appointment_id")
        if aid is None:
            continue
        rows = _fetch_rows_by(db, "visits", "appointment_id", [aid])
        if rows:
            relink.append({
                "table": "visits",
                "column": "appointment_id",
                "value": aid,
                "ids": [r["visit_id"] for r in rows],
            })
    return relink


def _supply_relink(db, supply_id):
    """Collect SET-NULL links that survive a supply delete.

    receipt_supplies.supply_id and package_items.supply_id are SET NULL on
    delete, so the rows survive but lose the reference.  On restore we update
    them back to the original supply_id.
    """
    relink = []
    for table, col, pk in (
        ("receipt_supplies", "supply_id", "receipt_supply_id"),
        ("package_items", "supply_id", "package_item_id"),
    ):
        rows = _fetch_rows_by(db, table, col, [supply_id])
        # After the delete these rows will have supply_id = NULL; at snapshot
        # time they still have the value, so we record the ids + the value.
        if rows:
            relink.append({
                "table": table,
                "column": col,
                "value": supply_id,
                "ids": [r[pk] for r in rows],
            })
    return relink


def capture_snapshot(table_name, record_id):
    """Build the undo snapshot dict for a top-level delete (call BEFORE delete).

    Returns None when the record does not exist (nothing to journal).
    """
    db = get_connection()
    rows_by_table = _capture_tree(db, table_name, record_id)
    if rows_by_table is None:
        return None

    if table_name == "owners":
        rows_by_table["entity_contacts"] = _owner_entity_contacts(db, record_id)

    order = [t for t in _RESTORE_ORDER[table_name] if t in rows_by_table]
    tables = [{"table": t, "rows": rows_by_table[t]} for t in order]

    relink = []
    if table_name == "supplies":
        relink.extend(_supply_relink(db, record_id))
    elif "visits" in rows_by_table and "receipts" not in rows_by_table:
        relink.extend(_visit_relink(db, rows_by_table["visits"]))
    if "appointments" in rows_by_table and "visits" not in rows_by_table:
        relink.extend(_appointment_relink(db, rows_by_table["appointments"]))

    return {"tables": tables, "relink": relink}


def record_deletion(table_name, record_id, snapshot, user_id=None):
    """Persist a snapshot to the journal. Returns the new deleted_record_id."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare(
        "INSERT INTO deleted_records (table_name, record_id, snapshot, deleted_by) "
        "VALUES (?, ?, ?, ?)"
    )
    q.addBindValue(table_name)
    q.addBindValue(record_id)
    q.addBindValue(json.dumps(snapshot))
    q.addBindValue(user_id)
    q.exec()
    return q.lastInsertId() if q.numRowsAffected() > 0 else None


def list_deleted_records(limit=50):
    """Return unresored journal entries, newest first."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare(
        "SELECT deleted_record_id, table_name, record_id, deleted_by, deleted_at, "
        "restored_at, snapshot "
        "FROM deleted_records WHERE restored_at IS NULL "
        "ORDER BY deleted_at DESC, deleted_record_id DESC LIMIT ?"
    )
    q.addBindValue(int(limit))
    rows = []
    if q.exec():
        while q.next():
            rows.append({
                "deleted_record_id": q.value(0),
                "table_name": q.value(1),
                "record_id": q.value(2),
                "deleted_by": q.value(3),
                "deleted_at": q.value(4),
                "restored_at": q.value(5),
                "snapshot": q.value(6),
            })
    return rows


def get_deleted_record(deleted_record_id):
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare(
        "SELECT table_name, record_id, snapshot, deleted_by, deleted_at, restored_at "
        "FROM deleted_records WHERE deleted_record_id = ?"
    )
    q.addBindValue(deleted_record_id)
    if not q.exec() or not q.next():
        return None
    return {
        "table_name": q.value(0),
        "record_id": q.value(1),
        "snapshot": q.value(2),
        "deleted_by": q.value(3),
        "deleted_at": q.value(4),
        "restored_at": q.value(5),
    }


def _reconsume_receipt_stock(db, snapshot, user_id=None):
    """Re-deducts stock for a restored receipt's supply lines.

    ``sales_repo.delete_receipt`` returns the sold units on delete, so the
    restore must take them out again (live stock + batches + movement trail).
    Runs inside the caller's transaction. Returns (ok, message).
    """
    from src.core.repositories import stock_repo
    lines = []
    for block in snapshot.get("tables", []):
        if block["table"] == "receipt_supplies":
            lines = block["rows"]
            break
    receipt_id = None
    for block in snapshot.get("tables", []):
        if block["table"] == "receipts" and block["rows"]:
            receipt_id = block["rows"][0].get("receipt_id")
            break
    for row in lines:
        supply_id = row.get("supply_id")
        qty = int(row.get("quantity") or 0)
        if not supply_id or qty <= 0:
            continue
        q = QSqlQuery(db)
        q.prepare("UPDATE supplies SET current_stock = current_stock - ? "
                  "WHERE supply_id = ?")
        q.addBindValue(qty)
        q.addBindValue(supply_id)
        if not q.exec():
            err = q.lastError().text()
            q.finish()
            return False, f"restore_stock_failed:{err}"
        q.finish()
        stock_repo.consume_batches(db, supply_id, qty)
        stock_repo.record_movement(
            db, supply_id, "sale", -qty,
            notes=f"Receipt #{receipt_id} restored", user_id=user_id,
            receipt_id=receipt_id)
    return True, ""


def restore_deleted_record(deleted_record_id, user_id=None):
    """Restore a journaled delete. Returns (ok, message)."""
    entry = get_deleted_record(deleted_record_id)
    if entry is None:
        return False, "record_missing"
    if entry["restored_at"]:
        return False, "already_restored"

    try:
        snapshot = json.loads(entry["snapshot"])
    except (TypeError, ValueError):
        return False, "invalid_snapshot"

    db = get_connection()

    db.transaction()
    try:
        for block in snapshot.get("tables", []):
            table, rows = block["table"], block["rows"]
            if not rows:
                continue
            cols = list(rows[0].keys())
            marks = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})"
            q = QSqlQuery(db)
            q.prepare(sql)
            for row in rows:
                for c in cols:
                    v = row.get(c)
                    # Absent FKs are stored as '' in this schema; on re-insert
                    # an empty string is an invalid FK id, so null it out.
                    q.addBindValue(None if v == "" else v)
                if not q.exec():
                    q.finish()
                    db.rollback()
                    return False, f"restore_failed:{table}:{q.lastError().text()}"
        for rel in snapshot.get("relink", []):
            marks = ", ".join(["?"] * len(rel["ids"]))
            sql = f"UPDATE {rel['table']} SET {rel['column']} = ? WHERE {_PK_COLUMN[rel['table']]} IN ({marks})"
            q = QSqlQuery(db)
            q.prepare(sql)
            q.addBindValue(rel["value"])
            for i in rel["ids"]:
                q.addBindValue(i)
            if not q.exec():
                db.rollback()
                return False, f"relink_failed:{rel['table']}"
        # sales_repo.delete_receipt hands the sold units back to stock; a
        # restored sale must take them out again, or stock is double-counted.
        if entry["table_name"] == "receipts":
            ok, msg = _reconsume_receipt_stock(db, snapshot, user_id)
            if not ok:
                db.rollback()
                return False, msg
        q = QSqlQuery(db)
        q.prepare("UPDATE deleted_records SET restored_at = datetime('now'), restored_by = ? "
                  "WHERE deleted_record_id = ?")
        q.addBindValue(user_id)
        q.addBindValue(deleted_record_id)
        q.exec()
        db.commit()
    except Exception:
        db.rollback()
        return False, "restore_failed"

    from src.core.repositories.audit_repo import record_action
    record_action(
        "RESTORE", entry["table_name"], entry["record_id"],
        changes=[{"field_name": "restored_record", "old_value": "", "new_value": str(entry["record_id"])}],
        user_id=user_id,
    )
    return True, ""