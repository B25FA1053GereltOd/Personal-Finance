# Status

Steps 1-7 complete. User confirmed Step 7 GUI verification passed
on 2026-10-20. No later step started.

Review groups reliable unknown merchants with counts, totals, examples and paged
expandable transactions; unreliable/protected items remain individually available.
Selected-only assignment is the default. A read-only preview precedes confirmation;
optional future-rule saving and selected assignments commit atomically. Skip/cancel
write nothing. Stale transaction/rule snapshots are rejected.

The editor supports effective ISO date, exact signed money, description, merchant
display, kind/category and note, with read-only source and history tabs. Manual
protection defaults on; clearing it is explicit. Source fields, matching keys and
deduplication identity survive corrections. Rule list/edit/disable affects future
imports only; retroactive changes require preview and explicit eligible selection.

Public interfaces: ReviewService load/preview_assignment/confirm_assignment/cancel,
preview_rule/apply_rule/change_rule, edit_get/edit_save. FinanceWorker adds review_,
rule_ and edit_ commands. Repository.atomic composes existing APIs; merchant_display
is now an independently editable, validated, audited field. Schema v3 is unchanged.

Checks (2026-10-20): full discovery **188 tests: 183 passed, 5 GUI tests explicitly
skipped**. Thirteen new service/worker/headless-controller checks cover cancellation,
rollback, future tagging, protected edits/reimport, source preservation, validation,
stale operations, selected-only retroactive changes, disabling and persistence.
GUI acceptance is user-verified; no agent visual verification claimed.

Synthetic fixtures: data/review-fixtures/review-initial.xlsx, review-future.xlsx,
review-disabled.xlsx. Exact manual commands and steps: docs/review_ui.md.
Pre-commit ignore checks cover private statements, financial exports, data/retest
databases, SQLite sidecars, backups, .venv and the nested repository. Only Step 7
source, tests and documentation are selected. No private contents accessed or
logged; no GUI launched, packages installed or push performed.

Blockers: none. Next: await further authorization.
