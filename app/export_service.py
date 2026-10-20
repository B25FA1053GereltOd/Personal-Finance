"""Filtered, exact effective-value CSV export. No Tk, network, or source logging."""

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.models import minor_to_money, review_status


class ExportError(ValueError):
    """Safe static diagnostics."""


@dataclass(frozen=True)
class ExportResult:
    count: int
    path: Path | None = field(default=None, repr=False)


FIELDS = ("date_time", "account", "account_identifier", "bank", "description",
          "merchant", "signed_amount", "currency", "kind", "category", "note",
          "classification_source", "review_status", "manual_protection")


def spreadsheet_text(value):
    """Neutralize text that spreadsheet programs could execute as a formula."""
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def export_csv(repository, path, filters):
    """Export all matching rows under one read snapshot; refuse overwrites."""
    target, owned, complete = Path(path), False, False
    try:
        if target.suffix.lower() != ".csv":
            raise ExportError("Choose a new filename ending in .csv.")
        with repository.read_snapshot():
            count = repository.count_transactions(**filters)
            if not count:
                return ExportResult(0)
            accounts = {row["id"]: row for row in repository.list_accounts()}
            categories = {row["id"]: row["name"] for row in repository.list_categories()}
            with target.open("x", encoding="utf-8-sig", newline="") as output:
                owned = True
                writer = csv.writer(output, quoting=csv.QUOTE_ALL)
                writer.writerow(FIELDS)
                for offset in range(0, count, 500):
                    for row in repository.query_transactions(**filters, limit=500, offset=offset):
                        account = accounts[row["account_id"]]
                        values = (row["occurred_at"], account["name"], account["identifier"], account["bank"],
                                  row["description"], row["merchant_display"] or "",
                                  str(minor_to_money(row["amount_minor"])), row["currency"], row["kind"],
                                  categories.get(row["category_id"], ""), row["note"], row["classification_source"],
                                  review_status(row), "protected" if row["manual_lock"] else "unlocked")
                        # Amount is validated numeric text; never prefix/round it.
                        writer.writerow([value if i == 6 else spreadsheet_text(value) for i, value in enumerate(values)])
            complete = True
            return ExportResult(count, target)
    except ExportError:
        raise
    except FileExistsError:
        raise ExportError("That export already exists. Choose a new filename; nothing was overwritten.") from None
    except (OSError, ValueError, TypeError, sqlite3.Error):
        raise ExportError("Export failed. Check filters, folder permissions and free disk space, then retry.") from None
    finally:
        if owned and not complete:
            try:
                target.unlink()
            except OSError:
                pass
