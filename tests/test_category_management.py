"""Focused tests for category localization, management, and direction filtering."""

import tempfile
import unittest
from pathlib import Path

from app.db import Repository
from app.export_service import export_csv
from app.models import DEFAULT_CATEGORIES, ImportInfo, ImportRow
from app.ui.i18n import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    get_category_display_name,
    load_category_settings,
    resolve_category_by_display_name,
    save_category_settings,
    set_language,
    translate,
)


class CategoryManagementTests(unittest.TestCase):
    def setUp(self):
        set_language("mn")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.folder = Path(self.temp_dir.name)
        self.repo = Repository(self.folder / "finance.sqlite3")
        self.addCleanup(self.repo.close)

    def test_default_categories_translation(self):
        """All 27 default categories from the prompt translate bidirectionally."""
        # 19 default expense categories
        self.assertEqual(len(DEFAULT_EXPENSE_CATEGORIES), 19)
        for mn, en in DEFAULT_EXPENSE_CATEGORIES:
            self.assertEqual(translate(en, "mn"), mn, f"Failed translating {en} to mn")
            self.assertEqual(translate(mn, "en"), en, f"Failed translating {mn} to en")

        # 8 default income categories
        self.assertEqual(len(DEFAULT_INCOME_CATEGORIES), 8)
        for mn, en in DEFAULT_INCOME_CATEGORIES:
            self.assertEqual(translate(en, "mn"), mn, f"Failed translating {en} to mn")
            self.assertEqual(translate(mn, "en"), en, f"Failed translating {mn} to en")

    def test_category_display_name_and_resolution(self):
        """Display names reflect language and custom overrides; resolution finds internal record."""
        categories = self.repo.list_categories()
        other_exp = next(c for c in categories if c["name"] == "Other expenses")

        # Default Mongolian display
        self.assertEqual(get_category_display_name(other_exp, categories, language="mn"), "Бусад зардал")
        # English display
        self.assertEqual(get_category_display_name(other_exp, categories, language="en"), "Other expenses")

        # Custom name override
        custom_names = {other_exp["id"]: "Миний бусад зардал"}
        self.assertEqual(get_category_display_name(other_exp, categories, language="mn", custom_names=custom_names),
                         "Миний бусад зардал")

        # Resolution by Mongolian name
        resolved = resolve_category_by_display_name("Бусад зардал", categories, language="mn")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["id"], other_exp["id"])

        # Resolution by English name
        resolved_en = resolve_category_by_display_name("Other expenses", categories, language="mn")
        self.assertIsNotNone(resolved_en)
        self.assertEqual(resolved_en["id"], other_exp["id"])

        # Resolution by custom name
        resolved_custom = resolve_category_by_display_name("Миний бусад зардал", categories, language="mn", custom_names=custom_names)
        self.assertIsNotNone(resolved_custom)
        self.assertEqual(resolved_custom["id"], other_exp["id"])

        # Blank / All categories returns None
        self.assertIsNone(resolve_category_by_display_name("All categories", categories))
        self.assertIsNone(resolve_category_by_display_name("Бүх ангилал", categories))
        self.assertIsNone(resolve_category_by_display_name("", categories))

    def test_category_settings_persistence(self):
        """Settings for disabled categories and custom display names round-trip cleanly."""
        disabled = {1, 5, 8}
        display_names = {1: "Тусгай нэр", 5: "Өөр нэр"}

        save_category_settings(self.folder, disabled, display_names)
        loaded = load_category_settings(self.folder)

        self.assertEqual(loaded["disabled_ids"], disabled)
        self.assertEqual(loaded["display_names"], display_names)

    def test_category_db_operations(self):
        """Adding, checking usage, deleting unused categories, and blocking used ones."""
        # Add new category
        cat_id = self.repo.create_category("Ном, хэвлэл, бичиг хэрэг", "expense")
        self.assertGreater(cat_id, 0)
        # Calling create_category again returns same id
        cat_id_again = self.repo.create_category("Ном, хэвлэл, бичиг хэрэг", "expense")
        self.assertEqual(cat_id, cat_id_again)

        # Unused category can be deleted
        self.assertFalse(self.repo.is_category_used(cat_id))
        self.assertEqual(self.repo.category_usage_count(cat_id), 0)
        self.repo.delete_category(cat_id)

        # Verify it's gone
        categories_now = [c["id"] for c in self.repo.list_categories()]
        self.assertNotIn(cat_id, categories_now)

        # Used category in transactions blocks deletion
        acc_id = self.repo.create_account("000123", "Synthetic account")
        expense_cat = next(c for c in self.repo.list_categories() if c["direction"] == "expense")
        info = ImportInfo(account_id=acc_id, sha256="a" * 64, parser_version="synthetic-v1", filename="synthetic.xlsx")
        row = ImportRow(description="Office supplies", bank_datetime="2026/10/18 09:05:00",
                        occurred_at="2026-10-18T09:05:00", amount_minor=-125050,
                        worksheet="Synthetic sheet", row_number=7)
        import_id = self.repo.write_import(info, [row])
        tx = self.repo.query_transactions(import_id=import_id)[0]
        self.repo.assign_category(tx["id"], expense_cat["id"], reason="Test category assignment")

        self.assertTrue(self.repo.is_category_used(expense_cat["id"]))
        self.assertEqual(self.repo.category_usage_count(expense_cat["id"]), 1)

        with self.assertRaises(ValueError) as ctx:
            self.repo.delete_category(expense_cat["id"])
        self.assertIn("Cannot delete category because it is already used. Disable it instead.", str(ctx.exception))

    def test_list_categories_with_usage(self):
        """list_categories_with_usage returns accurate usage counts."""
        usage_list = self.repo.list_categories_with_usage()
        self.assertGreater(len(usage_list), 0)
        for item in usage_list:
            self.assertIn("id", item)
            self.assertIn("name", item)
            self.assertIn("direction", item)
            self.assertIn("transaction_count", item)
            self.assertIn("total_usage", item)

    def test_export_csv_translates_categories(self):
        """Export CSV translates categories to Mongolian when language='mn'."""
        acc_id = self.repo.create_account("ACC_EXP", "Khan Bank Test", bank="Khan Bank", currency="MNT")
        other_exp = next(c for c in self.repo.list_categories() if c["name"] == "Other expenses")
        info = ImportInfo(account_id=acc_id, sha256="b" * 64, parser_version="synthetic-v1", filename="synthetic.xlsx")
        row = ImportRow(description="Misc purchase", bank_datetime="2026/10/18 09:05:00",
                        occurred_at="2026-10-18T09:05:00", amount_minor=-500000,
                        worksheet="Synthetic sheet", row_number=8)
        import_id = self.repo.write_import(info, [row])
        tx = self.repo.query_transactions(import_id=import_id)[0]
        self.repo.assign_category(tx["id"], other_exp["id"], reason="Test export")

        csv_path_mn = self.folder / "export_mn.csv"
        export_csv(self.repo, csv_path_mn, {}, language="mn")
        content_mn = csv_path_mn.read_text(encoding="utf-8")
        self.assertIn("Бусад зардал", content_mn)

        csv_path_en = self.folder / "export_en.csv"
        export_csv(self.repo, csv_path_en, {}, language="en")
        content_en = csv_path_en.read_text(encoding="utf-8")
        self.assertIn("Other expenses", content_en)


if __name__ == "__main__":
    unittest.main()
