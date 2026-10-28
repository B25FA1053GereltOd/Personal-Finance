"""Category management dialog: add, edit display name, enable/disable, delete, restore defaults."""

import tkinter as tk
from tkinter import messagebox, ttk

from app.ui.i18n import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    get_category_display_name,
    localize_widget_tree,
    save_category_settings,
    source_text,
    translate,
    translate_format,
)
from app.ui.theme import get_current_theme


class CategoriesDialog:
    """Dialog allowing user to view, add, edit display name, toggle, delete, and restore categories."""

    def __init__(self, app, parent=None):
        self.app = app
        self.parent = parent or app.window
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(f"🏷  {self.app.t('Category management')}")
        self.dialog.geometry("820x560")
        self.dialog.minsize(720, 480)
        self.dialog.transient(self.parent)
        tokens = get_current_theme()
        self.dialog.configure(background=tokens.bg)

        self.usage_data = {}  # category_id -> dict
        self.filter_direction = tk.StringVar(self.dialog, self.app.t("All"))
        self.search_text = tk.StringVar(self.dialog, "")

        self._build_ui()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        localize_widget_tree(self.dialog)
        self.dialog.grab_set()

        # Request fresh usage stats from worker
        self.app._request("category_list_usage")
        self.refresh()

    def _build_ui(self):
        tokens = get_current_theme()
        container = ttk.Frame(self.dialog, padding=(16, 14), style="TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        # Header
        header = ttk.Frame(container, style="TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            header, text=f"🏷  {self.app.t('Category management')}",
            font=(tokens.font_family, 13, "bold"), style="TLabel",
        ).pack(side="left")
        ttk.Label(
            header,
            text=self.app.t("Manage transaction categories, custom display names, and default presets."),
            style="Muted.TLabel",
        ).pack(side="left", padx=(12, 0))

        # Filters toolbar
        filters = ttk.Frame(container, style="TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(filters, text=self.app.t("Direction") + ":", style="TLabel").pack(side="left", padx=(0, 6))

        direction_choices = (self.app.t("All"), self.app.t("Expense"), self.app.t("Income"))
        self.dir_combo = ttk.Combobox(
            filters, textvariable=self.filter_direction, values=direction_choices,
            state="readonly", width=14,
        )
        self.dir_combo.pack(side="left", padx=(0, 14))
        self.dir_combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())

        ttk.Label(filters, text=self.app.t("Search") + ":", style="TLabel").pack(side="left", padx=(0, 6))
        search_entry = ttk.Entry(filters, textvariable=self.search_text, width=24)
        search_entry.pack(side="left", padx=(0, 10))
        search_entry.bind("<KeyRelease>", lambda _: self.refresh())

        self.count_label = ttk.Label(filters, text="", style="Muted.TLabel")
        self.count_label.pack(side="right")

        # Treeview table
        table_frame = ttk.Frame(container, style="TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("id", "direction", "display_name", "canonical", "status", "usage")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.column("id", width=45, anchor="center")
        self.tree.heading("direction", text=self.app.t("Direction"))
        self.tree.column("direction", width=95, anchor="center")
        self.tree.heading("display_name", text=self.app.t("Display name"))
        self.tree.column("display_name", width=230, anchor="w")
        self.tree.heading("canonical", text=self.app.t("Canonical key"))
        self.tree.column("canonical", width=210, anchor="w")
        self.tree.heading("status", text=self.app.t("Status"))
        self.tree.column("status", width=90, anchor="center")
        self.tree.heading("usage", text=self.app.t("Usage"))
        self.tree.column("usage", width=110, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("odd", background=tokens.tree_alt)
        self.tree.tag_configure("even", background=tokens.tree_bg)
        self.tree.tag_configure("disabled_row", foreground=tokens.muted)

        self.tree.bind("<<TreeviewSelect>>", lambda _: self._sync_buttons())
        self.tree.bind("<Double-1>", lambda _: self.edit_display_name())

        # Buttons toolbar
        buttons = ttk.Frame(container, style="TFrame")
        buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))

        self.btn_add = ttk.Button(
            buttons, text=f"➕  {self.app.t('Add category')}", command=self.add_category,
            style="Primary.TButton",
        )
        self.btn_add.pack(side="left", padx=(0, 6))

        self.btn_edit = ttk.Button(
            buttons, text=f"✏  {self.app.t('Edit display name')}", command=self.edit_display_name,
        )
        self.btn_edit.pack(side="left", padx=(0, 6))

        self.btn_toggle = ttk.Button(
            buttons, text=f"⚡  {self.app.t('Enable / disable')}", command=self.toggle_active,
        )
        self.btn_toggle.pack(side="left", padx=(0, 6))

        self.btn_delete = ttk.Button(
            buttons, text=f"🗑  {self.app.t('Delete category')}", command=self.delete_category,
        )
        self.btn_delete.pack(side="left", padx=(0, 6))

        self.btn_restore = ttk.Button(
            buttons, text=f"🔄  {self.app.t('Restore default category')}", command=self.restore_defaults,
        )
        self.btn_restore.pack(side="left", padx=(0, 6))

        ttk.Button(buttons, text=self.app.t("Close"), command=self.close).pack(side="right")

    def _sync_buttons(self):
        selected = bool(self.tree.selection())
        self.btn_edit.state(["!disabled"] if selected else ["disabled"])
        self.btn_toggle.state(["!disabled"] if selected else ["disabled"])
        self.btn_delete.state(["!disabled"] if selected else ["disabled"])

    def set_usage(self, usage_rows: list[dict]):
        self.usage_data = {r["id"]: r for r in usage_rows}
        self.refresh()

    def refresh_usage(self):
        self.app._request("category_list_usage")

    def _filtered_categories(self) -> list[dict]:
        direction_filter = source_text(self.filter_direction.get(), ("All", "Expense", "Income"))
        search = self.search_text.get().strip().lower()

        filtered = []
        for cat in self.app.categories:
            cat_dir = cat.get("direction", "expense")
            if direction_filter == "Expense" and cat_dir != "expense":
                continue
            if direction_filter == "Income" and cat_dir != "income":
                continue

            display_name = self.app.category_display_name(cat)
            canonical = cat.get("name", "")
            if search:
                if search not in display_name.lower() and search not in canonical.lower():
                    continue
            filtered.append(cat)
        return filtered

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        filtered = self._filtered_categories()
        tokens = get_current_theme()

        for idx, cat in enumerate(filtered):
            cat_id = cat["id"]
            direction = self.app.t("Expense" if cat.get("direction") == "expense" else "Income")
            display_name = self.app.category_display_name(cat)
            canonical = cat.get("name", "")
            is_disabled = cat_id in self.app.disabled_categories
            status = self.app.t("Disabled" if is_disabled else "Active")

            usage_info = self.usage_data.get(cat_id, {})
            tx_count = usage_info.get("transaction_count", 0)
            total_usage = usage_info.get("total_usage", tx_count)
            if total_usage > 0:
                usage_text = translate_format("{count} transactions", count=tx_count) if tx_count else f"Rules ({total_usage})"
            else:
                usage_text = self.app.t("Not used")

            row_tag = "odd" if idx % 2 else "even"
            tags = (row_tag, "disabled_row") if is_disabled else (row_tag,)

            self.tree.insert(
                "", "end", iid=str(cat_id),
                values=(cat_id, direction, display_name, canonical, status, usage_text),
                tags=tags,
            )

        self.count_label.configure(
            text=translate_format("{count} categories", count=len(filtered))
        )
        self._sync_buttons()

    def _selected_category(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        cat_id = int(sel[0])
        return next((c for c in self.app.categories if c["id"] == cat_id), None)

    def add_category(self):
        """Open add category modal with direction, preset or custom name."""
        tokens = get_current_theme()
        dlg = tk.Toplevel(self.dialog)
        dlg.title(self.app.t("Add category"))
        dlg.geometry("500x340")
        dlg.transient(self.dialog)
        dlg.resizable(False, False)
        dlg.configure(background=tokens.bg)

        frame = ttk.Frame(dlg, padding=(18, 16), style="TFrame")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=self.app.t("Direction") + ":", style="TLabel").pack(anchor="w", pady=(0, 4))
        dir_var = tk.StringVar(dlg, self.app.t("Expense"))
        dir_combo = ttk.Combobox(
            frame, textvariable=dir_var, values=(self.app.t("Expense"), self.app.t("Income")),
            state="readonly", width=25,
        )
        dir_combo.pack(fill="x", pady=(0, 12))

        source_mode = tk.StringVar(dlg, "preset")
        mode_frame = ttk.Frame(frame, style="TFrame")
        mode_frame.pack(fill="x", pady=(0, 8))

        rb_preset = ttk.Radiobutton(
            mode_frame, text=self.app.t("Select from default presets"),
            variable=source_mode, value="preset",
        )
        rb_preset.pack(anchor="w", pady=(0, 4))

        preset_var = tk.StringVar(dlg)
        preset_combo = ttk.Combobox(frame, textvariable=preset_var, state="readonly")
        preset_combo.pack(fill="x", pady=(0, 12))

        rb_custom = ttk.Radiobutton(
            frame, text=self.app.t("Or enter custom category name"),
            variable=source_mode, value="custom",
        )
        rb_custom.pack(anchor="w", pady=(0, 4))

        custom_var = tk.StringVar(dlg)
        custom_entry = ttk.Entry(frame, textvariable=custom_var)
        custom_entry.pack(fill="x", pady=(0, 16))

        def update_presets(_event=None):
            is_expense = source_text(dir_var.get(), ("Expense", "Income")) == "Expense"
            defaults = DEFAULT_EXPENSE_CATEGORIES if is_expense else DEFAULT_INCOME_CATEGORIES
            existing_names = {c["name"].lower() for c in self.app.categories}
            available = [
                mn for mn, en in defaults
                if mn.lower() not in existing_names and en.lower() not in existing_names
            ]
            preset_combo.configure(values=available)
            if available:
                preset_var.set(available[0])
            else:
                preset_var.set("")
                source_mode.set("custom")

        def on_mode_change(*_):
            if source_mode.get() == "preset":
                preset_combo.state(["!disabled"])
                custom_entry.state(["disabled"])
            else:
                preset_combo.state(["disabled"])
                custom_entry.state(["!disabled"])
                custom_entry.focus()

        source_mode.trace_add("write", on_mode_change)
        dir_combo.bind("<<ComboboxSelected>>", update_presets)
        update_presets()
        on_mode_change()

        def do_save():
            is_expense = source_text(dir_var.get(), ("Expense", "Income")) == "Expense"
            direction = "expense" if is_expense else "income"

            if source_mode.get() == "preset":
                selected_preset = preset_var.get().strip()
                if not selected_preset:
                    messagebox.showerror(self.app.t("Add category"), self.app.t("Choose a category."), parent=dlg)
                    return
                # Determine canonical key for preset
                defaults = DEFAULT_EXPENSE_CATEGORIES if is_expense else DEFAULT_INCOME_CATEGORIES
                canonical = next((en for mn, en in defaults if mn == selected_preset), selected_preset)
                name = canonical
            else:
                name = custom_var.get().strip()
                if not name:
                    messagebox.showerror(self.app.t("Add category"), self.app.t("Category name cannot be empty."), parent=dlg)
                    return

            self.app._request("category_add", name=name, direction=direction)
            dlg.destroy()

        btn_row = ttk.Frame(frame, style="TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text=self.app.t("Cancel"), command=dlg.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text=f"💾  {self.app.t('Save')}", command=do_save, style="Primary.TButton").pack(side="right")

        localize_widget_tree(dlg)
        dlg.grab_set()

    def edit_display_name(self):
        """Edit custom display name override for the selected category."""
        category = self._selected_category()
        if category is None:
            messagebox.showwarning(self.app.t("Category management"), self.app.t("Select a category first."), parent=self.dialog)
            return

        cat_id = category["id"]
        canonical = category.get("name", "")
        current_display = self.app.category_display_name(category)

        tokens = get_current_theme()
        dlg = tk.Toplevel(self.dialog)
        dlg.title(self.app.t("Edit display name"))
        dlg.geometry("480x240")
        dlg.transient(self.dialog)
        dlg.resizable(False, False)
        dlg.configure(background=tokens.bg)

        frame = ttk.Frame(dlg, padding=(18, 16), style="TFrame")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=f"{self.app.t('Canonical key')}: {canonical}", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text=self.app.t("Display name") + ":", style="TLabel").pack(anchor="w", pady=(0, 4))

        name_var = tk.StringVar(dlg, current_display)
        entry = ttk.Entry(frame, textvariable=name_var)
        entry.pack(fill="x", pady=(0, 16))
        entry.focus()

        def do_save():
            new_name = name_var.get().strip()
            if not new_name:
                self.app.custom_category_names.pop(cat_id, None)
            else:
                self.app.custom_category_names[cat_id] = new_name
            save_category_settings(self.app.data_dir, self.app.disabled_categories, self.app.custom_category_names)
            self.refresh()
            self.app._categories_changed()
            dlg.destroy()

        def do_reset():
            self.app.custom_category_names.pop(cat_id, None)
            save_category_settings(self.app.data_dir, self.app.disabled_categories, self.app.custom_category_names)
            self.refresh()
            self.app._categories_changed()
            dlg.destroy()

        btn_row = ttk.Frame(frame, style="TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text=self.app.t("Cancel"), command=dlg.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text=self.app.t("Reset to default"), command=do_reset).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text=f"💾  {self.app.t('Save')}", command=do_save, style="Primary.TButton").pack(side="right")

        localize_widget_tree(dlg)
        dlg.grab_set()

    def toggle_active(self):
        """Toggle active/disabled status for the selected category."""
        category = self._selected_category()
        if category is None:
            messagebox.showwarning(self.app.t("Category management"), self.app.t("Select a category first."), parent=self.dialog)
            return

        cat_id = category["id"]
        if cat_id in self.app.disabled_categories:
            self.app.disabled_categories.remove(cat_id)
        else:
            self.app.disabled_categories.add(cat_id)

        save_category_settings(self.app.data_dir, self.app.disabled_categories, self.app.custom_category_names)
        self.refresh()
        self.app._categories_changed()

    def delete_category(self):
        """Delete category if unused; block if used in transactions or rules."""
        category = self._selected_category()
        if category is None:
            messagebox.showwarning(self.app.t("Category management"), self.app.t("Select a category first."), parent=self.dialog)
            return

        cat_id = category["id"]
        usage_info = self.usage_data.get(cat_id, {})
        total_usage = usage_info.get("total_usage", 0)

        if total_usage > 0:
            messagebox.showwarning(
                self.app.t("Category management"),
                self.app.t("Cannot delete category because it is already used. Disable it instead."),
                parent=self.dialog,
            )
            return

        confirmed = messagebox.askyesno(
            self.app.t("Delete category"),
            translate_format(
                "Delete category '{name}'? This action cannot be undone.",
                name=self.app.category_display_name(category),
            ),
            parent=self.dialog,
            default="no",
        )
        if confirmed:
            self.app._request("category_delete", category_id=cat_id)

    def restore_defaults(self):
        """Restore all 27 default categories (19 expense, 8 income), enabling any disabled ones."""
        # 1. Enable all default categories that were disabled
        for mn, en in DEFAULT_EXPENSE_CATEGORIES + DEFAULT_INCOME_CATEGORIES:
            for cat in self.app.categories:
                if cat["name"] in (mn, en):
                    self.app.disabled_categories.discard(cat["id"])

        save_category_settings(self.app.data_dir, self.app.disabled_categories, self.app.custom_category_names)

        # 2. Add any missing default categories to DB
        existing_names = {c["name"].lower() for c in self.app.categories}
        for mn, en in DEFAULT_EXPENSE_CATEGORIES:
            if mn.lower() not in existing_names and en.lower() not in existing_names:
                self.app._request("category_add", name=en, direction="expense")
                existing_names.add(en.lower())

        for mn, en in DEFAULT_INCOME_CATEGORIES:
            if mn.lower() not in existing_names and en.lower() not in existing_names:
                self.app._request("category_add", name=en, direction="income")
                existing_names.add(en.lower())

        self.refresh()
        self.app._categories_changed()
        messagebox.showinfo(
            self.app.t("Category management"),
            self.app.t("Default categories restored."),
            parent=self.dialog,
        )

    def close(self):
        self.app.categories_dialog = None
        self.dialog.destroy()
