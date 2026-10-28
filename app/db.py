"""SQLite repository. All writes are atomic; source rows are immutable.

Each connection belongs to its creating thread, including the UI worker.
See docs/database.md for the small public API and row field conventions.
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import get_data_dir
from app.models import (
    DEFAULT_CATEGORIES, KINDS, ImportDecision, ImportInfo, ImportRow, MerchantMatch,
    RuleSelection, normalize_merchant_key, require_integer,
    require_text, validate_currency, validate_iso, validate_month,
)


SCHEMA_VERSION = 4
_EDITABLE = frozenset({
    "description", "occurred_at", "amount_minor", "currency", "reference",
    "balance_minor", "kind", "category_id", "merchant_key", "merchant_display", "note", "manual_lock",
})
_SOURCE_COLUMNS = (
    "id", "source_id", "import_id", "bank_datetime", "worksheet", "row_number",
    "dedup_key", "pos_id", "original_description", "original_occurred_at", "original_amount_minor",
    "original_currency", "original_reference", "original_balance_minor",
)
_SCHEMA = (
    """CREATE TABLE accounts (
        id INTEGER PRIMARY KEY,
        identifier TEXT NOT NULL CHECK(length(trim(identifier)) > 0),
        name TEXT NOT NULL,
        bank TEXT NOT NULL,
        currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
        UNIQUE(bank, identifier, currency)
    ) STRICT""",
    """CREATE TABLE categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('income', 'expense')),
        UNIQUE(name, direction)
    ) STRICT""",
    """CREATE TABLE imports (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        sha256 TEXT NOT NULL CHECK(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        parser_version TEXT NOT NULL,
        filename TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        total_count INTEGER NOT NULL CHECK(total_count >= 0),
        imported_count INTEGER NOT NULL CHECK(imported_count >= 0),
        skipped_count INTEGER NOT NULL CHECK(skipped_count >= 0),
        rejected_count INTEGER NOT NULL CHECK(rejected_count >= 0),
        CHECK(total_count = imported_count + skipped_count + rejected_count)
    ) STRICT""",
    """CREATE TABLE transactions (
        id INTEGER PRIMARY KEY,
        source_id TEXT NOT NULL UNIQUE,
        import_id INTEGER NOT NULL REFERENCES imports(id),
        bank_datetime TEXT NOT NULL,
        worksheet TEXT NOT NULL,
        row_number INTEGER NOT NULL CHECK(row_number > 0),
        dedup_key TEXT,
        pos_id TEXT,
        original_description TEXT NOT NULL,
        original_occurred_at TEXT NOT NULL,
        original_amount_minor INTEGER NOT NULL,
        original_currency TEXT NOT NULL,
        original_reference TEXT,
        original_balance_minor INTEGER,
        description TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        amount_minor INTEGER NOT NULL,
        currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
        reference TEXT,
        balance_minor INTEGER,
        kind TEXT NOT NULL DEFAULT 'unclassified'
            CHECK(kind IN ('unclassified', 'income', 'expense', 'transfer', 'excluded')),
        category_id INTEGER REFERENCES categories(id),
        merchant_key TEXT,
        note TEXT NOT NULL DEFAULT '',
        classification_source TEXT NOT NULL DEFAULT 'unclassified'
            CHECK(classification_source IN ('unclassified', 'import', 'rule', 'manual')),
        manual_lock INTEGER NOT NULL DEFAULT 0 CHECK(manual_lock IN (0, 1)),
        CHECK(kind != 'income' OR amount_minor > 0),
        CHECK(kind != 'expense' OR amount_minor < 0),
        CHECK(category_id IS NULL OR kind IN ('income', 'expense'))
    ) STRICT""",
    """CREATE TABLE merchant_rules (
        id INTEGER PRIMARY KEY,
        merchant_key TEXT NOT NULL CHECK(length(trim(merchant_key)) > 0),
        direction TEXT NOT NULL CHECK(direction IN ('credit', 'debit', 'zero')),
        kind TEXT NOT NULL CHECK(kind IN ('income', 'expense', 'transfer', 'excluded')),
        category_id INTEGER REFERENCES categories(id),
        CHECK(kind != 'income' OR direction = 'credit'),
        CHECK(kind != 'expense' OR direction = 'debit'),
        CHECK((kind IN ('income', 'expense') AND category_id IS NOT NULL)
            OR (kind IN ('transfer', 'excluded') AND category_id IS NULL)),
        UNIQUE(merchant_key, direction)
    ) STRICT""",
    """CREATE TABLE transaction_edits (
        id INTEGER PRIMARY KEY,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id),
        edited_at TEXT NOT NULL,
        reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
        changes_json TEXT NOT NULL CHECK(json_valid(changes_json))
    ) STRICT""",
    "CREATE INDEX transactions_date ON transactions(occurred_at DESC, id DESC)",
    "CREATE INDEX transactions_import ON transactions(import_id)",
    "CREATE INDEX imports_account ON imports(account_id)",
    "CREATE INDEX transactions_category ON transactions(category_id)",
    "CREATE INDEX transaction_edits_transaction ON transaction_edits(transaction_id, id)",
    """CREATE TRIGGER immutable_import BEFORE UPDATE ON imports BEGIN
        SELECT RAISE(ABORT, 'Import metadata is immutable'); END""",
    """CREATE TRIGGER immutable_category_direction BEFORE UPDATE OF direction ON categories
        WHEN NEW.direction IS NOT OLD.direction BEGIN
        SELECT RAISE(ABORT, 'Category direction is immutable'); END""",
    """CREATE TRIGGER immutable_account_identity BEFORE UPDATE OF identifier, bank, currency ON accounts
        WHEN EXISTS(SELECT 1 FROM imports WHERE account_id = OLD.id) BEGIN
        SELECT RAISE(ABORT, 'An imported account identity is immutable'); END""",
    """CREATE TRIGGER retain_transactions BEFORE DELETE ON transactions BEGIN
        SELECT RAISE(ABORT, 'Exclude transactions instead of deleting source data'); END""",
    """CREATE TRIGGER retain_edit_history BEFORE DELETE ON transaction_edits BEGIN
        SELECT RAISE(ABORT, 'Edit history is append-only'); END""",
    """CREATE TRIGGER immutable_edit_history BEFORE UPDATE ON transaction_edits BEGIN
        SELECT RAISE(ABORT, 'Edit history is append-only'); END""",
)

_IMPORT_SCHEMA = (
    """CREATE TABLE import_decisions (
        import_id INTEGER NOT NULL REFERENCES imports(id),
        row_index INTEGER NOT NULL CHECK(row_index >= 0),
        action TEXT NOT NULL CHECK(action IN ('keep', 'skip')),
        reason TEXT NOT NULL CHECK(reason IN ('new', 'verified_reference', 'manual')),
        source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        matching_ids_json TEXT NOT NULL CHECK(json_valid(matching_ids_json)),
        PRIMARY KEY(import_id, row_index)
    ) STRICT""",
    """CREATE TRIGGER immutable_import_decisions BEFORE UPDATE ON import_decisions
        BEGIN SELECT RAISE(ABORT, 'Import decisions are immutable'); END""",
    """CREATE TRIGGER retain_import_decisions BEFORE DELETE ON import_decisions
        BEGIN SELECT RAISE(ABORT, 'Import decisions are append-only'); END""",
    "CREATE INDEX imports_file ON imports(account_id, sha256)",
)

_CLASSIFICATION_SCHEMA = (
    "DROP TRIGGER merchant_rules_category_insert",
    "DROP TRIGGER merchant_rules_category_update",
    "ALTER TABLE merchant_rules RENAME TO legacy_merchant_rules",
    """CREATE TABLE merchant_rules (
        id INTEGER PRIMARY KEY,
        bank TEXT NOT NULL,
        merchant_key TEXT NOT NULL CHECK(length(trim(merchant_key)) > 0),
        display_text TEXT NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('credit', 'debit', 'zero')),
        kind TEXT NOT NULL CHECK(kind IN ('income', 'expense', 'transfer', 'excluded')),
        category_id INTEGER REFERENCES categories(id),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
        CHECK(active = 0 OR length(trim(bank)) > 0),
        CHECK(kind != 'income' OR direction = 'credit'),
        CHECK(kind != 'expense' OR direction = 'debit'),
        CHECK((kind IN ('income', 'expense') AND category_id IS NOT NULL)
            OR (kind IN ('transfer', 'excluded') AND category_id IS NULL)),
        UNIQUE(bank, merchant_key, direction)
    ) STRICT""",
    # Legacy rules have no verified bank scope. Preserve IDs/text, deactivate;
    # never assume that a previously global rule belongs to Khan or any bank.
    """INSERT INTO merchant_rules(id, bank, merchant_key, display_text, direction,
        kind, category_id, active) SELECT id, '', merchant_key, merchant_key,
        direction, kind, category_id, 0 FROM legacy_merchant_rules""",
    "DROP TABLE legacy_merchant_rules",
    """CREATE TRIGGER merchant_rules_category_insert BEFORE INSERT ON merchant_rules
        WHEN NEW.category_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction = NEW.kind)
        BEGIN SELECT RAISE(ABORT, 'Category direction must match transaction kind'); END""",
    """CREATE TRIGGER merchant_rules_category_update BEFORE UPDATE ON merchant_rules
        WHEN NEW.category_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction = NEW.kind)
        BEGIN SELECT RAISE(ABORT, 'Category direction must match transaction kind'); END""",
    "ALTER TABLE transactions ADD COLUMN merchant_display TEXT",
    "ALTER TABLE transactions ADD COLUMN merchant_pattern TEXT",
    "ALTER TABLE transactions ADD COLUMN merchant_type TEXT CHECK(merchant_type IN ('purchase', 'refund'))",
    "ALTER TABLE transactions ADD COLUMN applied_rule_id INTEGER REFERENCES merchant_rules(id)",
    "ALTER TABLE transactions ADD COLUMN applied_rule_revision INTEGER",
    """CREATE TRIGGER retain_merchant_rules BEFORE DELETE ON merchant_rules
        BEGIN SELECT RAISE(ABORT, 'Disable rules instead of deleting rule history'); END""",
)

_MAPPING_SCHEMA = (
    """CREATE TABLE mapping_rules (
        id INTEGER PRIMARY KEY,
        rule_name TEXT NOT NULL CHECK(length(trim(rule_name)) > 0),
        priority INTEGER NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        bank TEXT,
        account_id INTEGER REFERENCES accounts(id),
        direction TEXT NOT NULL CHECK(direction IN ('any', 'debit', 'credit')),
        source_field TEXT NOT NULL CHECK(source_field IN ('pos_id', 'merchant', 'description')),
        operator TEXT NOT NULL CHECK(operator IN ('exact', 'contains', 'starts_with', 'ends_with', 'regex')),
        match_value TEXT NOT NULL CHECK(length(trim(match_value)) > 0),
        target_kind TEXT NOT NULL CHECK(target_kind IN ('income', 'expense', 'transfer', 'excluded')),
        category_id INTEGER REFERENCES categories(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
        CHECK(target_kind IN ('transfer', 'excluded') AND category_id IS NULL
            OR target_kind IN ('income', 'expense') AND category_id IS NOT NULL)
    ) STRICT""",
    "CREATE INDEX mapping_rules_priority ON mapping_rules(active, priority DESC, id)",
    "ALTER TABLE transactions ADD COLUMN applied_mapping_rule_id INTEGER",
    "ALTER TABLE transactions ADD COLUMN applied_mapping_rule_name TEXT",
    "DROP TRIGGER immutable_source",
    """CREATE TRIGGER immutable_source
        BEFORE UPDATE OF id, source_id, import_id, bank_datetime, worksheet, row_number,
            dedup_key, pos_id, original_description, original_occurred_at, original_amount_minor,
            original_currency, original_reference, original_balance_minor
        ON transactions
        WHEN NEW.id IS NOT OLD.id OR NEW.source_id IS NOT OLD.source_id
            OR NEW.import_id IS NOT OLD.import_id OR NEW.bank_datetime IS NOT OLD.bank_datetime
            OR NEW.worksheet IS NOT OLD.worksheet OR NEW.row_number IS NOT OLD.row_number
            OR NEW.dedup_key IS NOT OLD.dedup_key OR NEW.pos_id IS NOT OLD.pos_id
            OR NEW.original_description IS NOT OLD.original_description
            OR NEW.original_occurred_at IS NOT OLD.original_occurred_at
            OR NEW.original_amount_minor IS NOT OLD.original_amount_minor
            OR NEW.original_currency IS NOT OLD.original_currency
            OR NEW.original_reference IS NOT OLD.original_reference
            OR NEW.original_balance_minor IS NOT OLD.original_balance_minor
        BEGIN SELECT RAISE(ABORT, 'Imported source values and identity are immutable'); END""",
    """CREATE TRIGGER mapping_rules_category_insert BEFORE INSERT ON mapping_rules
        WHEN NEW.category_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction = NEW.target_kind)
        BEGIN SELECT RAISE(ABORT, 'Category direction must match mapping target kind'); END""",
    """CREATE TRIGGER mapping_rules_category_update BEFORE UPDATE ON mapping_rules
        WHEN NEW.category_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction = NEW.target_kind)
        BEGIN SELECT RAISE(ABORT, 'Category direction must match mapping target kind'); END""",
)

_BUDGET_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY,
        month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
        currency TEXT NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]'),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        planned_amount_minor INTEGER NOT NULL CHECK(planned_amount_minor > 0),
        note TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(month, currency, category_id)
    ) STRICT""",
    "CREATE INDEX IF NOT EXISTS budgets_month_currency ON budgets(month, currency, active)",
    """CREATE TRIGGER IF NOT EXISTS budgets_category_insert BEFORE INSERT ON budgets
        WHEN NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction IN ('income', 'expense'))
        BEGIN SELECT RAISE(ABORT, 'Category must be an income or expense category'); END""",
    """CREATE TRIGGER IF NOT EXISTS budgets_category_update BEFORE UPDATE ON budgets
        WHEN NOT EXISTS(
            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction IN ('income', 'expense'))
        BEGIN SELECT RAISE(ABORT, 'Category direction must match category'); END""",
)

_ARCHIVE_SCHEMA = (
    "ALTER TABLE transactions ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1))",
    "ALTER TABLE transactions ADD COLUMN archived_at TEXT",
    "CREATE INDEX IF NOT EXISTS transactions_archived ON transactions(is_archived, occurred_at DESC, id DESC)",
)


class ImportStateChanged(ValueError):
    """An import preview must be refreshed before confirmation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classification_revision(row: dict) -> str:
    """Opaque revision for a complete joined classification row, never a log."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def schema_definition(connection):
    """Stable application schema fingerprint for conservative restore validation."""
    signature = []
    for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"):
        values = list(row)
        if values[0] == "table" and values[1] == "transactions" and values[3]:
            values[3] = _normalize_table_column_order(values[3])
        signature.append(tuple(values))
    return tuple(signature)


def _normalize_table_column_order(sql: str) -> str:
    """Canonicalize column order while preserving each complete SQL definition."""
    opening = sql.find("(")
    if opening < 0:
        return sql
    definitions = []
    start = opening + 1
    depth = 0
    quote = None
    index = start
    while index < len(sql):
        character = sql[index]
        if quote:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in ("'", '"', "`"):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                definitions.append(sql[start:index])
                break
            depth -= 1
        elif character == "," and depth == 0:
            definitions.append(sql[start:index])
            start = index + 1
        index += 1
    else:
        return sql

    columns, constraints = [], []
    for definition in definitions:
        normalized = re.sub(r"\s+", " ", definition.strip())
        first_word = normalized.split(" ", 1)[0].upper()
        if first_word in {"CHECK", "CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}:
            constraints.append(normalized)
        else:
            columns.append(normalized)
    return sql[:opening + 1] + ", ".join(sorted(columns) + constraints) + sql[index:]


class Repository:
    """Own one connection; use as a context manager or explicitly close()."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = get_data_dir() / "finance.sqlite3"
        if str(path) != ":memory:":
            path = Path(path).expanduser().absolute()
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.create_function(
            "unicode_casefold", 1,
            lambda value: unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).casefold()),
            deterministic=True,
        )
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._classifying_import_id: int | None = None
        try:
            self.initialize()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def backup_to(self, destination) -> None:
        """Snapshot via SQLite on this connection's owning thread, never raw copy."""
        if self._connection.in_transaction:
            raise ValueError("Finish the current write before taking a backup.")
        def check(status, remaining, total):
            if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise ValueError("Close other app instances before taking a backup.")
        with closing(sqlite3.connect(destination)) as target:
            self._connection.backup(target, pages=32, progress=check)

    def schema_definition(self):
        return schema_definition(self._connection)

    def change_token(self):
        """Detect writes on this connection or another connection since preview."""
        return self._connection.total_changes, self._connection.execute("PRAGMA data_version").fetchone()[0]

    def restore_from(self, source, *, progress=None):
        """Atomic SQLite backup into this connection; caller validates and backs up.

        SQLite holds the destination write transaction until all pages complete.
        An exception before completion finalizes the backup and rolls it back.
        No filesystem replacement or removal of journal/WAL files is involved.
        """
        if self._connection.in_transaction:
            raise ValueError("Finish the current write before restoring.")
        def check(status, remaining, total):
            if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise ValueError("Close other app instances before restoring.")
            if status != sqlite3.SQLITE_DONE and progress is not None:
                progress(status, remaining, total)
        source.backup(self._connection, pages=32, progress=check)

    @contextmanager
    def read_snapshot(self):
        """Consistent paginated export without acquiring a write transaction."""
        if self._connection.in_transaction:
            raise ValueError("Finish the current operation first.")
        self._connection.execute("BEGIN")
        try:
            yield
        finally:
            self._connection.execute("ROLLBACK")

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Compose existing repository/service writes as one rollback-safe action."""
        with self._write():
            yield

    @contextmanager
    def _write(self) -> Iterator[None]:
        nested = self._connection.in_transaction
        savepoint = "write_" + uuid4().hex
        self._connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
        try:
            yield
            self._connection.execute(f"RELEASE {savepoint}" if nested else "COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                if nested:
                    self._connection.execute(f"ROLLBACK TO {savepoint}")
                    self._connection.execute(f"RELEASE {savepoint}")
                else:
                    self._connection.execute("ROLLBACK")
            raise

    def initialize(self) -> None:
        """Initialize once or atomically migrate supported earlier schemas."""
        with self._write():
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                for statement in _BUDGET_SCHEMA:
                    self._connection.execute(statement)
                columns = {row[1] for row in self._connection.execute("PRAGMA table_info(transactions)")}
                if "is_archived" not in columns:
                    self._connection.execute("ALTER TABLE transactions ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1))")
                if "archived_at" not in columns:
                    self._connection.execute("ALTER TABLE transactions ADD COLUMN archived_at TEXT")
                self._connection.execute("CREATE INDEX IF NOT EXISTS transactions_archived ON transactions(is_archived, occurred_at DESC, id DESC)")
                return
            if version in (1, 2, 3):
                if version == 1:
                    for statement in _IMPORT_SCHEMA:
                        self._connection.execute(statement)

                if version in (1, 2):
                    for statement in _CLASSIFICATION_SCHEMA:
                        self._connection.execute(statement)

                columns = {row[1] for row in self._connection.execute("PRAGMA table_info(transactions)")}
                if "pos_id" not in columns:
                    self._connection.execute("ALTER TABLE transactions ADD COLUMN pos_id TEXT")
                if SCHEMA_VERSION >= 4:
                    for statement in _MAPPING_SCHEMA:
                        self._connection.execute(statement)

                    for statement in _BUDGET_SCHEMA:
                        self._connection.execute(statement)

                    columns = {row["name"] for row in self._rows("PRAGMA table_info(transactions)")}
                    if "is_archived" not in columns:
                        self._connection.execute("ALTER TABLE transactions ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1))")
                    if "archived_at" not in columns:
                        self._connection.execute("ALTER TABLE transactions ADD COLUMN archived_at TEXT")
                    self._connection.execute("CREATE INDEX IF NOT EXISTS transactions_archived ON transactions(is_archived, occurred_at DESC, id DESC)")


                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return
            if version != 0:
                raise ValueError(f"Unsupported database schema version {version}; expected {SCHEMA_VERSION}.")
            if self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone():
                raise ValueError("Refusing to initialize a nonempty database without a schema version.")
            for statement in _SCHEMA:
                self._connection.execute(statement)
            # Column names here and below are internal constants, never user input.
            columns = ", ".join(_SOURCE_COLUMNS)
            changed = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in _SOURCE_COLUMNS)
            self._connection.execute(f"""CREATE TRIGGER immutable_source
                BEFORE UPDATE OF {columns} ON transactions WHEN {changed} BEGIN
                SELECT RAISE(ABORT, 'Imported source values and identity are immutable'); END""")
            for table in ("transactions", "merchant_rules"):
                for operation in ("INSERT", "UPDATE"):
                    self._connection.execute(f"""CREATE TRIGGER {table}_category_{operation.lower()}
                        BEFORE {operation} ON {table}
                        WHEN NEW.category_id IS NOT NULL AND NOT EXISTS(
                            SELECT 1 FROM categories WHERE id = NEW.category_id AND direction = NEW.kind)
                        BEGIN SELECT RAISE(ABORT, 'Category direction must match transaction kind'); END""")
            for operation in ("INSERT", "UPDATE"):
                self._connection.execute(f"""CREATE TRIGGER transaction_currency_{operation.lower()}
                    BEFORE {operation} ON transactions WHEN NOT EXISTS(
                        SELECT 1 FROM imports i JOIN accounts a ON a.id = i.account_id
                        WHERE i.id = NEW.import_id AND a.currency = NEW.currency
                        AND a.currency = NEW.original_currency)
                    BEGIN SELECT RAISE(ABORT, 'Transaction currency must match its account'); END""")
            self._connection.executemany(
                "INSERT INTO categories(name, direction) VALUES (?, ?)", DEFAULT_CATEGORIES
            )
            for statement in _IMPORT_SCHEMA:
                self._connection.execute(statement)
            for statement in _CLASSIFICATION_SCHEMA:
                self._connection.execute(statement)
            if SCHEMA_VERSION >= 4:
                for statement in _MAPPING_SCHEMA:
                    self._connection.execute(statement)
                for statement in _BUDGET_SCHEMA:
                    self._connection.execute(statement)
                for statement in _ARCHIVE_SCHEMA:
                    self._connection.execute(statement)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _rows(self, sql: str, parameters: tuple = ()) -> list[dict]:
        return [dict(row) for row in self._connection.execute(sql, parameters)]

    def _has_column(self, table: str, column: str) -> bool:
        return any(row["name"] == column for row in self._rows(f"PRAGMA table_info({table})"))

    def create_account(self, identifier: str, name: str, *, bank: str = "Khan Bank", currency: str = "MNT") -> int:
        require_text(identifier, "Account identifier")
        require_text(name, "Account name")
        require_text(bank, "Bank")
        validate_currency(currency)
        with self._write():
            return self._connection.execute(
                "INSERT INTO accounts(identifier, name, bank, currency) VALUES (?, ?, ?, ?)",
                (identifier, name, bank, currency),
            ).lastrowid

    def list_accounts(self) -> list[dict]:
        return self._rows("SELECT * FROM accounts ORDER BY id")

    def list_categories(self) -> list[dict]:
        return self._rows("SELECT * FROM categories ORDER BY id")

    def create_category(self, name: str, direction: str) -> int:
        name = require_text(name, "Category name").strip()
        if direction not in ("income", "expense"):
            raise ValueError("Category direction must be income or expense.")
        with self._write():
            existing = self._connection.execute(
                "SELECT id FROM categories WHERE name = ? AND direction = ?",
                (name, direction),
            ).fetchone()
            if existing is not None:
                return existing[0]
            return self._connection.execute(
                "INSERT INTO categories(name, direction) VALUES (?, ?)",
                (name, direction),
            ).lastrowid

    def is_category_used(self, category_id: int) -> bool:
        require_integer(category_id, "Category ID", minimum=1)
        for table in ("transactions", "merchant_rules", "mapping_rules", "budgets"):
            if self._connection.execute(
                f"SELECT 1 FROM {table} WHERE category_id = ? LIMIT 1",
                (category_id,),
            ).fetchone() is not None:
                return True
        return False

    def category_usage_count(self, category_id: int) -> int:
        require_integer(category_id, "Category ID", minimum=1)
        row = self._connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id = ?",
            (category_id,),
        ).fetchone()
        return row[0] if row else 0

    def delete_category(self, category_id: int) -> None:
        require_integer(category_id, "Category ID", minimum=1)
        if self.is_category_used(category_id):
            raise ValueError("Cannot delete category because it is already used. Disable it instead.")
        with self._write():
            self._connection.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    def list_categories_with_usage(self) -> list[dict]:
        sql = """
            SELECT c.id, c.name, c.direction,
                   (SELECT COUNT(*) FROM transactions WHERE category_id = c.id) as transaction_count,
                   (SELECT COUNT(*) FROM transactions WHERE category_id = c.id) +
                   (SELECT COUNT(*) FROM merchant_rules WHERE category_id = c.id) +
                   (SELECT COUNT(*) FROM mapping_rules WHERE category_id = c.id) +
                   (SELECT COUNT(*) FROM budgets WHERE category_id = c.id) as total_usage
            FROM categories c
            ORDER BY c.direction, c.id
        """
        return self._rows(sql)

    def get_import_state(self, account_id: int) -> dict:
        """Read one consistent account/source snapshot, with an opaque revision.

        Effective values are excluded: manual edits neither change duplicate
        identity nor stale a preview. This method never starts a write.
        """
        if self._connection.in_transaction:
            return self._import_state(account_id)
        self._connection.execute("BEGIN")
        try:
            state = self._import_state(account_id)
            self._connection.execute("COMMIT")
            return state
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _import_state(self, account_id: int) -> dict:
        account = self._one("accounts", account_id)
        imports = self._rows("SELECT * FROM imports WHERE account_id = ? ORDER BY id", (account_id,))
        columns = ", ".join("t." + name for name in _SOURCE_COLUMNS)
        transactions = self._rows(
            f"SELECT {columns}, i.parser_version FROM transactions t "
            "JOIN imports i ON i.id = t.import_id WHERE i.account_id = ? ORDER BY t.id",
            (account_id,),
        )
        state = {"account": account, "imports": imports, "transactions": transactions}
        state["revision"] = hashlib.sha256(
            json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return state

    def write_import(self, info: ImportInfo, rows: Iterable[ImportRow], *, skipped_count: int = 0,
                     rejected_count: int = 0, expected_revision: str | None = None,
                     decisions: Iterable[ImportDecision] = (), classify: Callable[[int], None] | None = None) -> int:
        """Atomically store rows/decisions and run classification before committing."""
        if not isinstance(info, ImportInfo):
            raise ValueError("Import metadata must be an ImportInfo instance.")
        require_integer(skipped_count, "Skipped count", 0)
        require_integer(rejected_count, "Rejected count", 0)
        with self._write():
            if expected_revision is not None and self._import_state(info.account_id)["revision"] != expected_revision:
                raise ImportStateChanged("Account imports changed; create a new preview before confirming.")
            source_rows = tuple(rows)
            decisions = tuple(decisions)
            total = require_integer(len(source_rows) + skipped_count + rejected_count, "Total count", 0)
            if decisions:
                if any(not isinstance(d, ImportDecision) for d in decisions):
                    raise ValueError("Import decisions must be ImportDecision instances.")
                if (rejected_count or len(decisions) != total
                        or [d.row_index for d in decisions] != list(range(total))
                        or tuple(d.source for d in decisions if d.action == "keep") != source_rows):
                    raise ValueError("Decisions must account for every incoming row in order.")
                valid_ids = {r["id"] for r in self._import_state(info.account_id)["transactions"]}
                if any(not set(d.matching_transaction_ids) <= valid_ids for d in decisions):
                    raise ValueError("Decision candidates must belong to the selected account.")
            import_id = self._connection.execute(
                """INSERT INTO imports(account_id, sha256, parser_version, filename, imported_at,
                    total_count, imported_count, skipped_count, rejected_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (info.account_id, info.sha256.lower(), info.parser_version, info.filename,
                 _now(), total, len(source_rows), skipped_count, rejected_count),
            ).lastrowid
            for row in source_rows:
                if not isinstance(row, ImportRow):
                    raise ValueError("Each imported row must be an ImportRow instance.")
                self._connection.execute(
                    """INSERT INTO transactions(source_id, import_id, bank_datetime, worksheet,
                        row_number, dedup_key, pos_id, original_description, original_occurred_at,
                        original_amount_minor, original_currency, original_reference, original_balance_minor,
                        description, occurred_at, amount_minor, currency, reference, balance_minor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (uuid4().hex, import_id, row.bank_datetime, row.worksheet, row.row_number,
                     row.dedup_key, row.pos_id, row.description, row.occurred_at, row.amount_minor, row.currency,
                     row.reference, row.balance_minor, row.description, row.occurred_at,
                     row.amount_minor, row.currency, row.reference, row.balance_minor),
                )
            if decisions:
                self._connection.executemany(
                    """INSERT INTO import_decisions(import_id, row_index, action, reason,
                        source_json, matching_ids_json) VALUES (?, ?, ?, ?, ?, ?)""",
                    [(import_id, d.row_index, d.action, d.reason,
                      json.dumps(asdict(d.source), ensure_ascii=False),
                      json.dumps(d.matching_transaction_ids)) for d in decisions],
                )
            if classify is not None:
                previous = self._classifying_import_id
                self._classifying_import_id = import_id
                try:
                    classify(import_id)
                finally:
                    self._classifying_import_id = previous
            return import_id

    def get_import_decisions(self, import_id: int) -> list[dict]:
        """Read the immutable disposition of each incoming row, in source order."""
        self.get_import(import_id)
        rows = self._rows("SELECT * FROM import_decisions WHERE import_id = ? ORDER BY row_index", (import_id,))
        for row in rows:
            row["source"] = json.loads(row.pop("source_json"))
            row["matching_transaction_ids"] = json.loads(row.pop("matching_ids_json"))
        return rows

    def get_import(self, import_id: int) -> dict:
        return self._one("imports", import_id)

    def _one(self, table: str, identifier: int) -> dict:
        require_integer(identifier, "ID", 1)
        row = self._connection.execute(f"SELECT * FROM {table} WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise ValueError(f"No {table} record with ID {identifier}.")
        return dict(row)


    @staticmethod
    def _normalize_transaction(row: dict) -> dict:
        if row.get("applied_mapping_rule_id") is not None and row.get("classification_source") == "rule":
            row["classification_source"] = "mapping_rule"
        return row


    @staticmethod
    def _unpack_mapping_rule(row: dict) -> dict:
        raw_name = row.get("rule_name", "")
        name, _, note = raw_name.partition("\n")
        row["rule_name"] = name
        row["note"] = note
        return row

    def get_transaction(self, transaction_id: int) -> dict:
        return self._normalize_transaction(self._one("transactions", transaction_id))

    def query_transactions(self, *, account_id: int | None = None, import_id: int | None = None,
                           kind: str | None = None, category_id: int | None = None,
                           review_only: bool = False, date_from: str | None = None,
                           date_to: str | None = None, direction: str | None = None,
                           search: str = "", currency: str | None = None,
                           bank: str | None = None, archived: bool | None = False,
                           limit: int = 100, offset: int = 0) -> list[dict]:
        """Filter effective values; stable bank-local ISO order, newest first."""
        require_integer(limit, "Page size", 1)
        if limit > 1000:
            raise ValueError("Page size cannot exceed 1000.")
        require_integer(offset, "Page offset", 0)
        where, parameters = self._transaction_filter(
            account_id=account_id, import_id=import_id, kind=kind, category_id=category_id,
            review_only=review_only, date_from=date_from, date_to=date_to, direction=direction,
            search=search, currency=currency, bank=bank, archived=archived,
        )
        return [
            self._normalize_transaction(row)
            for row in self._rows(
                "SELECT t.*, i.account_id, a.bank, a.name AS account_name, a.identifier AS account_identifier "
                "FROM transactions t JOIN imports i ON i.id = t.import_id "
                "JOIN accounts a ON a.id = i.account_id" + where
                + " ORDER BY t.occurred_at DESC, t.id DESC LIMIT ? OFFSET ?", tuple(parameters + [limit, offset]),
            )
        ]

    def count_transactions(self, *, account_id: int | None = None, import_id: int | None = None,
                           kind: str | None = None, category_id: int | None = None,
                           review_only: bool = False, date_from: str | None = None,
                           date_to: str | None = None, direction: str | None = None, search: str = "",
                           currency: str | None = None, bank: str | None = None,
                           archived: bool | None = False) -> int:
        """Count with the same effective-value filters as the paginated query."""
        where, parameters = self._transaction_filter(
            account_id=account_id, import_id=import_id, kind=kind, category_id=category_id,
            review_only=review_only, date_from=date_from, date_to=date_to, direction=direction,
            search=search, currency=currency, bank=bank, archived=archived,
        )
        return self._connection.execute(
            "SELECT count(*) FROM transactions t JOIN imports i ON i.id = t.import_id "
            "JOIN accounts a ON a.id = i.account_id" + where,
            tuple(parameters),
        ).fetchone()[0]


    def _transaction_filter(self, *, account_id, import_id, kind, category_id, review_only,
                            date_from, date_to, direction, search, currency=None, bank=None,
                            archived=False):
        if type(review_only) is not bool:
            raise ValueError("review_only must be a boolean.")
        conditions, parameters = [], []
        if archived is not None:
            if type(archived) is not bool:
                raise ValueError("archived filter must be boolean or None.")
            if self._has_column("transactions", "is_archived"):
                conditions.append("t.is_archived = ?")
                parameters.append(int(archived))



        for column, value in (("i.account_id", account_id), ("t.import_id", import_id), ("t.category_id", category_id)):
            if value is not None:
                require_integer(value, column, 1)
                conditions.append(f"{column} = ?")
                parameters.append(value)
        if kind is not None:
            if kind not in KINDS:
                raise ValueError("Unknown transaction kind.")
            conditions.append("t.kind = ?")
            parameters.append(kind)
        if currency is not None:
            validate_currency(currency)
            conditions.append("t.currency = ?")
            parameters.append(currency)
        if bank is not None:
            require_text(bank, "Bank")
            conditions.append("a.bank = ?")
            parameters.append(bank)
        for operator, value in ((">=", date_from), ("<=", date_to)):
            if value is not None:
                validate_iso(value)
                if len(value) != 10:
                    raise ValueError("Date filters must use YYYY-MM-DD.")
                conditions.append(f"substr(t.occurred_at, 1, 10) {operator} ?")
                parameters.append(value)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("Start date must not be after end date.")
        if review_only:
            conditions.append("(t.kind = 'unclassified' OR (t.kind IN ('income', 'expense') AND t.category_id IS NULL))")
        if direction is not None:
            comparisons = {"debit": "<", "credit": ">", "zero": "="}
            if direction not in comparisons:
                raise ValueError("Direction must be debit, credit, or zero.")
            conditions.append(f"t.amount_minor {comparisons[direction]} 0")
        require_text(search, "Merchant / description search", allow_empty=True)
        if search:
            conditions.append(
                "(instr(unicode_casefold(t.description), unicode_casefold(?)) > 0 "
                "OR instr(unicode_casefold(COALESCE(t.merchant_display, '')), unicode_casefold(?)) > 0 "
                "OR instr(unicode_casefold(COALESCE(t.merchant_key, '')), unicode_casefold(?)) > 0)"
            )
            parameters.extend((search, search, search))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return where, parameters

    def reporting_rows(self, date_from=None, date_to=None, *, account_id=None, import_id=None,
                       kind=None, category_id=None, review_only=False, direction=None,
                       search="", currency=None, bank=None, archived: bool | None = False) -> list[dict]:
        """One read snapshot of effective reporting fields, without source text.

        Return individual integer amounts rather than SQLite SUM, whose signed
        64-bit accumulator can overflow even when each stored amount is valid.
        """
        where, parameters = self._transaction_filter(
            account_id=account_id, import_id=import_id, kind=kind, category_id=category_id,
            review_only=review_only, date_from=date_from, date_to=date_to, direction=direction,
            search=search, currency=currency, bank=bank, archived=archived)
        return self._rows(
            "SELECT t.occurred_at, t.currency, t.amount_minor, t.kind, t.category_id, c.name AS category_name "
            "FROM transactions t JOIN imports i ON i.id = t.import_id "
            "JOIN accounts a ON a.id = i.account_id LEFT JOIN categories c ON c.id = t.category_id" + where,
            tuple(parameters))

    def _validate_category(self, kind: str, category_id: int | None) -> None:
        if kind not in KINDS:
            raise ValueError("Unknown transaction kind.")
        if category_id is not None:
            category = self._one("categories", category_id)
            if category["direction"] != kind:
                raise ValueError("Category direction must match the effective transaction kind.")

    def _validate_effective(self, values: dict, account_currency: str) -> None:
        require_text(values["description"], "Description", allow_empty=True)
        validate_iso(values["occurred_at"])
        amount = require_integer(values["amount_minor"], "Amount")
        validate_currency(values["currency"])
        if values["currency"] != account_currency:
            raise ValueError("Transaction currency must match its account; currency conversion is not supported.")
        if values["reference"] is not None:
            require_text(values["reference"], "Reference", allow_empty=True)
        if values["balance_minor"] is not None:
            require_integer(values["balance_minor"], "Balance")
        if values["merchant_key"] is not None:
            require_text(values["merchant_key"], "Merchant key")
        if values["merchant_display"] is not None:
            require_text(values["merchant_display"], "Merchant display", allow_empty=True)
        require_text(values["note"], "Note", allow_empty=True)
        if type(values["manual_lock"]) is not bool:
            raise ValueError("Manual lock must be a boolean.")
        kind = values["kind"]
        self._validate_category(kind, values["category_id"])
        if (kind == "income" and amount <= 0) or (kind == "expense" and amount >= 0):
            raise ValueError("Income requires a positive amount; expense requires a negative amount.")

    def edit_transaction(self, transaction_id: int, *, reason: str, **changes: object) -> dict:
        """Apply a manual edit and a compact old/new audit record in one commit."""
        require_text(reason, "Edit reason")
        if not changes or not changes.keys() <= _EDITABLE:
            raise ValueError("Supply editable effective fields only; source values and identity cannot be edited.")
        with self._write():
            before = self.get_transaction(transaction_id)
            after = {**before, **changes, "classification_source": "manual"}
            after["manual_lock"] = changes.get("manual_lock", True)
            after["applied_rule_id"] = None
            after["applied_rule_revision"] = None
            after["applied_mapping_rule_id"] = None
            after["applied_mapping_rule_name"] = None
            self._validate_effective(after, before["original_currency"])
            delta = {key: {"old": before[key], "new": after[key]}
                     for key in sorted(_EDITABLE | {
                         "classification_source", "applied_rule_id", "applied_rule_revision",
                         "applied_mapping_rule_id", "applied_mapping_rule_name",
                     })
                     if before[key] != after[key]}
            if delta:
                assignments = ", ".join(f"{key} = ?" for key in delta)
                self._connection.execute(
                    f"UPDATE transactions SET {assignments} WHERE id = ?",
                    tuple(after[key] for key in delta) + (transaction_id,),
                )
                self._connection.execute(
                    "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                    (transaction_id, _now(), reason, json.dumps(delta, ensure_ascii=False)),
                )
            return self.get_transaction(transaction_id)

    def assign_category(self, transaction_id: int, category_id: int | None, *, reason: str) -> dict:
        """Explicit manual assignment; None resets the item to unclassified."""
        kind = self._one("categories", category_id)["direction"] if category_id is not None else "unclassified"
        return self.edit_transaction(transaction_id, reason=reason, kind=kind, category_id=category_id)

    def assign_categories(self, transaction_ids: Iterable[int], category_id: int | None, *, reason: str) -> int:
        """Explicit selected-only assignment; all rows lock or all roll back."""
        identifiers = tuple(transaction_ids)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Select each transaction only once.")
        with self._write():
            for identifier in identifiers:
                self.assign_category(identifier, category_id, reason=reason)
        return len(identifiers)

    def get_history(self, transaction_id: int) -> list[dict]:
        self.get_transaction(transaction_id)
        rows = self._rows("SELECT * FROM transaction_edits WHERE transaction_id = ? ORDER BY id", (transaction_id,))
        for row in rows:
            row["changes"] = json.loads(row.pop("changes_json"))
        return rows

    def upsert_rule(self, merchant_key: str, direction: str, kind: str, category_id: int | None = None, *,
                    bank: str = "Khan Bank", active: bool = True) -> int:
        """Create/update one exact merchant-key/sign rule; does not classify rows."""
        display_text = merchant_key
        merchant_key = normalize_merchant_key(merchant_key)
        require_text(bank, "Bank")
        if type(active) is not bool:
            raise ValueError("Rule active state must be boolean.")
        if direction not in ("credit", "debit", "zero"):
            raise ValueError("Rule direction must be credit, debit, or zero.")
        if kind not in ("income", "expense", "transfer", "excluded"):
            raise ValueError("Rule kind must be income, expense, transfer, or excluded.")
        if (kind == "income" and direction != "credit") or (kind == "expense" and direction != "debit"):
            raise ValueError("Rule direction is incompatible with its kind.")
        if kind in ("income", "expense") and category_id is None:
            raise ValueError("Income and expense rules require a category.")
        with self._write():
            self._validate_category(kind, category_id)
            self._connection.execute(
                """INSERT INTO merchant_rules(bank, merchant_key, display_text, direction, kind, category_id, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bank, merchant_key, direction) DO UPDATE SET kind = excluded.kind,
                    category_id = excluded.category_id, display_text = excluded.display_text,
                    active = excluded.active, revision = merchant_rules.revision + 1""",
                (bank, merchant_key, display_text, direction, kind, category_id, int(active)),
            )
            return self._connection.execute(
                "SELECT id FROM merchant_rules WHERE bank = ? AND merchant_key = ? AND direction = ?",
                (bank, merchant_key, direction),
            ).fetchone()[0]

    def get_rule(self, rule_id: int) -> dict:
        return self._one("merchant_rules", rule_id)

    def list_rules(self, *, include_disabled: bool = False) -> list[dict]:
        return self._rows("SELECT * FROM merchant_rules" + ("" if include_disabled else " WHERE active = 1") + " ORDER BY id")

    def disable_rule(self, rule_id: int) -> None:
        with self._write():
            self.get_rule(rule_id)
            self._connection.execute(
                "UPDATE merchant_rules SET active = 0, revision = revision + 1 WHERE id = ? AND active = 1", (rule_id,),
            )

    def delete_rule(self, rule_id: int) -> None:
        """Compatibility alias: disable while retaining referenced rule history."""
        self.disable_rule(rule_id)

    def save_mapping_rule(self, *, rule_name: str, priority: int, active: bool, bank: str | None,
                          account_id: int | None, direction: str, source_field: str,
                          operator: str, match_value: str, target_kind: str,
                          category_id: int | None, note: str = "", rule_id: int | None = None,
                          expected_revision: int | None = None) -> int:
        require_text(rule_name, "Rule name")
        require_text(note, "Rule note", allow_empty=True)
        require_integer(priority, "Rule priority", 0)
        if type(active) is not bool:
            raise ValueError("Rule active state must be boolean.")
        if bank is not None:
            require_text(bank, "Bank")
        if account_id is not None:
            require_integer(account_id, "Account ID", 1)
            account = self._one("accounts", account_id)
            if bank is not None and bank != account["bank"]:
                raise ValueError("The selected account does not belong to the selected bank.")
        if direction not in ("any", "debit", "credit"):
            raise ValueError("Mapping direction must be any, debit, or credit.")
        if source_field not in ("pos_id", "merchant", "description"):
            raise ValueError("Choose a supported mapping source field.")
        if operator not in ("exact", "contains", "starts_with", "ends_with", "regex"):
            raise ValueError("Choose a supported mapping operator.")
        require_text(match_value, "Match value")
        if operator == "regex":
            try:
                re.compile(match_value)
            except re.error:
                raise ValueError("Regular expression is invalid.") from None
        if target_kind not in ("income", "expense", "transfer", "excluded"):
            raise ValueError("Mapping target must be income, expense, transfer, or excluded.")
        if (target_kind in ("income", "expense")) != (category_id is not None):
            raise ValueError("Income/expense mappings need a category; transfer/excluded mappings do not.")
        if category_id is not None:
            require_integer(category_id, "Category ID", 1)
            category = self._one("categories", category_id)
            if category["direction"] != target_kind:
                raise ValueError("Target category direction must match the target kind.")

        clean_name = " ".join(rule_name.splitlines()).strip()
        clean_note = note.strip()
        stored_name = f"{clean_name}\n{clean_note}" if clean_note else clean_name
        now = _now()
        with self._write():
            values = (stored_name, priority, int(active), bank, account_id, direction,
                      source_field, operator, match_value, target_kind, category_id)
            if rule_id is None:
                return self._connection.execute(
                    """INSERT INTO mapping_rules(rule_name, priority, active, bank, account_id,
                       direction, source_field, operator, match_value, target_kind, category_id,
                       created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, now, now),
                ).lastrowid
            require_integer(rule_id, "Mapping rule ID", 1)
            current = self.get_mapping_rule(rule_id)
            if expected_revision is None or current["revision"] != expected_revision:
                raise ValueError("Mapping rule changed; refresh before editing.")
            self._connection.execute(
                """UPDATE mapping_rules SET rule_name=?, priority=?, active=?, bank=?, account_id=?,
                   direction=?, source_field=?, operator=?, match_value=?, target_kind=?, category_id=?,
                   updated_at=?, revision=revision+1 WHERE id=?""",
                (*values, now, rule_id),
            )
            return rule_id

    def get_mapping_rule(self, rule_id: int) -> dict:
        return self._unpack_mapping_rule(self._one("mapping_rules", rule_id))

    def list_mapping_rules(self, *, search: str = "", active: bool | None = None,
                           bank: str | None = None) -> list[dict]:
        require_text(search, "Mapping search", allow_empty=True)
        conditions, parameters = [], []
        if bank is not None:
            require_text(bank, "Bank")
            conditions.append("(bank = ? OR bank IS NULL)")
            parameters.append(bank)
        if active is not None:
            if type(active) is not bool:
                raise ValueError("Active filter must be boolean.")
            conditions.append("active = ?")
            parameters.append(int(active))
        if search.strip():
            conditions.append(
                "(instr(unicode_casefold(rule_name), unicode_casefold(?)) > 0 "
                "OR instr(unicode_casefold(match_value), unicode_casefold(?)) > 0)"
            )
            parameters.extend((search.strip(), search.strip()))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        order = (
            " ORDER BY CASE source_field WHEN 'pos_id' THEN 0 WHEN 'merchant' THEN 1 "
            "WHEN 'description' THEN 2 ELSE 3 END, priority DESC, id"
        )
        return [
            self._unpack_mapping_rule(row)
            for row in self._rows("SELECT * FROM mapping_rules" + where + order, tuple(parameters))
        ]

    def set_mapping_rule_active(self, rule_id: int, active: bool, *, expected_revision: int) -> None:
        if type(active) is not bool:
            raise ValueError("Mapping rule state must be boolean.")
        with self._write():
            current = self.get_mapping_rule(rule_id)
            if current["revision"] != expected_revision:
                raise ValueError("Mapping rule changed; refresh before editing.")
            if current["active"] != int(active):
                self._connection.execute(
                    "UPDATE mapping_rules SET active=?, updated_at=?, revision=revision+1 WHERE id=?",
                    (int(active), _now(), rule_id),
                )

    def delete_mapping_rule(self, rule_id: int, *, expected_revision: int) -> None:
        with self._write():
            current = self.get_mapping_rule(rule_id)
            if current["revision"] != expected_revision:
                raise ValueError("Mapping rule changed; refresh before deleting.")
            self._connection.execute("DELETE FROM mapping_rules WHERE id=?", (rule_id,))

    def apply_mapping_classification(self, transaction_id: int, rule_id: int, *,
                                     expected_revision: str, merchant_key: str | None = None) -> None:
        """Apply one verified mapping to an unlocked unclassified row with audit."""
        with self._write():
            row = next((r for r in self.classification_rows(transaction_id=transaction_id)), None)
            rule = self.get_mapping_rule(rule_id)
            if row is None or classification_revision(row) != expected_revision:
                raise ValueError("Transaction changed; preview the mapping rule again.")
            if (not rule["active"] or row["manual_lock"]
                    or row["classification_source"] != "unclassified"
                    or row["kind"] != "unclassified" or row["category_id"] is not None):
                raise ValueError("Transaction is protected or no longer eligible.")
            if rule["account_id"] is not None and rule["account_id"] != row["account_id"]:
                raise ValueError("Mapping account scope does not match.")
            if rule["bank"] is not None and rule["bank"] != row["bank"]:
                raise ValueError("Mapping bank scope does not match.")
            sign = "debit" if row["amount_minor"] < 0 else "credit" if row["amount_minor"] > 0 else "zero"
            if rule["direction"] not in ("any", sign) or row["currency"] != row["original_currency"]:
                raise ValueError("Mapping direction or currency is incompatible.")
            if (rule["target_kind"] == "income" and row["amount_minor"] <= 0
                    or rule["target_kind"] == "expense" and row["amount_minor"] >= 0):
                raise ValueError("Mapping target kind is incompatible with the signed amount.")
            if rule["category_id"] is not None:
                self._validate_category(rule["target_kind"], rule["category_id"])
            changes = {
                "kind": rule["target_kind"],
                "category_id": rule["category_id"],
                "classification_source": "rule",
                "applied_rule_id": None,
                "applied_rule_revision": None,
                "applied_mapping_rule_id": rule["id"],
                "applied_mapping_rule_name": rule["rule_name"],
            }
            if merchant_key is not None:
                changes["merchant_key"] = merchant_key
            delta = {key: {"old": row[key], "new": value} for key, value in changes.items()
                     if row[key] != value}
            if delta:
                assignments = ", ".join(f"{key} = ?" for key in delta)
                self._connection.execute(
                    f"UPDATE transactions SET {assignments} WHERE id=?",
                    tuple(change["new"] for change in delta.values()) + (transaction_id,),
                )
                self._connection.execute(
                    "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                    (transaction_id, _now(), "Classification mapping rule applied",
                     json.dumps(delta, ensure_ascii=False)),
                )

    def classification_rows(self, *, import_id: int | None = None,
                            transaction_id: int | None = None,
                            include_archived: bool = False) -> list[dict]:
        conditions, parameters = [], []
        if not include_archived and self._has_column("transactions", "is_archived"):
            conditions.append("t.is_archived = 0")
        if import_id is not None:
            require_integer(import_id, "Import ID", 1)
            conditions.append("i.id = ?")
            parameters.append(import_id)
        if transaction_id is not None:
            require_integer(transaction_id, "Transaction ID", 1)
            conditions.append("t.id = ?")
            parameters.append(transaction_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return [
            self._normalize_transaction(row)
            for row in self._rows(
                "SELECT t.*, i.account_id, i.parser_version, a.bank, a.name AS account_name FROM transactions t "
                "JOIN imports i ON i.id = t.import_id JOIN accounts a ON a.id = i.account_id"
                + where + " ORDER BY t.id", parameters,
            )
        ]


    @staticmethod
    def rule_eligible(row: dict, merchant: MerchantMatch, rule: dict) -> bool:
        sign = "debit" if row["amount_minor"] < 0 else "credit" if row["amount_minor"] > 0 else "zero"
        source_sign = "debit" if row["original_amount_minor"] < 0 else "credit" if row["original_amount_minor"] > 0 else "zero"
        merchant_sign = "debit" if merchant.transaction_type == "purchase" else "credit"
        return bool(rule["active"] and not row["manual_lock"]
                    and row["kind"] not in ("transfer", "excluded")
                    and row["bank"] == rule["bank"] and merchant.key == rule["merchant_key"]
                    and sign == source_sign == merchant_sign == rule["direction"]
                    and rule["kind"] == ("expense" if sign == "debit" else "income")
                    and rule["category_id"] is not None)

    def _apply_classification(self, row: dict, merchant: MerchantMatch, rule: dict | None) -> None:
        changes = {"merchant_key": merchant.key, "merchant_display": merchant.display_text,
                   "merchant_pattern": merchant.pattern, "merchant_type": merchant.transaction_type}
        if rule is not None:
            changes.update(kind=rule["kind"], category_id=rule["category_id"], classification_source="rule",
                           applied_rule_id=rule["id"], applied_rule_revision=rule["revision"])
            self._validate_category(rule["kind"], rule["category_id"])
        delta = {key: {"old": row[key], "new": value} for key, value in changes.items() if row[key] != value}
        if delta:
            assignments = ", ".join(f"{key} = ?" for key in delta)
            self._connection.execute(f"UPDATE transactions SET {assignments} WHERE id = ?",
                                     tuple(item["new"] for item in delta.values()) + (row["id"],))
            self._connection.execute(
                "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                (row["id"], _now(), "Saved merchant rule applied" if rule else "Verified POS merchant recognized",
                 json.dumps(delta, ensure_ascii=False)),
            )

    def classify_import(self, import_id: int, merchants: dict[int, MerchantMatch]) -> None:
        """Apply current scoped rules only to new unlocked import rows, atomically."""
        if self._classifying_import_id != import_id or not self._connection.in_transaction:
            raise ValueError("Automatic classification requires a new import commit; preview a rule for existing rows.")
        with self._write():
            rows = {r["id"]: r for r in self.classification_rows(import_id=import_id)}
            if not merchants.keys() <= rows.keys():
                raise ValueError("Merchant selections must belong to this import.")
            rules = {(r["bank"], r["merchant_key"], r["direction"]): r for r in self.list_rules()}
            for identifier, merchant in merchants.items():
                row = rows[identifier]
                if row["manual_lock"] or row["classification_source"] != "unclassified" or row["kind"] != "unclassified":
                    continue
                if not isinstance(merchant, MerchantMatch):
                    raise ValueError("A verified merchant match is required.")
                direction = "debit" if merchant.transaction_type == "purchase" else "credit"
                rule = rules.get((row["bank"], merchant.key, direction))
                if rule is not None and not self.rule_eligible(row, merchant, rule):
                    rule = None
                self._apply_classification(row, merchant, rule)

    def apply_rule(self, rule_id: int, selections: Iterable[RuleSelection], *, expected_revision: int) -> int:
        """Apply only selected, unchanged, eligible rows; audit and rollback as a batch."""
        selections = tuple(selections)
        if any(not isinstance(s, RuleSelection) for s in selections):
            raise ValueError("Rule selections must come from a preview.")
        if len({s.transaction_id for s in selections}) != len(selections):
            raise ValueError("Select each transaction only once.")
        with self._write():
            rule = self.get_rule(rule_id)
            if not rule["active"] or rule["revision"] != expected_revision:
                raise ValueError("Rule changed or was disabled; create a new preview.")
            rows = {r["id"]: r for r in self.classification_rows()}
            for selection in selections:
                row = rows.get(selection.transaction_id)
                if (row is None or classification_revision(row) != selection.revision
                        or not self.rule_eligible(row, selection.merchant, rule)):
                    raise ValueError("Selected transaction changed or is ineligible; create a new preview.")
                self._apply_classification(row, selection.merchant, rule)
        return len(selections)

    # -------------------------------------------------------------------------
    # Monthly Budget Management
    # -------------------------------------------------------------------------

    def create_budget(self, *, month: str, currency: str, category_id: int,
                      planned_amount_minor: int, note: str = "", active: bool = True) -> int:
        month = validate_month(month)
        currency = validate_currency(currency)
        require_integer(category_id, "Category ID", 1)
        require_integer(planned_amount_minor, "Planned amount", 1)
        require_text(note, "Budget note", allow_empty=True)
        if type(active) is not bool:
            raise ValueError("Active must be boolean.")

        category = self._one("categories", category_id)
        if category["direction"] not in ("income", "expense"):
            raise ValueError("Category must be an income or expense category.")

        existing = self._connection.execute(
            "SELECT id FROM budgets WHERE month = ? AND currency = ? AND category_id = ?",
            (month, currency, category_id),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"A budget for {month}, {currency}, and category already exists.")

        now = _now()
        with self._write():
            return self._connection.execute(
                """INSERT INTO budgets(month, currency, category_id, planned_amount_minor,
                   note, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (month, currency, category_id, planned_amount_minor, note.strip(), int(active), now, now),
            ).lastrowid

    def update_budget(self, budget_id: int, *, planned_amount_minor: int | None = None,
                      note: str | None = None, active: bool | None = None,
                      category_id: int | None = None, month: str | None = None,
                      currency: str | None = None) -> None:
        require_integer(budget_id, "Budget ID", 1)
        current = self.get_budget(budget_id)
        if current is None:
            raise ValueError(f"No budget with ID {budget_id}.")

        new_month = validate_month(month) if month is not None else current["month"]
        new_currency = validate_currency(currency) if currency is not None else current["currency"]
        new_category_id = current["category_id"] if category_id is None else category_id
        require_integer(new_category_id, "Category ID", 1)
        category = self._one("categories", new_category_id)
        if category["direction"] not in ("income", "expense"):
            raise ValueError("Category must be an income or expense category.")

        new_amount = current["planned_amount_minor"] if planned_amount_minor is None else planned_amount_minor
        require_integer(new_amount, "Planned amount", 1)
        new_note = current["note"] if note is None else note
        require_text(new_note, "Budget note", allow_empty=True)
        new_active = current["active"] if active is None else active
        if type(new_active) is not bool:
            raise ValueError("Active must be boolean.")

        if (new_month != current["month"] or new_currency != current["currency"] or new_category_id != current["category_id"]):
            dup = self._connection.execute(
                "SELECT id FROM budgets WHERE month = ? AND currency = ? AND category_id = ? AND id != ?",
                (new_month, new_currency, new_category_id, budget_id),
            ).fetchone()
            if dup is not None:
                raise ValueError(f"A budget for {new_month}, {new_currency}, and category already exists.")

        now = _now()
        with self._write():
            self._connection.execute(
                """UPDATE budgets SET month = ?, currency = ?, category_id = ?,
                   planned_amount_minor = ?, note = ?, active = ?, updated_at = ?
                   WHERE id = ?""",
                (new_month, new_currency, new_category_id, new_amount, new_note.strip(), int(new_active), now, budget_id),
            )

    def set_budget_active(self, budget_id: int, active: bool) -> None:
        require_integer(budget_id, "Budget ID", 1)
        if type(active) is not bool:
            raise ValueError("Active must be boolean.")
        with self._write():
            self.update_budget(budget_id, active=active)

    def delete_budget(self, budget_id: int) -> None:
        require_integer(budget_id, "Budget ID", 1)
        with self._write():
            self._connection.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))

    def get_budget(self, budget_id: int) -> dict | None:
        require_integer(budget_id, "Budget ID", 1)
        row = self._connection.execute(
            """SELECT b.*, c.name AS category_name, c.direction AS category_direction
               FROM budgets b JOIN categories c ON c.id = b.category_id
               WHERE b.id = ?""",
            (budget_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_budgets(self, *, month: str | None = None, currency: str | None = None,
                     category_id: int | None = None, active: bool | None = None,
                     direction: str | None = None) -> list[dict]:
        conditions, parameters = [], []
        if month is not None:
            month = validate_month(month)
            conditions.append("b.month = ?")
            parameters.append(month)
        if currency is not None:
            currency = validate_currency(currency)
            conditions.append("b.currency = ?")
            parameters.append(currency)
        if category_id is not None:
            require_integer(category_id, "Category ID", 1)
            conditions.append("b.category_id = ?")
            parameters.append(category_id)
        if active is not None:
            if type(active) is not bool:
                raise ValueError("Active filter must be boolean.")
            conditions.append("b.active = ?")
            parameters.append(int(active))
        if direction is not None:
            if direction not in ("income", "expense"):
                raise ValueError("Direction must be income or expense.")
            conditions.append("c.direction = ?")
            parameters.append(direction)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = (
            "SELECT b.*, c.name AS category_name, c.direction AS category_direction "
            "FROM budgets b JOIN categories c ON c.id = b.category_id"
            + where +
            " ORDER BY b.month DESC, b.currency, c.direction, c.name, b.id"
        )
        return self._rows(sql, tuple(parameters))

    def budget_summary(self, month: str, currency: str | None = None) -> dict:
        month = validate_month(month)
        conditions = ["b.month = ?", "b.active = 1"]
        parameters = [month]
        if currency is not None:
            currency = validate_currency(currency)
            conditions.append("b.currency = ?")
            parameters.append(currency)
        where = " WHERE " + " AND ".join(conditions)
        sql = (
            "SELECT b.currency, c.direction, SUM(b.planned_amount_minor) AS total_minor, COUNT(*) as count "
            "FROM budgets b JOIN categories c ON c.id = b.category_id"
            + where +
            " GROUP BY b.currency, c.direction"
        )
        rows = self._rows(sql, tuple(parameters))
        currencies = {}
        for r in rows:
            curr = r["currency"]
            entry = currencies.setdefault(curr, {
                "currency": curr,
                "planned_income": 0,
                "planned_expense": 0,
                "income_count": 0,
                "expense_count": 0,
            })
            if r["direction"] == "income":
                entry["planned_income"] = r["total_minor"]
                entry["income_count"] = r["count"]
            else:
                entry["planned_expense"] = r["total_minor"]
                entry["expense_count"] = r["count"]
        return currencies


    # -------------------------------------------------------------------------
    # Selective Transaction Archive / Soft-Delete
    # -------------------------------------------------------------------------

    def archive_transactions(self, transaction_ids: Iterable[int]) -> int:
        """Soft-delete/archive transactions; preserve source, balance, and audit history."""
        selected_ids = tuple(transaction_ids)
        if not selected_ids:
            return 0
        for tid in selected_ids:
            require_integer(tid, "Transaction ID", 1)
        ids = tuple(dict.fromkeys(selected_ids))
        now = _now()
        with self._write():
            for tid in ids:
                tx = self.get_transaction(tid)
                if tx and not tx.get("is_archived"):
                    delta = {"is_archived": {"old": 0, "new": 1}, "archived_at": {"old": None, "new": now}}
                    self._connection.execute(
                        "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                        (tid, now, "Transaction archived", json.dumps(delta, ensure_ascii=False)),
                    )
            placeholders = ",".join("?" for _ in ids)
            cur = self._connection.execute(
                f"UPDATE transactions SET is_archived = 1, archived_at = ? "
                f"WHERE is_archived = 0 AND id IN ({placeholders})",
                (now, *ids),
            )
            return cur.rowcount

    def restore_transactions(self, transaction_ids: Iterable[int]) -> int:
        """Restore archived transactions back to normal view and reporting."""
        selected_ids = tuple(transaction_ids)
        if not selected_ids:
            return 0
        for tid in selected_ids:
            require_integer(tid, "Transaction ID", 1)
        ids = tuple(dict.fromkeys(selected_ids))
        now = _now()
        with self._write():
            for tid in ids:
                tx = self.get_transaction(tid)
                if tx and tx.get("is_archived"):
                    delta = {"is_archived": {"old": 1, "new": 0}, "archived_at": {"old": tx.get("archived_at"), "new": None}}
                    self._connection.execute(
                        "INSERT INTO transaction_edits(transaction_id, edited_at, reason, changes_json) VALUES (?, ?, ?, ?)",
                        (tid, now, "Transaction restored from archive", json.dumps(delta, ensure_ascii=False)),
                    )
            placeholders = ",".join("?" for _ in ids)
            cur = self._connection.execute(
                f"UPDATE transactions SET is_archived = 0, archived_at = NULL "
                f"WHERE is_archived = 1 AND id IN ({placeholders})",
                ids,
            )
            return cur.rowcount
