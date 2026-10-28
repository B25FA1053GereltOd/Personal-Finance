# Dashboard

`ReportingService.summarize` reads effective transaction fields in one database
query on the existing worker thread. Stored amounts and service aggregates use
exact integer hundredths; the primary cards use Decimal for revenue, cost and
net arithmetic, and percentages use Decimal. No floating-point money is used.
The cards show Total Revenue (classified income), Total Cost (the positive
magnitude of classified expenses), Net (Revenue minus Cost), and Unclassified.
Transfers and unclassified rows are excluded from Revenue, Cost and Net.
Currencies remain separate. Net is not a bank balance.
Unclassified counts are visible; transfer/excluded amounts are omitted. Each
currency has independent totals, category percentages and monthly summaries.
The existing storage model represents amounts in hundredths; this does not add
parsing support for banks or currencies beyond the existing Khan MNT parser.

Presets use the computer's current calendar date. Custom ranges require both
ISO dates. Bounds include the stored effective bank-local calendar date, without
UTC conversion. Categories sort by descending amount within each currency/kind;
months sort chronologically. Category drill-down carries category, currency and
selected date bounds. Monthly drill-down intersects the month and selected range,
and includes all matching rows, including unclassified/transfer/excluded rows.

Import commits, transaction edits, classification confirmations and explicit rule
applications invalidate the Dashboard and queue a fresh report after the existing
refresh chain. Widgets are updated only on the Tk main thread. Errors clear stale
report contents and remain visible; Apply / refresh permits recovery. No new
schema or chart dependency is required.

## Exact synthetic manual GUI checklist

User-confirmed smoke checks (2026-10-20): start.bat launched successfully using
the isolated synthetic directory; Dashboard opened; all-time MNT/USD totals,
transaction/unclassified counts and both category breakdowns/percentages matched.
The remaining extended checks below are **optional/pending, NOT RUN**, not failures:
monthly tables, date presets/validation, drill-down, mutation refresh, restart,
backup UI and manual restore. The user stopped the step-by-step checklist.
Agent GUI checks remain NOT RUN; automated service, worker and headless controller
checks are not visual verification. All values below are invented.
Run in the VS Code PowerShell terminal; keep this terminal open for restart:

```powershell
Set-Location 'C:\Personal Finance'
$previousFinanceData = $env:PERSONAL_FINANCE_DATA_DIR
$env:TEMP = Join-Path (Get-Location).Path 'data\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:PERSONAL_FINANCE_DATA_DIR = Join-Path (Get-Location).Path ('data\gui-step8-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -c "import os; from tests.dashboard_fixture import create_dashboard_database; create_dashboard_database(os.environ['PERSONAL_FINANCE_DATA_DIR'])"
.\.venv\Scripts\python.exe -c "from tests.review_fixtures import create_review_fixtures; create_review_fixtures('data/review-fixtures')"
$syntheticBackupFolder = Join-Path $env:PERSONAL_FINANCE_DATA_DIR 'backups'
New-Item -ItemType Directory -Path $syntheticBackupFolder -Force | Out-Null
$syntheticBackupFolder
.\start.bat
```

1. Open Dashboard, All time, Apply / refresh Dashboard. Expect prominent cards
   Total Revenue: `1,200.00 MNT · 10.00 USD`; Total Cost:
   `150.00 MNT · 2.50 USD`; Net: `1,050.00 MNT · 7.50 USD`; Unclassified: `1`.
   The totals table shows 10 transactions, MNT transfers/excluded 2 and USD
   unclassified 0. Keep currencies separate.
2. Expenses by category: MNT Other expenses 130.10, count 2, 86.73%; Software &
   Digital Subscriptions 19.90, count 1, 13.27%. USD Other expenses 2.50, count 1,
   100%. Income: MNT Other income 1,200.00/count 2; USD Other income 10.00/count 1.
3. Monthly cash flow: September 2026 MNT 1,000.00/100.00/900.00; October 2026
   MNT 200.00/50.00/150.00 and USD 10.00/2.50/7.50 (income/expenses/net).
4. Custom range 2026-10-01 through 2026-10-31: expect 8 rows, MNT 200/50/150,
   USD 10/2.50/7.50. MNT category shares: Other expenses 60.20%, Software 39.80%.
   Set both dates to 2026-10-31: the late-night row is included, expense 19.90 MNT.
5. Test This month, Last month and This year, pressing Apply each time. On a
   computer dated October 2026 these select October, September, and all 2026
   respectively. On another date, expect that computer's actual calendar ranges;
   these fixtures may correctly yield an empty result.
6. Enter 2026-02-30, then reversed bounds. Expect visible validation errors and
   no stale totals or crash. Custom 2000-01-01 through 2000-12-31 gives the useful
   empty state. All time restores the initial report.
7. Custom 2026-10-10 through 2026-10-16: select MNT Other expenses and click
   View selected in Transactions (also test double-click). Expect just the
   30.10 MNT expense, category/currency/date filters populated. Return to Dashboard,
   select October MNT monthly row: expect three rows, including the unknown and
   transfer, with bounds still October 10–16. USD monthly drill-down gives two USD
   rows. Search, date/category/direction filters and editing remain available.
8. Import tab: Add account with name **Synthetic Khan**, bank Khan Bank, fictional
   IBAN **MN00000000000000000000**, MNT. Preview then commit
   `C:\Personal Finance\data\review-fixtures\review-initial.xlsx`.
   Dashboard All time updates automatically: 15 rows, 6 unclassified; money totals
   unchanged because all five new rows are unknown.
9. Review: expand merchant `FABLE Жишээ CAFE* 1`; select only the row beginning
   `A1B2C3`. Choose **Other expenses**, check **Also save a rule for future imports**,
   preview, confirm. This creates the Khan Bank/debit rule
   with normalized key `fable жишээ cafe* 1`. Expect MNT expenses 151.00,
   net 1,049.00, 5 unclassified. No other row is silently categorized.
10. Import `C:\Personal Finance\data\review-fixtures\review-future.xlsx` into
    Synthetic Khan. Expect automatic tagging: 16 rows, MNT expenses 152.00,
    net 1,048.00, 5 unclassified. USD remains unchanged.
11. Rules: select the Khan Bank rule just created (not the Synthetic bank fixture
    rule), preview existing rows, select only the `D4E5F6` row, explicitly apply.
    Expect MNT expenses 153.00/net 1,047.00 and 4 unclassified.
12. Transactions: find the `A1B2C3` row; edit amount to **-2.50**, keep Other
    expenses and manual protection. Save. Expect MNT expenses 154.50/net 1,045.50,
    4 unclassified. Source amount remains -1.00 in the read-only source tab;
    history records the correction. Clear browser filters and use page size 10:
    expect pages of 10 and 6 rows.
13. Click Backup, choose the exact `$syntheticBackupFolder` printed above.
    Expect success only after completion/validation and a new timestamped file.
    Repeat: expect a different filename. Cancel the picker: no backup is made.
14. Close the app. In the SAME terminal run `.\start.bat` without reseeding or
    replacing the environment variable. Expect 16 rows, 4 unclassified, MNT
    1,200.00/154.50/1,045.50 and USD 10.00/2.50/7.50. Two saved rules and the
    protected correction persist. Complete the temporary restore exercise in
    [backup_restore.md](backup_restore.md), then close the app.

Restore the previous data setting after all checks:

```powershell
if ($null -eq $previousFinanceData) {
    Remove-Item Env:PERSONAL_FINANCE_DATA_DIR -ErrorAction SilentlyContinue
} else {
    $env:PERSONAL_FINANCE_DATA_DIR = $previousFinanceData
}
```

Do not remove the synthetic directories automatically; they remain Git-ignored.
