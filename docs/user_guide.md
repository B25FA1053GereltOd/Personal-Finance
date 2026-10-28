# Personal Finance: local user guide

Launch by double-clicking `start.bat` in your clone, or run
`.\start.bat` from its root in PowerShell. The project-local .venv must already
be set up; follow README.md once. Startup errors stay visible. Administrator rights,
internet, login, cloud services and API keys are not needed.

The footer and Help / About show the app version, database version and active data
folder. Open data folder opens that exact directory in File Explorer. By default
data lives in `%LOCALAPPDATA%\PersonalFinanceTool`; see README for the documented
fallback and `PERSONAL_FINANCE_DATA_DIR` override.

## Language and navigation

The first launch uses Mongolian. Use **Тохиргоо → Хэл** to choose Mongolian or
English; the choice is saved in `settings.json` inside the active data folder.
Close and reopen the app to apply a changed language. This preference is not
part of the finance database.

The left sidebar opens **Хураангуй** (Dashboard), **Гүйлгээнүүд**
(Transactions), **Хуулга импортлох** (Import), **Танигдаагүй гүйлгээг ангилах**
(Review), **Ангиллын дүрэм** (Rules), and **Ангиллын зураглал** (Mapping Table).
The top actions include
**Нөөцлөх** (Backup), **Сэргээх** (Restore), and **CSV файлаар гаргах**
(Export CSV). Summary cards show **Нийт орлого** (Total Revenue),
**Нийт зардал** (Total Cost), **Цэвэр дүн** (Net), and **Ангилаагүй**
(Unclassified). Revenue and Cost are the prominent cards. Currency totals remain
separate; net is not an account balance.

Category display names are presented in clear Mongolian across the entire application (Dashboard charts, Review workflow, Mapping Table, Transactions table, and CSV exports when Mongolian is active). Stable canonical keys remain stored internally in the database so that existing transactions and mapping rules never break.

## Categories and category management

Under **Тохиргоо → Ангиллын удирдлага** (Settings → Category Management):
- **Ангилал нэмэх** (Add category): Add a category with direction (Expense or Income), choosing from the 27 default presets (19 expense, 8 income) or entering a custom category name.
- **Харагдах нэр засах** (Edit display name): Customize the visible display name for any category without modifying internal database identifiers.
- **Идэвхжүүлэх / Идэвхгүй болгох** (Enable / Disable): Toggle category availability in dropdowns for new transactions and rules. Existing transaction records and rules retain their categories.
- **Ангилал устгах** (Delete category): Delete an unused category. Categories currently referenced by transactions, merchant rules, or mapping rules cannot be deleted and must be disabled instead.
- **Үндсэн ангилал сэргээх** (Restore default category): Restores all 27 standard default categories, enabling any disabled presets and inserting missing ones.
- **Чиглэлээр шүүх** (Direction filtering): Category dropdowns in Review, Mapping Table, Browser, and Edit dialogs only display categories compatible with the transaction's direction (debit/expense vs credit/income).

## Teacher smoke test (about 8 minutes)

Do this after README setup/tests, with other app windows closed. Allow about eight
minutes for the GUI checks; installation and automated test time are separate.
Use only the generated fictional data. This is a manual checklist, not a claim
that the final-audit agent ran it.

1. In VS Code's PowerShell terminal at the cloned project root, prepare a new
   isolated demo and print its exact paths:

   ```powershell
   $teacherRoot = (Get-Location).Path
   $previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
   $env:PERSONAL_FINANCE_DATA_DIR = Join-Path $teacherRoot ('data\teacher-smoke-' + [guid]::NewGuid().ToString('N'))
   .\.venv\Scripts\python.exe -c "import os; from tests.dashboard_fixture import create_dashboard_database; create_dashboard_database(os.environ['PERSONAL_FINANCE_DATA_DIR'])"
   $teacherBackups = Join-Path $env:PERSONAL_FINANCE_DATA_DIR 'manual-backups'
   New-Item -ItemType Directory -Path $teacherBackups -Force | Out-Null
   $teacherCsv = Join-Path $env:PERSONAL_FINANCE_DATA_DIR 'synthetic-export.csv'
   Write-Output "Data: $env:PERSONAL_FINANCE_DATA_DIR"
   Write-Output "Backup folder: $teacherBackups"
   Write-Output "CSV file: $teacherCsv"
   Push-Location (Join-Path $teacherRoot 'docs')
   & (Join-Path $teacherRoot 'start.bat')
   Pop-Location
   ```

   **Expect:** the app launches even from `docs`, and its footer shows the printed
   synthetic directory. The generator refuses an existing database; it never
   opens a real one. Keep this terminal open.
2. Open **Dashboard**, choose **All time** and refresh. **Expect:** 10 rows and
   1 unclassified item; MNT income 1,200.00, expenses 150.00, net 1,050.00;
   USD income 10.00, expenses 2.50, net 7.50. Currencies stay separate.
3. Select the MNT **Other expenses** category and click **View selected in Transactions**.
   **Expect:** two rows totaling 130.10 in expenses. In Transactions reset dates,
   category, account, currency, direction, search and unclassified-only to show
   everything, then **Apply / refresh**. **Expect:** all 10 transactions.
4. Click **Export CSV** and use the exact printed CSV destination. **Expect:**
   success for 10 exported transactions. Do not reuse an existing filename.
5. Click **Backup** and select the printed backup folder. **Expect:** a validated
   success message with a new timestamped database path. Click **Restore**, select
   that backup, inspect the preview, then choose **No / Cancel** at confirmation.
   **Expect:** validation succeeds and cancellation keeps the 10 transactions.
   This deliberately does not test replacement of the live database.
6. Open **Help / About**, then **Open data folder**. **Expect:** app 0.9.0, schema 4
   and the printed synthetic directory; File Explorer opens that directory.
7. Close the app. In the same terminal run:

   ```powershell
   & (Join-Path $teacherRoot 'start.bat')
   ```

   **Expect:** the same directory, 10 transactions and the same All-time totals.
   Close the app again, then restore the prior terminal setting:

   ```powershell
   $env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData
   ```

   **Expect:** demo databases, backups and CSV remain in the ignored demo folder;
   nothing is deleted. Never launch from File Explorer to continue this isolated
   test: it will not inherit the terminal's temporary data-directory override.

Confirmed restore/restart, malformed input dialogs, and extended date/refresh
checks are separate optional manual checks in the detailed checklist below and
[dashboard.md](dashboard.md). They remain pending unless actually performed.

## Daily use

1. Import: add/select the statement's bank/account identity, select XLSX, confirm the account,
   then Preview. Resolve errors and explicit duplicate decisions before Commit.
   Cancel changes no transactions. Imports append only; exact duplicates are
   skipped and overlapping ambiguous rows need explicit Keep/Skip choices. The
   success summary separates added, duplicate skipped, invalid, skipped and
   unclassified counts. Khan MNT is the only supported parser; adding another
   bank identity does not imply its statement format is supported.
2. Review: choose unknown items and a compatible category. Selected transactions
   only is the default. Save a future merchant rule only when intended. Preview
   and confirm bulk changes. Other is a manual category, never an unknown default.
3. Transactions: apply date, category, bank, account, currency, direction, merchant/
   description search or unclassified filters. Search checks effective
   description, merchant display and merchant key. The post-import Show
   unclassified transactions action opens the filtered list; the separate Review
   tab groups merchants. Use Ctrl/Shift to select one or several rows. **🗑
   Сонгосон гүйлгээ устгах** asks for confirmation with the selected count,
   currency totals and date range before archiving; archived transactions are
   excluded from normal views and reports but retain their source and edit history.
   Choose **Архивлагдсан** to inspect them and restore selected rows, or **Бүгд**
   to show both active and archived rows. Edit selected changes effective values;
   original source values remain read-only. Bank/account identity and mapping-rule
   attribution are visible in the table. Manual categories stay protected unless
   explicitly unlocked. Rule changes do not silently change past transactions.
4. Mapping Table: create an invented rule, choose the narrowest bank/account
   scope, enter a synthetic test sample and select **Test rule**. To apply to
   existing records, select the rule, preview matches, select rows explicitly,
   and apply. Nothing is preselected; Cancel leaves existing transactions
   unchanged. See [mapping_rules.md](mapping_rules.md).
5. Dashboard: view totals separately by currency and select date presets/custom
   bounds. Net is categorized income minus expenses, not an account balance.
   Unknown/transfer/excluded amounts are omitted. Open a category/month to browse.
6. Export CSV: first Apply filters in Transactions. Export includes all matching
   pages with effective edited values. Choose a new `.csv` filename. Empty results
   create no file. Existing exports are never overwritten. UTF-8 BOM supports Excel;
   for exact large amounts/identifiers, import columns as Text. Formula-like text
   gains a protective leading apostrophe; the signed amount field stays exact.
7. Backup: choose an existing local folder. Wait for the completed/validated path.
   Only the database snapshot is backed up, never statement Excel files.
8. Restore: close other app instances, select a compatible backup, inspect counts,
   then confirm only if you intend to replace current data. A validated safety
   backup is created in the active data folder's `backups` subfolder first.
   Failures before/during replacement preserve the current database. After success,
   close/reopen the app. The selected backup and safety snapshot remain available.
   Detailed recovery instructions: [backup_restore.md](backup_restore.md).

   ## Prompt 12 GUI checklist (manual-only; currently NOT RUN)

   Use a disposable synthetic database only. Never use a private statement or
   existing finance database for these checks.

   1. Create a demo bank account named `Fictional Bank A` with a synthetic account
      identifier. Confirm it appears with the bank identity in the account selector
      and bank filter. The Khan parser should reject a file whose labeled account
      does not match; no other bank format is implied.
   2. Import the same synthetic XLSX twice. The second import should add zero rows
      and report duplicate skips. Import an overlapping synthetic file and verify
      each ambiguous row requires an explicit Keep/Skip choice; earlier rows remain.
   3. In Mapping Table add an invented exact description rule, target a compatible
      expense category and test it using a fictional sample. Preview matching
      existing rows, select one row, apply, and verify its currency/source data did
      not change. Confirm unselected rows remain unclassified.
   4. Edit/disable the rule and confirm the already classified row does not change.
      Try a one-character `Contains` value such as `T`; confirm the breadth warning.
      Enter an invalid regular expression and confirm it cannot be saved.
   5. Switch Settings to English and reopen to confirm Mapping Table labels and
      controls are English. Restore Mongolian and confirm database category names,
      transaction kinds, currencies, and bank/account identities were not
      translated.

   This checklist is a manual plan, not evidence of visual or GUI verification.

Keep databases, backups, CSV exports and statements private. No app operation logs
transaction values. An ignore rule does not remove a file already tracked by Git.

## Synthetic manual acceptance

**User smoke PASS (2026-10-21):** launcher, CSV export, backup, restore preview
validation/Cancel preserving data, Help/About version/data directory and Open data
folder. Confirmed restore/restart and other extended checks remain optional/pending,
not failures. The agent did not launch or control the GUI. Earlier Step 8 Dashboard
smoke checks passed. All example data below are invented.

In a new VS Code PowerShell terminal, prepare a unique synthetic database:

```powershell
Set-Location 'C:\Personal Finance'
$previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:PERSONAL_FINANCE_DATA_DIR = Join-Path (Get-Location).Path ('data\gui-step9-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -c "import os; from tests.dashboard_fixture import create_dashboard_database; print(create_dashboard_database(os.environ['PERSONAL_FINANCE_DATA_DIR']))"
$checkBackupFolder = Join-Path $env:PERSONAL_FINANCE_DATA_DIR 'manual-backups'
New-Item -ItemType Directory -Path $checkBackupFolder -Force | Out-Null
$checkCsv = Join-Path $env:PERSONAL_FINANCE_DATA_DIR 'synthetic-export.csv'
Write-Output "Backup folder: $checkBackupFolder"
Write-Output "CSV destination: $checkCsv"
# Test launcher resolution from a different current directory:
Push-Location 'C:\Personal Finance\docs'
& 'C:\Personal Finance\start.bat'
Pop-Location
```

Keep that terminal open. The database path printed above ends in `finance.sqlite3`;
the exact backup/export destinations are also printed. Do not recreate this data
directory during restart checks.

1. Confirm the footer shows app 0.9.0, database v4 and the new `data\gui-step9-...`
   directory. Help/About explains local operation. Open data folder opens only that
   directory. Dashboard All time: 10 rows, 1 unknown; MNT income 1,200.00/expenses
   150.00/net 1,050.00; USD 10.00/2.50/7.50.
2. Click Backup, cancel once: no snapshot. Repeat, choose the exact printed
   `$checkBackupFolder`: expect a validated success path. Save that filename for
   restore. Repeat Backup: a second distinct name appears; neither is overwritten.
3. Transactions: select account Fictional MNT, currency MNT, direction Debit,
   date bounds 2026-10-01 and 2026-10-31, search `Fictional Dashboard row 3`.
   Apply: expect one expense, -30.10 MNT. Edit its amount to -40.10, keep Other
   expenses/protection, note `Synthetic Step 9 correction`, then Save. Expect
   the effective row to change and the source amount to remain -30.10.
   Dashboard All time now shows MNT expenses 160.00/net 1,040.00.
4. Return to Transactions and reapply the same filters if needed. Click Export CSV,
   choose the exact printed `$checkCsv`. Expect one exported row and its path.
   Import the CSV in Excel as Text if desired: BOM/Unicode and quoted fields work;
   signed_amount is exactly `-40.10`, the note is the synthetic correction, and
   manual_protection is `protected`. No old source amount replaces the edited value.
   Reusing that filename is rejected, preserving the first export.
5. Search `no matching fictional description`, Apply, Export CSV: clear no-match
   message and no file picker/file creation. Reset filters; all 10 rows return.
6. Restore: select the snapshot from step 2. Summary: v4, 10 transactions, 2 accounts,
   1 rule. Choose No: current edited data remains. Preview again, choose Yes:
   safety backup succeeds, restore completes, its safety path is displayed, and
   further actions are disabled with close/reopen instructions.
7. Close the app. In the SAME terminal run `& 'C:\Personal Finance\start.bat'`.
   Expected: 10 rows, original -30.10 expense, MNT expenses 150.00/net 1,050.00,
   unchanged USD totals, 1 saved rule. The selected backup remains in manual-backups;
   the safety backup and staging snapshot remain in the data folder's backups folder.
8. Optionally restore the displayed safety backup using the same preview/confirm
   procedure. After restart, -40.10 and its synthetic note return. Cancel any other
   unfinished preview and close the app. Never test restore against real data here.

After closing the test app, restore the previous terminal setting:

```powershell
if ($null -eq $previousFinanceData) {
    Remove-Item Env:PERSONAL_FINANCE_DATA_DIR -ErrorAction SilentlyContinue
} else {
    $env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData
}
```

No generated data is deleted automatically. Backup failures/corruption and abrupt
restore interruptions are covered by automated synthetic tests; do not deliberately
interrupt a restore of real data. Report any manual failure before relying on it.
