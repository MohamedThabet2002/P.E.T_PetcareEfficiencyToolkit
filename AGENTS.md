# PET (Petcare Efficiency Toolkit)

Desktop veterinary clinic management app. Python 3 + PyQt5 + SQLite. Runs on Windows 7+.

## Stack & Layout

- **GUI**: PyQt5 / PyQtChart (PySide NOT used — stick to PyQt5 or PyQtChart imports)
- **DB**: SQLite via `src/core/database/*` (SQL file: `Database.db`, gitignored)
- **Language**: Python; entry point `main.py`. App lives in `src/` (no separate lib).
- **Versions**: Python venv at `.wvenv/` (PyQt5, PyQtChart, pytest, PyInstaller).
- **Tests**: `pytest` in `tests/` (database tests auto-clean; some use temp DBs).

### src/ layout (import pattern: `from src.<pkg>.<mod> import ...`)
- `config/` — constants, meta (APP_NAME/VERSION/ORG_NAME), paths
- `core/` — re-exports `get_connection`, `get_user_db_path`, `create_backup`, `list_backups`, `restore_backup`
  - `database/` — connection, migrations, schema_definitions, seed_data, legacy_migration
  - `repositories/` — one repo per domain (client, pet, visit, sales, stock, supply, user, audit, ...)
  - `services/` — business logic (clinical_service)
  - `backup_manager.py`, `permissions.py`, `importer.py`, `exporter.py`, `status_resolver.py`
- `modules/` — reusable widgets (base_page, charts, cards) + `signal_bus.py`
- `ui/` — `main_window.py`, `side_menu.py`, `pages/`, `dialogs/`, `themes/`
- `utils/` — formatters, i18n, settings_manager, font_loader

## Conventions

- **Repos** wrap DB access; **UI never touches SQL directly** — go through repos.
- **i18n**: two languages (English/Arabic RTL). Add UI strings in `src/utils/i18n.py`; don't hardcode user-facing strings.
- **Themes**: light/dark via `src/ui/themes/color_palettes.py`.
- **Tests**: mirror module name in `tests/` (e.g. `tests/test_<module>.py`), one file per repo/module.

## Run / Verify

- Run app: `main.py`
- Run tests: activate `.wvenv`, then `pytest` (uses current dir database; safe since `*.db` is gitignored)
- No linter installed (`.flake8` config is dormant) — verify with `python -m compileall src tests` + `pytest`.

**Venv**: use the Python venv at `.wvenv/` — NOT `.venv` (`.venv` is outdated/ignore it).

## Operating Rules (for AI agents — follow these automatically to save tokens)

You are an agent working on this repo. Every file you read costs tokens and latency, so minimize reading and stay precise. Treat these as hard defaults unless the user says otherwise.

**1. Read the smallest thing that does the job.**
- Open only the file(s) that actually contain the change. Do NOT open a whole 600–1000 line page/dialog file just to browse; open it only if the edit is inside it.
- Use grep/glob to locate a symbol or string, then read just the matching lines — not the whole file.
- This is the single biggest token saver here: several files (`info_dialogs.py`, `sales_repo.py`, `base_clinical_dialog.py`, `importer.py`, `settings_page.py`, `schema_definitions.py`) exceed 700–1900 lines.

**2. Work through the existing layers, don't reinvent.**
- UI → repo → DB. Repos wrap SQL; UI never calls SQL directly. Never bypass a repo that already exists.
- Follow the style of the sibling repo/dialog closest to your task instead of inventing a new pattern.
- Add new UI strings to `src/utils/i18n.py` (English + Arabic); never hardcode user-facing text.

**3. Default guardrails.**
- No new dependencies unless explicitly asked — PyQt5 / PyQtChart only, never PySide; stdlib + PyQt.
- No refactors or cleanup beyond the scope of the request.
- Don't commit, push, or create PRs unless explicitly asked.

**4. Preserve user intent / token economy.**
- If a user prompt is vague, favor the smallest reasonable change that matches the stated goal rather than guessing broadly.
- Prefer editing existing files over writing new ones.

**5. The user is a beginner — not every message is a task.**
- The user is learning; they may think out loud, ask questions, or suggest ideas while exploring. Do NOT treat every message as an instruction to change code.
- First review what was said: is it a real task, a question, or just an idea? If it's not clearly a task, respond with your assessment instead of editing files.
- Even when it sounds like a request, evaluate whether the idea is good and whether it fits this project (architecture, conventions, scope in AGENTS.md). Then either:
  - explain why it is a good fit and what you'd do (wait for confirmation for anything non-trivial), or
  - explain why it is NOT a good fit / not good practice, with the reason, and suggest an alternative.
- When unsure, ask a clarifying question rather than guessing. Teaching briefly ("why") is welcome — the user wants to learn, not just get code.

## Notes

(Add persistent notes here. This file is loaded into context at the start of every opencode session,
so keep notes SHORT: durable invariants, contracts and gotchas an agent cannot rediscover cheaply.
Dated "what changed" stories, test counts, suite totals and i18n key lists do NOT belong here —
git history / `CHANGELOG.md` cover them and they go stale.)

### Dashboard: 3 action buttons (permission + width gated)

- `DashboardPage._apply_action_button_visibility()` (called from `set_current_user` AND `resizeEvent`):
  every button follows its permission (`add_visit`, `add_supplies`, `quick_purchase`). When a user is
  allowed **all three**, the role's two main buttons always show and the third is width-gated on
  `WIDE_WINDOW_WIDTH` (**1200 px**, same threshold as the next-client countdown): **admins gate Quick
  Purchase**, everyone else gates **Add Supplies** (`is_admin(user)` decides). A partial grant is never
  width-gated; a `None` user hides all three. Keep `perm.desc.add_supplies` / `perm.desc.quick_purchase`
  (en+ar, `assets/translations.json`) in step with the rule.
- Quick Purchase opens `QuickPurchaseDialog`, then refreshes KPIs and emits `visits_page.data_changed`
  (cross-page fan-out).
- **Gotcha:** Qt does NOT deliver `resizeEvent` to a hidden widget (the pending resize arrives on
  `show()`), so tests must `show()` the page before `resize()` — `tests/test_dashboard_action_buttons.py`.

### Dashboard: Reminders card = `get_notifications` top 10

- Dashboard `_refresh_reminders()` calls `analytics_repo.get_notifications(limit=10)`; the
  **View all** button opens `RemindersDialog` with `limit=100`. The repo sorts LAST, before
  truncation, by `priority_order` (`pending_changes` → `unpaid_receipt` → `expense_balance`)
  then severity then details — so money owed always owns the card's first slots; the per-section
  LIMITs only bound the non-money sources.
- **"Unpaid" = `total > paid` read from `payments`** (via `get_unpaid_receipts_range`, shared with
  the Reports "Unpaid Receipts" table) — includes Partial receipts; the `payment_status` string is
  never the filter. Tests: `tests/test_analytics_repo.py::TestNotifications`.

### Statuses: follow-up vocabulary, Late, auto-cancel

- Follow-up vocabulary = `FOLLOWUP_STATUS_STATES` (`"Pending"`, `"Completed"`, `"Canceled"`) in
  `src/core/database/seed_data.py` — the single source. `FOLLOWUP_STATUS_RETIRED` (`Scheduled`,
  `Missed`) must never come back: migration `020_followup_status_prune` remaps stragglers to Pending
  and deletes those lookup rows (`followups.state_id` has **no FK** to `states_lookup`, so the remap
  is what keeps rows rendering a status).
- `lookup_repo.get_followup_statuses()` returns only those three; the follow-up editor combo is built
  from it. `followup_repo.resolve_status_state_id(status)` returns `None` for anything outside the
  vocabulary (derived `Late`, retired, unknown); queries COALESCE a missing state to `"Pending"`.
- Appointment-side combos (`appointments_dialog.STATUS_OPTIONS`, `visits_page.STATUS_OPTIONS`) are
  hardcoded `[Pending, Completed, Canceled]` **on purpose** — never derive them from the lookup (a
  lookup-driven list can end up with a single item and freeze the combo).
- The Appointments tab lists appointments + follow-ups in one table: the row kind is stashed on the
  hidden id cell with `Qt.UserRole` and read back by `_appointment_row_record()` — `followup_id` and
  `appointment_id` can collide.
- **Status is derived, never stored:** `src/core/status_resolver.py` owns Pending → Late → Canceled —
  `auto_cancel_hours()` reads `SettingsManager["auto_cancel_after_hours"]` live (clamped by
  `config/constants.py`), `resolve_status(stored, scheduled)` is pure. `appointment_repo` /
  `followup_repo` import it; a DB UPDATE cannot fix a status. Edited in Settings → Clinic Profile →
  **Scheduling Rules** (`auto_cancel_edit`, preview label).
- Because it is derived, `appointment_repo.get_appointments` carries `late_probe` (a status-column
  search for "late" skips the SQL LIKE and filters after the sort); the dashboard merges Late rows
  from `get_past_appointments`/`get_past_followups` + `get_upcoming_followups` and paints them
  `state_late`.
- Dashboard roll-over: `get_next_appointment_time` is **strictly future** (minute-truncated `>`), so
  `DashboardPage._update_countdown` latches `_countdown_expired` → `QTimer.singleShot(0, _advance_schedule)`
  **before** the narrow-window early return (works at any width). Today's Appointments = 4 slots
  (`ANALYTICS_LIMITS.late_preview_count` + `appointment_preview_count`): latest completed, earliest
  Late, two soonest pending; empty slots skipped, duplicates collapsed.
- Timing tests must monkeypatch `src.utils.settings_manager.SETTINGS_FILE` and reset
  `SettingsManager._cache` (pattern: `tests/test_settings_manager.py`); repo tests assume the 24 h
  default. Tests: `tests/test_status_resolver.py`, `tests/test_appointment_repo.py`,
  `tests/test_dashboard_appointments.py`, `tests/test_settings_page.py` (`TestSchedulingSection`).

### Central SignalBus (cross-page refresh)

- `src/modules/signal_bus.py` — `SignalBus.instance()` singleton (QObject); coarse events
  `visits_changed`, `clients_changed`, `supplies_changed`, `receipts_changed`, `appointments_changed`,
  `login_changed`. API: `bus.on(event, slot)` (decorator or direct), `connect`, `emit_event(event,
  payload=None)`, `reset()` (tests; tolerates no-connections). Zero-argument slots are auto-adapted;
  unknown event → `ValueError`.
- **New cross-page refresh code subscribes to the bus** (`bus.on("visits_changed", ...)`) — do not
  reach into sibling pages. The legacy `data_changed` wiring in `main_window._setup_ui` is untouched;
  `MainWindow` additionally forwards sub-page `data_changed` to the bus. Tests: `tests/test_signal_bus.py`
  (autouse fixture resets the singleton).

### Seed data

- `seed.py` builds demo data through the app's repos (never raw SQL), passes unique receipt codes
  (`VISIT-####`, `RETAIL-0##`, `EXPENSE-0##`) because `receipts.receipt_code` is UNIQUE, and links
  `users.doctor_id` so doctor-scoped views (My Visits, dashboard) resolve like real logins via
  `user_repo.get_doctor_id`.
- Back-compat repo params added for seed/importer: `visit_repo.add_visit(..., receipt_code=None,
  paid=..., discount=...)`, `sales_repo.create_sale_receipt_for_quick_purchase(..., receipt_code=None,
  paid=...)`, `user_repo.update_user_doctor(user_id, doctor_id)`.
- `seed_doctors`/`seed_users` are idempotent; `_clear_transactional_data` also clears `payments` +
  `receipt_adjustments`.

### Audit logging (every add/edit/delete)

- `audit_repo.record_action(action, table_name, record_id, changes=None, user_id=None)` wraps
  `record_change` and ALWAYS prepends an `action` detail row. Repos take a trailing
  `audit_user_id=None` (or reuse an existing `user_id`); UI passes
  `(self._current_user or {}).get("user_id")`. **No user id → no audit row** (backward compatible).
- Instrumented: `client_repo`, `pet_repo`, `visit_repo` (audits AFTER its transaction commit, using
  the real `visit_id`), `appointment_repo`, `supply_repo`, `sales_repo` (quick purchase / expense /
  delete_receipt / update_receipt). Deletion choke points `_handle_deletion_confirm`
  (clients/visits pages) pass `audit_user_id`.
- Pending workflow: `pending_changes_repo.submit_change` records `SUBMIT_<OP>` on the *target* table;
  `apply_pending_change(row, reviewer_id=…)` passes `audit_user_id=reviewer_id` into the live-table
  repos so admin-applied writes are credited to the approver. `clinical_service.process_full_clinical_entry`
  threads `current_user` into add/update calls (as do `QuickPurchaseDialog`, `EditReceiptDialog`).
- Rendering: `get_recent_changes_with_details(limit)` (headers + `details`, single JOIN),
  `field_diffs(old_row, new_row)`, `format_audit_message(entry)` → the Audit tab **Details** column +
  CSV export. ADD/DELETE records keep display values so deletes stay restorable; empty diffs fall
  back to the action label.
- My Visits page (`src/ui/pages/database_pages/my_visits_page.py`, also reused as the standalone
  Visits nav page): double-clicking a row edits it — admins get the write-through `VisitInfoDialog`,
  other roles get a pending UPDATE via `submit_change` (reads visit id/date/diag/consult/notes from
  `HOME_COLUMN_MAP` indices 0/10/11/12/13).
- Tests: `tests/test_audit_actions.py`.

### Receipts: identity, money, adjustments (read before touching receipts)

**Identity — two fields, two jobs:**
- `receipts.receipt_code` = the unique human number (`VISIT-<YYYYMM>-####`, `RETAIL-…`, `EXPENSE-…`,
  or seed's legacy `VISIT-####`/`EXPENSE-0##`); `receipts.receipt_kind` = business type
  `visit | retail | expense`. **Never filter on the code to decide type** — that is what silently
  broke billing and ~15 analytics queries before.
- Allocators in `sales_repo`: `_next_unique_code(db, prefix, width)` (`.finish()`es its SELECT,
  upper-cased compare so a legacy bare `'Expense'` can't collide) → `next_visit_code` /
  `next_retail_code` / `next_expense_code`. `add_visit` allocates `next_visit_code` inside its
  transaction (local import to avoid a cycle), writes `receipt_kind='visit'`, and **rolls back +
  returns None** if the receipt INSERT fails (when billable, its return value IS the receipt id).
  `update_receipt` deliberately leaves `receipt_kind` untouched. Migration `022_receipt_kind`
  backfilled old rows; `v_receipt_summary` exposes `receipt_kind` on all 4 UNION branches (the view
  is DROP+CREATEd on every `initialize_schema`, so no view migration is needed).
- Revenue/all-sales/owner-total filters: `COALESCE(receipt_kind,'retail') <> 'expense'`; cost:
  `= 'expense'` (`sales_repo`, `analytics_repo`, `client_loyalty_repo`). Expense cost expressions
  also use `LIKE 'EXPENSE%'` (SQLite LIKE is case-insensitive, so legacy `'Expense'` still matches).
  Ledger Type column uses `receipts_page.receipt_kind_label(kind, code)`; `is_expense_code` /
  `receipt_type_label` are legacy fallbacks, not the source of truth.

**Money invariants:**
- Every writer `.finish()`es its queries **before** `db.commit()` — QtSql refuses to commit with an
  active statement (failure mode: a confusing "SQL statements in progress", not an exception). Any
  query on a transaction path must be finished.
- `payment_status` is recomputed from the `payments` table (`payment_repo.update_receipt_payment_status`)
  after `update_receipt` / `recompute_receipt_total` / adjustments. Balances
  (`get_owner_financial_summary`, `get_open_receipt_balances_for_owner`, Owner dialog Finances) also
  derive from `payments` — setting the status string alone is meaningless; the payment row is what
  matters. Zero-total receipts read as Paid (0 of 0). Fresh-install CHECK allows `'Partial'`.
- `delete_receipt` gives stock back (→ `current_stock` + `return_to_batch`, logs `sale_return`;
  `payments` rows go via `ON DELETE CASCADE`); `undo_repo._reconsume_receipt_stock` is the restore
  mirror — keep the two in step. Historical contract: `delete_receipt(-1) is True`.
- `receipt_other.quantity/unit_price` are real columns (migration `024` backfills old rows);
  `get_receipt_line_items` hardcodes `line_type="Other"` for `receipt_other` (edit matching ignores
  the view).
- Refund = a **negative** `payments` row (`payment_repo.add_refund(receipt_id, amount, ...)`, capped
  at `credit + _EPSILON`, audit action `REFUND`; the `payment_method` CHECK forbids a "Refund"
  method — the sign marks it). `ReceiptInfoDialog` swaps Add Payment → Record Refund while
  `balance < -0.004`; `_edit_payment` refuses refund rows.

**Adjustments:**
- `receipt_adjustments` (migration `016`, CASCADE from receipts) + `receipt_adjustment_repo`.
  **Qt returns `''` for a NULL FK** — `add_adjustment` coerces empty `visit_id`/`adjusted_by` to
  `None` or the INSERT fails with a FOREIGN KEY error (matters for non-visit receipts too; same rule
  as `undo_repo`).
- `EditReceiptDialog._record_adjustment_trail` is the shared trail helper both edit dialogs call;
  an `ADJUST` audit on `receipts` is written only when the total actually moved (> 0.004).
  Consultation is entirely receipt-driven via `sales_repo.reconcile_consultation` — there is **no
  `visits.is_consult` column**. `recompute_receipt_total` re-applies the stored discount.
- Stock-batch corrections flow through `sales_repo.log_stock_adjustment(..., adjustment=...)`, which
  writes the trail + audit **after commit** and re-settles `payment_status`; read `old_total` BEFORE
  the UPDATE. Brand-new receipts pass no adjustment → no trail. A price-only batch edit
  (`delta == 0`) moves no money → deliberately no trail and no ledger row (known gap).
- The Visit Details dialog (`VisitInfoDialog`, `info_dialogs.py`) is a card grid (Visit Info |
  Follow-ups / Owner Info | Pet Info / Clinical | Billing) with an Edit footer for
  `can(user,"edit_records")`; **Settle Payment** (one-click full Cash payment) + **Adjust**
  (→ `VisitAdjustDialog`, a full `EditReceiptDialog` subclass with a consult-checkbox row) appear
  only in edit mode. Edit save order: `update_visit` → `_save_clinical_records` (delete-then-re-add
  per-visit rows by PK) → `_save_receipt_items` (reconcile consult, match supply lines by item name
  via `supply_repo.resolve_supply_id`, adjustment only if the total moved) → `_save_followups`.

**Ledger & dialogs:**
- `RECEIPT_COLUMN_MAP` is the single source for column AND filter; `ReceiptsPage._filter_field()`
  returns the column **key by combo index** — never the label (translations would break filtering).
  The `Total Price` column shows the receipt total; the per-line total is the separate `line_total`
  key from `get_receipt_items` (which returns `receipt_code`, `receipt_kind`, `notes`, `category`).
  `sales_repo.get_receipt` also returns `visit_id`/`owner_phone`/`notes`/`receipt_kind`.
- `ReceiptInfoDialog` (`receipts_page.py`; printable receipt card QSS `receipt*`/`#receiptItems`,
  Payments tracker, Adjustments list) emits `data_changed` after payment add/edit/delete and
  `_edit_receipt`; `ReceiptsPage` + `visits_page` subscribe. Its `_clear` must drop **sub-layout**
  items recursively (`takeAt(0)` on a nested `QHBoxLayout` leaves buttons parented to the content →
  toolbars stack on every rebuild). Tables use `verticalHeader().setSectionResizeMode(ResizeToContents)`
  + row wrap, then `_fit_content_table()` / `_auto_fit_once()` so rows never clip. Footer buttons are
  **Print** (the on-screen card) and **Print for Client** (Export PDF was removed): the latter builds a
  throwaway card with `_build_receipt_card(client=True)` — no status strip / Paid line, thank-you
  footer, never added to the layout — and only proceeds when `balance <= 0.004`; an unsettled receipt
  gets a `QMessageBox` instead of the printer.
- Quick Purchase (`quick_purchase_dialog.py`): validates the basket BEFORE creating the owner (no
  stray `owners` row); insufficient stock returns `STOCK_ERROR|name|stock` (same contract as
  `add_visit`) and that branch is checked before the generic failure; `paid=True` default records a
  full Cash payment inside the same transaction; supports packages (`packages=None`, package-only
   basket valid, bundled supplies NOT stock-deducted). Tests needing an *unsettled* purchase pass
   `paid=False`. Its success box mirrors the Add Visit wizard's: `_show_success` offers OK + **Print**,
   where Print calls `_print_receipt(receipt_id)` → `ReceiptInfoDialog.print_for_client(parent=…)`
   (same client copy + full-payment gate). Test stubs: `tests/test_quick_purchase_dialog.py`
  `silent_dialog` stands in for the constructed box (a real modal `exec_()` access-violates offscreen)
  and `test_rbac_workflow` stubs `_show_success`.
- Add General Expense: `add_general_expense(..., receipt_code=None)` auto-allocates `EXPENSE-###`
  (the old hardcoded `'Expense'` collided with the UNIQUE column on the second expense);
  `receipt_other.category` + `receipts.notes` are persisted (migration `018`) and `update_receipt`
  deliberately does NOT touch `category`. Expense Type column renders in `state_danger`.
- **Dialog tests:** stub `QMessageBox.information/warning/critical/question` (and replace
  `_show_results` where present) or offscreen pytest **access-violates the whole process**; pass a
  **real** user id (`repos["user"].add_user(...)`) because `receipt_adjustments.adjusted_by` is FK.
- Tests: `tests/test_payment_repo.py`, `tests/test_receipts_page.py`,
  `tests/test_edit_receipt_dialog.py`, `tests/test_receipt_info_dialog.py`,
  `tests/test_receipt_adjustment_repo.py`, `tests/test_visit_info_dialog.py`,
  `tests/test_quick_purchase_dialog.py`, `tests/test_sales_repo.py`.

### Stock & batches (invariant: `supplies.current_stock == SUM(stocks.quantity)`)

- Schema: `stocks.expiry_date` + `stocks.buy_price` (migration `021`, backfilled) are per-batch;
  `supplies.expiry_date`/`buy_price` remain the item defaults used by the supplies page and expiring
  reports. `stocks.receipt_id` (migration `023`) links a batch to the expense receipt it was bought
  on so a correction **amends that receipt** instead of minting a fresh `EXPENSE-###` every edit
  (falls back to a standalone receipt if the link is gone — `ON DELETE SET NULL`; pre-023 batches
  adopt a receipt on their first correction via `stamp_batch_receipt`; **no backfill**).
- **`_batch_row` must normalize Qt's `''`-for-NULL to `None`** for `supplier_id`/`expiry_date`/
  `buy_price` — re-binding `''` into the `supplier_id` FK makes the whole UPDATE fail silently.
- `stock_repo._settle_batch_change(db, supply_id, delta, movement_type, unit_price, note,
  receipt_date, user_id, receipt_id=…)` is the single choke point for ALL batch writes
  (`add`/`update`/`delete_stock_batch`, each taking `user_id=None`): (1) **recompute**
  `current_stock` from the batches (`SET current_stock = (SELECT COALESCE(SUM(quantity),0) …)`, NOT
  `+= delta` — repairs past drift), (2) signed `stock_movements` row via `record_movement`, (3) post
  `delta * unit_price` as an expense receipt via `sales_repo.log_stock_adjustment`. `delta == 0`
  (price/date/notes-only edit) stops after step 1. Movement types: `purchase` (+), `adjustment` (±),
  `removal` (−), and on the sales side `sale` (−) / `sale_return` (+). Signed amounts are
  intentional (expense receipts carry `owner_id = NULL`, so owner balances never see them; revenue
  queries filter on `receipt_kind`).
- `stock_repo` imports `sales_repo` **inside** `_settle_batch_change` — `sales_repo` imports
  `stock_repo` at module level, so a top-level import would cycle.
- `user_id=None` writes no audit row (the ledger still updates); when present, the audit target is
  table `stocks`, labelled **"stock batch"** in `audit_repo._TABLE_LABELS`.
- FIFO depletion: `consume_batches(db, supply_id, qty)` / `return_to_batch(...)` run **inside the
  caller's transaction on the caller's connection** (never call `get_connection()` yourself), finish
  their queries, draw oldest `purchase_date` first (a used batch stays at 0 so purchase history
  survives), return `None` when batches can't cover the amount; `return_to_batch` adds to the newest
  batch. **Every `UPDATE supplies SET current_stock` must be paired with one** — call sites:
  `visit_repo.add_visit`, `create_sale_receipt_for_quick_purchase`, `sales_repo.update_receipt._delta_stock`
  (delta sign decides direction). Restocks create their own batch via `supply_repo._add_stock_batch`
  (which also logs a `purchase` movement).
- Supplies page: `search_supplies` returns BOTH `current_stock` (live — stock checks, restock math,
  reports) and `batch_quantity` (`SUM(stocks.quantity)` — the page's Quantity column + low/out-of-stock
  highlight); the two track each other since batches deplete. Batch editor expiry uses sentinel
  `NO_EXPIRY_DATE = QDate(1900,1,1)` → `None` (an unset expiry is never inherited).
- Edge contract: `update_stock_batch(-1, …)` / `delete_stock_batch(-1)` return `True` with **no**
  sync/movement/receipt/audit (`tests/test_repo_edge_cases.py`).
- Live refresh: `StockBatchDialog.batches_changed = pyqtSignal()` → `SuppliesPage.on_link_clicked`
  keeps the dialog reference, connects it to `refresh_all_tabs()` + `data_changed`, then `exec_()`s
  the dialog (page updates while the dialog is open). The expiring report filters
  `COALESCE(st.quantity,0) > 0` so dead batches don't show.
- **Still open (not fixed):** `supply_repo.update_supply` (only reachable through
  `pending_changes_repo`) sets `current_stock` from its payload and never touches the batches;
  `update_supply_stock` with a *decrease* lowers `current_stock` with no compensating batch;
  `_add_stock_batch` posts no `receipt_id` on its movement (its expense receipt is created separately).
- Tests: `tests/test_stock_repo.py`, `tests/test_supply_repo.py`, `tests/test_supply_dialogs.py`.

### Excel / CSV import & export (Settings → Database Backup)

- **Engines are UI-free:** `src/core/importer.py` (reads `.xlsx`/`.xlsm` via openpyxl and
  `.csv`/`.tsv`/`.txt` via stdlib csv with encoding fallbacks `utf-8-sig` → `cp1256` → `latin-1`;
  `ImportTable(headers, rows, row_numbers, sheet_name)` where **`row_numbers` are 1-based FILE rows**;
  two-pass `match_columns`/`normalize_header`, `detect_entity` needs ≥2 matched fields; coercers
  `to_number`/`to_int`/`to_bool`/`to_date`/`to_datetime`/`parse_items`) and `src/core/exporter.py`
  (never imports `tr`). The importer imports `tr` from `src.utils.i18n` (still no Qt) so workbook
  text follows the app language.
- Core API: `import_table(entity_key, headers, rows, row_numbers=None, user_id=None, dry_run=False,
  context=None)` → `ImportSummary(imported/skipped/failed/results)`; `dry_run=True` is the dialog's
  **Validate**. Entities: `IMPORT_KEYS` = 16 (owners, pets, suppliers, supplies, packages,
  package_items, appointments, visits, followups, vaccinations, medications, treatments, tests,
  expenses, retail_sales, payments; == `exporter.EXPORT_KEYS`). A missing required
  COLUMN fails every row; rows are try/except-wrapped so one bad row can't kill the run.
- **Duplicates are SKIPPED, never overwritten** (owners by exact name+phone, pets by name within the
  owner). `_Context` caches lookups per run: `resolve_owner` auto-creates a missing owner, and
  **`remember_owner` / `remember_pet` / `remember_item` MUST be called after a successful add** —
  otherwise the next identical row imports twice / a Visits sheet can't see the pet the Pets sheet
  just added (both were real bugs). Dry-run planned records use `ctx.planned_id()` (negative ids).
- Visits need an existing pet; an unknown supply item, a bad date, or a `STOCK_ERROR|…` from
  `add_visit` fails only that row.
- Multi-sheet: `plan_workbook(path)` pairs every sheet with an entity (docs/unknown sheets →
  `ignored`, rest sorted into `IMPORT_KEYS` order) and `import_workbook(...)` shares ONE `_Context`
  across sheets — an owner created by sheet A resolves in sheet B whatever the order.
  `detect_entity` needs ≥2 matched fields, so the single-column suppliers sheet falls back to a
  `SHEET_NAMES` name match (`_entity_from_sheet_name`) when column detection returns None.
  `_Context` caches per-run: `resolve_owner` (auto-creates), `find_supplier`, `find_package_id`
  (DB fallback), `resolve_visit(owner, phone, pet, date)` for the visit-linked sheets
  (followups/vaccinations/medications/treatments/tests) — those resolve the parent visit by its
  owner/pet/date and FAIL with "…Import visits first." (NO auto-create). Payments resolve their
  receipt by `receipt_code`; owners/pets/suppliers/packages for other sheets resolve the same way
  with auto-create only for owners.
  `is_instructions_sheet(name)` (aliases incl. `readme/help/notes/about`) gates the dialog: that
  sheet can never be validated or imported.
- Templates are **headers only** (a demo record must never reach the DB): Excel = 2 sheets
  (`Template` with bold frozen header + per-header openpyxl Comments, `Instructions` with the
  column table), CSV = header row only. `write_template` / `write_all_templates(directory,
  file_format=None)` default to `.xlsx`. The Settings page's two buttons (`import_templates_btn` /
  `import_templates_csv_btn`, in the `export_group`, classes `template-action`)
  are the **single entry point** — the dialog's Save Template was removed. `write_table_file` is the
  single file writer (`rows=None` → template); never hand-roll a workbook. The Database Backup tab
  is card-based: QSS classes `page-title` / `backup-card` / `backup-status` in `assets/style.qss`;
  its three QGroupBoxes (`restore_group`/`import_group`/`export_group`) stay DIRECT children of the
  scroll content widget (test `test_import_group_lives_on_the_backup_tab`).
- Export mirrors the import columns so an export can be edited and handed straight back:
  `export_rows(entity_key)` keys rows by **spec field name** (not dict order — a spec change can't
  silently shift a column), `write_workbook` (Excel button) = all entities in one `.xlsx`
  (`WORKBOOK_NAME = "pet_data.xlsx"`) via `importer.write_excel_workbook`, `write_all_exports`
  (CSV button) = one file per entity. New helpers in Support: item `get_*_for_export`,
  `supplier_repo.find_supplier_id`, `package_repo.find_package_id`, `payment_repo.add_payment/
  add_refund(payment_date=…)` for round-trip fidelity.
  Round-trip-safe values: `consult` = `Yes`/`No` (deliberately **untranslated** — Arabic wouldn't
  parse back), visit supplies flattened to `Name x2; Other` via SQL `GROUP_CONCAT`, `None` → `""`,
  appointment `status` raw (never derived "Late"), payment dates stored `YYYY-MM-DD`.
- **Receipt codes are preserved so payments reattach** (`sales_repo.get_receipt_id_by_code`): visits
  and expenses export their `receipt_code`, and `_import_visits` / `_import_expenses` /
  `_import_retail_sales` replay it (`receipt_code=` into `add_visit` / `add_general_expense` /
  `create_sale_receipt_for_quick_purchase`), **skipping** the row when the code already exists. The
  Payments sheet then resolves the same code. Dry runs register the planned code via
  `_Context.remember_receipt` so the Payments/visit-linked sheets validate too.
- **Retail Sales sheet** (`retail_sales`, `sales_repo.get_retail_sales_for_export`): standalone
  quick-purchase receipts (`receipt_kind='retail'` with supply lines), items flattened to
  `parse_items` form; imports with `paid=False` (the receipt's money comes from its Payments rows).
- **Re-importing an export is idempotent** — every entity dedups: owners (name+phone), pets (name
  within owner), suppliers (name+phone+location — a Suppliers-sheet row needs all three to be
  considered the same supplier, so two "Acme" rows with different contacts both
  import; the batch/supplies flow still resolves a bare supplier name via
  `get_or_create_supplier`, matching by name alone), supplies (name+category), packages (name), package items
  (package+type+item), appointments (pet+minute), visits (owner/pet/day), follow-ups (visit+date),
  vaccinations/medications/treatments/tests (visit+item name), expenses + visits + retail sales
  (receipt_code), payments (receipt+amount+method+day, checked against the DB **only** so two equal
  same-day installments in one file still both import on a first run). Supplies dedup is the fix for
  the old "re-import restocks every item" bug. New dedup checks go through `_Context.knows_row`
  (`_clinical` / `_package_items` / `_appointments` buckets) or a `*_repo.find_*_id` helper, and the
  record must be registered after a successful add (`ctx.remember_row`).
- **Validate (dry run) mirrors the real run for receipt-code rows**: `_import_expenses`,
  `_import_retail_sales` and `_import_payments` call `sales_repo.get_receipt_id_by_code` (and the
  payment signature check) **before** their `ctx.dry_run` branch, so an existing expense/retail sale
  reports SKIPPED in Validate too — previously Validate always said "will be added" while the real
  import skipped, which read as phantom duplication. Known residual: on a **first-time** import,
  stock-batch expense rows auto-created by the Supplies sheet can't be predicted in dry run (their
  codes are allocated at insert), so Validate may over-count those few rows; a re-import agrees.
- Gating: `SettingsPage._update_import_access` sets `setEnabled(can(user,"edit_records"))` on import,
  export and both template buttons. Import runs `create_backup(..., backup_kind="manual")` first and
  **aborts if the backup fails**; `_refresh_after_import(entity_key)` fans out refreshes like
  `admin_page._refresh_pages_after_restore`.
- Dialog: `src/ui/dialogs/import_data_dialog.py` (`data_changed = pyqtSignal(str)`); all-sheets mode
  uses `self._plan` + the `_all_sheets_available` flag — read the **flag, not `isVisible()`** (an
  unshown dialog reports every child as invisible).
- **Tests must stub `QMessageBox.*` (and replace `_show_results`) — a real modal `exec_()` under
  `QT_QPA_PLATFORM=offscreen` access-violates the whole pytest process.** Tests:
  `tests/test_importer.py`, `tests/test_exporter.py`, `tests/test_import_data_dialog.py`,
  `tests/test_settings_page.py`.
- **Maintenance checklist — do this whenever a domain/field is added elsewhere in the app:** the
  spreadsheet engine is NOT auto-derived, so a new entity, column or field must be wired in by hand
  or it silently drops/omits data. Concretely: (1) keep `exporter.EXPORT_KEYS == importer.IMPORT_KEYS`
  (an AST test guards most order/parity, but new keys must be added to both); (2) add/adjust the
  `_SPECS` entry (headers, required flags, `field_label`/hints) and, if it's a new entity, an
  `_import_*` handler in `_HANDLERS` + a builder in `exporter._ROW_BUILDERS`; (3) give it a dedup key
  so re-imports stay idempotent (`_Context.knows_*` and/or a `*_repo.find_*_id` helper, registered
  with `ctx.remember_*` after a successful add); (4) update the templates/Instructions sheet; (5)
  prove the export→import round-trip in `tests/test_exporter.py` + `tests/test_importer.py`.
  Also re-check this section for stale claims after such a change.
- **Temporary banner:** the Backup tab shows an `experimental-banner` warning label
  (`SettingsPage.backup_experimental_banner`, i18n key `"Note: importing and exporting data is an
  experimental feature…"`) while the spreadsheet engine is still new. Remove the widget, its
  `retranslate_ui` line, the QSS class and the i18n key once import/export is considered stable.

### Shared receipt card (single source of truth)

- `src/modules/receipt_card.py` builds **the** receipt card: `build_receipt_card(header,
  items, discount, total, *, receipt_id=None, paid=0.0, balance=0.0, client=False)` →
  `ReceiptCard` NamedTuple (frame + the labels/table). Callers: `ReceiptInfoDialog.
  _build_receipt_card` (thin wrapper; keeps `_receipt_frame` for the on-screen card),
  `BaseClinicalDialog._rebuild_receipt_card` (wizard preview) and
  `visit_dialogs.ReceiptDetailsDialog` — **never hand-roll receipt UI again**: the frame class,
  `receiptItems` table and client footer may only be drawn inside `receipt_card.py`, enforced
  by `tests/test_receipt_card.py::test_no_module_hand_rolls_a_receipt_card` (scans `src/`).
- The wizard passes `client=True` (thank-you footer, no payment strip) and no `receipt_id`
  (a pre-save preview has no number), so its preview is the **client copy** of the real card.
  Its consultation line is the literal `"Consultation"` (the saved receipt carries
  `services_lookup`'s raw name — don't translate it) and items follow `get_receipt_line_items`
  order: **supplies → consultation → packages**.
- `BaseClinicalDialog._rebuild_receipt_card` swaps the new frame **at the old frame's layout
  index** (hint above / billing bar below must not move) and re-aliases the `receipt_*`
  attributes tests read; `receipt_visit_no` is gone (the shared card has Date/Type/… meta rows).
- `is_expense_code`, `receipt_kind_label` and `fit_content_table` also live there
  (`receipts_page` re-imports them). The receipt's own items table is the exception to
  `fit_content_table`: `fit_receipt_items_table` **pins it to the rows' height and turns its
  scrollbars off**, so a long receipt shows every line (the card grows; the surrounding dialog
  scrolls) and the pixmap Print grabs can never be clipped. The estimate runs BEFORE the table
  sits at its real (480px card) width, so wrapped rows can end up taller than the pin — the last
  lines then clip *inside* the table with no scrollbar to fetch them (only the mouse wheel could;
  their hidden scrollbar answers it). Re-pin with `refit_receipt_items_table` (reads the header's
  REAL `sectionSize`s via `resizeSections`) wherever a layout lands afterwards: the wizard's
  `_refresh_scroll_extent` (when the receipt's step is current), `ReceiptInfoDialog._auto_fit_once`,
  and every print grab (`_render_receipt_pixmap`, `_render_client_receipt_pixmap`).  `ReceiptInfoDialog._auto_fit_once`
  re-pins `receiptItems` after layout and only `fit_content_table`s the payments/adjustments
  tables; the frame layout ends with a trailing `addStretch(1)` so a stretched wizard card pools
  spare height below the content instead of stretching the table. **The outer scroll must be told
  the page height explicitly:** Qt answers a `QScrollArea` with the *previous* step's extent when a
  `QStackedWidget`'s current page changes (or a page grows), so a long receipt was painted clipped
  with no scrollbar until a later relayout. `BaseClinicalDialog._refresh_scroll_extent()` pins the
  stack's minimum to the visible page's `minimumSizeHint` — called from `_sync_step` AND at the end
  of `_rebuild_receipt_card` (the wizard rebuilds the card while step 4 is already visible). Both
  render paths (`base`/`ReceiptInfoDialog._render_receipt_pixmap`, `_render_client_receipt_pixmap`)
  also grow the frame to `minimumSizeHint` right before `grab()`, so a stale layout can never print a
  clipped receipt. `ReceiptDetailsDialog` (the
  lightweight "view receipt" box, opened from `AddVisitDialog`) renders the client card from
  `sales_repo.get_receipt` + `get_receipt_line_items` (its `visit_date`/
  `client_name` args are only fallbacks for an unknown id) and hosts the card in its own
  `QScrollArea` (buttons stay pinned; a long card scrolls), like every other surface.
  Tests:
  `tests/test_receipt_card.py` (label+row signature parity vs the client card, delegation
  spies, the no-hand-rolled-card scan, the pinned-table/no-scroll guards,
  `test_billing_step_never_paints_a_clipped_receipt`).

### Add Visit wizard (`AddFullEntryDialog`, 4 steps)

- Layout rules guarded by tests: `step_forms[3]` stays item 0 of `step_bodies[3]`,
  `receipt_hint_label` item 1; the billing bar (discount % + live total) is ONE spanning row below
  the receipt — stacked rows break the height guards. **Step 3 (Other Supplies) is built like
  `QuickPurchaseDialog`**: `_setup_supplies_step` gives both lists `stretch=3`, and
  `AddFullEntryDialog._pad_step_pages` overrides the base to set *this page's* bottom spacer to
  stretch `0`. Qt splits a page's height by each item's share of the **total** stretch, so the
  base `addStretch(1)` spacer used to park 62–80px under the lists while they grew ~6px; with it
  neutralised both lists land at ~216px and the gap is gone. Guarded by
  `test_supplies_step_hands_its_spare_height_to_the_lists` (the old
  `test_supplies_list_is_not_stretched_past_its_rows` asserted the opposite and is gone).
- **The billing spin must NOT be named `discount_spin`** — `BaseClinicalDialog._update_total` reads
  `discount_spin.value()` as *cash* and subtracts it. This dialog uses `discount_percent_spin`
  (percentage, suffix `" %"`) and converts via cent-rounded `_discount_cash(subtotal)`.
  `handle_accept`: `update_total()` first → `visit_data['discount']` (cash) → `clinical_service` →
  `visit_repo.add_visit(discount=..., paid_amount=..., payment_notes=..., payment_method=...)`. The billing
  bar also carries an **Amount Paid** spin and a **Method** combo (see the next bullet); `visit_repo.add_visit`
  then records that cash as an instant payment in its own transaction (`receipts.payment_status` bound at INSERT;
  `payments` row only when `paid_cash > 0`), default `payment_notes="Paid at entry"`.
- **Same discount pattern in the other two purchase dialogs**: `QuickPurchaseDialog` and
  `BulkPurchaseDialog` (dashboard **Add Supplies**) each carry a `discount_percent_spin` + `_discount_cash`
  that drive a live total; the cash discount is passed into `create_sale_receipt_for_quick_purchase(discount=...)`
  (stored on the retail receipt before its full payment) or folded into the shared bulk-purchase expense
  receipt via `sales_repo.apply_receipt_discount(receipt_id, cash)`. Never use the base `_update_total`
  pattern on these — `discount_spin` as a percentage would be misread as raw cash.
- **Amount Paid at the counter (all three billing dialogs)**: each billing dialogs's bar/footer also
  carries an `amount_paid_spin` that defaults to the live discounted total (`_paid_touched` flip +
  `blockSignals` while syncing, so a custom figure is never overwritten; `_update_total` always
  updates the max) and a **`pay_method_combo`** (`Cash`/`Card`/`Bank Transfer`/`Other`, same list the
  ReceiptInfoDialog add-payment uses; `payment_method()` maps display index → English value). Quick
  Purchase forwards it as `create_sale_receipt_for_quick_purchase(..., paid_amount=..., payment_method=...)`
  (None = legacy `paid` flag behaviour; 0 = Unpaid, partial = Partial, full/over = Paid, clamped to
  total), `process_bulk_purchase_items(..., paid_amount=..., payment_method=...)` records it via
  `payment_repo.add_payment` on the shared expense receipt after the discount is applied, and
  `visit_repo.add_visit(..., paid_amount=None, payment_notes="Paid at entry", payment_method="Cash")`
  binds the receipt's `payment_status` at INSERT and writes its own `payments` row inside the same
  transaction (clamped to the total; no row when `paid_cash <= 0`). `AddFullEntryDialog` passes
  `payment_notes=tr("Paid at entry")`. `QuickPurchaseDialog.handle_accept` recomputes
  the total **from `get_final_items`/`get_final_packages`** at accept time (a monkeypatched/stale basket
  must settle with a real figure, not the spin's default) — tests rely on that.
- Existing-record guard: `_confirm_if_data_will_change()` (step-1 `_go_next_step`) lists changed
  owner/pet fields in a `QMessageBox.question`; declining keeps the wizard on step 1. It resolves the
  pet via `_found_pet`, which `pet_name.editingFinished` fills — **tests must emit that signal**
  (offscreen Qt has no real focus, focus-out cannot be simulated).
- Pet identity = name within the owner: `clinical_service.process_full_clinical_entry` looks up with
  `pet_repo.get_pets_by_name_for_client` and saves via `pet_repo.update_pet` (all fields).
  `get_existing_pet` survives only in `clients_page`. **Still open:** renaming a pet in this dialog
  creates a new pet; an owner phone change creates a duplicate owner.
- Wizard chrome all lives in `BaseClinicalDialog`: `_build_step_indicator`/`_clear_step_indicator`;
  clickable steps via `eventFilter` installed on `self`, each `_step_items[i]` AND its badge + title
  label (QLabel swallows mouse events) — `_max_step` lets you click back to, or forward to, an
  already-reached step only, so `_update_save_state` gates stay unbypassable; **tests must send a
  real `QMouseEvent` via `qt_app.sendEvent` — `QTest.mouseClick` would not hit the filter**.
  `_configure_form_layout` + `_cap_form_labels` (**call only AFTER all `addRow` calls**),
  `_make_form_card`, `bare_steps=(i,)` leaves an undetached but usable `step_forms[i]`.
- **No dead vertical space (rules generalize to any wizard dialog):** `_pad_step_pages()` appends
  `addStretch(1)` to each `step_bodies[i]` (appended LAST — stretched content only wins the slack
  if the spacer's factor is `0`). **The Add Visit wizard opens at 720px and fills it**: it sets
  `_fit_floor = ADD_FULL_ENTRY_DIALOG_HEIGHT`, and `_fit_dialog_height` clamps to
  `[_fit_floor, _design_height]` (default floor `BASE_DIALOG_MIN_HEIGHT`), so this dialog never
   shrinks to its tallest step. Its `_pad_step_pages` override handles each page differently: step 1
   gets spacer 0 + `stretch 1` on its two-card row (both form cards stretch down), **step 2 is left
   on the base behaviour** (its spare height stays in the bottom spacer — the clinical cards keep
   their natural height), step 3 zeroes its spacer so its `stretch=3` lists take the room, and step 4
   stretches `receipt_frame` so the billing bar sits on the page's bottom edge
   (`_stretch_receipt_to_fill_the_step`, re-applied by the `_rebuild_receipt_card` override because a
   rebuild inserts the new frame at stretch 0). `_make_form_card` ends its own layout with
   `addStretch(1)` so a stretched card drops its slack *inside its bottom* instead of spreading its
   heading/rows; its trailing spacer is therefore the card's LAST item — insert any extra content
   (the follow-up group) before it. `_collapsible_group(...)` hides an unticked
   group's children (`QGroupBox.setChecked(False)` only *disables* — it never hides them);
   `_initialise_step_layout()` = pad + `_fit_dialog_height()`, called as the **last line** of
   `AddFullEntryDialog.__init__` (after `_setup_receipt`, which appends to `step_bodies[3]`), with a
   `QTimer.singleShot` fallback; re-fits in `showEvent`. Tests:
   `tests/test_add_visit_dialog.py::TestNoDeadVerticalSpace` (per-step "content reaches the page
   bottom" on steps 1/3/4, "step 2 keeps the spacer" + the 720px default).
- Clinical Exam sections are `ClinicalSectionCard(QGroupBox)` **non-checkable** accordion cards with
  a branded chevron and a live `_refresh_section_summaries()` right label — a plain checkable
  QGroupBox force-disables its children while unticked, so a header drawn inside it paints as
  nothing. The card re-implements `isChecked`/`setChecked`/`toggled` itself (keeping the API tests
  use: `_section_content`, `_section_header`, `setChecked(has_records)` in `info_dialogs.py`).
  `group.toggle()` does **not** exist on QGroupBox. The consultation charge is a matching one-line
  `toggle-card` above them. QSS: `clinical-card*`, `wizardStepper`, `step-badge/-title/-counter`,
  `form-card*`, `secondary-action` — all palette-variable driven (`test_color_palettes.py` fails on
  an unknown `@var`).
- Recommended 4-step layout: **1 Patient & Visit** (two form cards side by side + follow-up group
  inside Visit Details) → **2 Clinical Exam** → **3 Other Supplies** → **4 Billing & Review**
  (receipt + billing bar). `reason_for_visit` is threaded to `visits.reason_for_visit` by both
  dialogs + `clinical_service`. `AddVisitDialog` (owner/pet selectors) is NOT opened by any page
  (re-exported only) but still builds against the base — keep it compatible. All Add Visit buttons
  open `AddFullEntryDialog`; `EditVisitDialog` is gone (admin edits open `VisitInfoDialog`).
  Step 4 has **no** Print/Export buttons — after `handle_accept` succeeds, `AddFullEntryDialog._show_success`
  opens a `QMessageBox` (Information, "Record added successfully."/Receipt ID) whose **Print**
  (ActionRole) button calls `_print_receipt` and whose **OK** (default) just closes, then the wizard
  `accept()`s. `_print_receipt` is overridden in `AddFullEntryDialog`: it prints the **saved receipt
  through `ReceiptInfoDialog.print_for_client(parent=…)`** — the Receipts page's **Print for Client**
  behaviour verbatim: the client copy of the card and the full-payment gate ("Not Fully Paid" refusal).
  An unbilled visit (no receipt) falls back to the step-4 preview. The id comes from the `ids_out`
  dict param threaded through `clinical_service.process_full_clinical_entry`
  → `visit_repo.add_visit` — the plain return is ambiguous (receipt id OR visit id). Tests stub `_show_success`
  (see `_silence_message_boxes` in `tests/test_add_visit_dialog.py`).
- Test gotchas: measure layouts with a realistic font (`Segoe UI`, 9pt) — offscreen rendering
  defaults to Helvetica 12pt and fakes scrollbars; offscreen can't rasterise font glyphs under the
  app QSS, so pixel-verify backgrounds/borders only and prove text via geometry; accept-path tests
  must set a **pet name** (`visits.pet_id` is NOT NULL) and stub `QMessageBox.*`.
- Tests: `tests/test_add_visit_dialog.py`, `tests/test_clinical_service.py`.

### Record-book clinical exam (wizard step 2)
- **Step 2 of `AddFullEntryDialog` is the normalized record-book exam, NOT the old clinical
  sections.** `AddFullEntryDialog._setup_record_exam_sections` builds six collapsible
  `ClinicalSectionCard`s — General Physical Examination / Clinical Signs / Routine Tests /
  Vaccinations / Physical Exam / Recommended Tests & Treatments — reusing the mixin's
  `_collapsible_group`; the consultation toggle card stays on top. The old
  `ClinicalSectionsMixin._setup_clinical_sections` / `get_clinical_data` are **still used by
  `VisitInfoDialog` and the dead `AddVisitDialog`** — do not delete them.
- Wizard collection = `AddFullEntryDialog.get_clinical_exam_data()` (camelCase record-book shape)
  → `clinical_service.process_full_clinical_entry(clinical_exam=…)` → `visit_repo.add_visit`
  → `clinical_exam_repo.save_clinical_exam` (9 tables, migration `025`). `handle_accept` no longer
  passes `health_stats/tests/treatments/vaccinations/medications`, so the wizard no longer writes
  those legacy tables (intended; the other entry points still do).
- The schema source of truth is the code: `clinical_exam_repo.py` (the 9 tables' read/write shape)
  + `schema_definitions.clinical_exam_tables` + migration `025`. Tests:
  `tests/test_clinical_exam_repo.py`, `tests/test_add_visit_dialog.py::TestRecordBookExamSections`.

### Undo/restore for deletes (owner / pet / visit / appointment)

- Journal: `deleted_records` (DDL in `schema_definitions.py` + migration `_m_017`) — `snapshot` TEXT
  (JSON) of the record + every cascade child; restored rows are hidden (restore is one-shot).
  Engine: `src/core/repositories/undo_repo.py` — `capture_snapshot` BEFORE the delete,
  `record_deletion` only when the delete returned True (**missing-record deletes journal nothing**),
  `restore_deleted_record(id, user_id)` re-inserts rows in `_RESTORE_ORDER` (parents first) inside
  ONE transaction, applies relink UPDATEs (SET NULL links: `receipts.receipt_adjustments.visit_id`
  when a visit dies but receipts survive; `visits.appointment_id`), marks `restored_at`, records a
  `RESTORE` audit.
- **Gotcha:** this schema stores absent FKs as the empty string `''` (an invalid FK id) — restore
  rebinds every `''` to SQL `None` (`q.addBindValue(None if v == "" else v)`) or re-inserting
  `visits` with `appointment_id = ''` fails `FOREIGN KEY constraint failed`.
- Only those 4 deletes are journaled (call sites in `client_repo`/`pet_repo`/`visit_repo`/
  `appointment_repo`); supply/receipt/payment/lookup deletes are NOT.
- UI: `RestoreDeletedPanel` in `src/ui/pages/admin_panels.py` IS the **Restore Records** tab of the
  Admin page (gated `edit_records`); its `record_restored` signal drives
  `AdminPage._refresh_pages_after_restore`. Loads lazily (`__init__` never queries).
- Tests: `tests/test_undo_repo.py`, `tests/test_admin_panels.py`.

### File map & known hot spots

Use this to navigate without re-scanning the tree. **Big files — grep/offset, never read whole:**
`info_dialogs.py` (1976), `sales_repo.py` (1491), `base_clinical_dialog.py` (1383),
`importer.py` (1307), `settings_page.py` (1030), `analytics_repo.py` (995), `dashboard_page.py` (900),
`migrations.py` (885), `database_pages/receipts_page.py` (882), `schema_definitions.py` (776),
`reports_pages/reports_page.py` (756), `visit_repo.py` (717), `database_pages/supplies_page.py` (691),
`database_pages/visits_page.py` (664), `reports_pages/base_tab.py` (651).
Splits (import paths preserved): `settings_page.py` → `settings_palette_mixin.py`;
`main_window.py` → `pages/main_page.py` (`MainPage`, `ICONS`, status-bar constants);
`visits_page.py` → `dialogs/quick_purchase_dialog.py` (re-exported for
`tests/test_rbac_workflow.py`: `visits_page.QuickPurchaseDialog`).

#### Reports center (`src/ui/pages/reports_pages/`)
- `reports_page.py` = `ReportsPage` wrapper: pinned **slim** header (title/actions + period
  trigger / Day–Custom segment / exports; `QCalendarWidget` + presets live in a `Qt.Popup`) +
  archive banner + `QTabWidget` of
  5 tabs that fill the rest and never resize. **There is NO outer page scroll** — each
  `BaseReportTab` owns an internal `QScrollArea` (`self._scroll`, `widgetResizable=True`,
  `scroll_to_top()`); per-tab scrolling is what fixed the stretch/glitch (a single outer scroll
  lagged one event tick and painted the old tall geometry over the new short content).
- Tabs = one file/class each, extending `BaseReportTab` (`base_tab.py`): `overview_tab`,
  `financial_tab`, `patient_tab` (owns `clinical_table`), `supply_tab`, `audit_tab` (owns
  `audit_table`). **Every report piece belongs to exactly one tab**; exports/print
  (`ReportsPage._build_excel_sections`, `_export_current_report_csv`, `_print_current_report`) emit
  only the active tab's sections. Tests use `page.tabs` + `page.report_tabs[i]`.
- `BaseReportTab` shared helpers: `_make_section_title_bar`, `_create_kpi_card`,
  `_create_insight_table_card`, `_create_analytics_table_card`, `_create_chart_with_controls`,
  `_refresh_charts_content` / `_refresh_supply_charts_content`, `update_chart_theme`,
  `current_range`, `_set_table_rows`, `_refresh_stats`/`_refresh_insights`, `load_archive`, base
  `retranslate_ui`.
- Rules that keep it stable: **keep strong refs to cards in `self._cards`** (shiboken frees
  local-only widgets → child labels vanish, e.g. the patient/supply `low_stock` crash); **height
  caps** — insight tables `setFixedHeight(132)`, analytics tables 176–296, `audit_table` ≤ 320,
  `clinical_table` ≤ 260, every chart ≤ `LAYOUT_CONFIG["chart_max_height"]` (250); chart rebuilds
  run with **updates disabled** (never paint provisional oversized geometry); clear layout widgets
  with `_detach_orphan_widget` (setParent(None) + deleteLater), not bare `deleteLater`. Charts have
  **no per-chart period buttons** — all trend/supply charts follow the calendar range
  (`ReportsPage.refresh_data()` → `update_range`); set `self.viewing_archive` to suppress refreshes
  while archive view is open (`viewing_archive` flag on `ReportsPage` too).
- **Reports Workspace (period bar + navigator calendar + History panel):** the header is a *compact
  period bar* (two rows, no always-visible calendar — 720p must keep the tabs as the main surface).
  The date button opens a popup with quick presets (Today/This Week/Last Week/This Month/Last Month/
  This Quarter/Year to Date, calendar-aligned via `_preset_window`) and the navigator calendar; the
  bar itself has a Day/Week/Month/Quarter/Year/**Custom** segment, `‹ ›` nudge arrows (`_nudge`:
  standard types step by their natural unit; Custom/Preset shifts by the window's own length) and a
  friendly window title (`_period_title`, presets included) + live summary pill. Granularities 6
  days/1 month/1 quarter/1 year all **end** at the clicked day; presets apply an explicit
  `_custom_range` and set `_granularity="Custom"`. The `QCalendarWidget` is a **pure navigator** —
  clicking a day always shows **live** data for that window (never auto-opens a snapshot); it just
  marks saved-report days (bold brand day number) and tints the active custom span. Choosing Custom
  with no range auto-opens the popup for the two-click span.
- **Saving is explicit, and the archive is a history log:** `save_snapshot` always **INSERTs a new
  row** (no window-keyed upsert) — every "Save Report" is a deliberate point-in-time record (the repo
  keeps both if you file the same window twice). `_save_current_report` is gated by `view_reports`,
  refuses the Audit tab, and refreshes the panel + calendar. On top of that, `_maybe_daily_checkpoint`
  (called at the top of `refresh_data`) **auto-saves one `Day` snapshot per savable category** for
  **yesterday** — a complete day — the first time the page runs on each new day, so the history always
  has a daily record even if nobody presses Save (once-per-day guard = the `last_report_checkpoint`
  setting in `SettingsManager`; the marker is left unset on failure so the next refresh retries).
  The right-side **Report History** panel
  (`_setup_history_panel`; hidden/shown by `history_toggle_btn`/`history_collapse_btn`) lists
  `search_archives(text)` grouped by saved day with Open/Compare/Export/Delete; double-click opens.
  Open loads the snapshot into its owning tab (`_open_archive`, banner "Viewing archived report …");
  `Back to Live Data` (`_exit_archive_view`) always refreshes and, if Custom has no completed
  selection, falls back to `Day` (else `refresh_data()` early-returns). **Custom = two-click span**
  (`_custom_range`/`_custom_pending`; `refresh_data()` early-returns while the start is pending).
  `list_archive_days`/`list_archives_for_day` anchor on `period_end` (fallback `generated_at`).
  Compare opens `src/ui/dialogs/compare_reports_dialog.py` (`CompareReportsDialog`, metric table with
  signed deltas). Tests: `tests/test_report_archive_repo.py`, `tests/test_reports_page.py`,
  `tests/test_compare_reports_dialog.py`. New QSS classes: `reports-history-*`, `reports-preset-chip`,
  `reports-nudge`, `reports-period-trigger`, `reports-calendar-popup`.
- Analytics: `analytics_repo` `*_range` helpers share `_date_conditions(column, start, end)`; trend
  bucketing via `_trend_bucket`/`_trend_date_series` (single-day → hourly, ≤35 days → daily, else
  monthly, zero-filled). Excel export via `src/utils/excel_export.py` + openpyxl (imported lazily).

#### Dialogs (`src/ui/dialogs/`)
- **Footer rule (OK/Cancel must stay glued to the bottom):** a dialog's root layout is a
  `QVBoxLayout` holding the form (`QFormLayout()` — NOT `QFormLayout(dialog/self)`, which pins the
  form as the root so every resize pushes the buttons up), then `addStretch(1)`, then the button row.
  Measured in `tests/test_dialog_footer_pinning.py` (gap ≤ 40 px, drift ≤ 6 px when grown 150 px) —
  extend that test when adding a dialog.
- `info_dialogs.py` (biggest file): `InfoDialogMixin` (shared `_make_card`, `_clear_layout`,
  `_detail_row`, `_kpi_stat`, `_history_row`, `_badge`, `_build_footer`, `_set_edit_buttons`,
  `_can_edit`, `_can_write`, `_notify_parent_changed`), `OwnerInfoDialog` (card grid; `owners.notes`
  is only ever written here; Finances edit mode offers **Settle Outstanding** via
  `sales_repo.get_open_receipt_balances_for_owner` + `payment_repo.add_payment`), `PetInfoDialog`
  (2-col grid; `GENDER_OPTIONS = ["Female", "Male", "Other"]`; `pets.notes` written only here —
  `update_pet` preserves notes when `notes is None`; edit = admins write direct, others submit a
  pending `pets` UPDATE), `VisitInfoDialog` (see Receipts section). Edit mode for non-admins is
  always a `pending_changes_repo.submit_change`. Click-through rows close the parent dialog first
  (`_close_and_open`) then emit `data_changed`.
- `full_entry_dialog.py` / `visit_dialogs.py` / `base_clinical_dialog.py` — the wizard (see the
  Add Visit section above).
- `pet_medications_dialog.py` — read-only meds grouped per visit
  (`medication_repo.get_medication_history_by_visit`).
- `suppliers_dialog.py` — supplier CRUD, opened by the `suppliers_btn` corner button on
  `SuppliesPage` (same `add_supplies` gate as its sibling corner buttons); it used to live on the
  Admin page / Settings.
- Others: `appointments_dialog.py`, `followup_dialog.py`, `reminders_dialog.py`,
  `pending_changes_dialog.py`, `package_dialog.py` (`PackageDialog` — wired, kept),
  `stock_batch_dialog.py`, `login_dialog.py`, `first_run_dialog.py`, `role_editor_dialog.py`,
  `custom_permissions_dialog.py`, `permission_group_widget.py`, `import_data_dialog.py`,
  `edit_receipt_dialog.py`, `visit_adjust_dialog.py`, `quick_purchase_dialog.py`,
  `pet_health_timeline_dialog.py`, `supply_reorder_dialog.py`, `vaccine_schedule_dialog.py`.

#### Pages (`src/ui/pages/`)
- `dashboard_page.py`, `settings_page.py` (+ `settings_palette_mixin.py`), `main_page.py`
  (`MainPage` + status-bar constants), `admin_page.py`, `admin_panels.py`.
- `database_pages/`: `database_page.py` (hosts sub-pages), `clients_page.py` (Clients+Pets,
  `BaseEntityPage`), `visits_page.py` (standalone `VisitsPage` owning Visits+Appointments;
  `my_visits_page.py` lives here too and imports `HOME_COLUMN_MAP` from it), `supplies_page.py`,
  `receipts_page.py`.
- `reports_pages/`: `reports_page.py` (the real `ReportsPage` — there is **no shim** at
  `src/ui/pages/reports_page.py`; `main_page.py` imports from `reports_pages.reports_page`
  directly).
- `admin_panels.py`: `UserManagementPanel` (user table + Add/Rename/Edit Roles/Permissions/Custom
  Roles/Reset Password/Delete row) and `RestoreDeletedPanel`. Page protocol both expose:
  `refresh_data()` / `set_current_user(user)` / `clear_selection()` / `retranslate_ui()`.
  **Neither queries the DB in `__init__`** (AdminPage loads tabs lazily on show/tab switch) and the
  layout is strict: `addWidget(table, 1)` first → action row last with **no trailing
  `addStretch(1)`** (buttons pinned to the bottom edge; guarded by `test_admin_panels.py`).
- `admin_page.py`: admin-only top-level side-menu page (between visits and settings, gated
  `can(user,"manage_users")`), tabs host `admin_panels` directly + a page-level Save/Cancel row.
  Gate tabs with `tabs.setTabVisible(index, allowed)` (Qt 5.15+) — **never `panel.setVisible()`**:
  QTabWidget owns page visibility, forcing a panel visible stacks the inactive tab on top of the
  current one (`test_admin_page_never_shows_the_inactive_tab`). Permission edits only take effect
  at the target user's **next login**. Stack order must stay in lockstep with
  `side_menu.MENU_ITEMS_CONFIG` (AST test `test_nav_config_matches_main_page_stack_order`).

#### Repos (`src/core/repositories/`) — one per domain, all wrap SQL
client, pet, visit, appointment, sales, stock, supply, supplier, user, audit, log, medication,
vaccination, treatment, test, package, followup, health_stats, pending_changes, receipt_adjustment,
payment, undo, lookup, client_loyalty, pet_health_timeline, vaccine_schedule, report_archive,
analytics_repo, analytics_cache (`conftest.py` auto-discovers `*_repo.py` into `_REPO_NAMES`).

#### Core wiring
- `main.py` → `MainWindow` (main_window.py) → `MainPage` (stacked `main_page_content`) →
  6 pages (dashboard, database, reports, my_visits, admin, settings) + `DatabasePage` sub-stack.
- Side-menu nav buttons connect via `lambda checked, idx=...: self.main_page.main_page_content.setCurrentIndex(idx)`
  in `main_window.py` (`_sidemenu_connections`) — the old `partial(setCurrentIndex, page_index)`
  crashed because `clicked(bool)` passed an extra arg → TypeError.
- `main_window.py` owns cross-page `data_changed` signal wiring; role gating via
  `src/core/permissions.py` (`can`, `is_admin`, `is_doctor`, `is_staff`).

#### RBAC: role templates + per-user overrides
- **Model:** `can(user, action)` resolves in this order: per-user override → role
  templates (`role_permissions`) → static defaults (`_PERMISSIONS`). Deny-by-default.
- **Roles are editable templates**: `role_permissions(role_id, key)`; built-in
  `admin/doctor/staff` are `is_system=1` (can't rename/delete) but their templates ARE
  editable. `admin` is lockout-proof: **admin's effective set is always `ALL_ACTIONS`
  minus `ADMIN_CARVE_OUT`** (`view_visits` intentionally excluded — the doctor-only
  page; `tests/test_rbac_workflow.py` asserts `can(admin,'view_visits') is False`).
- **Per-user overrides**: `user_permissions(user_id, key, override)` where
  `-1`=inherit, `0`=deny, `1`=allow. Rows with `-1`/inherit are deleted on save.
- **Caching:** login/load attaches `user["_role_permissions"]` (set) +
  `user["_permissions"]` (dict) via `user_repo._attach_permissions`. `can()` uses those
  caches; falls back to static `_PERMISSIONS` only when absent (tests build bare dicts).
  **Template/override edits take effect at the user's next login/reload** — the current
  logged-in user is NOT live-refreshed.
- **Catalog:** `PERMISSION_CATALOG` = 6 sections × 20 actions in `permissions.py`
  (section key + `(action, display_key, desc_key)` per row; keys are i18n strings in
  `assets/translations.json`). `ALL_ACTIONS` = union of catalog.
- **Dialogs:** `role_editor_dialog.py` (RoleEditorDialog: left role list + New/Rename/Duplicate/
  Delete, right grouped checkboxes; system badge), `custom_permissions_dialog.py`
  (CustomPermissionsDialog: per-user Inherit/Allow/Deny radios with live "effective" column),
  `permission_group_widget.py` (shared collapsible sections; modes `check`/`tri-state`). User
  Management gained **Permissions** + **Custom Roles** buttons and an **Overrides** count column.
- **UIs already gated by `can()`** use the new layer automatically. Remaining raw
  `"admin" in roles` checks (main_window greeting/account menu, reminders_dialog) are
  identity/scoping, intentionally not switched.
- Schema: `role_permissions`, `user_permissions`, `roles.description`, `roles.is_system` —
  migration `014_rbac_role_permissions` (seeds built-in templates ONCE via `_migration_recorded`
  guard; edits persist after). `seed_permissions_for_role` in `permissions.py` is the single
  source for built-in defaults.
- **Every catalogued action is enforced** (no more defined-but-unused keys): `backup_restore`
  gates the Settings Database Backup buttons + create/restore handlers
  (`SettingsPage._update_backup_access`), `reset_passwords` gates the Reset Password button
  (`UserManagementPanel._apply_permission_gating`, re-run from `set_current_user`). The Admin tab
  itself needs `manage_users` **or** `reset_passwords` (`AdminPage.refresh_section_visibility` +
  `MainPage` nav gate), so a reset-only grant is reachable; every other user-panel action still
  re-checks `manage_users`.
- `UserManagementPanel` can **never delete the last admin**
  (`user_repo.count_users_with_role("admin") <= 1` → `Cannot Delete` warning) and **warns before
  a self-delete** (generic confirm becomes an explicit "you will be logged out" question).
- `user_repo.get_users_with_roles()` batches the user table (3 queries, not N+1); `add_user`
  resolves the role **before** inserting and returns `None` for an unknown role (no role-less
  ghost accounts). Migration `028_sync_builtin_role_permissions` re-runs
  `seed_permissions_for_role` **additively** (`INSERT OR IGNORE`) so a permission added to the
  catalog reaches existing doctor/staff templates — built-in template edits are preserved.

### Known issues / dead code (verified, not yet fixed)

These are safe references; don't re-investigate unless the task touches them.
- **Dead classes:** `ReorderSettingsDialog` (file deleted); `PackageDialog` was vetted and KEPT —
  it is wired to `supplies_page.py` (`packages_btn` → `_open_package_dialog`). `_LegacyVisitsPage`
  removed. `AddVisitDialog` is dead code (no page opens it) but still must build against
  `BaseClinicalDialog`.
- **Dead constants:** `constants.py` `DATE_FORMAT_SQL`, `SUPPLY_SUB_CATEGORIES`,
  `DEFAULT_LANGUAGE`, `STOCK_COLORS`; `cards.py` `LAYOUT_CONFIG`.
- **Security:** the stock seeded `admin/admin123` account is neutralized on first run by
  `FirstRunDialog.accept()` (reset when the clinic chooses `admin`, otherwise deleted —
  `tests/test_first_run_hardening.py`); the seed still inserts it for migrations/tests. Password
  hashing is PBKDF2 (`hash_secure`), backup encryption is Fernet (legacy hashes/keys still
  readable). SQL-injection vectors in the repos were whitelisted/parameterized (see Hardening).
- **Legacy data migration** is vetted + fixed — see the section below; `tests/test_legacy_migration.py`.
- **No UI bypasses repos:** no `QSqlQuery`/`get_connection`/raw SQL anywhere in `src/ui/` or
  `src/modules/` (the only matches are `exec_()`/`exec()` dialog invocations) — re-verify on
  future UI work.
- **`tr()` coverage:** `first_run_dialog.py` fully wrapped; the dashboard `add_visit_btn` /
  `quick_purchase_btn` already use `tr()` (older notes saying otherwise were stale).
- **First-run dialog styling + language:** shown *before* `MainWindow`, so it applies its own
  `get_styled_qss(...)` locally (banner `first-run-*` classes + shared `form-card`) — don't assume the
  app stylesheet is active yet. Its `language_combo` calls `load_translations` then `_retranslate_ui`
  (works because `i18n.tr` reads the live global). **`SettingsManager.set` is deferred to `accept()`**
  (`_finish`): writing settings.json earlier would make `main.py`'s `SETTINGS_FILE.exists()` check
  skip onboarding on the next launch. Only the footer's Cancel/Continue `QPushButton`s are used (no
  `QDialogButtonBox`).
- **Remember Me (auto-login)** is implemented in `main.py` (via `SettingsManager`
  `auto_login_user`, when the user still exists).
- **Identity/greeting:** `users.username` is the single source of truth for a display name (the old
  `user_name` setting was removed; renames happen only via Admin → User Management → Rename
  Username, `user_repo.rename_user`). Greeting: logged in → `user.get("username")`, logged out →
  `DEFAULT_CLINIC_OWNER`. Settings Identity rows: 0 = Clinic Name, 1 = Custom Logo.

### Legacy migration (`legacy_migration.py`) — archive-then-migrate

- **Two upgrade inputs, one code path.** A genuine **v1.0.0** DB has ONLY the old tables
  (`clients`, old-shaped `pets`/`visits`/`appointments`/`supplies`/`receipts`, `receipt_items`,
  `supply_reorder_levels`); a **hybrid** DB (the historical state older installs settled into) has
  the new-shaped tables PLUS the legacy source columns/rows. `initialize_schema` runs
  `archive_legacy_tables(db)` **before** creating the base schema: when `clients` exists AND
  `pets` has no `pet_id` (strict detection), each old-shaped table is copied to a
  constraint-free `_legacy_<name>` (`CREATE TABLE _legacy_x AS SELECT * FROM x`, stale archive
  dropped first) and the original dropped (FK toggled off), so `CREATE TABLE IF NOT EXISTS` can
  build the new shape. `migrate_from_legacy` reads `_source_table(db, name)` (the `_legacy_<name>`
  copy when present, else the live table) and drops `clients`/`receipt_items`/
  `supply_reorder_levels` + every `_legacy_*`; `_run_legacy_repair` (called when `clients` exists)
  re-drops them as cleanup. Never re-add a bare `FROM pets`/`visits`/… read here — it would hit the
  old-shaped table on a v1.0.0 DB.
- **Why the archive exists:** `CREATE TABLE IF NOT EXISTS` is a no-op against the old shape, so
  migration INSERTs into new column names (`owner_id`, `pet_id`, `current_stock`, `total_price`,
  `receipt_kind`) silently mismatched columns = data loss + a hard crash in migration `021`. The
  archive is the fix; the old `DROP TABLE clients` (`foreign key mismatch`) and
  `_rebuild_visits_without_client_id` (`no such column: visit_id`) failures followed from it.
- **`receipt_code` must be unique:** it was `receipt_type[:10]` ("Sale" for every receipt) and
  collided on the UNIQUE column with >1 same-kind receipt. New codes are
  `{VISIT|RETAIL|EXPENSE}-{legacy_id:04d}`. Visits link to their own legacy `pet_id` (via
  `pet_map`), falling back to the owner's first pet only when absent.
- **QtSql locking:** `DROP TABLE` needs an exclusive lock, so any active statement on
  `sqlite_master` (the `_run_legacy_repair` `detect` SELECT, now finished **before** calling
  `migrate_from_legacy`) makes every drop fail with `database table is locked`; the
  schema-creation query, index/column helpers and `_backfill_created_at` also `.finish()` now.
- Historical bugs already fixed (snapshot-then-iterate to stop the self-feeding infinite loop;
  `supplies.quantity` is column index **8**, not `sell_price`; explicit `owner_map`/`pet_map`/
  `visit_map` id remapping) — don't re-litigate them.
- Tests: `tests/test_legacy_migration.py` — `pure_v1_db` fixture = exact v1.0.0 DDL via
  `initialize_schema` (the real upgrade path); `legacy_db` fixture = the hybrid state.
  **Gotcha:** legacy FK seed values must reference legacy `id` values (e.g.
  `receipt_items.receipt_id` = the legacy `receipts.id`), since the migration looks rows up by the
  legacy id.

### Hardening pass

- `lookup_repo.py` wraps `stat_types_lookup`/`states_lookup`/`categories_lookup`/`services_lookup`
  reads (`get_stat_types()`, `get_states()`, `get_followup_statuses()`, `get_service_id()`) — UI
  never queries those tables directly. `supply_repo.get_sell_price(item_name, category=None)` is
  the single sell-price lookup (medication price auto-fill).
- SQL-injection fixes: every repo search/filter column is whitelisted/parameterized (`client_repo`,
  `pet_repo`, `visit_repo`, `appointment_repo`, `supply_repo`, `sales_repo`) — keep any NEW filter
  column whitelist-style.
- Dead code already removed (see git); `clinical_service.schedule_followup_after_entry(...)`
  owns the post-entry follow-up orchestration (UI must not hand-roll it).
- Testing config: `pytest.ini` (testpaths, `pythonpath=.`); `tests/conftest.py` auto-discovers
  `*_repo.py` in the repositories dir into `_REPO_NAMES` — **new repos are patched automatically**.
- Layer-boundary audit: clean (no raw SQL in `src/ui/` / `src/modules/`) — keep it that way.

### Release & DB upgrades (v1.0.0 → v1.1.0)

- **Version** is a single source: `src/config/meta.py` `VERSION` (semver, may carry a
  `-betaN`/`-rcN` suffix); `package_app.py` passes it to Inno as `/dMyAppVersion={VERSION}`.
  The `.iss` `#ifndef MyAppVersion` default must be kept in step for direct compiles. **Do not**
  compare versions as plain strings.
- **Installer upgrade guard** `.iss` `CompareVersions` (dotted numbers, then pre-release rank
  `alpha` < `beta` < `rc` < final) — plain string compare wrongly refused beta2 over beta1 and the
  final over a beta. The current release flow is `1.0.0 < 1.1.0`; pre-release comparison remains
  available for future releases.
- **Upgrade = install over the old one + auto-migrate.** Same AppId/DB path
  (`%LOCALAPPDATA%\Petcare Efficiency Toolkit (P.E.T)\Database.db`) so the old DB is opened in
  place; `initialize_schema` first archives a v1.0.0 schema (see the Legacy section above), then
  runs forward-only versioned migrations `schema_migrations` (001–028). The uninstall-before-upgrade
  passes `/PRESERVEDATA=1` so AppData survives. Regression: `tests/test_legacy_migration.py`
  `TestPureLegacyUpgrade` (exact v1.0.0 DDL → `initialize_schema`).
- **Pre-upgrade safety backup:** `connection.get_connection()` captures `db_existed` *before*
  `db.open()` and calls `_backup_before_upgrade` when a pre-existing DB has pending migrations
  (`migrations.pending_migration_versions`) or a legacy `clients` table (`has_legacy_schema`).
  Best-effort (a backup failure never blocks the upgrade). Fresh installs take no backup.
  Tests: `tests/test_migrations.py::TestUpgradeDetection`.
