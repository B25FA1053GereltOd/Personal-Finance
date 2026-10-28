"""Lightweight tables and Canvas charts; reporting and filter logic stay outside widgets."""

import tkinter as tk
from tkinter import ttk

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

        # Budget summary section
        budget_card = ttk.Frame(self.body, style="Card.TFrame", padding=(14, 12))
        budget_card.grid(row=7, column=0, sticky="ew", pady=(0, 14))
        budget_card.columnconfigure(0, weight=1)
        budget_header = ttk.Frame(budget_card, style="Card.TFrame")
        budget_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(budget_header, text=f"💰  {self.app.t('Monthly Budget')}", style="Section.TLabel").pack(side="left")
        view_budget_btn = ttk.Button(budget_header, text=f"💰  {self.app.t('View budgets')}",
                                     command=getattr(self.app, "_select_budget", lambda: None), style="Primary.TButton")
        view_budget_btn.pack(side="right")
        self.controls.append(view_budget_btn)
        ttk.Label(budget_card, text=self.app.t("Monthly budget management"), style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

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
