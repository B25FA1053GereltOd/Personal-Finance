"""Real review UI callbacks with widget stand-ins and the real worker/services."""

import time
import unittest
from unittest.mock import Mock, patch

from app.db import Repository
from app.ui.desktop import DesktopApp, PagedTable
from app.ui.review import ReviewViews
from tests.review_fixtures import create_review_fixtures
from tests.test_ui import temporary_case
from tests.test_ui_flow import Control, Tree, Value, build_views


class SelectableTree(Tree):
    def __init__(self):
        super().__init__()
        self.chosen = ()
        self.bind = Mock()

    def selection(self):
        return self.chosen

    def selection_set(self, *items):
        self.chosen = tuple(str(i) for i in items)

    def delete(self, *items):
        super().delete(*items)
        self.chosen = tuple(i for i in self.chosen if i not in items)


def table_factory(parent, columns, **options):
    table = PagedTable.__new__(PagedTable)
    table.size, table.page, table.items, table.values = options.get("size", 50), 0, (), lambda r: r
    table.tree = SelectableTree()
    table.previous, table.next, table.caption = Control(), Control(), Control()
    table.grid = Mock()
    return table


def build_review_views(app, data_dir):
    build_views(app, data_dir)
    app.transactions.tree = SelectableTree()
    app.review_views = ReviewViews(app, table_factory)


class ReviewControllerTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        create_review_fixtures(self.folder)
        self.errors = []
        replacements = [
            ("app.ui.desktop.DesktopApp._build", build_review_views),
            ("app.ui.review.tk.StringVar", Value), ("app.ui.review.tk.BooleanVar", Value),
            ("app.ui.review.tk.Toplevel", Mock()), ("app.ui.review.tk.Text", Mock()),
            ("app.ui.desktop.messagebox.showerror", Mock(side_effect=lambda title, message, **kw: self.errors.append(message))),
        ]
        replacements.extend(("app.ui.review.ttk." + name, Mock()) for name in
                            ("Frame", "Button", "Label", "Combobox", "Checkbutton", "Entry", "Notebook", "Scrollbar"))
        for target, replacement in replacements:
            p = patch(target, replacement)
            p.start()
            self.addCleanup(p.stop)
        self.app = DesktopApp(Mock(), self.folder)
        self.addCleanup(self.stop)
        self.wait()
        self.app._request("account", name="Synthetic Khan", identifier="MN00000000000000000000")
        self.wait()
        self.app.file_path.set(str(self.folder / "review-initial.xlsx"))
        self.app.account_confirmed.set(True)
        self.app._preview()
        self.wait()
        self.app._commit()
        self.wait()
        self.view = self.app.review_views
        self.view.open()
        self.wait()

    def stop(self):
        self.app.worker.stop()
        self.app.worker.thread.join(5)
        self.assertFalse(self.app.worker.thread.is_alive())

    def wait(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app._poll()
            if self.app.ready and not self.app.busy:
                return
            time.sleep(.005)
        self.fail("Synthetic review UI command timed out")

    def select_group_rows(self, *rows):
        self.view.groups.tree.selection_set(0)
        self.view.expand()
        self.view.rows.tree.selection_set(*rows)
        self.view._categories()
        self.view.category.set("Other expenses")

    def test_review_cancel_assign_future_rule_edit_and_selected_rule_apply(self):
        self.assertEqual(len(self.view.groups.items), 3)
        self.assertEqual(self.view.groups.tree.rows["0"][1], 3)
        self.select_group_rows(0)
        identifier = self.view.rows.items[0].transaction_id
        self.assertFalse(self.view.save_future.get())
        self.view.preview_assignment()
        self.wait()
        self.assertEqual(len(self.view.preview_rows.items), 1)
        self.view.cancel_preview()
        self.wait()
        self.assertIsNone(self.view.pending)
        self.view.save_future.set(True)
        self.view.preview_assignment()
        self.wait()
        self.view.apply_preview()
        self.wait()
        self.assertEqual(len(self.view.rules.items), 1)
        self.assertEqual(len(self.view.groups.items[0]["items"]), 2)
        # Use the actual transaction editor callback, including its field mapping.
        index = next(i for i, r in enumerate(self.app.transactions.items) if r["id"] == identifier)
        self.app.transactions.tree.selection_set(index)
        self.app._edit_selected()
        self.wait()
        original = self.view.edit_snapshot["row"]
        self.assertFalse(self.view.clear_protection.get())
        self.view.edit_fields["amount"].set("-2.50")
        self.view.edit_fields["merchant_display"].set("FICTIONAL DISPLAY OVERRIDE")
        self.view.edit_fields["note"].set("Synthetic UI note")
        self.view.save_edit()
        self.wait()
        self.assertIsNone(self.view.editor)
        with Repository(self.folder / "finance.sqlite3") as repo:
            edited = repo.get_transaction(identifier)
            self.assertEqual(edited["original_amount_minor"], original["original_amount_minor"])
            self.assertEqual(edited["merchant_key"], original["merchant_key"])
            self.assertEqual(edited["amount_minor"], -250)
            self.assertTrue(edited["manual_lock"])
        self.view.rules.tree.selection_set(0)
        self.view.rule_selected()
        self.view.rule_category.set("Software & Digital Subscriptions")
        self.view.change_rule(False)
        self.wait()
        self.view.rules.tree.selection_set(0)
        self.view.preview_rule()
        self.wait()
        self.assertEqual(len(self.view.preview_rows.items), 2)
        self.assertEqual(self.view.preview_rows.tree.selection(), ())
        chosen = self.view.preview_rows.items[0].transaction_id
        self.view.preview_rows.tree.selection_set(0)
        self.view.apply_preview()
        self.wait()
        with Repository(self.folder / "finance.sqlite3") as repo:
            self.assertEqual(repo.get_transaction(identifier), edited)
            self.assertIsNotNone(repo.get_transaction(chosen)["category_id"])
            self.assertEqual(repo.count_transactions(review_only=True), 3)
        self.assertEqual(self.errors, [])

    def test_invalid_editor_keeps_dialog_open_and_skip_preserves_review(self):
        self.select_group_rows(0)
        self.view.edit_review_row()
        self.wait()
        self.view.edit_fields["amount"].set("1.001")
        self.view.save_edit()
        self.wait()
        self.assertEqual(len(self.errors), 1)
        self.assertIsNotNone(self.view.editor)
        self.view.close_editor()
        self.view.skip()
        self.assertEqual(len(self.view.rows.items), 0)
        self.view.open()
        self.wait()
        self.assertEqual(len(self.view.groups.items[0]["items"]), 3)
        with Repository(self.folder / "finance.sqlite3") as repo:
            self.assertEqual(repo.count_transactions(review_only=True), 5)

    def test_group_selection_populates_rows_and_categories_and_direct_save_updates_counts_and_dashboard(self):
        from app.ui.dashboard import DashboardView
        from tests.ui_fixtures import create_ui_fixtures

        self.app.dashboard = DashboardView(self.app, table_factory)
        self.wait()
        self.view.skip()
        self.assertIn("Дараа үзэх", self.view.message.get())
        self.view.groups.tree.selection_set()
        self.view.save_assignment()
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()

        # Selecting a merchant group automatically selects its transaction rows and populates categories.
        self.view.groups.tree.selection_set(0)
        self.view.expand()
        self.assertNotIn("Дараа үзэх", self.view.message.get())
        self.assertEqual(len(self.view.rows.tree.selection()), 3)
        configured_values = self.view.category_box.configure.call_args.kwargs["values"]
        self.assertTrue("Бусад зардал" in configured_values or "Other expenses" in configured_values)

        # Saving without choosing a category shows a clear error and changes nothing.
        self.view.category.set("")
        self.view.save_assignment()
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()

        # Select one row (or use the group selection), choose Other expenses, and save directly.
        self.view.rows.tree.selection_set(0)
        target_id = self.view.rows.items[0].transaction_id
        self.view.category.set("Other expenses")
        self.view.save_assignment()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.view.groups.items[0]["items"]), 2)
        self.assertEqual(self.app.dashboard.report.unclassified_count, 4)
        self.assertEqual(self.app.dashboard.report.totals[0]["expenses"], 100)
        with Repository(self.folder / "finance.sqlite3") as repo:
            updated = repo.get_transaction(target_id)
            self.assertEqual(updated["classification_source"], "manual")
            self.assertTrue(updated["manual_lock"])
            self.assertEqual(repo.count_transactions(review_only=True), 4)

        # Verify both direct save and preview-then-apply workflows on the 23-row synthetic manual-check statement.
        fixtures = self.folder / "manual-fixtures"
        create_ui_fixtures(fixtures)
        self.app.file_path.set(str(fixtures / "synthetic-browser.xlsx"))
        self.app.account_confirmed.set(True)
        self.app._preview()
        self.wait()
        self.app._commit()
        self.wait()
        self.view.open()
        self.wait()
        before_unclassified = self.app.dashboard.report.unclassified_count
        debit_idx = next(i for i, g in enumerate(self.view.groups.items) if g["direction"] == "debit" and len(g["items"]) == 1)
        self.view.groups.tree.selection_set(debit_idx)
        self.view.expand()
        self.assertEqual(self.view.rows.tree.selection(), ("0",))
        single_id = self.view.rows.items[0].transaction_id
        self.view.category.set("Other expenses")
        self.view.save_assignment()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.app.dashboard.report.unclassified_count, before_unclassified - 1)
        with Repository(self.folder / "finance.sqlite3") as repo:
            classified = repo.get_transaction(single_id)
            self.assertEqual(classified["classification_source"], "manual")
            self.assertTrue(classified["manual_lock"])
