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


FIELDS = (
    "date_time",
    "account",
    "account_identifier",
    "bank",
    "description",
    "merchant",
    "signed_amount",
    "currency",
    "kind",
    "category",
    "note",
    "classification_source",
    "review_status",
    "manual_protection",
)

TRANSACTION_FIELDS_EN = (
    "date_time",
    "amount",
    "description",
    "category",
    "currency",
    "bank",
    "account",
    "direction",
    "classification_source",
    "rule_name",
)

TRANSACTION_FIELDS_MN = (
    "Хугацаа",
    "Дүн",
    "Гүйлгээ",
    "Ангилал",
    "Валют",
    "Банк",
    "Данс",
    "Чиглэл",
    "Ангилсан эх үүсвэр",
    "Ангиллын дүрэм",
)


def spreadsheet_text(value):
    """Neutralize text that spreadsheet programs could execute as a formula."""
    text = str(value or "")
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n"))
        else text
    )


def export_csv(repository, path, filters, translate=None, language=None, format=None, confirm_overwrite=False):
    """Export all matching rows under one read snapshot; refuse unconfirmed overwrites."""
    target = Path(path)
    owned, complete = False, False
    temp_target = None
    try:
        if target.suffix.lower() != ".csv":
            raise ExportError("Choose a new filename ending in .csv.")
        if target.exists() and not confirm_overwrite:
            raise ExportError("That export already exists. Choose a new filename; nothing was overwritten.")

        if format is None:
            format = "legacy"

        if format == "transactions":
            headers = TRANSACTION_FIELDS_MN if language == "mn" else TRANSACTION_FIELDS_EN
        else:
            headers = FIELDS

        with repository.read_snapshot():
            count = repository.count_transactions(**filters)
            if not count:
                return ExportResult(0)
            accounts = {row["id"]: row for row in repository.list_accounts()}
            categories = {row["id"]: row["name"] for row in repository.list_categories()}

            if target.exists() and confirm_overwrite:
                temp_target = target.with_name(f".{target.name}.tmp")
                file_handle = temp_target.open("w", encoding="utf-8-sig", newline="")
                owned = True
            else:
                file_handle = target.open("x", encoding="utf-8-sig", newline="")
                owned = True

            with file_handle as output:
                writer = csv.writer(output, quoting=csv.QUOTE_ALL)
                writer.writerow(headers)
                for offset in range(0, count, 500):
                    for row in repository.query_transactions(**filters, limit=500, offset=offset):
                        account = accounts.get(row["account_id"], {"name": "", "identifier": "", "bank": ""})
                        cat_name = categories.get(row["category_id"], "")
                        if cat_name:
                            if callable(translate):
                                cat_name = translate(cat_name)
                            elif language == "mn":
                                from app.ui.i18n import translate as i18n_translate

                                cat_name = i18n_translate(cat_name, "mn")

                        if format == "transactions":
                            amt_minor = row["amount_minor"]
                            if amt_minor < 0:
                                dir_label = "Зарлага" if language == "mn" else "debit"
                            elif amt_minor > 0:
                                dir_label = "Орлого" if language == "mn" else "credit"
                            else:
                                dir_label = "Тэг" if language == "mn" else "zero"

                            src = row.get("classification_source") or "unclassified"
                            rule_name = (
                                row.get("applied_mapping_rule_name")
                                or (f"Rule #{row['applied_rule_id']}" if row.get("applied_rule_id")
                                    else (f"Memory #{row['applied_memory_id']}" if row.get("applied_memory_id") else ""))
                            )
                            values = (
                                row["occurred_at"],
                                str(minor_to_money(amt_minor)),
                                row["description"],
                                cat_name,
                                row["currency"],
                                account["bank"],
                                account["name"],
                                dir_label,
                                src,
                                rule_name,
                            )
                            writer.writerow(
                                [
                                    value if i == 1 else spreadsheet_text(value)
                                    for i, value in enumerate(values)
                                ]
                            )
                        else:
                            values = (
                                row["occurred_at"],
                                account["name"],
                                account["identifier"],
                                account["bank"],
                                row["description"],
                                row["merchant_display"] or "",
                                str(minor_to_money(row["amount_minor"])),
                                row["currency"],
                                row["kind"],
                                cat_name,
                                row["note"],
                                row["classification_source"],
                                review_status(row),
                                "protected" if row["manual_lock"] else "unlocked",
                            )
                            writer.writerow(
                                [
                                    value if i == 6 else spreadsheet_text(value)
                                    for i, value in enumerate(values)
                                ]
                            )

            if temp_target is not None:
                temp_target.replace(target)
            complete = True
            return ExportResult(count, target)
    except ExportError:
        raise
    except FileExistsError:
        raise ExportError(
            "That export already exists. Choose a new filename; nothing was overwritten."
        ) from None
    except (OSError, ValueError, TypeError, sqlite3.Error):
        raise ExportError(
            "Export failed. Check filters, folder permissions and free disk space, then retry."
        ) from None
    finally:
        if owned and not complete:
            for p in (temp_target, target if temp_target is None else None):
                if p is not None:
                    try:
                        p.unlink()
                    except OSError:
                        pass
