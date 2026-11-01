"""Lightweight tables and Canvas charts; reporting and filter logic stay outside widgets."""

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from app.reporting import (
    PRESETS, ReportingError, category_chart_series, category_filters,
    format_money, month_filters, monthly_chart_series,
)
from app.ui.i18n import source_text
from app.ui.review import selected_items
from app.ui.theme import BORDER, FONT, GREEN, MUTED, NAVY, RED, SURFACE, WHITE, get_current_theme
from app.ui.view_models import dashboard_summary


MIN_CHART_HEIGHT = 320

CHART_TITLES = {
    "month": "Monthly income vs expense",
    "expense": "Expenses by category",
    "income": "Income by category",
}


def _unclassified_cell(row: dict):
    count = row.get("unclassified", 0)
    amount = row.get("unclassified_amount", 0)
    if count or amount:
        return f'{count} ({format_money(amount, row["currency"])})'
    return 0


def safe_category_label(text: str, max_chars: int = 34) -> str:
    """Wrap or shorten long category labels safely so chart text never clips."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


class ChartCanvas:
    """Full-width Canvas chart consuming pre-aggregated reporting series."""

    def __init__(self, parent, kind: str, translate=lambda s: s, *, min_height: int = MIN_CHART_HEIGHT):
        self.kind = kind
        self.translate = translate
        self.min_height = max(300, int(min_height))
        self.title_key = CHART_TITLES.get(kind, "Dashboard")
        self.title = self.translate(self.title_key)
        self.series = ()
        self.empty_message = ""
        self.drawn_items = []
        self.legends = []
        self.current_height = self.min_height
        self.theme_tokens = None
        self.canvas = None
        if isinstance(parent, tk.Misc) and isinstance(getattr(parent, "_w", None), str):
            tokens = get_current_theme()
            self.canvas = tk.Canvas(
                parent, background=tokens.chart_bg, highlightthickness=1,
                highlightbackground=tokens.border, height=self.min_height,
            )
            self.canvas.bind("<Configure>", lambda _event: self._redraw(), add="+")

    def grid(self, **kwargs):
        if self.canvas is not None:
            self.canvas.grid(**kwargs)

    def set_theme(self, tokens):
        self.theme_tokens = tokens
        if self.canvas is not None:
            self.canvas.configure(background=tokens.chart_bg, highlightbackground=tokens.border)
        self._redraw()

    def render(self, series, empty_message: str = "No chart data for the selected period and currency."):
        self.series = tuple(series)
        self.title = self.translate(self.title_key)
        self.empty_message = self.translate(empty_message) if not self.series else ""
        self._redraw()

    def _panel_height(self, section: dict) -> int:
        if self.kind == "month":
            return self.min_height
        count = min(8, len(section.get("bars", ())))
        return max(self.min_height, 96 + count * 38)

    def _redraw(self):
        tokens = self.theme_tokens or get_current_theme()
        self.drawn_items = []
        self.legends = []
        if not self.series:
            total_height = self.min_height
        else:
            total_height = sum(self._panel_height(section) for section in self.series)
        self.current_height = total_height
        if self.canvas is not None:
            if int(self.canvas.cget("height")) != total_height:
                self.canvas.configure(height=total_height)
            self.canvas.delete("all")
            width = max(680, int(self.canvas.winfo_width()))
            height = max(total_height, int(self.canvas.winfo_height()))
        else:
            width, height = 960, total_height

        pad_x = 24
        if not self.series:
            self.drawn_items.append({
                "type": "empty",
                "title": self.title,
                "text": self.empty_message,
            })
            if self.canvas is not None and self.empty_message:
                self.canvas.create_text(
                    pad_x, 24, anchor="w", text=self.title,
                    fill=tokens.text, font=(FONT, 11, "bold"),
                )
                self.canvas.create_rectangle(
                    pad_x, 48, width - pad_x, height - 24,
                    fill=tokens.surface, outline=tokens.border,
                )
                self.canvas.create_text(
                    width // 2, (48 + height - 24) // 2,
                    text=self.empty_message, fill=tokens.muted,
                    font=(FONT, 10), width=max(320, width - 96),
                )
            return

        y_offset = 0
        for index, section in enumerate(self.series):
            panel_h = self._panel_height(section)
            y0 = y_offset
            y1 = y0 + panel_h
            y_offset = y1
            if index > 0 and self.canvas is not None:
                self.canvas.create_line(pad_x, y0 + 2, width - pad_x, y0 + 2, fill=tokens.border)
            if self.kind == "month":
                self._draw_monthly(section, pad_x, width - pad_x, y0 + 16, y1 - 18)
            else:
                self._draw_categories(section, pad_x, width - pad_x, y0 + 16, y1 - 18)

    def _draw_legend(self, x_right: int, y_top: int, entries: list[tuple[str, str]]):
        tokens = self.theme_tokens or get_current_theme()
        cursor_x = x_right
        for label, color in reversed(entries):
            self.legends.append({"label": label, "color": color})
            text_w = max(56, len(label) * 7 + 10)
            cursor_x -= text_w
            if self.canvas is not None:
                self.canvas.create_text(
                    cursor_x + 16, y_top, anchor="w",
                    text=label, fill=tokens.text, font=(FONT, 9, "bold"),
                )
                self.canvas.create_rectangle(
                    cursor_x, y_top - 6, cursor_x + 12, y_top + 6,
                    fill=color, outline="",
                )
            cursor_x -= 16

    def _draw_monthly(self, section: dict, x0: int, x1: int, y0: int, y1: int):
        tokens = self.theme_tokens or get_current_theme()
        currency = section["currency"]
        header = f"{self.title} ({currency})"
        inc_text = self.translate("Income")
        exp_text = self.translate("Expenses")
        if self.canvas is not None:
            self.canvas.create_text(x0, y0, anchor="w", text=header, fill=tokens.text, font=(FONT, 11, "bold"))
        self._draw_legend(x1, y0, [(inc_text, tokens.income), (exp_text, tokens.expense)])

        bars = section["bars"]
        max_minor = max(1, section["max_minor"])
        axis_w = 135
        plot_x0 = x0 + axis_w
        plot_x1 = x1 - 12
        top = y0 + 36
        bottom = y1 - 44
        usable_h = max(120, bottom - top)

        for fraction in (0.0, 0.5, 1.0):
            gy = int(bottom - fraction * usable_h)
            tick_minor = int(round(max_minor * fraction))
            tick_label = format_money(tick_minor, currency)
            if self.canvas is not None:
                self.canvas.create_line(plot_x0, gy, plot_x1, gy, fill=tokens.border if fraction == 0.0 else tokens.chart_grid)
                self.canvas.create_text(
                    plot_x0 - 10, gy, anchor="e",
                    text=tick_label, fill=tokens.muted, font=(FONT, 8),
                )

        slot_w = max(72, (plot_x1 - plot_x0 - 16) // max(1, len(bars)))
        bar_w = max(16, min(38, (slot_w - 22) // 2))
        for i, item in enumerate(bars):
            group_center = plot_x0 + 12 + i * slot_w + slot_w // 2
            inc_x0 = group_center - bar_w - 3
            exp_x0 = group_center + 3
            inc_h = int(item["income"] * usable_h // max_minor) if item["income"] > 0 else 0
            exp_h = int(item["expenses"] * usable_h // max_minor) if item["expenses"] > 0 else 0
            self.drawn_items.append({
                "type": "month_bar",
                "currency": currency,
                "month": item["month"],
                "income": item["income"],
                "expenses": item["expenses"],
                "net": item["net"],
                "income_label": item["income_label"],
                "expense_label": item["expense_label"],
            })
            if self.canvas is not None:
                if inc_h > 0:
                    inc_top = bottom - max(4, inc_h)
                    self.canvas.create_rectangle(
                        inc_x0, inc_top, inc_x0 + bar_w, bottom,
                        fill=tokens.income, outline="",
                    )
                    self.canvas.create_text(
                        inc_x0 + bar_w // 2, max(y0 + 20, inc_top - 10),
                        text=item["income_label"], fill=tokens.income, font=(FONT, 8, "bold"),
                    )
                if exp_h > 0:
                    exp_top = bottom - max(4, exp_h)
                    self.canvas.create_rectangle(
                        exp_x0, exp_top, exp_x0 + bar_w, bottom,
                        fill=tokens.expense, outline="",
                    )
                    self.canvas.create_text(
                        exp_x0 + bar_w // 2, max(y0 + 20, exp_top - 10),
                        text=item["expense_label"], fill=tokens.expense, font=(FONT, 8, "bold"),
                    )
                self.canvas.create_text(
                    group_center, bottom + 14, text=item["month"],
                    fill=tokens.text, font=(FONT, 9, "bold"),
                )
                self.canvas.create_text(
                    group_center, bottom + 30, text=item["net_label"],
                    fill=tokens.muted, font=(FONT, 8),
                )

    def _draw_categories(self, section: dict, x0: int, x1: int, y0: int, y1: int):
        tokens = self.theme_tokens or get_current_theme()
        currency = section["currency"]
        header = f"{self.title} ({currency})"
        color = tokens.expense if self.kind == "expense" else tokens.income
        legend_label = f'{self.translate("Expenses" if self.kind == "expense" else "Income")} ({currency})'
        if self.canvas is not None:
            self.canvas.create_text(x0, y0, anchor="w", text=header, fill=tokens.text, font=(FONT, 11, "bold"))
        self._draw_legend(x1, y0, [(legend_label, color)])

        bars = section["bars"][:8]
        max_minor = max(1, section["max_minor"])
        usable_w = max(420, x1 - x0)
        label_w = min(260, max(175, int(usable_w * 0.30)))
        value_w = min(230, max(165, int(usable_w * 0.28)))
        bar_x0 = x0 + label_w + 12
        bar_max_w = max(90, usable_w - label_w - value_w - 28)
        top = y0 + 32
        row_h = max(34, (y1 - top) // max(1, len(bars)))
        for i, item in enumerate(bars):
            y = top + i * row_h
            fill_w = max(4, int(item["amount"] * bar_max_w // max_minor))
            display_category = safe_category_label(self.translate(item["category"]), 34)
            value_text = f'{item["amount_label"]} ({item["percentage_label"]})'
            self.drawn_items.append({
                "type": "category_bar",
                "currency": currency,
                "kind": self.kind,
                "category": item["category"],
                "display_category": display_category,
                "amount": item["amount"],
                "amount_label": item["amount_label"],
                "percentage": item["percentage_label"],
            })
            if self.canvas is not None:
                self.canvas.create_text(
                    x0, y + 10, anchor="w",
                    text=display_category, fill=tokens.text,
                    font=(FONT, 9, "bold"), width=label_w - 8,
                )
                self.canvas.create_rectangle(
                    bar_x0, y + 2, bar_x0 + bar_max_w, y + 20,
                    fill=tokens.surface, outline=tokens.border,
                )
                self.canvas.create_rectangle(
                    bar_x0, y + 2, bar_x0 + fill_w, y + 20,
                    fill=color, outline="",
                )
                self.canvas.create_text(
                    bar_x0 + bar_max_w + 12, y + 10, anchor="w",
                    text=value_text, fill=tokens.text, font=(FONT, 9, "bold"),
                )



class GoalAdjustDialog:
    """Modal dialog for customizing long-term apartment purchase parameters."""

    def __init__(self, parent, app, on_save, current=None):
        self.app = app
        self.on_save = on_save
        self.dialog = tk.Toplevel(parent)
        self.dialog.transient(parent)
        self.dialog.resizable(False, False)
        self.dialog.title(app.t("Зорилго тохируулах"))

        frame = ttk.Frame(self.dialog, padding=18)
        frame.pack(fill="both", expand=True)

        current = current or {}

        # 1. Target Apartment Price
        ttk.Label(frame, text=app.t("Зорилтот байрны үнэ") + " (MNT):").grid(row=0, column=0, sticky="w", pady=6)
        init_price = str(current.get("apartment_price_minor", 200_000_000_00) // 100)
        self.price_var = tk.StringVar(value=init_price)
        ttk.Entry(frame, textvariable=self.price_var, width=22).grid(row=0, column=1, sticky="w", pady=6, padx=8)

        # 2. Down Payment Percentage
        ttk.Label(frame, text=app.t("Урьдчилгаа төлбөрийн хувь (%)") + ":").grid(row=1, column=0, sticky="w", pady=6)
        init_pct = str(current.get("down_payment_pct", 30))
        self.pct_var = tk.StringVar(value=init_pct)
        ttk.Entry(frame, textvariable=self.pct_var, width=10).grid(row=1, column=1, sticky="w", pady=6, padx=8)

        # 3. Initial Accumulated Savings
        ttk.Label(frame, text=app.t("Одоогийн хуримтлал") + " (MNT):").grid(row=2, column=0, sticky="w", pady=6)
        init_savings = str(current.get("total_accumulated_savings_minor", 0) // 100)
        self.savings_var = tk.StringVar(value=init_savings)
        ttk.Entry(frame, textvariable=self.savings_var, width=22).grid(row=2, column=1, sticky="w", pady=6, padx=8)

        # 4. Target Monthly Savings (Optional Override)
        ttk.Label(frame, text=app.t("Зорилтот сарын хуримтлал") + " (MNT):").grid(row=3, column=0, sticky="w", pady=6)
        t_savings = current.get("effective_monthly_savings_minor")
        init_target = str(t_savings // 100) if t_savings else ""
        self.target_var = tk.StringVar(value=init_target)
        ttk.Entry(frame, textvariable=self.target_var, width=22).grid(row=3, column=1, sticky="w", pady=6, padx=8)

        ttk.Label(frame, text="(Хоосон үлдээвэл бодит гүйлгээнээс автоматаар тооцно)",
                  style="CardMuted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))

        save_btn = ttk.Button(btn_frame, text=app.t("Хадгалах"), style="Primary.TButton", command=self._save)
        save_btn.pack(side="right", padx=(6, 0))

        cancel_btn = ttk.Button(btn_frame, text=app.t("Cancel"), command=self.dialog.destroy)
        cancel_btn.pack(side="right")

        from app.ui.i18n import localize_widget_tree
        localize_widget_tree(self.dialog)
        self.dialog.grab_set()

    def _save(self):
        try:
            price_val = int(self.price_var.get().strip().replace(",", ""))
            if price_val <= 0:
                raise ValueError
            price_minor = price_val * 100
        except Exception:
            messagebox.showwarning(self.app.t("Зорилго тохируулах"), "Байрны үнийг зөв тоогоор оруулна уу.", parent=self.dialog)
            return

        try:
            pct_val = int(self.pct_var.get().strip())
            if not (1 <= pct_val <= 100):
                raise ValueError
        except Exception:
            messagebox.showwarning(self.app.t("Зорилго тохируулах"), "Урьдчилгааны хувь 1-100 хооронд байна.", parent=self.dialog)
            return

        try:
            sav_str = self.savings_var.get().strip().replace(",", "")
            sav_minor = int(sav_str) * 100 if sav_str else 0
            if sav_minor < 0:
                raise ValueError
        except Exception:
            messagebox.showwarning(self.app.t("Зорилго тохируулах"), "Хуримтлуулсан дүнг зөв тоогоор оруулна уу.", parent=self.dialog)
            return

        target_str = self.target_var.get().strip().replace(",", "")
        target_minor = int(target_str) * 100 if target_str else None

        self.dialog.destroy()
        self.on_save({
            "apartment_price_minor": price_minor,
            "down_payment_pct": pct_val,
            "initial_savings_minor": sav_minor,
            "target_monthly_savings_minor": target_minor,
        })


class DashboardView:
    def __init__(self, app, table_factory):
        self.app = app
        self.report = None
        self._known_currencies = set()
        self.request = dict(preset="All time", start="", end="", currency=None)
        self.preset = tk.StringVar(app.window, app.t("All time"))
        self.start, self.end = tk.StringVar(app.window), tk.StringVar(app.window)
        self.currency = tk.StringVar(app.window, app.t("All currencies"))
        self.message = tk.StringVar(app.window, app.t("Loading Dashboard…"))
        self.tab = ttk.Frame(app.tabs, padding=10)
        app.tabs.add(self.tab, text="Dashboard")
        self.tab.columnconfigure(0, weight=1)
        self.tab.rowconfigure(0, weight=1)

        is_real_tk = isinstance(app.window, tk.Misc) and isinstance(getattr(app.window, "_w", None), str)
        if is_real_tk:
            self.scroll_canvas = tk.Canvas(self.tab, background=SURFACE, highlightthickness=0)
            self.scrollbar = ttk.Scrollbar(self.tab, orient="vertical", command=self.scroll_canvas.yview)
            self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
            self.scroll_canvas.grid(row=0, column=0, sticky="nsew")
            self.scrollbar.grid(row=0, column=1, sticky="ns")
            self.body = ttk.Frame(self.scroll_canvas, padding=(4, 4, 12, 18))
            self._body_window = self.scroll_canvas.create_window((0, 0), window=self.body, anchor="nw")
            self.body.bind(
                "<Configure>",
                lambda _event: self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all")),
                add="+",
            )
            self.scroll_canvas.bind(
                "<Configure>",
                lambda event: self.scroll_canvas.itemconfigure(self._body_window, width=max(640, event.width)),
                add="+",
            )
            self.scroll_canvas.bind("<Enter>", lambda _event: self._bind_mousewheel(True), add="+")
            self.scroll_canvas.bind("<Leave>", lambda _event: self._bind_mousewheel(False), add="+")
        else:
            self.scroll_canvas = None
            self.scrollbar = None
            self.body = self.tab

        self.body.columnconfigure(0, weight=1)
        controls = ttk.Frame(self.body)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        preset = ttk.Combobox(controls, textvariable=self.preset, values=PRESETS, state="readonly", width=18)
        preset.pack(side="left", padx=4)
        ttk.Label(controls, text="Custom from / to (YYYY-MM-DD)").pack(side="left")
        first = ttk.Entry(controls, textvariable=self.start, width=13)
        first.pack(side="left", padx=4)
        last = ttk.Entry(controls, textvariable=self.end, width=13)
        last.pack(side="left", padx=4)
        ttk.Label(controls, text="Currency").pack(side="left", padx=(6, 2))
        self.currency_box = ttk.Combobox(
            controls, textvariable=self.currency,
            values=(app.t("All currencies"),), state="readonly", width=15,
        )
        self.currency_box.pack(side="left", padx=4)
        refresh = ttk.Button(controls, text="Apply / refresh Dashboard", command=self.apply, style="Primary.TButton")
        refresh.pack(side="left", padx=4)
        self.controls = [preset, first, last, self.currency_box, refresh]

        banner = ttk.Label(self.body, textvariable=self.message, wraplength=1100, style="Muted.TLabel")
        banner.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.body.bind("<Configure>", lambda event: banner.configure(wraplength=max(360, event.width - 40)), add="+")

        self.cards = ttk.Frame(self.body)
        self.cards.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.card_values = []
        for column in range(4):
            self.cards.columnconfigure(column, weight=3 if column < 2 else 2, uniform="card")
        tones = ("Revenue", "Cost", "Net", "Review")
        card_icons = {
            "Total Revenue": "📈",
            "Total Cost": "📉",
            "Net": "⚖",
            "Unclassified": "❓",
        }
        for column, (label, tone) in enumerate(zip(("Total Revenue", "Total Cost", "Net", "Unclassified"), tones)):
            primary = column < 2
            card = ttk.Frame(self.cards, style=f"{tone}Card.TFrame")
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 3 else 6))
            ttk.Frame(card, height=6 if primary else 3, style=f"{tone}Bar.TFrame").pack(fill="x")
            body = ttk.Frame(card, style=f"{tone}Card.TFrame", padding=(16, 14) if primary else (14, 10))
            body.pack(fill="both", expand=True)
            icon = card_icons.get(label, "")
            card_title = f"{icon}  {self.app.t(label)}" if icon else self.app.t(label)
            ttk.Label(body, text=card_title, style=f"{tone}Title.TLabel").pack(anchor="w")
            value = tk.StringVar(app.window, "—")
            ttk.Label(body, textvariable=value, style=f"{tone}Value.TLabel").pack(anchor="w", pady=(4 if primary else 3, 0))
            self.card_values.append(value)

        self.totals = table_factory(self.body, [
            ("currency", "Currency", 80), ("income", "Income", 170), ("expense", "Expenses", 170),
            ("net", "Net (income - expenses)", 190), ("review", "Unclassified", 145),
            ("omitted", "Transfers / excluded", 140)], title="Classified totals; currencies are never combined", height=3)
        self.totals.grid(row=3, column=0, sticky="ew", pady=(0, 12))

        self.sections = {}
        self.charts = {}
        self.breakdowns = {}
        self.drill_buttons = {}
        section_specs = (
            ("month", "Monthly income vs expense", "Monthly cash flow"),
            ("expense", "Expenses by category", "Expenses by category"),
            ("income", "Income by category", "Income by category"),
        )
        for offset, (kind, section_title, table_title) in enumerate(section_specs, start=4):
            section = ttk.Frame(self.body, style="Card.TFrame", padding=(14, 12))
            section.grid(row=offset, column=0, sticky="ew", pady=(0, 14))
            section.columnconfigure(0, weight=1)
            ttk.Label(section, text=section_title, style="Section.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, 8),
            )
            chart = ChartCanvas(section, kind, self.app.t, min_height=MIN_CHART_HEIGHT)
            chart.grid(row=1, column=0, sticky="ew", pady=(0, 10))
            columns = ([("month", "Month", 110), ("currency", "Currency", 80), ("income", "Income", 160),
                        ("expense", "Expenses", 160), ("net", "Net cash flow", 160), ("count", "Transactions", 100),
                        ("review", "Unclassified", 145)] if kind == "month" else
                       [("category", "Category", 360), ("currency", "Currency", 80), ("amount", "Amount", 190),
                        ("count", "Transactions", 100), ("percentage", "% of this currency/kind", 175)])
            table = table_factory(section, columns, title=table_title, height=6)
            table.grid(row=2, column=0, sticky="ew")
            table.tree.bind("<Double-1>", lambda _, k=kind: self.drill(k))
            table.tree.bind("<<TreeviewSelect>>", lambda _: self.sync())
            button = ttk.Button(section, text="View selected in Transactions", command=lambda k=kind: self.drill(k))
            button.grid(row=3, column=0, sticky="w", pady=(6, 2))
            self.controls.append(button)
            self.sections[kind] = section
            self.charts[kind] = chart
            self.breakdowns[kind] = table
            self.drill_buttons[kind] = button

        # -------------------------------------------------------------
        # Row 7: LONG-TERM GOAL: WHEN WILL I GET AN APARTMENT? Widget
        # -------------------------------------------------------------
        self.goal_card = ttk.Frame(self.body, style="Card.TFrame", padding=(16, 14))
        self.goal_card.grid(row=7, column=0, sticky="ew", pady=(0, 14))
        self.goal_card.columnconfigure(0, weight=1)

        goal_header = ttk.Frame(self.goal_card, style="Card.TFrame")
        goal_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        goal_titles = ttk.Frame(goal_header, style="Card.TFrame")
        goal_titles.pack(side="left")
        ttk.Label(goal_titles, text="🏠  LONG-TERM GOAL: WHEN WILL I GET AN APARTMENT?", font=(FONT, 11, "bold"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(goal_titles, text="Урт хугацааны зорилго: Орон сууц худалдан авах хугацаа ба өр орлогын харьцааны тооцоолол", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 0))

        adjust_goal_btn = ttk.Button(goal_header, text=f"⚙  {self.app.t('Зорилго тохируулах…')}",
                                     command=self.adjust_goal)
        adjust_goal_btn.pack(side="right")
        self.controls.append(adjust_goal_btn)

        self.goal_hero_frame = ttk.Frame(self.goal_card, style="Card.TFrame")
        self.goal_hero_frame.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        self.goal_hero_frame.columnconfigure(0, weight=1)

        self.goal_timeline_var = tk.StringVar(value="⏳ Тооцоолж байна…")
        self.goal_timeline_sub_var = tk.StringVar(value="Орон сууцны урьдчилгаа төлбөр цугларах тооцоолол")
        ttk.Label(self.goal_hero_frame, textvariable=self.goal_timeline_var, font=(FONT, 13, "bold"), foreground="#3b82f6").grid(row=0, column=0, sticky="w")
        ttk.Label(self.goal_hero_frame, textvariable=self.goal_timeline_sub_var, font=(FONT, 9), style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 6))

        self.goal_progress_canvas = None
        if is_real_tk:
            tokens = get_current_theme()
            self.goal_progress_canvas = tk.Canvas(self.goal_hero_frame, height=24, background=tokens.surface,
                                                  highlightthickness=1, highlightbackground=tokens.border)
            self.goal_progress_canvas.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        self.goal_kpi_frame = ttk.Frame(self.goal_card, style="Card.TFrame")
        self.goal_kpi_frame.grid(row=2, column=0, sticky="ew", pady=(6, 8))
        for col in range(4):
            self.goal_kpi_frame.columnconfigure(col, weight=1, uniform="goal_kpi")

        self.goal_val_target = tk.StringVar(value="—")
        self.goal_val_savings = tk.StringVar(value="—")
        self.goal_val_savings_rate = tk.StringVar(value="—")
        self.goal_val_dti = tk.StringVar(value="—")

        self._create_metric_card(self.goal_kpi_frame, "Зорилтот байр & Урьдчилгаа", self.goal_val_target, 0)
        self._create_metric_card(self.goal_kpi_frame, "Сарын хуримтлал", self.goal_val_savings, 1)
        self._create_metric_card(self.goal_kpi_frame, "Хуримтлалын хувь (Savings Rate)", self.goal_val_savings_rate, 2)
        self._create_metric_card(self.goal_kpi_frame, "Өр орлогын харьцаа (DTI)", self.goal_val_dti, 3)

        self.goal_advice_var = tk.StringVar(value="Банкны шалгуураар өр орлогын харьцааг тооцоолж байна…")
        self.goal_advice_label = ttk.Label(self.goal_card, textvariable=self.goal_advice_var, wraplength=980,
                                           font=(FONT, 9, "italic"), style="CardMuted.TLabel")
        self.goal_advice_label.grid(row=3, column=0, sticky="w", pady=(4, 0))

        # -------------------------------------------------------------
        # Row 8: Executive Budget vs Actual (ТӨСӨВ vs БОДИТ) Widget
        # -------------------------------------------------------------
        self.var_card = ttk.Frame(self.body, style="Card.TFrame", padding=(16, 14))
        self.var_card.grid(row=8, column=0, sticky="ew", pady=(0, 14))
        self.var_card.columnconfigure(0, weight=1)

        var_header = ttk.Frame(self.var_card, style="Card.TFrame")
        var_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        var_titles = ttk.Frame(var_header, style="Card.TFrame")
        var_titles.pack(side="left")
        ttk.Label(var_titles, text=f"💰  {self.app.t('Төсөв ба Бодит гүйцэтгэл')} (Budget vs Actual)", font=(FONT, 11, "bold"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(var_titles, text="Сонгосон хугацааны нийт төсөв болон бодит зардлын зөрүүгийн шинжилгээ", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 0))

        view_budget_btn = ttk.Button(var_header, text=f"📊  {self.app.t('Дэлгэрэнгүй төсвийн шинжилгээ үзэх')} ➔",
                                     command=getattr(self.app, "_select_budget", lambda: None), style="Primary.TButton")
        view_budget_btn.pack(side="right")
        self.controls.append(view_budget_btn)

        self.var_kpi_frame = ttk.Frame(self.var_card, style="Card.TFrame")
        self.var_kpi_frame.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        for col in range(4):
            self.var_kpi_frame.columnconfigure(col, weight=1, uniform="var_kpi")

        self.dash_var_budget = tk.StringVar(value="—")
        self.dash_var_actual = tk.StringVar(value="—")
        self.dash_var_variance = tk.StringVar(value="—")
        self.dash_var_pct = tk.StringVar(value="—")

        self._create_metric_card(self.var_kpi_frame, "ТӨСӨВ (Budget)", self.dash_var_budget, 0)
        self._create_metric_card(self.var_kpi_frame, "БОДИТ (Actual)", self.dash_var_actual, 1)
        self._create_metric_card(self.var_kpi_frame, "ЗӨРҮҮ (Variance)", self.dash_var_variance, 2)
        self._create_metric_card(self.var_kpi_frame, "% БИЕЛЭЛТ (Execution)", self.dash_var_pct, 3)

    def _bind_mousewheel(self, active: bool):
        if self.scroll_canvas is None:
            return
        if active:
            self.scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        else:
            self.scroll_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        if self.scroll_canvas is not None and getattr(event, "delta", 0):
            self.scroll_canvas.yview_scroll(int(-event.delta / 120), "units")

    def set_currencies(self, currencies):
        self._known_currencies.update(c for c in currencies if c)
        self.currency_box.configure(values=[self.app.t("All currencies"), *sorted(self._known_currencies)])

    def sync(self):
        idle = self.app.ready and not self.app.busy and not self.app.closing
        for widget in self.controls:
            self.app._enabled(widget, idle)
        for kind, button in self.drill_buttons.items():
            self.app._enabled(button, idle and self.report is not None and
                              len(selected_items(self.breakdowns[kind])) == 1)

    def apply(self):
        selected_currency = source_text(self.currency.get(), ("All currencies",))
        self.request = dict(
            preset=source_text(self.preset.get()),
            start=self.start.get(),
            end=self.end.get(),
            currency=None if selected_currency in ("", "All currencies") else selected_currency,
        )
        self.refresh()

    def refresh(self):
        if self.app._request("dashboard", **self.request):
            self.app.dashboard_dirty = False
            self.message.set(self.app.t("Refreshing Dashboard…"))

    def set_theme(self, tokens):
        if self.scroll_canvas is not None:
            self.scroll_canvas.configure(background=tokens.bg)
        for chart in self.charts.values():
            chart.set_theme(tokens)
        if self.report is not None:
            self.display(self.report)

    def clear(self, message):
        self.report = None
        for value in self.card_values:
            value.set("—")
        self.totals.set_items(())
        for table in self.breakdowns.values():
            table.set_items(())
        for chart in self.charts.values():
            chart.render((), message)
        self.message.set(self.app.t(message))

    def display(self, report):
        self.report = report
        self.set_currencies(r["currency"] for r in report.totals)
        selected_currency = self.request.get("currency")
        self.totals.set_items(report.totals, lambda r: (
            r["currency"], format_money(r["income"], r["currency"]), format_money(r["expenses"], r["currency"]),
            format_money(r["net"], r["currency"]), _unclassified_cell(r), r["omitted"]))
        for kind in ("income", "expense"):
            self.breakdowns[kind].set_items(tuple(r for r in report.categories if r["kind"] == kind), lambda r: (
                (self.app.category_display_name(r["category"]) if hasattr(self.app, "category_display_name") else self.app.t(r["category"])), r["currency"], format_money(r["amount"], r["currency"]), r["count"], f'{r["percentage"]:.2f}%'))
        self.breakdowns["month"].set_items(report.months, lambda r: (
            r["month"], r["currency"], format_money(r["income"], r["currency"]), format_money(r["expenses"], r["currency"]),
            format_money(r["net"], r["currency"]), r["count"], _unclassified_cell(r)))
        empty_chart = "No chart data for the selected period and currency."
        self.charts["month"].render(monthly_chart_series(report, selected_currency), empty_chart)
        self.charts["expense"].render(category_chart_series(report, "expense", selected_currency), empty_chart)
        self.charts["income"].render(category_chart_series(report, "income", selected_currency), empty_chart)
        for value, (_, display) in zip(self.card_values, dashboard_summary(report)):
            value.set(display)
        period = self.app.t("All time") if report.start is None else f"{report.start} through {report.end} (inclusive)"
        from app.ui.i18n import translate_format
        if report.start is not None:
            period = translate_format("{period} through {end} (inclusive)", period=report.start, end=report.end)
        if not report.transaction_count:
            self.message.set(translate_format(
                "{period}: no transactions. Import a statement or change the date range.", period=period))
        else:
            self.message.set(translate_format(
                "{period}: {count} transactions; {unclassified} unclassified. Unclassified, transfer and excluded amounts are omitted from income/expense/net totals. Net is not an account balance.",
                period=period, count=report.transaction_count, unclassified=report.unclassified_count))
        curr = self.request.get("currency")
        self.app._request("goal_analysis", currency=curr)
        month_to_check = report.end[:7] if getattr(report, "end", None) else datetime.now().strftime("%Y-%m")
        self.app._request("budget_variance", month=month_to_check, currency=curr)

    def _create_metric_card(self, parent, title, text_var, column):
        frame = ttk.Frame(parent, padding=(10, 8), style="Card.TFrame")
        frame.grid(row=0, column=column, padx=4, sticky="nsew")
        ttk.Label(frame, text=title, font=(FONT, 8, "bold"), style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=text_var, font=(FONT, 11, "bold"), style="CardValue.TLabel").pack(anchor="w", pady=(3, 0))
        return frame

    def handle_goal(self, payload):
        self.goal_data = payload
        curr = payload.get("currency", "MNT")
        tl_text = payload.get("timeline_text", "—")
        est_date = payload.get("estimated_target_date", "")
        self.goal_timeline_var.set(f"⏳ Тооцоолсон хугацаа: {tl_text}  ({est_date})")
        self.goal_timeline_sub_var.set(payload.get("timeline_subtitle", ""))

        apt_price = format_money(payload.get("apartment_price_minor", 0), curr)
        dp_target = format_money(payload.get("down_payment_target_minor", 0), curr)
        dp_pct = payload.get("down_payment_pct", 30)
        self.goal_val_target.set(f"{apt_price} ({dp_pct}%: {dp_target})")

        eff_sav = format_money(payload.get("effective_monthly_savings_minor", 0), curr)
        self.goal_val_savings.set(f"{eff_sav} / сар")

        sav_rate = payload.get("savings_rate_pct", 0.0)
        sav_label = payload.get("savings_grade_label", "")
        self.goal_val_savings_rate.set(f"{sav_rate:.1f}%  (● {sav_label})")

        dti_pct = payload.get("dti_pct", 0.0)
        dti_label = payload.get("dti_label", "")
        self.goal_val_dti.set(f"{dti_pct:.1f}%  (● {dti_label})")

        self.goal_advice_var.set(payload.get("dti_advice", ""))
        if self.goal_progress_canvas is not None:
            self._redraw_goal_progress(payload)

    def _redraw_goal_progress(self, payload):
        c = self.goal_progress_canvas
        if c is None:
            return
        tokens = get_current_theme()
        c.delete("all")
        w = max(400, int(c.winfo_width()))
        h = int(c.cget("height"))
        pct = payload.get("progress_pct", 0.0)
        curr = payload.get("currency", "MNT")
        accum = format_money(payload.get("total_accumulated_savings_minor", 0), curr)
        target = format_money(payload.get("down_payment_target_minor", 0), curr)

        c.create_rectangle(0, 0, w, h, fill=tokens.surface, outline=tokens.border)
        fill_w = max(2, int(w * min(100.0, pct) / 100))
        fill_color = tokens.green if pct >= 100 else tokens.primary
        c.create_rectangle(0, 0, fill_w, h, fill=fill_color, outline="")

        text = f"Урьдчилгаа хуримтлагдсан: {pct:.1f}% ({accum} / {target})"
        c.create_text(w // 2, h // 2, text=text, fill=WHITE if fill_w > w // 2 else tokens.text, font=(FONT, 9, "bold"))

    def handle_variance(self, payload):
        totals = payload.get("totals", {})
        curr = payload.get("currency")
        target = None
        if curr and curr in totals:
            target = totals[curr]
        elif len(totals) == 1:
            target = next(iter(totals.values()))

        if target:
            c = target["currency"]
            self.dash_var_budget.set(format_money(target["expense_budget"], c))
            self.dash_var_actual.set(format_money(target["expense_actual"], c))
            v = target["expense_variance"]
            sign = "+" if v > 0 else ""
            self.dash_var_variance.set(f"{sign}{format_money(v, c)}")
            self.dash_var_pct.set(f"{target['expense_pct']:.1f}%")
        elif len(totals) > 1:
            b_strs = [format_money(t["expense_budget"], c) for c, t in sorted(totals.items())]
            a_strs = [format_money(t["expense_actual"], c) for c, t in sorted(totals.items())]
            self.dash_var_budget.set(" | ".join(b_strs))
            self.dash_var_actual.set(" | ".join(a_strs))
            self.dash_var_variance.set(f"{len(totals)} валют")
            self.dash_var_pct.set("Бүгд")
        else:
            self.dash_var_budget.set("—")
            self.dash_var_actual.set("—")
            self.dash_var_variance.set("—")
            self.dash_var_pct.set("—")

    def adjust_goal(self):
        GoalAdjustDialog(
            self.app.window, self.app,
            on_save=lambda params: self.app._request("goal_save_params", **params),
            current=getattr(self, "goal_data", None),
        )

    def drill(self, kind):
        if self.app.busy or self.report is None:
            return
        rows = selected_items(self.breakdowns[kind])
        if len(rows) != 1:
            self.app._error("Select one Dashboard row to open its transactions.")
            return
        try:
            filters = (month_filters if kind == "month" else category_filters)(self.report, rows[0])
        except ReportingError as error:
            self.app._error(str(error))
            return
        self.app._dashboard_drill(filters)
