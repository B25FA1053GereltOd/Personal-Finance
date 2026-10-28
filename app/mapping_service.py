"""Priority-ordered, deterministic user mapping rules."""

import re
import unicodedata
from dataclasses import dataclass, field
from uuid import uuid4

from app.db import classification_revision
from app.models import normalize_merchant_key, require_integer, require_text


@dataclass(frozen=True)
class MappingPreview:
    token: str = field(repr=False)
    rule: dict = field(repr=False)
    rows: tuple[dict, ...] = field(repr=False)
    revisions: dict[int, str] = field(repr=False)


class MappingBlocked(ValueError):
    """Safe diagnostic for rejected mapping operations."""


class MappingService:
    _FIELD_PRIORITY = {"pos_id": 0, "merchant": 1, "description": 2}

    def __init__(self, repository):
        self.repository = repository
        self.pending: MappingPreview | None = None

    @staticmethod
    def warnings(rule: dict) -> tuple[str, ...]:
        if rule.get("operator") != "contains":
            return ()
        value = rule.get("match_value", "").strip()
        if len(value) == 1:
            return ("One-character Contains rules can match many transactions; verify scope and preview carefully.",)
        if len(value) < 4 or (rule.get("bank") is None and rule.get("account_id") is None):
            return ("This Contains rule may be broad; verify scope and preview matching transactions.",)
        return ()

    def save_rule(self, **values) -> dict:
        warnings = self.warnings(values)
        try:
            identifier = self.repository.save_mapping_rule(**values)
        except (ValueError, TypeError) as error:
            raise MappingBlocked(str(error)) from None
        return {"rule": self.repository.get_mapping_rule(identifier), "warnings": warnings}

    def set_active(self, rule_id: int, active: bool, expected_revision: int) -> dict:
        try:
            self.repository.set_mapping_rule_active(rule_id, active, expected_revision=expected_revision)
        except (ValueError, TypeError) as error:
            raise MappingBlocked(str(error)) from None
        return self.repository.get_mapping_rule(rule_id)

    def delete_rule(self, rule_id: int, expected_revision: int) -> None:
        try:
            self.repository.delete_mapping_rule(rule_id, expected_revision=expected_revision)
        except (ValueError, TypeError) as error:
            raise MappingBlocked(str(error)) from None

    @staticmethod
    def _value(row: dict, source_field: str, merchant_key: str | None):
        if source_field == "pos_id":
            return row.get("pos_id")
        if source_field == "merchant":
            return merchant_key or row.get("merchant_key") or row.get("merchant_display")
        if source_field == "description":
            return row.get("original_description") or row.get("description")
        raise MappingBlocked("Unsupported mapping source field.")

    @staticmethod
    def _normalized(value: str, source_field: str) -> str:
        if source_field == "pos_id":
            return unicodedata.normalize("NFC", value).strip().casefold()
        return normalize_merchant_key(value)

    @classmethod
    def matches(cls, rule: dict, row: dict, merchant_key: str | None = None) -> bool:
        value = cls._value(row, rule["source_field"], merchant_key)
        if value is None or not str(value).strip() or not str(rule.get("match_value", "")).strip():
            return False
        source = cls._normalized(str(value), rule["source_field"])
        wanted = str(rule["match_value"])
        if rule["operator"] == "regex":
            try:
                return re.search(wanted, source, re.IGNORECASE) is not None
            except re.error:
                return False
        wanted = cls._normalized(wanted, rule["source_field"])
        if rule["operator"] == "exact":
            if source == wanted:
                return True
            if rule["source_field"] == "description" and " " not in wanted:
                return wanted in source.split() or wanted in re.findall(r"[^\W_]+", source)
            return False
        if rule["operator"] == "contains":
            return wanted in source
        if rule["operator"] == "starts_with":
            return source.startswith(wanted)
        if rule["operator"] == "ends_with":
            return source.endswith(wanted)
        return False

    @staticmethod
    def _direction(row: dict) -> str:
        amount = row["amount_minor"]
        return "debit" if amount < 0 else "credit" if amount > 0 else "zero"

    @classmethod
    def eligible(cls, rule: dict, row: dict) -> bool:
        if (not rule["active"] or row["manual_lock"]
                or row["classification_source"] != "unclassified"
                or row["kind"] != "unclassified" or row["category_id"] is not None):
            return False
        if rule["bank"] is not None and rule["bank"] != row["bank"]:
            return False
        if rule["account_id"] is not None and rule["account_id"] != row["account_id"]:
            return False
        direction = cls._direction(row)
        if rule["direction"] not in ("any", direction):
            return False
        if rule["target_kind"] == "income" and direction != "credit":
            return False
        if rule["target_kind"] == "expense" and direction != "debit":
            return False
        return row["currency"] == row["original_currency"]

    def winning_rule(self, row: dict, merchant_key: str | None = None):
        rules = sorted(
            self.repository.list_mapping_rules(active=True),
            key=lambda r: (
                self._FIELD_PRIORITY.get(r["source_field"], 99),
                -int(r["priority"]),
                int(r["id"]),
            ),
        )
        for rule in rules:
            if (self.eligible(rule, row)
                    and self.matches(rule, row, merchant_key)):
                return rule
        return None

    def test_rule(self, rule: dict, sample: str) -> dict:
        require_text(sample, "Synthetic sample", allow_empty=True)
        if rule.get("operator") == "regex":
            try:
                re.compile(rule.get("match_value", ""))
            except re.error:
                raise MappingBlocked("Regular expression is invalid.") from None
        row = {
            "pos_id": sample if rule["source_field"] == "pos_id" else None,
            "merchant_key": sample if rule["source_field"] == "merchant" else None,
            "original_description": sample if rule["source_field"] == "description" else "",
        }
        return {"matched": self.matches(rule, row), "warnings": self.warnings(rule)}

    def preview(self, rule_id: int) -> MappingPreview:
        if self.pending is not None:
            raise MappingBlocked("Apply or cancel the current mapping preview first.")
        try:
            rule = self.repository.get_mapping_rule(rule_id)
        except ValueError as error:
            raise MappingBlocked(str(error)) from None
        if not rule["active"]:
            raise MappingBlocked("Enable the mapping rule before previewing it.")
        candidates = []
        revisions = {}
        for row in self.repository.classification_rows():
            winner = self.winning_rule(row)
            if winner and winner["id"] == rule_id:
                candidates.append(row)
                revisions[row["id"]] = classification_revision(row)
        preview = MappingPreview(uuid4().hex, rule, tuple(candidates), revisions)
        self.pending = preview
        return preview

    def cancel(self) -> None:
        self.pending = None

    def apply(self, token: str, transaction_ids) -> int:
        preview = self.pending
        if preview is None or token != preview.token:
            raise MappingBlocked("Create a fresh mapping preview.")
        identifiers = tuple(transaction_ids)
        if not identifiers:
            raise MappingBlocked("Select eligible transactions to apply; no rows are selected by default.")
        for identifier in identifiers:
            require_integer(identifier, "Transaction ID", 1)
        if len(set(identifiers)) != len(identifiers):
            raise MappingBlocked("Select each transaction only once.")
        if not set(identifiers) <= preview.revisions.keys():
            raise MappingBlocked("Select only transactions from this preview.")
        try:
            with self.repository.atomic():
                current_rule = self.repository.get_mapping_rule(preview.rule["id"])
                if (not current_rule["active"]
                        or current_rule["revision"] != preview.rule["revision"]):
                    raise MappingBlocked("Mapping rule changed; preview it again.")
                for identifier in identifiers:
                    full_row = self.repository.classification_rows(transaction_id=identifier)[0]
                    if (classification_revision(full_row) != preview.revisions[identifier]
                            or not self.eligible(current_rule, full_row)
                            or not self.matches(current_rule, full_row)):
                        raise MappingBlocked("A selected transaction changed or is no longer eligible.")
                    self.repository.apply_mapping_classification(
                        identifier, current_rule["id"],
                        expected_revision=preview.revisions[identifier])
        except MappingBlocked:
            raise
        except (ValueError, TypeError) as error:
            raise MappingBlocked(str(error)) from None
        self.pending = None
        return len(identifiers)

    def classify_import(self, import_id: int, merchants: dict[int, object]) -> None:
        rows = self.repository.classification_rows(import_id=import_id)
        for row in rows:
            if row["manual_lock"] or row["classification_source"] != "unclassified":
                continue
            merchant = merchants.get(row["id"])
            merchant_key = merchant.key if merchant is not None else None
            rule = self.winning_rule(row, merchant_key)
            if rule is not None:
                self.repository.apply_mapping_classification(
                    row["id"], rule["id"],
                    expected_revision=classification_revision(row),
                    merchant_key=merchant_key)
