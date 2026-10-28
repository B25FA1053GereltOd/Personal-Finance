"""Preview and explicitly confirm complete imports; never log statement values."""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from app.db import ImportStateChanged, Repository
from app.classification import ClassificationBlocked, ClassificationService
from app.models import ImportDecision, ImportInfo, ImportRow, require_text
from app.parsers.base import ParseIssue, ParseResult, StatementParser
from app.parsers.khan import KhanParser


class ImportBlocked(ValueError):
    """The caller must resolve validation, decisions, or a stale preview."""


@dataclass(frozen=True, kw_only=True)
class VerifiedReferencePolicy:
    """Developer-supplied evidence of stable, per-account unique references.

    No such policy exists for the observed Khan format. This is not a user
    preference or a flag to enable optimistic deduplication.
    """

    bank: str
    parser_version: str
    namespace: str
    evidence: str

    def __post_init__(self) -> None:
        for name in ("bank", "parser_version", "namespace", "evidence"):
            require_text(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class ExistingRow:
    transaction_id: int
    import_id: int
    source: ImportRow = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class PreviewRow:
    index: int
    source: ImportRow = field(repr=False)
    status: str  # valid, invalid, duplicate, ambiguous
    candidates: tuple[ExistingRow, ...] = field(default=(), repr=False)
    matched_rule: str | None = field(default=None, repr=False)
    matched_category: str | None = field(default=None, repr=False)
    classification_source: str = "unclassified"


@dataclass(frozen=True, kw_only=True)
class AmbiguousGroup:
    row_indexes: tuple[int, ...]
    existing: tuple[ExistingRow, ...] = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class ImportPreview:
    token: str = field(repr=False)
    info: ImportInfo | None = field(repr=False)
    revision: str = field(repr=False)
    rows: tuple[PreviewRow, ...] = field(repr=False)
    groups: tuple[AmbiguousGroup, ...] = field(repr=False)
    issues: tuple[ParseIssue, ...]
    valid_count: int
    invalid_count: int
    duplicate_count: int
    ambiguous_count: int
    identical_import_id: int | None = None

    @property
    def is_valid(self) -> bool:
        return (self.info is not None and self.invalid_count == 0
                and not any(i.severity == "error" for i in self.issues))


@dataclass(frozen=True, kw_only=True)
class ImportResult:
    status: str  # committed or identical_file
    import_id: int
    imported_count: int
    skipped_count: int


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _core(row: ImportRow) -> tuple:
    # ISO text retains supplied date/time precision; never round or normalize it.
    return row.currency, row.occurred_at, row.amount_minor, row.description


def _identity(row: ImportRow) -> tuple:
    return *_core(row), row.reference, row.balance_minor


def _compatible(left: ImportRow, right: ImportRow) -> bool:
    return _core(left) == _core(right) and all(
        a is None or b is None or a == b
        for a, b in ((left.reference, right.reference), (left.balance_minor, right.balance_minor))
    )


def _existing(row: dict) -> ExistingRow:
    return ExistingRow(transaction_id=row["id"], import_id=row["import_id"], source=ImportRow(
        description=row["original_description"], bank_datetime=row["bank_datetime"],
        occurred_at=row["original_occurred_at"], amount_minor=row["original_amount_minor"],
        currency=row["original_currency"], reference=row["original_reference"],
        balance_minor=row["original_balance_minor"], worksheet=row["worksheet"],
        row_number=row["row_number"], dedup_key=row["dedup_key"],
    ))


def _groups(rows: tuple[PreviewRow, ...]) -> tuple[AmbiguousGroup, ...]:
    """Connected candidate groups; row-level candidate edges remain explicit."""
    pending = {r.index: r for r in rows if r.status == "ambiguous"}
    by_existing = defaultdict(set)
    for row in pending.values():
        for candidate in row.candidates:
            by_existing[candidate.transaction_id].add(row.index)
    groups = []
    while pending:
        stack = [min(pending)]
        indexes, existing = set(), {}
        while stack:
            index = stack.pop()
            if index not in pending:
                continue
            row = pending.pop(index)
            indexes.add(index)
            for candidate in row.candidates:
                existing[candidate.transaction_id] = candidate
                stack.extend(by_existing[candidate.transaction_id] & pending.keys())
        groups.append(AmbiguousGroup(row_indexes=tuple(sorted(indexes)),
                                     existing=tuple(existing[i] for i in sorted(existing))))
    return tuple(groups)


def _validate_skip_multiplicity(rows: tuple[PreviewRow, ...], actions: Mapping[int, str]) -> None:
    """Each skipped incoming occurrence must match a distinct existing occurrence.

    An iterative augmenting-path search also handles optional-value wildcard
    groups without assuming all candidates are interchangeable.
    """
    edges = {r.index: tuple(c.transaction_id for c in r.candidates) for r in rows
             if r.status == "duplicate" or actions.get(r.index) == "skip"}
    owner: dict[int, int] = {}
    assigned: dict[int, int] = {}
    for start in edges:
        queue, visited, via = [start], {start}, {}
        free = None
        for current in queue:
            for candidate in edges[current]:
                if candidate in via:
                    continue
                via[candidate] = current
                if candidate not in owner:
                    free = candidate
                    break
                displaced = owner[candidate]
                if displaced not in visited:
                    visited.add(displaced)
                    queue.append(displaced)
            if free is not None:
                break
        if free is None:
            raise ImportBlocked("Too many rows marked skip for the existing occurrences; keep the unmatched rows.")
        while free is not None:
            incoming = via[free]
            previous = assigned.get(incoming)
            owner[free], assigned[incoming] = incoming, free
            free = previous


class ImportService:
    """Own in-memory previews; repository initialization precedes this workflow."""

    def __init__(self, repository: Repository, parser: StatementParser | None = None, *,
                 reference_policy: VerifiedReferencePolicy | None = None,
                 classification: ClassificationService | None = None) -> None:
        self.repository = repository
        self.parser = parser if parser is not None else KhanParser()
        self.reference_policy = reference_policy
        self.classification = classification if classification is not None else ClassificationService(repository)
        if self.classification.repository is not repository:
            raise ValueError("Import and classification must share the same repository.")
        self._pending: dict[str, ImportPreview] = {}

    def preview(self, path: str | Path, account_id: int) -> ImportPreview:
        """Read once, hash/parse identical bytes, and compare a read-only snapshot."""
        state = self.repository.get_import_state(account_id)
        path = Path(path)
        info = None
        if path.suffix.lower() != ".xlsx":
            parsed = ParseResult(issues=(ParseIssue("unsupported_file", "Select an XLSX statement."),))
        else:
            try:
                payload = path.read_bytes()
            except OSError:
                parsed = ParseResult(issues=(ParseIssue("unreadable_file", "Statement could not be read."),))
            else:
                # No source copy is written. The preview confirms this snapshot,
                # even if the original file changes after it was read.
                parsed = self.parser.parse_bytes(payload)
                info = ImportInfo(account_id=account_id, sha256=hashlib.sha256(payload).hexdigest(),
                                  parser_version=self.parser.version, filename=path.name)
        issues = list(parsed.issues)
        account = state["account"]
        metadata = parsed.metadata
        policy = self.reference_policy
        if metadata is None and not any(i.severity == "error" for i in issues):
            issues.append(ParseIssue("missing_metadata", "Statement metadata is required."))
        if metadata is not None:
            if metadata.account_identifier != account["identifier"] or metadata.currency != account["currency"]:
                issues.append(ParseIssue("account_mismatch", "Statement account/currency does not match the selected account."))
            if metadata.parser_version != self.parser.version:
                issues.append(ParseIssue("parser_version_mismatch", "Parser metadata version is inconsistent."))
        if isinstance(self.parser, KhanParser) and account["bank"] != "Khan Bank":
            issues.append(ParseIssue("bank_mismatch", "Khan statements require a Khan Bank account."))
        if policy is not None and (policy.bank != account["bank"] or policy.parser_version != self.parser.version):
            issues.append(ParseIssue("reference_policy_mismatch", "Verified reference policy does not cover this bank/parser."))
            policy = None
        if any(c.outcome == "failed" for c in parsed.checks):
            issues.append(ParseIssue("failed_reconciliation", "Statement reconciliation failed."))
        if parsed.candidate_row_count != len(parsed.records):
            issues.append(ParseIssue("incomplete_rows", "Every candidate transaction row must parse successfully."))

        invalid = set()
        row_error_numbers = {i.row_number for i in issues if i.severity == "error" and i.row_number is not None}
        for index, record in enumerate(parsed.records):
            if record.source.row_number in row_error_numbers:
                invalid.add(index)
            if record.source.currency != account["currency"]:
                invalid.add(index)
                issues.append(ParseIssue("row_currency_mismatch", "Transaction currency does not match the account.",
                                         row_number=record.source.row_number))
        if policy is not None:
            references = Counter(r.source.reference for r in parsed.records if r.source.reference)
            for index, record in enumerate(parsed.records):
                if record.source.reference and references[record.source.reference] > 1:
                    invalid.add(index)
                    issues.append(ParseIssue("reference_collision", "A verified unique reference repeats in the statement.",
                                             row_number=record.source.row_number))

        identical = next((i["id"] for i in state["imports"] if info and i["sha256"] == info.sha256), None)
        existing_by_core, trusted_by_key = defaultdict(list), defaultdict(list)
        for stored in state["transactions"]:
            existing = _existing(stored)
            existing_by_core[_core(existing.source)].append(existing)
            if policy is not None and stored["parser_version"] == policy.parser_version and existing.source.reference:
                key = self._key(account_id, existing.source, policy)
                if existing.source.dedup_key == key:
                    trusted_by_key[key].append(existing)

        categories = {c["id"]: c["name"] for c in self.repository.list_categories()}
        merchant_rules = {(r["bank"], r["merchant_key"], r["direction"]): r for r in self.repository.list_rules()}
        rows = []
        for index, record in enumerate(parsed.records):
            source = replace(record.source, dedup_key=self._key(account_id, record.source, policy))
            candidates: tuple[ExistingRow, ...] = ()
            if index in invalid:
                status = "invalid"
            elif identical is not None:
                status = "duplicate"
            else:
                trusted = trusted_by_key[source.dedup_key]
                fallback = [e for e in existing_by_core[_core(source)] if _compatible(source, e.source)]
                candidates = tuple(sorted({e.transaction_id: e for e in (*trusted, *fallback)}.values(),
                                          key=lambda e: e.transaction_id))
                if (len(trusted) == 1 and len(candidates) == 1
                        and _identity(source) == _identity(trusted[0].source)):
                    status = "duplicate"
                else:
                    status = "ambiguous" if candidates else "valid"
            matched_rule = None
            matched_category = None
            classification_source = "unclassified"
            if status in ("valid", "ambiguous"):
                synthetic_row = {
                    "account_id": account["id"],
                    "bank": account["bank"],
                    "parser_version": self.parser.version,
                    "pos_id": source.pos_id,
                    "original_description": source.description,
                    "description": source.description,
                    "original_amount_minor": source.amount_minor,
                    "amount_minor": source.amount_minor,
                    "original_currency": source.currency,
                    "currency": source.currency,
                    "manual_lock": 0,
                    "classification_source": "unclassified",
                    "kind": "unclassified",
                    "category_id": None,
                }
                try:
                    merchant = self.classification._merchant(synthetic_row)
                except ClassificationBlocked:
                    merchant = None
                winning = self.classification.mappings.winning_rule(
                    synthetic_row, merchant.key if merchant is not None else None)
                if winning is not None:
                    matched_rule = winning["rule_name"]
                    matched_category = categories.get(winning["category_id"]) or winning["target_kind"].capitalize()
                    classification_source = "mapping_rule"
                elif merchant is not None:
                    direction = "debit" if merchant.transaction_type == "purchase" else "credit"
                    m_rule = merchant_rules.get((account["bank"], merchant.key, direction))
                    if m_rule is not None and self.repository.rule_eligible(synthetic_row, merchant, m_rule):
                        matched_rule = f'Merchant rule #{m_rule["id"]}'
                        matched_category = categories.get(m_rule["category_id"])
                        classification_source = "rule"
            rows.append(PreviewRow(
                index=index, source=source, status=status, candidates=candidates,
                matched_rule=matched_rule, matched_category=matched_category,
                classification_source=classification_source,
            ))
        rows = tuple(rows)
        preview = ImportPreview(
            token=uuid4().hex, info=info, revision=state["revision"], rows=rows, groups=_groups(rows),
            issues=tuple(issues), valid_count=sum(r.status == "valid" for r in rows),
            invalid_count=len(invalid) + max(0, parsed.candidate_row_count - len(rows)),
            duplicate_count=sum(r.status == "duplicate" for r in rows),
            ambiguous_count=sum(r.status == "ambiguous" for r in rows), identical_import_id=identical,
        )
        self._pending[preview.token] = preview
        return preview

    @staticmethod
    def _key(account_id: int, row: ImportRow, policy: VerifiedReferencePolicy | None) -> str:
        if policy is not None and row.reference:
            return "reference-v1:" + _digest((policy.namespace, account_id, row.currency, row.reference))
        return "source-v1:" + _digest((account_id, *_identity(row)))

    def _require_pending(self, preview: ImportPreview) -> None:
        if not isinstance(preview, ImportPreview) or self._pending.get(preview.token) is not preview:
            raise ImportBlocked("Preview is canceled, already confirmed, replaced, or belongs to another service.")

    def cancel(self, preview: ImportPreview) -> None:
        """Discard only in-memory state; no database or source writes."""
        self._require_pending(preview)
        del self._pending[preview.token]

    def confirm(self, preview: ImportPreview, decisions: Mapping[int, str] | None = None) -> ImportResult:
        """Confirm every ambiguous row explicitly and atomically commit all rows."""
        self._require_pending(preview)
        if not preview.is_valid:
            raise ImportBlocked("Statement has validation errors; resolve them and create a new preview.")
        decisions = dict(decisions) if decisions is not None else {}
        required = {r.index for r in preview.rows if r.status == "ambiguous"}
        if (set(decisions) != required or any(type(i) is not int for i in decisions)
                or any(action not in ("keep", "skip") for action in decisions.values())):
            raise ImportBlocked("Provide exactly one keep/skip decision for every ambiguous incoming row.")
        if preview.identical_import_id is not None:
            result = ImportResult(status="identical_file", import_id=preview.identical_import_id,
                                  imported_count=0, skipped_count=len(preview.rows))
        else:
            _validate_skip_multiplicity(preview.rows, decisions)
            audit = tuple(ImportDecision(
                row_index=row.index, source=row.source,
                action=decisions.get(row.index, "skip" if row.status == "duplicate" else "keep"),
                reason="manual" if row.status == "ambiguous" else (
                    "verified_reference" if row.status == "duplicate" else "new"),
                matching_transaction_ids=tuple(c.transaction_id for c in row.candidates),
            ) for row in preview.rows)
            kept = tuple(d.source for d in audit if d.action == "keep")
            skipped = len(audit) - len(kept)
            try:
                import_id = self.repository.write_import(
                    preview.info, kept, skipped_count=skipped,
                    expected_revision=preview.revision, decisions=audit,
                    classify=self.classification.classify_import,
                )
            except ImportStateChanged:
                raise ImportBlocked("Account imports changed; create a new preview before confirming.") from None
            except sqlite3.Error:
                # SQLite/trigger exception text is not safe to show or log.
                raise ImportBlocked("Import write failed; no rows or import metadata were committed.") from None
            except ClassificationBlocked:
                raise ImportBlocked("Import classification failed; no rows or import metadata were committed.") from None
            result = ImportResult(status="committed", import_id=import_id,
                                  imported_count=len(kept), skipped_count=skipped)
        del self._pending[preview.token]
        return result
