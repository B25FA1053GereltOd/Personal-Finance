"""Synthetic priority mapping, scope, validation and explicit-application tests."""

import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from app.backup import validate_backup
from app.classification import ClassificationService
from app.db import SCHEMA_VERSION, Repository
from app.import_service import ImportService
from app.mapping_service import MappingBlocked, MappingService
from app.models import ImportInfo, ImportRow, MerchantMatch
from app.parsers.base import ParseResult, ParsedTransaction, StatementMetadata


class _SyntheticMappingParser:
    version = "synthetic-mapping-v1"

    def __init__(self, result: ParseResult):
        self.result = result

    def parse_bytes(self, payload: bytes) -> ParseResult:
        return self.result


class MappingServiceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "data" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mapping-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.repository = Repository(self.folder / "mapping.sqlite3")
        self.addCleanup(self.repository.close)
        categories = {c["name"]: c["id"] for c in self.repository.list_categories()}
        self.expense = categories["Other expenses"]
        self.cafeteria = categories["Cafeteria, Coffee & Snacks"]
        self.transport = categories["Public Transport / Commuting"]
        self.income = categories["Other income"]
        self.accounts = [
            self.repository.create_account("SYNTH-A", "Synthetic A", bank="Fictional Bank A"),
            self.repository.create_account("SYNTH-B", "Synthetic B", bank="Fictional Bank B"),
        ]
        self.service = MappingService(self.repository)
        self.classifier = ClassificationService(self.repository)
        self.sequence = 0

    def rule(self, *, name="Synthetic map", priority=10, bank=None, account_id=None,
             direction="any", source_field="description", operator="exact", value="Fictional shop",
             target_kind="expense", category_id=None, active=True, note=""):
        return self.service.save_rule(
            rule_name=name, priority=priority, active=active, bank=bank,
            account_id=account_id, direction=direction, source_field=source_field,
            operator=operator, match_value=value, target_kind=target_kind,
            category_id=category_id if category_id is not None else self.expense,
            note=note,
        )["rule"]

    def append(self, *, description="Fictional shop", amount=-125, account_id=None,
               pos_id=None, classify=True):
        self.sequence += 1
        account_id = self.accounts[0] if account_id is None else account_id
        row = ImportRow(description=description, bank_datetime=f"2026-10-01 10:00:{self.sequence:02d}",
                        occurred_at=f"2026-10-01T10:00:{self.sequence:02d}",
                        amount_minor=amount, worksheet="Synthetic", row_number=self.sequence,
                        currency="MNT", pos_id=pos_id)
        info = ImportInfo(account_id=account_id, sha256=f"{self.sequence:064x}",
                          parser_version="synthetic", filename=f"synthetic-{self.sequence}.xlsx")
        import_id = self.repository.write_import(
            info, [row], classify=self.classifier.classify_import if classify else None)
        return self.repository.query_transactions(import_id=import_id)[0]

    def test_description_operators_and_unicode_normalization(self):
        self.assertTrue(self.service.test_rule(
            {"source_field": "description", "operator": "exact", "match_value": "CAFÉ ЖИШЭЭ"},
            "Cafe\u0301\tЖишээ")["matched"])
        cases = (("contains", "TION"), ("starts_with", "Fic"), ("ends_with", "shop"))
        for operator, needle in cases:
            with self.subTest(operator=operator):
                self.assertTrue(self.service.test_rule(
                    {"source_field": "description", "operator": operator, "match_value": needle},
                    "Fictional shop")["matched"])

    def test_pos_id_matching_and_missing_values(self):
        row = {"pos_id": "POS-007"}
        exact = {"source_field": "pos_id", "operator": "exact", "match_value": "POS-007"}
        self.assertTrue(self.service.matches(exact, row))
        self.assertTrue(self.service.matches(exact, {"pos_id": "pos-007"}))
        self.assertFalse(self.service.matches(exact, {"pos_id": None}))
        self.assertFalse(self.service.matches(exact, {"pos_id": "POS-008"}))

    def test_exact_pos_id_food001_and_description_token_t_classification(self):
        pos_rule = self.rule(
            name="Food POS", source_field="pos_id", operator="exact", value="FOOD001",
            direction="debit", category_id=self.cafeteria, note="Cafeteria POS rule",
        )
        taxi_rule = self.rule(
            name="Taxi token", source_field="description", operator="exact", value="T",
            direction="debit", category_id=self.transport, note="Configured taxi token",
        )
        self.assertEqual(pos_rule["note"], "Cafeteria POS rule")
        self.assertEqual(taxi_rule["note"], "Configured taxi token")

        food_row = self.append(description="Fictional lunch purchase", pos_id="food001", amount=-850000)
        taxi_exact = self.append(description="t", amount=-300000)
        taxi_token = self.append(description="QPAY T 12345 UB", amount=-450000)
        non_taxi = self.append(description="RESTAURANT DINNER", amount=-1200000)

        self.assertEqual(food_row["category_id"], self.cafeteria)
        self.assertEqual(food_row["classification_source"], "mapping_rule")
        self.assertEqual(food_row["applied_mapping_rule_id"], pos_rule["id"])

        self.assertEqual(taxi_exact["category_id"], self.transport)
        self.assertEqual(taxi_exact["classification_source"], "mapping_rule")
        self.assertEqual(taxi_token["category_id"], self.transport)
        self.assertEqual(taxi_token["classification_source"], "mapping_rule")
        self.assertIsNone(non_taxi["category_id"])
        self.assertEqual(non_taxi["classification_source"], "unclassified")

    def test_source_field_order_priority_and_tiebreaker(self):
        extractor = lambda bank, version, desc: (
            MerchantMatch(display_text="SYNTHETIC COFFEE", pattern="synthetic")
            if "COFFEE" in desc else None
        )
        self.classifier = ClassificationService(self.repository, extractor=extractor)
        desc_high = self.rule(
            name="Description rule", priority=999, source_field="description",
            operator="contains", value="COFFEE", category_id=self.expense,
        )
        merch_mid = self.rule(
            name="Merchant rule", priority=50, source_field="merchant",
            operator="exact", value="synthetic coffee", category_id=self.transport,
        )
        pos_low = self.rule(
            name="POS rule", priority=1, source_field="pos_id",
            operator="exact", value="FOOD001", category_id=self.cafeteria,
        )
        # POS ID rule beats merchant and description rules regardless of numeric priority
        both = self.append(description="POS COFFEE SHOP", pos_id="FOOD001")
        self.assertEqual(both["applied_mapping_rule_id"], pos_low["id"])
        self.assertEqual(both["category_id"], self.cafeteria)

        # Merchant rule beats description rule when POS ID does not match
        merchant_only = self.append(description="POS COFFEE SHOP", pos_id="OTHER999")
        self.assertEqual(merchant_only["applied_mapping_rule_id"], merch_mid["id"])
        self.assertEqual(merchant_only["category_id"], self.transport)

        # Equal priority within same source_field uses oldest/lowest rule ID
        tie_first = self.rule(
            name="Tie first", priority=77, source_field="description",
            operator="contains", value="TIEBREAK", category_id=self.cafeteria,
        )
        tie_second = self.rule(
            name="Tie second", priority=77, source_field="description",
            operator="contains", value="TIEBREAK", category_id=self.transport,
        )
        self.assertLess(tie_first["id"], tie_second["id"])
        tied = self.append(description="SYNTHETIC TIEBREAK ROW")
        self.assertEqual(tied["applied_mapping_rule_id"], tie_first["id"])
        self.assertEqual(desc_high["active"], 1)

    def test_preview_shows_matched_rule_commit_applies_reimport_skips_and_unknown_in_review(self):
        self.rule(
            name="Food POS", source_field="pos_id", operator="exact", value="FOOD001",
            direction="debit", category_id=self.cafeteria,
        )
        self.rule(
            name="Taxi starts with T", source_field="description", operator="starts_with", value="T ",
            direction="debit", category_id=self.transport,
        )
        sources = (
            ImportRow(description="Lunch", bank_datetime="2026-10-05 12:00:00",
                      occurred_at="2026-10-05T12:00:00", amount_minor=-650000,
                      worksheet="Synthetic", row_number=1, currency="MNT", pos_id="FOOD001"),
            ImportRow(description="T 8899 UB", bank_datetime="2026-10-05 18:00:00",
                      occurred_at="2026-10-05T18:00:00", amount_minor=-350000,
                      worksheet="Synthetic", row_number=2, currency="MNT"),
            ImportRow(description="MYSTERY EXPENSE", bank_datetime="2026-10-05 19:00:00",
                      occurred_at="2026-10-05T19:00:00", amount_minor=-150000,
                      worksheet="Synthetic", row_number=3, currency="MNT"),
        )
        parsed = ParseResult(
            metadata=StatementMetadata(
                parser_version="synthetic-mapping-v1", currency="MNT", account_identifier="SYNTH-A",
                worksheet="Synthetic", period_start="2026-10-01", period_end="2026-10-31", printed_on="2026-11-01",
            ),
            records=tuple(
                ParsedTransaction(
                    source=s, branch="001", counterparty_account=None,
                    opening_balance_minor=0, credit_minor=0, debit_minor=s.amount_minor,
                )
                for s in sources
            ),
            candidate_row_count=len(sources),
        )
        statement_path = self.folder / "statement.xlsx"
        statement_path.write_bytes(b"SYNTHETIC STATEMENT BYTES")
        importer = ImportService(self.repository, _SyntheticMappingParser(parsed), classification=self.classifier)

        preview = importer.preview(statement_path, self.accounts[0])
        self.assertTrue(preview.is_valid)
        self.assertEqual(
            [(r.matched_rule, r.matched_category, r.classification_source) for r in preview.rows],
            [
                ("Food POS", "Cafeteria, Coffee & Snacks", "mapping_rule"),
                ("Taxi starts with T", "Public Transport / Commuting", "mapping_rule"),
                (None, None, "unclassified"),
            ],
        )

        committed = importer.confirm(preview)
        self.assertEqual(committed.status, "committed")
        self.assertEqual(committed.imported_count, 3)

        stored = sorted(self.repository.query_transactions(import_id=committed.import_id), key=lambda r: r["id"])
        self.assertEqual([r["classification_source"] for r in stored], ["mapping_rule", "mapping_rule", "unclassified"])
        self.assertEqual([r["category_id"] for r in stored], [self.cafeteria, self.transport, None])

        # Unknown transaction remains available in Review
        review_queue = self.classifier.review()
        self.assertEqual([item.transaction_id for item in review_queue.individual], [stored[2]["id"]])

        # Reimporting the same file creates no duplicates
        repreview = importer.preview(statement_path, self.accounts[0])
        self.assertEqual(repreview.duplicate_count, 3)
        recommit = importer.confirm(repreview)
        self.assertEqual(recommit.status, "identical_file")
        self.assertEqual(recommit.imported_count, 0)
        self.assertEqual(self.repository.count_transactions(), 3)

    def import_statement(self, name, sources, *, account_index=0, decisions=None):
        """Preview and commit one synthetic statement through the real ImportService."""
        identifier = ("SYNTH-A", "SYNTH-B")[account_index]
        parsed = ParseResult(
            metadata=StatementMetadata(
                parser_version="synthetic-mapping-v1", currency="MNT", account_identifier=identifier,
                worksheet="Synthetic", period_start="2026-10-01", period_end="2026-10-31",
                printed_on="2026-11-01"),
            records=tuple(ParsedTransaction(
                source=s, branch="001", counterparty_account=None, opening_balance_minor=0,
                credit_minor=max(s.amount_minor, 0), debit_minor=min(s.amount_minor, 0)) for s in sources),
            candidate_row_count=len(sources),
        )
        path = self.folder / name
        if not path.exists():
            path.write_bytes(f"SYNTHETIC STATEMENT {name}".encode())
        importer = ImportService(self.repository, _SyntheticMappingParser(parsed), classification=self.classifier)
        preview = importer.preview(path, self.accounts[account_index])
        self.assertTrue(preview.is_valid)
        return preview, importer.confirm(preview, decisions or {})

    @staticmethod
    def source(row_number, description, amount, *, day=1, pos_id=None):
        return ImportRow(description=description, bank_datetime=f"2026-10-{day:02d} 09:00:{row_number:02d}",
                         occurred_at=f"2026-10-{day:02d}T09:00:{row_number:02d}", amount_minor=amount,
                         worksheet="Synthetic", row_number=row_number, currency="MNT", pos_id=pos_id)

    def test_new_statement_appends_reimport_is_noop_and_existing_rows_unchanged(self):
        first_sources = (self.source(1, "OLD CAFE VISIT", -10000, pos_id="FOOD001"),
                         self.source(2, "OLD SALARY", 500000))
        _, first = self.import_statement("october-1.xlsx", first_sources)
        self.assertEqual((first.status, first.imported_count), ("committed", 2))
        old_ids = [r["id"] for r in self.repository.query_transactions(import_id=first.import_id)]
        snapshot = {i: (self.repository.get_transaction(i), self.repository.get_history(i)) for i in old_ids}

        # A rule created after the first import must not reclassify existing rows.
        self.rule(name="Food POS", source_field="pos_id", operator="exact", value="FOOD001",
                  direction="debit", category_id=self.cafeteria)
        second_sources = (self.source(1, "NEW CAFE VISIT", -12000, day=15, pos_id="FOOD001"),
                          self.source(2, "NEW UNKNOWN", -3000, day=15))
        _, second = self.import_statement("october-2.xlsx", second_sources)
        self.assertEqual((second.status, second.imported_count), ("committed", 2))
        self.assertEqual(self.repository.count_transactions(), 4)
        new_rows = sorted(self.repository.query_transactions(import_id=second.import_id), key=lambda r: r["id"])
        self.assertEqual([r["category_id"] for r in new_rows], [self.cafeteria, None])

        # Reimporting either statement adds nothing.
        for name, sources in (("october-1.xlsx", first_sources), ("october-2.xlsx", second_sources)):
            preview, result = self.import_statement(name, sources)
            self.assertEqual(preview.duplicate_count, 2)
            self.assertEqual((result.status, result.imported_count), ("identical_file", 0))
        self.assertEqual(self.repository.count_transactions(), 4)

        for identifier, (row, history) in snapshot.items():
            self.assertEqual(self.repository.get_transaction(identifier), row)
            self.assertEqual(self.repository.get_history(identifier), history)
        self.assertIsNone(self.repository.get_transaction(old_ids[0])["category_id"])

    def test_merchant_and_description_rules_respect_bank_account_and_direction_scope(self):
        third = self.repository.create_account("SYNTH-C", "Synthetic C", bank="Fictional Bank A")
        self.accounts.append(third)
        self.classifier = ClassificationService(self.repository, extractor=lambda bank, version, desc: (
            MerchantMatch(display_text="SYNTHETIC COFFEE", pattern="synthetic") if "COFFEE" in desc else None))
        # Same merchant, different banks, independent categories.
        bank_a = self.rule(name="Coffee A", bank="Fictional Bank A", source_field="merchant",
                           value="synthetic coffee", category_id=self.cafeteria)
        bank_b = self.rule(name="Coffee B", bank="Fictional Bank B", source_field="merchant",
                           value="synthetic coffee", category_id=self.transport)
        # Description rule limited to one account and to debits.
        taxi = self.rule(name="Taxi C", bank="Fictional Bank A", account_id=third, direction="debit",
                         operator="contains", value="TAXI RIDE", category_id=self.transport)
        # Credit-only description rule on Bank B.
        refund = self.rule(name="Refund B", bank="Fictional Bank B", direction="credit",
                           operator="starts_with", value="REFUND", target_kind="income",
                           category_id=self.income)

        coffee_a = self.append(description="POS COFFEE", account_id=self.accounts[0])
        coffee_b = self.append(description="POS COFFEE", account_id=self.accounts[1])
        coffee_c = self.append(description="POS COFFEE", account_id=third)
        taxi_c = self.append(description="TAXI RIDE UB", account_id=third)
        taxi_a = self.append(description="TAXI RIDE UB", account_id=self.accounts[0])
        refund_b_credit = self.append(description="REFUND SHOP", amount=700, account_id=self.accounts[1])
        refund_b_debit = self.append(description="REFUND SHOP", amount=-700, account_id=self.accounts[1])
        refund_a_credit = self.append(description="REFUND SHOP", amount=700, account_id=self.accounts[0])

        self.assertEqual((coffee_a["applied_mapping_rule_id"], coffee_a["category_id"]), (bank_a["id"], self.cafeteria))
        self.assertEqual((coffee_b["applied_mapping_rule_id"], coffee_b["category_id"]), (bank_b["id"], self.transport))
        # Bank-scoped (not account-scoped) rule applies to every account of that bank.
        self.assertEqual(coffee_c["applied_mapping_rule_id"], bank_a["id"])
        self.assertEqual(taxi_c["applied_mapping_rule_id"], taxi["id"])
        self.assertIsNone(taxi_a["category_id"])
        self.assertEqual((refund_b_credit["applied_mapping_rule_id"], refund_b_credit["category_id"]),
                         (refund["id"], self.income))
        self.assertIsNone(refund_b_debit["category_id"])
        self.assertIsNone(refund_a_credit["category_id"])
        for row in (taxi_a, refund_b_debit, refund_a_credit):
            self.assertEqual(row["classification_source"], "unclassified")

    def test_regex_validation_and_matching(self):
        rule = self.rule(source_field="description", operator="regex", value=r"^fictional\s+shop$")
        row = self.append(classify=False)
        self.assertTrue(self.service.matches(rule, row))
        with self.assertRaises(MappingBlocked):
            self.service.save_rule(
                rule_name="Invalid regex", priority=1, active=True, bank=None,
                account_id=None, direction="any", source_field="description",
                operator="regex", match_value="[", target_kind="expense",
                category_id=self.expense,
            )

    def test_priority_disabled_rules_and_manual_protection(self):
        low = self.rule(name="Low priority", priority=1, operator="contains", value="shop")
        high = self.rule(name="High priority", priority=9, operator="starts_with", value="Fic")
        row = self.append()
        self.assertEqual(row["applied_mapping_rule_id"], high["id"])
        self.assertEqual(row["applied_mapping_rule_name"], "High priority")
        self.service.set_active(high["id"], False, high["revision"])
        # The imported row is already classified (and therefore ineligible); use a
        # fresh unclassified row to observe the winner once the high rule is disabled.
        self.assertIsNone(self.service.winning_rule(row))
        unclassified = self.append(classify=False)
        self.assertEqual(self.service.winning_rule(unclassified)["id"], low["id"])
        protected = self.append(description="Protected fiction")
        self.repository.assign_category(protected["id"], self.expense, reason="Synthetic manual protection")
        self.rule(name="Protected matcher", priority=20, operator="contains", value="fiction")
        preview = self.service.preview(low["id"])
        self.assertNotIn(protected["id"], {r["id"] for r in preview.rows})
        self.service.cancel()

    def test_bank_account_direction_scope_and_currency_is_unchanged(self):
        self.rule(bank="Fictional Bank A", account_id=self.accounts[0],
                  direction="debit", source_field="pos_id", operator="exact",
                  value="PX-91")
        first = self.append(pos_id="PX-91", account_id=self.accounts[0])
        second = self.append(pos_id="PX-91", account_id=self.accounts[1])
        credit = self.append(pos_id="PX-91", amount=125, account_id=self.accounts[0])
        self.assertEqual(first["kind"], "expense")
        self.assertIsNone(second["category_id"])
        self.assertIsNone(credit["category_id"])
        self.assertEqual((first["currency"], first["original_currency"]), ("MNT", "MNT"))
        self.assertEqual(self.repository.count_transactions(bank="Fictional Bank A"), 2)
        self.assertEqual(self.repository.count_transactions(account_id=self.accounts[1]), 1)
        with self.assertRaises(ValueError):
            self.rule(bank="Fictional Bank B", account_id=self.accounts[0])

    def test_mapping_list_bank_filter_includes_global_and_matching_scope(self):
        self.rule(name="Global")
        self.rule(name="Bank A", bank="Fictional Bank A")
        self.rule(name="Bank B", bank="Fictional Bank B")
        rules = self.repository.list_mapping_rules(bank="Fictional Bank A")
        self.assertEqual({rule["rule_name"] for rule in rules}, {"Global", "Bank A"})

    def test_existing_application_requires_preview_and_explicit_selected_ids(self):
        first = self.append(classify=False)
        second = self.append(description="Fictional shop", classify=False)
        rule = self.rule()
        preview = self.service.preview(rule["id"])
        self.assertEqual({r["id"] for r in preview.rows}, {first["id"], second["id"]})
        self.assertEqual(self.service.apply(preview.token, [first["id"]]), 1)
        updated = self.repository.get_transaction(first["id"])
        unchanged = self.repository.get_transaction(second["id"])
        self.assertEqual((updated["category_id"], updated["applied_mapping_rule_name"]),
                         (self.expense, "Synthetic map"))
        self.assertIsNone(unchanged["category_id"])
        self.assertEqual(self.repository.get_history(first["id"])[-1]["reason"],
                         "Classification mapping rule applied")

    def test_one_character_contains_warns_and_empty_match_rejected(self):
        warnings = self.service.warnings({"operator": "contains", "match_value": "T"})
        self.assertTrue(any("One-character" in message for message in warnings))
        with self.assertRaises(MappingBlocked):
            self.rule(value="  ")

    def test_schema_v3_migration_preserves_transactions_and_adds_mapping_fields(self):
        temporary_root = Path(__file__).resolve().parents[1] / "data" / "test-temp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mapping-v3-", dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "legacy.sqlite3"
        with Repository(path) as legacy:
            account = legacy.create_account("SYNTH-V3", "Synthetic v3")
            categories_before = [(row["id"], row["name"], row["direction"])
                                 for row in legacy.list_categories()]
            legacy_category = next(row for row in legacy.list_categories()
                                   if row["direction"] == "expense")
            legacy_rule_id = legacy.upsert_rule(
                "Fictional legacy shop", "debit", "expense", legacy_category["id"],
                bank="Fictional Bank A")
            info = ImportInfo(account_id=account, sha256="a" * 64,
                              parser_version="synthetic", filename="legacy.xlsx")
            legacy.write_import(info, [ImportRow(
                description="Fictional legacy row", bank_datetime="2026-10-01 10:00:00",
                occurred_at="2026-10-01T10:00:00", amount_minor=-12500,
                worksheet="Synthetic", row_number=1, currency="MNT")])
            transaction_before = legacy.query_transactions()[0]
        with closing(sqlite3.connect(path)) as raw_connection, raw_connection as connection:
            connection.execute("DROP TRIGGER mapping_rules_category_insert")
            connection.execute("DROP TRIGGER mapping_rules_category_update")
            connection.execute("DROP TRIGGER immutable_source")
            connection.execute("DROP TABLE mapping_rules")
            connection.execute("ALTER TABLE transactions DROP COLUMN applied_mapping_rule_id")
            connection.execute("ALTER TABLE transactions DROP COLUMN applied_mapping_rule_name")
            connection.execute("ALTER TABLE transactions DROP COLUMN pos_id")
            immutable_columns = (
                "id, source_id, import_id, bank_datetime, worksheet, row_number, dedup_key, "
                "original_description, original_occurred_at, original_amount_minor, "
                "original_currency, original_reference, original_balance_minor")
            changed = " OR ".join(
                f"NEW.{column} IS NOT OLD.{column}" for column in immutable_columns.split(", "))
            connection.execute(f"""CREATE TRIGGER immutable_source
                BEFORE UPDATE OF {immutable_columns} ON transactions
                WHEN {changed}
                BEGIN SELECT RAISE(ABORT, 'Imported source values and identity are immutable'); END""")
            connection.execute("PRAGMA user_version = 3")
        with Repository(path) as migrated:
            transaction_after = migrated.query_transactions()[0]
            self.assertEqual(migrated._connection.execute("PRAGMA user_version").fetchone()[0],
                             SCHEMA_VERSION)
            self.assertEqual(migrated.list_mapping_rules(), [])
            self.assertEqual([(row["id"], row["name"], row["direction"])
                              for row in migrated.list_categories()], categories_before)
            self.assertEqual(migrated.get_rule(legacy_rule_id)["merchant_key"], "fictional legacy shop")
            self.assertIsNone(transaction_after["pos_id"])
            self.assertEqual(transaction_after["is_archived"], 0)
            self.assertIsNone(transaction_after["archived_at"])
            for field in ("id", "original_description", "original_amount_minor", "currency"):
                self.assertEqual(transaction_after[field], transaction_before[field])
            backup = Path(temporary.name) / "migrated.sqlite3"
            migrated.backup_to(backup)
            self.assertEqual(validate_backup(backup), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
