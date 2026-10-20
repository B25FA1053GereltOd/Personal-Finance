"""Lightweight tables; reporting and date/filter logic stay outside widgets."""

import tkinter as tk
from tkinter import ttk

from app.reporting import PRESETS, ReportingError, category_filters, month_filters, format_money
from app.ui.review import selected_items


class DashboardView:
    def __init__(self, app, table_factory):
        self.app = app
        self.report = None
        self.request = dict(preset="All time", start="", end="")
        self.preset = tk.StringVar(app.window, "All time")
        self.start, self.end = tk.StringVar(app.window), tk.StringVar(app.window)
        self.message = tk.StringVar(app.window, "Loading Dashboard…")
        self.tab = ttk.Frame(app.tabs, padding=10)
        app.tabs.add(self.tab, text="Dashboard")
        self.tab.columnconfigure(0, weight=1)
        self.tab.rowconfigure(3, weight=1)
        controls = ttk.Frame(self.tab)
        controls.grid(row=0, column=0, sticky="ew")
        preset = ttk.Combobox(controls, textvariable=self.preset, values=PRESETS, state="readonly", width=18)
        preset.pack(side="left", padx=4)
        ttk.Label(controls, text="Custom from / to (YYYY-MM-DD)").pack(side="left")
        first = ttk.Entry(controls, textvariable=self.start, width=13)
        first.pack(side="left", padx=4)
        last = ttk.Entry(controls, textvariable=self.end, width=13)
        last.pack(side="left", padx=4)
        refresh = ttk.Button(controls, text="Apply / refresh Dashboard", command=self.apply)
        refresh.pack(side="left", padx=4)
        self.controls = [preset, first, last, refresh]
        ttk.Label(self.tab, textvariable=self.message, wraplength=1100).grid(row=1, column=0, sticky="w", pady=8)
        self.totals = table_factory(self.tab, [
            ("currency", "Currency", 80), ("income", "Income", 170), ("expense", "Expenses", 170),
            ("net", "Net (income - expenses)", 190), ("review", "Unclassified", 95),
            ("omitted", "Transfers / excluded", 140)], title="Classified totals; currencies are never combined", height=4)
        self.totals.grid(row=2, column=0, sticky="ew")
        panels = ttk.Notebook(self.tab)
        panels.grid(row=3, column=0, sticky="nsew", pady=8)
        self.breakdowns = {}
        for kind, label in (("expense", "Expenses by category"), ("income", "Income by category"), ("month", "Monthly cash flow")):
            frame = ttk.Frame(panels)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            panels.add(frame, text=label)
            columns = ([("month", "Month", 110), ("currency", "Currency", 80), ("income", "Income", 160),
                        ("expense", "Expenses", 160), ("net", "Net cash flow", 160), ("count", "Transactions", 100),
                        ("review", "Unclassified", 100)] if kind == "month" else
                       [("category", "Category", 360), ("currency", "Currency", 80), ("amount", "Amount", 190),
                        ("count", "Transactions", 100), ("percentage", "% of this currency/kind", 175)])
            table = table_factory(frame, columns, title=label, height=12)
            table.grid(row=0, column=0, sticky="nsew")
            table.tree.bind("<Double-1>", lambda _, k=kind: self.drill(k))
            button = ttk.Button(frame, text="View selected in Transactions", command=lambda k=kind: self.drill(k))
            button.grid(row=1, column=0, sticky="w", pady=6)
            self.controls.append(button)
            self.breakdowns[kind] = table

    def sync(self):
        idle = self.app.ready and not self.app.busy and not self.app.closing
        for widget in self.controls:
            self.app._enabled(widget, idle)

    def apply(self):
        self.request = dict(preset=self.preset.get(), start=self.start.get(), end=self.end.get())
        self.refresh()

    def refresh(self):
        if self.app._request("dashboard", **self.request):
            self.app.dashboard_dirty = False
            self.message.set("Refreshing Dashboard…")

    def clear(self, message):
        self.report = None
        self.totals.set_items(())
        for table in self.breakdowns.values():
            table.set_items(())
        self.message.set(message)

    def display(self, report):
        self.report = report
        self.totals.set_items(report.totals, lambda r: (
            r["currency"], format_money(r["income"], r["currency"]), format_money(r["expenses"], r["currency"]),
            format_money(r["net"], r["currency"]), r["unclassified"], r["omitted"]))
        for kind in ("income", "expense"):
            self.breakdowns[kind].set_items(tuple(r for r in report.categories if r["kind"] == kind), lambda r: (
                r["category"], r["currency"], format_money(r["amount"], r["currency"]), r["count"], f'{r["percentage"]:.2f}%'))
        self.breakdowns["month"].set_items(report.months, lambda r: (
            r["month"], r["currency"], format_money(r["income"], r["currency"]), format_money(r["expenses"], r["currency"]),
            format_money(r["net"], r["currency"]), r["count"], r["unclassified"]))
        period = "All time" if report.start is None else f"{report.start} through {report.end} (inclusive)"
        self.message.set(f"{period}: no transactions. Import a statement or change the date range." if not report.transaction_count else
                         f"{period}: {report.transaction_count} transactions; {report.unclassified_count} unclassified. "
                         "Unclassified, transfer and excluded amounts are omitted from income/expense/net totals. Net is not an account balance.")

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
