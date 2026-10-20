# Status

Steps 1-8 preserved. Step 9 acceptance, confirmed restore, CSV export and local
usability implemented; schema v3 unchanged.

Restore validates/stages a snapshot, previews counts, requires explicit confirmation
and a validated safety backup, then uses an atomic SQLite destination transaction.
Source backups are retained; success requires restart. CSV exports all applied
filters/pages with effective values, UTF-8 BOM, exact decimal text and formula-text
protection; empty results create no file. Account filter, Help/About, app/schema
versions and safe Open data folder added. Existing start.bat retained.

Public APIs: RestoreService.preview/confirm/cancel; export_csv; open_data_folder;
Repository.change_token/restore_from/read_snapshot; shared models.review_status.
Worker commands: restore_preview/restore_confirm/restore_cancel/export_csv.

Checks (2026-10-21): 233 discovered, 228 passed, 0 failed, 5 GUI tests explicitly
skipped. Full offline synthetic import/classify/repeat/edit/reopen/backup/temporary
restore scenario passed. Restore interruption, safety failure, WAL, CSV filters,
precision and controller guards passed. Syntax: 42 Python files. Whitespace and
24 ignore probes passed. Only Step 9 source/tests/docs selected for the local commit.
After README TEMP/TMP setup:
`$env:PERSONAL_FINANCE_SKIP_GUI_TESTS='1'`;
`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
Launch: `& 'C:\Personal Finance\start.bat'`.
Evidence matrix: docs/acceptance.md. User guide/checklist: docs/user_guide.md.

User smoke PASS (2026-10-21): launcher, CSV export, backup, restore validation/Cancel
preserving data, Help/About version/data directory and Open data folder.
Prior Dashboard smoke passed. Confirmed restore/restart, F5 and extended GUI checks
remain optional/pending NOT RUN, not failures. Real-statement recheck NOT RUN by
privacy instruction.

No automated blockers. No private data accessed, agent GUI launched, packages
installed, nested repository modified or push. Next: await user direction.
