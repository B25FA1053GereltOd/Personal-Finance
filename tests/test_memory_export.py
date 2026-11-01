"""Synthetic tests for CSV export and local AI-assisted classification memory."""

import csv
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.classification import ClassificationService
from app.db import Repository
from app.export_service import (
    TRANSACTION_FIELDS_EN,
    TRANSACTION_FIELDS_MN,
    ExportError,
    export_csv,
)
from app.memory_service import MemoryService
from app.models import ImportInfo, ImportRow
from app.review_service import ReviewService


class SyntheticMemoryExportBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="fin-mem-exp-",
            dir=Path(__file__).resolve().parents[1] / "data" / "test-temp",
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.repo = Repository(self.db_path)
        self.addCleanup(self.repo.close)

        # Accounts
        self.khan_mnt = self.repo.create_account("MN01KHAN001", "Khan MNT", bank="Khan Bank", currency="MNT")
        self.khan_usd = self.repo.create_account("MN01KHAN002", "Khan USD", bank="Khan Bank", currency="USD")
        self.golomt_mnt = self.repo.create_account("MN02GOLOMT01", "Golomt MNT", bank="Golomt Bank", currency="MNT")

        # Categories
        self.categories = self.repo.list_categories()
        self.coffee_cat = next(c["id"] for c in self.categories if c["name"] == "Cafeteria, Coffee & Snacks")
        self.food_cat = self.coffee_cat
        self.transport_cat = next(c["id"] for c in self.categories if c["name"] == "Public Transport / Commuting")
        self.salary_cat = next(c["id"] for c in self.categories if c["name"] == "Earned income (part-time job, freelancing, internship)")
        self.other_cat = next(c["id"] for c in self.categories if c["name"] == "Other expenses")

        self.memory_service = MemoryService(self.repo)
        self.classification = ClassificationService(self.repo)
        self.review_service = ReviewService(self.repo)

    def _insert_rows(self, account_id, rows, sha=None):
        import hashlib, uuid
        sha_val = sha or hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        info = ImportInfo(
            account_id=account_id,
            filename=f"synthetic-{uuid.uuid4().hex[:6]}.xlsx",
            sha256=sha_val,
            parser_version="khan-mnt-1",
        )
        return self.repo.write_import(info, rows, classify=self.classification.classify_import)


class CSVExportTests(SyntheticMemoryExportBase):
    def test_csv_headers_en_and_mn_with_bom(self):
        rows = [
            ImportRow(
                description="CAFE SHOP 1", bank_datetime="2026-10-15 12:30:00",
                occurred_at="2026-10-15T12:30:00", amount_minor=-1500000,
                worksheet="Sheet1", row_number=1, dedup_key="tx-1",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows)
        tx_id = self.repo.query_transactions()[0]["id"]
        self.classification.assign_category([tx_id], self.coffee_cat)

        target_mn = Path(self.temp_dir.name) / "export_mn.csv"
        target_en = Path(self.temp_dir.name) / "export_en.csv"

        # 1. Mongolian export
        res_mn = export_csv(self.repo, target_mn, {}, language="mn", format="transactions")
        self.assertEqual(res_mn.count, 1)

        raw_bytes_mn = target_mn.read_bytes()
        self.assertTrue(raw_bytes_mn.startswith(b"\xef\xbb\xbf"), "Export must start with UTF-8 BOM")

        with target_mn.open(encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            self.assertEqual(tuple(reader[0]), TRANSACTION_FIELDS_MN)
            self.assertEqual(len(reader[1]), len(TRANSACTION_FIELDS_MN))
            self.assertEqual(reader[1][0], "2026-10-15T12:30:00")
            self.assertEqual(reader[1][1], "-15000.00")
            self.assertEqual(reader[1][2], "CAFE SHOP 1")
            self.assertEqual(reader[1][3], "Кофе, амттан")
            self.assertEqual(reader[1][4], "MNT")
            self.assertEqual(reader[1][5], "Khan Bank")
            self.assertEqual(reader[1][6], "Khan MNT")
            self.assertEqual(reader[1][7], "Зарлага")

        # 2. English export
        res_en = export_csv(self.repo, target_en, {}, language="en", format="transactions")
        self.assertEqual(res_en.count, 1)

        raw_bytes_en = target_en.read_bytes()
        self.assertTrue(raw_bytes_en.startswith(b"\xef\xbb\xbf"), "Export must start with UTF-8 BOM")

        with target_en.open(encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            self.assertEqual(tuple(reader[0]), TRANSACTION_FIELDS_EN)
            self.assertEqual(len(reader[1]), len(TRANSACTION_FIELDS_EN))
            self.assertEqual(reader[1][7], "debit")

    def test_exact_amounts_and_currencies_preserved(self):
        rows = [
            ImportRow(
                description="SALARY", bank_datetime="2026-10-01 10:00:00",
                occurred_at="2026-10-01T10:00:00", amount_minor=350000000,
                worksheet="Sheet1", row_number=1, dedup_key="tx-sal",
            ),
            ImportRow(
                description="USD EXPENSE", bank_datetime="2026-10-02 11:00:00",
                occurred_at="2026-10-02T11:00:00", amount_minor=-12550, currency="USD",
                worksheet="Sheet1", row_number=2, dedup_key="tx-usd",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows[:1])
        self._insert_rows(self.khan_usd, rows[1:])

        target = Path(self.temp_dir.name) / "exact.csv"
        export_csv(self.repo, target, {}, format="transactions")

        with target.open(encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            row_map = {r[2]: (r[1], r[4]) for r in reader[1:]}
            self.assertEqual(row_map["SALARY"], ("3500000.00", "MNT"))
            self.assertEqual(row_map["USD EXPENSE"], ("-125.50", "USD"))

    def test_filter_aware_export_across_all_pages(self):
        # Insert 520 transactions to cross 500-item page boundary
        batch = [
            ImportRow(
                description=f"ITEM {i}", bank_datetime="2026-10-10 12:00:00",
                occurred_at="2026-10-10T12:00:00", amount_minor=-100000,
                worksheet="Sheet1", row_number=i, dedup_key=f"large-tx-{i}",
            )
            for i in range(1, 521)
        ]
        self._insert_rows(self.khan_mnt, batch)

        target = Path(self.temp_dir.name) / "paged.csv"
        res = export_csv(self.repo, target, {"direction": "debit"}, format="transactions")
        self.assertEqual(res.count, 520)

        with target.open(encoding="utf-8-sig", newline="") as f:
            lines = list(csv.reader(f))
            self.assertEqual(len(lines) - 1, 520)

    def test_refuse_overwrite_without_confirmation(self):
        target = Path(self.temp_dir.name) / "existing.csv"
        target.write_text("existing data", encoding="utf-8")

        rows = [
            ImportRow(
                description="TEST", bank_datetime="2026-10-10",
                occurred_at="2026-10-10", amount_minor=-50000,
                worksheet="Sheet1", row_number=1, dedup_key="tx-ov-1",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows)

        with self.assertRaises(ExportError):
            export_csv(self.repo, target, {}, format="transactions", confirm_overwrite=False)

        self.assertEqual(target.read_text(encoding="utf-8"), "existing data")

    def test_safe_replacement_with_confirmed_overwrite(self):
        target = Path(self.temp_dir.name) / "overwrite_confirmed.csv"
        target.write_text("initial content", encoding="utf-8")

        rows = [
            ImportRow(
                description="TEST REPLACEMENT", bank_datetime="2026-10-10",
                occurred_at="2026-10-10", amount_minor=-50000,
                worksheet="Sheet1", row_number=1, dedup_key="tx-ov-2",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows)

        res = export_csv(self.repo, target, {}, format="transactions", confirm_overwrite=True)
        self.assertEqual(res.count, 1)

        content = target.read_text(encoding="utf-8-sig")
        self.assertIn("TEST REPLACEMENT", content)
        self.assertNotIn("initial content", content)


class ClassificationMemoryTests(SyntheticMemoryExportBase):
    def test_manual_confirmation_saves_reusable_memory(self):
        rows = [
            ImportRow(
                description="FOOD COURT 01", bank_datetime="2026-10-10 13:00:00",
                occurred_at="2026-10-10T13:00:00", amount_minor=-2500000,
                pos_id="POS888", worksheet="Sheet1", row_number=1, dedup_key="m-1",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows)
        tx_id = self.repo.query_transactions()[0]["id"]

        # Confirm category manually
        self.classification.assign_category([tx_id], self.food_cat)

        # Check memory table
        memories = self.repo.list_classification_memories()
        self.assertEqual(len(memories), 1)
        mem = memories[0]
        self.assertEqual(mem["match_field"], "pos_id")
        self.assertEqual(mem["match_value"], "POS888")
        self.assertEqual(mem["category_id"], self.food_cat)
        self.assertEqual(mem["direction"], "debit")
        self.assertEqual(mem["bank"], "Khan Bank")
        self.assertEqual(mem["usage_count"], 0)

    def test_automatic_memory_reuse_and_source(self):
        # 1. Create confirmed transaction that generates memory
        rows1 = [
            ImportRow(
                description="COFFEE HOUSE A", bank_datetime="2026-10-01 10:00:00",
                occurred_at="2026-10-01T10:00:00", amount_minor=-800000,
                pos_id="COF001", worksheet="Sheet1", row_number=1, dedup_key="cof-1",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows1)
        tx1 = self.repo.query_transactions()[0]
        self.classification.assign_category([tx1["id"]], self.coffee_cat)

        # 2. Import second transaction with matching POS ID
        rows2 = [
            ImportRow(
                description="COFFEE HOUSE B DIFFERENT DESC", bank_datetime="2026-10-05 11:00:00",
                occurred_at="2026-10-05T11:00:00", amount_minor=-900000,
                pos_id="COF001", worksheet="Sheet1", row_number=1, dedup_key="cof-2",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows2)

        # 3. Verify auto-classified with manual_memory
        txs = self.repo.query_transactions()
        tx2 = next(t for t in txs if t["dedup_key"] == "cof-2")
        self.assertEqual(tx2["category_id"], self.coffee_cat)
        self.assertEqual(tx2["classification_source"], "manual_memory")

        # Verify usage count incremented
        mem = self.repo.list_classification_memories()[0]
        self.assertEqual(mem["usage_count"], 1)

    def test_memory_scope_by_bank_account_and_direction(self):
        # Save memory scoped to Khan Bank and debit direction
        mem_id = self.repo.save_classification_memory(
            match_field="description",
            match_value="TAXI RIDE",
            category_id=self.transport_cat,
            direction="debit",
            bank="Khan Bank",
        )
        self.assertGreater(mem_id, 0)

        # Golomt bank transaction with same description must NOT match
        row_golomt = {
            "id": 999, "amount_minor": -1000000, "description": "TAXI RIDE",
            "bank": "Golomt Bank", "kind": "unclassified", "category_id": None,
        }
        self.assertIsNone(self.repo.match_classification_memory(row_golomt))

        # Khan bank transaction with credit direction must NOT match
        row_credit = {
            "id": 998, "amount_minor": 1000000, "description": "TAXI RIDE",
            "bank": "Khan Bank", "kind": "unclassified", "category_id": None,
        }
        self.assertIsNone(self.repo.match_classification_memory(row_credit))

        # Khan bank debit transaction DOES match
        row_khan_debit = {
            "id": 997, "amount_minor": -1000000, "description": "TAXI RIDE",
            "bank": "Khan Bank", "kind": "unclassified", "category_id": None,
        }
        match = self.repo.match_classification_memory(row_khan_debit)
        self.assertIsNotNone(match)
        self.assertEqual(match["category_id"], self.transport_cat)

    def test_memory_never_overwrites_manually_protected_transactions(self):
        mem_id = self.repo.save_classification_memory(
            match_field="description",
            match_value="PROTECTED ITEM",
            category_id=self.food_cat,
            direction="debit",
        )
        # Row with manual_lock=1
        row = {
            "id": 100, "amount_minor": -500000, "description": "PROTECTED ITEM",
            "bank": "Khan Bank", "kind": "unclassified", "category_id": None,
            "manual_lock": 1,
        }
        self.assertIsNone(self.repo.match_classification_memory(row))


class TimeSuggestionTests(SyntheticMemoryExportBase):
    def test_time_window_with_condition_high_confidence(self):
        # Rule: Weekdays 12:00-13:30 + 'lunch' description -> Food (high confidence)
        self.repo.save_time_rule(
            name="Weekday Lunch",
            weekdays=[0, 1, 2, 3, 4],
            start_time="12:00",
            end_time="13:30",
            category_id=self.food_cat,
            match_field="description",
            match_value="lunch",
            target_kind="expense",
            confidence="high",
        )

        # 2026-10-14 is Wednesday (weekday=2), time 12:30
        rows = [
            {
                "id": 10,
                "occurred_at": "2026-10-14T12:30:00",
                "description": "Quick lunch at cafeteria",
                "amount_minor": -1500000,
                "kind": "unclassified",
                "category_id": None,
            }
        ]
        suggestions = self.memory_service.find_suggestions(rows)
        self.assertEqual(len(suggestions), 1)
        sug = suggestions[0]
        self.assertEqual(sug["transaction_id"], 10)
        self.assertEqual(sug["category_id"], self.food_cat)
        self.assertEqual(sug["confidence"], "high")
        self.assertEqual(sug["source"], "time_rule")

    def test_time_only_rule_low_confidence_no_auto_classify_on_import(self):
        # Time-only rule without merchant condition
        self.repo.save_time_rule(
            name="General Lunch Window",
            weekdays=[0, 1, 2, 3, 4],
            start_time="12:00",
            end_time="13:30",
            category_id=self.food_cat,
            match_field=None,
            match_value=None,
            target_kind="expense",
            confidence="low",
            auto_classify=False,
        )

        rows = [
            ImportRow(
                description="RANDOM MERCHANT 999", bank_datetime="2026-10-14 12:15:00",
                occurred_at="2026-10-14T12:15:00", amount_minor=-2000000,
                worksheet="Sheet1", row_number=1, dedup_key="no-auto-1",
            ),
        ]
        # On import: must remain unclassified!
        self._insert_rows(self.khan_mnt, rows)
        tx = self.repo.query_transactions()[0]
        self.assertIsNone(tx["category_id"])
        self.assertEqual(tx["classification_source"], "unclassified")

        # But in Review suggestions: surfaces as low-confidence suggestion!
        suggestions = self.memory_service.find_suggestions([tx])
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["confidence"], "low")
        self.assertEqual(suggestions[0]["category_id"], self.food_cat)


class ReviewWorkflowTests(SyntheticMemoryExportBase):
    def setUp(self):
        super().setUp()
        # Seed a time rule
        self.repo.save_time_rule(
            name="Coffee Morning",
            weekdays=[0, 1, 2, 3, 4],
            start_time="08:00",
            end_time="10:00",
            category_id=self.coffee_cat,
            match_field="description",
            match_value="roasters",
            target_kind="expense",
            confidence="high",
        )
        # Import unclassified transaction matching the rule
        rows = [
            ImportRow(
                description="CITY ROASTERS", bank_datetime="2026-10-14 09:15:00",
                occurred_at="2026-10-14T09:15:00", amount_minor=-650000,
                worksheet="Sheet1", row_number=1, dedup_key="wf-1",
            ),
        ]
        self._insert_rows(self.khan_mnt, rows)
        self.tx = self.repo.query_transactions()[0]

    def test_accept_suggestion_assigns_category_and_saves_reusable_memory(self):
        # Suggestions present in Review load
        review_data = self.review_service.load()
        self.assertEqual(len(review_data["suggestions"]), 1)
        sug = review_data["suggestions"][0]
        self.assertEqual(sug["confidence"], "high")

        # Accept suggestion
        res = self.review_service.accept_suggestion(self.tx["id"], sug["category_id"])
        updated = self.repo.get_transaction(self.tx["id"])
        self.assertEqual(updated["category_id"], self.coffee_cat)
        self.assertTrue(updated["manual_lock"])
        self.assertIsNotNone(updated["applied_memory_id"])

        # Reusable memory was saved
        memories = self.repo.list_classification_memories()
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["category_id"], self.coffee_cat)

    def test_reject_suggestion_dismisses_without_memory(self):
        review_data = self.review_service.load()
        self.assertEqual(len(review_data["suggestions"]), 1)

        # Reject suggestion
        self.review_service.reject_suggestion(self.tx["id"])

        # Transaction remains unclassified
        tx_now = self.repo.get_transaction(self.tx["id"])
        self.assertIsNone(tx_now["category_id"])

        # Subsequent load does not re-suggest rejected item
        review_after = self.review_service.load()
        self.assertEqual(len(review_after["suggestions"]), 0)

        # No memory recorded
        self.assertEqual(len(self.repo.list_classification_memories()), 0)

    def test_edit_suggestion_assigns_new_category_and_saves_memory(self):
        # User changes suggested Coffee to Food
        self.review_service.edit_suggestion(self.tx["id"], self.food_cat)

        tx_now = self.repo.get_transaction(self.tx["id"])
        self.assertEqual(tx_now["category_id"], self.food_cat)
        self.assertTrue(tx_now["manual_lock"])

        # Saved memory uses the user's chosen category
        mem = self.repo.list_classification_memories()[0]
        self.assertEqual(mem["category_id"], self.food_cat)

    def test_export_classified_result_to_csv_after_review(self):
        # Accept suggestion
        self.review_service.accept_suggestion(self.tx["id"], self.coffee_cat)

        # Export classified result to CSV
        target = Path(self.temp_dir.name) / "post_review_export.csv"
        res = export_csv(self.repo, target, {}, language="mn", format="transactions")
        self.assertEqual(res.count, 1)

        with target.open(encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
            self.assertEqual(tuple(reader[0]), TRANSACTION_FIELDS_MN)
            row = reader[1]
            self.assertEqual(row[3], "Кофе, амттан")
            self.assertEqual(row[8], "manual_memory")


if __name__ == "__main__":
    unittest.main()
