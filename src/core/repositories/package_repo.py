"""
Package Repository for the PET Application.
Handles service packages that bundle multiple services and/or supplies.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_all_packages():
    """Returns all service packages."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT package_id, package_name, description, total_price FROM packages ORDER BY package_name ASC"):
        while query.next():
            results.append({
                "package_id": query.value(0),
                "package_name": query.value(1),
                "description": query.value(2),
                "total_price": query.value(3),
            })
    return results


def add_package(package_name, description, total_price):
    """Creates a new service package."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO packages (package_name, description, total_price)
        VALUES (?, ?, ?)
    """)
    query.addBindValue(package_name.strip())
    query.addBindValue(description.strip())
    query.addBindValue(total_price)
    if not query.exec():
        logger.error(f"Failed to add package '{package_name}': {query.lastError().text()}")
        return None
    return query.lastInsertId()


def update_package(package_id, package_name, description, total_price):
    """Updates a service package."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        UPDATE packages SET package_name = ?, description = ?, total_price = ?
        WHERE package_id = ?
    """)
    query.addBindValue(package_name.strip())
    query.addBindValue(description.strip())
    query.addBindValue(total_price)
    query.addBindValue(package_id)
    return query.exec()


def delete_package(package_id):
    """Deletes a service package and its items."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM packages WHERE package_id = ?")
    query.addBindValue(package_id)
    return query.exec()


def add_package_item(package_id, service_id=None, supply_id=None, quantity=1, item_type=None):
    """Adds a service or supply item to a package.
    
    Args:
        package_id: The package ID
        service_id: The service ID (if item is a service)
        supply_id: The supply ID (if item is a supply)
        quantity: Number of units
        item_type: 'service' or 'supply'. Auto-detected if not provided.
    """
    db = get_connection()
    query = QSqlQuery(db)
    
    # Auto-detect item_type if not provided
    if item_type is None:
        item_type = 'service' if service_id is not None else 'supply'
    
    query.prepare("""
        INSERT INTO package_items (package_id, item_type, service_id, supply_id, quantity)
        VALUES (?, ?, ?, ?, ?)
    """)
    query.addBindValue(package_id)
    query.addBindValue(item_type)
    query.addBindValue(service_id)
    query.addBindValue(supply_id)
    query.addBindValue(quantity)
    if not query.exec():
        logger.error(f"Failed to add item to package {package_id}: {query.lastError().text()}")
        return None
    return query.lastInsertId()


def get_package_items(package_id):
    """Retrieves all items (services/supplies) in a package."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT pi.package_item_id, pi.package_id, pi.item_type, pi.service_id, pi.supply_id, pi.quantity,
               srv.service_name, sup.item_name
        FROM package_items pi
        LEFT JOIN services_lookup srv ON pi.service_id = srv.service_id
        LEFT JOIN supplies sup ON pi.supply_id = sup.supply_id
        WHERE pi.package_id = ?
        ORDER BY pi.package_item_id ASC
    """)
    query.addBindValue(package_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "package_item_id": query.value(0),
                "package_id": query.value(1),
                "item_type": query.value(2),
                "service_id": query.value(3),
                "supply_id": query.value(4),
                "quantity": query.value(5),
                "service_name": query.value(6),
                "item_name": query.value(7),
            })
    return results


def remove_package_item(package_item_id):
    """Removes an item from a package."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM package_items WHERE package_item_id = ?")
    query.addBindValue(package_item_id)
    return query.exec()
