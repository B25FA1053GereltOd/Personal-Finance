"""SQLite snapshots and offline restore preparation; never replace user data."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from app.db import Repository, SCHEMA_VERSION, schema_definition


class BackupError(ValueError):
    """Safe diagnostic; raw OS/SQLite errors may contain private paths/content."""


def validate_connection(connection):
    """Validate within the caller's read snapshot; never modify the input."""
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise BackupError("Backup integrity check failed. Choose another backup; do not restore this file.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise BackupError("Backup contains broken references. Choose another backup.")
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise BackupError("Backup schema version is incompatible with this app. Use a matching app version.")
    with Repository(":memory:") as expected:
        if schema_definition(connection) != expected.schema_definition():
            raise BackupError("Backup schema does not match this app. Do not restore this file.")


def validate_backup(path):
    """Read-only integrity, foreign-key and exact supported-schema checks."""
    try:
        path = Path(path).absolute()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            validate_connection(connection)
        return SCHEMA_VERSION
    except BackupError:
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise BackupError("Backup could not be validated. Check that the file exists, is readable and is a SQLite backup.") from None


def create_backup(repository, folder):
    """Reserve an exclusive timestamped name and complete the snapshot before success."""
    destination = None
    owned = False
    complete = False
    try:
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise BackupError("Backup folder is unavailable. Select an existing local folder and try again.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = folder / f"finance-backup-{stamp}-{uuid4().hex[:8]}.sqlite3"
        if destination.resolve().parent != folder:
            raise BackupError("Select a valid local backup folder.")
        with destination.open("xb"):
            owned = True
        repository.backup_to(destination)
        validate_backup(destination)
        complete = True
        return destination
    except BackupError:
        raise
    except FileExistsError:
        raise BackupError("A backup with this name already exists. Retry to create a new name; nothing was overwritten.") from None
    except (OSError, sqlite3.Error, ValueError):
        raise BackupError("Backup failed. Close other app instances; check folder permissions, free disk space and drive availability, then retry.") from None
    finally:
        # Only our newly reserved incomplete artifact can be removed on failure.
        # No existing database, backup, or statement is ever deleted.
        if owned and not complete:
            try:
                destination.unlink()
            except OSError:
                pass  # Failure is already reported; never label the artifact successful.


def prepare_restore(source, destination):
    """Copy a closed backup to a NEW location and validate that separate copy.

    This intentionally cannot replace an existing database. The user must close
    the app and preserve the current database before the documented final swap.
    """
    owned = False
    complete = False
    destination = Path(destination)
    try:
        with Path(source).open("rb") as incoming, destination.open("xb") as outgoing:
            owned = True
            shutil.copyfileobj(incoming, outgoing)
        validate_backup(destination)
        complete = True
        return destination
    except BackupError:
        raise
    except FileExistsError:
        raise BackupError("Restore destination already exists. Choose a new staging filename; nothing was overwritten.") from None
    except (OSError, ValueError):
        raise BackupError("Restore copy failed. Check source readability, destination permissions and free disk space.") from None
    finally:
        if owned and not complete:
            try:
                destination.unlink()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Offline backup validation / restore staging. Close the app first.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("backup")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("backup")
    prepare.add_argument("new_destination")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate_backup(args.backup)
        else:
            prepare_restore(args.backup, args.new_destination)
    except BackupError as error:
        parser.exit(1, f"{error}\n")
    print("PASS: integrity, foreign keys and supported schema verified.")


if __name__ == "__main__":
    main()
