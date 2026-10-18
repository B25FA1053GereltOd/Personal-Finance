"""Small parser contract; issue messages must never include source cell values."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from app.models import ImportRow


@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    sheet_index: int | None = None
    row_number: int | None = None
    column: str | None = None


@dataclass(frozen=True)
class ReconciliationCheck:
    code: str
    outcome: Literal["passed", "failed", "not_checked"]


@dataclass(frozen=True, kw_only=True)
class StatementMetadata:
    parser_version: str
    currency: str
    account_identifier: str = field(repr=False)
    worksheet: str = field(repr=False)
    period_start: str = field(repr=False)
    period_end: str = field(repr=False)
    printed_on: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class ParsedTransaction:
    source: ImportRow = field(repr=False)
    branch: str = field(repr=False)
    counterparty_account: str | None = field(repr=False)
    opening_balance_minor: int = field(repr=False)
    credit_minor: int = field(repr=False)
    debit_minor: int = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class ParseResult:
    metadata: StatementMetadata | None = field(default=None, repr=False)
    records: tuple[ParsedTransaction, ...] = field(default=(), repr=False)
    issues: tuple[ParseIssue, ...] = ()
    checks: tuple[ReconciliationCheck, ...] = ()
    candidate_row_count: int = field(default=0, repr=False)

    @property
    def is_valid(self) -> bool:
        return self.metadata is not None and not any(i.severity == "error" for i in self.issues)


class StatementParser(Protocol):
    version: str

    def detect(self, path: str | Path) -> bool:
        """Return whether the workbook matches a supported, usable statement."""
        ...

    def parse(self, path: str | Path) -> ParseResult:
        """Return records and static structured diagnostics; never write input."""
        ...
