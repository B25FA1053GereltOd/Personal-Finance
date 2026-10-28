"""Focused synthetic unit and integration tests for monthly budget management."""

import unittest
from datetime import datetime

from app.db import Repository
from app.budget_service import BudgetBlocked, BudgetService
from app.models import validate_month, money_to_minor
from app.ui.worker import FinanceWorker
from tests.test_ui import temporary_case


class BudgetDatabaseTests(unittest.TestCase):
    """Test Repository budget schema, CRUD, constraints, and category protections."""

    def setUp(self):
        self.repo = Repository(":memory:")
        self.addCleanup(self.repo.close)
        # Create test categories
        self.food_cat = self.repo.create_category("Хоол хүнс", "expense")
        self.salary_cat = self.repo.create_category("Цалин, ажил эрхлэлт", "income")

    def test_create_valid_budget(self):
        b_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=60000000,
            note="Monthly food",
            active=True,
        )
        self.assertIsInstance(b_id, int)
        budget = self.repo.get_budget(b_id)
        self.assertIsNotNone(budget)
        self.assertEqual(budget["month"], "2026-10")
        self.assertEqual(budget["currency"], "MNT")
        self.assertEqual(budget["category_id"], self.food_cat)
        self.assertEqual(budget["category_name"], "Хоол хүнс")
        self.assertEqual(budget["category_direction"], "expense")
        self.assertEqual(budget["planned_amount_minor"], 60000000)
        self.assertEqual(budget["note"], "Monthly food")
        self.assertEqual(budget["active"], 1)

    def test_month_format_validation(self):
        self.assertEqual(validate_month("2026-10"), "2026-10")
        self.assertEqual(validate_month("2025-01"), "2025-01")
        self.assertEqual(validate_month("2030-12"), "2030-12")

        invalid_months = ["2026/10", "2026-13", "2026-00", "26-10", "2026-1", "invalid", "", 123]
        for inv in invalid_months:
            with self.subTest(month=inv):
                with self.assertRaises(ValueError):
                    self.repo.create_budget(
                        month=inv,
                        currency="MNT",
                        category_id=self.food_cat,
                        planned_amount_minor=100000,
                    )

    def test_amount_must_be_positive(self):
        # 0 or negative must be rejected
        for amount in (0, -1, -50000):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.repo.create_budget(
                        month="2026-10",
                        currency="MNT",
                        category_id=self.food_cat,
                        planned_amount_minor=amount,
                    )

    def test_currency_must_be_valid(self):
        for curr in ("", "mnt", "MNT1", "US", "TOOLONG"):
            with self.subTest(curr=curr):
                with self.assertRaises(ValueError):
                    self.repo.create_budget(
                        month="2026-10",
                        currency=curr,
                        category_id=self.food_cat,
                        planned_amount_minor=100000,
                    )

    def test_category_must_exist_and_match_income_or_expense(self):
        # Nonexistent category
        with self.assertRaises(ValueError):
            self.repo.create_budget(
                month="2026-10",
                currency="MNT",
                category_id=99999,
                planned_amount_minor=100000,
            )

    def test_duplicate_budget_prevention(self):
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=100000,
        )
        # Same month, currency, category must raise duplicate error
        with self.assertRaises(ValueError) as ctx:
            self.repo.create_budget(
                month="2026-10",
                currency="MNT",
                category_id=self.food_cat,
                planned_amount_minor=200000,
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_currency_separation_allows_same_category_different_currencies(self):
        # Same month and category, different currencies
        b_mnt = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
        )
        b_usd = self.repo.create_budget(
            month="2026-10",
            currency="USD",
            category_id=self.food_cat,
            planned_amount_minor=20000,
        )
        self.assertNotEqual(b_mnt, b_usd)

        mnt_budgets = self.repo.list_budgets(month="2026-10", currency="MNT")
        usd_budgets = self.repo.list_budgets(month="2026-10", currency="USD")
        self.assertEqual(len(mnt_budgets), 1)
        self.assertEqual(len(usd_budgets), 1)
        self.assertEqual(mnt_budgets[0]["planned_amount_minor"], 50000000)
        self.assertEqual(usd_budgets[0]["planned_amount_minor"], 20000)

    def test_update_budget(self):
        b_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            note="Initial",
        )
        self.repo.update_budget(
            b_id,
            planned_amount_minor=65000000,
            note="Updated note",
            active=False,
        )
        updated = self.repo.get_budget(b_id)
        self.assertEqual(updated["planned_amount_minor"], 65000000)
        self.assertEqual(updated["note"], "Updated note")
        self.assertEqual(updated["active"], 0)

    def test_toggle_active_status(self):
        b_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            active=True,
        )
        self.repo.set_budget_active(b_id, False)
        self.assertEqual(self.repo.get_budget(b_id)["active"], 0)
        self.repo.set_budget_active(b_id, True)
        self.assertEqual(self.repo.get_budget(b_id)["active"], 1)

    def test_delete_budget(self):
        b_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
        )
        self.repo.delete_budget(b_id)
        self.assertIsNone(self.repo.get_budget(b_id))
        # After deletion, can recreate with same tuple
        recreated_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=60000000,
        )
        self.assertIsNotNone(recreated_id)

    def test_category_used_in_budget_cannot_be_deleted(self):
        unused_cat = self.repo.create_category("Ном, бичиг хэрэг", "expense")
        self.assertFalse(self.repo.is_category_used(unused_cat))
        self.repo.delete_category(unused_cat)

        b_id = self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
        )
        self.assertTrue(self.repo.is_category_used(self.food_cat))
        with self.assertRaises(ValueError) as ctx:
            self.repo.delete_category(self.food_cat)
        self.assertIn("already used", str(ctx.exception))

        # After deleting the budget, category can be deleted
        self.repo.delete_budget(b_id)
        self.assertFalse(self.repo.is_category_used(self.food_cat))
        self.repo.delete_category(self.food_cat)

    def test_list_budgets_filtering(self):
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            active=True,
        )
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.salary_cat,
            planned_amount_minor=200000000,
            active=False,
        )
        self.repo.create_budget(
            month="2026-11",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=55000000,
            active=True,
        )

        # By month
        oct_budgets = self.repo.list_budgets(month="2026-10")
        self.assertEqual(len(oct_budgets), 2)

        # By direction
        exp_budgets = self.repo.list_budgets(month="2026-10", direction="expense")
        self.assertEqual(len(exp_budgets), 1)
        self.assertEqual(exp_budgets[0]["category_id"], self.food_cat)

        inc_budgets = self.repo.list_budgets(month="2026-10", direction="income")
        self.assertEqual(len(inc_budgets), 1)
        self.assertEqual(inc_budgets[0]["category_id"], self.salary_cat)

        # By active
        active_budgets = self.repo.list_budgets(month="2026-10", active=True)
        self.assertEqual(len(active_budgets), 1)
        self.assertEqual(active_budgets[0]["category_id"], self.food_cat)

    def test_budget_summary(self):
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            active=True,
        )
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.salary_cat,
            planned_amount_minor=200000000,
            active=True,
        )
        self.repo.create_budget(
            month="2026-10",
            currency="USD",
            category_id=self.food_cat,
            planned_amount_minor=30000,
            active=True,
        )
        # Inactive budget should not be summed
        inactive_cat = self.repo.create_category("Кофе, амттан", "expense")
        self.repo.create_budget(
            month="2026-10",
            currency="MNT",
            category_id=inactive_cat,
            planned_amount_minor=10000000,
            active=False,
        )

        summary = self.repo.budget_summary("2026-10")
        self.assertIn("MNT", summary)
        self.assertIn("USD", summary)
        self.assertEqual(summary["MNT"]["planned_expense"], 50000000)
        self.assertEqual(summary["MNT"]["planned_income"], 200000000)
        self.assertEqual(summary["USD"]["planned_expense"], 30000)
        self.assertEqual(summary["USD"]["planned_income"], 0)


class BudgetServiceTests(unittest.TestCase):
    """Test BudgetService domain validation and BudgetBlocked exceptions."""

    def setUp(self):
        self.repo = Repository(":memory:")
        self.addCleanup(self.repo.close)
        self.service = BudgetService(self.repo)
        self.food_cat = self.repo.create_category("Хоол хүнс", "expense")

    def test_service_save_valid(self):
        res = self.service.save_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            note="Service test",
        )
        self.assertIn("budget", res)
        self.assertEqual(res["budget"]["month"], "2026-10")

    def test_service_save_invalid_raises_budget_blocked(self):
        # Invalid month
        with self.assertRaises(BudgetBlocked):
            self.service.save_budget(
                month="bad-month",
                currency="MNT",
                category_id=self.food_cat,
                planned_amount_minor=10000,
            )

        # Invalid amount
        with self.assertRaises(BudgetBlocked):
            self.service.save_budget(
                month="2026-10",
                currency="MNT",
                category_id=self.food_cat,
                planned_amount_minor=-1000,
            )

        # Duplicate
        self.service.save_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000,
        )
        with self.assertRaises(BudgetBlocked):
            self.service.save_budget(
                month="2026-10",
                currency="MNT",
                category_id=self.food_cat,
                planned_amount_minor=70000,
            )

    def test_service_toggle_and_delete(self):
        res = self.service.save_budget(
            month="2026-10",
            currency="MNT",
            category_id=self.food_cat,
            planned_amount_minor=50000000,
            active=True,
        )
        b_id = res["budget"]["id"]
        toggled = self.service.toggle_active(b_id)
        self.assertFalse(toggled["budget"]["active"])

        self.service.delete_budget(b_id)
        self.assertIsNone(self.service.get_budget(b_id))


class BudgetWorkerIntegrationTests(unittest.TestCase):
    """Test worker queue operations for budget management."""

    def setUp(self):
        self.folder = temporary_case(self)
        self.worker = FinanceWorker(self.folder / "finance.sqlite3")
        self.addCleanup(self.worker.stop)
        # Wait for ready event
        event = self.worker.events.get(timeout=5)
        self.assertEqual(event.operation, "ready")

    def test_worker_budget_flow(self):
        # 1. Create a category
        self.worker.submit("category_add", name="Хоол хүнс", direction="expense")
        cat_ev = self.worker.events.get(timeout=5)
        self.assertEqual(cat_ev.operation, "category_add")
        cats = cat_ev.payload["categories"]
        food_id = next(c["id"] for c in cats if c["name"] == "Хоол хүнс")

        # 2. Save a budget
        self.worker.submit(
            "budget_save",
            month="2026-10",
            currency="MNT",
            category_id=food_id,
            planned_amount_minor=50000000,
            note="Worker budget test",
            active=True,
        )
        save_ev = self.worker.events.get(timeout=5)
        self.assertEqual(save_ev.operation, "budget_save")
        self.assertIsNone(save_ev.error)
        b_id = save_ev.payload["budget"]["id"]

        # 3. List budgets
        self.worker.submit("budget_list", month="2026-10")
        list_ev = self.worker.events.get(timeout=5)
        self.assertEqual(list_ev.operation, "budget_list")
        budgets = list_ev.payload["budgets"]
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0]["id"], b_id)

        # 4. Toggle active
        self.worker.submit("budget_active", budget_id=b_id)
        act_ev = self.worker.events.get(timeout=5)
        self.assertEqual(act_ev.operation, "budget_active")
        self.assertFalse(act_ev.payload["budget"]["active"])

        # 5. Delete budget
        self.worker.submit("budget_delete", budget_id=b_id)
        del_ev = self.worker.events.get(timeout=5)
        self.assertEqual(del_ev.operation, "budget_delete")

        # 6. Verify list empty
        self.worker.submit("budget_list", month="2026-10")
        empty_ev = self.worker.events.get(timeout=5)
        self.assertEqual(len(empty_ev.payload["budgets"]), 0)


class BudgetHelperAndUITests(unittest.TestCase):
    """Test month shift helper and budget translations."""

    def test_shift_month(self):
        from app.ui.budget import shift_month
        self.assertEqual(shift_month("2026-10", 1), "2026-11")
        self.assertEqual(shift_month("2026-10", -1), "2026-09")
        self.assertEqual(shift_month("2026-12", 1), "2027-01")
        self.assertEqual(shift_month("2026-01", -1), "2025-12")
        self.assertEqual(shift_month("2026-05", 12), "2027-05")
        # invalid string falls back to current month format YYYY-MM
        fallback = shift_month("invalid", 0)
        self.assertEqual(len(fallback), 7)
        self.assertEqual(fallback[4], "-")

    def test_budget_translations(self):
        from app.ui.i18n import translate
        self.assertEqual(translate("Budget", "mn"), "Төсөв")
        self.assertEqual(translate("Төсөв", "en"), "Budget")
        self.assertEqual(translate("Monthly Budget", "mn"), "Сарын төсөв")
        self.assertEqual(translate("Planned Amount", "mn"), "Төлөвлөсөн дүн")
        self.assertEqual(translate("Planned Expense", "mn"), "Төлөвлөсөн зардал")
        self.assertEqual(translate("Planned Income", "mn"), "Төлөвлөсөн орлого")
        self.assertEqual(translate("Add budget", "mn"), "Төсөв нэмэх")
        self.assertEqual(translate("Edit budget", "mn"), "Төсөв засах")
        self.assertEqual(translate("Delete budget", "mn"), "Төсөв устгах")
        self.assertEqual(translate("This month", "mn"), "Энэ сар")


if __name__ == "__main__":
    unittest.main()
