"""Synthetic tests for selective transaction archiving and restoration."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import Repository
from app.models import ImportInfo, ImportRow
from app.reporting import (
    ReportingService, category_chart_series, format_money, monthly_chart_series,
)
from app.ui.presentation import archive_confirmation_details, browser_filters, review_status
from app.ui.review import selected_items
from app.ui.worker import FinanceWorker


class TransactionArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(
            prefix="finance-archive-test-",
            dir=Path(__file__).resolve().parents[1] / "data" / "test-temp",
        )
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "test.sqlite3"
        self.repo = Repository(self.db_path)
        self.addCleanup(self.repo.close)
        self.account_mnt = self.repo.create_account("111111", "Khan Main", bank="Khan Bank", currency="MNT")
        self.account_usd = self.repo.create_account("222222", "Khan USD", bank="Khan Bank", currency="USD")
        self.categories = self.repo.list_categories()
        self.coffee_cat = next(c["id"] for c in self.categories if c["name"] == "Cafeteria, Coffee & Snacks")
        self.salary_cat = next(c["id"] for c in self.categories if c["name"] == "Earned income (part-time job, freelancing, internship)")

    def _insert_sample_transactions(self) -> dict[str, int]:
        rows_mnt = [
            ImportRow(
                description="COFFEE SHOP 1", bank_datetime="2026-10-01 09:00:00",
                occurred_at="2026-10-01T09:00:00", amount_minor=-500000,
                worksheet="Sheet1", row_number=1, dedup_key="mnt-row-1",
            ),
            ImportRow(
                description="COFFEE SHOP 2", bank_datetime="2026-10-05 10:00:00",
                occurred_at="2026-10-05T10:00:00", amount_minor=-750000,
                worksheet="Sheet1", row_number=2, dedup_key="mnt-row-2",
            ),
            ImportRow(
                description="SALARY OCT", bank_datetime="2026-10-15 18:00:00",
                occurred_at="2026-10-15T18:00:00", amount_minor=250000000,
                worksheet="Sheet1", row_number=3, dedup_key="mnt-row-3",
            ),
        ]
        info_mnt = ImportInfo(
            account_id=self.account_mnt, sha256="1" * 64,
            parser_version="synthetic-v1", filename="stmt_mnt.xlsx",
        )
        self.repo.write_import(info_mnt, rows_mnt)

        rows_usd = [
            ImportRow(
                description="AWS CLOUD", bank_datetime="2026-10-10 12:00:00",
                occurred_at="2026-10-10T12:00:00", amount_minor=-2000,
                currency="USD",
                worksheet="Sheet1", row_number=1, dedup_key="usd-row-1",
            ),
        ]
        info_usd = ImportInfo(
            account_id=self.account_usd, sha256="2" * 64,
            parser_version="synthetic-v1", filename="stmt_usd.xlsx",
        )
        self.repo.write_import(info_usd, rows_usd)
        all_tx = self.repo.query_transactions(archived=None)
        return {t["description"]: t["id"] for t in all_tx}

    def test_single_transaction_archive_and_restore(self) -> None:
        tx_map = self._insert_sample_transactions()
        target_id = tx_map["COFFEE SHOP 1"]

        # Verify active initially
        active_before = self.repo.query_transactions()
        self.assertEqual(len(active_before), 4)
        target_tx = next(t for t in active_before if t["id"] == target_id)
        self.assertEqual(target_tx["is_archived"], 0)
        self.assertIsNone(target_tx["archived_at"])

        # Archive single transaction
        self.repo.archive_transactions([target_id])

        # Excluded from active transactions
        active_after = self.repo.query_transactions()
        self.assertEqual(len(active_after), 3)
        self.assertNotIn(target_id, [t["id"] for t in active_after])
        self.assertEqual(self.repo.count_transactions(), 3)

        # Included when querying archived
        archived_txs = self.repo.query_transactions(archived=True)
        self.assertEqual(len(archived_txs), 1)
        self.assertEqual(archived_txs[0]["id"], target_id)
        self.assertEqual(archived_txs[0]["is_archived"], 1)
        self.assertIsNotNone(archived_txs[0]["archived_at"])
        self.assertEqual(review_status(archived_txs[0]), "Archived")

        # Included when querying all (archived=None)
        all_txs = self.repo.query_transactions(archived=None)
        self.assertEqual(len(all_txs), 4)

        # Restore transaction
        self.repo.restore_transactions([target_id])

        # Returns to active transactions
        active_restored = self.repo.query_transactions()
        self.assertEqual(len(active_restored), 4)
        restored_tx = next(t for t in active_restored if t["id"] == target_id)
        self.assertEqual(restored_tx["is_archived"], 0)
        self.assertIsNone(restored_tx["archived_at"])

    def test_multi_selection_archive_and_restore(self) -> None:
        tx_map = self._insert_sample_transactions()
        archive_ids = [tx_map["COFFEE SHOP 1"], tx_map["COFFEE SHOP 2"]]

        # Archive multiple
        self.repo.archive_transactions(archive_ids)

        active = self.repo.query_transactions()
        self.assertEqual(len(active), 2)
        self.assertEqual({t["id"] for t in active}, {tx_map["SALARY OCT"], tx_map["AWS CLOUD"]})

        archived = self.repo.query_transactions(archived=True)
        self.assertEqual(len(archived), 2)
        self.assertEqual({t["id"] for t in archived}, set(archive_ids))

        # Restore both
        self.repo.restore_transactions(archive_ids)
        self.assertEqual(len(self.repo.query_transactions()), 4)
        self.assertEqual(len(self.repo.query_transactions(archived=True)), 0)

    def test_archived_transactions_excluded_from_reporting_and_classification(self) -> None:
        tx_map = self._insert_sample_transactions()
        coffee1_id = tx_map["COFFEE SHOP 1"]
        coffee2_id = tx_map["COFFEE SHOP 2"]
        salary_id = tx_map["SALARY OCT"]

        # Classify coffee transaction first
        self.repo.assign_category(coffee1_id, self.coffee_cat, reason="Synthetic test classification")

        # Baseline reporting rows
        rep_before = self.repo.reporting_rows(currency="MNT")
        self.assertEqual(len(rep_before), 3)

        # Classification rows
        class_before = self.repo.classification_rows()
        self.assertIn(coffee2_id, [r["id"] for r in class_before])

        # Archive coffee transaction (coffee1_id) and second coffee (coffee2_id)
        self.repo.archive_transactions([coffee1_id, coffee2_id])

        # Reporting rows now excludes archived
        rep_after = self.repo.reporting_rows(currency="MNT")
        self.assertEqual(len(rep_after), 1)
        self.assertEqual(rep_after[0]["amount_minor"], 250000000)  # Salary remaining

        # Classification rows excludes archived
        class_after = self.repo.classification_rows()
        self.assertNotIn(coffee1_id, [r["id"] for r in class_after])
        self.assertNotIn(coffee2_id, [r["id"] for r in class_after])

        # Restore
        self.repo.restore_transactions([coffee1_id])
        rep_restored = self.repo.reporting_rows(currency="MNT")
        self.assertEqual(len(rep_restored), 2)

    def test_archive_excludes_dashboard_totals_and_charts_then_restore_reinstates_them(self) -> None:
        tx_map = self._insert_sample_transactions()
        expense_ids = (
            tx_map["COFFEE SHOP 1"],
            tx_map["COFFEE SHOP 2"],
            tx_map["AWS CLOUD"],
        )
        for transaction_id in expense_ids:
            self.repo.assign_category(transaction_id, self.coffee_cat, reason="Synthetic chart setup")
        self.repo.assign_category(tx_map["SALARY OCT"], self.salary_cat, reason="Synthetic chart setup")
        reporting = ReportingService(self.repo)

        before = reporting.summarize()
        self.assertEqual(before.transaction_count, 4)
        self.assertEqual({row["currency"] for row in monthly_chart_series(before)}, {"MNT", "USD"})

        archived_ids = [tx_map["COFFEE SHOP 1"], tx_map["AWS CLOUD"]]
        self.repo.archive_transactions(archived_ids)
        after = reporting.summarize()
        totals = {row["currency"]: row for row in after.totals}
        self.assertEqual(after.transaction_count, 2)
        self.assertEqual(set(totals), {"MNT"})
        self.assertEqual(totals["MNT"]["expenses"], 750000)
        self.assertEqual(monthly_chart_series(after)[0]["currency"], "MNT")
        self.assertEqual(category_chart_series(after, "expense")[0]["bars"][0]["count"], 1)

        self.repo.restore_transactions(archived_ids)
        restored = reporting.summarize()
        self.assertEqual(restored.transaction_count, before.transaction_count)
        self.assertEqual(monthly_chart_series(restored), monthly_chart_series(before))

    def test_reimport_statement_does_not_create_duplicate_of_archived_transaction(self) -> None:
        tx_map = self._insert_sample_transactions()
        archive_target = tx_map["COFFEE SHOP 1"]

        # Archive it
        self.repo.archive_transactions([archive_target])
        self.assertEqual(self.repo.count_transactions(account_id=self.account_mnt), 2)

        # The archived transaction's source data and deduplication key are preserved in import state
        state = self.repo.get_import_state(self.account_mnt)
        tx_in_state = next(t for t in state["transactions"] if t["id"] == archive_target)
        self.assertEqual(tx_in_state["dedup_key"], "mnt-row-1")
        self.assertEqual(tx_in_state["original_amount_minor"], -500000)

        # Verify total transactions in DB for this account remains 3
        total_in_db = self.repo.count_transactions(account_id=self.account_mnt, archived=None)
        self.assertEqual(total_in_db, 3)

    def test_audit_history_and_manual_protection_preserved(self) -> None:
        tx_map = self._insert_sample_transactions()
        target = tx_map["COFFEE SHOP 1"]
        self.repo.assign_category(target, self.coffee_cat, reason="Synthetic test classification")

        # Verify audit history
        edits_before = self.repo.get_history(target)
        self.assertGreaterEqual(len(edits_before), 1)

        # Archive
        self.repo.archive_transactions([target])
        edits_archive = self.repo.get_history(target)
        self.assertEqual(len(edits_archive), len(edits_before) + 1)
        latest_edit = edits_archive[-1]
        delta = latest_edit["changes"]
        self.assertEqual(delta.get("is_archived"), {"old": 0, "new": 1})

        # Restore
        self.repo.restore_transactions([target])
        edits_restore = self.repo.get_history(target)
        self.assertEqual(len(edits_restore), len(edits_archive) + 1)
        restore_delta = edits_restore[-1]["changes"]
        self.assertEqual(restore_delta.get("is_archived"), {"old": 1, "new": 0})

        # Manual lock and category still preserved
        tx = self.repo.get_transaction(target)
        self.assertEqual(tx["category_id"], self.coffee_cat)
        self.assertEqual(tx["manual_lock"], 1)

    def test_physical_delete_trigger_still_blocks_deletion(self) -> None:
        tx_map = self._insert_sample_transactions()
        target = tx_map["COFFEE SHOP 1"]
        with self.assertRaises(sqlite3.DatabaseError):
            self.repo._connection.execute("DELETE FROM transactions WHERE id = ?", (target,))

    def test_confirmation_dialog_calculations(self) -> None:
        txs = [
            {"occurred_at": "2026-10-01T09:00:00", "currency": "MNT", "amount_minor": -500000},
            {"occurred_at": "2026-10-15T18:00:00", "currency": "MNT", "amount_minor": -750000},
            {"occurred_at": "2026-10-10T12:00:00", "currency": "USD", "amount_minor": -2000},
        ]
        count, currency_totals, date_range = archive_confirmation_details(txs)
        self.assertEqual(count, 3)
        self.assertEqual(currency_totals["MNT"], -1250000)
        self.assertEqual(currency_totals["USD"], -2000)
        self.assertEqual(format_money(currency_totals["MNT"], "MNT"), "-12,500.00 MNT")
        self.assertEqual(format_money(currency_totals["USD"], "USD"), "-20.00 USD")
        self.assertEqual(date_range, "2026-10-01 — 2026-10-15")

    def test_selecting_one_or_multiple_transactions(self) -> None:
        class Selection:
            def __init__(self):
                self.selected = ()

            def selection(self):
                return self.selected

        class Table:
            def __init__(self, items):
                self.items = items
                self.tree = Selection()

        table = Table([{"id": 1}, {"id": 2}, {"id": 3}])
        table.tree.selected = ("1",)
        self.assertEqual(selected_items(table), [{"id": 2}])
        table.tree.selected = ("0", "2")
        self.assertEqual(selected_items(table), [{"id": 1}, {"id": 3}])

    def test_archive_and_restore_are_idempotent_for_duplicate_or_wrong_state_ids(self) -> None:
        tx_map = self._insert_sample_transactions()
        target = tx_map["COFFEE SHOP 1"]
        self.assertEqual(self.repo.archive_transactions([target, target]), 1)
        archived_at = self.repo.get_transaction(target)["archived_at"]
        history_count = len(self.repo.get_history(target))
        self.assertEqual(self.repo.archive_transactions([target]), 0)
        self.assertEqual(self.repo.get_transaction(target)["archived_at"], archived_at)
        self.assertEqual(len(self.repo.get_history(target)), history_count)
        self.assertEqual(self.repo.restore_transactions([target, target]), 1)
        self.assertEqual(self.repo.restore_transactions([target]), 0)

    def test_worker_archive_and_restore_operations(self) -> None:
        tx_map = self._insert_sample_transactions()
        target = tx_map["COFFEE SHOP 1"]
        worker = FinanceWorker(self.db_path)
        self.addCleanup(worker.thread.join)
        self.addCleanup(worker.stop)

        # Worker emits 'ready' upon startup
        ready_event = worker.events.get(timeout=5)
        self.assertEqual(ready_event.operation, "ready")

        # Worker transactions_archive
        worker.submit("transactions_archive", transaction_ids=[target])
        event = worker.events.get(timeout=5)
        self.assertEqual(event.operation, "transactions_archive")
        self.assertEqual(event.payload["archived_count"], 1)

        # Verify excluded in browse
        worker.submit("browse", filters=browser_filters(archived=False))
        event = worker.events.get(timeout=5)
        self.assertEqual(event.operation, "browse")
        self.assertEqual(event.payload["total"], 3)

        # Verify included in browse archived
        worker.submit("browse", filters=browser_filters(archived=True))
        event = worker.events.get(timeout=5)
        self.assertEqual(event.operation, "browse")
        self.assertEqual(event.payload["total"], 1)
        self.assertEqual(event.payload["rows"][0]["id"], target)

        # Worker transactions_restore
        worker.submit("transactions_restore", transaction_ids=[target])
        event = worker.events.get(timeout=5)
        self.assertEqual(event.operation, "transactions_restore")
        self.assertEqual(event.payload["restored_count"], 1)

        # Verify restored in browse
        worker.submit("browse", filters=browser_filters(archived=False))
        event = worker.events.get(timeout=5)
        self.assertEqual(event.operation, "browse")
        self.assertEqual(event.payload["total"], 4)


if __name__ == "__main__":
    unittest.main()
