"""
User Repository for the PET Application.
Handles user accounts, authentication, and role management.
"""

import logging
import hashlib
import base64
import hmac
import os
import binascii
from PyQt5.QtSql import QSqlQuery
from src.core.database import get_connection

logger = logging.getLogger(__name__)

# PBKDF2-HMAC-SHA256 parameters for newly created / re-hashed passwords.
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_ALG = "pbkdf2_sha256"
_SALT_BYTES = 16


def hash_password(password, salt=""):
    """Returns a SHA-256 hex digest of the password (with optional salt).

    NOTE: This is the legacy hashing primitive, retained for verifying hashes
    created before the PBKDF2 upgrade and for isolated callers/tests. New
    passwords must use :func:`hash_secure` instead.
    """
    return hashlib.sha256((salt + password).encode()).hexdigest()


def hash_secure(password, salt=None, iterations=_PBKDF2_ITERATIONS):
    """Returns a self-describing PBKDF2-HMAC-SHA256 hash for a password.

    Format: ``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``

    A fresh random salt is generated per call unless one is supplied (supplying
    a salt is only done when re-hashing/verifying an existing secure hash).
    """
    if salt is None:
        salt_bytes = os.urandom(_SALT_BYTES)
    else:
        salt_bytes = binascii.unhexlify(salt)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, iterations
    )
    salt_b64 = base64.b64encode(salt_bytes).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"{_PBKDF2_ALG}${iterations}${salt_b64}${hash_b64}"


def _verify_secure_hash(stored_hash, password):
    """Verifies ``password`` against a self-describing PBKDF2 hash string."""
    try:
        _, iterations_str, salt_b64, hash_b64 = stored_hash.split("$")
        iterations = int(iterations_str)
        salt_bytes = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError, binascii.Error):
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, iterations
    )
    return _constant_time_eq(dk, expected)


def _constant_time_eq(a: bytes, b: bytes) -> bool:
    """Constant-time comparison to avoid timing side-channels."""
    return hmac.compare_digest(a, b)


def verify_password(stored_hash, stored_salt, password):
    """Verifies a password against a stored hash in either format.

    Returns True on match. Detects the scheme by the hash's prefix:
      - ``pbkdf2_sha256$...`` -> PBKDF2-HMAC-SHA256 (current scheme)
      - otherwise              -> legacy SHA-256 (``salt`` + ``password``)

    The legacy path is kept so accounts created before the upgrade still work;
    :func:`authenticate_user` re-hashes them to the secure scheme on success.
    """
    if stored_hash and stored_hash.startswith(_PBKDF2_ALG + "$"):
        return _verify_secure_hash(stored_hash, password)
    return hash_password(password, stored_salt or "") == stored_hash


def authenticate_user(username, password):
    """Authenticates a user by username and password.
    
    Returns user dict on success, None on failure.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT user_id, username, password_hash, salt, last_login, doctor_id
        FROM users WHERE username = ?
    """)
    query.addBindValue(username)
    
    if query.exec() and query.next():
        stored_hash = query.value(2)
        salt = query.value(3) or ""
        if verify_password(stored_hash, salt, password):
            # Transparently upgrade legacy (unsalted/old-salt SHA-256) accounts
            # to the secure PBKDF2 scheme the first time they log in.
            if stored_hash and not stored_hash.startswith(_PBKDF2_ALG + "$"):
                secure = hash_secure(password)
                upq = QSqlQuery(db)
                upq.prepare("UPDATE users SET password_hash = ? WHERE user_id = ?")
                upq.addBindValue(secure)
                upq.addBindValue(query.value(0))
                upq.exec()

            # Update last login
            up = QSqlQuery(db)
            up.prepare("UPDATE users SET last_login = datetime('now', 'localtime') WHERE user_id = ?")
            up.addBindValue(query.value(0))
            up.exec()
            
            user = {
                "user_id": query.value(0),
                "username": query.value(1),
                "last_login": query.value(4),
                "doctor_id": query.value(5),
            }
            # Fetch roles for this user
            user["roles"] = get_user_roles(user["user_id"])
            _attach_permissions(user)
            return user
    return None


def add_user(username, password, role_name="staff", doctor_id=None):
    """Creates a new user with a securely hashed password and role assignment.

    Returns the new ``user_id``, or ``None`` on failure. The role is resolved
    *before* the user row is created: creating an account with an unknown role
    would leave a user who can log in but is denied every action.
    """
    db = get_connection()

    role_id = None
    if role_name:
        rq = QSqlQuery(db)
        rq.prepare("SELECT role_id FROM roles WHERE role_name = ?")
        rq.addBindValue(role_name)
        found = rq.exec() and rq.next()
        if found:
            role_id = rq.value(0)
        rq.finish()
        if not found:
            logger.error(f"Cannot add user '{username}': unknown role '{role_name}'")
            return None

    pw_hash = hash_secure(password)

    query = QSqlQuery(db)
    query.prepare("""
        INSERT INTO users (username, password_hash, salt, doctor_id)
        VALUES (?, ?, ?, ?)
    """)
    query.addBindValue(username)
    query.addBindValue(pw_hash)
    query.addBindValue(None)
    query.addBindValue(doctor_id)
    
    if not query.exec():
        logger.error(f"Failed to add user '{username}': {query.lastError().text()}")
        return None
    
    user_id = query.lastInsertId()
    query.finish()

    # Assign role
    if role_id is not None:
        ur = QSqlQuery(db)
        ur.prepare("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)")
        ur.addBindValue(user_id)
        ur.addBindValue(role_id)
        ur.exec()
        ur.finish()

    return user_id


def get_users():
    """Returns all users (without password hashes)."""
    db = get_connection()
    query = QSqlQuery(db)
    results = []
    if query.exec("SELECT user_id, username, last_login, doctor_id FROM users ORDER BY username ASC"):
        while query.next():
            results.append({
                "user_id": query.value(0),
                "username": query.value(1),
                "last_login": query.value(2),
                "doctor_id": query.value(3),
            })
    return results


def get_users_with_roles():
    """Returns all users plus their role names and explicit-override count.

    Batches the three lookups (users / roles / override counts) into three
    queries total, instead of ``get_user_roles`` + ``get_user_permissions`` per
    user (the N+1 the user-management table used to issue). Each item is a
    user dict with an extra ``roles`` list and ``override_count`` int.
    """
    db = get_connection()
    users = {}
    order = []

    query = QSqlQuery(db)
    if query.exec(
        "SELECT user_id, username, last_login, doctor_id FROM users ORDER BY username ASC"
    ):
        while query.next():
            uid = query.value(0)
            users[uid] = {
                "user_id": uid,
                "username": query.value(1),
                "last_login": query.value(2),
                "doctor_id": query.value(3),
                "roles": [],
                "override_count": 0,
            }
            order.append(uid)

    rq = QSqlQuery(db)
    if rq.exec(
        "SELECT ur.user_id, r.role_name FROM user_roles ur "
        "JOIN roles r ON ur.role_id = r.role_id"
    ):
        while rq.next():
            uid = rq.value(0)
            if uid in users:
                users[uid]["roles"].append(rq.value(1))

    oq = QSqlQuery(db)
    if oq.exec(
        "SELECT user_id, COUNT(*) FROM user_permissions "
        "WHERE override IN (0, 1) GROUP BY user_id"
    ):
        while oq.next():
            uid = oq.value(0)
            if uid in users:
                users[uid]["override_count"] = int(oq.value(1))

    return [users[uid] for uid in order]


def count_users_with_role(role_name):
    """Returns the number of distinct users holding *role_name*."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("""
        SELECT COUNT(DISTINCT ur.user_id)
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE r.role_name = ?
    """)
    query.addBindValue(role_name)
    if query.exec() and query.next():
        return int(query.value(0))
    return 0


def get_doctors():
    """Returns active doctors as ``doctor_id`` + ``doctor_name`` for selectors."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare(
        "SELECT doctor_id, first_name || ' ' || last_name FROM doctors "
        "WHERE is_active = 1 ORDER BY last_name, first_name"
    )
    results = []
    if query.exec():
        while query.next():
            results.append({
                "doctor_id": query.value(0),
                "doctor_name": query.value(1),
            })
    return results


def get_doctor_id(user):
    """Resolves the doctor ID associated with an authenticated user."""
    if not user:
        return None
    if user.get("doctor_id") is not None:
        return user["doctor_id"]

    user_id = user.get("user_id")
    if user_id is None:
        return None
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT doctor_id FROM users WHERE user_id = ?")
    query.addBindValue(user_id)
    if query.exec() and query.next():
        return query.value(0)
    return None


def update_user_doctor(user_id, doctor_id):
    """Links/clears a user's provider entry (used by seed admin/doctor accounts)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("UPDATE users SET doctor_id = ? WHERE user_id = ?")
    query.addBindValue(doctor_id)
    query.addBindValue(user_id)
    return query.exec()


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
    if query.exec("SELECT role_id, role_name, description, is_system FROM roles ORDER BY role_name ASC"):
        while query.next():
            results.append({
                "role_id": query.value(0),
                "role_name": query.value(1),
                "description": query.value(2),
                "is_system": bool(query.value(3)),
            })
    return results


def get_user_by_username(username):
    """Returns user info dict for a given username, or None if not found.

    Used for Remember-Me auto-login to verify the saved user still exists.

    Returns:
        dict with user_id, username, roles on success, None on failure.
    """
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT user_id, username FROM users WHERE username = ?")
    query.addBindValue(username)
    if query.exec() and query.next():
        user = {
            "user_id": query.value(0),
            "username": query.value(1),
        }
        user["roles"] = get_user_roles(user["user_id"])
        _attach_permissions(user)
        return user
    return None


def update_user_password(user_id, new_password):
    """Updates a user's password to the secure PBKDF2 scheme."""
    db = get_connection()
    user = None
    q = QSqlQuery(db)
    q.prepare("SELECT username FROM users WHERE user_id = ?")
    q.addBindValue(user_id)
    if q.exec() and q.next():
        pw_hash = hash_secure(new_password)

        up = QSqlQuery(db)
        up.prepare("UPDATE users SET password_hash = ?, salt = NULL WHERE user_id = ?")
        up.addBindValue(pw_hash)
        up.addBindValue(user_id)
        return up.exec()
    return False


def rename_user(user_id, new_username):
    """Renames a user's username. Returns True on success, None if the new
    username is already taken, False on other failures."""
    db = get_connection()
    check = QSqlQuery(db)
    check.prepare("SELECT 1 FROM users WHERE username = ? AND user_id != ?")
    check.addBindValue(new_username)
    check.addBindValue(user_id)
    if check.exec() and check.next():
        return None
    q = QSqlQuery(db)
    q.prepare("UPDATE users SET username = ? WHERE user_id = ?")
    q.addBindValue(new_username)
    q.addBindValue(user_id)
    return q.exec()


def get_user_by_id(user_id):
    """Returns user dict (with roles) by user_id, or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT user_id, username, last_login FROM users WHERE user_id = ?")
    query.addBindValue(user_id)
    if query.exec() and query.next():
        user = {
            "user_id": query.value(0),
            "username": query.value(1),
            "last_login": query.value(2),
        }
        user["roles"] = get_user_roles(user["user_id"])
        _attach_permissions(user)
        return user
    return None


def assign_role(user_id, role_name):
    """Assigns a role to a user if not already assigned."""
    db = get_connection()
    rq = QSqlQuery(db)
    rq.prepare("SELECT role_id FROM roles WHERE role_name = ?")
    rq.addBindValue(role_name)
    if not (rq.exec() and rq.next()):
        return False
    role_id = rq.value(0)
    
    # Check if already assigned
    cq = QSqlQuery(db)
    cq.prepare("SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = ?")
    cq.addBindValue(user_id)
    cq.addBindValue(role_id)
    if cq.exec() and cq.next():
        return True
        
    ins = QSqlQuery(db)
    ins.prepare("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)")
    ins.addBindValue(user_id)
    ins.addBindValue(role_id)
    return ins.exec()


def remove_role(user_id, role_name):
    """Removes a role from a user."""
    db = get_connection()
    rq = QSqlQuery(db)
    rq.prepare("SELECT role_id FROM roles WHERE role_name = ?")
    rq.addBindValue(role_name)
    if not (rq.exec() and rq.next()):
        return False
    role_id = rq.value(0)
    
    del_q = QSqlQuery(db)
    del_q.prepare("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?")
    del_q.addBindValue(user_id)
    del_q.addBindValue(role_id)
    return del_q.exec()


def delete_user(user_id):
    """Deletes a user by ID."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("DELETE FROM users WHERE user_id = ?")
    query.addBindValue(user_id)
    return query.exec()


# ---------------------------------------------------------------------------
# RBAC: role templates + per-user permission overrides
# ---------------------------------------------------------------------------

def get_role_by_name(role_name):
    """Returns a role dict (with permissions) by name, or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT role_id, role_name, description, is_system FROM roles WHERE role_name = ?")
    query.addBindValue(role_name)
    if query.exec() and query.next():
        role = {
            "role_id": query.value(0),
            "role_name": query.value(1),
            "description": query.value(2),
            "is_system": bool(query.value(3)),
        }
        role["permissions"] = get_role_permissions(role["role_id"])
        return role
    return None


def get_role_by_id(role_id):
    """Returns a role dict (with permissions) by id, or None."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT role_id, role_name, description, is_system FROM roles WHERE role_id = ?")
    query.addBindValue(role_id)
    if query.exec() and query.next():
        role = {
            "role_id": query.value(0),
            "role_name": query.value(1),
            "description": query.value(2),
            "is_system": bool(query.value(3)),
        }
        role["permissions"] = get_role_permissions(role["role_id"])
        return role
    return None


def get_role_permissions(role_id):
    """Returns the set of permission keys granted by a role."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT permission_key FROM role_permissions WHERE role_id = ?")
    query.addBindValue(role_id)
    keys = set()
    if query.exec():
        while query.next():
            keys.add(query.value(0))
    return keys


def add_role(role_name, description="", permissions=None):
    """Creates a new custom role.

    Returns the new role_id on success, None if the name is taken, False on
    other failures. Custom roles start with the supplied permission set (an
    iterable of permission keys); anything with ``manage_users`` is forbidden
    from being assigned a permission set that could escalate beyond intent.
    """
    db = get_connection()
    name = str(role_name or "").strip()
    if not name:
        return False

    check = QSqlQuery(db)
    check.prepare("SELECT 1 FROM roles WHERE role_name = ?")
    check.addBindValue(name)
    if check.exec() and check.next():
        return None

    q = QSqlQuery(db)
    q.prepare("INSERT INTO roles (role_name, description, is_system) VALUES (?, ?, 0)")
    q.addBindValue(name)
    q.addBindValue(description)
    if not q.exec():
        logger.error(f"Failed to add role '{name}': {q.lastError().text()}")
        return False

    role_id = q.lastInsertId()
    if permissions:
        set_role_permissions(role_id, set(permissions))
    return role_id


def rename_role(role_id, new_name):
    """Renames a role. Returns True on success, None if name taken, False on
    failure. System roles may not be renamed."""
    db = get_connection()
    name = str(new_name or "").strip()
    if not name:
        return False

    sys_check = QSqlQuery(db)
    sys_check.prepare("SELECT is_system FROM roles WHERE role_id = ?")
    sys_check.addBindValue(role_id)
    if sys_check.exec() and sys_check.next() and bool(sys_check.value(0)):
        return False

    check = QSqlQuery(db)
    check.prepare("SELECT 1 FROM roles WHERE role_name = ? AND role_id != ?")
    check.addBindValue(name)
    check.addBindValue(role_id)
    if check.exec() and check.next():
        return None

    q = QSqlQuery(db)
    q.prepare("UPDATE roles SET role_name = ? WHERE role_id = ?")
    q.addBindValue(name)
    q.addBindValue(role_id)
    return q.exec()


def update_role_description(role_id, description):
    """Updates a role's description."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("UPDATE roles SET description = ? WHERE role_id = ?")
    q.addBindValue(description)
    q.addBindValue(role_id)
    return q.exec()


def delete_role(role_id):
    """Deletes a custom role (system roles are protected), removing its
    permissions and user associations. Returns False if protected."""
    db = get_connection()
    sys_check = QSqlQuery(db)
    sys_check.prepare("SELECT is_system FROM roles WHERE role_id = ?")
    sys_check.addBindValue(role_id)
    if sys_check.exec() and sys_check.next() and bool(sys_check.value(0)):
        return False
    q = QSqlQuery(db)
    q.prepare("DELETE FROM roles WHERE role_id = ?")
    q.addBindValue(role_id)
    ok = q.exec()
    return ok


def set_role_permissions(role_id, permission_keys):
    """Replaces a role's permission set with *permission_keys* (an iterable of
    permission keys). Built-in roles are editable templates too; the admin role
    cannot be locked out of its core controls at resolution time anyway."""
    target = set(permission_keys)
    db = get_connection()

    existing = QSqlQuery(db)
    existing.prepare("SELECT permission_key FROM role_permissions WHERE role_id = ?")
    existing.addBindValue(role_id)
    have = set()
    if existing.exec():
        while existing.next():
            have.add(existing.value(0))

    for key in have - target:
        dq = QSqlQuery(db)
        dq.prepare("DELETE FROM role_permissions WHERE role_id = ? AND permission_key = ?")
        dq.addBindValue(role_id)
        dq.addBindValue(key)
        dq.exec()
    for key in target - have:
        iq = QSqlQuery(db)
        iq.prepare("INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?, ?)")
        iq.addBindValue(role_id)
        iq.addBindValue(key)
        iq.exec()
    return True


def get_user_permissions(user_id):
    """Returns {permission_key: override} for a user (only rows that exist).
    override is -1 (inherit), 0 (deny) or 1 (allow)."""
    db = get_connection()
    query = QSqlQuery(db)
    query.prepare("SELECT permission_key, override FROM user_permissions WHERE user_id = ?")
    query.addBindValue(user_id)
    overrides = {}
    if query.exec():
        while query.next():
            overrides[query.value(0)] = int(query.value(1))
    return overrides


def set_user_permissions(user_id, overrides):
    """Replaces a user's permission overrides.

    *overrides* is a dict mapping permission_key -> -1/0/1. Rows with -1
    (inherit) are removed (they carry no explicit override).
    """
    from src.core.permissions import ALL_ACTIONS
    db = get_connection()
    clean = {}
    for key, val in overrides.items():
        if key in ALL_ACTIONS:
            try:
                ival = int(val)
            except (TypeError, ValueError):
                ival = -1
            if ival in (-1, 0, 1):
                clean[key] = ival

    has_rows = QSqlQuery(db)
    has_rows.prepare("SELECT 1 FROM user_permissions WHERE user_id = ? LIMIT 1")
    has_rows.addBindValue(user_id)
    if has_rows.exec() and has_rows.next():
        del_q = QSqlQuery(db)
        del_q.prepare("DELETE FROM user_permissions WHERE user_id = ?")
        del_q.addBindValue(user_id)
        del_q.exec()

    for key, val in clean.items():
        if val == -1:
            continue
        iq = QSqlQuery(db)
        iq.prepare(
            "INSERT INTO user_permissions (user_id, permission_key, override) VALUES (?, ?, ?)"
        )
        iq.addBindValue(user_id)
        iq.addBindValue(key)
        iq.addBindValue(val)
        iq.exec()


def clear_user_permissions(user_id):
    """Removes all permission overrides for a user (inherit everything)."""
    db = get_connection()
    q = QSqlQuery(db)
    q.prepare("DELETE FROM user_permissions WHERE user_id = ?")
    q.addBindValue(user_id)
    return q.exec()


def get_role_permissions_by_name(role_name):
    """Returns the permission-key set for a role given its name."""
    role = get_role_by_name(role_name)
    if role:
        return role.get("permissions") or set()
    return set()


def _attach_permissions(user):
    """Attaches cached role templates + per-user overrides to a user dict that
    already has ``user_id`` and ``roles`` populated. Called on login/user load."""
    if not user or user.get("user_id") is None:
        return

    role_actions = set()
    for role_name in user.get("roles", []):
        role_actions |= get_role_permissions_by_name(role_name)
    user["_role_permissions"] = role_actions
    user["_permissions"] = get_user_permissions(user["user_id"])
