"""Review, explicit rule application, and effective-value editor widgets."""

import tkinter as tk
from tkinter import ttk

from app.models import KINDS, minor_to_money
from app.ui.presentation import format_mnt


def selected_items(table):
    return [table.items[int(i)] for i in table.tree.selection() if int(i) < len(table.items)]


class ReviewViews:
    def __init__(self, app, table_factory):
        self.app, self.table_factory = app, table_factory
        self.pending = None
        self.dialog = None
        self.editor = None
        self.actions, self.dialog_actions, self.editor_actions = [], [], []
        self.category = tk.StringVar(app.window)
        self.rule_category = tk.StringVar(app.window)
        self.save_future = tk.BooleanVar(app.window, False)
        self.message = tk.StringVar(app.window, "Refresh to load transactions awaiting review.")
        self.review_tab = ttk.Frame(app.tabs, padding=10)
        self.rules_tab = ttk.Frame(app.tabs, padding=10)
        app.tabs.add(self.review_tab, text="Review")
        app.tabs.add(self.rules_tab, text="Rules")
        self._build_review()
        self._build_rules()

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=4, pady=4)
        self.actions.append(button)
        return button

    def _build_review(self):
        tab = self.review_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)
        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew")
        self._button(bar, "Refresh review", self.open)
        self._button(bar, "Expand selected group", self.expand)
        self._button(bar, "Skip for later", self.skip)
        self.groups = self.table_factory(tab, [
            ("merchant", "Merchant / individual item", 240), ("count", "Count", 65),
            ("amount", "Total MNT", 130), ("direction", "Direction", 80),
            ("description", "Example description", 360)], title="Unknown merchants and individual items", height=6)
        self.groups.grid(row=1, column=0, sticky="nsew")
        self.groups.tree.bind("<<TreeviewSelect>>", lambda _: self.expand())
        self.groups.tree.bind("<Double-1>", lambda _: self.expand())
        ttk.Label(tab, text="Select only the transactions to change (Ctrl/Shift for multiple). No rows are selected automatically.",
                  wraplength=1000).grid(row=2, column=0, sticky="w", pady=5)
        self.rows = self.table_factory(tab, [
            ("id", "ID", 65), ("description", "Description", 420), ("amount", "Amount", 140),
            ("protected", "Manual protection", 130)], title="Expanded transactions", height=6, selectmode="extended")
        self.rows.grid(row=3, column=0, sticky="nsew")
        self.rows.tree.bind("<<TreeviewSelect>>", lambda _: self._categories())
        controls = ttk.Frame(tab)
        controls.grid(row=4, column=0, sticky="ew", pady=6)
        ttk.Label(controls, text="Category").pack(side="left")
        self.category_box = ttk.Combobox(controls, textvariable=self.category, state="readonly", width=36)
        self.category_box.pack(side="left", padx=4)
        self.actions.append(self.category_box)
        self.future_box = ttk.Checkbutton(controls, text="Also save a rule for future imports", variable=self.save_future)
        self.future_box.pack(side="left", padx=4)
        self.actions.append(self.future_box)
        self._button(controls, "Preview selected changes", self.preview_assignment)
        self._button(controls, "Edit selected transaction", self.edit_review_row)
        ttk.Label(tab, textvariable=self.message, wraplength=1050).grid(row=5, column=0, sticky="w", pady=6)

    def _build_rules(self):
        tab = self.rules_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew")
        self._button(bar, "Refresh rules", lambda: self.app._request("review_load"))
        ttk.Label(bar, text="Saving or disabling a rule never changes past classifications.").pack(side="left", padx=8)
        self.rules = self.table_factory(tab, [
            ("id", "ID", 55), ("bank", "Bank", 110), ("merchant", "Exact merchant key", 320),
            ("direction", "Direction", 80), ("category", "Category", 250), ("active", "State", 85)],
            title="Saved rules, including disabled rules", height=15)
        self.rules.grid(row=1, column=0, sticky="nsew")
        self.rules.tree.bind("<<TreeviewSelect>>", lambda _: self.rule_selected())
        controls = ttk.Frame(tab)
        controls.grid(row=2, column=0, sticky="ew")
        self.rule_category_box = ttk.Combobox(controls, textvariable=self.rule_category, state="readonly", width=40)
        self.rule_category_box.pack(side="left", padx=4)
        self.actions.append(self.rule_category_box)
        self._button(controls, "Save category / enable (future only)", lambda: self.change_rule(False))
        self._button(controls, "Disable rule", lambda: self.change_rule(True))
        self._button(controls, "Preview existing eligible rows", self.preview_rule)

    def sync(self):
        idle = self.app.ready and not self.app.busy and not self.app.closing
        available = idle and self.app.preview is None and self.pending is None and self.editor is None
        for widget in self.actions:
            self.app._enabled(widget, available)
        group = selected_items(self.groups)
        self.app._enabled(self.future_box, available and bool(group) and group[0]["reliable"])
        for widget in (*self.dialog_actions, *self.editor_actions):
            self.app._enabled(widget, idle)

    def open(self):
        if self.app._request("review_load"):
            self.app.tabs.select(self.review_tab)

    def expand(self):
        if self.pending is not None or self.app.busy:
            return
        groups = selected_items(self.groups)
        self.save_future.set(False)
        self.category.set("")
        self.rows.set_items(groups[0]["items"] if groups else (), lambda r: (
            r.transaction_id, r.description, format_mnt(r.amount_minor), "Protected" if r.manual_lock else "Unlocked"))
        self._categories()
        self.sync()

    def _categories(self):
        items = selected_items(self.rows)
        amounts = [i.amount_minor for i in items]
        names = [c["name"] for c in self.app.categories if amounts and
                 all(a > 0 if c["direction"] == "income" else a < 0 for a in amounts)]
        self.category_box.configure(values=names)
        if self.category.get() not in names:
            self.category.set("")

    def _category_id(self, name):
        return next((c["id"] for c in self.app.categories if c["name"] == name), None)

    def skip(self):
        if self.pending is None and not self.app.busy:
            self.rows.set_items(())
            self.category.set("")
            self.save_future.set(False)
            self.message.set("Skipped for later. No data changed; unreviewed items remain available after restart.")

    def preview_assignment(self):
        self.app._request("review_preview", transaction_ids=[i.transaction_id for i in selected_items(self.rows)],
                          category_id=self._category_id(self.category.get()), save_rule=self.save_future.get())

    def edit_review_row(self):
        items = selected_items(self.rows)
        if len(items) != 1:
            self.app._error("Select one transaction to edit.")
        else:
            self.app._request("edit_get", transaction_id=items[0].transaction_id)

    def rule_selected(self):
        rules = selected_items(self.rules)
        if not rules:
            return
        rule = rules[0]
        direction = "expense" if rule["direction"] == "debit" else "income"
        self.rule_category_box.configure(values=[c["name"] for c in self.app.categories if c["direction"] == direction])
        self.rule_category.set(next((c["name"] for c in self.app.categories if c["id"] == rule["category_id"]), ""))

    def change_rule(self, disable):
        rules = selected_items(self.rules)
        if not rules:
            self.app._error("Select a rule first.")
            return
        rule = rules[0]
        self.app._request("rule_change", rule_id=rule["id"], revision=rule["revision"],
                          category_id=self._category_id(self.rule_category.get()), disable=disable)

    def preview_rule(self):
        rules = selected_items(self.rules)
        if rules:
            self.app._request("rule_preview", rule_id=rules[0]["id"])
        else:
            self.app._error("Select an active rule first.")

    def _preview_dialog(self, mode, payload):
        self.pending = (mode, payload)
        dialog = self.dialog = tk.Toplevel(self.app.window)
        dialog.title("Preview changes - nothing has been saved")
        dialog.geometry("1000x540")
        dialog.transient(self.app.window)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        category_id = payload["category_id"] if mode == "assignment" else payload.category_id
        category = next(c["name"] for c in self.app.categories if c["id"] == category_id)
        if mode == "assignment":
            detail = "Selected transactions only; manual protection will be enabled."
            if payload["scope"]:
                detail += " Also save/enable an exact rule for future imports."
                bank, key, direction = payload["scope"]
                detail += f"\nBank: {bank}; direction: {direction}; exact merchant key: {key}."
                if payload["replaces_rule"]:
                    detail += " This replaces the saved rule for this scope."
            rows = payload["rows"]
            values = lambda r: (r["id"], r["occurred_at"], r["description"], format_mnt(r["amount_minor"]))
        else:
            detail = "Select eligible rows to apply. Locked, incompatible and unselected rows will not change."
            rows = payload.candidates
            values = lambda r: (r.transaction_id, r.direction, r.description, format_mnt(r.amount_minor))
        ttk.Label(dialog, text=f"Target category: {category}\n{detail}", wraplength=950).grid(row=0, column=0, sticky="w", padx=12, pady=10)
        self.preview_rows = self.table_factory(dialog, [
            ("id", "ID", 60), ("date", "Date / direction", 180), ("description", "Description", 480),
            ("amount", "Amount", 140)], title=f"Affected candidates: {len(rows)}", selectmode="extended")
        self.preview_rows.grid(row=1, column=0, sticky="nsew", padx=12)
        self.preview_rows.set_items(rows, values)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
        apply = ttk.Button(buttons, text="Confirm these changes" if mode == "assignment" else "Apply to selected rows", command=self.apply_preview)
        apply.pack(side="left")
        cancel = ttk.Button(buttons, text="Cancel / skip for later", command=self.cancel_preview)
        cancel.pack(side="left", padx=8)
        self.dialog_actions = [apply, cancel]
        dialog.protocol("WM_DELETE_WINDOW", self.cancel_preview)
        dialog.grab_set()

    def apply_preview(self):
        mode, payload = self.pending
        if mode == "assignment":
            self.app._request("review_apply", token=payload["token"])
        else:
            self.app._request("rule_apply", token=payload.token,
                              transaction_ids=[r.transaction_id for r in selected_items(self.preview_rows)])

    def cancel_preview(self):
        if not self.app.busy:
            self.app._request("review_cancel")

    def _close_preview(self):
        if self.dialog is not None:
            self.dialog.destroy()
        self.pending, self.dialog, self.dialog_actions = None, None, []

    def _edit_dialog(self, payload):
        if self.editor is not None:
            self.editor.destroy()
        row = payload["row"]
        self.edit_snapshot = payload
        self.editor = dialog = tk.Toplevel(self.app.window)
        dialog.title("Edit transaction - bank source remains unchanged")
        dialog.geometry("950x720")
        dialog.transient(self.app.window)
        tabs = ttk.Notebook(dialog)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        effective = ttk.Frame(tabs, padding=12)
        tabs.add(effective, text="Effective values")
        source = ttk.Frame(tabs, padding=12)
        tabs.add(source, text="Bank source (read-only)")
        history = ttk.Frame(tabs, padding=12)
        tabs.add(history, text="Edit history (read-only)")
        self.edit_fields = {}
        self.editor_actions = []
        data = [("occurred_at", "ISO date / time", row["occurred_at"]),
                ("amount", "Signed MNT (decimal, no commas)", str(minor_to_money(row["amount_minor"]))),
                ("description", "Description", row["description"]),
                ("merchant_display", "Merchant display (does not change matching key)", row["merchant_display"] or ""),
                ("kind", "Kind", row["kind"]),
                ("category", "Category", next((c["name"] for c in self.app.categories if c["id"] == row["category_id"]), "No category")),
                ("note", "Note", row["note"])]
        for index, (key, label, value) in enumerate(data):
            ttk.Label(effective, text=label).grid(row=index * 2, column=0, sticky="w")
            variable = self.edit_fields[key] = tk.StringVar(dialog, value)
            if key in ("kind", "category"):
                choices = KINDS if key == "kind" else ["No category"] + [c["name"] for c in self.app.categories]
                widget = ttk.Combobox(effective, textvariable=variable, values=choices, state="readonly", width=65)
            else:
                widget = ttk.Entry(effective, textvariable=variable, width=90)
            widget.grid(row=index * 2 + 1, column=0, sticky="ew", pady=(2, 8))
            self.editor_actions.append(widget)
        effective.columnconfigure(0, weight=1)
        self.clear_protection = tk.BooleanVar(dialog, False)
        protection = ttk.Checkbutton(effective, text="Explicitly clear manual protection (allow later rule application)", variable=self.clear_protection)
        protection.grid(row=14, column=0, sticky="w", pady=4)
        self.editor_actions.append(protection)
        ttk.Label(effective, text=f"Current protection: {'protected' if row['manual_lock'] else 'unlocked'}. Saving protects this edit by default.\n"
                  "A direction change needs a compatible kind/category, or choose unclassified and No category.", wraplength=850).grid(row=15, column=0, sticky="w")
        source_fields = [k for k in row if k.startswith("original_") or k in ("bank_datetime", "worksheet", "row_number", "dedup_key", "merchant_key", "merchant_pattern", "merchant_type")]
        self._readonly_text(source, "\n\n".join(f"{k}: {row[k]}" for k in source_fields))
        lines = []
        for entry in payload["history"]:
            lines.append(f"{entry['edited_at']} - {entry['reason']}")
            lines.extend(f"  {key}: {delta['old']} -> {delta['new']}" for key, delta in entry["changes"].items())
        self._readonly_text(history, "\n".join(lines) or "No edits recorded.")
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=8)
        save = ttk.Button(buttons, text="Save this transaction only", command=self.save_edit)
        save.pack(side="left")
        cancel = ttk.Button(buttons, text="Cancel", command=self.close_editor)
        cancel.pack(side="left", padx=8)
        self.editor_actions.extend((save, cancel))
        dialog.protocol("WM_DELETE_WINDOW", self.close_editor)
        dialog.grab_set()

    @staticmethod
    def _readonly_text(parent, text):
        widget = tk.Text(parent, wrap="word")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
        scrollbar.pack(side="right", fill="y")
        widget.configure(yscrollcommand=scrollbar.set)
        widget.pack(fill="both", expand=True)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def save_edit(self):
        fields = {key: variable.get() for key, variable in self.edit_fields.items()}
        fields["category_id"] = self._category_id(fields.pop("category"))
        self.app._request("edit_save", transaction_id=self.edit_snapshot["row"]["id"],
                          revision=self.edit_snapshot["revision"], fields=fields,
                          clear_protection=self.clear_protection.get())

    def close_editor(self):
        if not self.app.busy and self.editor is not None:
            self.editor.destroy()
            self.editor, self.editor_actions = None, []
            self.app._sync_controls()

    def handle(self, operation, payload):
        if operation == "review_load":
            queue = payload["queue"]
            groups = [{"name": g.merchant_key, "direction": g.direction, "items": g.items, "reliable": True} for g in queue.groups]
            groups.extend({"name": "Individual item (no group)", "direction": i.direction, "items": (i,), "reliable": False} for i in queue.individual)
            self.groups.set_items(groups, lambda g: (g["name"], len(g["items"]),
                format_mnt(sum(i.amount_minor for i in g["items"])), g["direction"], g["items"][0].description))
            self.rows.set_items(())
            self.category.set("")
            self.save_future.set(False)
            categories = {c["id"]: c["name"] for c in self.app.categories}
            self.rules.set_items(payload["rules"], lambda r: (r["id"], r["bank"], r["merchant_key"], r["direction"],
                categories.get(r["category_id"], "No category"), "Active" if r["active"] else "Disabled"))
            self.message.set(f"{len(queue.groups)} merchant groups; {len(queue.individual)} individual items. Skipping changes nothing.")
            self.app._browse(self.app.browser_page)
        elif operation in ("review_preview", "rule_preview"):
            self._preview_dialog("assignment" if operation == "review_preview" else "rule", payload)
        elif operation == "review_cancel":
            self._close_preview()
            self.message.set("Preview canceled. No categories or rules were changed.")
        elif operation in ("review_apply", "rule_apply", "rule_change", "edit_save"):
            if operation in ("review_apply", "rule_apply"):
                self._close_preview()
            if operation == "edit_save":
                self.close_editor()
            message = {"review_apply": "Selected transactions classified and protected.",
                       "rule_apply": "Rule applied only to explicitly selected eligible rows.",
                       "rule_change": "Rule saved for future use; past classifications unchanged.",
                       "edit_save": "Transaction correction saved with history; bank source unchanged."}[operation]
            self.app.summary.set(message)
            self.app._request("review_load")
        elif operation == "edit_get":
            self._edit_dialog(payload)
