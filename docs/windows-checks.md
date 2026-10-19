# Windows acceptance checks

For the Step 6 import/browser workflow, use the isolated synthetic-data
[manual GUI checklist](ui.md#manual-gui-checklist). Interactive Step 6 checks
remain **NOT RUN** by the agent: Tk could not initialize in the execution
environment because Tcl initialization files were not usable. No visual
verification is inferred from source inspection or service tests.
The user confirmed Prompt 6 manual GUI acceptance passed on 2026-10-19 after
the import/browser repair. The pre-commit suite passed 170 tests, with five
widget tests explicitly skipped to avoid opening a GUI in the agent session.

Run these from the workspace root in VS Code's integrated PowerShell terminal.
Use only synthetic paths and no real bank statements. Set
`PERSONAL_FINANCE_DATA_DIR` to an absolute workspace test directory first,
as shown in the Step 6 checklist; the app now opens a database at startup.

1. Run `.\.venv\Scripts\python.exe -m tkinter`. Confirm the Tk demo appears,
   then close it and confirm the process exits normally.
2. Run `.\.venv\Scripts\python.exe -m app`. Confirm the Personal Finance Tool
   window appears and shows the configured data folder. Close it using the
   title-bar **X**. Reopen it and confirm transactions persist.
3. Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v`.
   All tests must pass; they cover defaults, overrides, invalid relative paths,
   the home fallback, and independence from the working directory.
4. Select the workspace `.venv` interpreter in VS Code. Select the **Personal
   Finance Tool** launch configuration and use **Ctrl+F5**, then **F5**. A
   breakpoint in `app/__main__.py` should be reached during debugging; continue
   and close the window. Refresh and run unittest discovery in the Testing view.

Record actual results in `STATUS.md`. If an interactive check cannot be executed,
label it **NOT RUN**, even if configuration inspection succeeds. Do not count
importing Tkinter alone as verification that a window opens and closes.
