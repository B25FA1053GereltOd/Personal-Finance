"""Long-Term Financial Goal Tracker and Debt-to-Income (DTI) analysis service.

Calculates estimated timelines for home / apartment purchases based on:
- Historical savings rate (Хуримтлалын хувь)
- Income-to-debt ratio (Өр орлогын харьцаа / DTI)
- Configurable target apartment price and down payment percentage
"""

import json
import math
import os
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.config import get_data_dir
from app.models import money_to_minor, require_integer


# Standard defaults for Mongolia / Financial Planning
DEFAULT_APARTMENT_PRICE_MINOR = 200_000_000_00  # 200,000,000.00 MNT
DEFAULT_DOWN_PAYMENT_PCT = 30  # 30% standard mortgage down payment
DEFAULT_CURRENCY = "MNT"


@dataclass(frozen=True)
class GoalParameters:
    apartment_price_minor: int = DEFAULT_APARTMENT_PRICE_MINOR
    down_payment_pct: int = DEFAULT_DOWN_PAYMENT_PCT
    initial_savings_minor: int = 0
    target_monthly_savings_minor: int | None = None
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self):
        require_integer(self.apartment_price_minor, "Apartment price", minimum=1_000_00)
        require_integer(self.down_payment_pct, "Down payment percentage", minimum=1)
        if self.down_payment_pct > 100:
            raise ValueError("Down payment percentage cannot exceed 100%.")
        require_integer(self.initial_savings_minor, "Initial savings", minimum=0)
        if self.target_monthly_savings_minor is not None:
            require_integer(self.target_monthly_savings_minor, "Target monthly savings", minimum=0)


def load_goal_parameters(data_dir: Path | None = None) -> GoalParameters:
    """Load goal configuration from settings.json or return standard defaults."""
    folder = Path(data_dir) if data_dir else get_data_dir()
    path = folder / "settings.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "goal_settings" in data:
                raw = data["goal_settings"]
                return GoalParameters(
                    apartment_price_minor=raw.get("apartment_price_minor", DEFAULT_APARTMENT_PRICE_MINOR),
                    down_payment_pct=raw.get("down_payment_pct", DEFAULT_DOWN_PAYMENT_PCT),
                    initial_savings_minor=raw.get("initial_savings_minor", 0),
                    target_monthly_savings_minor=raw.get("target_monthly_savings_minor"),
                    currency=raw.get("currency", DEFAULT_CURRENCY),
                )
        except Exception:
            pass
    return GoalParameters()


def save_goal_parameters(data_dir: Path | None, params: GoalParameters) -> None:
    """Persist goal parameters into settings.json safely."""
    folder = Path(data_dir) if data_dir else get_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "settings.json"
    settings = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}

    settings["goal_settings"] = {
        "apartment_price_minor": params.apartment_price_minor,
        "down_payment_pct": params.down_payment_pct,
        "initial_savings_minor": params.initial_savings_minor,
        "target_monthly_savings_minor": params.target_monthly_savings_minor,
        "currency": params.currency,
    }

    tmp = folder / f"settings_{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


class GoalService:
    """Computes apartment timeline, savings rates, and debt-to-income (DTI) metrics."""

    def __init__(self, repository, data_dir: Path | None = None):
        self.repository = repository
        self.data_dir = data_dir

    def get_parameters(self) -> GoalParameters:
        return load_goal_parameters(self.data_dir)

    def update_parameters(self, **kwargs) -> GoalParameters:
        current = self.get_parameters()
        new_params = GoalParameters(
            apartment_price_minor=kwargs.get("apartment_price_minor", current.apartment_price_minor),
            down_payment_pct=kwargs.get("down_payment_pct", current.down_payment_pct),
            initial_savings_minor=kwargs.get("initial_savings_minor", current.initial_savings_minor),
            target_monthly_savings_minor=kwargs.get("target_monthly_savings_minor", current.target_monthly_savings_minor),
            currency=kwargs.get("currency", current.currency),
        )
        save_goal_parameters(self.data_dir, new_params)
        return new_params

    def calculate_apartment_goal(self, currency: str | None = None,
                                 params: GoalParameters | None = None) -> dict[str, Any]:
        """Analyze financial history to calculate apartment timeline and DTI status."""
        params = params or self.get_parameters()
        target_curr = currency or params.currency

        # Fetch non-archived transaction rows
        rows = self.repository.reporting_rows(currency=target_curr, archived=False)

        # Aggregate monthly financial figures
        months_data: dict[str, dict[str, int]] = {}
        for r in rows:
            month = r["occurred_at"][:7]
            kind = r["kind"]
            amount = r["amount_minor"]
            cat_name = (r.get("category_name") or "").strip()

            entry = months_data.setdefault(month, {
                "income": 0,
                "expenses": 0,
                "debt_payments": 0,
                "explicit_savings": 0,
            })

            if kind == "income":
                entry["income"] += amount
            elif kind == "expense":
                exp_abs = abs(amount)
                entry["expenses"] += exp_abs
                # Track debt repayment category ("Өр төлөлт" / "Debt Repayment")
                if "өр" in cat_name.lower() or "debt" in cat_name.lower():
                    entry["debt_payments"] += exp_abs
                # Track explicit savings category ("Хуримтлал" / "Savings")
                if "хуримтлал" in cat_name.lower() or "saving" in cat_name.lower():
                    entry["explicit_savings"] += exp_abs

        # Calculate monthly averages
        month_count = len(months_data)
        if month_count > 0:
            total_income = sum(m["income"] for m in months_data.values())
            total_expenses = sum(m["expenses"] for m in months_data.values())
            total_debt = sum(m["debt_payments"] for m in months_data.values())
            total_net = total_income - total_expenses

            avg_monthly_income = total_income // month_count
            avg_monthly_expenses = total_expenses // month_count
            avg_monthly_debt = total_debt // month_count
            calculated_monthly_savings = max(0, (total_income - total_expenses) // month_count)
            accumulated_net_savings = max(0, total_net)
        else:
            avg_monthly_income = 0
            avg_monthly_expenses = 0
            avg_monthly_debt = 0
            calculated_monthly_savings = 0
            accumulated_net_savings = 0

        # Effective monthly savings (use user override if specified)
        if params.target_monthly_savings_minor is not None and params.target_monthly_savings_minor > 0:
            effective_monthly_savings = params.target_monthly_savings_minor
        else:
            effective_monthly_savings = calculated_monthly_savings

        # Total accumulated savings (initial override + net savings)
        total_accumulated_savings = params.initial_savings_minor + accumulated_net_savings

        # Goal targets
        apartment_price = params.apartment_price_minor
        down_payment_pct = params.down_payment_pct
        down_payment_target = (apartment_price * down_payment_pct) // 100
        remaining_down_payment = max(0, down_payment_target - total_accumulated_savings)

        # 1. Savings Rate (%) = (Savings / Income) * 100
        if avg_monthly_income > 0:
            savings_rate_pct = round((effective_monthly_savings / avg_monthly_income) * 100, 1)
        else:
            savings_rate_pct = 0.0

        if savings_rate_pct >= 30.0:
            savings_grade = "excellent"
            savings_grade_label = "Маш сайн"
        elif savings_rate_pct >= 20.0:
            savings_grade = "good"
            savings_grade_label = "Хэвийн сайн"
        elif savings_rate_pct >= 10.0:
            savings_grade = "moderate"
            savings_grade_label = "Дундаж"
        else:
            savings_grade = "low"
            savings_grade_label = "Бага"

        # 2. Debt-to-Income Ratio (Өр орлогын харьцаа / DTI)
        # Mongolbank banking standard: DTI <= 40% (Prime), 40-50% (Eligible), > 50% (High burden)
        if avg_monthly_income > 0:
            dti_pct = round((avg_monthly_debt / avg_monthly_income) * 100, 1)
        else:
            dti_pct = 0.0

        if dti_pct <= 40.0:
            dti_status = "prime"
            dti_label = "Ипотект тэнцэх өндөр боломжтой"
            dti_badge_color = "#10b981"
            dti_advice = "Өр орлогын харьцаа 40%-иас бага тул банкны ипотекийн 6% эсвэл 8% зээлийн шалгуурт бүрэн нийцнэ."
        elif dti_pct <= 50.0:
            dti_status = "eligible"
            dti_label = "Зээлд тэнцэх боломжтой"
            dti_badge_color = "#f59e0b"
            dti_advice = "Өр орлогын харьцаа 50%-ийн дээд хязгаарт ойр байгаа тул өрөө нэмэлгүй хадгалахыг зөвлөж байна."
        else:
            dti_status = "high_burden"
            dti_label = "Өрийн дарамт өндөр"
            dti_badge_color = "#ef4444"
            dti_advice = "Өр орлогын харьцаа 50%-иас давсан байна. Ипотекийн зээл авахаас өмнө одоо байгаа өрөө дарж бууруулах шаардлагатай."

        # 3. Estimated Timeline Calculation
        progress_pct = min(100.0, round((total_accumulated_savings / down_payment_target) * 100, 1)) if down_payment_target > 0 else 100.0

        if remaining_down_payment == 0:
            months_needed = 0
            timeline_text = "Зорилтот урьдчилгаа хуримтлагдсан!"
            timeline_subtitle = "Ипотекийн зээл хүсэх эсвэл байраа худалдан авахад бэлэн"
            estimated_target_date = "Одоо бэлэн"
        elif effective_monthly_savings > 0:
            months_needed = math.ceil(remaining_down_payment / effective_monthly_savings)
            years = months_needed // 12
            months = months_needed % 12
            if years > 0 and months > 0:
                timeline_text = f"{years} жил {months} сар"
            elif years > 0:
                timeline_text = f"{years} жил"
            else:
                timeline_text = f"{months} сар"

            timeline_subtitle = f"Нийт {months_needed} сарын дараа зорилтод хүрнэ"

            today = date.today()
            target_year = today.year + (today.month - 1 + months_needed) // 12
            target_month = (today.month - 1 + months_needed) % 12 + 1
            estimated_target_date = f"{target_year} оны {target_month}-р сар"
        else:
            months_needed = None
            timeline_text = "Хугацаа тодорхойлох боломжгүй"
            timeline_subtitle = "Сар бүрийн хуримтлалын дүнг нэмэгдүүлж тооцоолно уу"
            estimated_target_date = "Хуримтлал шаардлагатай"

        return {
            "currency": target_curr,
            "apartment_price_minor": apartment_price,
            "down_payment_pct": down_payment_pct,
            "down_payment_target_minor": down_payment_target,
            "total_accumulated_savings_minor": total_accumulated_savings,
            "remaining_down_payment_minor": remaining_down_payment,
            "progress_pct": progress_pct,
            "avg_monthly_income_minor": avg_monthly_income,
            "avg_monthly_expenses_minor": avg_monthly_expenses,
            "avg_monthly_debt_minor": avg_monthly_debt,
            "effective_monthly_savings_minor": effective_monthly_savings,
            "savings_rate_pct": savings_rate_pct,
            "savings_grade": savings_grade,
            "savings_grade_label": savings_grade_label,
            "dti_pct": dti_pct,
            "dti_status": dti_status,
            "dti_label": dti_label,
            "dti_badge_color": dti_badge_color,
            "dti_advice": dti_advice,
            "months_needed": months_needed,
            "timeline_text": timeline_text,
            "timeline_subtitle": timeline_subtitle,
            "estimated_target_date": estimated_target_date,
            "month_count": month_count,
        }
