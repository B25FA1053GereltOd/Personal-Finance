# MVP acceptance and handoff

Verified 2026-10-21 against the persistent contract and the user's Prompt 1-9
requirements. `Personal_Finance_Tool_Requirements.txt` is absent, so the supplied
contract is the baseline. Existing functionality was preserved; Step 9 explicitly
authorized restore/export/usability additions. No critical service is a placeholder.
This is an automated acceptance result, not a claim of complete visual verification.

## Automated result

Full discovery: **233 tests; 228 passed, 0 failed/errors, 5 explicitly skipped GUI
tests**. Workspace `.venv` was used from an agent PowerShell process, not the visible
VS Code integrated terminal. Exact commands are in README.md. Python syntax and
changed-file whitespace checks passed. No packages were installed.

Tests contain only synthetic records/workbooks/databases. Existing focused tests
already covered the original critical behaviors; new tests target restore/export
boundaries and the combined offline scenario rather than duplicating every test.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Khan XLSX follows observed layout, dates/signs, preserves provenance and rejects malformed rows | `test_khan.KhanParserTests`, 33 tests using observed structure with invented values; `docs/khan_format.md` | PASS (synthetic) |
| Valid imports persist after reopening | `test_db`, `test_ui_flow`, `test_handoff.HandoffTests.test_offline_import_review_repeat_edit_restart_backup_and_temporary_restore` | PASS |
| Same file reimport adds zero | `test_import_service.test_identical_file_twice_is_no_write_even_renamed`; combined handoff scenario | PASS |
| Legitimate repeats retained, uncertain overlaps require decisions | `test_import_service` multiplicity, ambiguity, partial optional fields, stale preview and verified synthetic ID tests | PASS |
| Unknown merchants reviewable; scoped rules classify future imports | `test_classification`, `test_review_workflow`, combined handoff scenario | PASS |
| Manual category/field corrections survive imports/rule changes | `test_classification` manual override tests; `test_review_workflow`; combined scenario | PASS |
| Exact five income/eight expense categories seeded once | `test_db.RepositoryTests.test_repeated_initialization_seeds_exact_categories_once` | PASS |
| Malformed/canceled/failed imports leave no partial writes | `test_import_service`, `test_ui_flow`, atomic failure tests | PASS |
| Exact money and validated dates/category-direction edits | `test_models`, `test_db`, `test_review_workflow`; CSV max-integer test | PASS |
| Backup opens independently and restores into separate temporary location without replacing live data | `test_backup`, combined handoff scenario including unchanged-live comparison | PASS |
| Offline runtime without paid service, AI API, login or network | Combined scenario disables socket connection/DNS entry points; source audit found no app network calls (XML namespace URLs are identifiers) | PASS |
| Backup GUI boundary, exclusive names, validation/failure handling | `test_dashboard_ui` picker/worker test; `test_backup`; locked destination test | PASS (headless) |
| Restore preview/cancel, explicit confirmation, safety backup and restart guard | `test_local_operations.RestoreTests`; `test_handoff.LocalControllerTests` with real worker/services and widget stand-ins | PASS (headless) |
| Missing/corrupt/unrelated/newer database rejected without replacement | `RestoreTests.test_missing_corrupt_unrelated_newer_and_live_database_rejected` | PASS |
| Failed safety backup/interrupted restore preserves original data | Restore exception/page-copy rollback, abrupt subprocess exit/recovery, WAL and stale-preview tests | PASS |
| CSV BOM, Unicode, effective values, all filters/pages, exact amounts, no writes, empty export and safe formula text | `test_local_operations.ExportTests` and headless controller export check | PASS |
| Safe directory opening, Help/About and displayed versions | `LocalPathTests` mocks os.startfile with a path containing shell punctuation; headless Help/About callbacks | PASS (headless) |
| Run/debug uses workspace venv, module app, workspace cwd and integratedTerminal | `HandoffTests.test_workspace_run_debug_and_launcher_static_configuration` reads `.vscode` JSON | PASS (static) |
| Launcher locates own directory and venv, preserves errors, no automatic installs | Static launcher check; prior user Step 8 launch smoke test | PASS (static + prior user check) |
| Private statements, exports, databases, generated data/backups, .venv and nested repository excluded | Synthetic ignore probes and tracked/staged path audit, without reading private contents | PASS |

The combined scenario imports an invented Khan workbook, reviews an unknown
merchant, saves a rule, imports a new matching purchase, reimports the same file,
edits effective amount/description/note, changes a rule, reimports again, reopens,
backs up and restores to a separate temporary database. Manual protection, original
source values, rules and report totals are checked throughout. It runs with network
connect/DNS entry points disabled and does not initialize Tk.

## Actual GUI and statement evidence

| Check | Evidence | Result |
| --- | --- | --- |
| Step 1 F5 and Ctrl+F5 launch | User previously confirmed both | PASS (historical user-only) |
| Step 6 import/browser and Step 7 review/edit GUI | User previously confirmed manual acceptance | PASS (historical user-only) |
| Step 8 launcher, isolated directory, Dashboard opening, all-time MNT/USD totals/counts, income/expense breakdowns/percentages | User smoke-test report on 2026-10-20 | PASS (user-only) |
| Extended Step 8 monthly/date/drill-down/refresh/restart/backup UI checks | User stopped the checklist; not failures | NOT RUN (optional/pending) |
| Step 9 start.bat, CSV export, backup, restore preview validation and Cancel preserving data, Help/About version/data directory, Open data folder | User confirmed synthetic smoke test on 2026-10-21 | PASS (user-only) |
| Step 9 confirmed restore/restart, extended GUI failure cases, responsiveness/layout checks | Not reported as manually verified; agent GUI launch prohibited | NOT RUN (optional/pending, not failures) |
| Current F5/Ctrl+F5, File Explorer launch/from other directory | Static configuration verified; execution would launch GUI | NOT RUN this step |
| Current VS Code extension/debugger installation | Workspace configuration matches debugpy; extension inventory outside project not accessed | NOT RUN this step; setup instructions in README |
| Actual Khan statement recheck | Latest user constraint prohibits accessing private_statements or any real financial file | NOT RUN; current real-statement verification incomplete |
| Earlier actual Khan statement compatibility | Previously recorded Step 3/5 verification in format docs and user history, not repeated now | PASS (historical evidence only) |

No real statement's presence or contents were inspected this step. Historical
compatibility does not establish compatibility with a new bank layout.

## Limitations and next action

- No automated blockers remain. The reported synthetic smoke checks passed.
  Confirmed restore/restart and extended visual checks remain pending, not failed;
  [the isolated checklist](user_guide.md#synthetic-manual-acceptance) remains available.
- Restore requires closing other app instances and a restart afterward. Safety
  backups/staged copies are retained. Exact schema compatibility is conservative;
  customized/older/newer schemas require the matching app, not guessed migration.
- Interruption tests cover process exit and exceptions; no claim is made about
  faulty hardware or power-loss testing.
- Khan parsing supports only the verified MNT layout. Authorization prefixes are
  not unique bank references; overlaps can require explicit Keep/Skip decisions.
- CSV serializes exact decimal text. Excel auto-detection can alter long numbers
  or leading-zero identifiers; import those columns as Text. Formula-like text
  receives a protective apostrophe. Exports are private financial files.
- No installer/executable packaging, server, telemetry, login or cloud dependency
  was added. The user authorized a local Prompt 9 commit after verification.
  No private financial files are included; no push or nested-repository change.
