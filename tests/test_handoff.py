"""One synthetic offline end-to-end acceptance scenario and headless UI boundaries."""

import csv
import json
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import Mock, patch

from app.backup import create_backup, prepare_restore, validate_backup
from app.db import Repository
from app.import_service import ImportService
from app.review_service import ReviewService
from app.reporting import ReportingService
from tests.review_fixtures import create_review_fixtures
from tests.test_ui import temporary_case
from tests import test_review_ui as review_ui
from tests.test_ui_flow import Control


class HandoffTests(unittest.TestCase):
    def test_offline_import_review_repeat_edit_restart_backup_and_temporary_restore(self):
        folder = temporary_case(self)
        create_review_fixtures(folder)
        database = folder / "finance.sqlite3"
        # Outbound network operations fail throughout the synthetic scenario.
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("Network forbidden")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("Network forbidden")):
            with Repository(database) as repo:
                account = repo.create_account("MN00000000000000000000", "Synthetic Khan")
                imports, review = ImportService(repo), ReviewService(repo)
                first = imports.confirm(imports.preview(folder / "review-initial.xlsx", account), {})
                self.assertEqual(first.imported_count, 5)
                self.assertEqual(repo.count_transactions(review_only=True), 5)
                group = review.classification.review().groups[0]
                row_id = group.items[0].transaction_id
                categories = {c["name"]: c["id"] for c in repo.list_categories()}
                preview = review.preview_assignment([row_id], categories["Other expenses"], save_rule=True)
                review.confirm_assignment(preview["token"])
                future = imports.confirm(imports.preview(folder / "review-future.xlsx", account), {})
                future_row = repo.query_transactions(import_id=future.import_id)[0]
                self.assertEqual(future_row["category_id"], categories["Other expenses"])
                repeat = imports.confirm(imports.preview(folder / "review-initial.xlsx", account), {})
                self.assertEqual(repeat.imported_count, 0)
                original = repo.get_transaction(row_id)
                repo.edit_transaction(row_id, amount_minor=-250, description="Fictional corrected description",
                                      note="Synthetic correction", reason="Synthetic handoff")
                rule = repo.list_rules()[0]
                review.change_rule(rule["id"], rule["revision"], categories["Software & Digital Subscriptions"])
                imports.confirm(imports.preview(folder / "review-initial.xlsx", account), {})
                corrected = repo.get_transaction(row_id)
                self.assertEqual(corrected["amount_minor"], -250)
                self.assertEqual(corrected["category_id"], categories["Other expenses"])
                self.assertTrue(corrected["manual_lock"])
                self.assertEqual(corrected["original_amount_minor"], original["original_amount_minor"])
                report = ReportingService(repo).summarize()
            with Repository(database) as restarted:
                self.assertEqual(restarted.get_transaction(row_id), corrected)
                self.assertEqual(restarted.count_transactions(), 6)
                self.assertEqual(ReportingService(restarted).summarize(), report)
                before = restarted.query_transactions()
                backup = create_backup(restarted, folder)
                self.assertEqual(validate_backup(backup), 3)
                restored = prepare_restore(backup, folder / "separate-restored.sqlite3")
                with Repository(restored) as independent:
                    self.assertEqual(independent.query_transactions(), before)
                    self.assertEqual(independent.list_rules(), restarted.list_rules())
                self.assertEqual(restarted.query_transactions(), before)

    def test_workspace_run_debug_and_launcher_static_configuration(self):
        root = Path(__file__).resolve().parents[1]
        launch = json.loads((root / ".vscode/launch.json").read_text())
        config = next(c for c in launch["configurations"] if c["name"] == "Personal Finance Tool")
        self.assertEqual((config["type"], config["module"], config["cwd"], config["console"]),
                         ("debugpy", "app", "${workspaceFolder}", "integratedTerminal"))
        self.assertEqual(config["python"], "${workspaceFolder}/.venv/Scripts/python.exe")
        settings = json.loads((root / ".vscode/settings.json").read_text())
        self.assertTrue(settings["python.testing.unittestEnabled"])
        self.assertFalse(settings["python.terminal.activateEnvironment"])
        self.assertTrue((root / ".venv/Scripts/python.exe").is_file())
        launcher = (root / "start.bat").read_text()
        for command in ('pushd "%~dp0"', '".venv\\Scripts\\python.exe" -m app', 'pause'):
            self.assertIn(command, launcher)
        self.assertNotIn("pip install", launcher)


class LocalControllerTests(unittest.TestCase):
    stop = review_ui.ReviewControllerTests.stop

    def wait(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.app._poll()
            if not self.app.busy:
                return
            time.sleep(.005)
        self.fail("Synthetic local operation timed out")

    def setUp(self):
        review_ui.ReviewControllerTests.setUp(self)
        self.app.local_buttons = [Control() for _ in range(4)]
        self.messages = []
        p = patch("app.ui.desktop.messagebox.showinfo", side_effect=lambda title, message, **kw: self.messages.append(message))
        p.start()
        self.addCleanup(p.stop)

    def test_restore_cancel_confirm_requires_restart_and_preserves_safety(self):
        self.app._request("backup", folder=str(self.folder))
        self.wait()
        backup = next(self.folder.glob("finance-backup-*.sqlite3"))
        with Repository(self.folder / "finance.sqlite3") as repo:
            repo.edit_transaction(1, note="Later synthetic note", reason="Synthetic")
        with patch("app.ui.desktop.filedialog.askopenfilename", return_value=str(backup)), \
             patch("app.ui.desktop.messagebox.askyesno", return_value=False):
            self.app._restore()
            self.wait()
        self.assertIn("canceled", self.app.status.get())
        with Repository(self.folder / "finance.sqlite3") as repo:
            self.assertEqual(repo.get_transaction(1)["note"], "Later synthetic note")
        with patch("app.ui.desktop.filedialog.askopenfilename", return_value=str(backup)), \
             patch("app.ui.desktop.messagebox.askyesno", return_value=True):
            self.app._restore()
            self.wait()
        self.assertFalse(self.app.ready)
        self.assertTrue(all(button.disabled for button in self.app.local_buttons))
        self.assertIn("Close and reopen", self.app.status.get())
        self.assertEqual(self.app.transactions.items, ())
        self.assertFalse(self.app._request("account", name="Should not write", identifier="synthetic"))
        with Repository(self.folder / "finance.sqlite3") as repo:
            self.assertEqual(repo.get_transaction(1)["note"], "")
        self.assertEqual(self.errors, [])

    def test_restore_failure_keeps_ui_usable(self):
        self.app._request("backup", folder=str(self.folder))
        self.wait()
        backup = next(self.folder.glob("finance-backup-*.sqlite3"))
        with patch("app.ui.desktop.messagebox.askyesno", return_value=True), \
             patch("app.restore_service.create_backup", side_effect=OSError("SYNTHETIC_SECRET")):
            self.app._request("restore_preview", path=str(backup))
            self.wait()
        self.assertTrue(self.app.ready)
        self.assertNotIn("SYNTHETIC_SECRET", self.errors[-1])
        self.app._browse()
        self.wait()
        self.assertEqual(self.app.browser_total, 5)

    def test_worker_restore_preview_blocks_mutations_until_cancel(self):
        self.app.worker.submit("backup", folder=str(self.folder))
        event = self.app.worker.events.get(timeout=5)
        self.assertIsNone(event.error)
        self.app.worker.submit("restore_preview", path=str(event.payload))
        preview = self.app.worker.events.get(timeout=5)
        self.assertIsNone(preview.error)
        self.app.worker.submit("account", name="Blocked synthetic account", identifier="DO-NOT-CREATE")
        blocked = self.app.worker.events.get(timeout=5)
        self.assertIn("cancel", blocked.error)
        self.app.worker.submit("restore_cancel")
        self.assertIsNone(self.app.worker.events.get(timeout=5).error)
        self.app._browse()
        self.wait()
        self.assertEqual(self.app.browser_total, 5)

    def test_export_uses_applied_filters_all_pages_and_empty_does_not_open_picker(self):
        target = self.folder / "synthetic-ui.csv"
        self.app.active_filters = {"direction": "credit", "currency": "MNT"}
        self.app._browse()
        self.wait()
        with patch("app.ui.desktop.filedialog.asksaveasfilename", return_value=str(target)):
            self.app._export_csv()
            self.wait()
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signed_amount"], "2.00")
        self.assertIn("Exported 1", self.app.status.get())
        self.app.active_filters = {"search": "missing fictional row"}
        self.app._browse()
        self.wait()
        with patch("app.ui.desktop.filedialog.asksaveasfilename") as picker:
            self.app._export_csv()
        picker.assert_not_called()
        self.assertIn("No export file", self.app.status.get())

    def test_account_filter_is_applied_to_browser_and_export_and_reset_by_drill(self):
        self.app.browser_account_box = Control()
        self.app.browser_account_box.current(1)
        self.app._apply_filters()
        self.wait()
        self.assertEqual(self.app.active_filters["account_id"], self.app.accounts[0]["id"])
        self.app._dashboard_drill({"date_from": "2026-10-01", "date_to": "2026-10-31", "currency": "MNT"})
        self.wait()
        self.assertEqual(self.app.browser_account_box.current(), 0)
        self.assertNotIn("account_id", self.app.active_filters)

    def test_about_and_data_folder_actions_are_local_and_errors_visible(self):
        self.app._about()
        self.assertIn("Database schema 3", self.messages[-1])
        with patch("app.ui.desktop.open_data_folder") as folder:
            self.app._open_data_folder()
        folder.assert_called_once_with(self.folder.resolve())
        with patch("app.ui.desktop.open_data_folder", side_effect=ValueError("Synthetic unavailable folder")):
            self.app._open_data_folder()
        self.assertEqual(self.errors[-1], "Synthetic unavailable folder")
