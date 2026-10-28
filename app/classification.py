"""Deterministic exact merchant rules and explicit review operations, without UI."""

import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from uuid import uuid4

from app.db import Repository, classification_revision
from app.mapping_service import MappingBlocked, MappingService
from app.models import MerchantMatch, RuleSelection, normalize_merchant_key, require_integer


class ClassificationBlocked(ValueError):
    """A safe diagnostic for a rejected classification operation."""


# Fixed description grammar, not a configurable merchant matching rule.
_KHAN_CARD_DESCRIPTION = re.compile(r"[A-Za-z0-9]{6}[ \t]+(?P<merchant>\S[^\r\n]*)")
_NON_PURCHASE_MARKERS = frozenset({
    "qpay", "transfer", "transfers", "fee", "fees", "refund", "refunds",
    "reversal", "chargeback", "credit", "income", "atm",
    "шилжүүлэг", "шимтгэл", "буцаалт", "орлого",
})


def extract_merchant(bank: str, parser_version: str, description: str) -> MerchantMatch | None:
    """Recognize only the user-confirmed Khan authorization-prefix structure.

    Keep the complete remainder as display text; MerchantMatch normalizes its
    key. The caller must also enforce debit direction and transaction eligibility.
    Explicit non-purchase wording is ambiguity, never evidence for a new type.
    """
    if bank != "Khan Bank" or parser_version != "khan-mnt-1":
        return None
    match = _KHAN_CARD_DESCRIPTION.fullmatch(description)
    if match is None or any(ord(c) < 32 and c != "\t" for c in description):
        return None
    words = set(re.findall(r"[^\W_]+", description.casefold()))
    if words & _NON_PURCHASE_MARKERS:
        return None
    return MerchantMatch(display_text=match["merchant"], pattern="khan-card-auth6-v1")


@dataclass(frozen=True, kw_only=True)
class ReviewItem:
    transaction_id: int
    bank: str
    direction: str
    description: str = field(repr=False)
    amount_minor: int = field(repr=False)
    merchant: MerchantMatch | None = field(repr=False)
    manual_lock: bool


@dataclass(frozen=True, kw_only=True)
class MerchantGroup:
    bank: str
    direction: str
    merchant_key: str = field(repr=False)
    items: tuple[ReviewItem, ...] = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class ReviewQueue:
    groups: tuple[MerchantGroup, ...] = field(repr=False)
    individual: tuple[ReviewItem, ...] = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class RulePreview:
    token: str = field(repr=False)
    rule_id: int
    rule_revision: int
    category_id: int
    candidates: tuple[ReviewItem, ...] = field(repr=False)
    selections: tuple[RuleSelection, ...] = field(repr=False)


class ClassificationService:
    """A saved rule never modifies old rows without a selected-row confirmation.

    `extractor` is a developer integration seam for verified bank patterns;
    tests supply synthetic evidence. It is not a configurable matching rule.
    """

    def __init__(self, repository: Repository, *,
                 extractor: Callable[[str, str, str], MerchantMatch | None] = extract_merchant) -> None:
        self.repository = repository
        self.extractor = extractor
        self.mappings = MappingService(repository)
        self._pending: dict[str, RulePreview] = {}

    def _merchant(self, row: dict) -> MerchantMatch | None:
        try:
            match = self.extractor(row["bank"], row["parser_version"], row["original_description"])
        except Exception:
            # An extractor exception may embed source text. Abort safely instead
            # of logging it or reporting a partial import as successful.
            raise ClassificationBlocked("Merchant extraction failed; classification was not applied.") from None
        if match is None:
            return None
        if not isinstance(match, MerchantMatch):
            raise ClassificationBlocked("Merchant extractor returned invalid evidence.")
        amount = row["original_amount_minor"]
        if (match.transaction_type == "purchase" and amount >= 0
                or match.transaction_type == "refund" and amount <= 0):
            return None
        return match

    @staticmethod
    def _item(row: dict, merchant: MerchantMatch | None) -> ReviewItem:
        amount = row["amount_minor"]
        return ReviewItem(transaction_id=row["id"], bank=row["bank"],
                          direction="debit" if amount < 0 else "credit" if amount > 0 else "zero",
                          description=row["description"], amount_minor=amount,
                          merchant=merchant, manual_lock=bool(row["manual_lock"]))

    def review(self) -> ReviewQueue:
        """Group known POS merchants; keep unreliable or locked rows individual."""
        groups = defaultdict(list)
        individual = []
        for row in self.repository.classification_rows():
            if not (row["kind"] == "unclassified"
                    or row["kind"] in ("income", "expense") and row["category_id"] is None):
                continue
            merchant = self._merchant(row)
            item = self._item(row, merchant)
            merchant_direction = "debit" if merchant and merchant.transaction_type == "purchase" else "credit"
            if merchant is None or item.manual_lock or item.direction != merchant_direction:
                individual.append(item)
            else:
                groups[(item.bank, merchant.key, item.direction)].append(item)
        return ReviewQueue(
            groups=tuple(MerchantGroup(bank=bank, merchant_key=key, direction=direction, items=tuple(items))
                         for (bank, key, direction), items in sorted(groups.items())),
            individual=tuple(individual),
        )

    def assign_category(self, transaction_ids: Iterable[int], category_id: int | None, *,
                        reason: str = "Manual category assignment") -> int:
        """Transaction-only is the default: assign selected rows, lock, save no rule."""
        try:
            return self.repository.assign_categories(transaction_ids, category_id, reason=reason)
        except sqlite3.Error:
            raise ClassificationBlocked("Category assignment failed; no selected rows were changed.") from None

    def reclassify(self, transaction_id: int, category_id: int | None, *,
                   reason: str = "Manual reclassification") -> None:
        self.assign_category((transaction_id,), category_id, reason=reason)

    def save_rule(self, bank: str, merchant_text: str, direction: str, category_id: int) -> int:
        """Save/update an exact scope for future imports only; activate that rule."""
        if direction not in ("debit", "credit"):
            raise ClassificationBlocked("Merchant rules require a debit or credit direction.")
        require_integer(category_id, "Category ID", 1)
        kind = "expense" if direction == "debit" else "income"
        try:
            return self.repository.upsert_rule(merchant_text, direction, kind, category_id, bank=bank)
        except sqlite3.Error:
            raise ClassificationBlocked("Rule could not be saved; no past classifications changed.") from None

    def disable_rule(self, rule_id: int) -> None:
        try:
            self.repository.disable_rule(rule_id)
        except sqlite3.Error:
            raise ClassificationBlocked("Rule could not be disabled; no past classifications changed.") from None

    def classify_import(self, import_id: int) -> None:
        """Import commit callback: original identity in, exact scoped rules out."""
        merchants = {}
        for row in self.repository.classification_rows(import_id=import_id):
            merchant = self._merchant(row)
            if merchant is not None:
                merchants[row["id"]] = merchant
        try:
            self.mappings.classify_import(import_id, merchants)
        except MappingBlocked:
            raise ClassificationBlocked("Mapping classification failed; the import was not committed.") from None
        self.repository.classify_import(import_id, merchants)

    def preview_rule(self, rule_id: int) -> RulePreview:
        rule = self.repository.get_rule(rule_id)
        if not rule["active"] or rule["kind"] not in ("income", "expense") or rule["category_id"] is None:
            raise ClassificationBlocked("Select an active category rule.")
        candidates, selections = [], []
        for row in self.repository.classification_rows():
            merchant = self._merchant(row)
            if merchant is not None and self.repository.rule_eligible(row, merchant, rule):
                candidates.append(self._item(row, merchant))
                selections.append(RuleSelection(transaction_id=row["id"],
                                                revision=classification_revision(row), merchant=merchant))
        preview = RulePreview(token=uuid4().hex, rule_id=rule_id, rule_revision=rule["revision"],
                              category_id=rule["category_id"], candidates=tuple(candidates), selections=tuple(selections))
        self._pending[preview.token] = preview
        return preview

    def _require_pending(self, preview: RulePreview) -> None:
        if not isinstance(preview, RulePreview) or self._pending.get(preview.token) is not preview:
            raise ClassificationBlocked("Rule preview is canceled, consumed, changed, or belongs to another service.")

    def cancel_rule_preview(self, preview: RulePreview) -> None:
        self._require_pending(preview)
        del self._pending[preview.token]

    def apply_rule(self, preview: RulePreview, transaction_ids: Iterable[int]) -> int:
        """Require an explicit subset; never infer 'all matching transactions'."""
        self._require_pending(preview)
        identifiers = tuple(transaction_ids)
        for identifier in identifiers:
            require_integer(identifier, "Transaction ID", 1)
        candidates = {s.transaction_id: s for s in preview.selections}
        if len(set(identifiers)) != len(identifiers) or not set(identifiers) <= candidates.keys():
            raise ClassificationBlocked("Select only distinct eligible transactions from this preview.")
        try:
            count = self.repository.apply_rule(preview.rule_id, (candidates[i] for i in identifiers),
                                               expected_revision=preview.rule_revision)
        except sqlite3.Error:
            raise ClassificationBlocked("Rule application failed; no selected rows were changed.") from None
        del self._pending[preview.token]
        return count
