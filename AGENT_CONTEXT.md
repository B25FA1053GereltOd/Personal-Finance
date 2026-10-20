# Persistent implementation contract

Read this file and `STATUS.md` first. Do not assume any provider or coding
agent automatically reads this context file.

## Application baseline

- Python; Tkinter/ttk UI; sqlite3 database; openpyxl for `.xlsx` import; unittest.
- One local user, no dedicated server, offline runtime, no paid services or AI
  API calls.
- Support Khan Bank MNT statements first, with a separate parser interface for
  later banks. Import transactions, remember merchant category rules, review
  unknown merchants, and edit transactions manually in their respective steps.
- Unclassified is a review state, never an automatic "Other" assignment.

Default income categories (preserve these names):

- Earned income (part-time job, freelancing, internship)
- Allowance / Family support
- Scholarships / Grants
- Gifts / Donations
- Other income

Default expense categories (preserve these names):

- Tuition & Academic Fees
- Textbooks, Printing & School Supplies
- Cafeteria, Coffee & Snacks
- Dormitory / Rent & Utilities
- Public Transport / Commuting
- Social & Entertainment
- Software & Digital Subscriptions
- Other expenses

Target project structure: `app/__main__.py`, `app/models.py`, `app/db.py`,
`app/import_service.py`, `app/classification.py`, `app/parsers/base.py`,
`app/parsers/khan.py`, `app/ui/`, `tests/`, `docs/`, `requirements.txt`, `README.md`,
`AGENT_CONTEXT.md`, and `STATUS.md`. Add `__init__.py` where needed. Do not create
empty implementations for future features; add those modules only when their
implementation step begins. `app/config.py` holds Step 1 data-folder resolution.

## Step 1 scope and acceptance

Create a runnable Tkinter window, package entry point, requirements, Windows
PowerShell setup instructions, and `.gitignore`. Ignore `.venv`, data, backups,
`private_statements/`, private statement files, and Python caches. Preserve
unrelated files and existing VS Code settings and launch configurations.

Check installed Python, then create or reuse the workspace `.venv`. Install
dependencies into that environment only. Use explicit commands such as
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and
`.\.venv\Scripts\python.exe -m app`; do not depend on activation or change
PowerShell execution policy. Document interpreter selection in VS Code. If
Python editing/debugging support is missing, document the required extension
setup instead of claiming it is installed. Add minimal workspace run/debug and
unittest configuration compatible with installed tooling. Run module `app`
with the workspace as the working directory. Do not add build tooling.

Use a configurable data directory, defaulting to
`%LOCALAPPDATA%/PersonalFinanceTool`, independent of the current directory.
The one fallback when `LOCALAPPDATA` is absent or empty is
`Path.home() / "PersonalFinanceTool"`. `PERSONAL_FINANCE_DATA_DIR` accepts an
absolute override; empty means unset. Relative environment paths are errors.
Step 1 resolves and displays the location without creating it.

Acceptance: `.\.venv\Scripts\python.exe -m tkinter` works, and
`.\.venv\Scripts\python.exe -m app` opens and closes a window. Verify VS Code
run/debug configuration if available; otherwise label it NOT RUN. If Python or
Tkinter is missing, provide the exact setup action and mark the check blocked.
Do not claim success or install unrelated software. Complete only the requested
step; do not begin Prompt 2 without a new instruction.

## Step 2 contract

Implement only `app/models.py` and `app/db.py` with tests/documentation; retain
the existing UI and entry point. Use sqlite3 with parameterized values, foreign
keys, atomic writes, an idempotent versioned schema, and exact category seeding
once. Implement accounts, categories, imports, transactions, merchant rules,
and compact edit history. Record import SHA-256, account, parser version,
filename, UTC import time, and counts. Preserve the original description,
bank-supplied date/time, parsed ISO date/time, signed amount, currency, optional
reference and balance, worksheet, and row provenance separately from editable
effective values. Original values and deduplication identity never change.

Use Decimal and integer hundredths of MNT, rejecting excess precision and
floats. Keep account identifiers as text and genuinely omitted optional values
as null. Category direction must match effective direction. Support explicit
transfer/excluded kinds, keep unknown items reviewable, and reject incompatible
manual edits clearly. Provide atomic import, filtered/paginated query, category
assignment, audited edit, and rule CRUD APIs. Defer parser-specific fingerprints
to Step 4; do not add date/amount uniqueness constraints. Use temporary databases
and synthetic data in tests. See `docs/database.md` for the implemented API.

The user confirmed Step 1 complete, including F5 and Ctrl+F5, before authorizing
Step 2. Do not implement subsequent steps without a new request.

## Step 3 contract

Implement only the parser layer after locally inspecting a supplied Khan Bank
XLSX with openpyxl. If no statement is available, stop and ask for it or its
exact local path. Never invent headers, sheet names, signs, or separators.
Document only verified format facts and unresolved cases in
`docs/khan_format.md`, with no customer names, account values, balances, or
transaction lists. Resolve material amount/row ambiguities before parsing.

Keep parsers independent of the database and UI. Detect by verified headers
and content; preserve original row order, text, source row numbers, and genuine
optional bank references. Return normalized records, structured issues, and
statement metadata. Reject unknown currencies/layouts and ambiguous or malformed
rows explicitly; unfamiliar rows are not harmless footers. Require usable cached
formula results without computing them, and close workbooks after parsing.

Create only synthetic XLSX fixtures reproducing the observed structure. Test
credits, debits, dates, Unicode, blank rows, bad values, and unsupported headers.
Verify real statement counts and available reconciliations locally, reporting
only check outcomes. Real statement contents must never enter logs or fixtures.
See `docs/parsers.md` for the implemented API and test commands.

The exact requested filename was absent; one XLSX candidate was found under
the workspace's `private_statements/` and verified locally. Its private name
and financial values are intentionally not recorded here. No literal POS marker
was observed. Steps 4 and 5 were subsequently authorized; Step 5 received user
confirmation of the authorization-prefix purchase structure documented in
`docs/khan_format.md`. The Step 3 parsing behavior remains unchanged.

## Step 4 contract

Implement only the import service using the existing parser and repository;
do not build UI or classification. Workflow: select file/account, parse and
validate, preview, explicit confirmation, atomic commit, then summary.
Preview/cancel must not mutate the database. Expose valid, invalid, duplicate,
and ambiguous counts; any transaction or statement error blocks all rows.
Return success only after the complete commit succeeds.

Skip identical SHA-256 files only for the same account. Use a bank reference
as unique only after its stable uniqueness semantics are verified. Otherwise
compare immutable account, currency, ISO date/time with precision, signed amount,
original description, and optional reference/balance. Filename and sheet row
are provenance. Preserve multiplicity; indistinguishable overlap requires an
explicit per-row keep/skip decision and stored audit. Manual edits must neither
change matching identity nor lose categories/locks on reimport. Write all rows,
metadata, and decisions in one SQLite transaction. Do not claim universal
deduplication; Khan has no verified unique reference.

Expose preview/result models for later UI use. Necessary storage support is a
small atomic version-1-to-2 migration for immutable import decisions, consistent
source snapshots, and a revision guard checked inside the write transaction.
`parse_bytes` lets hashing and parsing share one memory snapshot without making
real-data disk copies. See `docs/import_service.md` for APIs and limitations.

Use synthetic tests for first import, identical file repeat, overlapping
verified test IDs, repeated legitimate rows, ambiguous decisions, malformed
input, cancel, injected rollback, and edited transaction reimport. Test stale
previews and migration as well. No packages, real statement reads/imports,
application launch, commit, or push are needed. Await a new request for Step 5.

## Step 5 contract

Step 5 was explicitly authorized. Implement classification/review services and
connect them to atomic import commit; do not build UI or start Step 6. Use only
deterministic saved rules, never AI calls. Extract POS merchants only from a
verified description pattern. The user confirmed the six-character alphanumeric
authorization token followed by whitespace and merchant text as card/POS
purchases. Local inspection verified the structure; see `docs/khan_format.md`.
For `Khan Bank` / `khan-mnt-1`, remove only that leading ASCII token and separator,
then use the normalized complete remainder as the key. Preserve numbers,
punctuation, domains, locations and display text; never guess shorter boundaries.
Only debit purchases are eligible. QPay, transfers, fees, refunds, credits,
malformed and unsupported descriptions remain reviewable. The token is not a
verified unique bank reference; original source/deduplication identity is intact.
Keep the synthetic extractor seam for tests, not as additional format evidence.

Normalize NFC Unicode, trim/collapse whitespace and casefold while retaining
digits, branch names and punctuation. Preserve display text and original bank
descriptions. Match normalized keys exactly by bank and debit/credit direction,
with one active rule per scope; no fuzzy/substring/regex matching or guessed
real-merchant categories. Record applied rule IDs/revisions. Group reliable
unknown POS merchants; keep missing keys individually reviewable.

Transaction-only assignment is the safe default and must not create a rule.
Provide selected-only category assignment, future-only rule save/update,
read-only preview plus explicit selected-row retroactive application, protected
manual reclassification, and rule disable/edit without changing past rows.
Explicit Other assignments count as classified; unknowns never default to Other.
Debit purchase rules cannot classify transfers, refunds, or non-POS credits.

Use atomic schema-v3 migration for bank scope, disabled rules, and applied-rule
attribution. Preserve legacy IDs; disable rules with unknown bank scope rather
than guessing. Classification, imports, decisions and audits share one commit.
Check locks/eligibility/revisions again when applying a preview; batch failures
roll back all selected changes. Test normalization, distinct merchants, scope,
missing keys, overrides/reimport, disabling, explicit subsets, rollback, and
migration using workspace temporary files only. The user authorized read-only
local statement checks for this pattern repair; expose only check outcomes and
sanitized format facts. Do not launch the GUI, install packages, access external
locations, commit or push as part of this repair.
See `docs/classification.md`. Final reports must state tests/count, changed files,
and any remaining limitations without personal financial data.

## Step 6 contract

Step 6 is authorized: implement only the import and transaction browser UI using
completed parser, repository, import and classification services. Do not duplicate
SQL or parser logic in widgets. Keep `python -m app` and `create_window(data_dir)`;
the UI now opens the configured `finance.sqlite3` on a persistent worker thread.

Use ttk Import/Transactions tabs, an XLSX picker, explicit account selection and
confirmation, preview/error display, per-row ambiguous Keep/Skip decisions and
Commit/Cancel. Account creation is an explicit separate write. Preview/cancel
must not mutate imports, transactions or accounts. Commit uses the existing
atomic service; show success only afterward, including added/skipped/unclassified
counts. Provide a visible action to the unclassified browser; full review and
editing UI remain Step 7 and must not be implemented now.

Provide date/category/direction/unclassified filters, literal Unicode description
search, database pagination, readable MNT formatting and Mongolian text. Keep
SQL in the repository: shared query/count filters add direction and NFC/casefold
search without a schema change. Render bounded pages of preview/errors/candidates.

`FinanceWorker` owns its connection and import preview/service on the same thread.
Use queues for commands/results and Tk `after` polling on the main thread; no
worker widget calls. Disable conflicting actions, sanitize failures, keep retry
and cancel available, and queue shutdown after any running atomic operation.

Use only synthetic fixtures and workspace data directories for agent checks.
Do not use Computer Use, control mouse/keyboard, expose real financial data,
install packages, commit or push for this step. Run automated tests, including
service boundaries; provide the manual GUI checklist in `docs/ui.md`. Hidden
widget tests are not visual verification. If Tk cannot initialize, mark GUI
checks NOT RUN with the reason. Leave completed earlier services intact except
the necessary repository filter/count extension.

## Step 7 contract

Step 7 is authorized: add only Review, effective transaction editing and rule
management UI using existing classification/repository APIs. Keep the import and
browser behavior from Steps 1-6. Group reliable unknown merchant keys with count,
total, example and expandable rows; keep unreliable/protected items accessible.
Selected-only category assignment is the default; optionally save a scoped rule
for future imports. Preview affected rows and confirm before bulk writes. Cancel
and skip change nothing; unknowns persist across restart.

Edit effective date, signed amount, description, merchant display, category,
kind and note; show source/history read-only. Validate ISO dates, exact money and
compatible direction/kind/category. Corrections cannot rewrite matching keys,
rules or source/deduplication identity. Protect manual edits unless explicitly
unlocked. Rule editing/disabling changes future behavior only; existing rows
require explicit preview and selected-only application. Use repository atomic
composition for category-plus-rule confirmation and stale-row checks for edits.

Use only synthetic fixtures/databases inside the workspace. Do not access private
financial files, launch/control the GUI, use Computer Use, stage, commit or push.
Run the full automated suite and distinguish headless checks from pending manual
GUI verification. See docs/review_ui.md for commands and exact manual steps.

## Step 8 contract

The user explicitly confirmed BOTH Dashboard and backup/launcher scope. Preserve
Steps 1–7. Keep reporting outside Tk widgets: exact integer money, Decimal
percentages, separate currencies, categorized income/expense totals and visible
unclassified counts. Transfer/excluded amounts are omitted. Net means income minus
expenses, not bank balance. Use inclusive effective bank-local dates, calendar
presets and validated ISO custom bounds; category/month drill-down carries the
same date/currency filters. Refresh after imports, edits, classification and rule
application through the existing worker/main-thread queue. Provide empty/error
states and bounded table rendering without chart dependencies.

Back up using SQLite's backup API on the connection-owning worker. Reserve new
timestamped names exclusively, validate before success, and report sanitized,
actionable failures. Manual restore closes the app, validates a separate copy
using integrity/foreign-key/schema compatibility checks, preserves the current
database, then prepares the restored file without overwriting existing files.
Never delete user data/imports. Test independent backup reopening and temporary
restore with invented transactions/rules. `start.bat` runs the existing .venv's
module app from its own directory with visible startup errors and no installs.

Use synthetic workspace data only. Do not access private_statements or real
financial files, launch the GUI, use Computer Use, alter the nested repository,
install packages, stage, commit or push. Run full automated tests plus syntax and
whitespace checks. Record tested versions honestly; launcher/visual checks are
NOT RUN until manually verified. See docs/dashboard.md and docs/backup_restore.md
for exact synthetic verification and operating instructions.

On 2026-10-20 the user confirmed the synthetic launcher/Dashboard smoke checks
passed and stopped the remaining extended checklist. Record unrun checks as
optional/pending, not failures. The user subsequently authorized one local
Prompt 8 commit after rerunning tests and privacy checks; no push is authorized.

## Working rules

- Work inside the open VS Code workspace (`C:\Personal Finance`). Edit files
  directly when tools allow; use its `.venv` and integrated terminal. If tools
  only provide a workspace shell, report that distinction honestly.
- Preserve existing user work, including `Personal-Finance/Prompt.txt`, nested
  repositories, unrelated files, and pre-existing Git changes.
- Work only inside this project folder. Ask before installing packages; Step 2
  needs only the existing Python standard library and installs none.
- Ask before any action outside this project folder. For tests/fixture
  generation, direct TEMP and TMP to `data/test-temp` inside the workspace;
  reuse the already installed openpyxl. Never print, log, or expose the user's
  name, account number, balances, or individual transaction details.
- Read this file and `STATUS.md` first; inspect only files relevant to the current
  step. Read `Personal_Finance_Tool_Requirements.txt` if it becomes available.
- Implement that step without redesigning completed work. Use no subagents.
  Avoid speculative features and never fabricate test results.
- Preserve source bank data; do not log private statements; use no real financial
  data in test fixtures.
- Keep the original XLSX only in `private_statements/`; never modify or delete
  it. Do not print or copy real names, account numbers, IBANs, balances,
  counterparty accounts, or transaction descriptions into chat, logs, Markdown,
  documentation, fixtures, or tests. Remove only generated copies confirmed
  to contain real statement data. Report acceptance using outcomes, test count,
  verification status, and changed filenames only.
- If execution is unavailable, provide changed files and exact commands, and
  label verification NOT RUN.
- After each step, update `STATUS.md` in at most 250 words with completed steps,
  public interfaces, checks and results, blockers, and the next step.
- Do not repeat unchanged code in chat. End each reply with changed files,
  checks run, and the next action in at most 150 words.
