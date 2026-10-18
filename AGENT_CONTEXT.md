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
and financial values are intentionally not recorded here. No POS marker was
observed, so no merchant separator is inferred. No Step 4 work is authorized.

## Working rules

- Work inside the open VS Code workspace (`C:\Personal Finance`). Edit files
  directly when tools allow; use its `.venv` and integrated terminal. If tools
  only provide a workspace shell, report that distinction honestly.
- Preserve existing user work, including `Personal-Finance/Prompt.txt`, nested
  repositories, unrelated files, and pre-existing Git changes.
- Work only inside this project folder. Ask before installing packages; Step 2
  needs only the existing Python standard library and installs none.
- Ask before any action outside this project folder. For Step 3 tests/fixture
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
