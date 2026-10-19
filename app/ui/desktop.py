"""Tk views. All widget access is on the main thread; services run in worker.py."""

import tkinter as tk
from pathlib import Path
from queue import Empty
from tkinter import filedialog, messagebox, ttk

from app.ui.presentation import browser_filters, format_mnt, issue_location, review_status
from app.ui.worker import FinanceWorker


class PagedTable(ttk.Frame):
    """Render only a bounded slice of an existing preview, never all its rows."""

    def __init__(self, parent, columns, *, title="", size=50, height=6, selectmode="browse"):
        super().__init__(parent)
        self.size, self.page, self.items, self.values = size, 0, (), lambda item: item
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text=title).grid(row=0, column=0, sticky="w", pady=(4, 3))
        area = ttk.Frame(self)
        area.grid(row=1, column=0, sticky="nsew")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(area, columns=[c[0] for c in columns], show="headings",
                                 height=height, selectmode=selectmode)
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=65, anchor="e" if key in ("amount", "balance") else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(area, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(area, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.footer = ttk.Frame(self)
        self.footer.grid(row=2, column=0, sticky="ew", pady=3)
        self.previous = ttk.Button(self.footer, text="Previous", command=lambda: self.move(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(self.footer, text="Next", command=lambda: self.move(1))
        self.next.pack(side="left", padx=4)
        self.caption = ttk.Label(self.footer)
        self.caption.pack(side="left", padx=8)
        self.render()

    def set_items(self, items, values=None):
        self.items, self.page = items, 0
        if values is not None:
            self.values = values
        self.render()

    def move(self, delta):
        self.page = max(0, min(self.page + delta, max(0, (len(self.items) - 1) // self.size)))
        self.render()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        start = self.page * self.size
        for index in range(start, min(start + self.size, len(self.items))):
            self.tree.insert("", "end", iid=str(index), values=self.values(self.items[index]))
        self.previous.state(["!disabled"] if self.page else ["disabled"])
        self.next.state(["!disabled"] if start + self.size < len(self.items) else ["disabled"])
        pages = max(1, (len(self.items) + self.size - 1) // self.size)
        self.caption.configure(text=f"Page {self.page + 1} of {pages} · {len(self.items)} rows")


class DesktopApp:
    def __init__(self, window: tk.Tk, data_dir: Path, *, worker_factory=FinanceWorker):
        self.window = window
        self.busy, self.ready, self.closing = True, False, False
        self.preview, self.decisions = None, {}
        self.accounts, self.categories = [], []
        self.browser_page, self.browser_total = 0, 0
        self.active_filters = {}
        self.account_dialog = None
        self.file_path = tk.StringVar(window)
        self.account_text = tk.StringVar(window)
        self.account_confirmed = tk.BooleanVar(window, False)
        self.status = tk.StringVar(window, "Opening local database…")
        self.preview_counts = tk.StringVar(window, "Select an account and an XLSX statement to preview.")
        self.summary = tk.StringVar(window)
        self.review_hint = tk.StringVar(window)
        self.date_from, self.date_to, self.search = (tk.StringVar(window) for _ in range(3))
        self.category_text = tk.StringVar(window, "All categories")
        self.direction_text = tk.StringVar(window, "All directions")
        self.review_only = tk.BooleanVar(window, False)
        self.page_size = tk.StringVar(window, "50")
        self.browser_caption = tk.StringVar(window, "No transactions loaded")
        self._build(data_dir)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.report_callback_exception = self._callback_error
        self.worker = worker_factory(data_dir / "finance.sqlite3")
        self._sync_controls()
        self._poll_id = window.after(40, self._poll)

    def _build(self, data_dir):
        root = self.window
        root.title("Personal Finance Tool")
        root.geometry("1200x820")
        root.minsize(940, 680)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        ttk.Style(root).configure("Treeview", rowheight=26)
        top = ttk.Frame(root, padding=(16, 10))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Personal Finance", font=("Segoe UI", 20, "bold")).pack(side="left")
        ttk.Label(top, text="Local · Offline · MNT").pack(side="right")
        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=12)
        self.import_tab = ttk.Frame(self.tabs, padding=10)
        self.transactions_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.import_tab, text="Import")
        self.tabs.add(self.transactions_tab, text="Transactions")
        self._build_import()
        self._build_browser()
        footer = ttk.Frame(root, padding=(16, 8))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, wraplength=850).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=140)
        self.progress.grid(row=0, column=1, sticky="e")
        ttk.Label(footer, text=f"Data folder: {data_dir}", wraplength=1000).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))

    def _build_import(self):
        tab = self.import_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(5, weight=1)
        account = ttk.Frame(tab)
        account.grid(row=0, column=0, sticky="ew", pady=4)
        account.columnconfigure(1, weight=1)
        ttk.Label(account, text="Account").grid(row=0, column=0, padx=(0, 8))
        self.account_box = ttk.Combobox(account, textvariable=self.account_text, state="readonly")
        self.account_box.grid(row=0, column=1, sticky="ew")
        self.account_box.bind("<<ComboboxSelected>>", lambda _: self._account_changed())
        self.add_account_button = ttk.Button(account, text="Add account…", command=self._add_account)
        self.add_account_button.grid(row=0, column=2, padx=(8, 0))
        file_row = ttk.Frame(tab)
        file_row.grid(row=1, column=0, sticky="ew", pady=4)
        file_row.columnconfigure(1, weight=1)
        ttk.Label(file_row, text="Statement").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(file_row, textvariable=self.file_path, state="readonly").grid(row=0, column=1, sticky="ew")
        self.choose_button = ttk.Button(file_row, text="Choose .xlsx…", command=self._choose_file)
        self.choose_button.grid(row=0, column=2, padx=(8, 0))
        self.confirm_account = ttk.Checkbutton(tab, text="I confirm this is the statement’s account (Khan Bank, MNT).",
                                              variable=self.account_confirmed, command=self._sync_controls)
        self.confirm_account.grid(row=2, column=0, sticky="w", pady=4)
        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, sticky="ew", pady=4)
        self.preview_button = ttk.Button(actions, text="Preview import", command=self._preview)
        self.preview_button.pack(side="left")
        self.commit_button = ttk.Button(actions, text="Commit import", command=self._commit)
        self.commit_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="Cancel preview", command=self._cancel)
        self.cancel_button.pack(side="left")
        ttk.Label(tab, textvariable=self.preview_counts, wraplength=1080).grid(row=4, column=0, sticky="w", pady=5)
        self.preview_tabs = ttk.Notebook(tab)
        self.preview_tabs.grid(row=5, column=0, sticky="nsew")
        rows = ttk.Frame(self.preview_tabs, padding=4)
        rows.columnconfigure(0, weight=1)
        rows.rowconfigure(0, weight=3)
        rows.rowconfigure(2, weight=2)
        errors = ttk.Frame(self.preview_tabs, padding=4)
        errors.columnconfigure(0, weight=1)
        errors.rowconfigure(0, weight=1)
        self.preview_tabs.add(rows, text="Rows and duplicate decisions")
        self.preview_tabs.add(errors, text="Errors and warnings")
        self.preview_table = PagedTable(rows, [
            ("status", "Status", 90), ("decision", "Decision", 90), ("sheet", "Worksheet", 130),
            ("row", "Row", 65), ("date", "Date / time", 170), ("description", "Original description", 360),
            ("amount", "Amount", 145)], title="Incoming rows — select ambiguous rows to choose Keep or Skip", selectmode="extended")
        self.preview_table.grid(row=0, column=0, sticky="nsew")
        self.preview_table.tree.bind("<<TreeviewSelect>>", lambda _: self._show_candidates())
        choices = ttk.Frame(rows)
        choices.grid(row=1, column=0, sticky="ew", pady=4)
        self.decision_buttons = []
        for text, action in (("Keep selected", "keep"), ("Skip selected", "skip"), ("Clear decision", None)):
            button = ttk.Button(choices, text=text, command=lambda a=action: self._decide(a))
            button.pack(side="left", padx=(0, 6))
            self.decision_buttons.append(button)
        self.candidates = PagedTable(rows, [
            ("identity", "Original row", 120), ("sheet", "Worksheet", 130), ("row", "Row", 65),
            ("date", "Date / time", 170), ("description", "Original description", 330),
            ("amount", "Amount", 145), ("reference", "Reference", 130), ("balance", "Balance", 145)],
            title="Possible matches for the first selected row (original imported values)", height=3)
        self.candidates.grid(row=2, column=0, sticky="nsew")
        self.issues = PagedTable(errors, [
            ("severity", "Severity", 85), ("sheet", "Worksheet", 110), ("row", "Row", 65),
            ("column", "Column", 65), ("code", "Code", 190), ("message", "Message", 520)],
            title="All errors must be resolved before any transaction can be committed.")
        self.issues.grid(row=0, column=0, sticky="nsew")
        result = ttk.Frame(tab)
        result.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        result.columnconfigure(0, weight=1)
        ttk.Label(result, textvariable=self.summary, wraplength=760).grid(row=0, column=0, sticky="w")
        self.review_button = ttk.Button(result, text="Review unknown merchants", command=self._review_unknown)
        self.review_button.grid(row=0, column=1, padx=(8, 0))

    def _build_browser(self):
        tab = self.transactions_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        filters = ttk.Frame(tab)
        filters.grid(row=0, column=0, sticky="ew")
        self.filter_widgets = []
        for column, label, variable in ((0, "From (YYYY-MM-DD)", self.date_from), (1, "To (YYYY-MM-DD)", self.date_to)):
            ttk.Label(filters, text=label).grid(row=0, column=column, sticky="w", padx=4)
            entry = ttk.Entry(filters, textvariable=variable, width=18)
            entry.grid(row=1, column=column, sticky="ew", padx=4)
            self.filter_widgets.append(entry)
        ttk.Label(filters, text="Category").grid(row=0, column=2, sticky="w", padx=4)
        self.category_box = ttk.Combobox(filters, textvariable=self.category_text, state="readonly", width=38)
        self.category_box.grid(row=1, column=2, sticky="ew", padx=4)
        ttk.Label(filters, text="Direction").grid(row=0, column=3, sticky="w", padx=4)
        self.direction_box = ttk.Combobox(filters, textvariable=self.direction_text, state="readonly", width=18,
                                           values=("All directions", "Debit", "Credit", "Zero"))
        self.direction_box.grid(row=1, column=3, sticky="ew", padx=4)
        ttk.Label(filters, text="Description search").grid(row=2, column=0, sticky="w", padx=4, pady=(8, 0))
        search = ttk.Entry(filters, textvariable=self.search)
        search.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4)
        search.bind("<Return>", lambda _: self._apply_filters())
        review = ttk.Checkbutton(filters, text="Unclassified only", variable=self.review_only)
        review.grid(row=3, column=2, sticky="w", padx=4)
        buttons = ttk.Frame(filters)
        buttons.grid(row=3, column=3, sticky="ew")
        apply = ttk.Button(buttons, text="Apply / refresh", command=self._apply_filters)
        apply.pack(side="left", padx=4)
        reset = ttk.Button(buttons, text="Reset", command=self._reset_filters)
        reset.pack(side="left", padx=4)
        self.filter_widgets.extend((search, review, apply, reset))
        for column in range(4):
            filters.columnconfigure(column, weight=1)
        browser_messages = ttk.Frame(tab)
        browser_messages.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Label(browser_messages, textvariable=self.summary, wraplength=1080).pack(anchor="w")
        ttk.Label(browser_messages, textvariable=self.review_hint, wraplength=1080).pack(anchor="w")
        self.transactions = PagedTable(tab, [
            ("date", "Date / time", 170), ("description", "Merchant / description", 360),
            ("amount", "Amount", 160), ("category", "Category", 260), ("review", "Review status", 150)],
            title="Transactions", size=100, height=14)
        self.transactions.grid(row=2, column=0, sticky="nsew")
        self.transactions.footer.grid_remove()
        paging = ttk.Frame(tab)
        paging.grid(row=3, column=0, sticky="ew", pady=6)
        self.browser_previous = ttk.Button(paging, text="Previous page", command=lambda: self._browse(self.browser_page - 1))
        self.browser_previous.pack(side="left")
        self.browser_next = ttk.Button(paging, text="Next page", command=lambda: self._browse(self.browser_page + 1))
        self.browser_next.pack(side="left", padx=6)
        ttk.Label(paging, textvariable=self.browser_caption).pack(side="left", padx=8)
        self.size_box = ttk.Combobox(paging, textvariable=self.page_size, values=("10", "25", "50", "100"), state="readonly", width=5)
        self.size_box.pack(side="right")
        self.size_box.bind("<<ComboboxSelected>>", lambda _: self._browse(0))
        ttk.Label(paging, text="Rows per page: ").pack(side="right")

    @staticmethod
    def _enabled(widget, enabled):
        widget.state(["!disabled"] if enabled else ["disabled"])

    def _sync_controls(self):
        idle = self.ready and not self.busy and not self.closing
        selecting = idle and self.preview is None
        for widget in (self.account_box, self.add_account_button, self.choose_button, self.confirm_account):
            self._enabled(widget, selecting)
        self._enabled(self.preview_button, selecting and bool(self.accounts) and bool(self.file_path.get()) and self.account_confirmed.get())
        self._enabled(self.cancel_button, idle and self.preview is not None)
        required = {row.index for row in self.preview.rows if row.status == "ambiguous"} if self.preview else set()
        self._enabled(self.commit_button, idle and self.preview is not None and self.preview.is_valid and required == self.decisions.keys())
        selected = self.preview_table.tree.selection()
        eligible = self.preview is not None and any(self.preview.rows[int(i)].status == "ambiguous" for i in selected)
        for button in self.decision_buttons:
            self._enabled(button, idle and eligible)
        self._enabled(self.review_button, idle)
        for widget in (*self.filter_widgets, self.category_box, self.direction_box, self.size_box):
            self._enabled(widget, idle)
        self._enabled(self.browser_previous, idle and self.browser_page > 0)
        self._enabled(self.browser_next, idle and (self.browser_page + 1) * int(self.page_size.get()) < self.browser_total)
        if self.busy:
            self.progress.start(15)
        else:
            self.progress.stop()

    def _request(self, operation, **payload):
        if self.busy or not self.ready or self.closing:
            return False
        self.busy = True
        self.status.set({"preview": "Parsing and validating statement…", "commit": "Committing the complete import…",
                         "cancel": "Canceling preview…", "account": "Saving account…", "browse": "Loading transactions…"}[operation])
        self._sync_controls()
        try:
            self.worker.submit(operation, **payload)
        except RuntimeError:
            self.busy, self.ready = False, False
            self._error("The database worker is unavailable. Close and reopen the app.")
            self._sync_controls()
            return False
        return True

    def _account_changed(self):
        self.account_confirmed.set(False)
        self._sync_controls()

    def _choose_file(self):
        path = filedialog.askopenfilename(parent=self.window, title="Choose a Khan Bank MNT statement",
                                          filetypes=[("Excel statement", "*.xlsx")])
        if path:
            self.file_path.set(path)
            self.account_confirmed.set(False)
            self.summary.set("")
            self._sync_controls()

    def _set_accounts(self, accounts, selected=None):
        self.accounts = accounts
        self.account_box.configure(values=[f'{a["name"]} — {a["identifier"]} ({a["bank"]}, {a["currency"]})' for a in accounts])
        if accounts:
            index = next((i for i, a in enumerate(accounts) if a["id"] == selected), 0)
            self.account_box.current(index)
        self.account_confirmed.set(False)

    def _add_account(self):
        if self.busy or self.preview is not None:
            return
        dialog = tk.Toplevel(self.window)
        self.account_dialog = dialog
        dialog.title("Add Khan Bank account")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=18)
        content.pack(fill="both", expand=True)
        name, identifier = tk.StringVar(dialog), tk.StringVar(dialog)
        ttk.Label(content, text="Account name").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=name, width=46).grid(row=1, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(content, text="IBAN exactly as shown on the statement (text)").grid(row=2, column=0, sticky="w")
        ttk.Entry(content, textvariable=identifier, width=46).grid(row=3, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(content, text="Khan Bank · MNT\nSaving creates an account only; no transactions are imported.").grid(row=4, column=0, sticky="w")
        def close_dialog():
            if not self.busy:
                dialog.destroy()
                self.account_dialog = None
        def save():
            if not name.get().strip() or not identifier.get().strip():
                messagebox.showerror("Account", "Enter an account name and its statement IBAN.", parent=dialog)
                return
            if self._request("account", name=name.get(), identifier=identifier.get()):
                save_button.state(["disabled"])
                cancel.state(["disabled"])
        save_button = ttk.Button(content, text="Save account", command=save)
        save_button.grid(row=5, column=0, sticky="w", pady=(16, 0))
        cancel = ttk.Button(content, text="Cancel", command=close_dialog)
        cancel.grid(row=5, column=0, sticky="e", pady=(16, 0))
        self.account_dialog_buttons = (save_button, cancel)
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.grab_set()

    def _preview(self):
        index = self.account_box.current()
        if index >= 0 and self.account_confirmed.get():
            self.summary.set("")
            self._request("preview", path=self.file_path.get(), account_id=self.accounts[index]["id"])

    def _preview_values(self, row):
        source = row.source
        return (row.status.capitalize(), self.decisions.get(row.index, "Choose" if row.status == "ambiguous" else "—"),
                source.worksheet, source.row_number, source.occurred_at.replace("T", " "), source.description, format_mnt(source.amount_minor))

    def _show_candidates(self):
        selected = self.preview_table.tree.selection()
        if self.preview is None or not selected:
            self.candidates.set_items(())
        else:
            row = self.preview.rows[int(selected[0])]
            sources = [("Incoming", row.source)] + [(f"Existing #{c.transaction_id}", c.source) for c in row.candidates]
            self.candidates.set_items(sources, lambda pair: (
                pair[0], pair[1].worksheet, pair[1].row_number, pair[1].occurred_at.replace("T", " "),
                pair[1].description, format_mnt(pair[1].amount_minor), pair[1].reference or "—", format_mnt(pair[1].balance_minor)))
        self._sync_controls()

    def _decide(self, action):
        if self.busy or self.preview is None:
            return
        selected = self.preview_table.tree.selection()
        for item in selected:
            row = self.preview.rows[int(item)]
            if row.status == "ambiguous":
                if action is None:
                    self.decisions.pop(row.index, None)
                else:
                    self.decisions[row.index] = action
                self.preview_table.tree.item(item, values=self._preview_values(row))
        self.status.set(f"Duplicate decisions: {len(self.decisions)} of {self.preview.ambiguous_count}. Each skipped occurrence must have its own existing match.")
        self._sync_controls()

    def _commit(self):
        if self.preview is not None and self.preview.is_valid:
            self._request("commit", decisions=dict(self.decisions))

    def _cancel(self):
        self._request("cancel")

    def _clear_preview(self):
        self.preview, self.decisions = None, {}
        self.preview_table.set_items(())
        self.candidates.set_items(())
        self.issues.set_items(())
        self.preview_counts.set("Select an account and an XLSX statement to preview.")

    def _apply_filters(self):
        if self.busy:
            return
        try:
            index = self.category_box.current()
            self.active_filters = browser_filters(
                self.date_from.get(), self.date_to.get(), self.categories[index - 1]["id"] if index > 0 else None,
                None if self.direction_text.get() == "All directions" else self.direction_text.get().lower(),
                self.review_only.get(), self.search.get())
        except ValueError as error:
            self._error(str(error))
            return
        self._browse(0)

    def _reset_filters(self):
        self.date_from.set("")
        self.date_to.set("")
        self.search.set("")
        self.category_text.set("All categories")
        self.direction_text.set("All directions")
        self.review_only.set(False)
        self.review_hint.set("")
        self._apply_filters()

    def _browse(self, page=0):
        self._request("browse", filters=dict(self.active_filters), page=max(0, page), page_size=int(self.page_size.get()))

    def _review_unknown(self):
        if self.busy:
            return
        self.date_from.set("")
        self.date_to.set("")
        self.search.set("")
        self.category_text.set("All categories")
        self.direction_text.set("All directions")
        self.review_only.set(True)
        self.review_hint.set("Transactions awaiting review. Category editing is not available in this view yet.")
        self.tabs.select(self.transactions_tab)
        self._apply_filters()

    def _error(self, message):
        self.status.set(message)
        if not self.closing:
            messagebox.showerror("Personal Finance", message, parent=self.account_dialog or self.window)

    def _callback_error(self, *_):
        self._error("An interface action failed. Refresh the view or close and reopen the app.")

    def _poll(self):
        while True:
            try:
                event = self.worker.events.get_nowait()
            except Empty:
                break
            if event.operation == "stopped":
                self.ready, self.busy = False, False
                if self.closing:
                    self.window.destroy()
                    return
                self._sync_controls()
                continue
            if self.closing:
                continue
            self.busy = False
            if event.error:
                if event.operation == "fatal":
                    self.ready = False
                if self.account_dialog is not None:
                    for button in self.account_dialog_buttons:
                        button.state(["!disabled"])
                self._error(event.error)
            else:
                try:
                    self._handle(event.operation, event.payload)
                except Exception:
                    self._error("The operation finished but its view could not be updated. Refresh the view before continuing.")
            self._sync_controls()
        self._poll_id = self.window.after(40, self._poll)

    def _handle(self, operation, payload):
        self.status.set("Ready")
        if operation == "ready":
            self.ready = True
            self._set_accounts(payload["accounts"])
            self.categories = payload["categories"]
            self.category_box.configure(values=["All categories"] + [c["name"] for c in self.categories])
            self._browse()
        elif operation == "account":
            if self.account_dialog is not None:
                self.account_dialog.destroy()
                self.account_dialog = None
            self._set_accounts(payload["accounts"], payload["selected"])
            self.status.set("Account saved. Select a statement and confirm its account before previewing.")
        elif operation == "preview":
            # Row counts alone do not include statement/account validation errors.
            # Replace every previous diagnostic, even when the rows are all valid.
            self.summary.set("")
            self.preview, self.decisions = payload, {}
            self.candidates.set_items(())
            self.preview_table.set_items(payload.rows, self._preview_values)
            self.issues.set_items(payload.issues, lambda issue: (issue.severity, *issue_location(issue), issue.code, issue.message))
            errors = [issue for issue in payload.issues if issue.severity == "error"]
            self.preview_counts.set(f"Valid: {payload.valid_count} · Invalid: {payload.invalid_count} · Duplicate: {payload.duplicate_count} · Ambiguous: {payload.ambiguous_count} · Blocking errors: {len(errors)}. Nothing has been imported yet.")
            if not payload.is_valid:
                self.preview_tabs.select(1)
                if any(issue.code == "account_mismatch" for issue in errors):
                    message = ("Import blocked: the statement account/currency does not match the selected account. "
                               "Cancel preview, select or add the matching account, confirm it, and preview again. "
                               "Valid row counts do not mean the statement can be committed.")
                else:
                    message = "Import blocked. Review errors, cancel, and resolve the source problem before creating a new preview."
                self.summary.set(message)
                self.status.set(message)
            else:
                self.preview_tabs.select(0)
                self.status.set("Preview validated. Choose Keep/Skip for ambiguous rows, then click Commit import."
                                if payload.ambiguous_count else "Preview validated. Click Commit import to save these transactions.")
        elif operation == "cancel":
            self._clear_preview()
            self.summary.set("Preview canceled. No transactions or import metadata were changed.")
        elif operation == "commit":
            self._clear_preview()
            result = payload["result"]
            unclassified = payload["unclassified"]
            count = str(unclassified) if unclassified is not None else "unavailable — use Review unknown merchants"
            prefix = "Identical file already imported." if result.status == "identical_file" else "Import committed."
            self.summary.set(f"{prefix} Added: {result.imported_count} · Skipped: {result.skipped_count} · Unclassified added: {count}")
            # Old browser filters must not hide a successful import. The refresh
            # uses the same worker/connection that completed the atomic write.
            self.tabs.select(self.transactions_tab)
            self._reset_filters()
        elif operation == "browse":
            self.browser_page, self.browser_total = payload["page"], payload["total"]
            categories = {c["id"]: c["name"] for c in self.categories}
            self.transactions.set_items(payload["rows"], lambda row: (
                row["occurred_at"].replace("T", " "), row["merchant_display"] or row["description"], format_mnt(row["amount_minor"]),
                categories.get(row["category_id"], "—"), review_status(row)))
            pages = max(1, (payload["total"] + payload["page_size"] - 1) // payload["page_size"])
            self.browser_caption.set(f"Page {self.browser_page + 1} of {pages} · {self.browser_total} transactions")

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set("Closing after the current operation finishes…")
        self._sync_controls()
        self.worker.stop()
        if not self.worker.thread.is_alive():
            self.window.after_cancel(self._poll_id)
            self.window.destroy()
