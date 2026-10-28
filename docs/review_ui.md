# Step 7: Review, manual corrections and rules

Step 8 preserves this workflow. Successful confirmations, edits and explicit rule
applications also refresh the Dashboard automatically. Synthetic cross-feature
checks are in [dashboard.md](dashboard.md); GUI verification of Step 8 remains
manual, distinct from the previously passed Step 7 acceptance.

The Review tab groups reliable unknown merchants by exact bank/key/direction.
Each group shows count, signed total and an example description. Select a group
or use Expand selected group to see its transactions. Items without reliable
keys, and protected unknown items, remain individually accessible. Tables render
bounded pages; Ctrl/Shift selects rows on the current page. No selection means
no implicit bulk update. Skip for later changes no data; restart retains review
items. Refresh review reloads groups and the browser.

Choose a compatible category for the selected rows. **Selected transactions only**
is the default (the future-rule checkbox is off). Preview shows the exact rows
and target category; confirmation assigns them and enables manual protection.
Selecting **Also save a rule for future imports** is allowed only within one
reliable unlocked group. The preview explicitly warns when replacing an existing
rule. Category assignment and rule saving are one atomic operation. Cancel makes
no writes. Stale rows or a changed rule require a new preview.

In Transactions, select a row and click Edit selected (or double-click it).
The editor is also accessible from Review. Effective date, signed decimal amount,
description, merchant display, kind, category and note are editable. Source and
history tabs are read-only. Date/precision/direction/category checks happen before
saving; errors keep the editor open. Income/expense edits require a compatible
category; choose unclassified and No category explicitly when unresolved. Transfer
and excluded kinds also require No category. Changing merchant display never
rewrites matching keys, rules, source values or deduplication identity.

Edits protect the transaction by default. The unchecked **Explicitly clear manual
protection** option is the only editor path to unlocking. Unlocking does not apply
any rule by itself. A saved rule can affect an existing unlocked row only through
the separate explicit rule preview/application workflow. Original values remain
available, and changes are stored in audit history.

Rules lists active and disabled rules. Select one, choose a category, and Save
category / enable for future use only; Disable also leaves past classifications
untouched. Preview existing eligible rows excludes protected or incompatible rows.
Nothing is selected automatically. Apply affects only the explicitly selected
eligible rows; cancel changes nothing. Revisions/eligibility are checked again
under the write lock, so stale selections fail together rather than partially.

## Architecture and public boundaries

- `ReviewViews` contains widgets/callbacks only. It uses the existing main-thread
  queue polling and `FinanceWorker`; no SQL or parser logic is in widgets.
- Worker commands: `review_load`, `review_preview`, `review_apply`, `review_cancel`,
  `rule_preview`, `rule_apply`, `rule_change`, `edit_get`, `edit_save`.
- `ReviewService` composes `ClassificationService` and existing repository edits.
  Assignment previews retain row/rule snapshots until explicit confirmation.
  Rule previews delegate to existing classification eligibility and revision checks.
  Edits pass a fixed effective-field allowlist and stale-row revision guard.
- `Repository.atomic()` composes existing nested savepoint writes. The existing
  `merchant_display` column is now editable and audited independently of keys.
  No schema migration or default-category change is needed.
- All connections and services remain on their creating worker thread. Import
  previews and review writes cannot conflict; queued errors use safe diagnostics.
  Payloads contain local financial values for display, never for logging.

## Verification completed automatically

Synthetic service, worker and widget-stand-in controller tests cover grouped and
individual review, preview/cancel, selected-only assignment, atomic future-rule
saving (including injected rollback), automatic tagging on a new import, audited
editing, source/identity preservation, validation, stale previews/editors/rules,
explicit unlocking, future-only rule changes/disabling, selected-only retroactive
application, reimport protection, and reopening stored choices. All prior tests
remain in the full suite. Widget stand-ins do not constitute visual verification.

Run without launching Tk:

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:PERSONAL_FINANCE_SKIP_GUI_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

## Exact manual GUI checklist (NOT RUN by agent)

The user confirmed this manual GUI verification passed on 2026-10-20. This is
user verification, not agent visual inspection. The pre-commit full suite passed
183 tests with five GUI tests explicitly skipped to avoid opening a window.

Use only the invented workbooks generated by `tests.review_fixtures`. No real
statements or application database are needed. From `C:\Personal Finance`:

```powershell
$previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -c "from tests.review_fixtures import create_review_fixtures; create_review_fixtures('data/review-fixtures')"
$env:PERSONAL_FINANCE_DATA_DIR = Join-Path (Get-Location).Path ('data\gui-step7-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m app
```

1. Add account **Synthetic Khan**, fictional IBAN **MN00000000000000000000**.
   Select `C:\Personal Finance\data\review-fixtures\review-initial.xlsx`, confirm
   the account and Preview. Expect five valid rows and zero blocking errors.
   Cancel: Transactions stays empty. Preview again and Commit: five rows appear.
2. Open the Review tab (or choose Review in the sidebar). Expect one merchant
   group containing three rows and two individual items. Expand the group; choose Skip for later and
   Refresh review: all remain. Confirm the individual rows can also be expanded
   and edited; a future rule is unavailable for these unreliable descriptions.
3. Expand the merchant group, select only its first row, choose Other expenses,
   leave the future-rule checkbox off, and Preview selected changes. Cancel once;
   it remains unknown. Preview again and Confirm. One row leaves review, is
   protected, and no rule is created.
4. Select one of the two remaining group rows. Choose Other expenses, check
   Also save a rule for future imports, preview and confirm. One row remains in
   that group. Rules shows one active rule; the selected row is protected.
5. Import `C:\Personal Finance\data\review-fixtures\review-future.xlsx` with the
   same account. Expect Added 1 / Unclassified added 0. Six total transactions
   now exist; the new row has Other expenses automatically.
6. In Transactions, edit the first manually classified row (the invented source
   description begins `A1B2C3`). Try amount `1.001`: saving must fail and leave the
   editor open. Try positive `2.00` with expense/category retained: it must fail.
   Set amount `-2.50`, ISO date `2026-10-15`, invented description/display and note;
   keep expense / Other expenses and leave clear-protection unchecked. Save.
   Reopen: effective corrections persist, original bank amount/date/description
   remain unchanged in the read-only tab, matching key stays unchanged, and
   history lists corrections. Cancel the editor without another write.
7. In Rules, change the rule category to Software & Digital Subscriptions and
   Save category / enable. Existing classifications stay unchanged. Preview
   existing eligible rows: the two protected manual rows are absent; the remaining
   unknown purchase and automatically tagged future purchase are present. Select
   only the unknown purchase and Apply. It changes category; the unselected future
   purchase remains Other expenses. Reimport the initial file: Added 0, Skipped 5;
   the manual correction and protected categories remain intact.
8. Disable the rule. Import
   `C:\Personal Finance\data\review-fixtures\review-disabled.xlsx`: Added 1,
   Unclassified added 1, seven total rows. Earlier categories remain unchanged.
9. Close and reopen using `.\.venv\Scripts\python.exe -m app` in the same terminal
   without regenerating the data-directory variable. Verify seven rows, the
   correction/history, disabled rule and three remaining review items persist.
10. Optional protection check: re-enable the rule, edit a protected row, explicitly
    check clear-protection and save. Its category does not change immediately.
    It now appears in rule preview; Cancel leaves it unchanged. Editing again
    with clear-protection unchecked restores protection.

Check readability, scrolling, selection, tab navigation, busy controls, error
dialogs and responsiveness manually. Step 6 filtering/search/pagination remains
available; use its existing larger synthetic checklist for pagination.
After closing, restore `$env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData`.
No existing data folder is deleted by this checklist.
