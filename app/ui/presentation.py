"""Small display and input helpers, independent of Tk, SQL and statement parsing."""

from app.models import minor_to_money, validate_iso


def format_mnt(minor: int | None) -> str:
    return "—" if minor is None else f"{minor_to_money(minor):,.2f} MNT"


def browser_filters(date_from="", date_to="", category_id=None, direction=None,
                    review_only=False, search="", currency=None) -> dict:
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
                  direction=direction, review_only=review_only, search=search.strip())
    if currency is not None:
        result["currency"] = currency
    return result


def review_status(row: dict) -> str:
    if row["kind"] == "unclassified" or (row["kind"] in ("income", "expense") and row["category_id"] is None):
        return "Needs review"
    if row["kind"] in ("transfer", "excluded"):
        return row["kind"].capitalize()
    return "Manual / protected" if row["manual_lock"] else "Classified"


def issue_location(issue) -> tuple[str, str, str]:
    # Parser worksheet indices are zero based; show human-readable worksheet numbers.
    return ("Statement" if issue.sheet_index is None else f"Worksheet {issue.sheet_index + 1}",
            "—" if issue.row_number is None else str(issue.row_number), issue.column or "—")
