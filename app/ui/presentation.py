"""Small display and input helpers, independent of Tk, SQL and statement parsing."""

from app.models import minor_to_money, validate_iso, review_status
from app.reporting import format_money


def format_mnt(minor: int | None) -> str:
    return "—" if minor is None else f"{minor_to_money(minor):,.2f} MNT"


def merchant_description_label(row: dict) -> str:
    merchant = (row.get("merchant_display") or "").strip()
    description = (row.get("description") or "").strip()
    if merchant and description and merchant != description:
        return f"{merchant} — {description}"
    return merchant or description


def direction_kind_label(row: dict, translate=lambda s: s) -> str:
    amount = row["amount_minor"]
    direction = "Credit" if amount > 0 else ("Debit" if amount < 0 else "Zero")
    kind = str(row.get("kind") or "unclassified").capitalize()
    return f"{translate(direction)} · {translate(kind)}"


def classification_source_label(row: dict, translate=lambda s: s) -> str:
    raw = str(row.get("classification_source") or "unclassified")
    source = "Rule" if raw == "mapping_rule" else raw.capitalize()
    mapping_name = row.get("applied_mapping_rule_name")
    rule_id = row.get("applied_rule_id")
    if mapping_name:
        return f"{translate(source)}: {mapping_name}"
    if rule_id:
        return f'{translate(source)}: {translate("Merchant rule")} #{rule_id}'
    return translate(source)


def transaction_row_values(row: dict, categories: dict, translate=lambda s: s) -> tuple[str, ...]:
    return (
        row["occurred_at"].replace("T", " "),
        merchant_description_label(row),
        f'{row["bank"]} / {row["account_name"]}',
        format_money(row["amount_minor"], row["currency"]),
        categories.get(row["category_id"], "—"),
        classification_source_label(row, translate),
        translate(review_status(row)),
        direction_kind_label(row, translate),
    )


def archive_confirmation_details(transactions: list[dict]) -> tuple[int, dict[str, int], str]:
    currency_totals = {}
    dates = []
    for row in transactions:
        currency = row["currency"]
        currency_totals[currency] = currency_totals.get(currency, 0) + row["amount_minor"]
        occurred_at = row.get("occurred_at")
        if occurred_at:
            dates.append(occurred_at[:10])
    first_date, last_date = (min(dates), max(dates)) if dates else (None, None)
    date_range = (first_date if first_date == last_date else f"{first_date} — {last_date}") if dates else "—"
    return len(transactions), currency_totals, date_range


def browser_filters(date_from="", date_to="", category_id=None, direction=None,
                    review_only=False, search="", currency=None, bank=None,
                    archived=False) -> dict:
    start, end = date_from.strip() or None, date_to.strip() or None
    try:
        for value in (start, end):
            if value is not None:
                validate_iso(value)
                if len(value) != 10:
                    raise ValueError
    except ValueError:
        raise ValueError("Enter valid dates as YYYY-MM-DD, or leave them blank.") from None
    if start and end and start > end:
        raise ValueError("The start date must not be after the end date.")
    result = dict(date_from=start, date_to=end, category_id=category_id,
                  direction=direction, review_only=review_only, search=search.strip(),
                  archived=archived)
    if currency is not None:
        result["currency"] = currency
    if bank is not None:
        result["bank"] = bank
    return result


def issue_location(issue) -> tuple[str, str, str]:
    # Parser worksheet indices are zero based; show human-readable worksheet numbers.
    return ("Statement" if issue.sheet_index is None else f"Worksheet {issue.sheet_index + 1}",
            "—" if issue.row_number is None else str(issue.row_number), issue.column or "—")
