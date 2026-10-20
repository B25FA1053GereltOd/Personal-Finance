"""Explicit preview/confirm restore, using SQLite atomic destination writes."""

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import sqlite3
from uuid import uuid4

from app.backup import BackupError, create_backup, validate_connection
from app.db import SCHEMA_VERSION


@dataclass(frozen=True)
class RestorePreview:
    token: str
    transactions: int
    accounts: int
    rules: int
    schema: int = SCHEMA_VERSION


@dataclass(frozen=True)
class RestoreResult:
    safety_backup: Path = field(repr=False)
    restart_required: bool = True


class RestoreService:
    def __init__(self, repository, database):
        self.repository = repository
        self.database = Path(database).resolve()
        self.pending = None
        self._stage = None
        self.restart_required = False

    def cancel(self):
        # Retain the staged snapshot; never delete the selected backup/user data.
        self.pending = None

    def preview(self, path):
        if self.restart_required:
            raise BackupError("Restore completed. Close and reopen the app.")
        self.cancel()
        stage, owned, complete = None, False, False
        try:
            selected = Path(path).resolve(strict=True)
            if selected == self.database or selected.samefile(self.database):
                raise BackupError("Choose a separate backup, not the active database.")
            folder = self.database.parent / "backups"
            folder.mkdir(exist_ok=True)
            stage = folder / ("restore-stage-" + uuid4().hex + ".sqlite3")
            with closing(sqlite3.connect(selected.as_uri() + "?mode=ro", uri=True)) as source:
                source.execute("BEGIN")
                validate_connection(source)
                with stage.open("xb"):
                    owned = True
                with closing(sqlite3.connect(stage)) as destination:
                    source.backup(destination)
            with closing(sqlite3.connect(stage.as_uri() + "?mode=ro", uri=True)) as source:
                validate_connection(source)
                counts = [source.execute("SELECT count(*) FROM " + table).fetchone()[0]
                          for table in ("transactions", "accounts", "merchant_rules")]
            self._stage = stage
            with stage.open("rb") as stream:
                self._digest = hashlib.file_digest(stream, "sha256").hexdigest()
            self._revision = self.repository.change_token()
            self.pending = RestorePreview(uuid4().hex, *counts)
            complete = True
            return self.pending
        except BackupError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise BackupError("Restore preview failed. Choose an existing readable Personal Finance backup.") from None
        finally:
            if owned and not complete:
                try:
                    stage.unlink()
                except OSError:
                    pass

    def confirm(self, token, *, confirmed=False):
        if confirmed is not True or self.pending is None or token != self.pending.token:
            raise BackupError("Preview the backup and explicitly confirm restore first.")
        try:
            with self._stage.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != self._digest or self.repository.change_token() != self._revision:
                raise BackupError("Data changed since the preview. Cancel and preview again.")
            with closing(sqlite3.connect(self._stage.as_uri() + "?mode=ro", uri=True)) as source:
                source.execute("BEGIN")
                validate_connection(source)
                safety = create_backup(self.repository, self.database.parent / "backups")
                if self.repository.change_token() != self._revision:
                    raise BackupError("Current data changed while making the safety backup. Preview again.")
                self.repository.restore_from(source)
            self.restart_required = True
            self.cancel()
            return RestoreResult(safety)
        except BackupError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise BackupError("Restore failed. The live database was not replaced. Close other app instances, check disk space and retry.") from None
