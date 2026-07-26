"""
Default seed data module for the PET Application.
Inserts default lookup data for new installations.
"""

import hashlib
import logging

from PyQt5.QtSql import QSqlQuery

logger = logging.getLogger(__name__)


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
    admin_pw = hashlib.sha256("admin123".encode()).hexdigest()
    q = QSqlQuery(db)
    q.prepare("INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)")
    q.addBindValue("admin")
    q.addBindValue(admin_pw)
    q.exec()

    # Default role
    q = QSqlQuery(db)
    q.prepare("INSERT OR IGNORE INTO roles (role_name) VALUES ('admin')")
    q.exec()
    q = QSqlQuery(db)
    q.prepare("INSERT OR IGNORE INTO roles (role_name) VALUES ('staff')")
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
                   "followup_status": ["Scheduled", "Completed", "Missed"]}
    for cat_name, state_list in states_data.items():
        cq = QSqlQuery(db)
        cq.prepare("INSERT OR IGNORE INTO categories_lookup (category_name) VALUES (?)")
        cq.addBindValue(cat_name)
        if cq.exec():
            cat_id = cq.lastInsertId()
            # Need to get the actual category_id
            cg = QSqlQuery(db)
            cg.prepare("SELECT category_id FROM categories_lookup WHERE category_name = ?")
            cg.addBindValue(cat_name)
            if cg.exec() and cg.next():
                cat_id = cg.value(0)
                for sv in state_list:
                    sq = QSqlQuery(db)
                    sq.prepare("INSERT OR IGNORE INTO states_lookup (category_id, state_value) VALUES (?, ?)")
                    sq.addBindValue(cat_id)
                    sq.addBindValue(sv)
                    sq.exec()

    logger.info("Default lookup data populated")
