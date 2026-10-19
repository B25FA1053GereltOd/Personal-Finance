# Status

Steps 1–5 complete within the documented MVP scope; Step 6 is not started.
The remaining Step 5 extraction blocker is resolved. UI, entry point, parser,
database schema and real statements are unchanged by this repair.

User-confirmed Khan card/POS descriptions have a six-character ASCII alphanumeric
authorization token, whitespace, then merchant text. Production extraction removes
only that prefix/separator and normalizes the complete remainder, preserving
numbers, punctuation, domains and locations. Evidence: `khan-card-auth6-v1`.
Original descriptions and deduplication identity remain unchanged; authorization
tokens are not unique bank references.

Only compatible debit purchases use exact saved rules. Credits/refunds, QPay,
transfer/fee wording, malformed and unsupported descriptions remain unclassified.
Manual locks, selected-only retroactive application, disabled rules, and atomic
import/classification audits retain their existing behavior.

Public interfaces unchanged:
- `extract_merchant`, `normalize_merchant_key`, `MerchantMatch`.
- `ClassificationService`: `review`, `assign_category`, `reclassify`, `save_rule`,
  `disable_rule`, `preview_rule`, `cancel_rule_preview`, `apply_rule`, `classify_import`.
- Existing preview/review models and repository/import APIs: see
  `docs/classification.md`, `docs/database.md`, `docs/import_service.md`.

Checks (2026-10-19): **77 tests passed** — 33 parser and 44 classification,
including nine new synthetic tests. Command:
`.\.venv\Scripts\python.exe -m unittest tests.test_khan tests.test_classification`.
The earlier full suite passed 140 tests; it was not rerun for this repair.

Actual statement compatibility **VERIFIED** locally: parsing, source accounting/order,
reconciliation, purchase extraction, complete remainder preservation, QPay abstention,
and unchanged workbook content. No real values were recorded. No GUI, installs,
external access, commit or push.

Blockers: none. Next: await authorization for Step 6; unsupported descriptions
continue through manual review.
