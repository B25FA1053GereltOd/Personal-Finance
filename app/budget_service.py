"""Monthly budget service for stage 1 and 2 corporate finance budget & variance management."""

from calendar import monthrange
import sqlite3
from app.models import require_integer, require_text, validate_currency, validate_month
from app.reporting import format_money


class BudgetBlocked(ValueError):
    """Safe diagnostic for rejected budget operations."""


class BudgetService:
    def __init__(self, repository):
        self.repository = repository

    def save_budget(self, *, month: str, currency: str, category_id: int,
                    planned_amount_minor: int, note: str = "", active: bool = True,
                    budget_id: int | None = None) -> dict:
        """Create or update a monthly budget row with validation."""
        try:
            month = validate_month(month)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        try:
            currency = validate_currency(currency)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        try:
            require_integer(category_id, "Category ID", minimum=1)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        try:
            require_integer(planned_amount_minor, "Planned amount", minimum=1)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        try:
            require_text(note, "Budget note", allow_empty=True)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        if type(active) is not bool:
            raise BudgetBlocked("Active status must be boolean.")

        try:
            if budget_id is None:
                identifier = self.repository.create_budget(
                    month=month,
                    currency=currency,
                    category_id=category_id,
                    planned_amount_minor=planned_amount_minor,
                    note=note,
                    active=active,
                )
            else:
                require_integer(budget_id, "Budget ID", minimum=1)
                self.repository.update_budget(
                    budget_id,
                    month=month,
                    currency=currency,
                    category_id=category_id,
                    planned_amount_minor=planned_amount_minor,
                    note=note,
                    active=active,
                )
                identifier = budget_id
            return {"budget": self.repository.get_budget(identifier)}
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None

    def toggle_active(self, budget_id: int, active: bool | None = None) -> dict:
        """Toggle or set the active status of a budget."""
        try:
            current = self.repository.get_budget(budget_id)
            if current is None:
                raise BudgetBlocked(f"No budget with ID {budget_id}.")
            new_active = not bool(current["active"]) if active is None else bool(active)
            self.repository.set_budget_active(budget_id, new_active)
            return {"budget": self.repository.get_budget(budget_id)}
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None

    def delete_budget(self, budget_id: int) -> None:
        """Delete a budget."""
        try:
            self.repository.delete_budget(budget_id)
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None

    def get_budget(self, budget_id: int) -> dict | None:
        return self.repository.get_budget(budget_id)

    def list_budgets(self, *, month: str | None = None, currency: str | None = None,
                     category_id: int | None = None, active: bool | None = None,
                     direction: str | None = None) -> list[dict]:
        try:
            return self.repository.list_budgets(
                month=month,
                currency=currency,
                category_id=category_id,
                active=active,
                direction=direction,
            )
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None

    def get_summary(self, month: str, currency: str | None = None) -> dict:
        try:
            return self.repository.budget_summary(month, currency)
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None

    def variance_analysis(self, month: str, currency: str | None = None,
                          direction: str | None = None) -> dict:
        """Corporate finance budget vs actual variance analysis.

        Compares planned budgets (ТӨСӨВ) against actual transactions (БОДИТ)
        for the given month, computing:
        - planned_minor
        - actual_minor
        - variance_minor (favorable/unfavorable)
        - utilization_pct (% execution)
        - status indicators (under_budget / over_budget / target_met / shortfall / unbudgeted)
        - summary totals (expense, income, net savings)
        """
        try:
            month = validate_month(month)
            if currency is not None:
                currency = validate_currency(currency)
        except ValueError as err:
            raise BudgetBlocked(str(err)) from None

        try:
            y, m = map(int, month.split("-"))
            last_day = monthrange(y, m)[1]
            date_from = f"{month}-01"
            date_to = f"{month}-{last_day:02d}"

            # 1. Fetch effective non-archived transaction rows
            rows = self.repository.reporting_rows(
                date_from=date_from, date_to=date_to, currency=currency, archived=False
            )

            # 2. Fetch budgets for the month
            budgets = self.repository.list_budgets(
                month=month, currency=currency, direction=direction
            )

            # Map active budgets by (currency, category_id, direction)
            budget_map = {}
            for b in budgets:
                key = (b["currency"], b["category_id"], b.get("category_direction", "expense"))
                budget_map[key] = b

            # 3. Group actual transactions by (currency, category_id, direction)
            actuals_map = {}
            for r in rows:
                kind = r["kind"]
                cat_id = r.get("category_id")
                if kind not in ("income", "expense") or cat_id is None:
                    continue
                if direction is not None and kind != direction:
                    continue
                r_curr = r["currency"]
                key = (r_curr, cat_id, kind)
                amt = r["amount_minor"] if kind == "income" else -r["amount_minor"]
                entry = actuals_map.setdefault(key, {
                    "actual_minor": 0,
                    "count": 0,
                    "category_name": r.get("category_name", ""),
                })
                entry["actual_minor"] += amt
                entry["count"] += 1

            # 4. Combine all keys
            all_keys = set(budget_map.keys()) | set(actuals_map.keys())
            items = []
            totals_by_currency = {}

            for curr, cat_id, dir_kind in sorted(all_keys, key=lambda k: (k[0], 0 if k[2] == "expense" else 1, k[1])):
                b_info = budget_map.get((curr, cat_id, dir_kind))
                a_info = actuals_map.get((curr, cat_id, dir_kind))

                # If budget is inactive, planned is 0
                planned_minor = b_info["planned_amount_minor"] if (b_info and b_info.get("active", 1)) else 0
                actual_minor = a_info["actual_minor"] if a_info else 0
                cat_name = (b_info["category_name"] if b_info else None) or (a_info["category_name"] if a_info else "Бусад")
                budget_id = b_info["id"] if b_info else None
                note = b_info.get("note", "") if b_info else ""
                active = bool(b_info.get("active", True)) if b_info else False

                # Calculate variance
                if dir_kind == "expense":
                    # For expenses: planned - actual. Positive = saved (favorable), Negative = over budget
                    variance_minor = planned_minor - actual_minor
                    if planned_minor == 0 and actual_minor > 0:
                        status = "unbudgeted"
                        status_label = "Төлөвлөгдөөгүй"
                    elif actual_minor > planned_minor:
                        status = "over_budget"
                        status_label = "Хэтэрсэн"
                    elif actual_minor == planned_minor and planned_minor > 0:
                        status = "on_track"
                        status_label = "Яг хүрсэн"
                    else:
                        status = "under_budget"
                        status_label = "Хэмнэсэн"
                else:
                    # For income: actual - planned. Positive = target exceeded, Negative = shortfall
                    variance_minor = actual_minor - planned_minor
                    if planned_minor == 0 and actual_minor > 0:
                        status = "unbudgeted"
                        status_label = "Нэмэлт орлого"
                    elif actual_minor >= planned_minor and planned_minor > 0:
                        status = "target_met"
                        status_label = "Биелсэн"
                    else:
                        status = "shortfall"
                        status_label = "Дутуу"

                # Utilization percentage
                if planned_minor > 0:
                    pct = round((actual_minor / planned_minor) * 100, 1)
                else:
                    pct = 100.0 if actual_minor > 0 else 0.0

                items.append({
                    "budget_id": budget_id,
                    "month": month,
                    "currency": curr,
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "direction": dir_kind,
                    "planned_minor": planned_minor,
                    "actual_minor": actual_minor,
                    "variance_minor": variance_minor,
                    "utilization_pct": pct,
                    "status": status,
                    "status_label": status_label,
                    "note": note,
                    "active": active,
                    "transaction_count": a_info["count"] if a_info else 0,
                })

                # Accumulate currency totals
                tot = totals_by_currency.setdefault(curr, {
                    "currency": curr,
                    "expense_budget": 0,
                    "expense_actual": 0,
                    "income_budget": 0,
                    "income_actual": 0,
                })
                if dir_kind == "expense":
                    tot["expense_budget"] += planned_minor
                    tot["expense_actual"] += actual_minor
                else:
                    tot["income_budget"] += planned_minor
                    tot["income_actual"] += actual_minor

            # Complete totals with variances and execution %
            for curr, tot in totals_by_currency.items():
                tot["expense_variance"] = tot["expense_budget"] - tot["expense_actual"]
                tot["income_variance"] = tot["income_actual"] - tot["income_budget"]
                tot["net_budget"] = tot["income_budget"] - tot["expense_budget"]
                tot["net_actual"] = tot["income_actual"] - tot["expense_actual"]
                tot["net_variance"] = tot["net_actual"] - tot["net_budget"]

                tot["expense_pct"] = round((tot["expense_actual"] / tot["expense_budget"] * 100), 1) if tot["expense_budget"] > 0 else (100.0 if tot["expense_actual"] > 0 else 0.0)
                tot["income_pct"] = round((tot["income_actual"] / tot["income_budget"] * 100), 1) if tot["income_budget"] > 0 else (100.0 if tot["income_actual"] > 0 else 0.0)

            return {
                "month": month,
                "currency": currency,
                "direction": direction,
                "items": items,
                "totals": totals_by_currency,
            }
        except (ValueError, TypeError, sqlite3.Error) as err:
            raise BudgetBlocked(str(err)) from None
