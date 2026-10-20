# Import and transaction browser (Step 6)

`python -m app` opens the ttk Import and Transactions tabs, using
`get_data_dir() / "finance.sqlite3"`. The UI shows local financial values only
inside the application, never logs them, and performs no network or AI calls.

## Boundaries and lifetime

- `create_window(data_dir)` retains its entry-point contract. `DesktopApp` builds
  widgets and polls a queue with `after`; all Tk work is on the main thread.
- `FinanceWorker(database)` creates, uses and closes its repository and
  `ImportService` on one persistent worker thread. Commands are `account`,
  `preview`, `cancel`, `commit`, `browse`; results are `Event` objects whose
  private payload is omitted from repr. No connections cross threads.
- Startup initializes storage and loads account/category lists. Adding an account
  is a separate explicit write. Preview/cancel do not change accounts,
  transactions, import metadata or classification history.
- The worker retains the exact service-owned preview until cancel/confirm. Parsing,
  duplicate checks, queries and commit run outside Tk. Conflicting account/file,
  import and filter actions are disabled while work is pending.
- Closing queues shutdown after any running operation. A running atomic commit
  finishes before the connection closes; closing during parsing discards the
  uncommitted preview. The entry point also stops/joins the worker if its event
  loop exits unexpectedly. No worker invokes a widget or message box.
- Import errors remain structured and use existing static service diagnostics.
  Unexpected exceptions are replaced by safe messages without source text or
  tracebacks. Validation/write errors leave cancellation/retry available.

## Workflow

Choose an existing account or explicitly save a Khan Bank MNT account using its
statement IBAN. Choose `.xlsx`, check account confirmation, then Preview. Every
file/account change requires confirmation again. The parser validates the match;
the UI does not parse headers or infer account IDs.

The preview shows valid, invalid, duplicate and ambiguous counts, with paged
source rows. Select ambiguous rows and choose **Keep selected** or **Skip
selected**; no decision is preselected. The first selected row's original values
and existing candidate IDs, worksheet/row, date, amount, reference and balance
appear beneath it. Decisions survive page changes. The service revalidates all
decisions, multiplicity and source revision at commit.

Errors/warnings have severity, code, message, worksheet number (one-based), source
row and column. Worksheet names are shown in parsed source-row previews; errors
use the parser's worksheet index, including when malformed rows have no record.
Any error blocks Commit. Cancel, resolve the source problem without overwriting
the original bank export, then create a new preview.

Valid/invalid **row** counts do not include statement-level failures such as an
account mismatch. A separate **Blocking errors** count and persistent explanation
show why Commit is disabled. For an account mismatch, cancel and select/add the
matching account, confirm it and preview again. A successful preview replaces
previous errors, candidate rows and status messages.

Success is displayed only after `ImportService.confirm` returns. The summary shows
added, skipped, and **unclassified added** counts. Identical-file skips report
zero added/unclassified-added and leave existing rows unchanged. If the subsequent
unclassified-count query fails, the UI still reports the successful commit and
marks that count unavailable; it does not invite a duplicate retry.
After success the UI switches to Transactions, clears browser filters, and reloads
page one using the same worker-owned database. The import summary is visible in
both tabs. It does not create or switch accounts/databases during refresh.

**Review unknown merchants** now opens the Step 7 Review view and also refreshes
the unclassified browser. It does not change any categories until an explicit
preview/confirmation. See [review and editing](review_ui.md).

## Browser

Date/time, complete merchant display text (or effective description), exact MNT
amount, category and review status appear in a Unicode ttk table. Use inclusive
YYYY-MM-DD date bounds, category, debit/credit/zero direction, unclassified-only,
and description search together; **Apply / refresh** resets pagination. Search
matches literal substrings of effective descriptions with Unicode casefold/NFC.
Digits, punctuation and Mongolian text remain intact. Page size is 10/25/50/100;
the repository filters before LIMIT/OFFSET and provides matching counts.
Preview, diagnostic and candidate tables also render only 50 rows per page.

## Automated verification

Run from the workspace integrated PowerShell terminal:

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Tests use synthetic workbooks and disposable workspace databases. They cover
preview/cancel read-only behavior, commit, identical/overlapping files, explicit
decisions, rollback, post-commit count errors, safe failures, thread ownership,
shutdown, persistence, Unicode search, filters, and pagination. Five additional
withdrawn-Tk tests exercise widget callbacks when Tk is available; they do not
move the mouse, generate keyboard input, or constitute visual verification.
Set `$env:PERSONAL_FINANCE_SKIP_GUI_TESTS = '1'` before the command to explicitly
skip those five tests without initializing Tk; remove that environment variable
to allow them again. Three headless controller tests always exercise the real
preview/cancel/commit/list queue flow, account mismatch recovery, stale-message
clearing, automatic refresh/filter reset and persisted rows. Only widgets are
replaced with in-memory stand-ins; parser, service, worker and repository are real.

## Repair retest: original three-row fixture

The reported failure was consistent with account validation: the configured
database had no matching synthetic account, no import of the fixture, and no
transactions. These were read-only boolean checks; no account or transaction
values were printed. With a matching account the headless regression saves and
lists all three rows. The previous UI misleadingly showed three valid rows and
zero invalid rows despite a statement-level account mismatch. The validation
guard remains intact. On 2026-10-19 the user confirmed that Prompt 6 manual GUI
acceptance passed after the repair. This is user verification, not agent visual QA.

Close the old app. From `C:\Personal Finance` in PowerShell, use a fresh isolated
folder (the following does not delete or alter an existing database):

```powershell
$previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
$env:PERSONAL_FINANCE_DATA_DIR = Join-Path (Get-Location).Path ('data\gui-retest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m app
```

1. Add **Synthetic Khan**, fictional IBAN **MN00000000000000000000**.
2. Choose only `C:\Personal Finance\tests\fixtures\khan_synthetic.xlsx`, confirm
   that account and Preview. Expect Valid 3, Invalid/Duplicate/Ambiguous 0,
   Blocking errors 0, and enabled Commit. Cancel; Transactions stays at 0.
3. Preview again and Commit. Expect automatic navigation to Transactions,
   three rows, and summary Added 3 / Skipped 0 / Unclassified added 3. Filters
   should be cleared. Apply / refresh must retain all three rows.
4. Close and run the same launch command in the same terminal (without changing
   the data environment variable). The three transactions must persist.
5. To check error recovery, add a different fictional account with identifier
   `FICTIONAL-WRONG`; preview the same fixture with it. Expect a visible account
   mismatch, Blocking errors 1, and disabled Commit despite Valid 3 / Invalid 0.
   Cancel, select Synthetic Khan, confirm, and preview again. The mismatch and
   old errors must disappear. Cancel this already-imported preview.
6. Close the app and restore the previous setting:
   `$env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData`.

## Manual GUI checklist

**Agent GUI/visual checks: NOT RUN.** Tk initialization failed in the execution
environment because Tcl initialization files were not usable. No Computer Use
or mouse/keyboard automation was used. Perform the following in VS Code using
the workspace interpreter; record the actual outcomes after checking.

Prepare only fictional workbooks and isolate the GUI database inside the project:

```powershell
$previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
$env:PERSONAL_FINANCE_DATA_DIR = Join-Path (Get-Location).Path 'data\gui-step6-check'
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -c "from pathlib import Path; from tests.ui_fixtures import create_ui_fixtures; create_ui_fixtures(Path('data/gui-step6-fixtures'))"
.\.venv\Scripts\python.exe -m tkinter
# Close the Tk demo, then launch the app:
.\.venv\Scripts\python.exe -m app
```

If Tk also fails in this terminal, stop the GUI check and repair Tcl/Tk support
for the Python interpreter selected by `.venv`; do not mark launch as passed.
No package installation is required by Step 6.

1. Confirm both tabs, controls, scrollbars, and Mongolian text are legible when
   resizing the window. Add account name **Synthetic Khan** and fictional IBAN
   **MN00000000000000000000**. Account saving is an explicit separate write.
2. Choose `data/gui-step6-fixtures/synthetic-browser.xlsx`, confirm the account,
   then Preview. Expect 23 valid rows, no invalid/duplicate/ambiguous rows on a
   fresh database. Cancel. Transactions must remain empty. Preview again.
3. Commit. Expect Added 23, Skipped 0, Unclassified added 23. Open Transactions
   and check MNT signs/two decimals and Unicode descriptions. Click Review unknown
   merchants; it must show unclassified rows without modifying them.
4. Set 10 rows/page. Check page sizes 10, 10, 3 and Previous/Next limits. Search
   `жишээ` (case insensitive), filter Debit, and use date 2026-10-10 for both bounds:
   expect 23 rows. Credit or a different date gives none. Selecting an expense
   category gives none because unknowns were not automatically categorized.
   Reset filters; invalid dates must show a usable error without losing rows.
5. Import the same file again: expect Added 0, Skipped 23, no duplicated rows.
   Preview `synthetic-overlap.xlsx`: expect 23 ambiguous rows and disabled Commit
   until every row has an explicit decision. Inspect incoming/existing original
   values; choose Skip for all selected ambiguous rows, then Commit. Still 23 rows.
6. Preview `synthetic-invalid.xlsx`: inspect worksheet/row/column errors,
   including Worksheet 1, row 4. Commit must remain disabled. Cancel and check
   that the original 23 transactions remain available.
7. Confirm the UI continues repainting during preview/commit and conflicting
   actions are disabled. Close with X during a preview; reopen and confirm no
   uncommitted rows were added. Close normally and reopen: 23 rows persist.

For repeat runs, choose a new empty directory under `data/` for the GUI database;
the checklist does not delete an existing database. After closing the app:

```powershell
$env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData
```

Step 7 adds merchant review, transaction editing and rule management. Its separate
[synthetic manual checklist](review_ui.md) records checks without changing the
Step 6 acceptance history above.
