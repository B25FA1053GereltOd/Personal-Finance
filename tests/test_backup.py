"""Synthetic SQLite backup/independent restore; never inspect financial files."""

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.backup import BackupError, create_backup, prepare_restore, validate_backup
from app.db import Repository
from tests.dashboard_fixture import populate
from tests.test_ui import temporary_case


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_case(self)
        self.repo = Repository(self.folder / "live.sqlite3")
        self.addCleanup(self.repo.close)
        populate(self.repo)

    def test_backup_independent_integrity_rules_and_restore_to_temporary_location(self):
        backup = create_backup(self.repo, self.folder)
        self.assertEqual(validate_backup(backup), 3)
        with Repository(backup) as snapshot:
            self.assertEqual(snapshot.query_transactions(), self.repo.query_transactions())
            self.assertEqual(snapshot.list_rules(), self.repo.list_rules())
        stage = self.folder / "restore-stage.sqlite3"
        prepare_restore(backup, stage)
        restored_dir = self.folder / "temporary-restored-data"
        restored_dir.mkdir()
        restored = prepare_restore(stage, restored_dir / "finance.sqlite3")
        with Repository(restored) as reopened:
            self.assertEqual(reopened.count_transactions(), 10)
            self.assertEqual(len(reopened.list_rules()), 1)
        self.repo.edit_transaction(1, note="Synthetic change after backup", reason="Synthetic")
        with Repository(backup) as independent:
            self.assertNotEqual(independent.get_transaction(1)["note"], self.repo.get_transaction(1)["note"])

    def test_wal_committed_data_is_included_without_raw_database_copy(self):
        self.repo._connection.execute("PRAGMA journal_mode=WAL")
        self.repo.edit_transaction(1, note="Synthetic WAL correction", reason="Synthetic")
        backup = create_backup(self.repo, self.folder)
        with Repository(backup) as reopened:
            self.assertEqual(reopened.get_transaction(1)["note"], "Synthetic WAL correction")

    def test_backup_and_restore_never_overwrite_existing_files(self):
        with patch("app.backup.datetime") as clock, patch("app.backup.uuid4") as identifier:
            clock.now.return_value.strftime.return_value = "synthetic-stamp"
            identifier.return_value.hex = "abcdefgh1234"
            first = create_backup(self.repo, self.folder)
            before = first.read_bytes()
            with self.assertRaises(BackupError):
                create_backup(self.repo, self.folder)
            self.assertEqual(first.read_bytes(), before)
        with self.assertRaises(BackupError):
            prepare_restore(first, first)
        self.assertEqual(first.read_bytes(), before)

    def test_unavailable_permissions_and_injected_failure_are_sanitized(self):
        with self.assertRaisesRegex(BackupError, "existing local folder"):
            create_backup(self.repo, self.folder / "missing")
        with patch.object(Path, "open", side_effect=PermissionError("SYNTHETIC_SECRET")):
            with self.assertRaisesRegex(BackupError, "permissions") as caught:
                create_backup(self.repo, self.folder)
        self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))
        before = set(self.folder.iterdir())
        with patch.object(self.repo, "backup_to", side_effect=sqlite3.OperationalError("SYNTHETIC_SECRET")):
            with self.assertRaises(BackupError):
                create_backup(self.repo, self.folder)
        self.assertEqual(set(self.folder.iterdir()), before)

    def test_corrupt_wrong_version_and_incompatible_schema_rejected_read_only(self):
        corrupt = self.folder / "corrupt.sqlite3"
        corrupt.write_bytes(b"FICTIONAL INVALID DATABASE")
        with self.assertRaises(BackupError):
            validate_backup(corrupt)
        self.assertEqual(corrupt.read_bytes(), b"FICTIONAL INVALID DATABASE")
        backup = create_backup(self.repo, self.folder)
        with closing(sqlite3.connect(backup)) as connection:
            connection.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(BackupError, "version"):
            validate_backup(backup)
        with closing(sqlite3.connect(backup)) as connection:
            connection.execute("PRAGMA user_version=3")
            connection.execute("DROP INDEX transactions_date")
        with self.assertRaisesRegex(BackupError, "schema"):
            validate_backup(backup)
        with self.assertRaises(BackupError):
            prepare_restore(corrupt, self.folder / "invalid-stage.sqlite3")
        self.assertFalse((self.folder / "invalid-stage.sqlite3").exists())

    def test_backup_inside_write_is_rejected_without_hanging(self):
        with self.repo.atomic():
            with self.assertRaises(BackupError):
                create_backup(self.repo, self.folder)

    def test_documented_restore_cli_prepares_and_validates_without_gui(self):
        backup = create_backup(self.repo, self.folder)
        target = self.folder / "cli-restored.sqlite3"
        for arguments in (("prepare", str(backup), str(target)), ("validate", str(target))):
            result = subprocess.run([sys.executable, "-m", "app.backup", *arguments],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS", result.stdout)
        with Repository(target) as reopened:
            self.assertEqual((reopened.count_transactions(), len(reopened.list_rules())), (10, 1))
