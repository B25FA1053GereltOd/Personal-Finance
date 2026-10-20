"""Headless actual UI callbacks + worker + synthetic database, not visual QA."""

import sqlite3
import unittest
from unittest.mock import patch

from app.backup import validate_backup
from app.db import Repository
from app.ui.dashboard import DashboardView
from tests import test_review_ui as review_ui
from tests.dashboard_fixture import populate


class DashboardControllerTests(unittest.TestCase):
    wait = review_ui.ReviewControllerTests.wait
    stop = review_ui.ReviewControllerTests.stop

    def setUp(self):
        review_ui.ReviewControllerTests.setUp(self)
        self.dashboard = self.app.dashboard = DashboardView(self.app, review_ui.table_factory)
        self.wait()

    def select_group_rows(self, *rows):
        review_ui.ReviewControllerTests.select_group_rows(self, *rows)

    def test_auto_refresh_after_classification_import_rule_application_and_edit(self):
        self.assertEqual(self.dashboard.report.unclassified_count, 5)
        self.select_group_rows(0)
        identifier = self.view.rows.items[0].transaction_id
        self.view.save_future.set(True)
        self.view.preview_assignment()
        self.wait()
        self.view.apply_preview()
        self.wait()
        self.assertEqual((self.dashboard.report.totals[0]["expenses"], self.dashboard.report.unclassified_count), (100, 4))
        self.app.file_path.set(str(self.folder / "review-future.xlsx"))
        self.app.account_confirmed.set(True)
        self.app._preview()
        self.wait()
        self.app._commit()
        self.wait()
        self.assertEqual((self.dashboard.report.transaction_count, self.dashboard.report.totals[0]["expenses"]), (6, 200))
        self.view.rules.tree.selection_set(0)
        self.view.preview_rule()
        self.wait()
        self.view.preview_rows.tree.selection_set(0)
        self.view.apply_preview()
        self.wait()
        self.assertEqual(self.dashboard.report.totals[0]["expenses"], 300)
        self.app._request("edit_get", transaction_id=identifier)
        self.wait()
        self.view.edit_fields["amount"].set("-2.50")
        self.view.save_edit()
        self.wait()
        self.assertEqual(self.dashboard.report.totals[0]["expenses"], 450)
        self.assertEqual(self.errors, [])

    def test_currency_and_date_drill_down_resets_search_and_preserves_filters_on_refresh(self):
        with Repository(self.folder / "finance.sqlite3") as repo:
            populate(repo)
        self.dashboard.preset.set("Custom range")
        self.dashboard.start.set("2026-10-10")
        self.dashboard.end.set("2026-10-31")
        self.dashboard.apply()
        self.wait()
        table = self.dashboard.breakdowns["expense"]
        index = next(i for i, r in enumerate(table.items) if r["currency"] == "USD")
        table.tree.selection_set(index)
        self.app.search.set("old nonmatching search")
        self.app.review_only.set(True)
        self.dashboard.drill("expense")
        self.wait()
        self.assertEqual(self.app.currency_text.get(), "USD")
        self.assertFalse(self.app.review_only.get())
        self.assertEqual(self.app.search.get(), "")
        self.assertEqual(self.app.browser_total, 1)
        self.assertIn("USD", self.app.transactions.tree.rows["0"][2])
        self.app._apply_filters()
        self.wait()
        self.assertEqual(self.app.browser_total, 1)
        monthly = self.dashboard.breakdowns["month"]
        monthly.tree.selection_set(next(i for i, r in enumerate(monthly.items) if r["currency"] == "USD"))
        self.dashboard.drill("month")
        self.wait()
        self.assertEqual(self.app.browser_total, 2)
        self.assertEqual((self.app.date_from.get(), self.app.date_to.get()), ("2026-10-10", "2026-10-31"))
        self.assertEqual(self.errors, [])

    def test_invalid_input_database_error_empty_state_and_recovery(self):
        self.dashboard.preset.set("Custom range")
        self.dashboard.start.set("bad")
        self.dashboard.end.set("2026-10-01")
        self.dashboard.apply()
        self.wait()
        self.assertIsNone(self.dashboard.report)
        self.assertEqual(len(self.errors), 1)
        self.dashboard.preset.set("All time")
        with patch("app.ui.worker.ReportingService.summarize", side_effect=sqlite3.OperationalError("SYNTHETIC_SECRET")):
            self.dashboard.apply()
            self.wait()
        self.assertIsNone(self.dashboard.report)
        self.assertNotIn("SYNTHETIC_SECRET", self.errors[-1])
        self.dashboard.apply()
        self.wait()
        self.assertEqual(self.dashboard.report.transaction_count, 5)
        self.dashboard.preset.set("Custom range")
        self.dashboard.start.set("2000-01-01")
        self.dashboard.end.set("2000-01-31")
        self.dashboard.apply()
        self.wait()
        self.assertIn("no transactions", self.dashboard.message.get())
        self.assertEqual(self.dashboard.totals.items, ())

    def test_backup_picker_cancel_then_worker_snapshot_success(self):
        before = set(self.folder.iterdir())
        with patch("app.ui.desktop.filedialog.askdirectory", return_value=""):
            self.app._backup()
        self.assertEqual(set(self.folder.iterdir()), before)
        with patch("app.ui.desktop.filedialog.askdirectory", return_value=str(self.folder)):
            self.app._backup()
        self.wait()
        snapshots = list(self.folder.glob("finance-backup-*.sqlite3"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(validate_backup(snapshots[0]), 3)
        self.assertIn("Backup completed and validated", self.app.status.get())
        self.assertEqual(self.errors, [])
