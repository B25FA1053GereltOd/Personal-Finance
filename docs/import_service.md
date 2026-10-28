# Safe import service (Step 4)

`ImportService` coordinates the existing parser and repository. It has no UI,
network calls, logging, or new package requirements. Step 5 connects deterministic
[classification services](classification.md) inside the import transaction. The caller
opens a repository and selects an existing account first. Repository construction
initializes/migrates storage; preview and cancel themselves never write it.

## Workflow and public API

1. Construct `ImportService(repository)` for Khan, or supply `parser` explicitly.
2. Call `preview(path, account_id) -> ImportPreview`. The file is read once;
   SHA-256 and `parser.parse_bytes` use those exact bytes. No temporary source
   copy is written. Account identifier, currency, and bank must match. Khan
   accounts use the labeled IBAN; other account-number aliases are not guessed.
3. Present the preview locally. `cancel(preview)` only discards in-memory state.
   After explicit confirmation, call `confirm(preview, decisions)` where decisions
   maps each ambiguous **zero-based incoming index** to `"keep"` or `"skip"`.
   These indexes differ from one-based worksheet row numbers. Missing, extra,
   or invalid decisions block confirmation, including missing keep choices.
4. Display success only after confirmation returns `ImportResult(status,
   import_id, imported_count, skipped_count)`. Status is `committed` or
   `identical_file`. The latter references the earlier import and writes nothing.
   A different file whose rows are all skipped still records its import/audit.
   Imports append only newly retained rows; they never replace earlier
   transactions. The desktop summary separately shows Added, Duplicate skipped,
   Invalid, Unclassified added and total Skipped. A commitable preview has zero
   invalid rows; invalid rows remain visible in the blocked preview.

Confirmation applies to the immutable preview snapshot even if the source file
later changes. Re-preview to use changed contents. Previews belong to their
service instance, cannot be edited/restored from serialized copies, and are
consumed after success/cancel. They do not survive process exit. A failed write
allows retry; changed account import state requires a fresh preview.

## Preview model and counts

`ImportPreview` exposes `rows`, `groups`, `issues`, `is_valid`, and disjoint counts:

- `valid_count`: new rows without existing matches.
- `duplicate_count`: identical-file rows or proven unique-reference matches.
- `ambiguous_count`: incoming rows requiring explicit decisions.
- `invalid_count`: malformed/rejected transaction rows, not diagnostic count.

Blank/header/total rows are excluded. An unreadable file has no known candidate
rows, so counts may all be zero while `is_valid` is false. Statement-level errors
also block the complete import even with zero invalid rows. No good-looking
subset of a failed statement is imported. Failed reconciliation blocks too.

`PreviewRow` contains `index`, `source: ImportRow`, `status`, and `candidates`.
Each `ExistingRow` contains transaction/import IDs and immutable original source
values. `AmbiguousGroup.row_indexes` points to new rows in `preview.rows`;
`existing` contains the connected existing candidates. Each row retains its
specific candidate edges for optional-value ambiguity. These models support
side-by-side local review. Representations omit source fields; explicit access
to those fields is private and must never be logged or copied to documentation.

## Duplicate policy and limits

- File SHA-256 matches are scoped to the account; renaming a file does not bypass
  them. Other accounts are independent.
- The observed Khan format has no bank-reference column or verified unique ID.
  Counterparty accounts are not references. **Khan cross-file matches require
  decisions**, even when all compared values match: equal values alone cannot
  prove that two occurrences are the same transaction.
- Fingerprints compare account, currency, original ISO date/time including
  precision, signed integer amount, exact original description, and optional
  reference/closing balance. Text is not trimmed and dates are not rounded.
  Filename, worksheet and row are provenance, not cross-file identity.
- Conflicting non-null optional fields distinguish fallback candidates; missing
  values are unknowns when finding ambiguous matches. Differences in other
  compared fields or date precision may prevent matching. This does not claim
  universal deduplication across corrections or different export formats.
- First imports retain every occurrence, even repeated fingerprints. No unique
  fingerprint/date/amount constraint is added. Each skipped incoming occurrence
  must match a distinct existing candidate. Extra repetitions cannot all be
  skipped against one earlier occurrence. Keeping every ambiguous row is allowed.
- `VerifiedReferencePolicy(bank, parser_version, namespace, evidence)` is a
  developer integration contract, not a user preference. Supply it only after
  verifying stable, per-account unique references for that exact bank/parser.
  No production policy is registered. Tests use a **synthetic bank contract**;
  they are not evidence of real Khan reference semantics.
- With that policy, one incoming reference and one proven existing reference
  with equal immutable values can be skipped. Changed values, multiple candidates,
  or legacy rows lacking verified identity require review. Repeated supposedly
  unique references inside one file are errors, never silently collapsed.

Reference and fallback fingerprints have separate versioned prefixes. Legacy
null-fingerprint rows still match by original fields. Effective amounts, text,
dates, categories, locks, notes, and edit history neither enter matching nor
get overwritten on reimport.

## Atomic storage

`Repository.get_import_state(account_id)` reads account/import/original-row
state in one read transaction without UI pagination. Its revision ignores manual
effective edits. `write_import(..., expected_revision=..., decisions=...)`
checks that revision under `BEGIN IMMEDIATE` before any insertion. Concurrent
imports stale the preview, closing the duplicate-check/write race. Manual edits
during preview remain intact.

Schema v2 adds append-only `import_decisions` and a nonunique file lookup index
with an atomic migration from v1. Every committed incoming row has an audit
entry with original values/provenance/fingerprint, action, reason (`new`,
`verified_reference`, `manual`), and candidate transaction IDs. Skipped source
rows remain reviewable. Metadata records hash, account, parser version, filename,
UTC time, and complete counts. Metadata, retained rows, and decisions commit
in **one SQLite transaction**, or all roll back. Read saved decisions using
`get_import_decisions(import_id)`. This is private database storage, never logs.

The backward-compatible low-level repository still accepts validated rows
without previews; statement import callers must use `ImportService`.
`ImportBlocked` provides safe messages for invalid input, decisions, stale
previews, and database failures; raw SQLite exception text is suppressed.
Success is returned only after commit completes.

Step 5 supplies a `ClassificationService` automatically, or accepts one through
`classification=` on the same repository. Its callback runs within `write_import`
before the outer commit; classifications/audits roll back with rows and decisions.
Rule changes affect future imports only unless old rows are explicitly selected
through a rule preview. Khan merchant extraction supports only the confirmed
authorization-prefix purchase pattern documented in `khan_format.md` and keeps
the complete remainder as its key. Credits and unsupported descriptions remain
unclassified. Authorization tokens do not change reference/deduplication policy.
The Prompt 12 Mapping Table evaluates active mapping rules before those legacy
exact merchant rules. Mapping rules do not change source values, currency, or
deduplication identity; existing rows change only after explicit preview and
selected application.

## Checks

Run in the workspace's integrated PowerShell terminal:

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_import_service.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Tests use the synthetic workbook, invented parser records, and workspace temporary
databases. They cover first/identical imports, synthetic verified IDs, Khan overlap,
multiplicity, malformed files/rows, cancel, row/audit rollback, edited originals,
concurrent changes, exact-byte snapshots, and atomic migration. Step 4 does not
open/import a real statement or launch the app.
