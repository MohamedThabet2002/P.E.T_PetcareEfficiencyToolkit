"""
SQL schema definitions for the PET Application.
Contains table and view SQL string definitions.
"""

# --- 1. Lookup Tables ---
lookup_tables = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories_lookup (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        category_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS states_lookup (
        state_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        state_value TEXT NOT NULL,
        FOREIGN KEY(category_id) REFERENCES categories_lookup(category_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS systems_lookup (
        system_id INTEGER PRIMARY KEY AUTOINCREMENT,
        system_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stat_types_lookup (
        stat_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
        system_id INTEGER NOT NULL,
        stat_name TEXT NOT NULL,
        FOREIGN KEY(system_id) REFERENCES systems_lookup(system_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS species_lookup (
        species_id INTEGER PRIMARY KEY AUTOINCREMENT,
        species_name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS breeds_lookup (
        breed_id INTEGER PRIMARY KEY AUTOINCREMENT,
        species_id INTEGER NOT NULL,
        breed_name TEXT NOT NULL,
        FOREIGN KEY(species_id) REFERENCES species_lookup(species_id) ON DELETE CASCADE,
        UNIQUE(breed_name, species_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS services_lookup (
        service_id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT NOT NULL UNIQUE,
        service_type TEXT,
        base_price REAL,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tests_lookup (
        test_id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS treatments_lookup (
        treatment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        treatment_name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vaccines_lookup (
        vaccine_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vaccine_name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS log_types_lookup (
        log_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_action TEXT NOT NULL UNIQUE
    )
    """,
]

# --- 2. Core Tables ---
core_tables = [
    """
    CREATE TABLE IF NOT EXISTS owners (
        owner_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contacts (
        contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT,
        address TEXT,
        contact_type TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_contacts (
        entity_contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT,
        entity_id INTEGER NOT NULL,
        contact_id INTEGER NOT NULL,
        FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pets (
        pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        pet_name TEXT NOT NULL,
        species_id INTEGER,
        breed_id INTEGER,
        gender TEXT,
        age_in_months INTEGER,
        weight_in_kg REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(owner_id) REFERENCES owners(owner_id) ON DELETE CASCADE,
        FOREIGN KEY(species_id) REFERENCES species_lookup(species_id) ON DELETE SET NULL,
        FOREIGN KEY(breed_id) REFERENCES breeds_lookup(breed_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS appointments (
        appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_id INTEGER NOT NULL,
        doctor_id INTEGER,
        appointment_date TEXT NOT NULL,
        service TEXT,
        status TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS appointment_status_history (
        status_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        user_id INTEGER,
        status TEXT NOT NULL,
        changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(appointment_id) REFERENCES appointments(appointment_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_id INTEGER NOT NULL,
        doctor_id INTEGER,
        appointment_id INTEGER,
        visit_date TEXT NOT NULL,
        reason_for_visit TEXT,
        temperature_in_c REAL,
        temperature_status_id INTEGER,
        weight_status_id INTEGER,
        diagnosis TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE,
        FOREIGN KEY(appointment_id) REFERENCES appointments(appointment_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS followups (
        followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        doctor_id INTEGER,
        followup_date TEXT NOT NULL,
        state_id INTEGER,
        notes TEXT,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS health_stats (
        health_stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_id INTEGER NOT NULL,
        visit_id INTEGER,
        stat_type_id INTEGER,
        state_id INTEGER,
        extra_note TEXT,
        FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS medications (
        medication_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        supply_id INTEGER,
        dosage TEXT,
        instructions TEXT,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE,
        FOREIGN KEY(supply_id) REFERENCES supplies(supply_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tests (
        routine_test_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        test_id INTEGER,
        state_id INTEGER,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE,
        FOREIGN KEY(test_id) REFERENCES tests_lookup(test_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS treatments (
        treatment_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        treatment_id INTEGER,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE,
        FOREIGN KEY(treatment_id) REFERENCES treatments_lookup(treatment_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vaccinations (
        vaccination_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        vaccine_id INTEGER,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE,
        FOREIGN KEY(vaccine_id) REFERENCES vaccines_lookup(vaccine_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        name TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS subcategories (
        category_name TEXT,
        sub_name TEXT,
        PRIMARY KEY (category_name, sub_name),
        FOREIGN KEY (category_name) REFERENCES categories(name) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS supplies (
        supply_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        category TEXT,
        sub_category TEXT,
        current_stock INTEGER DEFAULT 0,
        reorder_level INTEGER,
        expiry_date TEXT,
        buy_price REAL,
        sell_price REAL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stocks (
        batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
        supply_id INTEGER NOT NULL,
        supplier_id INTEGER,
        purchase_date TEXT,
        expiry_date TEXT,
        buy_price REAL,
        quantity INTEGER,
        notes TEXT,
        receipt_id INTEGER,
        FOREIGN KEY(supply_id) REFERENCES supplies(supply_id) ON DELETE CASCADE,
        FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        supply_id INTEGER NOT NULL,
        user_id INTEGER,
        receipt_id INTEGER,
        movement_type TEXT,
        quantity INTEGER NOT NULL,
        movement_date TEXT DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        FOREIGN KEY(supply_id) REFERENCES supplies(supply_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS packages (
        package_id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        description TEXT,
        total_price REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS package_items (
        package_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_id INTEGER NOT NULL,
        item_type TEXT CHECK(item_type IN ('service', 'supply')),
        service_id INTEGER,
        supply_id INTEGER,
        quantity INTEGER,
        FOREIGN KEY(package_id) REFERENCES packages(package_id) ON DELETE CASCADE,
        FOREIGN KEY(service_id) REFERENCES services_lookup(service_id) ON DELETE SET NULL,
        FOREIGN KEY(supply_id) REFERENCES supplies(supply_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipts (
        receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER,
        owner_id INTEGER,
        receipt_date TEXT DEFAULT CURRENT_DATE,
        total_price REAL,
        staff_id INTEGER,
        receipt_code TEXT UNIQUE,
        receipt_kind TEXT,
        payment_status TEXT NOT NULL DEFAULT 'Unpaid'
            CHECK(payment_status IN ('Paid', 'Partial', 'Unpaid')),
        discount REAL DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE SET NULL,
        FOREIGN KEY(owner_id) REFERENCES owners(owner_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_services (
        receipt_service_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        service_id INTEGER,
        quantity INTEGER,
        unit_price REAL,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE,
        FOREIGN KEY(service_id) REFERENCES services_lookup(service_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_supplies (
        receipt_supply_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        supply_id INTEGER,
        quantity INTEGER,
        unit_price REAL,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE,
        FOREIGN KEY(supply_id) REFERENCES supplies(supply_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_packages (
        receipt_package_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        package_id INTEGER,
        quantity INTEGER DEFAULT 1,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE,
        FOREIGN KEY(package_id) REFERENCES packages(package_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_other (
        receipt_other_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        description TEXT,
        amount REAL,
        quantity INTEGER DEFAULT 1,
        unit_price REAL,
        category TEXT,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_adjustments (
        adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        visit_id INTEGER,
        adjusted_by INTEGER,
        description TEXT,
        old_total REAL,
        new_total REAL,
        delta REAL,
        details TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE SET NULL,
        FOREIGN KEY(adjusted_by) REFERENCES users(user_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS doctors (
        doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        specialization TEXT,
        phone TEXT,
        email TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT,
        last_login TEXT,
        doctor_id INTEGER,
        FOREIGN KEY(doctor_id) REFERENCES doctors(doctor_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS roles (
        role_id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_name TEXT NOT NULL UNIQUE,
        description TEXT,
        is_system INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_roles (
        user_role_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY(role_id) REFERENCES roles(role_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_permissions (
        role_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_id INTEGER NOT NULL,
        permission_key TEXT NOT NULL,
        FOREIGN KEY(role_id) REFERENCES roles(role_id) ON DELETE CASCADE,
        UNIQUE(role_id, permission_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_permissions (
        user_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        permission_key TEXT NOT NULL,
        override INTEGER NOT NULL DEFAULT -1,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        UNIQUE(user_id, permission_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS change_header (
        change_header_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        table_name TEXT NOT NULL,
        record_id INTEGER,
        changed_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS change_detail (
        change_detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
        change_header_id INTEGER NOT NULL,
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        FOREIGN KEY(change_header_id) REFERENCES change_header(change_header_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        log_type_id INTEGER,
        entity_type TEXT,
        entity_id INTEGER,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        details TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_changes (
        pending_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER,
        table_name       TEXT NOT NULL,
        record_id        INTEGER,
        operation        TEXT NOT NULL CHECK(operation IN ('UPDATE','INSERT','DELETE')),
        payload          TEXT,
        status           TEXT NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','approved','rejected')),
        reviewer_id      INTEGER,
        reviewed_at      TEXT,
        review_notes     TEXT,
        submitted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id)     REFERENCES users(user_id) ON DELETE SET NULL,
        FOREIGN KEY(reviewer_id) REFERENCES users(user_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vaccine_schedules (
        schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vaccine_id INTEGER NOT NULL,
        species_id INTEGER NOT NULL,
        interval_days INTEGER NOT NULL,
        notes TEXT,
        FOREIGN KEY(vaccine_id) REFERENCES vaccines_lookup(vaccine_id) ON DELETE CASCADE,
        FOREIGN KEY(species_id) REFERENCES species_lookup(species_id) ON DELETE CASCADE,
        UNIQUE(vaccine_id, species_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vaccination_reminders (
        reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_id INTEGER NOT NULL,
        vaccine_id INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','completed','skipped')),
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(pet_id) REFERENCES pets(pet_id) ON DELETE CASCADE,
        FOREIGN KEY(vaccine_id) REFERENCES vaccines_lookup(vaccine_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL DEFAULT 'Cash'
                           CHECK(payment_method IN ('Cash','Card','Bank Transfer','Other')),
        payment_date TEXT DEFAULT CURRENT_DATE,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_archives (
        archive_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        report_kind  TEXT NOT NULL,
        period_type  TEXT NOT NULL DEFAULT 'Month',
        period_start TEXT,
        period_end   TEXT,
        generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        generated_by TEXT,
        data_json    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deleted_records (
        deleted_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        record_id INTEGER NOT NULL,
        snapshot TEXT NOT NULL,
        deleted_by INTEGER,
        deleted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        restored_at TEXT,
        restored_by INTEGER,
        FOREIGN KEY(deleted_by) REFERENCES users(user_id) ON DELETE SET NULL,
        FOREIGN KEY(restored_by) REFERENCES users(user_id) ON DELETE SET NULL
    )
    """,
]

# --- 3. View Definitions ---
views = [
    """
    DROP VIEW IF EXISTS v_visit_details
    """,
    """
    DROP VIEW IF EXISTS v_receipt_summary
    """,
    """
    DROP VIEW IF EXISTS v_home_records
    """,
    """
    CREATE VIEW IF NOT EXISTS v_visit_details AS
    SELECT 
        v.visit_id, v.visit_date, v.diagnosis, v.notes,
        v.reason_for_visit, v.temperature_in_c,
        p.pet_id, p.pet_name, p.gender, p.age_in_months, p.weight_in_kg,
        o.owner_id, o.first_name, o.last_name,
        sl.species_name, bl.breed_name
    FROM visits v
    JOIN pets p ON v.pet_id = p.pet_id
    JOIN owners o ON p.owner_id = o.owner_id
    LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
    LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
    """,
    """
    CREATE VIEW IF NOT EXISTS v_receipt_summary AS
    SELECT 
        r.receipt_id, r.receipt_date, r.total_price, r.receipt_code, r.receipt_kind,
        r.visit_id, o.owner_id, o.first_name || ' ' || o.last_name AS owner_name,
        'Service' AS item_type, rs.service_id AS item_id,
        COALESCE(srv.service_name, '(deleted service)') AS item_name, rs.quantity, rs.unit_price,
        rs.quantity * rs.unit_price AS line_total,
        r.notes AS notes
    FROM receipts r
    LEFT JOIN owners o ON r.owner_id = o.owner_id
    -- LEFT JOINs: deleting a catalog item must never hide its receipt line
    -- (the amount stays in receipts.total_price, so the row has to stay
    -- visible/editable or the receipt can never be reconciled again).
    JOIN receipt_services rs ON r.receipt_id = rs.receipt_id
    LEFT JOIN services_lookup srv ON rs.service_id = srv.service_id
    UNION ALL
    SELECT 
        r.receipt_id, r.receipt_date, r.total_price, r.receipt_code, r.receipt_kind,
        r.visit_id, o.owner_id, o.first_name || ' ' || o.last_name AS owner_name,
        'Supply' AS item_type, rs.supply_id AS item_id,
        COALESCE(s.item_name, '(deleted item)') AS item_name, rs.quantity, rs.unit_price,
        rs.quantity * rs.unit_price AS line_total,
        r.notes AS notes
    FROM receipts r
    LEFT JOIN owners o ON r.owner_id = o.owner_id
    JOIN receipt_supplies rs ON r.receipt_id = rs.receipt_id
    LEFT JOIN supplies s ON rs.supply_id = s.supply_id
    UNION ALL
    SELECT 
        r.receipt_id, r.receipt_date, r.total_price, r.receipt_code, r.receipt_kind,
        r.visit_id, o.owner_id, o.first_name || ' ' || o.last_name AS owner_name,
        'Package' AS item_type, rp.package_id AS item_id,
        COALESCE(pkg.package_name, '(deleted package)') AS item_name, rp.quantity, pkg.total_price,
        rp.quantity * pkg.total_price AS line_total,
        r.notes AS notes
    FROM receipts r
    LEFT JOIN owners o ON r.owner_id = o.owner_id
    JOIN receipt_packages rp ON r.receipt_id = rp.receipt_id
    LEFT JOIN packages pkg ON rp.package_id = pkg.package_id
    UNION ALL
    SELECT 
        r.receipt_id, r.receipt_date, r.total_price, r.receipt_code, r.receipt_kind,
        r.visit_id, o.owner_id, o.first_name || ' ' || o.last_name AS owner_name,
        -- Expenses carry their own category (receipt_other.category); lines
        -- added by other flows fall back to the generic 'Other' bucket.
        COALESCE(NULLIF(ro.category, ''), 'Other') AS item_type,
        ro.receipt_other_id AS item_id,
        ro.description,
        COALESCE(NULLIF(ro.quantity, 0), 1),
        COALESCE(ro.unit_price,
                 ro.amount / COALESCE(NULLIF(ro.quantity, 0), 1)),
        ro.amount AS line_total,
        r.notes AS notes
    FROM receipts r
    LEFT JOIN owners o ON r.owner_id = o.owner_id
    JOIN receipt_other ro ON r.receipt_id = ro.receipt_id
    """,
    """
    CREATE VIEW IF NOT EXISTS v_home_records AS
    SELECT 
        v.visit_id, v.visit_date, v.diagnosis, v.notes,
        v.reason_for_visit, v.temperature_in_c,
        p.pet_id, p.pet_name, p.gender, p.age_in_months, p.weight_in_kg,
        o.owner_id, o.first_name, o.last_name,
        o.first_name || ' ' || o.last_name AS owner_full_name,
        c.phone_number,
        sl.species_name, bl.breed_name,
        r.receipt_id
    FROM visits v
    JOIN pets p ON v.pet_id = p.pet_id
    JOIN owners o ON p.owner_id = o.owner_id
    LEFT JOIN species_lookup sl ON p.species_id = sl.species_id
    LEFT JOIN breeds_lookup bl ON p.breed_id = bl.breed_id
    LEFT JOIN entity_contacts ec ON ec.entity_type = 'owner' AND ec.entity_id = o.owner_id
    LEFT JOIN contacts c ON ec.contact_id = c.contact_id
    LEFT JOIN receipts r ON r.visit_id = v.visit_id
    """,
    """
    DROP VIEW IF EXISTS v_pet_health_timeline
    """,
    """
    CREATE VIEW IF NOT EXISTS v_pet_health_timeline AS
    SELECT
        v.pet_id,
        'Visit' AS event_type,
        v.visit_id AS event_id,
        v.visit_date AS event_date,
        v.diagnosis AS summary,
        v.temperature_in_c AS detail_1,
        v.reason_for_visit AS detail_2,
        v.visit_id AS source_visit_id
    FROM visits v
    UNION ALL
    SELECT
        v.pet_id,
        'Medication' AS event_type,
        m.medication_id AS event_id,
        v.visit_date AS event_date,
        COALESCE(sl.item_name, 'Unknown') || CASE WHEN m.dosage IS NOT NULL AND m.dosage != '' THEN ' (' || m.dosage || ')' ELSE '' END AS summary,
        NULL AS detail_1,
        m.instructions AS detail_2,
        m.visit_id AS source_visit_id
    FROM medications m
    JOIN visits v ON m.visit_id = v.visit_id
    LEFT JOIN supplies sl ON m.supply_id = sl.supply_id
    UNION ALL
    SELECT
        v.pet_id,
        'Test' AS event_type,
        t.routine_test_id AS event_id,
        v.visit_date AS event_date,
        COALESCE(tl.test_name, 'Unknown') AS summary,
        NULL AS detail_1,
        sl2.state_value AS detail_2,
        t.visit_id AS source_visit_id
    FROM tests t
    JOIN visits v ON t.visit_id = v.visit_id
    LEFT JOIN tests_lookup tl ON t.test_id = tl.test_id
    LEFT JOIN states_lookup sl2 ON t.state_id = sl2.state_id
    UNION ALL
    SELECT
        v.pet_id,
        'Treatment' AS event_type,
        tr2.treatment_record_id AS event_id,
        v.visit_date AS event_date,
        COALESCE(tl2.treatment_name, 'Unknown') AS summary,
        NULL AS detail_1,
        NULL AS detail_2,
        tr2.visit_id AS source_visit_id
    FROM treatments tr2
    JOIN visits v ON tr2.visit_id = v.visit_id
    LEFT JOIN treatments_lookup tl2 ON tr2.treatment_id = tl2.treatment_id
    UNION ALL
    SELECT
        v.pet_id,
        'Vaccination' AS event_type,
        vacc.vaccination_id AS event_id,
        v.visit_date AS event_date,
        COALESCE(vl.vaccine_name, 'Unknown') AS summary,
        NULL AS detail_1,
        NULL AS detail_2,
        vacc.visit_id AS source_visit_id
    FROM vaccinations vacc
    JOIN visits v ON vacc.visit_id = v.visit_id
    LEFT JOIN vaccines_lookup vl ON vacc.vaccine_id = vl.vaccine_id
    UNION ALL
    SELECT
        hs.pet_id,
        'Health Stat' AS event_type,
        hs.health_stat_id AS event_id,
        v.visit_date AS event_date,
        COALESCE(st.stat_name, 'Unknown') AS summary,
        NULL AS detail_1,
        sl3.state_value AS detail_2,
        hs.visit_id AS source_visit_id
    FROM health_stats hs
    JOIN visits v ON hs.visit_id = v.visit_id
    LEFT JOIN stat_types_lookup st ON hs.stat_type_id = st.stat_type_id
    LEFT JOIN states_lookup sl3 ON hs.state_id = sl3.state_id
    """,
]
clinical_exam_tables = [
    """
    CREATE TABLE IF NOT EXISTS visit_general_exam (
        general_exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL UNIQUE,
        weight_value REAL,
        weight_condition TEXT CHECK(weight_condition IN ('underweight','normal','overweight')),
        temperature_value REAL,
        temperature_status TEXT CHECK(temperature_status IN ('low','normal','high')),
        neutered INTEGER DEFAULT 0 CHECK(neutered IN (0,1)),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_clinical_signs (
        clinical_signs_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL UNIQUE,
        energy TEXT CHECK(energy IN ('normal','increased','decreased')),
        appetite TEXT CHECK(appetite IN ('normal','increased','decreased','none')),
        water_intake TEXT CHECK(water_intake IN ('normal','increased','decreased','none')),
        urination TEXT CHECK(urination IN ('normal','increased','decreased','none')),
        feces_status TEXT CHECK(feces_status IN ('normal','abnormal')),
        feces_notes TEXT,
        vomiting_present INTEGER DEFAULT 0 CHECK(vomiting_present IN (0,1)),
        vomiting_frequency TEXT,
        coughing_present INTEGER DEFAULT 0 CHECK(coughing_present IN (0,1)),
        coughing_frequency TEXT,
        sneezing_present INTEGER DEFAULT 0 CHECK(sneezing_present IN (0,1)),
        sneezing_frequency TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_physical_exam (
        physical_exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL UNIQUE,
        heart_normal INTEGER DEFAULT 1 CHECK(heart_normal IN (0,1)),
        heart_rate INTEGER,
        heart_rate_category TEXT CHECK(heart_rate_category IN ('slow','normal','fast')),
        murmur_left TEXT,
        murmur_right TEXT,
        lungs_normal INTEGER DEFAULT 1 CHECK(lungs_normal IN (0,1)),
        eyes_normal INTEGER DEFAULT 1 CHECK(eyes_normal IN (0,1)),
        ears_normal INTEGER DEFAULT 1 CHECK(ears_normal IN (0,1)),
        nose_throat_normal INTEGER DEFAULT 1 CHECK(nose_throat_normal IN (0,1)),
        mouth_teeth_gums_normal INTEGER DEFAULT 1 CHECK(mouth_teeth_gums_normal IN (0,1)),
        gingivitis_severity TEXT CHECK(gingivitis_severity IN ('none','mild','moderate','severe')),
        abdomen_normal INTEGER DEFAULT 1 CHECK(abdomen_normal IN (0,1)),
        musculoskeletal_normal INTEGER DEFAULT 1 CHECK(musculoskeletal_normal IN (0,1)),
        skin_hair_coat_normal INTEGER DEFAULT 1 CHECK(skin_hair_coat_normal IN (0,1)),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_physical_exam_findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        system_name TEXT NOT NULL,
        finding_text TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_physical_exam_conditions (
        cond_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        system_name TEXT NOT NULL,
        condition_text TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_physical_exam_locations (
        loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        location_text TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_routine_tests (
        vtest_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        test_name TEXT,
        result TEXT CHECK(result IN ('positive','negative','pending')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_vaccination_list (
        vvacc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL,
        vaccine_name TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_recommended_tests_treatments (
        rec_id INTEGER PRIMARY KEY AUTOINCREMENT,
        visit_id INTEGER NOT NULL UNIQUE,
        xrays INTEGER DEFAULT 0 CHECK(xrays IN (0,1)),
        ekg INTEGER DEFAULT 0 CHECK(ekg IN (0,1)),
        urinalysis INTEGER DEFAULT 0 CHECK(urinalysis IN (0,1)),
        thyroid_level INTEGER DEFAULT 0 CHECK(thyroid_level IN (0,1)),
        follow_up TEXT,
        ultrasonic_teeth_cleaning INTEGER DEFAULT 0 CHECK(ultrasonic_teeth_cleaning IN (0,1)),
        drug_monitoring INTEGER DEFAULT 0 CHECK(drug_monitoring IN (0,1)),
        blood_screen INTEGER DEFAULT 0 CHECK(blood_screen IN (0,1)),
        deep_ear_video INTEGER DEFAULT 0 CHECK(deep_ear_video IN (0,1)),
        other TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(visit_id) REFERENCES visits(visit_id) ON DELETE CASCADE
    )
    """,
]
