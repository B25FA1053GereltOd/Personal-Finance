"""Validated inputs and exact MNT amounts for the persistence layer."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1
KINDS = ("unclassified", "income", "expense", "transfer", "excluded")
DEFAULT_CATEGORIES = (
    ("Earned income (part-time job, freelancing, internship)", "income"),
    ("Allowance / Family support", "income"),
    ("Scholarships / Grants", "income"),
    ("Gifts / Donations", "income"),
    ("Other income", "income"),
    ("Tuition & Academic Fees", "expense"),
    ("Textbooks, Printing & School Supplies", "expense"),
    ("Cafeteria, Coffee & Snacks", "expense"),
    ("Dormitory / Rent & Utilities", "expense"),
    ("Public Transport / Commuting", "expense"),
    ("Social & Entertainment", "expense"),
    ("Software & Digital Subscriptions", "expense"),
    ("Other expenses", "expense"),
)


def require_integer(value: int, name: str, minimum: int = MIN_INTEGER) -> int:
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be an integer between {minimum} and {MAX_INTEGER}.")
    return value


def money_to_minor(value: str | Decimal | int) -> int:
    """Convert an ungrouped decimal amount to hundredths without rounding.

    Floats, booleans, non-finite values, and more than two decimal places
    (including trailing zeros) are rejected. Decimal context cannot round this.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError("Money must be decimal text, Decimal, or an integer, never a float.")
    if isinstance(value, str) and not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value.strip()):
        raise ValueError("Money must be ungrouped decimal text, such as '-1250.50'.")
    try:
        amount = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation as error:
        raise ValueError("Invalid decimal money value.") from error
    if not amount.is_finite():
        raise ValueError("Money must be finite.")
    sign, digits, exponent = amount.as_tuple()
    if exponent < -2:
        raise ValueError("Money cannot have more than two decimal places.")
    if amount.is_zero():
        return 0
    if len(digits) + exponent + 2 > 19:
        raise ValueError("Money exceeds the SQLite integer range.")
    coefficient = int("".join(map(str, digits)))
    minor = coefficient * 10 ** (exponent + 2) * (-1 if sign else 1)
    return require_integer(minor, "Money in hundredths")


def minor_to_money(value: int) -> Decimal:
    """Return an exact two-place Decimal from stored hundredths."""
    require_integer(value, "Money in hundredths")
    whole, fraction = divmod(abs(value), 100)
    return Decimal(f"{'-' if value < 0 else ''}{whole}.{fraction:02d}")


def validate_iso(value: str) -> str:
    """Accept ISO calendar dates or ISO datetimes with seconds; never guess."""
    if not isinstance(value, str):
        raise ValueError("Date/time must be ISO text.")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        date.fromisoformat(value)
    elif re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
        r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?", value
    ):
        datetime.fromisoformat(value)
    else:
        raise ValueError("Date/time must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS with optional offset.")
    return value


def require_text(value: str, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be {'possibly empty' if allow_empty else 'nonempty'} text.")
    return value


def validate_currency(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("Currency must be a three-letter uppercase code, such as MNT.")
    return value


@dataclass(frozen=True, kw_only=True)
class ImportInfo:
    account_id: int
    sha256: str
    parser_version: str
    filename: str

    def __post_init__(self) -> None:
        require_integer(self.account_id, "Account ID", 1)
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("Import SHA-256 must contain exactly 64 hexadecimal characters.")
        require_text(self.parser_version, "Parser version")
        require_text(self.filename, "Filename")
        if any(character in self.filename for character in ("/", "\\", "\x00")):
            raise ValueError("Filename must be a filename, not a path.")


@dataclass(frozen=True, kw_only=True)
class ImportRow:
    """A parsed source row; no classification or parser fingerprint is inferred."""

    description: str
    bank_datetime: str
    occurred_at: str
    amount_minor: int
    worksheet: str
    row_number: int
    currency: str = "MNT"
    reference: str | None = None
    balance_minor: int | None = None
    dedup_key: str | None = None

    def __post_init__(self) -> None:
        require_text(self.description, "Description", allow_empty=True)
        require_text(self.bank_datetime, "Original bank date/time")
        validate_iso(self.occurred_at)
        require_integer(self.amount_minor, "Amount")
        validate_currency(self.currency)
        require_text(self.worksheet, "Worksheet")
        require_integer(self.row_number, "Worksheet row", 1)
        if self.reference is not None:
            require_text(self.reference, "Reference", allow_empty=True)
        if self.balance_minor is not None:
            require_integer(self.balance_minor, "Balance")
        if self.dedup_key is not None:
            require_text(self.dedup_key, "Deduplication key")


@dataclass(frozen=True, kw_only=True)
class ImportDecision:
    """One incoming row's disposition, persisted with its import, never logged."""

    row_index: int
    source: ImportRow = field(repr=False)
    action: str
    reason: str
    matching_transaction_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        require_integer(self.row_index, "Incoming row index", 0)
        if not isinstance(self.source, ImportRow):
            raise ValueError("Decision source must be an ImportRow.")
        if self.action not in ("keep", "skip"):
            raise ValueError("Decision must be keep or skip.")
        if self.reason not in ("new", "verified_reference", "manual"):
            raise ValueError("Unknown import decision reason.")
        if not isinstance(self.matching_transaction_ids, tuple):
            raise ValueError("Matching transaction IDs must be a tuple.")
        for identifier in self.matching_transaction_ids:
            require_integer(identifier, "Matching transaction ID", 1)
        if len(set(self.matching_transaction_ids)) != len(self.matching_transaction_ids):
            raise ValueError("Matching transaction IDs must not repeat.")
        if self.action == "skip" and not self.matching_transaction_ids:
            raise ValueError("A skipped row must identify an existing candidate.")


def normalize_merchant_key(text: str) -> str:
    """Canonical Unicode + casefold + whitespace; keep digits and punctuation."""
    require_text(text, "Merchant text")
    return unicodedata.normalize("NFC", " ".join(unicodedata.normalize("NFC", text).casefold().split()))


@dataclass(frozen=True, kw_only=True)
class MerchantMatch:
    """Evidence from a verified POS extractor; the display text stays intact."""

    display_text: str = field(repr=False)
    pattern: str
    transaction_type: str = "purchase"

    def __post_init__(self) -> None:
        require_text(self.display_text, "Merchant display text")
        require_text(self.pattern, "Verified merchant pattern")
        if self.transaction_type not in ("purchase", "refund"):
            raise ValueError("Merchant type must be a verified POS purchase or refund.")

    @property
    def key(self) -> str:
        return normalize_merchant_key(self.display_text)


@dataclass(frozen=True, kw_only=True)
class RuleSelection:
    transaction_id: int
    revision: str = field(repr=False)
    merchant: MerchantMatch = field(repr=False)

    def __post_init__(self) -> None:
        require_integer(self.transaction_id, "Transaction ID", 1)
        require_text(self.revision, "Transaction revision")
        if not isinstance(self.merchant, MerchantMatch):
            raise ValueError("A verified merchant match is required.")


def review_status(row: dict) -> str:
    """Shared review state for tables and exports; independent of Tk."""
    if row["kind"] == "unclassified" or (row["kind"] in ("income", "expense") and row["category_id"] is None):
        return "Needs review"
    if row["kind"] in ("transfer", "excluded"):
        return row["kind"].capitalize()
    return "Manual / protected" if row["manual_lock"] else "Classified"
