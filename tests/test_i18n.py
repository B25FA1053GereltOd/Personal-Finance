"""Localization tests use disposable workspace preferences only."""

import tempfile
import unittest
from decimal import localcontext
from pathlib import Path

from app.ui.i18n import (
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    get_language,
    load_language,
    load_theme,
    save_language,
    save_theme,
    set_language,
    source_text,
    translate,
)
from app.ui.messages import import_preview_counts, import_result, page_caption
from app.ui.view_models import dashboard_summary
from tests.test_ui import ROOT


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.previous = get_language()
        set_language(DEFAULT_LANGUAGE)
        (ROOT / "data" / "test-temp").mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="i18n-", dir=ROOT / "data" / "test-temp")
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(set_language, self.previous)
        self.folder = Path(self.temporary.name)

    def test_default_is_mongolian_and_known_labels_translate(self):
        self.assertEqual(DEFAULT_LANGUAGE, "mn")
        self.assertEqual(translate("Dashboard"), "Хураангуй")
        self.assertEqual(translate("Import statement"), "Хуулга импортлох")
        self.assertEqual(translate("Review unknown merchants"), "Танигдаагүй гүйлгээг ангилах")
        self.assertEqual(translate("Show unclassified transactions"), "Ангилаагүй гүйлгээг харуулах")
        self.assertEqual(translate("Total Revenue"), "Нийт орлого")
        self.assertEqual(translate("Total Cost"), "Нийт зардал")
        self.assertEqual(translate("Net"), "Цэвэр дүн")
        self.assertEqual(translate("A future label"), "A future label")
        self.assertEqual(translate("Other expenses", "en"), "Other expenses")
        self.assertEqual(translate("MNT"), "MNT")
        self.assertEqual(translate("expense"), "expense")
        self.assertEqual(translate("transfer"), "transfer")

    def test_english_is_available_and_missing_keys_stay_english(self):
        self.assertEqual(translate("Dashboard", "en"), "Dashboard")
        self.assertEqual(translate("Total Revenue", "en"), "Total Revenue")
        self.assertEqual(translate("Total Cost", "en"), "Total Cost")
        self.assertEqual(translate("Unmapped label", "en"), "Unmapped label")
        self.assertEqual(translate("Mapping Table", "en"), "Mapping Table")

    def test_mapping_table_labels_are_localized_without_translating_values(self):
        self.assertEqual(translate("Mapping Table"), "Ангиллын зураглал")
        self.assertEqual(translate("Rule name"), "Дүрмийн нэр")
        self.assertEqual(translate("Source field"), "Талбар")
        self.assertEqual(translate("Match operator"), "Тааруулах нөхцөл")
        self.assertEqual(translate("Match value"), "Тааруулах утга")
        self.assertEqual(translate("Priority"), "Эрэмбэ")
        self.assertEqual(translate("Bank"), "Банк")
        self.assertEqual(translate("Account"), "Данс")
        self.assertEqual(translate("Direction"), "Чиглэл")
        self.assertEqual(translate("Target category"), "Зорилтот ангилал")
        self.assertEqual(translate("Active"), "Идэвхтэй")
        self.assertEqual(translate("MNT"), "MNT")
        self.assertEqual(translate("Other expenses", "en"), "Other expenses")

    def test_language_preference_round_trips_without_database_values(self):
        self.assertEqual(load_language(self.folder), DEFAULT_LANGUAGE)
        save_language(self.folder, "en")
        self.assertEqual(load_language(self.folder), "en")
        self.assertEqual((self.folder / "settings.json").read_text(encoding="utf-8").strip(),
                         '{\n  "language": "en"\n}')
        with self.assertRaises(ValueError):
            save_language(self.folder, "fr")

    def test_direction_labels_map_to_untranslated_query_values(self):
        self.assertEqual(source_text("Зарлага", ("All directions", "Debit", "Credit", "Zero")), "Debit")
        self.assertEqual(source_text("Орлого", ("All directions", "Debit", "Credit", "Zero")), "Credit")

    def test_import_and_page_messages_use_localized_templates(self):
        counts = import_preview_counts(10, 2, 1, 3, 1)
        self.assertIn("Хүчинтэй: 10", counts)
        self.assertIn("Блоклосон алдаа: 1", counts)
        self.assertEqual(page_caption(2, 4, 11), "4 хуудасны 2 · 11 мөр")
        self.assertIn("Импорт амжилттай.", import_result("committed", 3, 0, "3"))
        self.assertIn("Давхардсан: 2", import_result("committed", 3, 2, "1", duplicate=2))

    def test_summary_cards_keep_currencies_separate(self):
        class Report:
            totals = (
                {"currency": "MNT", "income": 10000, "expenses": 2500, "net": -999999},
                {"currency": "USD", "income": 500, "expenses": 125, "net": 999999},
            )
            unclassified_count = 2

        cards = dashboard_summary(Report())
        self.assertEqual([label for label, _ in cards],
                         ["Total Revenue", "Total Cost", "Net", "Unclassified"])
        self.assertEqual(cards[0][1], "100.00 MNT · 5.00 USD")
        self.assertEqual(cards[1][1], "25.00 MNT · 1.25 USD")
        self.assertEqual(cards[2][1], "75.00 MNT · 3.75 USD")
        self.assertEqual(cards[3][1], "2")

    def test_summary_revenue_cost_and_net_remain_decimal_exact_at_large_values(self):
        class LargeReport:
            totals = ({"currency": "MNT", "income": 10**35 + 1, "expenses": 10**35, "net": -7},)
            unclassified_count = 0

        with localcontext() as context:
            context.prec = 3
            cards = dashboard_summary(LargeReport())

        self.assertTrue(cards[0][1].endswith(".01 MNT"))
        self.assertTrue(cards[1][1].endswith(".00 MNT"))
        self.assertEqual(cards[2][1], "0.01 MNT")

    def test_theme_preference_round_trips_and_preserves_language(self):
        self.assertEqual(DEFAULT_THEME, "dark")
        self.assertEqual(load_theme(self.folder), "dark")
        save_theme(self.folder, "light")
        self.assertEqual(load_theme(self.folder), "light")
        save_language(self.folder, "en")
        self.assertEqual(load_language(self.folder), "en")
        self.assertEqual(load_theme(self.folder), "light")
        save_language(self.folder, "mn")
        self.assertEqual(load_language(self.folder), "mn")
        self.assertEqual(load_theme(self.folder), "light")
        with self.assertRaises(ValueError):
            save_theme(self.folder, "neon")

    def test_theme_and_icon_translations(self):
        self.assertEqual(translate("Theme"), "Системийн өнгө")
        self.assertEqual(translate("Light mode"), "Гэрэлтэй горим")
        self.assertEqual(translate("Dark mode"), "Бараан горим")
        self.assertEqual(translate("Data location"), "Өгөгдлийн байрлал")
        self.assertEqual(translate("Backup & privacy"), "Нөөцлөлт ба нууцлал")
        self.assertEqual(translate("📊  Dashboard"), "📊  Хураангуй")
        self.assertEqual(translate("📋  Transactions"), "📋  Гүйлгээнүүд")
        self.assertEqual(translate("🔄  Apply / refresh"), "🔄  Хэрэгжүүлэх / шинэчлэх")
        self.assertEqual(translate("Theme", "en"), "Theme")
        self.assertEqual(translate("Dark mode", "en"), "Dark mode")


if __name__ == "__main__":
    unittest.main()
