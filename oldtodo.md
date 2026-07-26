# PET Migration - TODO.md
## Phase 3: UI Column Key Fixes (Needed to prevent crashes)
The repositories return new column names but some UI pages still reference old column keys:

| File | Issue | Fix Status |
|---|---|---|
| `src/ui/pages/supplies.py` | `"id"` -> `"supply_id"`, `"quantity"` -> `"current_stock"` | ❌ |
| `src/ui/pages/clients.py` | `"consult"` column in Visits tab hardcodes 0 | ❌ |
| `src/ui/pages/receipts.py` | `"category"` -> `"item_type"` from `v_receipt_summary` | ❌ |

## New PET UI Features Not Yet Added
Features from `New PET/` that are still pending implementation:

- **Login dialog** (`New PET/ui/login.py`) - user/role based authentication
- **QChart-based dashboard** with KPI cards, bar charts
- **Dual SideMenu** (SmallMenu + BigMenu concept with toggle)
- **Top bar with notifications** button + dropdown menu
- **Database-driven pages** (`database_pages/clients_page/`, `database_pages/visits_page/`)

## Phase 4: Future Enhancements
- Notification button in top bar
- Full login/auth flow using `user_repo.py`
- Clinical dashboard with charts (QChart)
- Database-driven UI pages