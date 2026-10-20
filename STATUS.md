# Status

Steps 1-7 complete. Step 8 Dashboard and backup/launcher implemented.

Dashboard provides currency totals, classified income/expenses/net,
unclassified counts, category percentages and monthly tables.
Inclusive calendar presets/custom ISO dates and category/month drill-down retain
currency/date filters. Import, edit, classification and rule application refresh
through the existing worker queue. Transfers/excluded/unknown amounts are omitted;
net is not a bank balance. Source identities and schema v3 are unchanged.

Backup uses SQLite's backup API, exclusive timestamped destinations and integrity,
foreign-key/schema validation before success. Restore preparation validates a
separate file without overwriting data. start.bat uses .venv with visible errors.

Public APIs: ReportingService.summarize, date_range, category_filters,
month_filters; Repository.reporting_rows, backup_to, schema_definition and currency
query/count filters; backup.create_backup, validate_backup, prepare_restore.
Worker commands: dashboard and backup. Manual instructions: docs/dashboard.md
and docs/backup_restore.md; tested versions in README.md.

Checks (2026-10-20): full suite 207 discovered, 202 passed, 0 failed, 5 GUI tests
explicitly skipped. Synthetic tests cover calculations, dates, currencies,
drill-down, refresh/restart, error recovery, independent backups, WAL, collisions,
rollback-safe failures and CLI temporary restore. Syntax/whitespace and ignore
checks passed. Only Step 8 source, tests, documentation and launcher are selected
for the local commit. No private financial files accessed or staged;
no agent GUI launch, dependency install, nested-repository change or push.

User-confirmed smoke PASS (2026-10-20): start.bat, isolated synthetic directory,
Dashboard opening, MNT/USD all-time totals/counts and income/expense category
totals/percentages.

Optional/pending, NOT RUN (not failures): monthly tables, presets/custom date
validation, drill-down, mutation refresh, restart persistence, backup UI and manual
restore. The user stopped the extended checklist. Blockers: none for this commit.
Next: await direction; do not resume the checklist.
