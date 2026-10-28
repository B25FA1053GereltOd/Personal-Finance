# Status

Steps 1–9 and the Step 10 final audit remain intact. App version 0.9.0.
**Database schema is now v4** (was v3). Work below is uncommitted in the local
working tree; nothing is staged, committed or pushed.

## Mongolian localization / UI redesign (done, uncommitted)

- Centralized translations (`app/ui/i18n.py`) with English fallback, atomic local
  language preference, Mongolian confirmations, view models and messages
  (`app/ui/view_models.py`, `app/ui/messages.py`). Category names, currencies,
  bank/account names and transaction kinds are not translated.
- Navy-sidebar light theme; Dashboard cards Total Revenue / Total Cost / Net /
  Unclassified (Decimal, currencies separate); unclassified-filter action fix;
  Unicode casefold search over description, merchant display and key.

## Prompt 12 progress (implemented; completion NOT declared)

- **Append-only imports:** new rows are appended; exact duplicates skipped;
  ambiguous overlaps need explicit Keep/Skip; prior rows are never replaced.
- **Multi-bank/account scope:** accounts carry bank identity; bank and account
  filters can combine. Khan Bank MNT remains the only parser.
- **Schema v3→v4:** atomic migration adds optional `pos_id`, persisted
  `mapping_rules`, and applied-mapping-rule attribution. Covered by a synthetic
  migration test (transactions, category IDs and source values preserved).
- **POS ID:** column exists; Khan provides no verified POS ID, so it is NULL.
- **Mapping rules:** `app/mapping_service.py`; highest priority wins, ties by
  ascending rule ID; disabled rules ignored; bank/account/direction scope must
  match; only unclassified, unlocked rows are eligible, so manual or already
  classified rows are protected. Existing rows change only via preview plus
  explicit selected-row apply with revision rechecks.
- **UI:** Mapping Table page `app/ui/mapping.py`. Docs: `docs/mapping_rules.md`.

## Test-only fixes this session (no production code changed)

- Stale schema expectations 3→4 in `test_backup`, `test_dashboard_ui`,
  `test_handoff`, `test_local_operations`.
- `test_mapping_service`: priority test now checks a fresh unclassified row
  (the imported row was already classified, hence correctly ineligible).
- `test_mapping_service`: v3 migration test closes its raw SQLite connection
  (`contextlib.closing`) so temp-directory cleanup succeeds on Windows.

## Mongolian category names and editable category management (done, uncommitted)

- **Localization:** All 27 default categories (19 expense, 8 income) display in clear Mongolian across the Dashboard charts, Review workflow, Mapping Table, Transactions table, and CSV export (when language is Mongolian). Stable internal canonical keys and integer IDs remain unchanged in the database, ensuring 100% backward compatibility with existing transactions, merchant rules, and mapping rules.
- **Direction filtering:** Category selection dropdowns across Review, Mapping Table, Transactions browser, and Edit dialogs filter categories strictly by transaction direction (debit/expense vs credit/income).
- **Category management dialog:** Available under **Тохиргоо → Ангиллын удирдлага** (`CategoriesDialog` in `app/ui/categories_dialog.py`).
  - Add category with direction (Expense/Income), default presets or custom name.
  - Edit custom display name override without altering database keys.
  - Enable / disable category (disabled categories excluded from dropdowns for new transactions while preserving old records).
  - Delete category: blocked if category is used in transactions or rules with clear warning; allows deletion only if unused.
  - Restore default categories: enables disabled presets and inserts any missing standard categories.
- **Persistence:** Category preferences (disabled category IDs and display name overrides) persist atomically in `settings.json`.

## Monthly budget management — Stage 1 (done, uncommitted)

- **Database schema & constraints:**
  - Table `budgets` added to schema: `id`, `month` (`YYYY-MM`), `currency` (`[A-Z]{3}`), `category_id` (foreign key to `categories.id`), `planned_amount_minor` (positive integer), `note`, `active` (0/1), timestamps, and a strict unique constraint on `(month, currency, category_id)`.
  - Database-level triggers `budgets_category_insert` and `budgets_category_update` enforce that budget categories must have direction `income` or `expense`.
  - Database schema version remains 4; existing v4 databases automatically ensure the `budgets` table and triggers are present upon initialization without breaking backup fingerprinting or schema version checks (`validate_backup` passes).
  - Category deletion protection: `Repository.is_category_used` and `list_categories_with_usage` inspect `budgets` table, preventing deletion of categories referenced in active or inactive budgets.
  - Multi-currency support: separate budgets for MNT, USD, and any other three-letter currencies.
- **Service layer (`app/budget_service.py`):**
  - `BudgetBlocked(ValueError)` safe exception for diagnostic errors.
  - `BudgetService`: `save_budget`, `toggle_active`, `delete_budget`, `list_budgets`, `get_summary`.
  - Validates positive amounts, valid months (`YYYY-MM`), 3-letter currency codes, direction-compatible categories, and duplicate prevention.
- **Worker & Threading (`app/ui/worker.py`):**
  - Worker dispatches `budget_list`, `budget_save`, `budget_active`, `budget_delete`, and `budget_summary`.
  - Catches `BudgetBlocked` in domain exception group; wraps generic unexpected errors safely.
- **UI (`app/ui/budget.py`):**
  - Dedicated Budget management page (`💰  Төсөв`) in sidebar and notebook tabs.
  - Month navigation with previous (`◀`), next (`▶`), and "This month" (`Энэ сар`) quick-action.
  - Filters by currency, direction, and active status.
  - Summary cards showing total Planned Expense, total Planned Income, and Count.
  - Paged table with formatted columns and empty-state messaging when no budgets exist for selected month.
  - Add / Edit modal dialog with direction-filtered Mongolian category display names, positive amount validation, and duplicate prevention.
  - Delete confirmation dialog and active toggle.
  - Dashboard section with quick-access button to Budget page (`💰  Төсөв үзэх`).
- **Translations (`app/ui/i18n.py`):**
  - Complete Mongolian and English bilingual support for all budget buttons, labels, dialog fields, headers, and messages.

## Checks (2026-10-28, TEMP in `data/test-temp`)

- `Ran 274 tests` — 269 passed, 0 failed, 0 errors, 5 skipped (GUI tests skipped by flag).
- `test_ui.py` GUI tests run with GUI enabled: 25 passed, 0 failed, 0 errors.
- Python syntax compile of `app/` and `tests/` OK.

## NOT RUN

- **GUI verification: NOT RUN** (no launch, no visual check).
- **Real-statement verification: NOT RUN** (`private_statements` not accessed).

## Remaining manual checks

Synthetic-only, per `docs/user_guide.md`: launch via `start.bat`; Mapping Table
create/test/save/disable/delete a rule; preview and apply to selected rows only;
bank/account filters in Transactions; Mongolian/English switch; 1280×720 layout;
Dashboard refresh; backup/restore with a v4 database. Also pending: a
requirement-by-requirement review of Prompt 12 against `AGENT_CONTEXT.md`, and
refreshing the other docs' schema references if any still say v3.
