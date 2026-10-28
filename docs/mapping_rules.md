# Classification Mapping Table

The Mapping Table classifies eligible transactions with deterministic,
user-editable rules. It runs locally inside the existing import worker; it does
not call AI or a network service. The page is **Ангиллын зураглал** in Mongolian
and **Mapping Table** in English.

## Rule fields

Each rule stores a name, priority, active state, bank/account scope, direction,
source field, operator, value, target kind/category, and created/updated times.
Rules are evaluated by descending priority, then ascending rule ID for a stable
tie. The first matching, eligible rule wins.

| Field | Values / behavior |
| --- | --- |
| Bank | Any bank or one exact bank identity |
| Account | Any account or one stored account |
| Direction | Any, debit, or credit; target kind still enforces a compatible sign |
| Source field | POS ID, normalized merchant, or original description |
| Operator | Exact, contains, starts with, ends with, or regular expression |
| Target | Income/expense with a compatible category, or transfer/excluded without one |
| Active | Disabled rules are ignored |

Merchant and description matching uses NFC Unicode normalization, casefolding,
trimmed/collapsed whitespace. Punctuation and digits are preserved. POS IDs use
NFC and trimming, without changing case. All comparisons are local and
deterministic. `contains` is a substring operation; regex is a case-insensitive
Python regular-expression search. Regex syntax is validated before saving.

The Khan Bank parser currently has no verified POS ID field or pattern. Its
`pos_id` is therefore NULL. Do not infer a value from the authorization prefix,
branch, or other description text. Add a new bank parser only after its format
has a real synthetic specification or approved sample and separately verified
field semantics.

## Fictional examples

The following values are invented and are not production merchant or POS data.

| Rule name | Scope | Direction | Field/operator/value | Target |
| --- | --- | --- | --- | --- |
| Fictional cafe POS | Fictional Bank A / Demo checking | Debit | POS ID / exact / `SYN-POS-81` | Expense / Cafeteria, Coffee & Snacks |
| Fictional book shop | Fictional Bank A / any account | Debit | Merchant / exact / `nomiin delguur` | Expense / Textbooks, Printing & School Supplies |
| Fictional transport description | Any bank / any account | Debit | Description / starts with / `SYNTH TRIP` | Expense / Public Transport / Commuting |
| Fictional support credit | Any bank / any account | Credit | Description / regex / `^SYNTH SUPPORT [0-9]+$` | Income / Allowance / Family support |

Example: an invented normalized merchant `Fictional Cafe 2` remains distinct
from `Fictional Cafe 3`; digits are not deleted. Unicode strings with composed
or decomposed accents compare consistently after NFC normalization.

## Safe workflow

1. Create a rule using the smallest correct scope and an appropriately high or
   low priority. A global rule can affect more accounts than a bank/account rule.
2. Enter a synthetic test sample and choose **Test rule**. This checks whether
   the sample matches and reports broad `Contains` patterns. A one-character
   `Contains`, including `T`, receives a specific warning. Empty values and
   invalid regular expressions are rejected.
3. Save the rule. Saving, editing, enabling, disabling, or deleting it does not
   silently change already classified transactions.
4. To apply a saved rule to existing rows, select the rule and choose **Preview
   matching transactions**. The preview contains only currently eligible rows
   for which the rule is the current winning rule.
5. Select only the rows to change in the preview and choose **Apply to selected**.
   No rows are preselected; empty selection is rejected. Cancel leaves all rows
   unchanged. The app rechecks the rule and each transaction revision before
   applying atomically.

Manual assignments and protected rows are never overwritten. Unclassified,
locked, direction-incompatible, or currency-inconsistent records are excluded.
The mapping operation changes only classification fields and appends audit
history; original bank source fields, signed money, currency, and deduplication
identity remain unchanged. A manual correction to merchant display does not
change the stored matching key or rewrite rules.

## Append imports and account filters

Imports append newly accepted rows. Exact duplicates are skipped, ambiguous
overlaps require explicit Keep/Skip choices, and prior transactions are not
replaced. Multiple bank/account identities are stored on accounts and visible
in the transaction browser; bank and account filters can be combined. The
currently implemented statement parser remains Khan Bank MNT only. Adding an
account identity does not imply that an unverified bank statement format can be
imported.

## Developer notes

- UI strings belong in `app/ui/i18n.py`; keep stored category identifiers,
  bank/account names, currencies, and transaction kinds untranslated.
- Mapping logic belongs in `app/mapping_service.py`; widgets do not duplicate
  SQL, parser logic, or matching rules.
- Add tests with invented bank names, merchants, POS IDs, amounts, and
  descriptions. Cover priority ties, scopes, operators, disabled rules,
  protection, preview/apply, and migration.
- Run focused mapping/import/database tests, then the full suite. Do not open
  private statements to construct fixtures.
