# Observed Khan Bank MNT workbook format

Inspected locally with openpyxl on 2026-10-19. This document contains format
facts only, with no customer values, workbook filename, or transaction samples.

## Verified facts

- The supplied workbook has one worksheet. Its name is not a format identifier.
  The content identifies the layout; the filename is not used for recognition.
- A metadata/title row precedes the eight-column transaction header. In that
  row, A is `Хэвлэсэн огноо:`, B is the print date, C ends with
  ` дансны дэлгэрэнгүй хуулга`, D is `Хэрэглэгч:`, E is customer text,
  F is `Интервал:`, G and I are period dates separated by `-` in H,
  J is `Валют:`, K is `MNT`, and L contains `IBAN: ` followed by the account
  identifier. The IBAN is text beginning with `MN` and continuing with digits.
  The title prefix is not needed to identify the account; the labeled IBAN is
  the verified account location.
- The exact header cells, in order, are:

| Column | Observed header | Meaning |
| --- | --- | --- |
| A | Гүйлгээний огноо | Bank transaction date and time |
| B | Салбар | Branch code, stored as digit text |
| C | Эхний үлдэгдэл | Balance immediately before the row |
| D | Кредит гүйлгээ | Credit, positive when active |
| E | Дебит гүйлгээ | Debit, already negative when active |
| F | Эцсийн үлдэгдэл | Balance immediately after the row |
| G | Гүйлгээний утга | Original transaction description |
| H | Харьцсан данс | Optional counterparty account, not a bank reference |

- Transaction dates are text in `YYYY-MM-DD HH:MM:SS` form, including seconds.
  No timezone appears. Period dates use `YYYY/MM/DD`. The print date uses
  `MM/DD/YYYY`; the observed components disambiguate its month/day order.
- Transaction rows follow the header, in nondecreasing date/time order.
  There are blank rows. There are no populated transaction cells beyond H.
  Descriptions are nonempty Unicode text. The optional counterparty account is
  text or genuinely blank. No dedicated bank reference column is present.
- Columns C–F contain numeric Excel values representable exactly in hundredths.
  The inactive credit/debit cell is numeric zero, not blank. Exactly one of D/E
  is nonzero on each transaction. Signed amount is D + E; debits must not be
  negated again. Each F equals C + D + E, and successive balances reconcile.
- The final nonblank row is labeled `Нийт дүн:` in A. Only D and E contain
  totals; other cells are blank. These totals are text using comma thousands
  separators and a decimal point with two fractional digits.
- Total D equals the sum of positive credits. Total E is the **positive
  magnitude** of the negative debit sum. First opening balance + total credits
  − total debit magnitude equals the last closing balance. These conventions
  and reconciliation identities were checked locally without recording values.
- No merged ranges, formula cells, or repeated headers were present in the
  supplied workbook. The exact numeric OOXML values also satisfy the model's
  precision requirements.

## Unresolved or unobserved formats

- No `POS` or `ПОС` marker was found in descriptions. A POS-specific pattern or
  merchant separator is **not verified**; descriptions must remain intact.
- Other worksheet layouts, column orders, currencies, title/metadata layouts,
  date conventions, reference fields, subtotal/footer labels, and debit sign
  conventions have not been verified.
- Merged-cell layouts and formulas are not demonstrated by this sample.
  Required formula fields cannot be interpreted without usable cached values.
  Missing caches provide no evidence for computing or guessing a result.
- Repeated headers were not observed. Only an exact repetition of the verified
  eight-column header is recognizable without inventing new row semantics.
