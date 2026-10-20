"""Offline effective-value summaries. Integer money, Decimal percentages, no Tk."""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext, ROUND_HALF_UP
import re


PRESETS = ("All time", "This month", "Last month", "This year", "Custom range")


class ReportingError(ValueError):
    """Static safe diagnostic, containing no financial data."""


def date_range(preset="All time", start="", end="", *, today=None):
    today = today or date.today()
    if preset == "All time":
        return None, None
    if preset == "This month":
        return today.replace(day=1).isoformat(), today.replace(day=monthrange(today.year, today.month)[1]).isoformat()
    if preset == "Last month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1).isoformat(), last.isoformat()
    if preset == "This year":
        return date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    if preset != "Custom range":
        raise ReportingError("Choose a supported Dashboard date preset.")
    try:
        first, last = start.strip(), end.strip()
        if not all(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", s) for s in (first, last)):
            raise ValueError
        if date.fromisoformat(first) > date.fromisoformat(last):
            raise ReportingError("The start date must not be after the end date.")
    except ReportingError:
        raise
    except (ValueError, AttributeError, TypeError):
        raise ReportingError("Enter both custom dates as valid YYYY-MM-DD values.") from None
    return first, last


def format_money(minor, currency):
    """Format integer hundredths, including totals beyond one SQLite integer."""
    whole, fraction = divmod(abs(minor), 100)
    return f"{'-' if minor < 0 else ''}{whole:,}.{fraction:02d} {currency}"


def percentage(amount, total):
    if not total:
        return Decimal("0.00")
    with localcontext() as ctx:
        ctx.prec = max(28, len(str(total)) + 10)
        return (Decimal(amount) * 100 / Decimal(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Report:
    start: str | None
    end: str | None
    totals: tuple = field(repr=False)
    categories: tuple = field(repr=False)
    months: tuple = field(repr=False)
    transaction_count: int
    unclassified_count: int


class ReportingService:
    def __init__(self, repository):
        self.repository = repository

    def summarize(self, preset="All time", start="", end="", *, today=None):
        start, end = date_range(preset, start, end, today=today)
        rows = self.repository.reporting_rows(start, end)
        totals, months, categories = {}, {}, {}
        def empty(currency, **extra):
            return dict(currency=currency, income=0, expenses=0, net=0, count=0,
                        unclassified=0, omitted=0, **extra)
        for row in rows:
            currency, month = row["currency"], row["occurred_at"][:7]
            total = totals.setdefault(currency, empty(currency))
            monthly = months.setdefault((month, currency), empty(currency, month=month))
            kind = row["kind"]
            unknown = kind == "unclassified" or (kind in ("income", "expense") and row["category_id"] is None)
            included = not unknown and kind in ("income", "expense")
            for target in (total, monthly):
                target["count"] += 1
                if unknown:
                    target["unclassified"] += 1
                elif included:
                    amount = row["amount_minor"] if kind == "income" else -row["amount_minor"]
                    target["income" if kind == "income" else "expenses"] += amount
                    target["net"] += row["amount_minor"]
                else:
                    target["omitted"] += 1
            if included:
                key = (currency, kind, row["category_id"])
                category = categories.setdefault(key, dict(currency=currency, kind=kind,
                    category_id=row["category_id"], category=row["category_name"], amount=0, count=0))
                category["amount"] += amount
                category["count"] += 1
        for category in categories.values():
            denominator = totals[category["currency"]]["income" if category["kind"] == "income" else "expenses"]
            category["percentage"] = percentage(category["amount"], denominator)
        return Report(start, end, tuple(totals[k] for k in sorted(totals)),
                      tuple(sorted(categories.values(), key=lambda c: (c["currency"], c["kind"], -c["amount"], c["category_id"]))),
                      tuple(months[k] for k in sorted(months)), len(rows),
                      sum(t["unclassified"] for t in totals.values()))


def category_filters(report, row):
    if row not in report.categories:
        raise ReportingError("Refresh the Dashboard and select a category row.")
    return dict(date_from=report.start, date_to=report.end,
                category_id=row["category_id"], currency=row["currency"])


def month_filters(report, row):
    if row not in report.months:
        raise ReportingError("Refresh the Dashboard and select a monthly row.")
    year, month = map(int, row["month"].split("-"))
    start, end = date(year, month, 1).isoformat(), date(year, month, monthrange(year, month)[1]).isoformat()
    return dict(date_from=max(start, report.start) if report.start else start,
                date_to=min(end, report.end) if report.end else end, currency=row["currency"])
