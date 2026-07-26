"""
User Repository for the PET Application.
Handles user accounts, authentication, and role management.
"""

import logging
import hashlib
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)


def hash_password(password, salt=""):
    """Returns a SHA-256 hex digest of the password (with optional salt)."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


def authenticate_user(username, password):
    """Authenticates a user by username and password.
    
    Returns user dict on success, None on failure.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT user_id, username, password_hash, salt, last_login
        FROM users WHERE username = ?
    """)
    query.addBindValue(username)
    
    if query.exec() and query.next():
        stored_hash = query.value(2)
        salt = query.value(3) or ""
        if hash_password(password, salt) == stored_hash:
            # Update last login
            up = QSqlQuery(db)
            up.prepare("UPDATE users SET last_login = datetime('now', 'localtime') WHERE user_id = ?")
            up.addBindValue(query.value(0))
            up.exec()
            
            return {
                "user_id": query.value(0),
                "username": query.value(1),
                "last_login": query.value(4),
            }
    return None


def add_user(username, password, role_name="staff"):
    """Creates a new user with a hashed password and role assignment."""
    db = get_connection()
    
    salt = hashlib.sha256(username.encode()).hexdigest()[:8]
    pw_hash = hash_password(password, salt)
    
    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO users (username, password_hash, salt)
        VALUES (?, ?, ?)
    """)
    query.addBindValue(username)
    query.addBindValue(pw_hash)
    query.addBindValue(salt)
    
    if not query.exec():
        logger.error(f"Failed to add user '{username}': {query.lastError().text()}")
        return None
    
    user_id = query.lastInsertId()
    
    # Assign role
    rq = QSqlQuery(db)
    rq.prepare("SELECT role_id FROM roles WHERE role_name = ?")
    rq.addBindValue(role_name)
    if rq.exec() and rq.next():
        role_id = rq.value(0)
        ur = QSqlQuery(db)
        ur.prepare("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)")
        ur.addBindValue(user_id)
        ur.addBindValue(role_id)
        ur.exec()
    
    return user_id


def get_users():
    """Returns all users (without password hashes)."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT user_id, username, last_login FROM users ORDER BY username ASC"):
        while query.next():
            results.append({
                "user_id": query.value(0),
                "username": query.value(1),
                "last_login": query.value(2),
            })
    return results


def get_user_roles(user_id):
    """Returns role names assigned to a user."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT r.role_name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = ?
    """)
    query.addBindValue(user_id)
    results = []
    if query.exec():
        while query.next():
            results.append(query.value(0))
    return results


def get_all_roles():
    """Returns all defined roles."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT role_id, role_name FROM roles ORDER BY role_name ASC"):
        while query.next():
            results.append({
                "role_id": query.value(0),
                "role_name": query.value(1),
            })
    return results


def update_user_password(user_id, new_password):
    """Updates a user's password."""
    db = get_connection()
    user = None
    q = QSqlQuery(db)
    q.prepare("SELECT username FROM users WHERE user_id = ?")
    q.addBindValue(user_id)
    if q.exec() and q.next():
        username = q.value(0)
        salt = hashlib.sha256(username.encode()).hexdigest()[:8]
        pw_hash = hash_password(new_password, salt)
        
        up = QSqlQuery(db)
        up.prepare("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?")
        up.addBindValue(pw_hash)
        up.addBindValue(salt)
        up.addBindValue(user_id)
        return up.exec()
    return False


def delete_user(user_id):
    """Deletes a user by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM users WHERE user_id = ?")
    query.addBindValue(user_id)
    return query.exec()
