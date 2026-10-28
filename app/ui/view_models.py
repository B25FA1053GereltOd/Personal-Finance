"""Pure display models for the dashboard summary cards."""

from decimal import Decimal, localcontext

from app.reporting import format_money


def dashboard_summary(report) -> tuple[tuple[str, str], ...]:
    totals = report.totals

    def amount_text(amount: Decimal, currency: str) -> str:
        minor_units = int((amount * Decimal(100)).to_integral_exact())
        return format_money(minor_units, currency)

    revenue, cost, net, unclassified_amounts = [], [], [], []
    for row in totals:
        currency = row["currency"]
        precision = max(
            len(str(abs(row["income"]))),
            len(str(abs(row["expenses"]))),
            len(str(abs(row.get("unclassified_amount", 0)))),
        ) + 4
        with localcontext() as context:
            context.prec = max(context.prec, precision)
            total_revenue = Decimal(row["income"]) / Decimal(100)
            total_cost = Decimal(row["expenses"]) / Decimal(100)
            revenue.append(amount_text(total_revenue, currency))
            cost.append(amount_text(total_cost, currency))
            net.append(amount_text(total_revenue - total_cost, currency))
            if "unclassified_amount" in row and (row.get("unclassified", 0) or row["unclassified_amount"]):
                unclassified_total = Decimal(row["unclassified_amount"]) / Decimal(100)
                unclassified_amounts.append(amount_text(unclassified_total, currency))

    def joined(values):
        return " · ".join(values) or "—"

    unclassified_text = (
        f"{report.unclassified_count} ({joined(unclassified_amounts)})"
        if unclassified_amounts else str(report.unclassified_count)
    )
    return (
        ("Total Revenue", joined(revenue)),
        ("Total Cost", joined(cost)),
        ("Net", joined(net)),
        ("Unclassified", unclassified_text),
    )


def filtered_totals_text(report, translate=lambda s: s) -> str:
    if report is None:
        return ""
    cards = dict(dashboard_summary(report))
    return (
        f'{translate("Total Revenue")}: {cards["Total Revenue"]} | '
        f'{translate("Total Cost")}: {cards["Total Cost"]} | '
        f'{translate("Net")}: {cards["Net"]} | '
        f'{translate("Unclassified")}: {cards["Unclassified"]}'
    )
