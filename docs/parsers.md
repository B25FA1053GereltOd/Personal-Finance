# Parser API (Step 3)

The parser reads files without writing them, changing the database, launching
the UI, applying merchant rules, or deduplicating transactions. The implemented
format is documented separately in [khan_format.md](khan_format.md). Other
layouts are explicitly unsupported until verified from a supplied statement.

`app.parsers.base.StatementParser` is a protocol with `version`,
`detect(path) -> bool`, and `parse(path) -> ParseResult`.
Step 4 adds `parse_bytes(payload: bytes) -> ParseResult` so the import service
hashes and parses the same in-memory bytes without a private temporary copy.
The path entry point delegates to it; format interpretation is unchanged.
`app.parsers.khan.KhanParser` implements it with version `khan-mnt-1`.
Detection performs full validation; a recognizable but malformed, unreconciled,
or unsupported-currency statement returns false. Parse it to obtain the reasons.
Selection uses the verified headers and labeled metadata, not the filename,
worksheet name, or a fixed header row number. Exactly one matching sheet is
required. Unrelated nonmatching worksheets are not selected.

`ParseResult` provides:

- `metadata`: `StatementMetadata` with parser version, currency, text account
  identifier from the labeled IBAN, worksheet, ISO period boundaries, and ISO
  print date. Customer names are not included.
- `records`: ordered `ParsedTransaction` objects, each containing a normalized
  `source: app.models.ImportRow`, branch text, optional counterparty account,
  opening balance, signed credit and signed debit in integer hundredths.
  The source preserves original description/date text, worksheet, one-based
  row number, normalized ISO datetime, signed amount, MNT, and closing balance.
  `reference` remains None because this profile has no bank reference field;
  the counterparty account is not substituted for a reference. `dedup_key`
  remains None in parser results; the import service supplies versioned identity
  fingerprints during preview without changing the original parser records.
- `issues`: `ParseIssue` objects with a stable code, static message, severity,
  zero-based sheet index, one-based row number, and column letter where relevant.
  No message contains a cell value, filename, account, balance, or description.
- `checks`: named reconciliation outcomes (`passed`, `failed`, `not_checked`)
  for candidate-row accounting, per-row balances, running balances, credit
  total, debit magnitude total, endpoint balance, and chronological row order.
- `candidate_row_count`: nonblank potential transaction rows encountered;
  this includes malformed/unrecognized rows and excludes headers/totals.
- `is_valid`: true only when metadata exists and there are no error issues.

**Consumers must check `is_valid` before any later import.** A failed parse may
still return syntactically valid records to support local review; those records
are not an approved partial import. Financial reconciliation is `not_checked`
when structural/row errors prevent a complete comparison. Warnings currently
identify exact repeated headers that were explicitly skipped.

Descriptions, raw bank date/time text, account/branch text, and source order are
preserved. No POS/merchant splitting, date sorting, account-number coercion,
automatic income/expense classification, or Other category assignment occurs.
Blank rows are skipped only if both the original and cached cells are empty.
An unfamiliar nonblank row produces an error. Content after totals, missing
totals, unsupported headers, and merged-cell layouts are rejected explicitly.

The input is read once into memory. openpyxl opens original/formula and cached
views from that snapshot, and both workbooks are closed even on validation
failure. Required formula cells must have usable caches; optional account
formulas with missing caches are also errors, not silently missing values.
The parser never evaluates formulas or launches Excel. For numeric money,
OOXML numeric text goes directly to Decimal, preventing an intermediate float
from concealing excess precision. Text money uses the verified comma-grouping
and decimal-point convention. All arithmetic then uses integer hundredths.

Result/metadata/record representations omit sensitive fields. Callers must
still avoid logging explicit source fields or serializing actual statements
into test artifacts. Parser errors are safe summaries, not copies of exceptions.

## Synthetic fixture and tests

`tests/fixtures/khan_synthetic.xlsx` contains only invented names, identifiers,
descriptions, dates, and amounts. It reproduces the verified layout, includes
credits/debits/Unicode/blank rows, and has reconciling totals. Only this exact
fixture is exempted from the global XLSX ignore rule. `tests/khan_fixture.py`
recreates it; tests never search for or open real statements.

Use the workspace `.venv`. These commands keep temporary files inside the
project, including temporary files used by openpyxl and the earlier tests:

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

To regenerate only the synthetic fixture, run
`.\.venv\Scripts\python.exe -m tests.khan_fixture` after setting those temporary
directory variables. No new packages are required. Real statement compatibility
is checked separately and reported only as outcomes; no statement values enter
fixtures, test logs, or documentation.
