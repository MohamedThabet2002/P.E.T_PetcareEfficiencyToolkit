# Developer Guide — Petcare Efficiency Toolkit (P.E.T)

> **Current version under development:** 1.1.0
> Single version source of truth: `src/config/meta.py`

---

## 1. Environment Setup

### Requirements
- **Python** 3.8 or higher (3.11 recommended)
- **PyQt5** + **PyQtChart** — see `requirements.txt`
- **pytest** for running the test suite

### Quick start

```bash
# Clone and enter the repo
git clone <repo-url>
cd PET

# Create a virtual environment (Windows)
python -m venv .venv
.venv\Scripts\activate

# Install runtime + dev dependencies
pip install -r requirements.txt
pip install pytest  # dev only; not in runtime requirements
```

### Run the application

```bash
python main.py
```

**Default credentials (first-run only):**
Username: `admin` / Password: `admin123`
Change this immediately in Settings > User Management before using in a real clinic.

---

## 2. Seed Data

There are **two separate seed mechanisms** — do not confuse them:

| File | Purpose | When to run |
|------|---------|-------------|
| `src/core/database/seed_data.py` | First-run defaults (species, roles, services, etc.) | Runs automatically on first launch via schema migrations |
| `seed.py` (root) | Realistic demo / test data (clients, pets, visits, supplies…) | Run manually for demos or development only |

```bash
# Populate demo data (safe to run on a fresh DB)
python seed.py

# Force-wipe transactional data and reseed
python seed.py --force
```

Never commit Database.db — it is gitignored. Use seed.py to recreate demo data.

---

## 3. Roles

The application ships with three roles:

| Role | Access |
|------|--------|
| `admin` | Full access: all pages, edit/delete records, backup/restore, user management |
| `doctor` | Clinical pages, own visits/appointments only, read-only other data; edits go through approval |
| `staff` | General access, read-only clinical data, edits go through approval |

Roles are seeded automatically in `src/core/database/seed_data.py` and backfilled by migration `004_add_doctor_role`.

---

## 4. Testing

The test suite lives in `tests/` and is versioned with the project.

```bash
# Run all tests (verbose)
python -m pytest tests/ -v

# Run a specific file
python -m pytest tests/test_settings_manager.py -v

# Run with coverage (if pytest-cov installed)
python -m pytest tests/ --cov=src --cov-report=term-missing
```

Target: 0 failures, 0 errors.

---

## 5. Schema Migrations

Migrations run automatically every time the app starts (`src/core/database/migrations.py`).
Already-applied versions are tracked in the `schema_migrations` table (INSERT OR IGNORE).

| Version | Description |
|---------|-------------|
| `001_initial_schema` | Initial indexes |
| `002_receipt_other_columns` | `quantity` + `unit_price` on `receipt_other` |
| `003_package_item_type` | `item_type` discriminator on `package_items` |
| `004_add_doctor_role` | Ensure `doctor` role exists in `roles` table |
| `005_pending_changes` | Add `pending_changes` table for approval workflow |
| `006_receipt_payment_status` | Track payment status for receipt reminders |
| `007_user_doctor_mapping` | Link authenticated users to doctor records |
| `008_appointment_service` | Preserve the selected service on appointments |
| `009_followup_doctor` | Track the doctor assigned to each follow-up and backfill legacy rows |

When adding a new migration:
1. Add the DDL/DML inside `run_migrations()` in `migrations.py`
2. Call `_record_migration(db, "NNN_description")` at the end of that block
3. Document it in the table above

Doctor attribution is explicit: `users.doctor_id` maps an account to a row in
`doctors`, while visits, appointments, and follow-ups store their assigned
`doctor_id`. A follow-up inherits its source visit's doctor unless an
authorized user selects a substitute doctor.

The Visits page owns the Visits and Appointments tabs. Clients owns only
Clients and Pets. Dashboard Add Visit and Quick Purchase reuse the same
dialogs exposed by Visits.

---

## 6. Build & Packaging

### Step 1 — PyInstaller

```bash
python -m PyInstaller --clean --noconfirm PET.spec
```

This generates `dist/PET/`.

### Step 2 — Inno Setup installer

```bash
python package_app.py
```

Requires Inno Setup 6 installed. The installer output goes to `Output/PET_Setup.exe`.

The installer is configured to preserve user data in
`%LocalAppData%\Petcare Efficiency Toolkit (P.E.T)` during upgrades.

---

## 7. Key Paths

| Concern | Path |
|---------|------|
| Entry point | `main.py` |
| Version | `src/config/meta.py` |
| Window / nav | `src/ui/main_window.py`, `src/ui/side_menu.py` |
| Dashboard / Reports | `src/ui/pages/dashboard_page.py`, `reports_page.py` |
| Cards / Charts | `src/modules/cards.py`, `charts.py` |
| Permissions | `src/core/permissions.py` |
| Schema / Migrations | `src/core/database/schema_definitions.py`, `migrations.py` |
| Backup | `src/core/backup_manager.py` |
| Users / Roles | `src/core/repositories/user_repo.py` |
| Audit | `src/core/repositories/audit_repo.py` |
| Product notes | `my notes.md` |
