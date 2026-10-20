# Local backup and restore

## Restore from the app (Step 9)

Close other app instances first. Click **Restore**, select a separate Personal
Finance SQLite backup and inspect the confirmation: schema version, transaction,
account and rule counts. No financial descriptions or account identifiers appear
in this summary. **No** is the default. Cancel leaves the live database unchanged.

The worker reads the selected backup through SQLite in read-only mode and validates
integrity, foreign keys and exact schema compatibility. Missing, corrupted,
unrelated and unsupported/newer schemas are rejected. It snapshots the selected
database into a new `backups/restore-stage-<unique-id>.sqlite3` inside the active
data directory. The staged copy is validated again; its digest and the current
database revision are checked on confirmation. Changed data requires a new preview.
The originally selected backup is never modified or deleted.

On **Yes**, a timestamped, validated safety backup of the current database is made
in that same `backups` folder. If validation or safety backup fails, restore does
not begin. SQLite's backup API copies the staged snapshot into the live connection
in a destination transaction; a failed/interrupted page copy rolls back. There is
no raw file replacement, deletion of WAL/journal sidecars or manual rename by the
GUI. Tests cover exceptions during copying, abrupt process exit with SQLite recovery,
WAL mode, stale previews and safety-backup failure. Power loss and faulty hardware
are not simulated; retain backups on a reliable local drive.

After success the app displays the safety backup path and disables further work.
**Close and reopen the app with the same data setting.** The worker also rejects
further operations until restart. Previews cannot overlap with import/review work.
Staged snapshots are retained after cancellation; they are private database files,
Git-ignored alongside backups. No bank statement Excel files are bundled in a backup.
This is a single-user operation; close other app instances before starting.

`RestoreService(repository, database).preview(path)` returns a summary/token.
`confirm(token, confirmed=True)` requires that exact pending preview, and returns
the safety backup path plus `restart_required=True`. `cancel()` clears the pending
decision without altering the live database.

The Step 8 manual procedure below remains available. The new GUI acceptance steps
are in [user_guide.md](user_guide.md#synthetic-manual-acceptance).

The toolbar Backup action selects an existing local folder. The database-owning
worker calls SQLite's backup API, not a file copy of the live database. A UTC
timestamp plus random suffix names the snapshot. Exclusive creation prevents
overwriting existing files. Integrity, foreign keys and schema checks must finish
before success is reported. Cancel writes nothing. Errors recommend checking
folder permissions, drive availability and free space, without logging raw
database contents or exception details. Only newly created incomplete artifacts
may be removed on failure; existing databases, statements and backups are retained.

`app.backup.create_backup(repository, folder)` returns the completed path.
`validate_backup(path)` opens read-only and requires integrity_check=ok, intact
foreign keys, schema version 3 and the exact schema supported by this app.
`prepare_restore(source, new_destination)` copies a closed backup to a new file
and validates that separate copy. It refuses existing destinations. Validation
does not initialize, migrate or repair its input. Older/newer or customized schemas
are conservatively rejected; use the matching app version instead of bypassing checks.

## Tested temporary restore exercise

Automated tests create invented transactions and a rule, snapshot them, reopen the
backup independently, verify integrity, prepare a separate restore, reopen it in a
temporary data directory and verify persistence. CLI prepare/validate are also
tested. These tests use workspace temporary directories and no GUI.

For manual verification, first complete docs/dashboard.md through backup/restart,
then **close the app**. Keep that PowerShell session and its variables:

```powershell
Set-Location 'C:\Personal Finance'
$syntheticSourceData = $env:PERSONAL_FINANCE_DATA_DIR
$selectedBackup = (Get-ChildItem -LiteralPath $syntheticBackupFolder -Filter 'finance-backup-*.sqlite3' -File | Sort-Object Name | Select-Object -Last 1).FullName
if (-not $selectedBackup) { throw 'Create the synthetic backup first.' }
$restoreExercise = Join-Path (Get-Location).Path ('data\restore-step8-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $restoreExercise -Force | Out-Null
$stagedCopy = Join-Path $restoreExercise 'validated-copy.sqlite3'
.\.venv\Scripts\python.exe -m app.backup prepare "$selectedBackup" "$stagedCopy"
if ($LASTEXITCODE -ne 0) { throw 'Stop: restore validation failed.' }
$temporaryData = Join-Path $restoreExercise 'restored-data'
New-Item -ItemType Directory -Path $temporaryData -Force | Out-Null
$restoredDatabase = Join-Path $temporaryData 'finance.sqlite3'
.\.venv\Scripts\python.exe -m app.backup prepare "$stagedCopy" "$restoredDatabase"
if ($LASTEXITCODE -ne 0) { throw 'Stop: restore preparation failed.' }
.\.venv\Scripts\python.exe -m app.backup validate "$restoredDatabase"
if ($LASTEXITCODE -ne 0) { throw 'Stop: restored database validation failed.' }
$env:PERSONAL_FINANCE_DATA_DIR = $temporaryData
.\start.bat
# Close the restored app before switching back:
$env:PERSONAL_FINANCE_DATA_DIR = $syntheticSourceData
```

Expected: each CLI operation reports PASS. The independently restored app has the
same 16 synthetic rows, two rules, protected edit and totals from the checklist.
The original synthetic database, selected backup and validation copy still exist.
Nothing is replaced or deleted. The user confirmed the normal synthetic launcher
smoke check passed on 2026-10-20. On 2026-10-21 the user confirmed backup creation,
restore preview validation and Cancel preserving data. Confirmed restore and
restored-app verification remain optional/pending (NOT RUN), not failures.
Automated backup/temporary-restore checks passed; the agent did not launch a GUI.

## Restore into the configured data location

1. Close every instance of the app. Choose a completed backup and keep it intact.
   Determine the configured location using the same environment as normal launch:
   `.\.venv\Scripts\python.exe -c "from app.config import get_data_dir; print(get_data_dir())"`.
2. Use `app.backup prepare` as above to make and validate a uniquely named copy
   separate from `finance.sqlite3`. Stop on any failure. Do not validate by opening
   the backup with Repository: that API initializes/migrates databases.
3. Before moving the current database, check for `finance.sqlite3-wal`,
   `finance.sqlite3-shm` and `finance.sqlite3-journal` in its data folder. If any
   remain, STOP. Reopen/close the matching app cleanly or obtain assistance; do not
   delete sidecars or copy just the main file from a live database.
4. Preserve the current database by renaming it within the SAME resolved data
   folder to a new name such as `finance-preserved-<unique timestamp>.sqlite3`.
   Verify the destination is inside that folder and does not exist. Do not delete
   it. Use PowerShell `Move-Item -LiteralPath` with explicit paths; do not use Force.
5. With the app still closed and `finance.sqlite3` now absent, run:
   `.\.venv\Scripts\python.exe -m app.backup prepare "<validated-copy-path>" "<configured-data-folder>\finance.sqlite3"`.
   This creates a new file and revalidates it, refusing any existing destination.
   If it fails, stop; the preserved original remains available.
6. Launch normally with the same data setting, verify totals/rules/edits, and retain
   the preserved database and backup. No automatic cleanup or deletion is provided.

## Windows launcher and tested environment

`C:\Personal Finance\start.bat` locates its own directory (including spaces), runs
that directory's `.venv\Scripts\python.exe -m app`, and preserves inherited data
configuration. It does not install anything. Missing-environment or nonzero startup
errors remain visible via pause. Double-click it, or run `.\start.bat` from this
workspace in PowerShell. Actual launcher execution: **PASS, user-confirmed
2026-10-20**, using the isolated synthetic data directory. The agent did not launch
or control the GUI. Extended restart/restore checks remain optional/pending.

Measured in the existing workspace environment on 2026-10-20: Python 3.15.0,
SQLite 3.53.4, openpyxl 3.1.5, et_xmlfile 2.0.0. Imported Tcl/Tk version constants
are 9.0/9.0; no Tk window was initialized for Step 8. No dependencies installed.
