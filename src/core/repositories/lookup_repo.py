"""Lookup table repository for the PET Application.

Wraps read access to the small constant/lookup tables (stat types, states,
categories, services) so UI code never runs raw SQL against them.
"""

from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection
from src.core.database.seed_data import FOLLOWUP_STATUS_STATES


def get_stat_types():
    """Returns id/name pairs from the stat_types_lookup table, ordered by name."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT stat_type_id, stat_name FROM stat_types_lookup ORDER BY stat_name ASC"):
        while query.next():
            results.append((query.value(0), query.value(1)))
    return results


def get_states(category_id=None, category_name=None):
    """Returns (state_id, state_value) pairs from states_lookup.

    Optionally filtered by a numeric category_id or by the category name
    (joined through categories_lookup). If neither is given, all states are
    returned.
    """
    db = get_connection()
    query = QSqlQuery(db)
    sql = (
        "SELECT s.state_id, s.state_value FROM states_lookup s "
        "LEFT JOIN categories_lookup c ON c.category_id = s.category_id"
    )
    if category_id is not None:
        sql += " WHERE s.category_id = ?"
    elif category_name is not None:
        sql += " WHERE c.category_name = ?"
    sql += " ORDER BY s.state_value ASC"
    query.prepare(sql)
    if category_id is not None:
        query.addBindValue(category_id)
    elif category_name is not None:
        query.addBindValue(category_name)
    results = []
    if query.exec():
        while query.next():
            results.append((query.value(0), query.value(1)))
    return results


def get_followup_statuses():
    """Returns (state_value, state_id) pairs for the 'followup_status' category.

    Restricted to the supported vocabulary (FOLLOWUP_STATUS_STATES) and returned
    in its declared order, so a legacy row such as "Scheduled" — which older
    databases still carry until migration 020 prunes it — is never offered in a
    follow-up status combo.
    """
    stored = {value: state_id for state_id, value in get_states(category_name="followup_status")}
    return [(value, stored[value]) for value in FOLLOWUP_STATUS_STATES
            if value in stored]


def get_state_id(category_name, state_value):
    """Returns the state_id matching *state_value* inside a lookup category.

    Returns None when either the category or the value is unknown — callers
    that treat a missing state as a meaningful value (e.g. a follow-up with no
    state reads back as "Pending") must handle that explicitly.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "SELECT s.state_id FROM states_lookup s "
        "JOIN categories_lookup c ON c.category_id = s.category_id "
        "WHERE c.category_name = ? AND s.state_value = ?"
    )
    query.addBindValue(category_name)
    query.addBindValue(state_value)
    if query.exec() and query.next():
        return query.value(0)
    return None


def get_service_id(service_name):
    """Returns the service_id matching a service name, or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT service_id FROM services_lookup WHERE service_name = ?")
    query.addBindValue(service_name)
    if query.exec() and query.next():
        return query.value(0)
    return None