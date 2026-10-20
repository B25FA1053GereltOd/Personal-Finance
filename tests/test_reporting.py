"""Exact synthetic reporting, filtering, currencies, and drill-down boundaries."""

from datetime import date
from decimal import Decimal, localcontext
import unittest

from app.db import Repository
from app.models import ImportInfo, ImportRow, MAX_INTEGER
from app.reporting import ReportingService, ReportingError, date_range, category_filters, month_filters, format_money
from tests.dashboard_fixture import populate
from tests.test_ui import temporary_case


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.database = temporary_case(self) / "report.sqlite3"
        self.repo = Repository(self.database)
        self.addCleanup(self.repo.close)
        self.ids = populate(self.repo)
        self.service = ReportingService(self.repo)

    def test_exact_totals_classification_exclusions_and_currency_separation(self):
        report = self.service.summarize()
        self.assertEqual((report.transaction_count, report.unclassified_count), (10, 1))
        totals = {r["currency"]: r for r in report.totals}
        self.assertEqual((totals["MNT"]["income"], totals["MNT"]["expenses"], totals["MNT"]["net"]), (120000, 15000, 105000))
        self.assertEqual(totals["MNT"]["omitted"], 2)
        self.assertEqual((totals["USD"]["income"], totals["USD"]["expenses"], totals["USD"]["net"]), (1000, 250, 750))

    def test_inclusive_boundaries_categories_counts_and_decimal_percentages(self):
        report = self.service.summarize("Custom range", "2026-10-01", "2026-10-31")
        categories = [r for r in report.categories if r["currency"] == "MNT" and r["kind"] == "expense"]
        self.assertEqual([(r["amount"], r["count"], r["percentage"]) for r in categories],
                         [(3010, 1, Decimal("60.20")), (1990, 1, Decimal("39.80"))])
        self.assertEqual(report.transaction_count, 8)
        last = self.service.summarize("Custom range", "2026-10-31", "2026-10-31")
        self.assertEqual((last.transaction_count, last.totals[0]["expenses"]), (1, 1990))

    def test_months_chronological_and_filtered_month_drill_clips_boundaries(self):
        report = self.service.summarize()
        self.assertEqual([(r["month"], r["currency"], r["net"]) for r in report.months],
                         [("2026-09", "MNT", 90000), ("2026-10", "MNT", 15000), ("2026-10", "USD", 750)])
        report = self.service.summarize("Custom range", "2026-10-10", "2026-10-16")
        for row in report.months:
            filters = month_filters(report, row)
            self.assertEqual((filters["date_from"], filters["date_to"]), ("2026-10-10", "2026-10-16"))
            self.assertEqual(self.repo.count_transactions(**filters), row["count"])

    def test_category_drill_matches_count_amount_and_currency_with_pagination(self):
        report = self.service.summarize()
        for category in report.categories:
            filters = category_filters(report, category)
            self.assertEqual(self.repo.count_transactions(**filters), category["count"])
            rows = [self.repo.query_transactions(**filters, limit=1, offset=i)[0] for i in range(category["count"])]
            self.assertEqual(sum(abs(r["amount_minor"]) for r in rows), category["amount"])
            self.assertTrue(all(r["currency"] == category["currency"] for r in rows))
        with self.assertRaises(ReportingError):
            category_filters(report, {})
        for method in (self.repo.query_transactions, self.repo.count_transactions):
            with self.assertRaises(ValueError):
                method(currency="invalid")

    def test_presets_year_rollover_leap_year_and_invalid_dates(self):
        self.assertEqual(date_range("Last month", today=date(2026, 1, 10)), ("2025-12-01", "2025-12-31"))
        self.assertEqual(date_range("This month", today=date(2024, 2, 15)), ("2024-02-01", "2024-02-29"))
        self.assertEqual(date_range("This year", today=date(2026, 10, 20)), ("2026-01-01", "2026-12-31"))
        for start, end in (("", ""), ("2026-02-29", "2026-03-01"), ("20261001", "2026-10-31"),
                           ("2026-10-02", "2026-10-01"), ("2026-10-01T00:00:00", "2026-10-31")):
            with self.subTest(start=start), self.assertRaises(ReportingError):
                date_range("Custom range", start, end)
        with self.assertRaises(ReportingError):
            date_range("invented preset")

    def test_empty_and_uncategorized_income_stay_reviewable(self):
        empty = self.service.summarize("Custom range", "2000-01-01", "2000-12-31")
        self.assertEqual((empty.transaction_count, empty.totals, empty.months, empty.categories), (0, (), (), ()))
        self.repo.edit_transaction(self.ids[0], kind="income", category_id=None, reason="Synthetic pending review")
        report = self.service.summarize()
        self.assertEqual(report.unclassified_count, 2)
        self.assertEqual(report.totals[0]["income"], 20000)

    def test_edits_effective_dates_and_categories_survive_reopening(self):
        row = self.repo.get_transaction(self.ids[3])
        self.repo.edit_transaction(row["id"], amount_minor=-4010, occurred_at="2026-11-01", reason="Synthetic correction")
        report = self.service.summarize()
        with Repository(self.database) as reopened:
            self.assertEqual(ReportingService(reopened).summarize(), report)
            self.assertEqual(reopened.get_transaction(row["id"])["original_amount_minor"], -3010)
        self.assertEqual(report.months[-1]["expenses"], 4010)

    def test_totals_beyond_sqlite_integer_and_low_decimal_precision_are_exact(self):
        account = self.repo.create_account("SYNTHETIC-LARGE", "Synthetic large")
        income = next(c["id"] for c in self.repo.list_categories() if c["name"] == "Other income")
        imported = self.repo.write_import(ImportInfo(account_id=account, sha256="f"*64, filename="synthetic.xlsx", parser_version="synthetic"),
            [ImportRow(description="Fictional large", bank_datetime="2025-01-01", occurred_at="2025-01-01",
                       amount_minor=MAX_INTEGER, worksheet="Synthetic", row_number=i+1) for i in range(2)])
        self.repo.assign_categories([r["id"] for r in self.repo.query_transactions(import_id=imported)], income, reason="Synthetic category")
        with localcontext() as ctx:
            ctx.prec = 3
            report = self.service.summarize("Custom range", "2025-01-01", "2025-01-01")
            self.assertEqual(report.totals[0]["income"], MAX_INTEGER*2)
            self.assertEqual(report.categories[0]["percentage"], Decimal("100.00"))
            self.assertEqual(format_money(MAX_INTEGER*2, "MNT"), "184,467,440,737,095,516.14 MNT")
