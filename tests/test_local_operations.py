"""Synthetic restore and CSV failure boundaries. No GUI or real financial files."""

from contextlib import closing
import csv
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.backup import BackupError, create_backup, validate_backup
from app.db import Repository
from app.export_service import ExportError, export_csv, FIELDS
from app.local_actions import open_data_folder
from app.models import ImportInfo, ImportRow, MAX_INTEGER
from app.restore_service import RestoreService
from tests.dashboard_fixture import populate
from tests.test_ui import temporary_case


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        self.database = self.folder / "finance.sqlite3"
        self.repo = Repository(self.database)
        self.addCleanup(self.repo.close)
        populate(self.repo)
        self.backup = create_backup(self.repo, self.folder)
        self.repo.edit_transaction(1, note="Fictional current change", reason="Synthetic")
        self.service = RestoreService(self.repo, self.database)

    def test_preview_cancel_confirm_safety_backup_and_restart(self):
        original = self.repo.get_transaction(1)
        source_bytes = self.backup.read_bytes()
        preview = self.service.preview(self.backup)
        self.assertEqual((preview.transactions, preview.accounts, preview.rules, preview.schema), (10, 2, 1, 3))
        self.service.cancel()
        self.assertEqual(self.repo.get_transaction(1), original)
        with self.assertRaises(BackupError):
            self.service.confirm(preview.token, confirmed=True)
        preview = self.service.preview(self.backup)
        with self.assertRaises(BackupError):
            self.service.confirm(preview.token)
        result = self.service.confirm(preview.token, confirmed=True)
        self.assertTrue(result.restart_required)
        self.assertEqual(validate_backup(result.safety_backup), 3)
        with Repository(result.safety_backup) as preserved:
            self.assertEqual(preserved.get_transaction(1), original)
        with Repository(self.database) as restarted:
            self.assertEqual(restarted.count_transactions(), 10)
            self.assertEqual(len(restarted.list_rules()), 1)
            self.assertEqual(restarted.get_transaction(1)["note"], "")
        self.assertEqual(self.backup.read_bytes(), source_bytes)
        with self.assertRaises(BackupError):
            self.service.preview(self.backup)

    def test_missing_corrupt_unrelated_newer_and_live_database_rejected(self):
        corrupt = self.folder / "corrupt.db"
        corrupt.write_bytes(b"FICTIONAL CORRUPTION")
        unrelated = self.folder / "unrelated.db"
        with closing(sqlite3.connect(unrelated)) as connection:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.execute("PRAGMA user_version=3")
        newer = create_backup(self.repo, self.folder)
        with closing(sqlite3.connect(newer)) as connection:
            connection.execute("PRAGMA user_version=999")
        before = self.repo.query_transactions()
        for path in (corrupt, unrelated, newer, self.database, self.folder / "missing.db"):
            with self.subTest(case=path.name), self.assertRaises(BackupError):
                self.service.preview(path)
        self.assertEqual(self.repo.query_transactions(), before)
        self.assertIsNone(self.service.pending)

    def test_safety_backup_failure_never_calls_restore(self):
        preview = self.service.preview(self.backup)
        before = self.repo.query_transactions()
        with patch("app.restore_service.create_backup", side_effect=BackupError("Synthetic failure")), \
             patch.object(self.repo, "restore_from") as apply:
            with self.assertRaises(BackupError):
                self.service.confirm(preview.token, confirmed=True)
        apply.assert_not_called()
        self.assertEqual(self.repo.query_transactions(), before)

    def test_preview_stage_or_current_changes_reject_without_restore(self):
        preview = self.service.preview(self.backup)
        self.repo.edit_transaction(1, note="New synthetic correction", reason="Synthetic")
        with self.assertRaisesRegex(BackupError, "changed"):
            self.service.confirm(preview.token, confirmed=True)
        preview = self.service.preview(self.backup)
        with Repository(self.service._stage) as changed:
            changed.edit_transaction(1, note="Changed staged synthetic copy", reason="Synthetic")
        with self.assertRaisesRegex(BackupError, "changed"):
            self.service.confirm(preview.token, confirmed=True)
        self.assertEqual(self.repo.get_transaction(1)["note"], "New synthetic correction")

    def test_external_write_after_preview_rejected(self):
        preview = self.service.preview(self.backup)
        with Repository(self.database) as other:
            other.edit_transaction(1, note="Fictional second instance", reason="Synthetic")
        with self.assertRaisesRegex(BackupError, "changed"):
            self.service.confirm(preview.token, confirmed=True)

    def test_failure_during_page_copy_rolls_back_destination(self):
        self.repo.edit_transaction(1, note="X" * 300000, reason="Synthetic large pages")
        large = create_backup(self.repo, self.folder)
        self.repo.edit_transaction(1, note="Keep current value", reason="Synthetic")
        preview = self.service.preview(large)
        before = self.repo.query_transactions()
        real_restore = self.repo.restore_from
        def interrupt(*args):
            raise sqlite3.OperationalError("SYNTHETIC_SECRET")
        with patch.object(self.repo, "restore_from", side_effect=lambda source: real_restore(source, progress=interrupt)):
            with self.assertRaises(BackupError) as caught:
                self.service.confirm(preview.token, confirmed=True)
        self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))
        self.assertEqual(self.repo.query_transactions(), before)
        self.assertTrue(list((self.folder / "backups").glob("finance-backup-*.sqlite3")))

    def test_process_interruption_recovers_original_live_database(self):
        self.repo.edit_transaction(1, note="Y" * 300000, reason="Synthetic large pages")
        large = create_backup(self.repo, self.folder)
        self.repo.edit_transaction(1, note="Retain through interruption", reason="Synthetic")
        script = """import os, sys
from app.db import Repository
from app.restore_service import RestoreService
with Repository(sys.argv[1]) as repo:
    service = RestoreService(repo, sys.argv[1])
    preview = service.preview(sys.argv[2])
    apply = repo.restore_from
    repo.restore_from = lambda source: apply(source, progress=lambda *args: os._exit(77))
    service.confirm(preview.token, confirmed=True)
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.database), str(large)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 77)
        with Repository(self.database) as recovered:
            self.assertEqual(recovered.get_transaction(1)["note"], "Retain through interruption")
            self.assertEqual(recovered.count_transactions(), 10)
        self.assertEqual(validate_backup(self.database), 3)

    def test_restore_with_wal_preserves_safety_snapshot(self):
        self.repo._connection.execute("PRAGMA journal_mode=WAL")
        preview = self.service.preview(self.backup)
        result = self.service.confirm(preview.token, confirmed=True)
        self.assertEqual(self.repo.get_transaction(1)["note"], "")
        with Repository(result.safety_backup) as preserved:
            self.assertEqual(preserved.get_transaction(1)["note"], "Fictional current change")

    def test_locked_backup_destination_fails_without_retrying_forever(self):
        target = self.folder / "locked.sqlite3"
        with closing(sqlite3.connect(target)) as other:
            other.execute("CREATE TABLE synthetic(value)")
            other.execute("BEGIN EXCLUSIVE")
            with self.assertRaisesRegex(ValueError, "other app instances"):
                self.repo.backup_to(target)
            other.rollback()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        self.repo = Repository(self.folder / "finance.sqlite3")
        self.addCleanup(self.repo.close)
        populate(self.repo)
        self.target = self.folder / "synthetic.csv"

    def read(self):
        with self.target.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_bom_unicode_effective_values_exact_amount_and_no_database_writes(self):
        self.repo.edit_transaction(4, amount_minor=-123456789012345, description='Fictional Жишээ, "quoted"\nnext',
                                   merchant_display="Fictional display", note="Edited note", reason="Synthetic")
        before = self.repo.change_token()
        result = export_csv(self.repo, self.target, {"search": "ЖИШЭЭ"})
        self.assertEqual(result.count, 1)
        self.assertTrue(self.target.read_bytes().startswith(b"\xef\xbb\xbf"))
        row = self.read()[0]
        self.assertEqual(tuple(row), FIELDS)
        self.assertEqual(row["signed_amount"], "-1234567890123.45")
        self.assertEqual(row["description"], 'Fictional Жишээ, "quoted"\nnext')
        self.assertEqual((row["merchant"], row["note"], row["manual_protection"]),
                         ("Fictional display", "Edited note", "protected"))
        self.assertEqual(self.repo.change_token(), before)

    def test_all_active_filters_match_existing_browser_query(self):
        for filters in ({"currency": "USD"}, {"account_id": 1, "date_from": "2026-10-01", "date_to": "2026-10-31",
                                              "direction": "debit"}, {"review_only": True},
                        {"kind": "transfer"}, {"category_id": 13}, {"search": "row 3", "currency": "MNT"},
                        {"import_id": 2}):
            expected = self.repo.query_transactions(**filters)
            path = self.folder / ("filtered-" + str(len(list(self.folder.glob("*.csv")))) + ".csv")
            result = export_csv(self.repo, path, filters)
            self.assertEqual(result.count, len(expected))
            if expected:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual([r["description"] for r in rows], [r["description"] for r in expected])
            else:
                self.assertFalse(path.exists())

    def test_exports_all_pages_and_max_integer_precision(self):
        imported = self.repo.write_import(ImportInfo(account_id=1, sha256="f"*64, parser_version="synthetic", filename="synthetic.xlsx"),
            [ImportRow(description="Fictional export", bank_datetime="2026-10-20", occurred_at="2026-10-20",
                       amount_minor=MAX_INTEGER, worksheet="Synthetic", row_number=i+1) for i in range(501)])
        self.assertEqual(export_csv(self.repo, self.target, {"import_id": imported}).count, 501)
        self.assertEqual(len(self.read()), 501)
        self.assertEqual(self.read()[0]["signed_amount"], "92233720368547758.07")

    def test_empty_export_no_file_and_existing_file_never_overwritten(self):
        self.assertEqual(export_csv(self.repo, self.target, {"search": "absent fictional text"}).count, 0)
        self.assertFalse(self.target.exists())
        self.target.write_bytes(b"EXISTING SYNTHETIC FILE")
        with self.assertRaises(ExportError):
            export_csv(self.repo, self.target, {})
        self.assertEqual(self.target.read_bytes(), b"EXISTING SYNTHETIC FILE")

    def test_formula_text_neutralized_but_signed_money_preserved(self):
        self.repo.edit_transaction(4, description=" =HYPERLINK(\"fictional\")", merchant_display="@SUM(1)",
                                   note="\t=1+1", reason="Synthetic")
        export_csv(self.repo, self.target, {"search": "HYPERLINK"})
        row = self.read()[0]
        self.assertTrue(all(row[key].startswith("'") for key in ("description", "merchant", "note")))
        self.assertEqual(row["signed_amount"], "-30.10")

    def test_write_failure_cleans_only_new_partial_export_and_keeps_database(self):
        before = self.repo.query_transactions()
        with patch("app.export_service.csv.writer") as writer:
            writer.return_value.writerow.side_effect = OSError("SYNTHETIC_SECRET")
            with self.assertRaises(ExportError) as caught:
                export_csv(self.repo, self.target, {})
        self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))
        self.assertFalse(self.target.exists())
        self.assertEqual(self.repo.query_transactions(), before)
        with self.assertRaises(ExportError):
            export_csv(self.repo, self.folder / "missing" / "file.csv", {})
        with self.assertRaises(ExportError):
            export_csv(self.repo, self.target, {"currency": "bad"})

    def test_snapshot_stays_consistent_during_other_connection_write(self):
        database = self.folder / "finance.sqlite3"
        self.repo._connection.execute("PRAGMA journal_mode=WAL")
        original_query = self.repo.query_transactions
        def changed(**filters):
            with Repository(database) as other:
                other.edit_transaction(1, description="Later fictional edit", reason="Synthetic")
            return original_query(**filters)
        with patch.object(self.repo, "query_transactions", side_effect=changed):
            export_csv(self.repo, self.target, {})
        self.assertFalse(any(r["description"] == "Later fictional edit" for r in self.read()))


class LocalPathTests(unittest.TestCase):
    def test_open_folder_passes_one_absolute_path_without_shell_interpretation(self):
        folder = temporary_case(self) / "fictional & (folder)"
        folder.mkdir()
        with patch("app.local_actions.os.startfile", create=True) as start:
            open_data_folder(folder)
        start.assert_called_once_with(str(folder.resolve()), "open")

    def test_invalid_or_unavailable_folder_has_sanitized_error(self):
        folder = temporary_case(self)
        with patch("app.local_actions.os.startfile", create=True, side_effect=OSError("SYNTHETIC_SECRET")):
            with self.assertRaises(ValueError) as caught:
                open_data_folder(folder)
            self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))
        for path in ("relative-folder", folder / "missing"):
            with self.assertRaises(ValueError):
                open_data_folder(path)
