"""Exact decimal and source-input checks; all examples are synthetic."""

import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

from app.models import ImportInfo, ImportRow, minor_to_money, money_to_minor, validate_iso


class MoneyTests(unittest.TestCase):
    def test_exact_signed_hundredths(self) -> None:
        cases = {"0": 0, "-0.00": 0, "0.01": 1, "-1234.56": -123456, "+25.1": 2510}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(money_to_minor(value), expected)
                self.assertEqual(minor_to_money(expected), Decimal(value))
        self.assertEqual(money_to_minor(12), 1200)
        self.assertEqual(money_to_minor(Decimal("1.23")), 123)

    def test_excess_precision_is_rejected_instead_of_rounded(self) -> None:
        for value in ("1.001", "1.230", "0.000", Decimal("-2.999")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "two decimal places"):
                money_to_minor(value)

    def test_rejects_floats_nonfinite_ambiguous_and_invalid_values(self) -> None:
        for value in (0.1, True, None, "1,234.56", "1.234,56", "", "1e3", "NaN", Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money_to_minor(value)

    def test_sqlite_integer_boundaries_and_overflow(self) -> None:
        self.assertEqual(money_to_minor("92233720368547758.07"), 2**63 - 1)
        self.assertEqual(money_to_minor("-92233720368547758.08"), -(2**63))
        for value in ("92233720368547758.08", "-92233720368547758.09", Decimal("1E99999")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money_to_minor(value)
        for value in (2**63, -(2**63) - 1, True, 0.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                minor_to_money(value)

    def test_low_decimal_context_does_not_round_money(self) -> None:
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(money_to_minor(Decimal("123456789.12")), 12345678912)
            self.assertEqual(minor_to_money(12345678912), Decimal("123456789.12"))


class SourceModelTests(unittest.TestCase):
    def row(self, **changes) -> ImportRow:
        return ImportRow(**{
            "description": "Synthetic merchant", "bank_datetime": "2026/10/18 09:05:00",
            "occurred_at": "2026-10-18T09:05:00", "amount_minor": -101,
            "worksheet": "Synthetic", "row_number": 2, **changes,
        })

    def test_iso_dates_and_datetimes(self) -> None:
        for value in ("2024-02-29", "2026-10-18T09:05:00", "2026-10-18T09:05:00.123456+08:00", "2026-10-18T01:05:00Z"):
            self.assertEqual(validate_iso(value), value)

    def test_ambiguous_invalid_and_incomplete_dates_are_rejected(self) -> None:
        for value in ("18/10/2026", "10/11/2026", "20261018", "2026-02-29", "2026-10-18 09:00:00", "2026-10-18T09:05", "2026-10-18T25:00:00", "2026-10-18T09:05:00+01:99", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_iso(value)

    def test_source_input_is_frozen_and_optional_values_remain_null(self) -> None:
        row = self.row()
        self.assertIsNone(row.reference)
        self.assertIsNone(row.balance_minor)
        self.assertIsNone(row.dedup_key)
        with self.assertRaises(FrozenInstanceError):
            row.description = "changed"

    def test_source_row_validates_types_provenance_and_currency(self) -> None:
        for changes in ({"amount_minor": 1.2}, {"amount_minor": True}, {"balance_minor": 0.5},
                        {"row_number": 0}, {"row_number": "2"}, {"worksheet": ""},
                        {"currency": "mnt"}, {"description": None}, {"bank_datetime": ""},
                        {"reference": 123}, {"dedup_key": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.row(**changes)

    def test_import_metadata_validation(self) -> None:
        valid = {"account_id": 1, "sha256": "a" * 64, "parser_version": "synthetic-v1", "filename": "synthetic.xlsx"}
        self.assertEqual(ImportInfo(**valid).filename, "synthetic.xlsx")
        for changes in ({"account_id": True}, {"sha256": "g" * 64}, {"sha256": "a" * 63},
                        {"parser_version": ""}, {"filename": "C:\\private\\file.xlsx"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ImportInfo(**{**valid, **changes})


if __name__ == "__main__":
    unittest.main()
