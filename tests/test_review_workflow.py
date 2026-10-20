"""Synthetic service/worker regression coverage; no real data or Tk windows."""

import unittest
from unittest.mock import patch

from app.db import Repository
from app.import_service import ImportService
from app.models import minor_to_money
from app.review_service import ReviewBlocked, ReviewService
from app.ui.worker import FinanceWorker
from tests.test_ui import temporary_case
from tests.review_fixtures import create_review_fixtures


def edit_fields(row, **changes):
    fields = {k: row[k] for k in ("occurred_at", "description", "merchant_display", "category_id", "kind", "note")}
    fields["merchant_display"] = fields["merchant_display"] or ""
    fields["amount"] = str(minor_to_money(row["amount_minor"]))
    fields.update(changes)
    return fields


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        create_review_fixtures(self.folder)
        self.database = self.folder / "review.sqlite3"
        self.repo = Repository(self.database)
        self.addCleanup(self.repo.close)
        self.account = self.repo.create_account("MN00000000000000000000", "Synthetic Khan")
        self.service = ReviewService(self.repo)
        self.importer = ImportService(self.repo)
        self.categories = {c["name"]: c["id"] for c in self.repo.list_categories()}
        self.expense = self.categories["Other expenses"]
        self.software = self.categories["Software & Digital Subscriptions"]
        self.income = self.categories["Other income"]
        self.import_file("review-initial.xlsx")
        self.group = self.service.load()["queue"].groups[0]
        self.ids = [i.transaction_id for i in self.group.items]

    def import_file(self, name):
        preview = self.importer.preview(self.folder / name, self.account)
        self.assertTrue(preview.is_valid)
        return self.importer.confirm(preview, {})

    def assign(self, ids, save_rule=False):
        preview = self.service.preview_assignment(ids, self.expense, save_rule)
        return self.service.confirm_assignment(preview["token"])

    def test_selected_only_default_and_cancel_have_no_rule_or_unselected_changes(self):
        before = tuple(self.repo._connection.iterdump())
        preview = self.service.preview_assignment(self.ids[:1], self.expense)
        self.assertIsNone(preview["scope"])
        self.assertEqual(tuple(self.repo._connection.iterdump()), before)
        self.service.cancel()
        self.assertEqual(tuple(self.repo._connection.iterdump()), before)
        self.assign(self.ids[:1])
        self.assertEqual(self.repo.list_rules(), [])
        self.assertEqual(self.repo.get_transaction(self.ids[0])["category_id"], self.expense)
        self.assertTrue(self.repo.get_transaction(self.ids[0])["manual_lock"])
        self.assertIsNone(self.repo.get_transaction(self.ids[1])["category_id"])
        queue = self.service.load()["queue"]
        self.assertEqual((len(queue.groups[0].items), len(queue.individual)), (2, 2))

    def test_rule_future_import_manual_edit_selected_retroactive_and_restart(self):
        self.assign(self.ids[:1])
        rule_id = self.assign(self.ids[1:2], True)["rule_id"]
        imported = self.import_file("review-future.xlsx")
        future = self.repo.query_transactions(import_id=imported.import_id)[0]
        self.assertEqual((future["category_id"], future["classification_source"]), (self.expense, "rule"))
        snapshot = self.service.edit_get(self.ids[0])
        before = snapshot["row"]
        fields = edit_fields(before, occurred_at="2026-10-15", amount="-2.50", description="Fictional corrected description",
                             merchant_display="Fictional corrected display", note="Synthetic correction")
        self.service.edit_save(before["id"], snapshot["revision"], fields)
        after = self.repo.get_transaction(before["id"])
        source_keys = [k for k in before if k.startswith("original_") or k in ("dedup_key", "worksheet", "row_number", "merchant_key")]
        self.assertEqual({k: before[k] for k in source_keys}, {k: after[k] for k in source_keys})
        self.assertEqual(after["amount_minor"], -250)
        self.assertGreater(len(self.repo.get_history(before["id"])), len(snapshot["history"]))
        rule = self.repo.get_rule(rule_id)
        self.service.change_rule(rule_id, rule["revision"], self.software)
        self.assertEqual(self.repo.get_transaction(future["id"])["category_id"], self.expense)
        preview = self.service.preview_rule(rule_id)
        self.assertEqual({i.transaction_id for i in preview.candidates}, {self.ids[2], future["id"]})
        self.service.apply_rule(preview.token, [self.ids[2]])
        self.assertEqual(self.repo.get_transaction(self.ids[2])["category_id"], self.software)
        self.assertEqual(self.repo.get_transaction(future["id"])["category_id"], self.expense)
        self.assertEqual(self.import_file("review-initial.xlsx").status, "identical_file")
        self.import_file("review-disabled.xlsx")
        with Repository(self.database) as reopened:
            self.assertEqual(reopened.get_transaction(before["id"]), after)
            self.assertEqual(reopened.get_rule(rule_id)["category_id"], self.software)
            self.assertEqual(reopened.count_transactions(), 7)
            self.assertEqual(len(ReviewService(reopened).load()["queue"].individual), 2)

    def test_disable_rule_changes_only_future_imports(self):
        rule_id = self.assign(self.ids[:1], True)["rule_id"]
        self.import_file("review-future.xlsx")
        before = self.repo.query_transactions()
        rule = self.repo.get_rule(rule_id)
        self.service.change_rule(rule_id, rule["revision"], disable=True)
        self.assertEqual(self.repo.query_transactions(), before)
        imported = self.import_file("review-disabled.xlsx")
        self.assertIsNone(self.repo.query_transactions(import_id=imported.import_id)[0]["category_id"])
        self.assertFalse(self.service.load()["rules"][0]["active"])

    def test_missing_merchant_cannot_save_rule_but_can_assign_category(self):
        item = next(i for i in self.service.load()["queue"].individual if i.direction == "debit")
        with self.assertRaises(ReviewBlocked):
            self.service.preview_assignment([item.transaction_id], self.expense, True)
        self.assign([item.transaction_id])
        self.assertTrue(self.repo.get_transaction(item.transaction_id)["manual_lock"])
        self.assertEqual(self.repo.list_rules(), [])

    def test_incompatible_assignment_and_zero_selection_rejected_without_writes(self):
        before = tuple(self.repo._connection.iterdump())
        for ids, category in (([], self.expense), (self.ids, self.income), ([self.ids[0]] * 2, self.expense)):
            with self.assertRaises(ReviewBlocked):
                self.service.preview_assignment(ids, category)
        self.assertEqual(tuple(self.repo._connection.iterdump()), before)

    def test_stale_assignment_rejected_and_rule_save_failure_rolls_back_both(self):
        preview = self.service.preview_assignment(self.ids[:1], self.expense, True)
        self.repo.edit_transaction(self.ids[0], reason="Synthetic competing edit", note="changed")
        with self.assertRaises(ReviewBlocked):
            self.service.confirm_assignment(preview["token"])
        self.service.cancel()
        preview = self.service.preview_assignment(self.ids[1:2], self.expense, True)
        before = tuple(self.repo._connection.iterdump())
        save = self.service.classification.save_rule
        def fail_after_write(*args):
            save(*args)
            raise RuntimeError("synthetic injected failure")
        with patch.object(self.service.classification, "save_rule", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                self.service.confirm_assignment(preview["token"])
        self.assertEqual(tuple(self.repo._connection.iterdump()), before)

    def test_stale_rule_prevents_assignment_overwriting_new_rule(self):
        preview = self.service.preview_assignment(self.ids[:1], self.expense, True)
        self.service.classification.save_rule(self.group.bank, self.group.merchant_key, "debit", self.software)
        with self.assertRaises(ReviewBlocked):
            self.service.confirm_assignment(preview["token"])
        self.assertIsNone(self.repo.get_transaction(self.ids[0])["category_id"])

    def test_edit_validation_and_explicit_unclassified_direction_change(self):
        self.assign(self.ids[:1])
        snap = self.service.edit_get(self.ids[0])
        for change in ({"occurred_at": "2026-02-30"}, {"amount": "1.001"}, {"amount": "2.00"},
                       {"kind": "transfer"}, {"category_id": None}, {"kind": "income", "category_id": self.expense}):
            with self.subTest(change=change), self.assertRaises(ReviewBlocked):
                self.service.edit_save(self.ids[0], snap["revision"], edit_fields(snap["row"], **change))
            self.assertEqual(self.repo.get_transaction(self.ids[0]), snap["row"])
        self.service.edit_save(self.ids[0], snap["revision"],
                               edit_fields(snap["row"], amount="2.00", kind="unclassified", category_id=None))
        row = self.repo.get_transaction(self.ids[0])
        self.assertEqual((row["amount_minor"], row["original_amount_minor"]), (200, -100))
        self.assertTrue(row["manual_lock"])

    def test_stale_editor_and_source_field_injection_rejected(self):
        snap = self.service.edit_get(self.ids[0])
        with self.assertRaises(ReviewBlocked):
            self.service.edit_save(self.ids[0], snap["revision"], {**edit_fields(snap["row"]), "dedup_key": "invented"})
        self.repo.edit_transaction(self.ids[0], reason="Synthetic concurrent edit", note="changed")
        with self.assertRaises(ReviewBlocked):
            self.service.edit_save(self.ids[0], snap["revision"], edit_fields(snap["row"]))

    def test_unlock_requires_explicit_choice_and_does_not_apply_rule(self):
        rule_id = self.assign(self.ids[:1], True)["rule_id"]
        snap = self.service.edit_get(self.ids[0])
        self.service.edit_save(self.ids[0], snap["revision"], edit_fields(snap["row"]), clear_protection=True)
        row = self.repo.get_transaction(self.ids[0])
        self.assertFalse(row["manual_lock"])
        self.assertEqual(row["classification_source"], "manual")
        preview = self.service.preview_rule(rule_id)
        self.assertIn(self.ids[0], {i.transaction_id for i in preview.candidates})
        with self.assertRaises(ReviewBlocked):
            self.service.apply_rule(preview.token, [])
        self.service.cancel()
        self.assertEqual(self.repo.get_transaction(self.ids[0]), row)


class ReviewWorkerTests(unittest.TestCase):
    def test_worker_review_preview_commit_edit_and_import_conflict(self):
        folder = temporary_case(self)
        create_review_fixtures(folder)
        worker = FinanceWorker(folder / "worker.sqlite3")
        def stop():
            worker.stop()
            worker.thread.join(5)
            self.assertFalse(worker.thread.is_alive())
        self.addCleanup(stop)
        ready = worker.events.get(timeout=5)
        expense = next(c["id"] for c in ready.payload["categories"] if c["name"] == "Other expenses")
        def ask(op, **kw):
            worker.submit(op, **kw)
            event = worker.events.get(timeout=5)
            self.assertEqual(event.operation, op)
            return event
        account = ask("account", name="Synthetic", identifier="MN00000000000000000000").payload["selected"]
        path = folder / "review-initial.xlsx"
        ask("preview", path=path, account_id=account)
        self.assertIsNotNone(ask("review_preview", transaction_ids=[1], category_id=expense).error)
        self.assertIsNone(ask("commit").error)
        queue = ask("review_load").payload["queue"]
        identifier = queue.groups[0].items[0].transaction_id
        preview = ask("review_preview", transaction_ids=[identifier], category_id=expense, save_rule=True)
        self.assertIsNone(preview.error)
        self.assertIsNotNone(ask("preview", path=path, account_id=account).error)
        self.assertIsNone(ask("review_apply", token=preview.payload["token"]).error)
        snap = ask("edit_get", transaction_id=identifier).payload
        self.assertIsNone(ask("edit_save", transaction_id=identifier, revision=snap["revision"],
                              fields=edit_fields(snap["row"], note="Synthetic worker correction")).error)
        self.assertEqual(ask("browse").payload["total"], 5)
        self.assertTrue(ask("edit_get", transaction_id=identifier).payload["row"]["manual_lock"])
