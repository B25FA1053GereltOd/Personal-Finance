"""SQLite repository. All writes are atomic; source rows are immutable.

The UI deliberately does not open this repository until its integration step.
See docs/database.md for the small public API and row field conventions.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import get_data_dir
from app.models import (
    DEFAULT_CATEGORIES, KINDS, ImportDecision, ImportInfo, ImportRow, require_integer,
    require_text, validate_currency, validate_iso,
)


SCHEMA_VERSION = 2
_EDITABLE = frozenset({
    "description", "occurred_at", "amount_minor", "currency", "reference",
    "balance_minor", "kind", "category_id", "merchant_key", "note", "manual_lock",
})
_SOURCE_COLUMNS = (
    "id", "source_id", "import_id", "bank_datetime", "worksheet", "row_number",
    "dedup_key", "original_description", "original_occurred_at", "original_amount_minor",
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


class ImportStateChanged(ValueError):
    """An import preview must be refreshed before confirmation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._connection.execute("PRAGMA foreign_keys = ON")
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

    @contextmanager
    def _write(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def initialize(self) -> None:
        """Initialize once or atomically migrate version 1's decision storage."""
        with self._write():
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                return
            if version == 1:
                for statement in _IMPORT_SCHEMA:
                    self._connection.execute(statement)
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
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _rows(self, sql: str, parameters: tuple = ()) -> list[dict]:
        return [dict(row) for row in self._connection.execute(sql, parameters)]

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
                     decisions: Iterable[ImportDecision] = ()) -> int:
        """Store all rows, metadata and decisions atomically; optionally guard a preview."""
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
                        row_number, dedup_key, original_description, original_occurred_at,
                        original_amount_minor, original_currency, original_reference, original_balance_minor,
                        description, occurred_at, amount_minor, currency, reference, balance_minor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (uuid4().hex, import_id, row.bank_datetime, row.worksheet, row.row_number,
                     row.dedup_key, row.description, row.occurred_at, row.amount_minor, row.currency,
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

    def get_transaction(self, transaction_id: int) -> dict:
        return self._one("transactions", transaction_id)

    def query_transactions(self, *, account_id: int | None = None, import_id: int | None = None,
                           kind: str | None = None, category_id: int | None = None,
                           review_only: bool = False, date_from: str | None = None,
                           date_to: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """Filter effective values; stable bank-local ISO order, newest first."""
        require_integer(limit, "Page size", 1)
        if limit > 1000:
            raise ValueError("Page size cannot exceed 1000.")
        require_integer(offset, "Page offset", 0)
        if type(review_only) is not bool:
            raise ValueError("review_only must be a boolean.")
        conditions, parameters = [], []
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
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self._rows(
            "SELECT t.*, i.account_id FROM transactions t JOIN imports i ON i.id = t.import_id" + where
            + " ORDER BY t.occurred_at DESC, t.id DESC LIMIT ? OFFSET ?", tuple(parameters + [limit, offset]),
        )

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
            self._validate_effective(after, before["original_currency"])
            delta = {key: {"old": before[key], "new": after[key]}
                     for key in sorted(_EDITABLE | {"classification_source"}) if before[key] != after[key]}
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

    def get_history(self, transaction_id: int) -> list[dict]:
        self.get_transaction(transaction_id)
        rows = self._rows("SELECT * FROM transaction_edits WHERE transaction_id = ? ORDER BY id", (transaction_id,))
        for row in rows:
            row["changes"] = json.loads(row.pop("changes_json"))
        return rows

    def upsert_rule(self, merchant_key: str, direction: str, kind: str, category_id: int | None = None) -> int:
        """Create/update one exact merchant-key/sign rule; does not classify rows."""
        require_text(merchant_key, "Merchant key")
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
                """INSERT INTO merchant_rules(merchant_key, direction, kind, category_id) VALUES (?, ?, ?, ?)
                    ON CONFLICT(merchant_key, direction) DO UPDATE SET kind = excluded.kind, category_id = excluded.category_id""",
                (merchant_key, direction, kind, category_id),
            )
            return self._connection.execute(
                "SELECT id FROM merchant_rules WHERE merchant_key = ? AND direction = ?", (merchant_key, direction)
            ).fetchone()[0]

    def list_rules(self) -> list[dict]:
        return self._rows("SELECT * FROM merchant_rules ORDER BY id")

    def delete_rule(self, rule_id: int) -> None:
        with self._write():
            self._one("merchant_rules", rule_id)
            self._connection.execute("DELETE FROM merchant_rules WHERE id = ?", (rule_id,))
