"""Monthly budget UI: view, filter, add, edit, and toggle budgets by month, currency and category."""

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from app.models import money_to_minor, validate_currency, validate_month
from app.reporting import format_money
from app.ui.i18n import get_category_display_name, localize_widget_tree, source_text
from app.ui.review import selected_items


def shift_month(month_str: str, delta: int) -> str:
    """Add delta months to a YYYY-MM string."""
    try:
        y, m = map(int, month_str.strip().split("-"))
        total = y * 12 + (m - 1) + delta
        new_y = total // 12
        new_m = total % 12 + 1
        return f"{new_y:04d}-{new_m:02d}"
    except Exception:
        return datetime.now().strftime("%Y-%m")


class BudgetDialog:
    """Modal dialog for creating or editing a monthly budget."""

    def __init__(self, parent, app, on_save, budget=None, default_month=None, default_currency="MNT"):
        self.app = app
        self.on_save = on_save
        self.budget = budget
        self.dialog = tk.Toplevel(parent)
        self.dialog.transient(parent)
        self.dialog.resizable(False, False)

        is_edit = budget is not None
        title = app.t("Edit budget" if is_edit else "Add budget")
        self.dialog.title(title)

        frame = ttk.Frame(self.dialog, padding=16)
        frame.pack(fill="both", expand=True)

        # 1. Month
        ttk.Label(frame, text=app.t("Month")).grid(row=0, column=0, sticky="w", pady=4)
        init_month = budget["month"] if is_edit else (default_month or datetime.now().strftime("%Y-%m"))
        self.month_var = tk.StringVar(value=init_month)
        month_entry = ttk.Entry(frame, textvariable=self.month_var, width=16)
        month_entry.grid(row=0, column=1, sticky="w", pady=4, padx=6)

        # 2. Currency
        ttk.Label(frame, text=app.t("Currency")).grid(row=1, column=0, sticky="w", pady=4)
        init_curr = budget["currency"] if is_edit else (default_currency or "MNT")
        self.currency_var = tk.StringVar(value=init_curr)
        known_currencies = sorted(list({a["currency"] for a in app.accounts} | {"MNT", "USD", "EUR"}))
        currency_combo = ttk.Combobox(frame, textvariable=self.currency_var, values=known_currencies, width=14)
        currency_combo.grid(row=1, column=1, sticky="w", pady=4, padx=6)

        # 3. Direction
        ttk.Label(frame, text=app.t("Direction")).grid(row=2, column=0, sticky="w", pady=4)
        init_dir = budget.get("category_direction", "expense") if is_edit else "expense"
        self.direction_var = tk.StringVar(value=app.t("Expense" if init_dir == "expense" else "Income"))
        direction_combo = ttk.Combobox(
            frame, textvariable=self.direction_var, state="readonly", width=14,
            values=(app.t("Expense"), app.t("Income")),
        )
        direction_combo.grid(row=2, column=1, sticky="w", pady=4, padx=6)
        direction_combo.bind("<<ComboboxSelected>>", lambda _: self._update_categories())

        # 4. Category
        ttk.Label(frame, text=app.t("Category")).grid(row=3, column=0, sticky="w", pady=4)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(frame, textvariable=self.category_var, state="readonly", width=32)
        self.category_combo.grid(row=3, column=1, sticky="w", pady=4, padx=6)

        # 5. Planned Amount
        ttk.Label(frame, text=app.t("Planned amount")).grid(row=4, column=0, sticky="w", pady=4)
        if is_edit:
            init_amount = f"{budget['planned_amount_minor'] / 100:.2f}"
        else:
            init_amount = ""
        self.amount_var = tk.StringVar(value=init_amount)
        amount_entry = ttk.Entry(frame, textvariable=self.amount_var, width=16)
        amount_entry.grid(row=4, column=1, sticky="w", pady=4, padx=6)

        # 6. Active status
        ttk.Label(frame, text=app.t("Active status")).grid(row=5, column=0, sticky="w", pady=4)
        self.active_var = tk.BooleanVar(value=bool(budget["active"]) if is_edit else True)
        active_check = ttk.Checkbutton(frame, text=app.t("Active"), variable=self.active_var)
        active_check.grid(row=5, column=1, sticky="w", pady=4, padx=6)

        # 7. Note
        ttk.Label(frame, text=app.t("Budget note")).grid(row=6, column=0, sticky="w", pady=4)
        self.note_var = tk.StringVar(value=budget.get("note", "") if is_edit else "")
        note_entry = ttk.Entry(frame, textvariable=self.note_var, width=32)
        note_entry.grid(row=6, column=1, sticky="w", pady=4, padx=6)

        # Populate categories
        self._update_categories(budget.get("category_id") if is_edit else None)

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))

        save_btn = ttk.Button(btn_frame, text=app.t("Save"), style="Primary.TButton", command=self._save)
        save_btn.pack(side="right", padx=(6, 0))

        cancel_btn = ttk.Button(btn_frame, text=app.t("Cancel"), command=self.dialog.destroy)
        cancel_btn.pack(side="right")

        localize_widget_tree(self.dialog)
        self.dialog.grab_set()

    def _get_direction(self) -> str:
        val = source_text(self.direction_var.get(), ("Expense", "Income", "expense", "income")).lower()
        if val in ("income", "credit"):
            return "income"
        return "expense"

    def _update_categories(self, selected_id=None):
        direction = self._get_direction()
        cats = self.app.active_categories(direction=direction)
        display_names = [self.app.category_display_name(c) for c in cats]
        self.category_combo.configure(values=display_names)
        if selected_id:
            matched = next((c for c in cats if c["id"] == selected_id), None)
            if matched:
                self.category_var.set(self.app.category_display_name(matched))
                return
        if display_names:
            self.category_var.set(display_names[0])
        else:
            self.category_var.set("")

    def _save(self):
        month_str = self.month_var.get().strip()
        try:
            month = validate_month(month_str)
        except ValueError:
            messagebox.showwarning(self.app.t("Budget"), self.app.t("Month must be in YYYY-MM format."), parent=self.dialog)
            return

        currency_str = self.currency_var.get().strip().upper()
        try:
            currency = validate_currency(currency_str)
        except ValueError:
            messagebox.showwarning(self.app.t("Budget"), self.app.t("Choose a currency."), parent=self.dialog)
            return

        direction = self._get_direction()
        cat_display = self.category_var.get().strip()
        cats = self.app.active_categories(direction=direction)
        cat_id = None
        for c in cats:
            if self.app.category_display_name(c) == cat_display or c["name"] == cat_display:
                cat_id = c["id"]
                break
        if cat_id is None:
            cat_id = self.app.resolve_category_id(cat_display)

        if cat_id is None:
            messagebox.showwarning(self.app.t("Budget"), self.app.t("Choose a category."), parent=self.dialog)
            return

        amount_str = self.amount_var.get().strip().replace(",", "")
        try:
            amount_minor = money_to_minor(amount_str)
            if amount_minor <= 0:
                raise ValueError
        except Exception:
            messagebox.showwarning(self.app.t("Budget"), self.app.t("Enter a positive planned amount."), parent=self.dialog)
            return

        payload = {
            "month": month,
            "currency": currency,
            "category_id": cat_id,
            "planned_amount_minor": amount_minor,
            "note": self.note_var.get().strip(),
            "active": self.active_var.get(),
        }
        if self.budget is not None:
            payload["budget_id"] = self.budget["id"]

        self.dialog.destroy()
        self.on_save(payload)


class BudgetView:
    """Monthly budget management page with month navigation, filtering, and summary cards."""

    def __init__(self, app, table_factory):
        self.app = app
        self.table_factory = table_factory
        self.budgets = []
        self.summary = {}

        self.tab = ttk.Frame(app.tabs, padding=10)
        app.tabs.add(self.tab, text="Budget")
        self.tab.columnconfigure(0, weight=1)
        self.tab.rowconfigure(3, weight=1)

        # ---------------------------------------------------------------------
        # Row 0: Month Navigation & Filter Controls
        # ---------------------------------------------------------------------
        nav_frame = ttk.Frame(self.tab)
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Month navigation controls
        ttk.Label(nav_frame, text=app.t("Selected month") + ":", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))

        prev_btn = ttk.Button(nav_frame, text="◀", width=3, command=self._prev_month)
        prev_btn.pack(side="left", padx=2)

        self.month_var = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        self.month_entry = ttk.Entry(nav_frame, textvariable=self.month_var, width=10, font=("Segoe UI", 10))
        self.month_entry.pack(side="left", padx=2)
        self.month_entry.bind("<Return>", lambda _: self.load())

        next_btn = ttk.Button(nav_frame, text="▶", width=3, command=self._next_month)
        next_btn.pack(side="left", padx=2)

        this_month_btn = ttk.Button(nav_frame, text=app.t("This month"), command=self._this_month)
        this_month_btn.pack(side="left", padx=4)

        # Filters
        ttk.Separator(nav_frame, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(nav_frame, text=app.t("Currency") + ":").pack(side="left", padx=(4, 2))
        self.currency_var = tk.StringVar(value=app.t("All currencies"))
        self.currency_combo = ttk.Combobox(
            nav_frame, textvariable=self.currency_var, state="readonly", width=14,
            values=(app.t("All currencies"), "MNT", "USD", "EUR"),
        )
        self.currency_combo.pack(side="left", padx=3)
        self.currency_combo.bind("<<ComboboxSelected>>", lambda _: self.load())

        ttk.Label(nav_frame, text=app.t("Direction") + ":").pack(side="left", padx=(6, 2))
        self.direction_var = tk.StringVar(value=app.t("All directions"))
        self.direction_combo = ttk.Combobox(
            nav_frame, textvariable=self.direction_var, state="readonly", width=14,
            values=(app.t("All directions"), app.t("Expense"), app.t("Income")),
        )
        self.direction_combo.pack(side="left", padx=3)
        self.direction_combo.bind("<<ComboboxSelected>>", lambda _: self.load())

        ttk.Label(nav_frame, text=app.t("Active status") + ":").pack(side="left", padx=(6, 2))
        self.active_var = tk.StringVar(value=app.t("All rules"))
        self.active_combo = ttk.Combobox(
            nav_frame, textvariable=self.active_var, state="readonly", width=12,
            values=(app.t("All rules"), app.t("Active"), app.t("Disabled")),
        )
        self.active_combo.pack(side="left", padx=3)
        self.active_combo.bind("<<ComboboxSelected>>", lambda _: self.load())

        # ---------------------------------------------------------------------
        # Row 1: Action Toolbar
        # ---------------------------------------------------------------------
        action_frame = ttk.Frame(self.tab)
        action_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.btn_add = ttk.Button(action_frame, text=f"➕  {app.t('Add budget')}", command=self.add_budget)
        self.btn_add.pack(side="left", padx=3)

        self.btn_edit = ttk.Button(action_frame, text=f"✏  {app.t('Edit budget')}", command=self.edit_budget)
        self.btn_edit.pack(side="left", padx=3)

        self.btn_toggle = ttk.Button(action_frame, text=f"⚡  {app.t('Enable / disable')}", command=self.toggle_budget)
        self.btn_toggle.pack(side="left", padx=3)

        self.btn_delete = ttk.Button(action_frame, text=f"🗑  {app.t('Delete budget')}", command=self.delete_budget)
        self.btn_delete.pack(side="left", padx=3)

        self.btn_refresh = ttk.Button(action_frame, text=f"🔄  {app.t('Refresh')}", command=self.load)
        self.btn_refresh.pack(side="left", padx=3)

        # ---------------------------------------------------------------------
        # Row 2: Summary Cards Frame
        # ---------------------------------------------------------------------
        self.summary_frame = ttk.Frame(self.tab)
        self.summary_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.summary_expense_var = tk.StringVar(value="—")
        self.summary_income_var = tk.StringVar(value="—")
        self.summary_count_var = tk.StringVar(value="0")

        self.card_expense = self._create_card(self.summary_frame, app.t("Planned Expense"), self.summary_expense_var, 0, color="expense")
        self.card_income = self._create_card(self.summary_frame, app.t("Planned Income"), self.summary_income_var, 1, color="income")
        self.card_count = self._create_card(self.summary_frame, app.t("Total"), self.summary_count_var, 2)

        # ---------------------------------------------------------------------
        # Row 3: PagedTable
        # ---------------------------------------------------------------------
        self.table = table_factory(self.tab, [
            ("id", "ID", 45),
            ("month", "Month", 85),
            ("currency", "Currency", 75),
            ("direction", "Direction", 85),
            ("category", "Category", 230),
            ("planned_amount", "Planned Amount", 140),
            ("active", "Active status", 85),
            ("note", "Budget note", 200),
        ], title="Monthly Budget", height=14)
        self.table.grid(row=3, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda _: self.sync())

        # ---------------------------------------------------------------------
        # Row 4: Status / Empty state banner
        # ---------------------------------------------------------------------
        self.status = tk.StringVar(value="")
        self.status_label = ttk.Label(self.tab, textvariable=self.status, wraplength=1000)
        self.status_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

        self.sync()

    def _create_card(self, parent, title, text_var, column, color=None):
        parent.columnconfigure(column, weight=1, uniform="budget_card")
        frame = ttk.Frame(parent, padding=(12, 8), style="Card.TFrame")
        frame.grid(row=0, column=column, padx=4, sticky="nsew")
        ttk.Label(frame, text=title, font=("Segoe UI", 9), style="CardTitle.TLabel").pack(anchor="w")
        val_label = ttk.Label(frame, textvariable=text_var, font=("Segoe UI", 13, "bold"), style="CardValue.TLabel")
        if color == "expense":
            val_label.configure(foreground="#ef4444")
        elif color == "income":
            val_label.configure(foreground="#10b981")
        val_label.pack(anchor="w", pady=(2, 0))
        return frame

    def _prev_month(self):
        self.month_var.set(shift_month(self.month_var.get(), -1))
        self.load()

    def _next_month(self):
        self.month_var.set(shift_month(self.month_var.get(), 1))
        self.load()

    def _this_month(self):
        self.month_var.set(datetime.now().strftime("%Y-%m"))
        self.load()

    def sync(self):
        """Update button enabled states based on row selection and worker status."""
        idle = (self.app.ready and not self.app.busy and not self.app.closing
                and self.app.preview is None)
        selected = len(selected_items(self.table)) == 1

        self.app._enabled(self.btn_add, idle)
        self.app._enabled(self.btn_edit, idle and selected)
        self.app._enabled(self.btn_toggle, idle and selected)
        self.app._enabled(self.btn_delete, idle and selected)
        self.app._enabled(self.btn_refresh, idle)

    def sync_categories(self):
        """Called when categories are added, modified or deleted."""
        pass

    def load(self):
        """Request budgets and summary from the worker."""
        if not self.app.ready or self.app.busy:
            return

        month_str = self.month_var.get().strip()
        try:
            month = validate_month(month_str)
        except ValueError:
            month = datetime.now().strftime("%Y-%m")
            self.month_var.set(month)

        curr_src = source_text(self.currency_var.get(), ("All currencies",))
        currency = None if curr_src == "All currencies" else curr_src

        dir_src = source_text(self.direction_var.get(), ("All directions", "Expense", "Income", "Debit", "Credit"))
        direction = None
        if dir_src in ("Expense", "Debit", "expense"):
            direction = "expense"
        elif dir_src in ("Income", "Credit", "income"):
            direction = "income"

        state_src = source_text(self.active_var.get(), ("All rules", "Active", "Disabled"))
        active = None
        if state_src == "Active":
            active = True
        elif state_src == "Disabled":
            active = False

        self.app._request("budget_list", month=month, currency=currency, direction=direction, active=active)

    def add_budget(self):
        curr_src = source_text(self.currency_var.get(), ("All currencies",))
        default_curr = "MNT" if curr_src == "All currencies" else curr_src
        BudgetDialog(
            self.app.window, self.app,
            on_save=self._save_budget_payload,
            default_month=self.month_var.get().strip(),
            default_currency=default_curr,
        )

    def edit_budget(self):
        items = selected_items(self.table)
        if len(items) != 1:
            return
        budget = items[0]
        BudgetDialog(
            self.app.window, self.app,
            on_save=self._save_budget_payload,
            budget=budget,
        )

    def _save_budget_payload(self, payload):
        self.app._request("budget_save", **payload)

    def toggle_budget(self):
        items = selected_items(self.table)
        if len(items) != 1:
            return
        budget = items[0]
        self.app._request("budget_active", budget_id=budget["id"])

    def delete_budget(self):
        items = selected_items(self.table)
        if len(items) != 1:
            return
        budget = items[0]
        cat_name = self.app.category_display_name(budget["category_id"])
        confirm = messagebox.askyesno(
            self.app.t("Delete budget"),
            f"{self.app.t('Delete budget')} {cat_name} ({budget['currency']})?",
            parent=self.app.window,
        )
        if confirm:
            self.app._request("budget_delete", budget_id=budget["id"])

    def handle(self, operation: str, payload):
        """Handle worker events for budget operations."""
        if operation == "budget_list":
            self.budgets = payload.get("budgets", [])
            self.summary = payload.get("summary", {})

            # Format rows for PagedTable
            def format_row(b):
                cat_disp = self.app.category_display_name(b["category_id"])
                dir_label = self.app.t("Expense" if b.get("category_direction") == "expense" else "Income")
                status_label = self.app.t("Active" if b["active"] else "Disabled")
                return (
                    b["id"],
                    b["month"],
                    b["currency"],
                    dir_label,
                    cat_disp,
                    format_money(b["planned_amount_minor"], b["currency"]),
                    status_label,
                    b.get("note", ""),
                )

            self.table.set_items(self.budgets, format_row)

            # Update summary cards
            curr_src = source_text(self.currency_var.get(), ("All currencies",))
            if curr_src != "All currencies" and curr_src in self.summary:
                info = self.summary[curr_src]
                self.summary_expense_var.set(format_money(info["planned_expense"], curr_src))
                self.summary_income_var.set(format_money(info["planned_income"], curr_src))
                self.summary_count_var.set(str(len(self.budgets)))
            elif len(self.summary) == 1:
                curr = next(iter(self.summary.keys()))
                info = self.summary[curr]
                self.summary_expense_var.set(format_money(info["planned_expense"], curr))
                self.summary_income_var.set(format_money(info["planned_income"], curr))
                self.summary_count_var.set(str(len(self.budgets)))
            elif len(self.summary) > 1:
                # Multiple currencies summary
                exp_strs = [format_money(s["planned_expense"], c) for c, s in sorted(self.summary.items())]
                inc_strs = [format_money(s["planned_income"], c) for c, s in sorted(self.summary.items())]
                self.summary_expense_var.set(" | ".join(exp_strs))
                self.summary_income_var.set(" | ".join(inc_strs))
                self.summary_count_var.set(str(len(self.budgets)))
            else:
                self.summary_expense_var.set("—")
                self.summary_income_var.set("—")
                self.summary_count_var.set("0")

            # Update empty-state or count in status
            if not self.budgets:
                self.status.set(self.app.t("No budgets found for this month."))
            else:
                self.status.set(f"{len(self.budgets)} {self.app.t('Budgets')}")

            self.sync()

        elif operation in ("budget_save", "budget_active", "budget_delete"):
            self.load()
