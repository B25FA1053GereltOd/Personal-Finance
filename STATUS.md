# Status

Steps 1–4 complete. Step 5 has not started. The UI, entry point, configuration,
requirements, and real statement are unchanged.

Step 4 adds safe import preview/cancel/confirmation, counts, source fingerprints,
multiplicity-aware overlap review, saved keep/skip decisions, atomic commits,
and stale-preview protection. Khan has no verified unique reference: cross-file
matches require explicit decisions. Identical file hashes are skipped per
account. Manual categories, values, locks, and history are preserved.

Public interfaces:
- `ImportService(repository, parser=None, reference_policy=None)`:
  `preview(path, account_id)`, `cancel(preview)`, `confirm(preview, decisions=None)`.
- `ImportPreview`, `PreviewRow`, `ExistingRow`, `AmbiguousGroup`, `ImportResult`,
  `ImportBlocked`, and evidence-based `VerifiedReferencePolicy` (no production
  reference policy registered).
- `Repository.get_import_state`, `get_import_decisions`; `write_import` adds
  optional `expected_revision` and `decisions: ImportDecision` values.
- Parser `parse_bytes` shares the exact hashed snapshot; existing path API remains.

Schema v2 atomically migrates v1, adding immutable decision storage and a
nonunique file-hash index. Earlier APIs remain compatible.

Checks: **105 unittest tests passed**, including **33 new import-service tests**
and all 33 parser tests. Covered acceptance cases, synthetic Khan overlaps,
rollback during rows/decisions, reopening, concurrent imports, and migration.
Tests used synthetic data and workspace temporary files. Prompt 3's real
statement verification remains recorded; no real statement was opened in Step 4.

Git verification: all 27 ignore probes passed; existing private financial files
remain ignored and untracked. Local commit scope contains only the 13 reviewed
Prompt 4 files. No packages installed, app launched, or push performed.
Details: `docs/import_service.md`, `docs/database.md`, `docs/parsers.md`.

Blockers: none. Next: await instruction for Prompt 5.
