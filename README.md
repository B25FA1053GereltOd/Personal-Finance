# Personal Finance Tool

A local, single-user Windows desktop app using Python and Tkinter/ttk.
Step 1 supplies the application window and development setup. Step 2 supplies
the database/model layer, exact money conversion, and repository operations.
Step 3 supplies the verified Khan Bank MNT parser and synthetic workbook tests.
Step 4 supplies preview/confirmation, conservative duplicate handling, and atomic
imports with saved decisions. Step 5 adds scoped merchant rules, manual review,
and explicit retroactive application. UI integration belongs to a later step.
Runtime is offline and requires no server, paid service, API key, or AI call.

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
current terminal session. No additional packages are needed for Steps 3–5.

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
with an explanatory startup error. The existing window displays the resolved
location without opening a database. Explicitly constructing `Repository()`
creates `finance.sqlite3` in this directory; the UI will use it in a later step.

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
is verified. The existing window remains unchanged.
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
agents are not assumed to load these files automatically. Steps 1–5 services are
implemented; supported Khan extraction and checks are recorded in `STATUS.md`.
Later steps require a new instruction. Ask before installing any
additional packages.
