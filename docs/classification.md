# Merchant rules and review (Step 5)

`ClassificationService` provides deterministic saved rules and explicit review
operations. It has no AI/network calls, logging, or GUI. No real-merchant
categories are seeded. Transaction-only assignment is the safe default;
rule saving and retroactive application are separate explicit operations.

## Verified production extraction

`extract_merchant(bank, parser_version, description)` supports only the
user-confirmed Khan six-character ASCII alphanumeric authorization prefix,
followed by spaces/tabs and nonempty merchant text. Local inspection verified
that structure in the supplied statement. See `docs/khan_format.md`.
It removes only the first token and separator and retains the entire remainder
as display text. The normalized complete remainder is the key; numbers,
punctuation, domains and locations are never stripped. The evidence ID is
`khan-card-auth6-v1`; bank/parser scope is `Khan Bank` / `khan-mnt-1`.

The service accepts this purchase evidence only for negative original amounts.
Credits/refunds and zero amounts remain unclassified, including with a saved
credit rule. QPay, transfers, fees and unsupported descriptions supply no
merchant evidence. Explicit non-purchase word markers also cause abstention,
even with a code-shaped prefix. Malformed, multiline or unsupported prefixes
return `None`. Exact rule eligibility still protects locks, transfer/excluded
kinds and effective direction. Matching never changes original descriptions,
references or deduplication identity; the authorization token is not a unique ID.

A developer may supply `extractor=` for a verified bank/parser format. It returns
`MerchantMatch(display_text, pattern, transaction_type)` for a confidently
identified POS purchase/refund, or `None`. Type defaults to `purchase`; `refund`
is explicit. Transfer text must not be represented as merchant evidence. The
separate invented test grammar exists only in tests, never production extraction.
Extractor exceptions abort safely without exposing source text.

Keys use NFC Unicode normalization, casefolding, and collapsed/trimmed whitespace,
then NFC again. Digits, branch names and punctuation remain. Compatibility
characters are not folded with NFKC. `normalize_merchant_key` is available from
`app.classification` and `app.models`. Display text retains its extracted case
and whitespace. Rules never rewrite original or effective bank descriptions.

## Service API

Construct `ClassificationService(repository)`. The optional extractor is a
developer integration seam, not a configurable fuzzy or regex rule engine.

| Operation | Behavior |
| --- | --- |
| `review()` | Read-only `ReviewQueue` of exact bank/key/direction groups and individual rows without reliable keys or manually locked for review. |
| `assign_category(transaction_ids, category_id, reason=...)` | Atomically assign only selected rows; mark manual and lock; create no rule; return count. |
| `reclassify(transaction_id, category_id, reason=...)` | Manual one-row override with the same protection. `None` explicitly returns it to locked manual review. |
| `save_rule(bank, merchant_text, direction, category_id)` | Save/update and activate an exact scope for future imports. Return stable rule ID; change no old rows. |
| `disable_rule(rule_id)` | Stop future application without altering previous classifications. |
| `preview_rule(rule_id)` | Read-only `RulePreview` of eligible unlocked matches and target category. |
| `cancel_rule_preview(preview)` | Discard memory state without writes. |
| `apply_rule(preview, transaction_ids)` | Apply an explicitly selected subset; no default “all.” Empty selection changes nothing. Return count. |
| `classify_import(import_id)` | Import callback: extract original merchant evidence and apply current active rules before commit. |

Rules match `(bank, normalized merchant key, debit/credit direction)` exactly.
One stored rule per scope includes its disabled state. Saving it again retains
its ID and increments revision. Changing scope means saving a separate rule and
explicitly disabling the old one. Debit category rules require expense categories;
credit category rules require income categories. No fuzzy, substring, wildcard,
or regex matching exists. Legacy low-level transfer/excluded rules are retained
for compatibility but never applied automatically by the classifier.

## Classification Mapping Table (Prompt 12)

`MappingService` evaluates user-created rules before the legacy exact merchant
rules during the same atomic import callback. It is deterministic and has no AI
or network calls. A mapping rule stores its name, integer priority, enabled
state, optional bank/account scope, optional debit/credit direction, source
field (`pos_id`, normalized merchant, or original description), operator,
match value, target kind/category, timestamps and revision. Highest priority
wins; equal priorities use ascending persistent rule ID. A global rule can
match any bank; bank-scoped and account-scoped rules require exact identity.

Operators are exact, contains, starts with, ends with, and Python regular
expression search. Merchant/description text is NFC-normalized, casefolded,
and whitespace-collapsed; punctuation and digits are retained. POS IDs are
NFC-normalized and trimmed without casefolding. The parser sets a POS ID only
when a verified bank format exposes one. The supported Khan parser currently
does not expose one, so Khan `pos_id` values remain NULL. The original bank
description is never rewritten by a mapping rule.

Income targets require a positive credit and a compatible income category;
expense targets require a negative debit and a compatible expense category.
Transfer/excluded targets have no category. Rules only classify currently
unclassified, unlocked transactions. Manual assignments remain protected.
Currency and deduplication identity are not mapping targets and cannot change.
Each applied mapping stores a rule ID/name snapshot for transaction display.

Saving, editing, disabling or deleting a rule has no retroactive effect. For
existing rows, **Preview matching transactions** creates a service-owned
candidate list. The user must select rows in that preview and explicitly apply;
empty selection is rejected. Only currently eligible rows for which the rule
is still the winning rule are previewed. Rule and transaction revisions are
rechecked atomically before any write. Applying one rule does not silently
reclassify transactions assigned by another rule or manual corrections.

The Mapping Table UI supports search, active-state and bank-scope filters,
add/edit, enable/disable, delete with confirmation, synthetic rule testing, and
preview/apply. Empty match values and invalid regex syntax are rejected. Short
Contains patterns receive a specific breadth warning; users see synthetic
match testing before saving. See [mapping_rules.md](mapping_rules.md) for
fictional examples and operating guidance.

Verified purchases require negative original/effective amounts to use a debit
rule. Verified refunds require positive original/effective amounts and a separate
credit rule. Debit purchase rules cannot classify refunds, transfers, non-POS
credits, zero amounts, or changed directions. Explicit transfer/excluded rows
are ineligible. Unknown rows never default to Other; an explicit compatible
Other assignment counts as classified and leaves review.

`ReviewItem` exposes transaction ID, bank, effective direction/description/amount,
merchant evidence and manual-lock state. `MerchantGroup` has bank/key/direction
and its items. Locked unknowns remain individual. `RulePreview` has rule ID and
revision, target category, candidate items, and immutable `RuleSelection` values.
Source/merchant fields are excluded from repr; explicitly accessed private fields
must never be logged. Previews belong to their service instance and cannot be
edited, replayed after success/cancel, or restored from serialized copies.

## Persistence and atomicity

Schema v3 adds merchant-rule bank scope, display text, active state and revision, plus
transaction merchant display/pattern/type and applied rule ID/revision. Applied
IDs are foreign keys; rules cannot be physically deleted. Legacy v1/v2 rules had
no bank scope. Migration preserves their IDs/text and disables them with an empty
unknown bank scope; it never guesses a bank or merges existing keys. Explicitly
re-save with the correct bank. All other source data/history survives migration.
Schema v4 adds the Mapping Table rules, optional immutable POS ID, and mapping
rule attribution snapshots. The migration preserves existing rows and seeds no
real or guessed mapping rules.

`ImportService` classifies at confirmation. Its optional `classification=` instance
must share the repository. `Repository.write_import(..., classify=...)` invokes
the callback before the outer commit. Nested operations use savepoints, so import
metadata, rows, decisions, classification and audits roll back together on any
failure. Automatic classification is allowed only inside that new import callback;
reusing it afterward is rejected and requires a rule preview instead.
An identical-file skip does not reclassify old rows. Current rules at
commit govern new rows; import preview does not freeze rules or predict categories.

Saving/editing/disabling a rule never updates old rows. Retroactive application
rechecks rule revision and each selected row's revision, lock, bank, merchant,
direction and kind under the write lock. A changed/ineligible selected row fails
the whole batch. Unselected changes do not alter the selected set, and newly
appearing matches are not automatically included. Original source text drives
matching after edits; immutable source values/fingerprints remain intact.

Assignments store `classification_source="rule"` and applied rule ID/revision,
with audited changes. Manual edits set manual source, default to a manual lock,
clear current applied-rule attribution, and preserve old attribution in audit
history. The lock survives rule changes and reimport. Explicit unlocking remains
an existing repository operation; category assignment never implicitly unlocks.

## Verification

```powershell
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_classification.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Tests use fictional values in the confirmed Khan structure, a separate invented
test grammar, workspace temporary databases and the existing synthetic Khan
fixture. They cover matching, Unicode/space normalization,
distinct keys, bank/direction scope, missing keys, manual overrides/reimport,
disabled rules, explicit subsets, stale previews, rollback, safe extractor failures,
and atomic migration. No real financial files are opened and no GUI is launched.
