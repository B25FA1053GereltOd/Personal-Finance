# Personal Finance Tool

A local, single-user Windows desktop app using Python and Tkinter/ttk.
Step 1 supplies the application window and development setup. Step 2 supplies
the database/model layer, exact money conversion, and repository operations.
Step 3 supplies the verified Khan Bank MNT parser and synthetic workbook tests.
Step 4 supplies preview/confirmation, conservative duplicate handling, and atomic
imports with saved decisions. Step 5 adds scoped merchant rules, manual review,
and explicit retroactive application. Step 6 adds the import and transaction
browser UI. Step 7 adds grouped merchant review, effective-value editing with
read-only bank references/history, and explicit rule management. See the
[synthetic Step 7 manual checklist](docs/review_ui.md).
Step 8 adds currency-separated Dashboard tables, local SQLite backups, validated
manual restore preparation, and `start.bat`. See the exact
[synthetic Dashboard checklist](docs/dashboard.md) and
[backup/restore instructions](docs/backup_restore.md).
Runtime is offline and requires no server, paid service, API key, or AI call.
Step 9 adds confirmed restore with a safety backup, filtered CSV export, an account
filter, Help/About and Open data folder. Start with the
[user guide](docs/user_guide.md). Requirement-by-requirement verification and
limitations are recorded in [acceptance.md](docs/acceptance.md).

## Setup in VS Code on Windows

Open **C:\Personal Finance** as the workspace folder. The existing
`Personal-Finance/Prompt.txt` is a reference file; run commands from the workspace
root, where this README and `app/` live.

In **Terminal > New Terminal**, choose **PowerShell**:

```powershell
Set-Location 'C:\Personal Finance'
python --version
# Create only if .venv does not already exist:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m tkinter
# Close the Tk demo before continuing.
.\.venv\Scripts\python.exe -m app
```

Reuse an existing working `.venv`; do not recreate it during normal runs. All
dependency installs, app runs, and tests use its explicit Python executable.
Shell activation and PowerShell execution-policy changes are unnecessary.
The one-time dependency installation requires network access or a local wheel
cache. `openpyxl` is the only third-party app requirement; Tkinter, sqlite3,
and unittest come with Python. No build tooling is needed.

Python 3.15.0 with Tk 9.0 was found during this workspace's setup. If Python is
missing on another PC, install the Windows 64-bit Python distribution from
<https://www.python.org/downloads/windows/> with Tcl/Tk support enabled, reopen
the terminal, and run the commands above. If `import tkinter` fails, modify or
repair that Python installation with **tcl/tk and IDLE** selected. Tkinter is
not a pip dependency.

## Interpreter, running, debugging, and tests

1. Open the Command Palette and choose **Python: Select Interpreter**.
2. Choose **Enter interpreter path** and select
   `C:\Personal Finance\.venv\Scripts\python.exe`.
3. In **Run and Debug**, select **Personal Finance Tool**. Use **F5** to debug
   or **Ctrl+F5** to run. Both use module `app` and the workspace as the working
   directory. Close the window with **Close** or its title-bar **X**.
4. In the Testing view, refresh unittest discovery and run the tests, or use:

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

These temporary-directory variables keep test files inside the project for the
current terminal session. No additional packages are needed for Steps 3–9.
For headless verification without launching Tk windows, set
`$env:PERSONAL_FINANCE_SKIP_GUI_TESTS = '1'` before running unittest. Those GUI
tests will be explicitly skipped, not reported as visually verified.

Workspace configuration uses the current `debugpy` launch type. Microsoft
**Python** (`ms-python.python`), **Python Debugger** (`ms-python.debugpy`), and
**Pylance** (`ms-python.vscode-pylance`) were detected as installed. On another
installation, install Python and Python Debugger through VS Code's Extensions
view; add Pylance for language analysis. An interpreter previously selected in
VS Code can override the default setting, so explicitly select `.venv` above.
See `STATUS.md` for what was actually verified, including any NOT RUN checks.

## Data folder

The default is `%LOCALAPPDATA%\PersonalFinanceTool`. If `LOCALAPPDATA` is absent
or empty, the single fallback is `Path.home() / "PersonalFinanceTool"`
(normally `C:\Users\<you>\PersonalFinanceTool`). Neither depends on the current
working directory. Override it for the current PowerShell session with an
absolute path:

```powershell
$env:PERSONAL_FINANCE_DATA_DIR = 'C:\Personal Finance\data'
.\.venv\Scripts\python.exe -m app
# Restore the default for this terminal:
Remove-Item Env:PERSONAL_FINANCE_DATA_DIR
```

An empty override uses the default. Relative environment paths are rejected
with an explanatory startup error. The window displays the resolved location.
Starting the app now opens/initializes `finance.sqlite3` there, owned by a worker
thread. For synthetic verification, use the isolated workspace data directory
in the [Step 6 manual checklist](docs/ui.md#manual-gui-checklist).

## Project and privacy

`app/__main__.py` starts the app, `app/config.py` resolves the data directory,
and `app/ui/__init__.py` creates the window. `app/models.py` validates money and
source inputs; `app/db.py` provides SQLite storage. See
[the database API](docs/database.md) for methods and integrity rules. `tests/`
contains configuration, model, and repository checks. `docs/` also contains
the Windows acceptance checklist. Future modules
are listed in `AGENT_CONTEXT.md` and will be added only when their step starts.

`app/parsers/` provides database-independent statement parsing. See the
[verified format facts](docs/khan_format.md) and [parser API](docs/parsers.md).
The parser preserves source order and text, reports malformed rows explicitly,
and checks balances and totals. `app/import_service.py` coordinates read-only
preview/cancel and explicit confirmation before atomic storage. See the
[import service API](docs/import_service.md) for counts, decisions, and limitations.
Khan cross-file matches require explicit review because no unique bank reference
is verified. The Import tab exposes these decisions explicitly before Commit.
`tests/fixtures/khan_synthetic.xlsx` is the sole XLSX Git-ignore exception and
contains only invented test data.

`app/classification.py` supplies [classification and review services](docs/classification.md).
Manual assignment affects selected transactions only and locks the choice;
saving a rule does not change past rows. Khan purchase extraction removes only
the user-confirmed six-character authorization prefix and uses the normalized
complete remainder as the key. Credits, QPay and unsupported descriptions stay
unclassified. See the verified format facts for scope and limitations. Tests
use fictional values only.

Keep all real bank files in `private_statements/`. Git ignores that directory,
`.venv/`, data, backups, databases, Python caches, and common statement/export
formats even outside that folder. Ignore rules do not protect files already
tracked by Git. Never commit real financial data, log statements, modify
original bank exports, or use them in tests.

Read `AGENT_CONTEXT.md` and `STATUS.md` before any later implementation step;
agents are not assumed to load these files automatically. Steps 1–9 are
implemented; verification results
and remaining GUI checks are recorded in `STATUS.md`.
Later steps require a new instruction. Ask before installing any
additional packages.

## Import and browse

Use **Import → Add account** to save a Khan Bank account with its exact statement
IBAN as text. Choose an XLSX file, confirm the selected account, and click
**Preview import**. Inspect errors and original incoming/existing rows; choose
Keep/Skip for every ambiguous row. **Cancel preview** writes nothing; **Commit
import** applies the existing atomic import/classification services. Account
creation is a separate explicit action that persists even if a preview is canceled.

The **Transactions** tab provides inclusive date bounds, category, account, currency, debit/credit,
unclassified and literal Unicode description search filters. Click **Apply /
refresh** after changing filters. Pages contain 10, 25, 50 or 100 rows. **Review
unknown merchants** opens grouped review. Assign selected rows only by default,
or explicitly save a future merchant rule; preview before confirming bulk changes.
Edit a selected transaction's effective fields while viewing immutable source and
history tabs. Manual assignments remain protected. Rules can be edited/disabled
without changing past rows; retroactive application requires explicit selection.
See [UI architecture and manual verification](docs/ui.md). No real statements
are used by automated tests.

## Dashboard, backup and everyday launch

The Dashboard shows classified income, expenses and net cash flow separately for
each currency, unknown counts, category amounts/counts/percentages and monthly
tables. Net is income minus expenses, not the bank balance. Unclassified,
transfer and excluded amounts do not enter those totals. Choose All time, This
month, Last month, This year or an inclusive custom ISO range. Select a category
or month and open its Transactions to investigate it. Successful imports, edits,
classifications and rule applications refresh the report automatically.

After one-time setup, launch from PowerShell with `.\start.bat`, or double-click
`C:\Personal Finance\start.bat`. It runs the existing workspace virtual environment
from the project directory, preserves startup errors and performs no installs.
It inherits `PERSONAL_FINANCE_DATA_DIR` when launched from that terminal.
Launcher execution for Step 8: **PASS, user-confirmed 2026-10-20**, using the
isolated synthetic directory. Dashboard opening, all-time currency totals/counts
and income/expense category amounts/percentages also passed the user's smoke test.
Extended GUI checks remain optional/pending (NOT RUN), not failures; see the checklist.

Use **Backup** to select a local folder. Success means SQLite's backup API and
integrity/schema validation completed; existing snapshots are never overwritten.
For GUI restore, close other app instances, choose a compatible backup and confirm
the summary. A validated safety backup is required before SQLite restores the
snapshot atomically. After success, close/reopen this app as instructed. The selected
backup remains untouched. For manual restore, close the app, validate a separate
copy and preserve the current database first. Follow the complete
[manual restore and tested temporary exercise](docs/backup_restore.md); never
copy a live database file directly or delete statement files.

Tested existing environment on 2026-10-20: Python 3.15.0, SQLite 3.53.4,
openpyxl 3.1.5 and et_xmlfile 2.0.0. Imported Tcl/Tk constants: 9.0/9.0;
Step 8 GUI smoke testing was performed by the user only. No dependency changes or installs.

## Export and final verification

In Transactions, choose filters and click **Apply / refresh** before **Export CSV**.
Export uses all matching pages and effective edited values, including account,
bank, category, currency, note and review/protection state. It writes UTF-8 with
BOM, quoted fields and exact decimal text. No matching rows means no file; existing
files are never overwritten. Spreadsheet formula-like text is prefixed with an
apostrophe for safety. To preserve identifiers/large decimals in Excel, import
through **Data > From Text/CSV** and select Text for those columns; automatic Excel
type conversion can discard leading zeros or precision even though the CSV is exact.
Keep exports private; CSV files are Git-ignored.

**Help / About** explains the workflow and shows app/database versions and the data
directory. **Open data folder** uses the Windows file-opening API without shell
commands. `start.bat` uses its own project location even when the calling directory
differs; no administrator rights, install step or internet is needed for normal use.

Run the final automated checks in workspace PowerShell:

```powershell
Set-Location 'C:\Personal Finance'
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:PERSONAL_FINANCE_SKIP_GUI_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -c "import ast; from pathlib import Path; paths=list(Path('app').rglob('*.py'))+list(Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p)) for p in paths]; print('Syntax PASS')"
git -c core.safecrlf=false diff --check
```

Step 9 automated result: **233 discovered, 228 passed, 0 failed, 5 GUI tests
explicitly skipped**. The agent used a workspace PowerShell process, not the visible
VS Code integrated terminal. Run/debug configuration was verified statically;
F5/Ctrl+F5 and File Explorer launch were not rerun by the agent. No real statement
was accessed. User-confirmed synthetic smoke PASS on 2026-10-21: start.bat, CSV
export, backup, restore preview validation/Cancel preserving the database,
Help/About version/data directory and Open data folder. Confirmed restore/restart
and extended GUI checks remain optional/pending, not failed; see the short
[isolated synthetic checklist](docs/user_guide.md#synthetic-manual-acceptance).
