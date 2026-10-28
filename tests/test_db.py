"""Repository acceptance tests using disposable workspace databases only."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.db import Repository
from app.models import ImportInfo, ImportRow


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="finance-test-", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.sqlite3"
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.close)
        self.account = self.repo.create_account("000123", "Synthetic account")
        self.income = next(c["id"] for c in self.repo.list_categories() if c["name"] == "Other income")
        self.expense = next(c["id"] for c in self.repo.list_categories() if c["name"] == "Other expenses")

    def row(self, **changes) -> ImportRow:
        return ImportRow(**{
            "description": "  Synthetic café — жишээ  ", "bank_datetime": "2026/10/18 09:05:00",
            "occurred_at": "2026-10-18T09:05:00", "amount_minor": -125050,
            "worksheet": "Synthetic sheet", "row_number": 7, **changes,
        })

    def info(self, **changes) -> ImportInfo:
        return ImportInfo(**{
            "account_id": self.account, "sha256": "a" * 64,
            "parser_version": "synthetic-v1", "filename": "synthetic.xlsx", **changes,
        })

    def insert(self, **changes) -> int:
        import_id = self.repo.write_import(self.info(), [self.row(**changes)])
        return self.repo.query_transactions(import_id=import_id)[0]["id"]

    def test_repeated_initialization_seeds_exact_categories_once(self) -> None:
        expected = [
            ("Earned income (part-time job, freelancing, internship)", "income"),
            ("Allowance / Family support", "income"), ("Scholarships / Grants", "income"),
            ("Gifts / Donations", "income"), ("Other income", "income"),
            ("Tuition & Academic Fees", "expense"), ("Textbooks, Printing & School Supplies", "expense"),
            ("Cafeteria, Coffee & Snacks", "expense"), ("Dormitory / Rent & Utilities", "expense"),
            ("Public Transport / Commuting", "expense"), ("Social & Entertainment", "expense"),
            ("Software & Digital Subscriptions", "expense"), ("Other expenses", "expense"),
        ]
        before = self.repo.list_categories()
        for _ in range(3):
            self.repo.initialize()
        with Repository(self.path) as reopened:
            self.assertEqual(reopened.list_categories(), before)
            self.assertEqual([(c["name"], c["direction"]) for c in before], expected)
            self.assertEqual(reopened._connection.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)

    def test_source_metadata_counts_and_unknown_state_are_preserved(self) -> None:
        source = self.row(reference="000456", balance_minor=998877, dedup_key="opaque-synthetic-key")
        import_id = self.repo.write_import(self.info(sha256="B" * 64), [source], skipped_count=2, rejected_count=1)
        metadata = self.repo.get_import(import_id)
        self.assertEqual(metadata["account_id"], self.account)
        self.assertEqual(metadata["sha256"], "b" * 64)
        self.assertEqual(metadata["parser_version"], "synthetic-v1")
        self.assertEqual(metadata["filename"], "synthetic.xlsx")
        self.assertTrue(metadata["imported_at"].endswith("+00:00"))
        self.assertEqual([metadata[k] for k in ("total_count", "imported_count", "skipped_count", "rejected_count")], [4, 1, 2, 1])
        stored = self.repo.query_transactions(import_id=import_id)[0]
        for name in ("description", "occurred_at", "amount_minor", "currency", "reference", "balance_minor"):
            self.assertEqual(stored["original_" + name], getattr(source, name))
            self.assertEqual(stored[name], getattr(source, name))
        for name in ("bank_datetime", "worksheet", "row_number", "dedup_key"):
            self.assertEqual(stored[name], getattr(source, name))
        self.assertEqual(stored["kind"], "unclassified")
        self.assertEqual(stored["classification_source"], "unclassified")
        self.assertIsNone(stored["category_id"])
        self.assertIsNone(stored["merchant_key"])
        self.assertEqual(stored["manual_lock"], 0)
        self.assertEqual(len(self.repo.query_transactions(review_only=True)), 1)

    def test_search_matches_effective_merchant_display_and_key_with_unicode(self) -> None:
        transaction_id = self.insert()
        self.repo.edit_transaction(
            transaction_id, reason="Synthetic merchant correction",
            merchant_display="ӨВӨРМӨЦ ДЭЛГҮҮР", merchant_key="түлхүүр 17",
        )

        self.assertEqual([r["id"] for r in self.repo.query_transactions(search="дэлгүүр")],
                         [transaction_id])
        self.assertEqual([r["id"] for r in self.repo.query_transactions(search="ТҮЛХҮҮР 17")],
                         [transaction_id])

    def test_persistence_after_reopening_includes_account_rules_and_history(self) -> None:
        transaction_id = self.insert()
        self.repo.assign_category(transaction_id, self.expense, reason="Synthetic manual review")
        self.repo.edit_transaction(transaction_id, reason="Synthetic annotation", note="Reviewed", merchant_key="synthetic")
        self.repo.upsert_rule("synthetic", "debit", "expense", self.expense)
        expected = self.repo.get_transaction(transaction_id)
        self.repo.close()
        with Repository(self.path) as reopened:
            self.assertEqual(reopened.list_accounts()[0]["identifier"], "000123")
            self.assertEqual(reopened.get_transaction(transaction_id), expected)
            self.assertEqual(len(reopened.get_history(transaction_id)), 2)
            self.assertEqual(reopened.list_rules()[0]["merchant_key"], "synthetic")
            self.assertEqual(reopened._connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_failed_import_rolls_back_metadata_and_earlier_rows(self) -> None:
        self.insert()
        before = self.repo.query_transactions()
        before_imports = self.repo._connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "currency"):
            self.repo.write_import(self.info(), [self.row(), self.row(currency="USD")])
        self.assertEqual(self.repo.query_transactions(), before)
        self.assertEqual(self.repo._connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0], before_imports)
        # The rolled-back connection remains usable.
        self.insert(row_number=8)
        with Repository(self.path) as reopened:
            self.assertEqual(len(reopened.query_transactions()), 2)

    def test_invalid_row_type_rolls_back_import(self) -> None:
        with self.assertRaisesRegex(ValueError, "ImportRow"):
            self.repo.write_import(self.info(), [self.row(), object()])
        self.assertEqual(self.repo.query_transactions(), [])
        self.assertEqual(self.repo._connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0], 0)

    def test_foreign_keys_are_enabled_and_enforced(self) -> None:
        self.assertEqual(self.repo._connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            self.repo.write_import(self.info(account_id=99999), [])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            self.repo._connection.execute(
                "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                (99999, "2026-10-18T00:00:00Z", "synthetic", "{}"),
            )
        self.insert()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            self.repo._connection.execute("DELETE FROM accounts WHERE id = ?", (self.account,))

    def test_manual_edits_audit_deltas_and_preserve_originals(self) -> None:
        transaction_id = self.insert(reference="001", balance_minor=500000, dedup_key="synthetic-identity")
        original = self.repo.get_transaction(transaction_id)
        changed = self.repo.edit_transaction(
            transaction_id, reason="Synthetic correction", description="Corrected", amount_minor=-999,
            occurred_at="2026-10-19", reference=None, balance_minor=None, merchant_key="synthetic",
            note="A note", kind="expense", category_id=self.expense,
        )
        for key in db._SOURCE_COLUMNS:
            self.assertEqual(changed[key], original[key], key)
        self.assertEqual(changed["amount_minor"], -999)
        self.assertEqual(changed["manual_lock"], 1)
        self.assertEqual(changed["classification_source"], "manual")
        history = self.repo.get_history(transaction_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["reason"], "Synthetic correction")
        self.assertEqual(history[0]["changes"]["amount_minor"], {"old": -125050, "new": -999})
        self.assertNotIn("original_description", history[0]["changes"])
        self.assertNotIn("currency", history[0]["changes"])
        self.repo.edit_transaction(transaction_id, reason="Same value", note="A note")
        self.assertEqual(len(self.repo.get_history(transaction_id)), 1)

    def test_audit_failure_rolls_back_effective_edit(self) -> None:
        transaction_id = self.insert()
        original = self.repo.get_transaction(transaction_id)
        self.repo._connection.execute("""CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON transaction_edits
            BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic audit failure"):
            self.repo.edit_transaction(transaction_id, reason="Synthetic edit", note="must roll back")
        self.assertEqual(self.repo.get_transaction(transaction_id), original)
        self.assertEqual(self.repo.get_history(transaction_id), [])

    def test_incompatible_edits_leave_transaction_and_history_unchanged(self) -> None:
        transaction_id = self.insert()
        original = self.repo.get_transaction(transaction_id)
        incompatible = (
            {"kind": "income", "category_id": self.income},
            {"kind": "expense", "category_id": self.income},
            {"kind": "transfer", "category_id": self.expense},
            {"kind": "excluded", "category_id": self.expense},
            {"kind": "unclassified", "category_id": self.expense},
            {"kind": "expense", "amount_minor": 0},
            {"kind": "income", "amount_minor": 0},
            {"category_id": 99999}, {"currency": "USD"}, {"amount_minor": 0.1},
            {"occurred_at": "10/11/2026"}, {"original_description": "forbidden"},
            {"dedup_key": "forbidden"}, {"manual_lock": 1},
        )
        for changes in incompatible:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.repo.edit_transaction(transaction_id, reason="Synthetic incompatible edit", **changes)
            self.assertEqual(self.repo.get_transaction(transaction_id), original)
            self.assertEqual(self.repo.get_history(transaction_id), [])

    def test_category_assignment_checks_sign_and_can_reset_review_state(self) -> None:
        transaction_id = self.insert(amount_minor=123)
        with self.assertRaisesRegex(ValueError, "positive.*negative"):
            self.repo.assign_category(transaction_id, self.expense, reason="Wrong direction")
        assigned = self.repo.assign_category(transaction_id, self.income, reason="Explicit income")
        self.assertEqual(assigned["kind"], "income")
        self.assertEqual(self.repo.query_transactions(review_only=True), [])
        reset = self.repo.assign_category(transaction_id, None, reason="Needs review")
        self.assertIsNone(reset["category_id"])
        self.assertEqual(reset["kind"], "unclassified")
        self.assertEqual(len(self.repo.query_transactions(review_only=True)), 1)

    def test_transfer_and_excluded_are_explicit_and_uncategorized(self) -> None:
        for amount in (-100, 100, 0):
            for kind in ("transfer", "excluded"):
                with self.subTest(amount=amount, kind=kind):
                    transaction_id = self.insert(amount_minor=amount)
                    self.assertEqual(self.repo.get_transaction(transaction_id)["kind"], "unclassified")
                    result = self.repo.edit_transaction(transaction_id, reason="Explicit choice", kind=kind)
                    self.assertIsNone(result["category_id"])
        self.assertEqual(self.repo.query_transactions(review_only=True), [])

    def test_edit_can_change_direction_only_with_compatible_kind_and_category(self) -> None:
        transaction_id = self.insert()
        self.repo.assign_category(transaction_id, self.expense, reason="Initial expense")
        with self.assertRaisesRegex(ValueError, "positive.*negative"):
            self.repo.edit_transaction(transaction_id, reason="Wrong sign", amount_minor=50)
        updated = self.repo.edit_transaction(transaction_id, reason="Correct direction", amount_minor=50,
                                             kind="income", category_id=self.income, manual_lock=False)
        self.assertEqual(updated["original_amount_minor"], -125050)
        self.assertEqual(updated["amount_minor"], 50)
        self.assertEqual(updated["manual_lock"], 0)

    def test_database_protects_source_identity_imports_and_history(self) -> None:
        transaction_id = self.insert(dedup_key="synthetic-key")
        original = self.repo.get_transaction(transaction_id)
        for name, value in {"original_description": "changed", "original_occurred_at": "2026-01-01",
                            "original_amount_minor": 1, "original_currency": "USD", "original_reference": "changed",
                            "original_balance_minor": 1, "bank_datetime": "changed", "worksheet": "changed",
                            "row_number": 8, "source_id": "changed", "dedup_key": "changed", "id": 999,
                            "import_id": 999}.items():
            with self.subTest(name=name), self.assertRaises(sqlite3.IntegrityError):
                self.repo._connection.execute(f"UPDATE transactions SET {name} = ? WHERE id = ?", (value, transaction_id))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.repo._connection.execute("UPDATE imports SET filename = ? WHERE id = ?", ("changed.xlsx", original["import_id"]))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Exclude"):
            self.repo._connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        self.repo.assign_category(transaction_id, self.expense, reason="Synthetic assignment")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo._connection.execute("DELETE FROM transaction_edits WHERE transaction_id = ?", (transaction_id,))

    def test_database_enforces_category_direction_and_prevents_direction_changes(self) -> None:
        transaction_id = self.insert()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Category direction"):
            self.repo._connection.execute("UPDATE transactions SET kind = ?, category_id = ? WHERE id = ?", ("expense", self.income, transaction_id))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.repo._connection.execute("UPDATE categories SET direction = ? WHERE id = ?", ("expense", self.income))

    def test_duplicate_dates_amounts_and_hashes_are_not_prematurely_deduplicated(self) -> None:
        first, second = self.insert(), self.insert()
        self.assertNotEqual(self.repo.get_transaction(first)["source_id"], self.repo.get_transaction(second)["source_id"])
        self.assertEqual([row["id"] for row in self.repo.query_transactions()], [second, first])

    def test_missing_optional_bank_values_persist_as_null(self) -> None:
        transaction_id = self.insert()
        with Repository(self.path) as reopened:
            stored = reopened.get_transaction(transaction_id)
            for name in ("original_reference", "reference", "original_balance_minor", "balance_minor", "dedup_key"):
                self.assertIsNone(stored[name])

    def test_default_repository_uses_configured_data_directory(self) -> None:
        directory = self.path.parent / "configured-data"
        with patch("app.db.get_data_dir", return_value=directory):
            with Repository() as configured:
                self.assertEqual(len(configured.list_categories()), 13)
        self.assertTrue((directory / "finance.sqlite3").is_file())

    def test_filtered_queries_and_pagination_use_effective_values(self) -> None:
        early = self.insert(occurred_at="2026-10-17")
        middle = self.insert(occurred_at="2026-10-18")
        late = self.insert(occurred_at="2026-10-18T23:59:59")
        self.repo.assign_category(middle, self.expense, reason="Synthetic category")
        self.assertEqual([t["id"] for t in self.repo.query_transactions(limit=1, offset=1)], [middle])
        self.assertEqual([t["id"] for t in self.repo.query_transactions(date_from="2026-10-18", date_to="2026-10-18")], [late, middle])
        self.assertEqual([t["id"] for t in self.repo.query_transactions(kind="expense", category_id=self.expense)], [middle])
        self.assertEqual({t["id"] for t in self.repo.query_transactions(review_only=True)}, {early, late})
        second_account = self.repo.create_account("000124", "Second synthetic account")
        imported = self.repo.write_import(self.info(account_id=second_account), [self.row()])
        self.assertEqual(len(self.repo.query_transactions(account_id=second_account, import_id=imported)), 1)
        self.repo.edit_transaction(early, reason="Synthetic date correction", occurred_at="2026-10-20")
        self.assertEqual(self.repo.query_transactions(limit=1)[0]["id"], early)
        for filters in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"date_from": "18/10/2026"},
                        {"date_from": "2026-10-20", "date_to": "2026-10-18"}, {"kind": "bad"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.repo.query_transactions(**filters)

    def test_rules_crud_and_incompatible_rule_rejection(self) -> None:
        rule = self.repo.upsert_rule("synthetic", "debit", "expense", self.expense)
        self.assertEqual(len(self.repo.list_rules()), 1)
        self.assertEqual(self.repo.upsert_rule("synthetic", "debit", "transfer"), rule)
        self.assertEqual(self.repo.list_rules()[0]["kind"], "transfer")
        self.assertIsNone(self.repo.list_rules()[0]["category_id"])
        for direction, kind, category in (("debit", "income", self.income), ("credit", "expense", self.expense),
                                          ("debit", "expense", self.income), ("credit", "income", None),
                                          ("zero", "transfer", self.expense)):
            with self.subTest(direction=direction, kind=kind), self.assertRaises(ValueError):
                self.repo.upsert_rule("synthetic", direction, kind, category)
        self.assertEqual(len(self.repo.list_rules()), 1)
        self.repo.delete_rule(rule)
        self.assertEqual(self.repo.list_rules(), [])

    def test_parameterized_sql_preserves_quotes_and_sql_like_text(self) -> None:
        payload = "Synthetic '); DROP TABLE accounts; --"
        identifier = self.insert(description=payload)
        self.repo.upsert_rule(payload, "debit", "expense", self.expense)
        self.repo.edit_transaction(identifier, reason=payload, note=payload)
        self.assertEqual(self.repo.get_transaction(identifier)["original_description"], payload)
        self.assertEqual(self.repo.list_rules()[0]["merchant_key"], payload.casefold())
        self.assertEqual(self.repo.list_accounts()[0]["identifier"], "000123")

    def test_account_identifier_must_be_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "Account identifier"):
            self.repo.create_account(123, "Synthetic account")

    def test_initialization_failure_rolls_back_schema_and_version(self) -> None:
        other = self.path.parent / "failed.sqlite3"
        with patch.object(db, "_SCHEMA", db._SCHEMA + ("INVALID SYNTHETIC SQL",)):
            with self.assertRaises(sqlite3.OperationalError):
                Repository(other)
        connection = sqlite3.connect(other)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall(), [])
        finally:
            connection.close()
        with Repository(other) as recovered:
            self.assertEqual(len(recovered.list_categories()), 13)

    def test_unknown_schema_version_is_rejected_without_overwriting(self) -> None:
        other = self.path.parent / "future.sqlite3"
        connection = sqlite3.connect(other)
        connection.execute("PRAGMA user_version = 99")
        connection.close()
        with self.assertRaisesRegex(ValueError, "schema version 99"):
            Repository(other)
        connection = sqlite3.connect(other)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
