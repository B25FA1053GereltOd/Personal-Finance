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

    @property
    def unclassified_amounts(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (r["currency"], r.get("unclassified", 0), r.get("unclassified_amount", 0))
            for r in self.totals
            if r.get("unclassified", 0) or r.get("unclassified_amount", 0)
        )


def summarize_rows(rows, start=None, end=None) -> Report:
    totals, months, categories = {}, {}, {}

    def empty(currency, **extra):
        return dict(currency=currency, income=0, expenses=0, net=0, count=0,
                    unclassified=0, unclassified_amount=0, omitted=0, **extra)

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
                target["unclassified_amount"] += abs(row["amount_minor"])
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


class ReportingService:
    def __init__(self, repository):
        self.repository = repository

    def summarize(self, preset="All time", start="", end="", *, currency=None, today=None):
        start, end = date_range(preset, start, end, today=today)
        selected_currency = None if currency in (None, "", "All currencies") else currency
        try:
            rows = self.repository.reporting_rows(start, end, currency=selected_currency)
        except ValueError as error:
            raise ReportingError(str(error)) from None
        return summarize_rows(rows, start, end)

    def summarize_filters(self, **filters) -> Report:
        rows = self.repository.reporting_rows(**filters)
        return summarize_rows(rows, filters.get("date_from"), filters.get("date_to"))


def chart_currencies(report: Report | None, currency: str | None = None) -> tuple[str, ...]:
    if report is None:
        return ()
    selected = None if currency in (None, "", "All currencies") else currency
    return tuple(r["currency"] for r in report.totals if selected is None or r["currency"] == selected)


def monthly_chart_series(report: Report | None, currency: str | None = None) -> tuple[dict, ...]:
    if report is None:
        return ()
    series = []
    for cur in chart_currencies(report, currency):
        months = [m for m in report.months if m["currency"] == cur and (m["income"] > 0 or m["expenses"] > 0)]
        if not months:
            continue
        max_minor = max(max(m["income"], m["expenses"]) for m in months)
        series.append({
            "currency": cur,
            "max_minor": max_minor,
            "bars": tuple(
                {
                    "month": m["month"],
                    "currency": cur,
                    "income": m["income"],
                    "expenses": m["expenses"],
                    "net": m["net"],
                    "income_label": format_money(m["income"], cur),
                    "expense_label": format_money(m["expenses"], cur),
                    "net_label": format_money(m["net"], cur),
                }
                for m in months
            ),
        })
    return tuple(series)


def category_chart_series(report: Report | None, kind: str, currency: str | None = None) -> tuple[dict, ...]:
    if kind not in ("income", "expense"):
        raise ReportingError("Chart category kind must be income or expense.")
    if report is None:
        return ()
    series = []
    for cur in chart_currencies(report, currency):
        cats = [c for c in report.categories if c["currency"] == cur and c["kind"] == kind and c["amount"] > 0]
        if not cats:
            continue
        series.append({
            "currency": cur,
            "kind": kind,
            "total_minor": sum(c["amount"] for c in cats),
            "max_minor": max(c["amount"] for c in cats),
            "bars": tuple(
                {
                    "category_id": c["category_id"],
                    "category": c["category"],
                    "currency": cur,
                    "amount": c["amount"],
                    "amount_label": format_money(c["amount"], cur),
                    "count": c["count"],
                    "percentage": c["percentage"],
                    "percentage_label": f'{c["percentage"]:.2f}%',
                }
                for c in cats
            ),
        })
    return tuple(series)


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
