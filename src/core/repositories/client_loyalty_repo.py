"""
Client Loyalty Repository for the PET Application.
Provides per-client visit frequency, spending, and loyalty analytics.
"""

import logging
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def get_client_loyalty_stats(owner_id):
    """Returns loyalty statistics for a specific owner."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT
            COUNT(DISTINCT v.visit_id) AS visit_count,
            COALESCE(SUM(r.total_price), 0) AS total_spend,
            MAX(v.visit_date) AS last_visit_date,
            CASE WHEN COUNT(DISTINCT v.visit_id) > 0
                 THEN ROUND(COALESCE(SUM(r.total_price), 0) * 1.0 / COUNT(DISTINCT v.visit_id), 2)
                 ELSE 0 END AS avg_spend
        FROM pets p
        LEFT JOIN visits v ON p.pet_id = v.pet_id
        LEFT JOIN receipts r ON v.visit_id = r.visit_id AND COALESCE(r.receipt_kind, 'visit') <> 'expense'
        WHERE p.owner_id = ?
    """)
    query.addBindValue(owner_id)
    if query.exec() and query.next():
        return {
            "visit_count": int(query.value(0) or 0),
            "total_spend": float(query.value(1) or 0),
            "last_visit_date": query.value(2),
            "avg_spend": float(query.value(3) or 0),
        }
    return {"visit_count": 0, "total_spend": 0.0, "last_visit_date": None, "avg_spend": 0.0}


def get_top_clients(limit=10):
    """Returns the top-spending clients."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT o.owner_id,
               o.first_name || ' ' || o.last_name AS owner_name,
               COUNT(DISTINCT v.visit_id) AS visit_count,
               COALESCE(SUM(r.total_price), 0) AS total_spend,
               MAX(v.visit_date) AS last_visit_date
        FROM owners o
        JOIN pets p ON o.owner_id = p.owner_id
        LEFT JOIN visits v ON p.pet_id = v.pet_id
        LEFT JOIN receipts r ON v.visit_id = r.visit_id AND COALESCE(r.receipt_kind, 'visit') <> 'expense'
        GROUP BY o.owner_id
        HAVING total_spend > 0
        ORDER BY total_spend DESC
        LIMIT ?
    """)
    query.addBindValue(limit)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "owner_id": query.value(0),
                "owner_name": query.value(1),
                "visit_count": int(query.value(2) or 0),
                "total_spend": float(query.value(3) or 0),
                "last_visit_date": query.value(4),
            })
    return results


def get_visit_frequency(owner_id):
    """Returns visit counts per month for an owner."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT strftime('%Y-%m', v.visit_date) AS month, COUNT(*) AS visit_count
        FROM pets p
        JOIN visits v ON p.pet_id = v.pet_id
        WHERE p.owner_id = ?
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    query.addBindValue(owner_id)
    results = []
    if query.exec():
        while query.next():
            results.append({
                "month": query.value(0),
                "visit_count": int(query.value(1) or 0),
            })
    return results
