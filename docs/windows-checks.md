# Step 1 acceptance checks

Run these from the workspace root in VS Code's integrated PowerShell terminal.
Use only synthetic paths and no bank statements.

1. Run `.\.venv\Scripts\python.exe -m tkinter`. Confirm the Tk demo appears,
   then close it and confirm the process exits normally.
2. Run `.\.venv\Scripts\python.exe -m app`. Confirm the Personal Finance Tool
   window appears and shows the configured data folder. Close it with **Close**.
   Run it again and close it using the title-bar **X**.
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
