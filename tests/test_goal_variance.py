"""Focused synthetic tests for Budget vs Actual variance analysis and Long-Term Goal Tracker."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.db import Repository
from app.budget_service import BudgetService
from app.goal_service import GoalService, GoalParameters
from app.models import ImportInfo, ImportRow


class VarianceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
        self.addCleanup(self.repo.close)
        self.budget_service = BudgetService(self.repo)

        # Create categories
        self.cat_food = self.repo.create_category("Хоол хүнс", "expense")
        self.cat_rent = self.repo.create_category("Түрээс, дотуур байр", "expense")
        self.cat_salary = self.repo.create_category("Цалин, ажил эрхлэлт", "income")

        # Create account & import
        self.acc_id = self.repo.create_account("MNT-01", "Checking", bank="Khan", currency="MNT")
        imp_id = self.repo.write_import(
            ImportInfo(account_id=self.acc_id, sha256="a" * 64, parser_version="1.0", filename="oct.xlsx"),
            [
                # Food: 450,000 MNT spent
                ImportRow(description="Food 1", bank_datetime="2026-10-05 12:00:00",
                          occurred_at="2026-10-05", amount_minor=-45000000, worksheet="Sheet1", row_number=1),
                # Rent: 800,000 MNT spent
                ImportRow(description="Rent", bank_datetime="2026-10-10 12:00:00",
                          occurred_at="2026-10-10", amount_minor=-80000000, worksheet="Sheet1", row_number=2),
                # Salary: 2,500,000 MNT received
                ImportRow(description="Salary", bank_datetime="2026-10-25 12:00:00",
                          occurred_at="2026-10-25", amount_minor=250000000, worksheet="Sheet1", row_number=3),
            ]
        )

        # Categorize transactions
        txs = self.repo.query_transactions(import_id=imp_id)
        for t in txs:
            if "Food" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_food, reason="test")
            elif "Rent" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_rent, reason="test")
            elif "Salary" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_salary, reason="test")

    def test_variance_under_budget_and_over_budget(self):
        # Budget Food: 500,000 MNT (Spent 450,000 -> Under budget by 50,000)
        self.budget_service.save_budget(
            month="2026-10", currency="MNT", category_id=self.cat_food, planned_amount_minor=50000000
        )
        # Budget Rent: 700,000 MNT (Spent 800,000 -> Over budget by 100,000)
        self.budget_service.save_budget(
            month="2026-10", currency="MNT", category_id=self.cat_rent, planned_amount_minor=70000000
        )
        # Budget Salary: 2,000,000 MNT (Received 2,500,000 -> Target met by +500,000)
        self.budget_service.save_budget(
            month="2026-10", currency="MNT", category_id=self.cat_salary, planned_amount_minor=200000000
        )

        analysis = self.budget_service.variance_analysis("2026-10", currency="MNT")
        self.assertIn("items", analysis)
        self.assertIn("totals", analysis)

        items_by_cat = {item["category_id"]: item for item in analysis["items"]}

        # Food checks
        food = items_by_cat[self.cat_food]
        self.assertEqual(food["planned_minor"], 50000000)
        self.assertEqual(food["actual_minor"], 45000000)
        self.assertEqual(food["variance_minor"], 5000000)  # +50,000 MNT saved
        self.assertEqual(food["status"], "under_budget")
        self.assertEqual(food["utilization_pct"], 90.0)

        # Rent checks
        rent = items_by_cat[self.cat_rent]
        self.assertEqual(rent["planned_minor"], 70000000)
        self.assertEqual(rent["actual_minor"], 80000000)
        self.assertEqual(rent["variance_minor"], -10000000)  # -100,000 MNT over
        self.assertEqual(rent["status"], "over_budget")
        self.assertEqual(rent["utilization_pct"], 114.3)

        # Salary checks
        salary = items_by_cat[self.cat_salary]
        self.assertEqual(salary["planned_minor"], 200000000)
        self.assertEqual(salary["actual_minor"], 250000000)
        self.assertEqual(salary["variance_minor"], 50000000)  # +500,000 MNT exceeded
        self.assertEqual(salary["status"], "target_met")
        self.assertEqual(salary["utilization_pct"], 125.0)

        # Totals checks
        totals = analysis["totals"]["MNT"]
        self.assertEqual(totals["expense_budget"], 120000000)  # 500k + 700k
        self.assertEqual(totals["expense_actual"], 125000000)  # 450k + 800k
        self.assertEqual(totals["expense_variance"], -5000000)  # -50k over total budget
        self.assertEqual(totals["income_budget"], 200000000)
        self.assertEqual(totals["income_actual"], 250000000)
        self.assertEqual(totals["net_budget"], 80000000)      # 2.0M - 1.2M = 800k
        self.assertEqual(totals["net_actual"], 125000000)     # 2.5M - 1.25M = 1.25M
        self.assertEqual(totals["net_variance"], 45000000)    # +450k net surplus


class LongTermGoalTrackerTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
        self.addCleanup(self.repo.close)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.service = GoalService(self.repo, self.data_dir)

        # Create categories
        self.cat_salary = self.repo.create_category("Цалин, ажил эрхлэлт", "income")
        self.cat_living = self.repo.create_category("Хоол хүнс", "expense")
        self.cat_debt = self.repo.create_category("Өр төлөлт", "expense")
        self.cat_savings = self.repo.create_category("Хуримтлал", "expense")

        # Create account
        self.acc_id = self.repo.create_account("MNT-GOAL", "Savings", bank="Khan", currency="MNT")

    def _add_month_data(self, month: str, salary_minor: int, living_minor: int,
                         debt_minor: int = 0, explicit_savings_minor: int = 0):
        rows = [
            ImportRow(description="Salary", bank_datetime=f"{month}-01 10:00:00",
                      occurred_at=f"{month}-01", amount_minor=salary_minor, worksheet="S", row_number=1),
            ImportRow(description="Living", bank_datetime=f"{month}-05 10:00:00",
                      occurred_at=f"{month}-05", amount_minor=-living_minor, worksheet="S", row_number=2),
        ]
        if debt_minor > 0:
            rows.append(ImportRow(description="Debt", bank_datetime=f"{month}-10 10:00:00",
                                  occurred_at=f"{month}-10", amount_minor=-debt_minor, worksheet="S", row_number=3))
        if explicit_savings_minor > 0:
            rows.append(ImportRow(description="Deposit", bank_datetime=f"{month}-15 10:00:00",
                                  occurred_at=f"{month}-15", amount_minor=-explicit_savings_minor, worksheet="S", row_number=4))

        sha = hashlib.sha256(f"{month}-{salary_minor}-{living_minor}".encode()).hexdigest()
        imp_id = self.repo.write_import(
            ImportInfo(account_id=self.acc_id, sha256=sha, parser_version="1.0", filename=f"{month}.xlsx"),
            rows,
        )
        for t in self.repo.query_transactions(import_id=imp_id):
            if "Salary" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_salary, reason="test")
            elif "Living" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_living, reason="test")
            elif "Debt" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_debt, reason="test")
            elif "Deposit" in t["description"]:
                self.repo.assign_category(t["id"], self.cat_savings, reason="test")

    def test_apartment_goal_timeline_and_dti_calculation(self):
        # Month 1: Income 4,000,000, Living 2,000,000, Debt 600,000 (DTI = 600k/4M = 15%, Savings = 1,400,000)
        self._add_month_data("2026-09", 400000000, 200000000, 60000000)
        # Month 2: Income 4,000,000, Living 2,000,000, Debt 600,000
        self._add_month_data("2026-10", 400000000, 200000000, 60000000)

        # Target Apartment: 200,000,000 MNT, 30% Down Payment = 60,000,000 MNT
        params = GoalParameters(
            apartment_price_minor=200_000_000_00,
            down_payment_pct=30,
            initial_savings_minor=10_000_000_00,  # 10M already saved
            currency="MNT",
        )
        res = self.service.calculate_apartment_goal(params=params)

        # Verify targets
        self.assertEqual(res["apartment_price_minor"], 200_000_000_00)
        self.assertEqual(res["down_payment_target_minor"], 60_000_000_00)
        # Net savings over 2 months: (4M - 2.6M) * 2 = 2.8M. Total accumulated = 10M + 2.8M = 12.8M
        self.assertEqual(res["total_accumulated_savings_minor"], 12_800_000_00)
        self.assertEqual(res["remaining_down_payment_minor"], 47_200_000_00)

        # Monthly averages
        self.assertEqual(res["avg_monthly_income_minor"], 400000000)
        self.assertEqual(res["effective_monthly_savings_minor"], 140000000)  # 1,400,000 MNT/month

        # Savings rate: (1.4M / 4.0M) * 100 = 35.0%
        self.assertEqual(res["savings_rate_pct"], 35.0)
        self.assertEqual(res["savings_grade"], "excellent")

        # DTI: (600k / 4.0M) * 100 = 15.0%
        self.assertEqual(res["dti_pct"], 15.0)
        self.assertEqual(res["dti_status"], "prime")
        self.assertEqual(res["dti_label"], "Ипотект тэнцэх өндөр боломжтой")

        # Timeline: 47,200,000 / 1,400,000 = 33.71 -> 34 months (2 years 10 months)
        self.assertEqual(res["months_needed"], 34)
        self.assertIn("2 жил 10 сар", res["timeline_text"])

    def test_high_debt_burden_warning(self):
        # Income 3,000,000 MNT, Debt payments 1,800,000 MNT (DTI = 60% > 50%)
        self._add_month_data("2026-10", 300000000, 100000000, 180000000)
        res = self.service.calculate_apartment_goal()

        self.assertEqual(res["dti_pct"], 60.0)
        self.assertEqual(res["dti_status"], "high_burden")
        self.assertEqual(res["dti_label"], "Өрийн дарамт өндөр")
        self.assertIn("Өр орлогын харьцаа 50%-иас давсан", res["dti_advice"])

    def test_save_and_load_parameters(self):
        self.service.update_parameters(
            apartment_price_minor=250_000_000_00,
            down_payment_pct=25,
            initial_savings_minor=30_000_000_00,
            target_monthly_savings_minor=2_000_000_00,
            currency="MNT",
        )
        loaded = self.service.get_parameters()
        self.assertEqual(loaded.apartment_price_minor, 250_000_000_00)
        self.assertEqual(loaded.down_payment_pct, 25)
        self.assertEqual(loaded.initial_savings_minor, 30_000_000_00)
        self.assertEqual(loaded.target_monthly_savings_minor, 2_000_000_00)


class WorkerGoalVarianceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.folder = Path(self.temp_dir.name)
        from app.ui.worker import FinanceWorker
        self.worker = FinanceWorker(self.folder / "finance.sqlite3")
        self.addCleanup(self.worker.stop)

    def wait_event(self, op: str):
        import time
        start = time.time()
        while time.time() - start < 5.0:
            if not self.worker.events.empty():
                evt = self.worker.events.get_nowait()
                if evt.operation == op:
                    return evt
            time.sleep(0.02)
        self.fail(f"Timed out waiting for event {op}")

    def test_worker_goal_and_variance_operations(self):
        # Wait for ready event
        self.wait_event("ready")

        # Submit goal_analysis
        self.worker.submit("goal_analysis", currency="MNT")
        evt_goal = self.wait_event("goal_analysis")
        self.assertIsNone(evt_goal.error)
        self.assertEqual(evt_goal.payload["currency"], "MNT")
        self.assertIn("timeline_text", evt_goal.payload)

        # Submit budget_variance
        self.worker.submit("budget_variance", month="2026-10", currency="MNT")
        evt_var = self.wait_event("budget_variance")
        self.assertIsNone(evt_var.error)
        self.assertEqual(evt_var.payload["month"], "2026-10")
        self.assertIn("items", evt_var.payload)


if __name__ == "__main__":
    unittest.main()
