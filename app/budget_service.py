"""Monthly budget service for stage 1 budget management."""

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
