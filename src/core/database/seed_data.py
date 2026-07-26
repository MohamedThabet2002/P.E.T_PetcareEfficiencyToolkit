"""
Default seed data module for the PET Application.

Inserts default lookup data and roles for new installations.
This module is run automatically on first launch (first-run flow).
It is NOT intended for demo/test data population — use the root ``seed.py``
for that purpose.
"""

import logging

from PyQt5.QtSql import QSqlQuery

logger = logging.getLogger(__name__)

# The statuses the UI writes for a follow-up (the same vocabulary appointments
# use). Databases seeded before a status was added here are backfilled by
# migration 019_followup_status_states; statuses that have since been retired
# ("Scheduled", "Missed") are pruned by 020_followup_status_prune.
FOLLOWUP_STATUS_STATES = ("Pending", "Completed", "Canceled")
FOLLOWUP_STATUS_RETIRED = ("Scheduled", "Missed")


def ensure_lookup_category(db, category_name):
    """Returns the category_id of a lookup category, inserting it when absent.

    ``categories_lookup`` has no UNIQUE index on ``category_name``, so
    ``INSERT OR IGNORE`` would create a duplicate row on every re-run — look
    the category up first instead.
    """
    query = QSqlQuery(db)
    query.prepare("SELECT category_id FROM categories_lookup WHERE category_name = ?")
    query.addBindValue(category_name)
    if query.exec() and query.next():
        return query.value(0)
    query = QSqlQuery(db)
    query.prepare("INSERT INTO categories_lookup (category_name) VALUES (?)")
    query.addBindValue(category_name)
    if query.exec():
        return query.lastInsertId()
    logger.warning("Failed to insert lookup category '%s': %s",
                   category_name, query.lastError().text())
    return None


def ensure_lookup_states(db, category_name, state_values):
    """Inserts the *state_values* missing from a states_lookup category.

    ``states_lookup`` has no UNIQUE(category_id, state_value) index either, so
    each value is checked before insertion. Safe to call repeatedly; also used
    by the follow-up status backfill migration.
    """
    category_id = ensure_lookup_category(db, category_name)
    if category_id is None:
        return
    for state_value in state_values:
        query = QSqlQuery(db)
        query.prepare("SELECT state_id FROM states_lookup WHERE category_id = ? AND state_value = ?")
        query.addBindValue(category_id)
        query.addBindValue(state_value)
        if query.exec() and query.next():
            continue
        query = QSqlQuery(db)
        query.prepare("INSERT INTO states_lookup (category_id, state_value) VALUES (?, ?)")
        query.addBindValue(category_id)
        query.addBindValue(state_value)
        if query.exec():
            logger.info("Added '%s' state to '%s' lookup", state_value, category_name)
        else:
            logger.warning("Failed to add '%s' state to '%s' lookup: %s",
                           state_value, category_name, query.lastError().text())


def populate_default_lookup_data(db):
    """Insert default lookup data for new installations."""
    query = QSqlQuery(db)

    # Species
    species = ["Dog", "Cat", "Bird", "Rabbit", "Hamster", "Guinea Pig", "Fish", "Reptile"]
    for s in species:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO species_lookup (species_name) VALUES (?)")
        q.addBindValue(s)
        q.exec()

    # Breeds for Dogs
    dog_breeds = [
        "Labrador Retriever", "German Shepherd", "Golden Retriever", "Bulldog",
        "Poodle", "Beagle", "Rottweiler", "Yorkshire Terrier", "Dachshund",
        "Shih Tzu", "Husky", "Border Collie", "Cocker Spaniel", "Boxer",
        "Chihuahua", "Doberman", "Other"
    ]
    sq_dog = QSqlQuery(db)
    sq_dog.prepare("SELECT species_id FROM species_lookup WHERE species_name = 'Dog'")
    if sq_dog.exec() and sq_dog.next():
        dog_id = sq_dog.value(0)
        for b in dog_breeds:
            q = QSqlQuery(db)
            q.prepare("INSERT OR IGNORE INTO breeds_lookup (species_id, breed_name) VALUES (?, ?)")
            q.addBindValue(dog_id)
            q.addBindValue(b)
            q.exec()

    # Breeds for Cats
    cat_breeds = [
        "Persian", "Siamese", "Maine Coon", "Bengal", "Sphynx",
        "Ragdoll", "Scottish Fold", "British Shorthair", "Abyssinian",
        "Birman", "Oriental", "Other"
    ]
    sq_cat = QSqlQuery(db)
    sq_cat.prepare("SELECT species_id FROM species_lookup WHERE species_name = 'Cat'")
    if sq_cat.exec() and sq_cat.next():
        cat_id = sq_cat.value(0)
        for b in cat_breeds:
            q = QSqlQuery(db)
            q.prepare("INSERT OR IGNORE INTO breeds_lookup (species_id, breed_name) VALUES (?, ?)")
            q.addBindValue(cat_id)
            q.addBindValue(b)
            q.exec()

    # Services
    services = [
        ("Consultation", "medical", 50.0),
        ("Vaccination", "medical", 30.0),
        ("Check-up", "medical", 40.0),
        ("Surgery", "surgical", 200.0),
        ("Dental Cleaning", "medical", 80.0),
        ("Grooming", "grooming", 35.0),
        ("Microchipping", "medical", 25.0),
        ("Blood Test", "lab", 45.0),
        ("X-Ray", "lab", 60.0),
        ("Follow-up", "medical", 30.0),
    ]
    for name, stype, price in services:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO services_lookup (service_name, service_type, base_price) VALUES (?, ?, ?)")
        q.addBindValue(name)
        q.addBindValue(stype)
        q.addBindValue(price)
        q.exec()

    # Tests
    tests = ["Blood Test", "Urinalysis", "Fecal Exam", "Heartworm Test", "Allergy Test",
             "Skin Scrape", "Ear Swab", "X-Ray", "Ultrasound", "MRI"]
    for t in tests:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO tests_lookup (test_name) VALUES (?)")
        q.addBindValue(t)
        q.exec()

    # Treatments
    treatments = ["Antibiotic Therapy", "Fluid Therapy", "Wound Care", "Physical Therapy",
                  "Dietary Management", "Parasite Treatment", "Pain Management"]
    for t in treatments:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO treatments_lookup (treatment_name) VALUES (?)")
        q.addBindValue(t)
        q.exec()

    # Vaccines
    vaccines = ["Rabies", "DHPP", "FVRCP", "Bordetella", "Leptospirosis",
                "Canine Influenza", "Feline Leukemia", "Heartworm Prevention"]
    for v in vaccines:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO vaccines_lookup (vaccine_name) VALUES (?)")
        q.addBindValue(v)
        q.exec()

    # Log types
    log_types = ["CREATE", "UPDATE", "DELETE", "LOGIN", "LOGOUT", "PRINT", "EXPORT"]
    for lt in log_types:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO log_types_lookup (log_action) VALUES (?)")
        q.addBindValue(lt)
        q.exec()

    # Default admin user
    # ⚠️  SECURITY: The password 'admin123' is a placeholder for first-run setup.
    # The first-run dialog should force a password change before the app is used
    # in a real clinic environment. NEVER ship this password unchanged to production.
    #
    # Only create it on a brand-new install (empty users table). FirstRunDialog
    # deletes this stock account once the clinic sets up its own admin; the old
    # unconditional INSERT OR IGNORE re-created it every time any lookup table
    # was later emptied, silently reopening the well-known admin/admin123 login.
    users_query = QSqlQuery(db)
    users_empty = bool(
        users_query.exec("SELECT COUNT(*) FROM users")
        and users_query.next()
        and (users_query.value(0) or 0) == 0
    )
    users_query.finish()
    if users_empty:
        from src.core.repositories.user_repo import hash_secure
        admin_pw = hash_secure("admin123")
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)")
        q.addBindValue("admin")
        q.addBindValue(admin_pw)
        q.exec()

    # Default roles: admin (full access), doctor (clinical, own visits), staff (general)
    for role_name in ("admin", "staff", "doctor"):
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO roles (role_name) VALUES (?)")
        q.addBindValue(role_name)
        q.exec()

    # Assign admin role to admin user
    uq = QSqlQuery(db)
    uq.prepare("SELECT user_id FROM users WHERE username = 'admin'")
    if uq.exec() and uq.next():
        uid = uq.value(0)
        rq = QSqlQuery(db)
        rq.prepare("SELECT role_id FROM roles WHERE role_name = 'admin'")
        if rq.exec() and rq.next():
            rid = rq.value(0)
            ur = QSqlQuery(db)
            ur.prepare("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)")
            ur.addBindValue(uid)
            ur.addBindValue(rid)
            ur.exec()

    # Default systems for health stats
    systems = ["Temperature", "Weight", "Heart Rate", "Respiratory Rate"]
    for sys_name in systems:
        q = QSqlQuery(db)
        q.prepare("INSERT OR IGNORE INTO systems_lookup (system_name) VALUES (?)")
        q.addBindValue(sys_name)
        q.exec()

    # Default stat types
    sq_sys = QSqlQuery(db)
    sq_sys.prepare("SELECT system_id FROM systems_lookup WHERE system_name = 'Temperature'")
    if sq_sys.exec() and sq_sys.next():
        tid = sq_sys.value(0)
        tq = QSqlQuery(db)
        tq.prepare("INSERT OR IGNORE INTO stat_types_lookup (system_id, stat_name) VALUES (?, 'Normal')")
        tq.addBindValue(tid)
        tq.exec()
        tq = QSqlQuery(db)
        tq.prepare("INSERT OR IGNORE INTO stat_types_lookup (system_id, stat_name) VALUES (?, 'Elevated')")
        tq.addBindValue(tid)
        tq.exec()
        tq = QSqlQuery(db)
        tq.prepare("INSERT OR IGNORE INTO stat_types_lookup (system_id, stat_name) VALUES (?, 'Low')")
        tq.addBindValue(tid)
        tq.exec()

    # Default states
    states_data = {"visit_reason": ["Routine Check", "Sick Visit", "Follow-up", "Emergency", "Vaccination"],
                   "test_result": ["Normal", "Abnormal", "Pending"],
                   "followup_status": list(FOLLOWUP_STATUS_STATES)}
    for cat_name, state_list in states_data.items():
        ensure_lookup_states(db, cat_name, state_list)

    logger.info("Default lookup data populated")
