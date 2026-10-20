# Personal Finance: local user guide

Launch by double-clicking `C:\Personal Finance\start.bat`, or run
`& 'C:\Personal Finance\start.bat'` in PowerShell. The project-local .venv must already
be set up; follow README.md once. Startup errors stay visible. Administrator rights,
internet, login, cloud services and API keys are not needed.

The footer and Help / About show the app version, database version and active data
folder. Open data folder opens that exact directory in File Explorer. By default
data lives in `%LOCALAPPDATA%\PersonalFinanceTool`; see README for the documented
fallback and `PERSONAL_FINANCE_DATA_DIR` override.

## Daily use

1. Import: add/select the statement's account, select XLSX, confirm the account,
   then Preview. Resolve errors and explicit duplicate decisions before Commit.
   Cancel changes no transactions. Khan MNT is the supported parser.
2. Review: choose unknown items and a compatible category. Selected transactions
   only is the default. Save a future merchant rule only when intended. Preview
   and confirm bulk changes. Other is a manual category, never an unknown default.
3. Transactions: apply date, category, account, currency, direction, search or
   unclassified filters. Edit selected changes effective values; original source
   values remain read-only. Manual categories stay protected unless explicitly
   unlocked. Rule changes do not silently change past transactions.
4. Dashboard: view totals separately by currency and select date presets/custom
   bounds. Net is categorized income minus expenses, not an account balance.
   Unknown/transfer/excluded amounts are omitted. Open a category/month to browse.
5. Export CSV: first Apply filters in Transactions. Export includes all matching
   pages with effective edited values. Choose a new `.csv` filename. Empty results
   create no file. Existing exports are never overwritten. UTF-8 BOM supports Excel;
   for exact large amounts/identifiers, import columns as Text. Formula-like text
   gains a protective leading apostrophe; the signed amount field stays exact.
6. Backup: choose an existing local folder. Wait for the completed/validated path.
   Only the database snapshot is backed up, never statement Excel files.
7. Restore: close other app instances, select a compatible backup, inspect counts,
   then confirm only if you intend to replace current data. A validated safety
   backup is created in the active data folder's `backups` subfolder first.
   Failures before/during replacement preserve the current database. After success,
   close/reopen the app. The selected backup and safety snapshot remain available.
   Detailed recovery instructions: [backup_restore.md](backup_restore.md).

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

1. Confirm the footer shows app 0.9.0, database v3 and the new `data\gui-step9-...`
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
6. Restore: select the snapshot from step 2. Summary: v3, 10 transactions, 2 accounts,
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
