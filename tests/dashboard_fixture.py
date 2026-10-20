"""Create a NEW synthetic Dashboard database; never inspect an existing one."""

from pathlib import Path
from app.db import Repository
from app.models import ImportInfo, ImportRow


def populate(repository):
    categories = {c["name"]: c["id"] for c in repository.list_categories()}
    records = [
        ("MNT", "2026-09-30T23:59:59", 100000, "Other income", None),
        ("MNT", "2026-09-30", -10000, "Other expenses", None),
        ("MNT", "2026-10-01", 20000, "Other income", None),
        ("MNT", "2026-10-10", -3010, "Other expenses", None),
        ("MNT", "2026-10-31T23:59:59+08:00", -1990, "Software & Digital Subscriptions", None),
        ("MNT", "2026-10-15", 5000, None, None),
        ("MNT", "2026-10-16", -4000, None, "transfer"),
        ("MNT", "2026-10-17", -500, None, "excluded"),
        ("USD", "2026-10-10", 1000, "Other income", None),
        ("USD", "2026-10-10", -250, "Other expenses", None),
    ]
    identifiers = []
    for index, currency in enumerate(("MNT", "USD")):
        account = repository.create_account("SYNTHETIC-DASHBOARD-" + currency, "Fictional " + currency,
                                            bank="Synthetic bank", currency=currency)
        subset = [r for r in records if r[0] == currency]
        imported = repository.write_import(ImportInfo(account_id=account, sha256=str(index + 1) * 64,
            filename="synthetic-dashboard.xlsx", parser_version="synthetic-dashboard-1"),
            [ImportRow(description=f"Fictional Dashboard row {i}", bank_datetime=r[1], occurred_at=r[1],
                       amount_minor=r[2], currency=currency, worksheet="Synthetic", row_number=i + 1)
             for i, r in enumerate(subset)])
        rows = sorted(repository.query_transactions(import_id=imported), key=lambda r: r["row_number"])
        for row, record in zip(rows, subset):
            if record[3]:
                repository.assign_category(row["id"], categories[record[3]], reason="Synthetic fixture category")
            elif record[4]:
                repository.edit_transaction(row["id"], kind=record[4], reason="Synthetic fixture kind")
            identifiers.append(row["id"])
    repository.upsert_rule("Fictional backup merchant", "debit", "expense", categories["Other expenses"], bank="Synthetic bank")
    return identifiers


def create_dashboard_database(folder):
    path = Path(folder) / "finance.sqlite3"
    if path.exists():
        raise ValueError("Choose a new synthetic data directory; existing files are never overwritten.")
    with Repository(path) as repository:
        populate(repository)
    return path
