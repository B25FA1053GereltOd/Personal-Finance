# Database and money API

The window and entry point remain unchanged. Storage is available through
`app.db.Repository`; running `python -m app` still displays the Step 1 window.
Parsing and safe import orchestration are separate from this persistence layer.
The import UI and automatic classifier remain future work.

## Opening and lifetime

Use `with Repository(path) as repository`, or call `close()` explicitly.
`Repository()` uses `get_data_dir() / "finance.sqlite3"`, creates its parent
directory if necessary, and initializes the database. Passing an explicit path
is useful for tests. Relative explicit paths are relative to the caller's
working directory; the default configuration remains independent of it.

Each repository owns one sqlite3 connection with foreign keys enabled and
explicit `BEGIN IMMEDIATE`/commit/rollback write transactions. Schema creation,
category seeding, imports, edits with audit records, and rule changes are atomic.
Do not share a repository across threads or access its private connection in
application code. Tests access it only to inject failures or verify constraints.

The schema is version **2**, recorded with `PRAGMA user_version`. Repeated
initialization and reopening preserve category IDs and seed no additional rows.
Unsupported versions and nonempty unversioned databases are refused, not
overwritten. The schema uses SQLite STRICT tables (SQLite 3.37+) and JSON
validation; this workspace has SQLite 3.53.4. Step 4 atomically migrates version 1
by adding append-only import decisions and a nonunique account/file-hash index.
Existing categories, imports, transactions, edits, and rules are preserved.

## Model inputs and values

- `money_to_minor(str | Decimal | int) -> int` converts MNT to integer hundredths.
  For example, `"-1250.50"` becomes `-125050`. `minor_to_money(int) -> Decimal`
  reverses that conversion exactly, independently of Decimal context precision.
  Floats, booleans, non-finite values, grouped/locale-dependent text, excess
  decimal places (even `"1.230"`), and 64-bit integer overflow are rejected.
- `ImportInfo(account_id=..., sha256=..., parser_version=..., filename=...)` is
  frozen, validated metadata. The import service supplies the actual file's
  SHA-256; this repository does not read or hash files.
  Supply only the filename, not a path. SHA-256 is stored as lowercase hex.
- `ImportRow(description=..., bank_datetime=..., occurred_at=..., amount_minor=...,
  worksheet=..., row_number=..., currency="MNT", reference=None,
  balance_minor=None, dedup_key=None)` is a frozen source row. Row numbers are
  one-based. `bank_datetime` preserves the bank-supplied date/time text exactly.
  `occurred_at` must already be an unambiguous ISO calendar date or a datetime
  with seconds, optional microseconds, and optional `Z`/UTC offset. The model
  validates dates and never guesses a locale or invents a missing time.
  The parser is responsible for interpreting the statement format.

Account identifiers and optional references remain text, including leading
zeros. Missing references and balances are stored as SQL NULL; zero and empty
reference text remain distinguishable from missing values. Currency is an
uppercase three-letter code and must match the account. No currency conversion
is performed. The amount conversion contract in this step is MNT hundredths.

## Repository methods

Read methods return fresh dictionaries (or lists of dictionaries), never live
database cursors. Creates return integer IDs. Invalid application inputs and
missing records raise `ValueError`; database constraint violations raise
`sqlite3.IntegrityError`. Neither successful nor failed operations log source
rows or statement contents.

| Method | Behavior |
| --- | --- |
| `initialize()` | Idempotent version check/initialization, also called on construction. |
| `create_account(identifier, name, *, bank="Khan Bank", currency="MNT")` | Create an account; identifier must be text. Duplicate bank/identifier/currency is rejected. |
| `list_accounts()`, `list_categories()` | Read accounts and the 13 exact seeded income/expense categories. |
| `write_import(info, rows, *, skipped_count=0, rejected_count=0, expected_revision=None, decisions=())` | Commit metadata, supplied `ImportRow` values, and decisions together, or none. Optionally reject stale previews under the write lock. Return import ID. |
| `get_import_state(account_id)` | Consistent read-only account/import/original-row snapshot and revision, unaffected by effective edits. Contains private data; never log it. |
| `get_import_decisions(import_id)` | Read saved source-row dispositions, reasons, and candidate IDs in incoming order. |
| `get_import(import_id)` | Read hash, account, parser version, filename, UTC import time, and counts. |
| `get_transaction(transaction_id)` | Read original and effective values, provenance, and classification state. |
| `query_transactions(...)` | Filter and paginate effective values; arguments are described below. |
| `assign_category(transaction_id, category_id, *, reason)` | Explicit manual assignment; selects the category's kind and validates amount direction. `None` returns the item to unclassified review. |
| `edit_transaction(transaction_id, *, reason, **changes)` | Atomically validate/edit effective fields and append an audit delta. Return the updated transaction. |
| `get_history(transaction_id)` | Read edits oldest first, with UTC time, reason, and decoded `changes` mapping of field to old/new values. |
| `upsert_rule(merchant_key, direction, kind, category_id=None)` | Create/update a rule by exact merchant key and direction; return its stable ID. |
| `list_rules()`, `delete_rule(rule_id)` | Read/delete merchant rules. No automatic rule application yet. |

Query keyword filters: `account_id`, `import_id`, `kind`, `category_id`,
`review_only`, `date_from`, and `date_to`. Defaults are `limit=100, offset=0`;
page size is 1–1000. Date bounds are inclusive `YYYY-MM-DD` values and refer to
the stored effective bank-local date. Results are ordered by effective ISO
timestamp text descending, then ID descending for stable ties. Offsets are
preserved; this order is not a cross-timezone UTC chronology. `review_only=True`
selects unclassified items and income/expense items without a category. Query
results additionally include `account_id`.

## Immutable sources and manual edits

Every transaction has an immutable generated `source_id` and `import_id`.
`original_description`, `original_occurred_at`, `original_amount_minor`,
`original_currency`, `original_reference`, and `original_balance_minor` preserve
the initial parsed values. `bank_datetime`, `worksheet`, `row_number`, and
`dedup_key` preserve source provenance/identity. Database triggers reject their
modification, import-metadata modification, and transaction deletion. Use an
explicit excluded kind instead of deleting bank data. Category direction and
an imported account's identifier/bank/currency also cannot change.

Editable effective fields are `description`, `occurred_at`, `amount_minor`,
`currency` (must still match the account), `reference`, `balance_minor`, `kind`,
`category_id`, `merchant_key`, `note`, and `manual_lock`. Source/identity fields
are not accepted by the edit API. A manual edit sets `classification_source` to
`manual` and defaults `manual_lock` to true; explicitly pass the boolean false
to unlock. Changes are validated as one combined final state. Only changed
fields enter the compact JSON audit record; a no-op creates no audit record.
If audit insertion fails, the effective edit rolls back too. History is append-only.

New imports start with `kind="unclassified"`, no category or merchant key,
`classification_source="unclassified"`, an empty note, and no manual lock.
Positive/negative amounts alone never assign income/expense or an Other category.
Income requires a positive effective amount; expense requires a negative one.
A category, when present, must match the kind. Income/expense can remain without
a category for review. `transfer` and `excluded` are explicit kinds, accept any
sign including zero, and must have no income/expense category. To change the
sign of a categorized transaction, supply a compatible kind/category in the
same edit, or explicitly reset the kind and category to unclassified/None.

Rules store exact caller-supplied merchant keys and `credit`, `debit`, or `zero`
directions. Income/expense rules require compatible categories and signs;
transfer/excluded rules must have no category. Rule changes never alter existing
transactions or bypass their manual locks in this step.

Import `imported_count` is computed from the supplied rows; `total_count` is
imported + skipped + rejected. Caller-supplied skipped/rejected counts are
nonnegative integers. The entire supplied iterable is consumed in the atomic
write; a failing row leaves neither metadata nor earlier rows behind.

Step 4 implements fingerprints and duplicate handling in the
[import service](import_service.md). `dedup_key` remains optional and immutable;
it is never constrained unique. Generated `source_id` identifies an occurrence,
not its content. The low-level repository remains backward compatible;
statement imports must use the service for preview and duplicate policy.
`ImportDecision` supplies row index, source, keep/skip action, reason, and candidate
IDs. If supplied, decisions must account for every incoming row; kept sources
must equal the supplied rows in order, and candidates must belong to the selected
account. A stale `expected_revision` raises `ImportStateChanged` before insertion.
Decision writes and revision checking share the import transaction. Legacy
imports have no decision entries.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Database tests create and clean up temporary databases within the project.
Fixtures contain only synthetic text, paths, identifiers, and amounts. They
exercise rollback, source immutability, exact money, category/sign compatibility,
foreign keys, reopening, query pagination, rule CRUD, and audit persistence.
