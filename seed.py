"""
Seed the PET clinic database with realistic test data.

Usage:
    python seed.py           # seed if no sample clients exist
    python seed.py --force   # wipe transactional data and reseed

All dates fall within August – December 2026 and are anchored relative to the
current date so that the app's dashboard (which splits records into 'recent
past' vs 'upcoming' against today's time) populates correctly. Every dated
record uses the consistent ``YYYY-MM-DD HH:mm`` format. Lookup defaults
(species, services, admin user, etc.) are applied automatically by schema
migrations. This script adds sample clients, pets, appointments, visits,
inventory, standalone retail receipts, and general expenses.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtSql import QSqlQuery

from src.core.database import get_connection, get_user_db_path
from src.core.repositories import (
    appointment_repo,
    client_repo,
    followup_repo,
    package_repo,
    payment_repo,
    pet_repo,
    sales_repo,
    stock_repo,
    supplier_repo,
    supply_repo,
    user_repo,
    visit_repo,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("seed")

# Marker used to detect whether sample data is already present.
SAMPLE_OWNER = "Ahmed Hassan"

# Fixed reference date so every seed run produces the same Aug-Dec 2026 window.
SEED_BASE = date(2026, 9, 15)

# Hard clamp so every generated date stays within August - December 2026.
WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 12, 31)

# Consistent timestamp format used everywhere (matches UI DATE_TIME_FORMAT_UI).
STAMP = "%Y-%m-%d %H:%M"


def _clamp(d):
    """Clamp a date to the Aug-Dec 2026 window, returning a date."""
    if d < WINDOW_START:
        return WINDOW_START
    if d > WINDOW_END:
        return WINDOW_END
    return d


def _dt(offset_base, day_offset, hour, minute=0):
    """Return a 'YYYY-MM-DD HH:mm' string clamped inside the Aug-Dec 2026 window."""
    target = _clamp(offset_base + timedelta(days=day_offset))
    return datetime.combine(target, datetime.min.time()).replace(
        hour=hour, minute=minute
    ).strftime(STAMP)

# ---------------------------------------------------------------------------
# Seed data constants
# ---------------------------------------------------------------------------

DOCTORS = [
    ("Sara", "Mahmoud", "General Practice", "01011112222", "sara.mahmoud@clinic.local"),
    ("Omar", "Khalil", "Surgery", "01022223333", "omar.khalil@clinic.local"),
    ("Lina", "Farid", "Dermatology", "01033334444", "lina.farid@clinic.local"),
]

CATEGORIES = {
    "Meds": ["Antibiotics", "Vaccines", "Painkillers", "Supplements", "Other"],
    "Food": ["Dry Food", "Wet Food", "Treats", "Prescription", "Other"],
    "Litter": ["Clumping", "Non-Clumping", "Silica", "Other"],
    "Tools": ["Surgical", "Grooming", "Diagnostic", "Office", "Other"],
}

SUPPLIERS = ["VetSupply Co", "PetMed Distributors", "Cairo Animal Care"]

# (item, category, sub, qty, buy, sell, expiry_days_from_base, reorder)
SUPPLIES = [
    ("Amoxicillin 250mg", "Meds", "Antibiotics", 64, 12.0, 25.0, 365, 20),
    ("Meloxicam 1.5mg", "Meds", "Painkillers", 38, 8.0, 18.0, 400, 15),
    ("Rabies Vaccine", "Meds", "Vaccines", 22, 40.0, 75.0, 180, 10),
    ("FVRCP Vaccine", "Meds", "Vaccines", 20, 35.0, 65.0, 200, 8),
    ("Omega-3 Capsules", "Meds", "Supplements", 54, 5.0, 12.0, 300, 15),
    ("Royal Canin Adult Dog 3kg", "Food", "Dry Food", 17, 90.0, 140.0, 240, 5),
    ("Hill's Wet Cat Food", "Food", "Wet Food", 42, 8.0, 15.0, 200, 12),
    ("Dental Chews", "Food", "Treats", 29, 6.0, 12.0, 365, 10),
    ("Clumping Cat Litter 10L", "Litter", "Clumping", 14, 25.0, 45.0, None, 6),
    ("Silica Litter 5L", "Litter", "Silica", 2, 30.0, 55.0, None, 5),
    ("Surgical Gloves Box", "Tools", "Surgical", 9, 40.0, 70.0, None, 4),
    ("Nail Clippers", "Tools", "Grooming", 7, 15.0, 35.0, None, 3),
    ("Digital Thermometer", "Tools", "Diagnostic", 0, 50.0, 95.0, None, 2),
    ("Dewormer Tablets", "Meds", "Other", 8, 10.0, 22.0, 60, 5),
    ("Ear Cleanser Solution", "Meds", "Other", 25, 7.0, 16.0, 365, 8),
]

# (owner_name, phone, [(pet_name, species, breed, gender, age_months, weight_kg)])
CLIENTS = [
    ("Ahmed Hassan", "01012345678", [
        ("Max", "Dog", "Labrador Retriever", "Male", 36, 28.5),
        ("Bella", "Dog", "Beagle", "Female", 18, 12.0),
    ]),
    ("Mona Ali", "01098765432", [
        ("Mimi", "Cat", "Persian", "Female", 24, 4.2),
        ("Simba", "Cat", "Maine Coon", "Male", 48, 7.8),
    ]),
    ("Youssef Ibrahim", "01155556666", [
        ("Rocky", "Dog", "German Shepherd", "Male", 60, 34.0),
    ]),
    ("Nour El-Din", "01233334444", [
        ("Kiwi", "Bird", "Other", "Female", 12, 0.35),
        ("Coco", "Rabbit", "Other", "Male", 10, 1.8),
    ]),
    ("Sara Adel", "01577778888", [
        ("Luna", "Cat", "Siamese", "Female", 30, 3.9),
        ("Thor", "Dog", "Husky", "Male", 20, 22.0),
    ]),
    ("Karim Nabil", "01044445555", [
        ("Buddy", "Dog", "Golden Retriever", "Male", 42, 30.0),
    ]),
    ("Layla Mansour", "01166667777", [
        ("Shadow", "Cat", "British Shorthair", "Male", 36, 5.5),
        ("Cleo", "Cat", "Ragdoll", "Female", 14, 3.2),
    ]),
    ("Tarek Ramadan", "01288889999", [
        ("Rex", "Dog", "Doberman", "Male", 48, 38.0),
    ]),
    ("Huda Kamal", "01544445555", [
        ("Snowball", "Cat", "Persian", "Female", 60, 4.8),
        ("Ziggy", "Cat", "Bengal", "Male", 24, 5.1),
    ]),
    ("Adel Farouk", "01022224444", [
        ("Charlie", "Dog", "Poodle", "Male", 30, 8.0),
        ("Daisy", "Dog", "Cocker Spaniel", "Female", 24, 11.5),
    ]),
]

# (owner_idx, pet_idx, days_offset, hour, status, service, notes, doctor_idx)
APPOINTMENTS = [
    (0, 0, -45, 10, "Completed", "Annual checkup", "Routine wellness exam", 0),
    (1, 0, -38, 14, "Completed", "Vaccination", "FVRCP booster due", 2),
    (2, 0, -30, 9, "Completed", "Surgery consult", "Pre-op evaluation", 1),
    (4, 1, -22, 11, "Completed", "Consultation", "Limping evaluation", 1),
    (6, 0, -15, 15, "Completed", "Dental cleaning", "Annual dental check", 0),
    (3, 0, -10, 12, "Canceled", "Wing clip", "Owner rescheduled", 0),
    (7, 0, -7, 10, "Completed", "Follow-up", "Post-surgery checkup", 1),
    # -3d stored as Pending but time has passed >24h → auto-cancels to "Canceled"
    (5, 0, -3, 9, "Pending", "Consultation", "No-show; auto-canceled", 2),
    # -1d stored as Pending; within the 24h late window → shows "Late"
    (8, 0, -1, 15, "Pending", "Follow-up", "Recheck bloodwork", 1),
    (0, 1, 0, 11, "Pending", "Vaccination", "Follow-up booster", 0),
    (1, 1, 2, 14, "Pending", "Consultation", "Skin irritation check", 2),
    (4, 0, 5, 9, "Pending", "Consultation", "Routine visit", 2),
    (8, 0, 8, 16, "Pending", "Follow-up", "Recheck bloodwork results", 0),
    (5, 0, 12, 17, "Pending", "Consultation", "Evening appointment", 0),
    (9, 0, 18, 10, "Pending", "Grooming consult", "Nail trim and coat check", 2),
    (9, 1, 20, 11, "Pending", "Vaccination", "Annual booster", 0),
    (6, 1, 25, 14, "Pending", "Consultation", "Kitten wellness visit", 0),
    (1, 0, 30, 9, "Pending", "Dental", "Teeth scaling", 1),
    (7, 0, 35, 10, "Pending", "Consultation", "Senior dog wellness", 0),
    (2, 0, 40, 15, "Pending", "Post-op review", "Second follow-up", 1),
    (3, 0, 45, 12, "Pending", "Consultation", "Feather checkup", 0),
    (8, 1, 50, 11, "Pending", "Consultation", "Weight monitoring", 2),
]

# (owner_idx, pet_idx, days_ago, reason, diagnosis, notes, temp, consult,
#  items, test_names, treatment_names, vaccine_names, followup_in_days)
VISIT_PLAN = [
    (
        0, 0, 45, "Routine Check", "Healthy", "Annual wellness visit; all vitals normal",
        38.5, True,
        [{"item_name": "Dental Chews", "quantity": 1}],
        ["Blood Test"],
        [],
        ["Rabies", "DHPP"],
        30,
    ),
    (
        1, 0, 38, "Sick Visit", "Mild gastroenteritis",
        "Vomiting and diarrhea for 2 days; started probiotics",
        39.2, True,
        [{"item_name": "Amoxicillin 250mg", "quantity": 1}],
        ["Fecal Exam"],
        ["Antibiotic Therapy", "Dietary Management"],
        [],
        7,
    ),
    (
        4, 1, 22, "Limping", "Mild sprain",
        "Right foreleg limping; x-ray clear",
        38.6, True,
        [{"item_name": "Meloxicam 1.5mg", "quantity": 1}],
        [],
        ["Pain Management"],
        [],
        14,
    ),
    (
        1, 1, 18, "Vaccination", "Up to date",
        "FVRCP booster administered; no adverse reaction",
        38.4, True,
        [],
        [],
        [],
        ["FVRCP"],
        None,
    ),
    (
        6, 0, 15, "Sick Visit", "Otitis externa",
        "Left ear inflamed with dark discharge; ear swab taken",
        38.8, True,
        [{"item_name": "Ear Cleanser Solution", "quantity": 1}],
        ["Ear Swab"],
        ["Pain Management"],
        [],
        5,
    ),
    (
        0, 1, 12, "Sick Visit", "Mild gastroenteritis",
        "Soft stool, appetite reduced; deworming recommended",
        39.0, True,
        [{"item_name": "Dewormer Tablets", "quantity": 1}],
        ["Fecal Exam"],
        ["Dietary Management"],
        [],
        10,
    ),
    (
        2, 0, 8, "Emergency", "Wound from dog fight",
        "Laceration on left flank; sutured and cleaned",
        39.5, True,
        [
            {"item_name": "Amoxicillin 250mg", "quantity": 2},
            {"item_name": "Surgical Gloves Box", "quantity": 1},
        ],
        ["Blood Test"],
        ["Wound Care", "Antibiotic Therapy", "Pain Management"],
        [],
        3,
    ),
    (
        4, 0, 5, "Follow-up", "Improving dermatitis",
        "Skin condition improving; continue medicated shampoo",
        38.6, True,
        [],
        ["Skin Scrape"],
        ["Parasite Treatment"],
        [],
        14,
    ),
    (
        5, 0, 3, "Check-up", "Healthy weight gain",
        "Weight on track; diet advice given",
        38.3, True,
        [{"item_name": "Royal Canin Adult Dog 3kg", "quantity": 1}],
        [],
        ["Dietary Management"],
        [],
        None,
    ),
    (
        8, 0, 1, "Vaccination", "Up to date",
        "Rabies booster administered; new certificate issued",
        38.7, True,
        [],
        [],
        [],
        ["Rabies"],
        365,
    ),
    (
        9, 0, 40, "Sick Visit", "Ear infection",
        "Both ears waxy; cleaning and medication prescribed",
        38.9, True,
        [{"item_name": "Ear Cleanser Solution", "quantity": 1}],
        ["Ear Swab"],
        ["Antibiotic Therapy"],
        [],
        7,
    ),
    (
        3, 1, 35, "Sick Visit", "GI upset",
        "Rabbit eating less; fecal sample examined",
        39.1, True,
        [],
        ["Fecal Exam"],
        ["Fluid Therapy"],
        [],
        4,
    ),
    (
        7, 0, 10, "Emergency", "Post-suture check",
        "Wound healing well; sutures removed",
        38.4, True,
        [],
        [],
        ["Wound Care"],
        [],
        None,
    ),
    (
        8, 1, 28, "Routine Check", "Healthy",
        "Annual wellness visit; vaccinations up to date",
        38.5, True,
        [],
        ["Blood Test"],
        [],
        ["FVRCP"],
        365,
    ),
    (
        6, 1, 20, "Sick Visit", "Upper respiratory infection",
        "Sneezing and nasal discharge; supportive care started",
        39.3, True,
        [{"item_name": "Omega-3 Capsules", "quantity": 1}],
        [],
        ["Antibiotic Therapy"],
        [],
        7,
    ),
    (
        9, 1, 15, "Check-up", "Healthy",
        "New puppy visit; deworming administered",
        38.4, True,
        [{"item_name": "Dewormer Tablets", "quantity": 1}],
        ["Fecal Exam"],
        ["Dietary Management"],
        [],
        30,
    ),
]

# Standalone retail receipts: (owner_idx, day_offset, items, receipt_code)
# items: [(item_name, qty)]
RETAIL_RECEIPTS = [
    (5, -20, [("Hill's Wet Cat Food", 2), ("Dental Chews", 3)], "RETAIL-001"),
    (9, -10, [("Royal Canin Adult Dog 3kg", 1)], "RETAIL-002"),
]

# General expenses: (day_offset, category, item_name, amount)
EXPENSES = [
    (-40, "Utilities", "Electricity bill", 1200.0),
    (-25, "Maintenance", "Clinic deep clean", 350.0),
    (-5, "Utilities", "Internet and phone", 450.0),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exec(db, sql, binds=None):
    q = QSqlQuery(db)
    q.prepare(sql)
    for value in binds or []:
        q.addBindValue(value)
    if not q.exec():
        raise RuntimeError(f"SQL failed: {q.lastError().text()}\n  {sql}")
    return q


def _scalar(db, sql, binds=None, default=None):
    q = _exec(db, sql, binds)
    if q.next():
        return q.value(0)
    return default


def _lookup_map(db, table, id_col, name_col):
    q = _exec(db, f"SELECT {id_col}, {name_col} FROM {table}")
    result = {}
    while q.next():
        result[str(q.value(1))] = q.value(0)
    return result


def _state_id(db, category_name, state_value):
    return _scalar(
        db,
        """
        SELECT s.state_id
        FROM states_lookup s
        JOIN categories_lookup c ON c.category_id = s.category_id
        WHERE c.category_name = ? AND s.state_value = ?
        """,
        [category_name, state_value],
    )


def _already_seeded(db):
    return bool(
        _scalar(
            db,
            "SELECT 1 FROM owners WHERE first_name = ? AND last_name = ? LIMIT 1",
            SAMPLE_OWNER.split(" ", 1),
        )
    )


def _clear_transactional_data(db):
    """Remove sample/clinic data while keeping lookup tables and the admin user."""
    logger.info("Clearing existing transactional data...")
    tables = [
        "receipt_adjustments",
        "receipt_other",
        "receipt_packages",
        "receipt_supplies",
        "receipt_services",
        "receipts",
        "payments",
        "stock_movements",
        "stocks",
        "package_items",
        "packages",
        "medications",
        "tests",
        "treatments",
        "vaccinations",
        "health_stats",
        "followups",
        "appointment_status_history",
        "appointments",
        "visits",
        "pets",
        "entity_contacts",
        "contacts",
        "owners",
        "supplies",
        "subcategories",
        "categories",
        "suppliers",
        "doctors",
        "sessions",
        "change_detail",
        "change_header",
        "logs",
        "user_roles",
        "users",
    ]
    for table in tables:
        _exec(db, f"DELETE FROM {table}")

    admin_hash = user_repo.hash_secure("admin")
    _exec(
        db,
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ["admin", admin_hash],
    )
    admin_id = _scalar(db, "SELECT user_id FROM users WHERE username = 'admin'")
    role_id = _scalar(db, "SELECT role_id FROM roles WHERE role_name = 'admin'")
    if admin_id and role_id:
        _exec(
            db,
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            [admin_id, role_id],
        )
    logger.info("Transactional data cleared; admin user restored.")


# ---------------------------------------------------------------------------
# Seed sections
# ---------------------------------------------------------------------------

def seed_users(doctor_ids):
    """Create the doctor/staff login accounts.

    The ``doctor`` account is linked to the first provider record so the app's
    doctor-scoped views (My Visits, dashboard) resolve it via ``users.doctor_id``.
    """
    logger.info("Seeding users...")
    db = get_connection()
    doctor_user_id = None
    staff_user_id = None
    for username, password, role in [
        ("doctor", "doctor", "doctor"),
        ("staff", "staff", "staff"),
    ]:
        existing = _scalar(
            db,
            "SELECT user_id FROM users WHERE username = ?",
            [username],
        )
        if existing:
            user_id = int(existing)
        else:
            user_id = int(user_repo.add_user(username, password, role_name=role))
        if username == "doctor":
            doctor_user_id = user_id
            if doctor_ids:
                user_repo.update_user_doctor(user_id, doctor_ids[0])
        elif username == "staff":
            staff_user_id = user_id
    return doctor_user_id, staff_user_id


def seed_doctors(db):
    logger.info("Seeding doctors...")
    ids = []
    for first, last, spec, phone, email in DOCTORS:
        existing = _scalar(
            db,
            """
            SELECT doctor_id FROM doctors
            WHERE first_name = ? AND last_name = ?
            """,
            [first, last],
        )
        if existing:
            ids.append(existing)
            continue
        q = _exec(
            db,
            """
            INSERT INTO doctors (first_name, last_name, specialization, phone, email, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            [first, last, spec, phone, email],
        )
        ids.append(q.lastInsertId())
    return ids


def seed_inventory(db):
    logger.info("Seeding inventory categories, suppliers, and supplies...")

    for cat, subs in CATEGORIES.items():
        supply_repo.add_category(cat)
        for sub in subs:
            supply_repo.add_subcategory(cat, sub)

    supplier_ids = []
    for name in SUPPLIERS:
        supplier_ids.append(supplier_repo.add_supplier(name))

    purchase_base = SEED_BASE - timedelta(days=14)

    supply_ids = {}
    for item, cat, sub, qty, buy, sell, expiry_days, reorder in SUPPLIES:
        expiry = (
            _clamp(SEED_BASE + timedelta(days=expiry_days)).isoformat()
            if expiry_days
            else None
        )
        purchase = _clamp(purchase_base).isoformat()
        supply_id, _ = supply_repo.add_supply(
            item_name=item,
            category=cat,
            sub_category=sub,
            purchase_date=purchase,
            expiry_date=expiry,
            buy_price=buy,
            sell_price=sell,
            quantity=qty,
            supplier="VetSupply Co",
        )
        if supply_id:
            _exec(
                db,
                "UPDATE supplies SET reorder_level = ? WHERE supply_id = ?",
                [reorder, supply_id],
            )
            if qty > 0 and supplier_ids:
                stock_repo.add_stock_batch(
                    supply_id,
                    supplier_ids[0],
                    purchase,
                    qty,
                    notes="Initial seed batch",
                )
            supply_ids[item] = supply_id

    services = _lookup_map(db, "services_lookup", "service_id", "service_name")

    pkg_checkup = package_repo.add_package(
        "Wellness Checkup",
        "Consultation + basic blood work package",
        85.0,
    )
    if pkg_checkup and "Consultation" in services:
        package_repo.add_package_item(
            pkg_checkup, service_id=services["Consultation"], quantity=1, item_type="service"
        )
    if pkg_checkup and "Blood Test" in services:
        package_repo.add_package_item(
            pkg_checkup, service_id=services["Blood Test"], quantity=1, item_type="service"
        )

    pkg_vax = package_repo.add_package(
        "Puppy Vaccine Bundle",
        "Consultation + rabies vaccine",
        110.0,
    )
    if pkg_vax and "Vaccination" in services:
        package_repo.add_package_item(
            pkg_vax, service_id=services["Vaccination"], quantity=1, item_type="service"
        )
    if pkg_vax and supply_ids.get("Rabies Vaccine"):
        package_repo.add_package_item(
            pkg_vax,
            supply_id=supply_ids["Rabies Vaccine"],
            quantity=1,
            item_type="supply",
        )

    return supply_ids


def seed_clients_and_pets(audit_user_id=None):
    logger.info("Seeding clients and pets...")
    owner_pets = []
    for owner_name, phone, pets in CLIENTS:
        owner_id = client_repo.add_client(owner_name, phone, audit_user_id=audit_user_id)
        pet_rows = []
        for pet_name, species, breed, gender, age, weight in pets:
            pet_id = pet_repo.add_pet(
                pet_name, species, breed, gender, age, weight, owner_id,
                audit_user_id=audit_user_id,
            )
            pet_rows.append((pet_id, pet_name))
        owner_pets.append((owner_id, owner_name, pet_rows))
    return owner_pets


def seed_appointments(db, owner_pets, doctor_ids, staff_user_id=None):
    logger.info("Seeding appointments...")
    today = date.today()
    for owner_idx, pet_idx, day_off, hour, status, service, notes, doc_idx in APPOINTMENTS:
        owner_id, _, pets = owner_pets[owner_idx]
        pet_id, _ = pets[pet_idx]
        when = _dt(today, day_off, hour)
        doctor_id = doctor_ids[doc_idx % len(doctor_ids)] if doctor_ids else None
        appointment_repo.add_appointment(
            when,
            service,
            status,
            notes,
            owner_id,
            pet_id,
            doctor_id=doctor_id,
            user_id=staff_user_id,
        )


def seed_visits_and_clinical(db, owner_pets, doctor_ids, supply_ids, doctor_user_id=None):
    logger.info("Seeding visits, clinical records, receipts, and follow-ups...")
    tests = _lookup_map(db, "tests_lookup", "test_id", "test_name")
    treatments = _lookup_map(db, "treatments_lookup", "treatment_id", "treatment_name")
    vaccines = _lookup_map(db, "vaccines_lookup", "vaccine_id", "vaccine_name")
    normal_result = _state_id(db, "test_result", "Normal")
    abnormal_result = _state_id(db, "test_result", "Abnormal")
    pending_fu = _state_id(db, "followup_status", "Pending")

    for idx, (
        owner_idx,
        pet_idx,
        days_ago,
        reason,
        diagnosis,
        notes,
        temp,
        consult,
        items,
        test_names,
        treatment_names,
        vaccine_names,
        followup_days,
    ) in enumerate(VISIT_PLAN, start=1):
        owner_id, _, pets = owner_pets[owner_idx]
        pet_id, _ = pets[pet_idx]
        today = date.today()
        visit_hour = 9 + (owner_idx % 8)  # spread consult hours across the day
        visit_date = _dt(today, -days_ago, visit_hour)

        test_payload = []
        for name in test_names:
            tid = tests.get(name)
            if tid:
                test_payload.append({
                    "test_id": tid,
                    "state_id": (
                        abnormal_result
                        if name in ("Ear Swab", "Skin Scrape")
                        else normal_result
                    ),
                })

        treatment_payload = [
            treatments[name] for name in treatment_names if name in treatments
        ]
        vaccine_payload = [
            vaccines[name] for name in vaccine_names if name in vaccines
        ]

        med_payload = []
        for item in items:
            sid = supply_ids.get(item["item_name"])
            if sid:
                med_payload.append({
                    "supply_id": sid,
                    "dosage": "as directed",
                    "instructions": "Take with food",
                })

        doctor_id = doctor_ids[owner_idx % len(doctor_ids)] if doctor_ids else None

        result = visit_repo.add_visit(
            visit_date=visit_date,
            diagnosis=diagnosis,
            consult=consult,
            notes=notes,
            pet_id=pet_id,
            items=items,
            client_id=owner_id,
            reason_for_visit=reason,
            temperature=temp,
            tests=test_payload or None,
            treatments=treatment_payload or None,
            vaccinations=vaccine_payload or None,
            medications=med_payload or None,
            doctor_id=doctor_id,
            audit_user_id=doctor_user_id,
            receipt_code=f"VISIT-{idx:04d}",
        )

        if isinstance(result, str) or result is None:
            logger.warning(
                "Visit seed skipped for pet %s on %s: %s",
                pet_id,
                visit_date,
                result,
            )
            continue

        visit_id = _scalar(
            db,
            """
            SELECT visit_id FROM visits
            WHERE pet_id = ? AND visit_date = ?
            ORDER BY visit_id DESC LIMIT 1
            """,
            [pet_id, visit_date],
        )
        if not visit_id:
            logger.warning("Could not resolve visit_id after insert for pet %s", pet_id)
            continue

        if followup_days is not None:
            fu_hour = 10 + (owner_idx % 7)
            followup_repo.add_followup(
                visit_id,
                _dt(today, -days_ago + followup_days, fu_hour),
                state_id=pending_fu,
                notes=f"Follow-up after {reason.lower()}",
                doctor_id=doctor_id,
            )


def seed_retail_receipts(db, owner_pets, supply_ids, staff_user_id=None):
    """Quick-purchase receipts not tied to a clinical visit.

    Routes through ``sales_repo.create_sale_receipt_for_quick_purchase`` (the
    app's Quick Purchase flow) so stock is deducted, receipts get their supply
    lines, and the sale is attributed to the staff user in the audit log.
    """
    logger.info("Seeding standalone retail receipts...")
    today = date.today()
    for owner_idx, day_off, items, receipt_code in RETAIL_RECEIPTS:
        owner_id = owner_pets[owner_idx][0]
        receipt_date = _dt(today, day_off, 15 + (owner_idx % 5))

        receipt_items = []
        for item_name, qty in items:
            sid = supply_ids.get(item_name)
            if not sid:
                continue
            sell_price = float(
                _scalar(
                    db,
                    "SELECT sell_price FROM supplies WHERE supply_id = ?",
                    [sid],
                    0.0,
                )
            )
            receipt_items.append({
                "item_name": item_name,
                "quantity": qty,
                "price": sell_price,
            })

        if not receipt_items:
            continue

        sales_repo.create_sale_receipt_for_quick_purchase(
            owner_id,
            receipt_date,
            receipt_items,
            user_id=staff_user_id,
            receipt_code=receipt_code,
        )


def seed_payments(db):
    """Record payments against seeded receipts.

    Older receipts are settled in full while recent ones stay open, so the
    ledger shows a realistic mix of Paid / Partial / Unpaid balances.
    """
    logger.info("Seeding payments...")
    q = _exec(
        db,
        """
        SELECT receipt_id, total_price, receipt_date
        FROM receipts
        WHERE receipt_code LIKE 'VISIT-%'
          OR receipt_code LIKE 'RETAIL-%'
        ORDER BY receipt_date ASC
        """,
    )
    rows = []
    while q.next():
        rows.append((q.value(0), float(q.value(1) or 0)))

    if not rows:
        return

    pay_full = max(1, len(rows) // 2)
    for i, (receipt_id, total) in enumerate(rows):
        if i < pay_full:
            payment_repo.add_payment(receipt_id, round(total, 2), "Cash", "Settled in full")
        elif i == pay_full and total > 4.0:
            payment_repo.add_payment(
                receipt_id, round(total * 0.6, 2), "Card", "Partial payment"
            )


def seed_expenses(db):
    """General clinic operating expenses.

    Inserts directly with unique ``EXPENSE-###`` codes (same pattern used by the
    other receipt seeding here) rather than going through
    ``sales_repo.add_general_expense``, so demo codes stay stable.
    """
    logger.info("Seeding general expenses...")
    today = date.today()
    for idx, (day_off, category, item_name, amount) in enumerate(EXPENSES, start=1):
        exp_date = _dt(today, day_off, 18)
        q = _exec(
            db,
            """
            INSERT INTO receipts (receipt_date, total_price, receipt_code, receipt_kind, notes)
            VALUES (?, ?, ?, 'expense', ?)
            """,
            [exp_date, amount, f"EXPENSE-{idx:03d}", "Seeded demo expense"],
        )
        receipt_id = q.lastInsertId()
        _exec(
            db,
            """
            INSERT INTO receipt_other (receipt_id, description, amount, category)
            VALUES (?, ?, ?, ?)
            """,
            [receipt_id, item_name, amount, category],
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_PROMPT = """
What would you like to do?

  [1] Wipe & Reseed   -- Delete all data, then seed fresh Aug-Dec 2026 data
  [2] Add on top      -- Keep existing data and seed additional records on top
  [3] Wipe only       -- Delete all data without seeding
  [q] Quit

  Enter choice: """


def _prompt_choice() -> str:
    """Ask the user what to do; returns 'wipe_reseed', 'add', 'wipe', or 'quit'."""
    while True:
        raw = input(_PROMPT).strip().lower()
        if raw in ("1", "wipe_reseed", "wipe & reseed", "wipe and reseed"):
            return "wipe_reseed"
        if raw in ("2", "add", "add on top", "override"):
            return "add"
        if raw in ("3", "wipe", "wipe only", "delete"):
            return "wipe"
        if raw in ("q", "quit", "exit", ""):
            return "quit"
        print("  Invalid choice. Please enter 1, 2, 3, or q.\n")


def _run_seed(db, owner_pets_db=None):
    """Execute all seed functions. Returns (owner_pets, doctor_ids, supply_ids)."""
    doctor_ids = seed_doctors(db)
    doctor_user_id, staff_user_id = seed_users(doctor_ids)

    if owner_pets_db is not None:
        owner_pets = owner_pets_db
        logger.info("Reusing existing clients/pets (add-on-top mode).")
    else:
        owner_pets = seed_clients_and_pets(audit_user_id=staff_user_id)

    supply_ids = seed_inventory(db)
    seed_appointments(db, owner_pets, doctor_ids, staff_user_id=staff_user_id)
    seed_visits_and_clinical(db, owner_pets, doctor_ids, supply_ids, doctor_user_id=doctor_user_id)
    seed_retail_receipts(db, owner_pets, supply_ids, staff_user_id=staff_user_id)
    seed_payments(db)
    seed_expenses(db)
    return owner_pets, doctor_ids, supply_ids


def _collect_existing_owner_pets(db):
    """Return owner_pets list from existing data for add-on-top mode."""
    owner_pets = []
    q = _exec(db, "SELECT owner_id, first_name, last_name FROM owners ORDER BY owner_id")
    while q.next():
        owner_id = q.value(0)
        full_name = f"{q.value(1)} {q.value(2)}"
        pq = _exec(
            db,
            "SELECT pet_id, pet_name FROM pets WHERE owner_id = ? ORDER BY pet_id",
            [owner_id],
        )
        pets = []
        while pq.next():
            pets.append((pq.value(0), pq.value(1)))
        owner_pets.append((owner_id, full_name, pets))
    return owner_pets


def main(force: bool = False, mode: str | None = None) -> int:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)

    db_path = get_user_db_path()
    logger.info("Using database: %s", db_path)
    logger.info("Seeding data within Aug-Dec 2026 (anchored to today: %s).", date.today().isoformat())

    db = get_connection()
    if not db.isOpen():
        logger.error("Could not open database.")
        return 1

    # --- Resolve mode ---------------------------------------------------
    if mode is None:
        if force:
            mode = "wipe_reseed"
        elif not _already_seeded(db):
            mode = "wipe_reseed"
        else:
            mode = _prompt_choice()

    if mode == "quit":
        logger.info("Aborted by user.")
        return 0

    # --- Execute chosen mode --------------------------------------------
    if mode == "wipe_reseed":
        _clear_transactional_data(db)

    elif mode == "wipe":
        _clear_transactional_data(db)
        logger.info("Data wiped. No new seed data added.")
        return 0

    elif mode == "add":
        if not _already_seeded(db):
            logger.info("No existing data found; proceeding with full seed.")
        else:
            logger.info("Existing data detected; adding new records on top.")

    try:
        if mode == "add" and _already_seeded(db):
            existing_owner_pets = _collect_existing_owner_pets(db)
            _run_seed(db, owner_pets_db=existing_owner_pets)
        else:
            _run_seed(db)
    except Exception:
        logger.exception("Seeding failed.")
        return 1

    counts = {
        "owners": _scalar(db, "SELECT COUNT(*) FROM owners", default=0),
        "pets": _scalar(db, "SELECT COUNT(*) FROM pets", default=0),
        "appointments": _scalar(db, "SELECT COUNT(*) FROM appointments", default=0),
        "visits": _scalar(db, "SELECT COUNT(*) FROM visits", default=0),
        "supplies": _scalar(db, "SELECT COUNT(*) FROM supplies", default=0),
        "receipts": _scalar(db, "SELECT COUNT(*) FROM receipts", default=0),
        "doctors": _scalar(db, "SELECT COUNT(*) FROM doctors", default=0),
        "users": _scalar(db, "SELECT COUNT(*) FROM users", default=0),
    }
    logger.info("Seed complete: %s", counts)
    logger.info(
        "Login: admin / admin  |  doctor / doctor  |  staff / staff"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed PET database with test data")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Non-interactive shortcut: wipe data and reseed (equivalent to choosing 1)",
    )
    parser.add_argument(
        "--mode",
        choices=["wipe_reseed", "add", "wipe"],
        default=None,
        help="Non-interactive mode: wipe_reseed | add | wipe",
    )
    args = parser.parse_args()
    sys.exit(main(force=args.force, mode=args.mode))
