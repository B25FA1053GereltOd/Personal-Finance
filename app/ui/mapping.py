"""Editable priority Mapping Table UI, using worker-owned mapping services."""

import tkinter as tk
from tkinter import messagebox, ttk
from app.ui.i18n import translate_format

from app.models import KINDS
from app.mapping_service import MappingService
from app.ui.i18n import localize_widget_tree, source_text
from app.ui.review import selected_items
from app.reporting import format_money


class MappingView:
    SOURCE_FIELDS = ("pos_id", "merchant", "description")
    OPERATORS = ("exact", "contains", "starts_with", "ends_with", "regex")
    DIRECTIONS = ("any", "debit", "credit")
    TARGET_KINDS = tuple(kind for kind in KINDS if kind != "unclassified")

    def __init__(self, app, table_factory):
        self.app, self.table_factory = app, table_factory
        self.editor = None
        self.pending = None
        self.editing_rule = None
        self.editor_fields = {}
        self.tab = ttk.Frame(app.tabs, padding=10)
        app.tabs.add(self.tab, text="Mapping Table")
        self.tab.columnconfigure(0, weight=1)
        self.tab.rowconfigure(2, weight=1)
        filters = ttk.Frame(self.tab)
        filters.grid(row=0, column=0, sticky="ew")
        self.search = tk.StringVar(app.window)
        self.state = tk.StringVar(app.window, app.t("All rules"))
        ttk.Label(filters, text="Search").grid(row=0, column=0, sticky="w", padx=4)
        entry = ttk.Entry(filters, textvariable=self.search, width=26)
        entry.grid(row=0, column=1, sticky="ew", padx=5)
        entry.bind("<Return>", lambda _: self.load())
        state = ttk.Combobox(filters, textvariable=self.state, state="readonly", width=14,
                             values=tuple(app.t(value) for value in ("All rules", "Active", "Disabled")))
        state.grid(row=0, column=2, padx=5)
        state.bind("<<ComboboxSelected>>", lambda _: self.load())
        self.bank = tk.StringVar(app.window, app.t("All bank scopes"))
        self.bank_box = ttk.Combobox(
            filters, textvariable=self.bank, state="readonly", width=24,
            values=(app.t("All bank scopes"),) + tuple(sorted({a["bank"] for a in app.accounts})))
        self.bank_box.grid(row=0, column=3, padx=5)
        self.bank_box.bind("<<ComboboxSelected>>", lambda _: self.load())
        self.buttons = []
        self.button_text = {}
        actions = ttk.Frame(filters)
        actions.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        for text, callback, icon in (
            ("Search", self.load, "🔄"), ("Add rule", self.add_rule, "➕"), ("Edit rule", self.edit_rule, "✏"),
            ("Enable / disable", self.toggle_rule, "⚡"), ("Delete rule", self.delete_rule, "🗑"),
            ("Test rule", self.test_selected, "🧪"), ("Preview matching transactions", self.preview, "👁"),
        ):
            button = ttk.Button(actions, text=f"{icon}  {app.t(text)}", command=callback)
            button.pack(side="left", padx=3)
            self.buttons.append(button)
            self.button_text[button] = text
        filters.columnconfigure(1, weight=1)
        self.table = table_factory(self.tab, [
            ("id", "ID", 45), ("rule_name", "Rule name", 145), ("priority", "Priority", 65),
            ("scope", "Bank / account scope", 170), ("direction", "Direction", 75),
            ("source_field", "Field", 90), ("operator", "Condition", 90),
            ("match_value", "Match value", 160), ("target", "Target", 200),
            ("active", "Active", 65), ("note", "Note", 140),
        ], title="Classification Mapping Table", height=14)
        self.table.grid(row=2, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda _: self.sync())
        self.status = tk.StringVar(app.window, app.t("Mapping Table rules classify only matching eligible transactions."))
        ttk.Label(self.tab, textvariable=self.status, wraplength=1100).grid(
            row=3, column=0, sticky="w", pady=(6, 0))

    def sync(self):
        idle = (self.app.ready and not self.app.busy and not self.app.closing
                and self.app.preview is None
                and not (self.app.review_views and (
                    self.app.review_views.pending is not None or self.app.review_views.editor is not None)))
        selected = len(selected_items(self.table)) == 1
        for button in self.buttons:
            self.app._enabled(button, idle and (
                self.button_text[button] in ("Search", "Add rule") or selected))
        self.app._enabled(self.bank_box, idle)
        for widget in self.editor_widgets if self.editor else ():
            self.app._enabled(widget, idle)
        if self.pending is not None:
            self.app._enabled(self.preview_apply, idle and bool(selected_items(self.preview_table)))
            if hasattr(self, "preview_apply_all"):
                self.app._enabled(self.preview_apply_all, idle and bool(self.pending.rows))

    def load(self):
        state = source_text(self.state.get(), ("All rules", "Active", "Disabled"))
        active = {"Active": True, "Disabled": False}.get(state)
        bank_values = (self.app.t("All bank scopes"),) + tuple(sorted({a["bank"] for a in self.app.accounts}))
        self.bank_box.configure(values=bank_values)
        if self.bank.get() not in bank_values:
            self.bank.set(self.app.t("All bank scopes"))
        bank = source_text(self.bank.get(), ("All bank scopes",))
        self.app._request("mapping_load", search=self.search.get(), active=active,
                          bank=None if bank == "All bank scopes" else bank)

    def _selected_rule(self):
        rows = selected_items(self.table)
        if len(rows) != 1:
            self.app._error("Select one mapping rule.")
            return None
        return rows[0]

    def add_rule(self):
        self._open_editor(None)

    def edit_rule(self):
        row = self._selected_rule()
        if row is not None:
            self._open_editor(row)

    def _open_editor(self, rule):
        if self.editor is not None:
            self.editor.destroy()
        dialog = self.editor = tk.Toplevel(self.app.window)
        self.editing_rule = rule
        dialog.title(self.app.t("Add mapping rule") if rule is None else self.app.t("Edit mapping rule"))
        dialog.geometry("760x710")
        dialog.transient(self.app.window)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        self.editor_fields = {}
        self.editor_widgets = []
        values = rule or {}

        def add_entry(key, label, default=""):
            row_index = len(self.editor_fields)
            ttk.Label(frame, text=self.app.t(label)).grid(row=row_index, column=0, sticky="w", pady=3)
            variable = tk.StringVar(dialog, str(values.get(key, default)))
            widget = ttk.Entry(frame, textvariable=variable)
            widget.grid(row=row_index, column=1, sticky="ew", padx=6, pady=3)
            self.editor_fields[key] = variable
            self.editor_widgets.append(widget)

        def add_combo(key, label, choices, default):
            row_index = len(self.editor_fields)
            ttk.Label(frame, text=self.app.t(label)).grid(row=row_index, column=0, sticky="w", pady=3)
            variable = tk.StringVar(dialog)
            widget = ttk.Combobox(frame, textvariable=variable, state="readonly", values=choices)
            widget.grid(row=row_index, column=1, sticky="ew", padx=6, pady=3)
            current = values.get(key, default)
            variable.set(str(current))
            self.editor_fields[key] = variable
            self.editor_widgets.append(widget)
            return widget

        add_entry("rule_name", "Rule name")
        add_entry("note", "Note")
        add_entry("priority", "Priority", "100")
        bank_choices = (self.app.t("Any bank"),) + tuple(sorted({a["bank"] for a in self.app.accounts}))
        add_combo("bank", "Bank", bank_choices, values.get("bank") or self.app.t("Any bank"))
        account_choices = (self.app.t("Any account"),) + tuple(
            f'{a["name"]} ({a["currency"]}) #{a["id"]}' for a in self.app.accounts)
        initial_account = self.app.t("Any account")
        if rule and rule["account_id"] is not None:
            account = next((a for a in self.app.accounts if a["id"] == rule["account_id"]), None)
            if account is not None:
                initial_account = f'{account["name"]} ({account["currency"]}) #{account["id"]}'
        account_box = add_combo("account", "Account", account_choices, initial_account)
        account_box.bind("<<ComboboxSelected>>", lambda _: self._account_scope_changed())
        add_combo("direction", "Direction",
                  tuple(self.app.t(v) for v in ("Any direction", "Debit", "Credit")),
                  self.app.t({"any": "Any direction", "debit": "Debit", "credit": "Credit"}.get(
                      values.get("direction", "any"))))
        add_combo("source_field", "Source field",
                  tuple(self.app.t(v) for v in self.SOURCE_FIELDS),
                  self.app.t(values.get("source_field", "description")))
        add_combo("operator", "Match operator",
                  tuple(self.app.t(v) for v in self.OPERATORS),
                  self.app.t(values.get("operator", "exact")))
        add_entry("match_value", "Match value")
        target_labels = tuple(self.app.t(kind.title()) for kind in self.TARGET_KINDS)
        kind_box = add_combo("target_kind", "Target kind", target_labels,
                             self.app.t(values.get("target_kind", "expense").title()))
        self.category_var = tk.StringVar(dialog)
        category_row = len(self.editor_fields)
        ttk.Label(frame, text=self.app.t("Target category")).grid(row=category_row, column=0, sticky="w", pady=3)
        self.category_box = ttk.Combobox(frame, textvariable=self.category_var, state="readonly")
        self.category_box.grid(row=category_row, column=1, sticky="ew", padx=6, pady=3)
        self.editor_fields["category_id"] = self.category_var
        self.editor_widgets.append(self.category_box)
        kind_box.bind("<<ComboboxSelected>>", lambda _: self._update_categories())
        sample_row = len(self.editor_fields)
        ttk.Label(frame, text=self.app.t("Synthetic test sample")).grid(row=sample_row, column=0, sticky="w", pady=3)
        self.sample = tk.StringVar(dialog)
        sample_entry = ttk.Entry(frame, textvariable=self.sample)
        sample_entry.grid(row=sample_row, column=1, sticky="ew", padx=6, pady=3)
        self.editor_widgets.append(sample_entry)
        self.active_var = tk.BooleanVar(dialog, bool(values.get("active", True)))
        active_box = ttk.Checkbutton(frame, text=self.app.t("Active"), variable=self.active_var)
        active_box.grid(row=sample_row + 1, column=1, sticky="w")
        self.editor_widgets.append(active_box)
        self._update_categories(values.get("category_id"))
        controls = ttk.Frame(frame)
        controls.grid(row=sample_row + 2, column=0, columnspan=2, sticky="ew", pady=12)
        test = ttk.Button(controls, text=self.app.t("Test rule"), command=self.test_editor)
        test.pack(side="left")
        save = ttk.Button(controls, text=self.app.t("Save"), command=self.save_editor, style="Primary.TButton")
        save.pack(side="left", padx=6)
        cancel = ttk.Button(controls, text=self.app.t("Cancel"), command=self.close_editor)
        cancel.pack(side="left")
        self.editor_widgets.extend((test, save, cancel))
        dialog.protocol("WM_DELETE_WINDOW", self.close_editor)
        localize_widget_tree(dialog)
        dialog.grab_set()
        self.sync()

    def _account_scope_changed(self):
        if self.editor is None:
            return
        index = next((i for i, account in enumerate(self.app.accounts, 1)
                      if self.editor_fields["account"].get().endswith(f'#{account["id"]}')), 0)
        if index and source_text(self.editor_fields["bank"].get(), ("Any bank",)) == "Any bank":
            self.editor_fields["bank"].set(self.app.accounts[index - 1]["bank"])

    def _update_categories(self, selected_id=None):
        if not hasattr(self, "category_box") or self.editor is None:
            return
        kind = source_text(self.editor_fields["target_kind"].get(),
                           tuple(value.title() for value in self.TARGET_KINDS)).casefold()
        categories = self.app.active_categories(direction=kind)
        names = [self.app.category_display_name(c) for c in categories]
        self.category_box.configure(values=names)
        category = next((c for c in categories if c["id"] == selected_id), None)
        if category:
            self.category_var.set(self.app.category_display_name(category))
        elif self.category_var.get() not in names:
            self.category_var.set(names[0] if names else "")
        self.app._enabled(self.category_box, kind in ("income", "expense"))

    def _rule_values(self):
        f = self.editor_fields
        bank = source_text(f["bank"].get(), ("Any bank",))
        account_text = f["account"].get()
        account = next((a for a in self.app.accounts
                        if account_text.endswith(f'#{a["id"]}')), None)
        direction = source_text(f["direction"].get(), ("Any direction", "Debit", "Credit"))
        source_field = source_text(f["source_field"].get(), self.SOURCE_FIELDS)
        operator = source_text(f["operator"].get(), self.OPERATORS)
        category_id = self.app.resolve_category_id(self.category_var.get())
        return {
            "rule_name": f["rule_name"].get(),
            "note": f["note"].get() if "note" in f else "",
            "priority": int(f["priority"].get()),
            "active": bool(self.active_var.get()),
            "bank": None if bank == "Any bank" else bank,
            "account_id": account["id"] if account else None,
            "direction": {"Any direction": "any", "Debit": "debit", "Credit": "credit"}[direction],
            "source_field": source_field,
            "operator": {"starts_with": "starts_with", "ends_with": "ends_with"}.get(operator, operator),
            "match_value": f["match_value"].get(),
            "target_kind": source_text(f["target_kind"].get(),
                                       tuple(value.title() for value in self.TARGET_KINDS)).casefold(),
            "category_id": category_id if source_text(
                f["target_kind"].get(), tuple(value.title() for value in self.TARGET_KINDS)).casefold()
                in ("income", "expense") else None,
            **({"rule_id": self.editing_rule["id"],
                "expected_revision": self.editing_rule["revision"]} if self.editing_rule else {}),
        }

    def save_editor(self):
        try:
            values = self._rule_values()
        except (ValueError, KeyError) as error:
            self.app._error(str(error) or "Complete the mapping rule fields.")
            return
        warnings = MappingService.warnings(values)
        for warning in warnings:
            if not messagebox.askyesno(self.app.t("Broad mapping rule warning"),
                                       self.app.t(warning), parent=self.editor, default="no"):
                return
        self.app._request("mapping_save", **values)

    def test_editor(self):
        try:
            values = self._rule_values()
        except (ValueError, KeyError) as error:
            self.app._error(str(error) or "Complete the mapping rule fields.")
            return
        self.app._request("mapping_test", rule=values, sample=self.sample.get())

    def test_selected(self):
        rule = self._selected_rule()
        if rule is not None:
            self._open_editor(rule)
            self.test_editor()

    def toggle_rule(self):
        rule = self._selected_rule()
        if rule is not None:
            self.app._request("mapping_active", rule_id=rule["id"],
                              active=not bool(rule["active"]), expected_revision=rule["revision"])

    def delete_rule(self):
        rule = self._selected_rule()
        if rule is not None and messagebox.askyesno(
                self.app.t("Delete mapping rule"),
                self.app.t("Delete this mapping rule? Existing transactions and currency values will remain unchanged."),
                parent=self.app.window, default="no"):
            self.app._request("mapping_delete", rule_id=rule["id"], expected_revision=rule["revision"])

    def preview(self):
        rule = self._selected_rule()
        if rule is not None:
            self.app._request("mapping_preview", rule_id=rule["id"])

    def _show_preview(self, preview):
        dialog = self.preview_dialog = tk.Toplevel(self.app.window)
        dialog.title(self.app.t("Preview mapping rule matches"))
        dialog.geometry("1000x540")
        dialog.transient(self.app.window)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text=self.app.t("Select only eligible transactions to apply; protected rows are excluded."),
                  wraplength=950).grid(row=0, column=0, sticky="w", padx=12, pady=10)
        self.preview_table = self.table_factory(dialog, [
            ("id", "ID", 60), ("bank", "Bank", 120), ("account", "Account", 150),
            ("description", "Description", 410), ("amount", "Amount", 140)],
            title=f'{self.app.t("Matching transactions")}: {len(preview.rows)}',
            selectmode="extended")
        self.preview_table.grid(row=1, column=0, sticky="nsew", padx=12)
        self.preview_table.set_items(preview.rows, lambda r: (
            r["id"], r["bank"], r["account_name"], r["description"],
            format_money(r["amount_minor"], r["currency"])))
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=10)
        self.preview_apply = ttk.Button(buttons, text=self.app.t("Apply to selected"), command=self.apply_preview)
        self.preview_apply.pack(side="left")
        self.preview_apply_all = ttk.Button(
            buttons, text=self.app.t("Apply to existing eligible rows"),
            command=self.apply_all_preview, style="Primary.TButton")
        self.preview_apply_all.pack(side="left", padx=8)
        cancel = ttk.Button(buttons, text=self.app.t("Cancel"), command=self.cancel_preview)
        cancel.pack(side="left", padx=4)
        self.pending = preview
        self.preview_buttons = (self.preview_apply, self.preview_apply_all, cancel)
        dialog.protocol("WM_DELETE_WINDOW", self.cancel_preview)
        localize_widget_tree(dialog)
        dialog.grab_set()
        self.sync()

    def apply_preview(self):
        self.app._request("mapping_apply", token=self.pending.token,
                          transaction_ids=[r["id"] for r in selected_items(self.preview_table)])

    def apply_all_preview(self):
        if self.pending is not None:
            self.app._request("mapping_apply", token=self.pending.token,
                              transaction_ids=[r["id"] for r in self.pending.rows])

    def cancel_preview(self):
        if not self.app.busy:
            self.app._request("mapping_cancel")

    def close_editor(self):
        if self.editor is not None and not self.app.busy:
            self.editor.destroy()
            self.editor = None
            self.editing_rule = None
            self.app._sync_controls()

    def handle(self, operation, payload):
        if operation == "mapping_load":
            categories = {c["id"]: self.app.category_display_name(c) for c in self.app.categories}
            accounts = {a["id"]: a for a in self.app.accounts}

            def display(rule):
                scope = rule["bank"] or self.app.t("Any bank")
                if rule["account_id"] is not None:
                    account = accounts[rule["account_id"]]
                    scope += f' / {account["name"]} #{account["id"]}'
                target = self.app.t(rule["target_kind"].title())
                if rule["category_id"] is not None:
                    target += " / " + categories.get(rule["category_id"], "")
                return (rule["id"], rule["rule_name"], rule["priority"], scope,
                        self.app.t({"any": "Any direction", "debit": "Debit", "credit": "Credit"}[rule["direction"]]),
                        self.app.t(rule["source_field"]), self.app.t(rule["operator"]),
                        rule["match_value"], target, self.app.t("Active" if rule["active"] else "Disabled"),
                        rule.get("note", ""))

            self.table.set_items(payload, display)
            self.status.set(translate_format("{count} mapping rules loaded.", count=len(payload)))
        elif operation == "mapping_test":
            result = payload
            message = self.app.t("The synthetic sample matches this rule.") if result["matched"] else self.app.t(
                "The synthetic sample does not match this rule.")
            if result["warnings"]:
                message += "\n" + "\n".join(self.app.t(w) for w in result["warnings"])
            messagebox.showinfo(self.app.t("Test rule"), message, parent=self.editor or self.app.window)
        elif operation == "mapping_preview":
            self._show_preview(payload)
        elif operation == "mapping_cancel":
            if getattr(self, "preview_dialog", None) is not None:
                self.preview_dialog.destroy()
            self.pending = None
            self.preview_dialog = None
            self.load()
        elif operation in ("mapping_save", "mapping_active", "mapping_delete", "mapping_apply"):
            if operation == "mapping_save":
                if self.editor is not None:
                    self.editor.destroy()
                    self.editor = None
                    self.editing_rule = None
                if payload["warnings"]:
                    self.status.set(self.app.t(payload["warnings"][0]))
            if operation == "mapping_apply":
                self.preview_dialog.destroy()
                self.pending = None
            self.status.set(self.app.t("Mapping rule saved; currency and source data remain unchanged.")
                            if operation == "mapping_save" else self.app.t("Mapping table updated."))
            self.load()
