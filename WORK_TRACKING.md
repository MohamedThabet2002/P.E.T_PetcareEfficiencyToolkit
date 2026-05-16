# Work Tracking - Database Schema Migration & Feature Update

This file tracks the step-by-step progress of updating the old PET project to use the new database schema and features.

## Status Legend
- [ ] Not started
- [x] Completed
- [-] Skipped / TODO

## Phase 1: Database Schema Migration

### Step 1.1: Update `src/core/database.py`
- [x] Replace old table definitions with new schema from New PET database
- [x] Add all new tables
- [x] Update indexes for new schema
- [x] Update connection settings
- [x] Update views for new schema

### Step 1.2: Update `src/core/repositories/`
- [x] Update `client_repo.py` - new schema references (owner_id, first_name/last_name split)
- [x] Update `pet_repo.py` - species_id, breed_id, owner_id references
- [x] Update `visit_repo.py` - new columns (temperature, reason, doctor_id, etc.)
- [x] Update `appointment_repo.py` - pet_id based, doctor_id, status_history
- [x] Update `supply_repo.py` - current_stock, reorder_level, supplier_id references
- [x] Update `sales_repo.py` - restructured receipts (receipt_supplies, receipt_services, etc.)
- [ ] Create new repositories:
  - [ ] `supplier_repo.py`
  - [ ] `stock_repo.py`
  - [ ] `health_stats_repo.py`
  - [ ] `followup_repo.py`
  - [ ] `test_repo.py`
  - [ ] `treatment_repo.py`
  - [ ] `vaccination_repo.py`
  - [ ] `medication_repo.py`
  - [ ] `package_repo.py`
  - [ ] `user_repo.py`
  - [ ] `audit_repo.py`
  - [ ] `log_repo.py`

### Step 1.3: Update `src/seed.py`
- [x] Rewrite seed script to use new schema
- [x] Add lookup table seeding (species, breeds, services, etc.)
- [x] Update sample data to match new table structure

## Phase 2: UI Updates

### Step 2.1: Core UI Components
- [ ] Update `src/ui/pages/clients.py` - use first_name/last_name, contacts model
- [ ] Update `src/ui/pages/home.py` (visit records) - reflect new visit columns
- [ ] Update `src/ui/pages/supplies.py` - use suppliers table, stock batches
- [ ] Update `src/ui/pages/receipts.py` - structured receipt items
- [ ] Update `src/ui/pages/dashboard.py` - adapt analytics queries to new schema
- [ ] Update `src/ui/dialogs/clinical_dialogs.py` - add health stats, tests, treatments, medications, vaccinations
- [ ] Update `src/ui/dialogs/settings.py` - add suppliers management, species/breeds management

### Step 2.2: New Feature Pages/Dialogs
- [ ] Create login dialog
- [ ] Create user management dialog
- [ ] Create species/breeds management dialog
- [ ] Create suppliers management dialog
- [ ] Create packages management dialog
- [ ] Create stock management dialog
- [ ] Create followups dialog
- [ ] Add health stats recording to visit dialogs
- [ ] Add tests/treatments/vaccinations to visit dialogs
- [ ] Add medications to visit dialogs

### Step 2.3: Update `src/ui/side_menu.py`
- [ ] Update to match New PET's dual SideMenuSmall/SideMenuBig concept
- [ ] Add new navigation items if needed

### Step 2.4: Update `src/ui/main_window.py`
- [ ] Add notification button from New PET
- [ ] Add account menu with logout reference
- [ ] Update top bar to match New PET design

## Phase 3: Testing & Cleanup

### Step 3.1: Testing
- [ ] Run seed script with new schema
- [ ] Verify dashboard loads without errors
- [ ] Verify client CRUD operations work
- [ ] Verify visit CRUD operations work
- [ ] Verify supply CRUD operations work
- [ ] Verify receipt CRUD operations work
- [ ] Verify appointment CRUD works
- [ ] Verify theme switching works
- [ ] Verify i18n still works

### Step 3.2: Cleanup
- [x] Remove old temp files (_cleanup_db.py, _temp_check_db.py, _verify_views.py)
- [x] Final review of TODO.md - comprehensive tracking of unimplemented features
- [x] Update WORK_TRACKING.md status

