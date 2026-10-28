"""Real controller/queue/service flows with in-memory widget stand-ins, no Tk."""

import time
import unittest
from unittest.mock import Mock, patch

from app.db import Repository
from app.ui.desktop import DesktopApp, PagedTable
from tests.test_ui import FIXTURE, temporary_case


class Value:
    def __init__(self, master=None, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Control:
    def __init__(self):
        self.disabled = False
        self.index = 0

    def state(self, values):
        self.disabled = "disabled" in values

    def configure(self, **kwargs):
        pass

    def current(self, index=None):
        if index is not None:
            self.index = index
        return self.index


class Tree:
    def __init__(self):
        self.rows = {}

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            del self.rows[item]

    def insert(self, parent, position, *, iid, values):
        self.rows[iid] = values

    def selection(self):
        return ()


def build_views(app, data_dir):
    # Exercise actual PagedTable rendering and DesktopApp callbacks without Tk.
    for name in ("account_box", "add_account_button", "choose_button", "confirm_account",
                 "preview_button", "cancel_button", "commit_button", "review_button",
                 "category_box", "direction_box", "size_box", "browser_previous", "browser_next"):
        setattr(app, name, Control())
    app.filter_widgets, app.decision_buttons = [], []
    app.progress, app.tabs, app.preview_tabs = Mock(), Mock(), Mock()
    app.transactions_tab = object()
    for name in ("preview_table", "candidates", "issues", "transactions"):
        table = PagedTable.__new__(PagedTable)
        table.size, table.page, table.items, table.values = 50, 0, (), lambda row: row
        table.tree = Tree()
        table.previous, table.next, table.caption = Control(), Control(), Control()
        setattr(app, name, table)


class ControllerImportFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        self.errors = []
        for target, replacement in (("app.ui.desktop.tk.StringVar", Value),
                                    ("app.ui.desktop.tk.BooleanVar", Value),
                                    ("app.ui.desktop.DesktopApp._build", build_views)):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("app.ui.desktop.messagebox.showerror",
                        side_effect=lambda title, message, **kw: self.errors.append(message))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = DesktopApp(Mock(), self.folder)
        self.addCleanup(self.stop_worker)
        self.wait_idle()
        self.app._request("account", name="Synthetic Khan", identifier="MN00000000000000000000")
        self.wait_idle()

    def stop_worker(self):
        self.app.worker.stop()
        self.app.worker.thread.join(5)
        self.assertFalse(self.app.worker.thread.is_alive())

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app._poll()
            if self.app.ready and not self.app.busy:
                return
            time.sleep(.005)
        self.fail("Synthetic controller flow did not finish")

    def preview(self):
        self.app.file_path.set(str(FIXTURE))
        self.app.account_confirmed.set(True)
        self.app._preview()
        self.wait_idle()

    def test_preview_cancel_preview_commit_lists_three_and_persists(self):
        self.preview()
        self.assertEqual(self.app.preview.valid_count, 3)
        self.app._cancel()
        self.wait_idle()
        self.app._apply_filters()
        self.wait_idle()
        self.assertEqual(self.app.browser_total, 0)
        self.preview()
        self.assertFalse(self.app.commit_button.disabled)
        self.app._commit()
        self.wait_idle()
        self.assertIn("Нэмсэн: 3", self.app.summary.get())
        self.assertEqual(self.app.browser_total, 3)
        self.assertEqual(len(self.app.transactions.tree.rows), 3)
        self.app.tabs.select.assert_called_with(self.app.transactions_tab)
        self.stop_worker()
        with Repository(self.folder / "finance.sqlite3") as repo:
            self.assertEqual(repo.count_transactions(), 3)
        self.assertEqual(self.errors, [])

    def test_statement_account_error_is_visible_despite_valid_rows_then_clears(self):
        self.app._request("account", name="Different synthetic account", identifier="FICTIONAL-WRONG")
        self.wait_idle()
        self.preview()
        self.assertEqual((self.app.preview.valid_count, self.app.preview.invalid_count), (3, 0))
        self.assertFalse(self.app.preview.is_valid)
        self.assertTrue(self.app.commit_button.disabled)
        self.assertIn("Блоклосон алдаа: 1", self.app.preview_counts.get())
        self.assertIn("сонгосон данстай", self.app.summary.get())
        self.app._commit()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.browser_total, 0)
        self.app._cancel()
        self.wait_idle()
        self.app.account_box.current(0)
        self.preview()
        self.assertTrue(self.app.preview.is_valid)
        self.assertFalse(self.app.commit_button.disabled)
        self.assertEqual(self.app.summary.get(), "")
        self.assertNotIn("хориглогдлоо", self.app.status.get().lower())
        self.assertEqual(len(self.app.issues.tree.rows), 0)
        self.app._commit()
        self.wait_idle()
        self.assertEqual(self.app.browser_total, 3)
        self.assertEqual(self.errors, [])

    def test_success_refresh_clears_filters_that_would_hide_new_rows(self):
        self.app.search.set("FICTIONAL UNMATCHED SEARCH")
        self.app.date_from.set("2099-01-01")
        self.app.direction_text.set("Debit")
        self.app.review_only.set(True)
        self.app._apply_filters()
        self.wait_idle()
        self.assertEqual(self.app.browser_total, 0)
        self.preview()
        self.app._commit()
        self.wait_idle()
        self.assertEqual(self.app.search.get(), "")
        self.assertEqual(self.app.date_from.get(), "")
        self.assertEqual(self.app.direction_text.get(), "Бүх чиглэл")
        self.assertFalse(self.app.review_only.get())
        self.assertEqual(self.app.browser_total, 3)
        self.assertEqual(len(self.app.transactions.tree.rows), 3)
        self.assertEqual(self.errors, [])

    def test_show_unclassified_action_applies_filter_and_opens_transaction_list(self):
        self.preview()
        self.app._commit()
        self.wait_idle()
        with Repository(self.folder / "finance.sqlite3") as repo:
            row = next(r for r in repo.query_transactions() if r["amount_minor"] < 0)
            expense = next(c["id"] for c in repo.list_categories() if c["name"] == "Other expenses")
            repo.assign_category(row["id"], expense, reason="Synthetic reviewed transaction")

        self.app.search.set("stale search")
        self.app.date_from.set("2099-01-01")
        self.app._review_unknown()
        self.wait_idle()

        self.assertTrue(self.app.review_only.get())
        self.assertEqual(self.app.search.get(), "")
        self.assertEqual(self.app.date_from.get(), "")
        self.assertTrue(self.app.active_filters["review_only"])
        self.assertEqual(self.app.browser_total, 2)
        self.assertEqual(len(self.app.transactions.tree.rows), 2)
        self.app.tabs.select.assert_called_with(self.app.transactions_tab)
        self.assertEqual(self.errors, [])
