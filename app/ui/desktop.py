"""Tk views. All widget access is on the main thread; services run in worker.py."""

import tkinter as tk
from pathlib import Path
from queue import Empty
from tkinter import filedialog, messagebox, ttk

from app.ui.presentation import (
    archive_confirmation_details, browser_filters, format_mnt, issue_location, review_status,
    transaction_row_values,
)
from app.ui.view_models import filtered_totals_text
from app.ui.worker import FinanceWorker
from app.ui.review import ReviewViews, selected_items
from app.ui.dashboard import DashboardView
from app.ui.mapping import MappingView
from app.ui.budget import BudgetView
from app.ui.categories_dialog import CategoriesDialog
from app.reporting import format_money
from app.db import SCHEMA_VERSION
from app.local_actions import APP_VERSION, open_data_folder
from app.ui.i18n import (
    LANGUAGE_NAMES,
    ToolTip,
    get_category_display_name,
    load_category_settings,
    load_language,
    load_theme,
    localize_widget_tree,
    resolve_category_by_display_name,
    save_category_settings,
    save_language,
    save_theme,
    set_language,
    source_text,
    translate,
    translate_format,
)
from app.ui.messages import import_preview_counts, import_result, page_caption
from app.ui.theme import apply_theme, get_current_theme


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
        tokens = get_current_theme()
        self.tree.tag_configure("odd", background=tokens.tree_alt)
        self.tree.tag_configure("even", background=tokens.tree_bg)
        self.empty_label = ttk.Label(area, text=translate("Nothing to show yet."), style="EmptyState.TLabel")
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

    def apply_theme(self, tokens):
        self.tree.tag_configure("odd", background=tokens.tree_alt)
        self.tree.tag_configure("even", background=tokens.tree_bg)

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
        # Row striping and the empty-state message exist only on fully built tables.
        decorated = getattr(self, "empty_label", None) is not None
        for index in range(start, min(start + self.size, len(self.items))):
            tag = "odd" if (index - start) % 2 else "even"
            if decorated:
                self.tree.insert("", "end", iid=str(index), values=self.values(self.items[index]),
                                 tags=(tag,))
            else:
                self.tree.insert("", "end", iid=str(index), values=self.values(self.items[index]))
        if decorated:
            if self.items:
                self.empty_label.place_forget()
            else:
                self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self.previous.state(["!disabled"] if self.page else ["disabled"])
        self.next.state(["!disabled"] if start + self.size < len(self.items) else ["disabled"])
        pages = max(1, (len(self.items) + self.size - 1) // self.size)
        self.caption.configure(text=page_caption(self.page + 1, pages, len(self.items)))


class ArchiveConfirmDialog:
    """Confirmation modal before archiving/soft-deleting selected transactions."""

    def __init__(self, parent, app, transactions: list[dict], on_confirm):
        self.app = app
        self.on_confirm = on_confirm
        self.dialog = tk.Toplevel(parent)
        self.dialog.transient(parent)
        self.dialog.resizable(False, False)
        self.dialog.title(app.t("Archive transactions"))

        frame = ttk.Frame(self.dialog, padding=18)
        frame.pack(fill="both", expand=True)

        # Header / Title
        ttk.Label(frame, text=f"🗑  {app.t('Archive transactions')}", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        # Warning banner
        warn_frame = ttk.Frame(frame, style="Card.TFrame", padding=(10, 8))
        warn_frame.pack(fill="x", pady=(0, 12))
        warn_text = app.t("These transactions will be removed from normal reports, dashboard totals, and classification.")
        ttk.Label(warn_frame, text=f"⚠️ {warn_text}", wraplength=420, style="CardMuted.TLabel").pack(anchor="w")

        # Details
        info_frame = ttk.Frame(frame)
        info_frame.pack(fill="x", pady=(0, 12))
        info_frame.columnconfigure(1, weight=1)

        # Count
        ttk.Label(info_frame, text=app.t("Number of selected transactions") + ":", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=2)
        count, currency_totals, date_range_str = archive_confirmation_details(transactions)
        ttk.Label(info_frame, text=str(count), font=("Segoe UI", 9)).grid(row=0, column=1, sticky="w", padx=8, pady=2)

        # Date range
        ttk.Label(info_frame, text=app.t("Date range") + ":", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, text=date_range_str, font=("Segoe UI", 9)).grid(row=1, column=1, sticky="w", padx=8, pady=2)

        # Total amount grouped by currency
        ttk.Label(info_frame, text=app.t("Total amount by currency") + ":", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="nw", pady=2)
        amounts_box = ttk.Frame(info_frame)
        amounts_box.grid(row=2, column=1, sticky="w", padx=8, pady=2)
        for cur, total_minor in sorted(currency_totals.items()):
            formatted = format_money(total_minor, cur)
            ttk.Label(amounts_box, text=formatted, font=("Segoe UI", 9, "bold")).pack(anchor="w")

        # Action buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(12, 0))

        archive_btn = ttk.Button(btn_frame, text=app.t("Archive"), style="Primary.TButton", command=self._confirm)
        archive_btn.pack(side="right", padx=(6, 0))

        cancel_btn = ttk.Button(btn_frame, text=app.t("Cancel"), command=self.dialog.destroy)
        cancel_btn.pack(side="right")

        localize_widget_tree(self.dialog)
        self.dialog.grab_set()

    def _confirm(self):
        self.dialog.destroy()
        self.on_confirm()


class DesktopApp:
    def __init__(self, window: tk.Tk, data_dir: Path, *, worker_factory=FinanceWorker):
        self.window = window
        self.busy, self.ready, self.closing = True, False, False
        self.preview, self.decisions = None, {}
        self.accounts, self.categories = [], []
        self.browser_page, self.browser_total = 0, 0
        self.active_filters = {}
        self.data_dir = Path(data_dir).resolve()
        self.language = load_language(self.data_dir)
        self.theme = load_theme(self.data_dir)
        set_language(self.language)
        self.t = translate
        self.account_dialog = None
        self.categories_dialog = None
        category_settings = load_category_settings(self.data_dir)
        self.disabled_categories = category_settings["disabled_ids"]
        self.custom_category_names = category_settings["display_names"]
        self.browser_categories = []
        self.review_views = None
        self.mapping_view = None
        self.dashboard, self.dashboard_dirty = None, True
        self.transaction_refresh_queue = []
        self.file_path = tk.StringVar(window)
        self.account_text = tk.StringVar(window)
        self.account_confirmed = tk.BooleanVar(window, False)
        self.status = tk.StringVar(window, self.t("Opening local database…"))
        self.preview_counts = tk.StringVar(window, self.t("Select an account and an XLSX statement to preview."))
        self.summary = tk.StringVar(window)
        self.review_hint = tk.StringVar(window)
        self.date_from, self.date_to, self.search = (tk.StringVar(window) for _ in range(3))
        self.category_text = tk.StringVar(window, self.t("All categories"))
        self.direction_text = tk.StringVar(window, self.t("All directions"))
        self.currency_text = tk.StringVar(window, self.t("All currencies"))
        self.browser_account_text = tk.StringVar(window, self.t("All accounts"))
        self.browser_bank_text = tk.StringVar(window, self.t("All banks"))
        self.browser_archive_text = tk.StringVar(window, self.t("Active"))
        self.review_only = tk.BooleanVar(window, False)
        self.page_size = tk.StringVar(window, "50")
        self.browser_caption = tk.StringVar(window, self.t("No transactions loaded"))
        self.filtered_totals = tk.StringVar(window, "")
        self.browser_report = None
        self._build(data_dir)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.report_callback_exception = self._callback_error
        self.worker = worker_factory(data_dir / "finance.sqlite3")
        self._sync_controls()
        self._poll_id = window.after(40, self._poll)

    def _build(self, data_dir):
        root = self.window
        root.title(self.t("Personal Finance Tool"))
        root.geometry("1280x720")
        root.minsize(1024, 640)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        apply_theme(root, self.theme)
        top = ttk.Frame(root, padding=(18, 10), style="Topbar.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Personal Finance", style="Brand.TLabel").pack(side="left")
        ttk.Label(top, text="Local · Offline", style="Tag.TLabel").pack(side="left", padx=(12, 0))
        self.settings_button = ttk.Button(top, text="⚙  " + self.t("Settings"), command=self._settings)
        self.settings_button.pack(side="right", padx=(5, 0))
        self.backup_button = ttk.Button(top, text="📦  " + self.t("Backup…"), command=self._backup, style="Primary.TButton")
        self.backup_button.pack(side="right", padx=12)
        self.local_buttons = []
        for label, callback, icon in (("Restore…", self._restore, "📥"), ("Export CSV…", self._export_csv, "📤"),
                                      ("Help / About", self._about, "ℹ"), ("Open data folder", self._open_data_folder, "📁")):
            button = ttk.Button(top, text=f"{icon}  {self.t(label)}", command=callback)
            button.pack(side="right", padx=3)
            self.local_buttons.append(button)
        shell = ttk.Frame(root)
        shell.grid(row=1, column=0, sticky="nsew")
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)
        self.sidebar = ttk.Frame(shell, style="Sidebar.TFrame", padding=(10, 18))
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.configure(width=232)
        self.sidebar.grid_propagate(False)
        ttk.Label(self.sidebar, text="Personal Finance", style="SidebarTitle.TLabel",
                  wraplength=185).pack(anchor="w", padx=8, pady=(2, 18))
        self.nav_buttons, self.nav_tabs = [], []
        self.content = ttk.Frame(shell, padding=(22, 14, 22, 10))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)
        page_header = ttk.Frame(self.content)
        page_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.page_heading = tk.StringVar(root, "")
        self.page_explanation = tk.StringVar(root, "")
        ttk.Label(page_header, textvariable=self.page_heading, style="PageTitle.TLabel").pack(anchor="w")
        self.page_description = ttk.Label(page_header, textvariable=self.page_explanation,
                                          style="PageDescription.TLabel", wraplength=940)
        self.page_description.pack(anchor="w", pady=(2, 0))
        self.content.bind("<Configure>", self._resize_content, add="+")
        self.tabs = ttk.Notebook(self.content, style="Hidden.TNotebook")
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.import_tab = ttk.Frame(self.tabs, padding=10)
        self.transactions_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.import_tab, text="Import")
        self.tabs.add(self.transactions_tab, text="Transactions")
        self._build_import()
        self._build_browser()
        self.review_views = ReviewViews(self, PagedTable)
        self.mapping_view = MappingView(self, PagedTable)
        self.budget_view = BudgetView(self, PagedTable)
        self.dashboard = DashboardView(self, PagedTable)
        self.page_details = {
            str(self.dashboard.tab): ("Dashboard", "At-a-glance totals by currency; net is not an account balance."),
            str(self.transactions_tab): ("Transactions", "Search, filter, inspect and edit imported transactions."),
            str(self.import_tab): ("Import statement", "Preview an XLSX statement and confirm every import decision."),
            str(self.review_views.review_tab): ("Review", "Classify unknown transactions deliberately; no category is assigned automatically."),
            str(self.review_views.rules_tab): ("Rules", "Manage exact merchant rules for future imports."),
            str(self.mapping_view.tab): ("Mapping Table", "Classify transactions with ordered, editable mapping rules."),
            str(self.budget_view.tab): ("Budget", "Monthly budget management by category and currency."),
        }
        pages = (
            (self.dashboard.tab, "Dashboard", "Review income, expenses, net cash flow and unclassified items.", "📊"),
            (self.transactions_tab, "Transactions", "Search, filter, inspect and edit imported transactions.", "📋"),
            (self.import_tab, "Import statement", "Preview an XLSX statement and confirm every import decision.", "📥"),
            (self.review_views.review_tab, "Review", "Classify unknown transactions deliberately; no category is assigned automatically.", "⚖"),
            (self.review_views.rules_tab, "Rules", "Manage exact merchant rules for future imports.", "⚡"),
            (self.mapping_view.tab, "Mapping Table", "Classify transactions with ordered, editable mapping rules.", "🏷"),
            (self.budget_view.tab, "Budget", "Monthly budget management by category and currency.", "💰"),
        )
        for tab, label, description, icon in pages:
            if tab is self.mapping_view.tab:
                callback = self._select_mapping
            elif tab is self.budget_view.tab:
                callback = self._select_budget
            else:
                callback = lambda page=tab: self._select_page(page)
            button = ttk.Button(self.sidebar, text=f"{icon}  {self.t(label)}", style="Sidebar.TButton", command=callback)
            button.pack(fill="x", pady=2)
            self.nav_buttons.append(button)
            self.nav_tabs.append(str(tab))
            button.bind("<Enter>", lambda _event, text=description: self.status.set(self.t(text)))
            button.bind("<Leave>", lambda _event: self.status.set(self.t("Ready")))
        self.tabs.bind("<<NotebookTabChanged>>", self._page_changed)
        for number, (tab, *_rest) in enumerate(pages[:9], start=1):
            if tab is self.mapping_view.tab:
                cb = lambda _event: self._select_mapping()
            elif tab is self.budget_view.tab:
                cb = lambda _event: self._select_budget()
            else:
                cb = lambda _event, page=tab: self._select_page(page)
            root.bind(f"<Control-Key-{number}>", cb)
        self._select_page(self.dashboard.tab)
        footer = ttk.Frame(root, padding=(22, 8), style="Footer.TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(2, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=850, style="FooterStatus.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.error_text = None
        self.status.trace_add("write", self._status_changed)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=140)
        self.progress.grid(row=0, column=1, sticky="e")
        ttk.Label(footer, text=f"App {APP_VERSION} · Database v{SCHEMA_VERSION}", style="Footer.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(footer, text="Active data location:", style="Footer.TLabel").grid(row=1, column=1, sticky="e", padx=(8, 4), pady=(3, 0))
        ttk.Label(footer, text=str(data_dir), wraplength=650, anchor="e", style="Footer.TLabel").grid(
            row=1, column=2, sticky="ew", pady=(3, 0))
        localize_widget_tree(root)

    def _select_page(self, tab):
        self.tabs.select(tab)
        self._page_changed()
        if (self.review_views is not None
                and tab in (self.review_views.review_tab, self.review_views.rules_tab)
                and self.ready and not self.busy and self.preview is None
                and self.review_views.pending is None and self.review_views.editor is None):
            self._request("review_load")

    def _select_mapping(self):
        self._select_page(self.mapping_view.tab)
        self.mapping_view.load()

    def _select_budget(self):
        self._select_page(self.budget_view.tab)
        self.budget_view.load()

    def _page_changed(self, _event=None):
        tab = self.tabs.select()
        label, description = self.page_details.get(tab, ("Personal Finance", ""))
        self.page_heading.set(self.t(label))
        self.page_explanation.set(self.t(description))
        for button, nav_tab in zip(self.nav_buttons, self.nav_tabs):
            active = nav_tab == str(tab)
            button.configure(style="SidebarActive.TButton" if active else "Sidebar.TButton")
            button.state(["selected"] if active else ["!selected"])

    def _resize_content(self, event):
        self.page_description.configure(wraplength=max(360, event.width - 60))

    def _status_changed(self, *_):
        if hasattr(self, "status_label"):
            failed = self.error_text is not None and self.status.get() == self.error_text
            self.status_label.configure(style="FooterError.TLabel" if failed else "FooterStatus.TLabel")

    def apply_theme_mode(self, theme: str):
        self.theme = theme
        try:
            save_theme(self.data_dir, theme)
        except OSError:
            pass
        apply_theme(self.window, theme)
        tokens = get_current_theme()
        self.window.configure(background=tokens.bg)
        if hasattr(self, "sidebar"):
            self.sidebar.configure(style="Sidebar.TFrame")
        tables = [
            getattr(self, "transactions", None),
            getattr(self, "preview_table", None),
            getattr(self, "candidates", None),
            getattr(self, "issues", None),
        ]
        if self.review_views is not None:
            tables.extend([
                getattr(self.review_views, "groups", None),
                getattr(self.review_views, "rows", None),
                getattr(self.review_views, "rules", None),
            ])
        if self.mapping_view is not None:
            tables.append(getattr(self.mapping_view, "table", None))
        if self.budget_view is not None:
            tables.append(getattr(self.budget_view, "table", None))
        if self.dashboard is not None:
            tables.append(getattr(self.dashboard, "totals", None))
            tables.extend(self.dashboard.breakdowns.values())
            self.dashboard.set_theme(tokens)
        for tbl in tables:
            if tbl is not None and hasattr(tbl, "apply_theme"):
                tbl.apply_theme(tokens)
            elif tbl is not None and hasattr(tbl, "tree"):
                tbl.tree.tag_configure("odd", background=tokens.tree_alt)
                tbl.tree.tag_configure("even", background=tokens.tree_bg)
        self._page_changed()

    def category_display_name(self, category: dict | int | str | None) -> str:
        return get_category_display_name(
            category, categories=self.categories, language=self.language,
            custom_names=self.custom_category_names,
        )

    def resolve_category_id(self, display_text: str) -> int | None:
        cat = resolve_category_by_display_name(
            display_text, categories=self.categories, language=self.language,
            custom_names=self.custom_category_names,
        )
        return cat["id"] if cat else None

    def active_categories(self, direction: str | None = None) -> list[dict]:
        cats = [c for c in self.categories if c["id"] not in self.disabled_categories]
        if direction:
            cats = [c for c in cats if c.get("direction") == direction]
        return cats

    def _update_browser_category_choices(self):
        direction_src = source_text(self.direction_text.get(), ("All directions", "Debit", "Credit", "Zero"))
        cat_direction = {"Debit": "expense", "Credit": "income"}.get(direction_src)
        active = self.active_categories(direction=cat_direction)
        self.browser_categories = active
        values = [self.t("All categories")] + [self.category_display_name(c) for c in active]
        if hasattr(self, "category_box"):
            self.category_box.configure(values=values)
            current = self.category_text.get()
            if current not in values and current != self.t("All categories"):
                cat_id = self.resolve_category_id(current)
                if cat_id:
                    matched = next((c for c in active if c["id"] == cat_id), None)
                    if matched:
                        self.category_text.set(self.category_display_name(matched))
                    else:
                        self.category_text.set(self.t("All categories"))
                else:
                    self.category_text.set(self.t("All categories"))

    def _categories_changed(self):
        self._update_browser_category_choices()
        if self.review_views is not None:
            self.review_views._categories()
            if hasattr(self.review_views, "rules"):
                self.review_views.rule_selected()
        if self.mapping_view is not None:
            self.mapping_view._update_categories()
            self.mapping_view.load()
        if hasattr(self, "budget_view") and self.budget_view is not None:
            self.budget_view.load()
        if hasattr(self, "transactions") and hasattr(self, "browser_page"):
            categories = {c["id"]: self.category_display_name(c) for c in self.categories}
            if self.transactions.items:
                self.transactions.render()
        if self.categories_dialog is not None:
            self.categories_dialog.refresh()

    def _open_categories_dialog(self, parent=None):
        if self.categories_dialog is None:
            self.categories_dialog = CategoriesDialog(self, parent=parent)
        else:
            self.categories_dialog.dialog.lift()

    def _settings(self):
        tokens = get_current_theme()
        dialog = tk.Toplevel(self.window)
        dialog.title(self.t("Settings"))
        dialog.transient(self.window)
        dialog.resizable(False, False)
        dialog.configure(background=tokens.bg)

        body = ttk.Frame(dialog, padding=(18, 16), style="TFrame")
        body.pack(fill="both", expand=True)

        title_frame = ttk.Frame(body, style="TFrame")
        title_frame.pack(fill="x", pady=(0, 14))
        ttk.Label(title_frame, text=f"⚙  {self.t('Settings')}", font=(tokens.font_family, 14, "bold"),
                  style="TLabel").pack(side="left")

        # 1. Language Card (🌐 Хэл)
        lang_card = ttk.LabelFrame(body, text=f"  🌐  {self.t('Language')}  ", padding=(14, 10), style="TLabelframe")
        lang_card.pack(fill="x", pady=(0, 10))
        lang_hint = "Програмын үндсэн хэл нь Монгол хэл байна. Хүсвэл англи хэл рүү шилжих боломжтой."
        ttk.Label(lang_card, text=lang_hint if self.language == "mn" else "Select the interface display language.",
                  wraplength=460, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        lang_row = ttk.Frame(lang_card, style="TFrame")
        lang_row.pack(fill="x")
        ttk.Label(lang_row, text=self.t("Language") + ":", style="TLabel").pack(side="left", padx=(0, 10))
        current_lang = tk.StringVar(dialog, self.t(LANGUAGE_NAMES[self.language]))
        lang_choices = tuple(self.t(LANGUAGE_NAMES[code]) for code in ("mn", "en"))
        lang_combo = ttk.Combobox(lang_row, textvariable=current_lang, values=lang_choices, state="readonly", width=18)
        lang_combo.pack(side="left")
        ToolTip(lang_combo, self.t("Select application display language"))

        # 2. Theme Card (🎨 Системийн өнгө)
        theme_card = ttk.LabelFrame(body, text=f"  🎨  {self.t('Theme')}  ", padding=(14, 10), style="TLabelframe")
        theme_card.pack(fill="x", pady=(0, 10))
        theme_hint = "Интерфэйсийн өнгийн горимыг сонгоно уу. Өөрчлөлт шууд дэлгэцэнд хэрэгжинэ."
        ttk.Label(theme_card, text=theme_hint if self.language == "mn" else "Choose dark or light visual mode. Updates immediately.",
                  wraplength=460, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        theme_row = ttk.Frame(theme_card, style="TFrame")
        theme_row.pack(fill="x")
        ttk.Label(theme_row, text=self.t("Theme") + ":", style="TLabel").pack(side="left", padx=(0, 10))

        theme_choices_map = {
            self.t("Dark mode"): "dark",
            self.t("Light mode"): "light",
            "Бараан горим": "dark",
            "Гэрэлтэй горим": "light",
            "Dark mode": "dark",
            "Light mode": "light",
        }
        active_display_theme = self.t("Dark mode") if self.theme == "dark" else self.t("Light mode")
        current_theme_var = tk.StringVar(dialog, active_display_theme)
        theme_combo_values = (self.t("Dark mode"), self.t("Light mode"))
        theme_combo = ttk.Combobox(theme_row, textvariable=current_theme_var, values=theme_combo_values,
                                   state="readonly", width=18)
        theme_combo.pack(side="left")
        ToolTip(theme_combo, self.t("Select theme mode"))

        def on_theme_change(_event=None):
            selected_mode = theme_choices_map.get(current_theme_var.get(), "dark")
            self.apply_theme_mode(selected_mode)
            new_tokens = get_current_theme()
            dialog.configure(background=new_tokens.bg)

        theme_combo.bind("<<ComboboxSelected>>", on_theme_change)

        # Category Management Card (🏷 Ангиллын удирдлага)
        cat_card = ttk.LabelFrame(body, text=f"  🏷  {self.t('Category management')}  ", padding=(14, 10), style="TLabelframe")
        cat_card.pack(fill="x", pady=(0, 10))
        cat_hint = "Гүйлгээний ангиллуудыг нэмэх, засах, идэвхгүй болгох эсвэл үндсэн тохиргоог сэргээх."
        ttk.Label(cat_card, text=cat_hint if self.language == "mn" else "Manage transaction categories, custom display names, and defaults.",
                  wraplength=460, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        cat_row = ttk.Frame(cat_card, style="TFrame")
        cat_row.pack(fill="x")
        ttk.Label(cat_row, text=f"{len(self.active_categories())} {self.t('categories')}", style="Muted.TLabel").pack(side="left")
        ttk.Button(cat_row, text=f"🏷  {self.t('Manage categories…')}", command=lambda: self._open_categories_dialog(parent=dialog)).pack(side="right")

        # 3. Data Location Card (📁 Өгөгдлийн байрлал)
        loc_card = ttk.LabelFrame(body, text=f"  📁  {self.t('Data location')}  ", padding=(14, 10), style="TLabelframe")
        loc_card.pack(fill="x", pady=(0, 10))
        loc_hint = "Санхүүгийн мэдээлэл болон өгөгдлийн сан хадгалагдаж буй үндсэн хавтас."
        ttk.Label(loc_card, text=loc_hint if self.language == "mn" else "Directory where your financial database is stored locally.",
                  wraplength=460, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        loc_row = ttk.Frame(loc_card, style="TFrame")
        loc_row.pack(fill="x")
        ttk.Label(loc_row, text=str(self.data_dir), wraplength=340, font=(tokens.font_family, 9), style="TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(loc_row, text=f"📁  {self.t('Open data folder')}", command=self._open_data_folder).pack(side="right", padx=(8, 0))

        # 4. Backup & Privacy Card (🔒 Нөөцлөлт ба нууцлал)
        priv_card = ttk.LabelFrame(body, text=f"  🔒  {self.t('Backup & privacy')}  ", padding=(14, 10), style="TLabelframe")
        priv_card.pack(fill="x", pady=(0, 14))
        priv_hint = "Бүх өгөгдөл таны төхөөрөмж дээр хадгалагдах бөгөөд интернэт рүү дамжуулагдахгүй. Тогтмол нөөцлөлт хийнэ үү."
        ttk.Label(priv_card, text=priv_hint if self.language == "mn" else "All data stays local and private on your machine. Keep regular backups.",
                  wraplength=460, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        priv_row = ttk.Frame(priv_card, style="TFrame")
        priv_row.pack(fill="x")
        ttk.Label(priv_row, text=f"App {APP_VERSION} · Database v{SCHEMA_VERSION}", style="Muted.TLabel").pack(side="left")
        ttk.Button(priv_row, text=f"📦  {self.t('Backup…')}", command=self._backup, style="Primary.TButton").pack(side="right")

        # Dialog Action Buttons
        btn_row = ttk.Frame(body, style="TFrame")
        btn_row.pack(fill="x", pady=(4, 0))

        def save():
            selected_mode = theme_choices_map.get(current_theme_var.get(), "dark")
            self.apply_theme_mode(selected_mode)
            chosen_lang = "mn" if current_lang.get() in (self.t(LANGUAGE_NAMES["mn"]), "Монгол") else "en"
            lang_changed = chosen_lang != self.language
            try:
                save_language(self.data_dir, chosen_lang)
                save_theme(self.data_dir, selected_mode)
            except OSError as error:
                self._error(f"Cannot save settings: {error}")
                return
            self.language = chosen_lang
            if lang_changed:
                messagebox.showinfo(self.t("Settings"),
                                    self.t("Language saved. Close and reopen the application to apply it."),
                                    parent=dialog)
            dialog.destroy()

        close_btn = ttk.Button(btn_row, text=self.t("Close"), command=dialog.destroy)
        close_btn.pack(side="right", padx=(8, 0))
        save_btn = ttk.Button(btn_row, text=f"💾  {self.t('Save')}", command=save, style="Primary.TButton")
        save_btn.pack(side="right")

        dialog.grab_set()

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
        actions.grid(row=3, column=0, sticky="ew", pady=8)
        self.preview_button = ttk.Button(actions, text="👁  " + self.t("Preview import"), command=self._preview, style="Primary.TButton")
        self.preview_button.pack(side="left")
        self.commit_button = ttk.Button(actions, text="💾  " + self.t("Commit import"), command=self._commit, style="Primary.TButton")
        self.commit_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="✕  " + self.t("Cancel preview"), command=self._cancel)
        self.cancel_button.pack(side="left")
        ttk.Label(tab, textvariable=self.preview_counts, wraplength=900).grid(row=4, column=0, sticky="w", pady=5)
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
            ("status", "Status", 90), ("decision", "Decision", 90), ("rule", "Classification rule", 180),
            ("sheet", "Worksheet", 120), ("row", "Row", 65), ("date", "Date / time", 160),
            ("description", "Original description", 320), ("amount", "Amount", 140)],
            title="Incoming rows — select ambiguous rows to choose Keep or Skip", selectmode="extended")
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
        self.review_button = ttk.Button(result, text="Show unclassified transactions", command=self._review_unknown)
        self.review_button.grid(row=0, column=1, padx=(8, 0))

    def _build_browser(self):
        tab = self.transactions_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        filters = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
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
        self.direction_box.bind("<<ComboboxSelected>>", lambda _: self._update_browser_category_choices())
        ttk.Label(filters, text="Merchant / description search").grid(row=2, column=0, sticky="w", padx=4, pady=(8, 0))
        search = ttk.Entry(filters, textvariable=self.search)
        search.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4)
        search.bind("<Return>", lambda _: self._apply_filters())
        review = ttk.Checkbutton(filters, text="Unclassified only", variable=self.review_only)
        review.grid(row=3, column=2, sticky="w", padx=4)
        buttons = ttk.Frame(filters)
        buttons.grid(row=3, column=3, sticky="ew")
        apply = ttk.Button(buttons, text="🔄  " + self.t("Apply / refresh"), command=self._apply_filters, style="Primary.TButton")
        apply.pack(side="left", padx=4)
        reset = ttk.Button(buttons, text="✕  " + self.t("Reset"), command=self._reset_filters)
        reset.pack(side="left", padx=4)
        edit = ttk.Button(buttons, text="✏  " + self.t("Edit selected"), command=self._edit_selected)
        self.edit_button = edit
        edit.pack(side="left", padx=4)
        archive = ttk.Button(buttons, text="🗑 " + self.t("Delete selected"), command=self._archive_selected)
        self.archive_button = archive
        archive.pack(side="left", padx=4)
        restore = ttk.Button(buttons, text="↺  " + self.t("Restore selected"), command=self._restore_selected)
        self.restore_button = restore
        restore.pack(side="left", padx=4)
        self.filter_widgets.extend((search, review, apply, reset, edit, archive, restore))
        ttk.Label(filters, text="Currency").grid(row=4, column=0, sticky="w", padx=4)
        self.currency_box = ttk.Combobox(filters, textvariable=self.currency_text,
                                         values=(self.t("All currencies"),), state="readonly")
        self.currency_box.grid(row=5, column=0, sticky="ew", padx=4)
        self.filter_widgets.append(self.currency_box)
        ttk.Label(filters, text="Account").grid(row=4, column=1, sticky="w", padx=4)
        self.browser_account_box = ttk.Combobox(filters, textvariable=self.browser_account_text,
                                                values=(self.t("All accounts"),), state="readonly")
        self.browser_account_box.grid(row=5, column=1, sticky="ew", padx=4)
        ttk.Label(filters, text="Status / archive").grid(row=4, column=2, sticky="w", padx=4)
        self.browser_archive_box = ttk.Combobox(
            filters, textvariable=self.browser_archive_text,
            values=(self.t("Active"), self.t("Archived"), self.t("All")), state="readonly", width=14)
        self.browser_archive_box.grid(row=5, column=2, sticky="ew", padx=4)
        self.browser_archive_box.bind("<<ComboboxSelected>>", lambda _: self._apply_filters())
        self.filter_widgets.append(self.browser_archive_box)
        self.filter_widgets.append(self.browser_account_box)
        ttk.Label(filters, text="Bank").grid(row=4, column=3, sticky="w", padx=4)
        self.browser_bank_box = ttk.Combobox(
            filters, textvariable=self.browser_bank_text,
            values=(self.t("All banks"),), state="readonly")
        self.browser_bank_box.grid(row=5, column=3, sticky="ew", padx=4)
        self.filter_widgets.append(self.browser_bank_box)
        for column in range(4):
            filters.columnconfigure(column, weight=1)
        browser_messages = ttk.Frame(tab)
        browser_messages.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(browser_messages, textvariable=self.summary, wraplength=900).pack(anchor="w")
        ttk.Label(browser_messages, textvariable=self.review_hint, wraplength=900).pack(anchor="w")
        ttk.Label(browser_messages, textvariable=self.filtered_totals, wraplength=900, style="Muted.TLabel").pack(anchor="w")
        self.transactions = PagedTable(tab, [
            ("date", "Date / time", 135), ("description", "Merchant / description", 250),
            ("bank_account", "Bank / account", 175), ("amount", "Amount", 130),
            ("category", "Category", 155), ("rule", "Classification rule", 175),
            ("review", "Review status", 125), ("kind", "Direction / kind", 135)],
            title="Transactions", size=100, height=14, selectmode="extended")
        self.transactions.grid(row=2, column=0, sticky="nsew")
        self.transactions.tree.bind("<<TreeviewSelect>>", lambda _: self._sync_controls())
        self.transactions.tree.bind("<Double-1>", lambda _: self._edit_selected())
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
        reviewing = self.review_views is not None and (self.review_views.pending is not None or self.review_views.editor is not None)
        selecting = idle and self.preview is None and not reviewing
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
        selected_transactions = selected_items(self.transactions)
        num_selected = len(selected_transactions)
        arch_src = source_text(self.browser_archive_text.get(), ("Active", "Archived", "All"))
        if hasattr(self, "archive_button"):
            all_active = all(not row.get("is_archived") for row in selected_transactions)
            self._enabled(self.archive_button, selecting and num_selected >= 1
                          and arch_src != "Archived" and all_active)
        if hasattr(self, "restore_button"):
            has_archived = any(row.get("is_archived") for row in selected_transactions)
            self._enabled(self.restore_button, selecting and has_archived
                          and arch_src in ("Archived", "All"))
        if hasattr(self, "edit_button"):
            selected_is_active = num_selected == 1 and not selected_transactions[0].get("is_archived")
            self._enabled(self.edit_button, selecting and selected_is_active)
        if hasattr(self, "backup_button"):
            self._enabled(self.backup_button, selecting)
        for button in getattr(self, "local_buttons", ()):
            self._enabled(button, selecting)
        self._enabled(self.browser_previous, idle and self.browser_page > 0)
        self._enabled(self.browser_next, idle and (self.browser_page + 1) * int(self.page_size.get()) < self.browser_total)
        if self.busy:
            self.progress.start(15)
        else:
            self.progress.stop()
        if self.review_views is not None:
            self.review_views.sync()
        if self.mapping_view is not None:
            self.mapping_view.sync()
        if hasattr(self, "budget_view") and self.budget_view is not None:
            self.budget_view.sync()
        if self.dashboard is not None:
            self.dashboard.sync()

    def _request(self, operation, **payload):
        if self.busy or not self.ready or self.closing:
            return False
        self.busy = True
        self.status.set(self.t({"preview": "Parsing and validating statement…", "commit": "Committing the complete import…",
                         "cancel": "Canceling preview…", "account": "Saving account…", "browse": "Loading transactions…",
                         "dashboard": "Calculating Dashboard…", "backup": "Creating and validating backup…"}.get(operation, "Processing review action…")))
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
        path = filedialog.askopenfilename(parent=self.window, title=self.t("Choose a Khan Bank MNT statement"),
                                          filetypes=[("Excel statement", "*.xlsx")])
        if path:
            self.file_path.set(path)
            self.account_confirmed.set(False)
            self.summary.set("")
            self._sync_controls()

    def _backup(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.window, title=self.t("Choose a local backup folder"), mustexist=True)
        if folder:
            self._request("backup", folder=folder)

    def _restore(self):
        if self.busy or not self.ready:
            return
        path = filedialog.askopenfilename(parent=self.window, title=self.t("Choose a Personal Finance backup"),
                                          filetypes=[("SQLite backup", "*.sqlite3 *.sqlite *.db")])
        if path:
            self._request("restore_preview", path=path)

    def _export_csv(self):
        if self.busy or not self.ready:
            return
        if not self.browser_total:
            self.status.set(self.t("No transactions match the applied filters. No export file was created."))
            return
        path = filedialog.asksaveasfilename(parent=self.window, title=self.t("Export all transactions matching applied filters"),
                                          defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                          initialfile="transactions.csv")
        if path:
            self._request("export_csv", path=path, filters=dict(self.active_filters), language=self.language)

    def _open_data_folder(self):
        try:
            open_data_folder(self.data_dir)
        except ValueError as error:
            self._error(str(error))

    def _about(self):
        messagebox.showinfo(self.t("Help / About"),
                            self.t("App {version} | Database schema {schema}\nData folder: {folder}\n\n"
                                   "Offline; no account, cloud or API key.\n"
                                   "Import: select account/file, preview, then confirm.\n"
                                   "Review: selected-only categories by default; rules are optional.\n"
                                   "Transactions: Apply filters before Export CSV (all matching pages).\n"
                                   "Backup saves a validated snapshot. Restore requires confirmation,\n"
                                   "creates a safety backup, and requires close/reopen afterward.\n"
                                   "Close other app instances before restore.\n"
                                   "Full instructions: docs/user_guide.md in the project folder.").format(
                                       version=APP_VERSION, schema=SCHEMA_VERSION, folder=self.data_dir),
                            parent=self.window)

    def _set_accounts(self, accounts, selected=None):
        self.accounts = accounts
        currencies = sorted({a["currency"] for a in accounts})
        if hasattr(self, "currency_box"):
            self.currency_box.configure(values=[self.t("All currencies")] + currencies)
        if self.dashboard is not None:
            self.dashboard.set_currencies(currencies)
        if hasattr(self, "browser_account_box"):
            self.browser_account_box.configure(values=[self.t("All accounts")] + [f'{a["name"]} ({a["currency"]}) #{a["id"]}' for a in accounts])
        if hasattr(self, "browser_bank_box"):
            self.browser_bank_box.configure(
                values=[self.t("All banks")] + sorted({a["bank"] for a in accounts}))
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
        dialog.title(self.t("Add bank account"))
        dialog.transient(self.window)
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=18)
        content.pack(fill="both", expand=True)
        name, identifier, bank = tk.StringVar(dialog), tk.StringVar(dialog), tk.StringVar(dialog, "Khan Bank")
        ttk.Label(content, text="Account name").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=name, width=46).grid(row=1, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(content, text="Bank").grid(row=2, column=0, sticky="w")
        ttk.Entry(content, textvariable=bank, width=46).grid(row=3, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(content, text="IBAN exactly as shown on the statement (text)").grid(row=4, column=0, sticky="w")
        ttk.Entry(content, textvariable=identifier, width=46).grid(row=5, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(content, text="MNT account. Other bank formats remain unsupported until verified.").grid(row=6, column=0, sticky="w")
        def close_dialog():
            if not self.busy:
                dialog.destroy()
                self.account_dialog = None
        def save():
            if not name.get().strip() or not identifier.get().strip() or not bank.get().strip():
                messagebox.showerror(
                    self.t("Account"),
                    self.t("Enter bank name, account name and its statement identifier."),
                    parent=dialog)
                return
            if self._request("account", name=name.get(), identifier=identifier.get(), bank=bank.get()):
                save_button.state(["disabled"])
                cancel.state(["disabled"])
        save_button = ttk.Button(content, text="Save account", command=save)
        save_button.grid(row=7, column=0, sticky="w", pady=(16, 0))
        cancel = ttk.Button(content, text="Cancel", command=close_dialog)
        cancel.grid(row=7, column=0, sticky="e", pady=(16, 0))
        self.account_dialog_buttons = (save_button, cancel)
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        localize_widget_tree(dialog)
        dialog.grab_set()

    def _preview(self):
        index = self.account_box.current()
        if index >= 0 and self.account_confirmed.get():
            self.summary.set("")
            self._request("preview", path=self.file_path.get(), account_id=self.accounts[index]["id"])

    def _preview_values(self, row):
        source = row.source
        rule_label = "—"
        if getattr(row, "matched_rule", None):
            category = getattr(row, "matched_category", None)
            rule_label = f"{row.matched_rule} → {self.t(category)}" if category else row.matched_rule
        return (self.t(row.status.capitalize()), self.t(self.decisions.get(row.index, "Choose")) if row.status == "ambiguous" else "—",
                rule_label, source.worksheet, source.row_number, source.occurred_at.replace("T", " "),
                source.description, format_mnt(source.amount_minor))

    def _show_candidates(self):
        selected = self.preview_table.tree.selection()
        if self.preview is None or not selected:
            self.candidates.set_items(())
        else:
            row = self.preview.rows[int(selected[0])]
            sources = [(self.t("Incoming"), row.source)] + [(f"Existing #{c.transaction_id}", c.source) for c in row.candidates]
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
        self.status.set(translate_format(
            "Duplicate decisions: {selected} of {total}. Each skipped occurrence must have its own existing match.",
            selected=len(self.decisions), total=self.preview.ambiguous_count))
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
        self.preview_counts.set(self.t("Select an account and an XLSX statement to preview."))

    def _apply_filters(self):
        if self.busy:
            return
        try:
            cat_id = self.resolve_category_id(self.category_text.get())
            if cat_id is None and hasattr(self, "category_box"):
                index = self.category_box.current()
                if index > 0 and hasattr(self, "browser_categories") and index - 1 < len(self.browser_categories):
                    cat_id = self.browser_categories[index - 1]["id"]
                elif index > 0 and index - 1 < len(self.categories):
                    cat_id = self.categories[index - 1]["id"]
            arch_src = source_text(self.browser_archive_text.get(), ("Active", "Archived", "All"))
            archived = False
            if arch_src == "Archived":
                archived = True
            elif arch_src == "All":
                archived = None
            self.active_filters = browser_filters(
                self.date_from.get(), self.date_to.get(), cat_id,
                {"Debit": "debit", "Credit": "credit", "Zero": "zero"}.get(
                    source_text(self.direction_text.get(), ("All directions", "Debit", "Credit", "Zero"))),
                self.review_only.get(), self.search.get(),
                currency=None if source_text(self.currency_text.get(), ("All currencies",)) == "All currencies" else self.currency_text.get(),
                bank=None if source_text(self.browser_bank_text.get(), ("All banks",)) == "All banks"
                else self.browser_bank_text.get(),
                archived=archived)
            if hasattr(self, "browser_account_box"):
                account_index = self.browser_account_box.current()
                if account_index > 0:
                    self.active_filters["account_id"] = self.accounts[account_index - 1]["id"]
            if hasattr(self, "browser_bank_box"):
                bank_index = self.browser_bank_box.current()
                if bank_index > 0:
                    self.active_filters["bank"] = sorted({a["bank"] for a in self.accounts})[bank_index - 1]
        except ValueError as error:
            self._error(str(error))
            return
        self._browse(0)

    def _reset_filters(self):
        self.date_from.set("")
        self.date_to.set("")
        self.search.set("")
        self.category_text.set(self.t("All categories"))
        self.direction_text.set(self.t("All directions"))
        self.currency_text.set(self.t("All currencies"))
        self.browser_account_text.set(self.t("All accounts"))
        self.browser_bank_text.set(self.t("All banks"))
        self.browser_archive_text.set(self.t("Active"))
        if hasattr(self, "browser_account_box"):
            self.browser_account_box.current(0)
        if hasattr(self, "browser_bank_box"):
            self.browser_bank_box.current(0)
        if hasattr(self, "browser_archive_box"):
            self.browser_archive_box.current(0)
        self.review_only.set(False)
        self.review_hint.set("")
        self._apply_filters()

    def _browse(self, page=0):
        self._request("browse", filters=dict(self.active_filters), page=max(0, page), page_size=int(self.page_size.get()))

    def _dashboard_drill(self, filters):
        self.browser_account_text.set(self.t("All accounts"))
        self.browser_bank_text.set(self.t("All banks"))
        self.browser_archive_text.set(self.t("Active"))
        if hasattr(self, "browser_account_box"):
            self.browser_account_box.current(0)
        if hasattr(self, "browser_bank_box"):
            self.browser_bank_box.current(0)
        if hasattr(self, "browser_archive_box"):
            self.browser_archive_box.current(0)
        self.date_from.set(filters.get("date_from") or "")
        self.date_to.set(filters.get("date_to") or "")
        self.currency_text.set(filters["currency"])
        category_id = filters.get("category_id")
        index = next((i + 1 for i, c in enumerate(self.categories) if c["id"] == category_id), 0)
        self.category_box.current(index)
        self.category_text.set(self.categories[index - 1]["name"] if index else self.t("All categories"))
        self.direction_text.set(self.t("All directions"))
        self.review_only.set(False)
        self.search.set("")
        self.review_hint.set(self.t("Dashboard selection: date and currency filters are applied."))
        self.active_filters = dict(filters)
        self.tabs.select(self.transactions_tab)
        self._browse(0)

    def _review_unknown(self):
        if self.busy:
            return
        self.browser_account_text.set(self.t("All accounts"))
        self.browser_bank_text.set(self.t("All banks"))
        self.browser_archive_text.set(self.t("Active"))
        if hasattr(self, "browser_account_box"):
            self.browser_account_box.current(0)
        if hasattr(self, "browser_bank_box"):
            self.browser_bank_box.current(0)
        if hasattr(self, "browser_archive_box"):
            self.browser_archive_box.current(0)
        self.date_from.set("")
        self.date_to.set("")
        self.search.set("")
        self.category_text.set(self.t("All categories"))
        self.direction_text.set(self.t("All directions"))
        self.currency_text.set(self.t("All currencies"))
        self.review_only.set(True)
        self.review_hint.set(self.t("Transactions awaiting review. Use Review to classify or edit selected rows."))
        self.active_filters = browser_filters(review_only=True)
        self.tabs.select(self.transactions_tab)
        self._browse(0)

    def _archive_selected(self):
        if self.busy:
            return
        selected = [row for row in selected_items(self.transactions) if not row.get("is_archived")]
        if not selected:
            return
        ArchiveConfirmDialog(
            self.window, self, selected,
            on_confirm=lambda: self._request("transactions_archive", transaction_ids=[r["id"] for r in selected]),
        )

    def _restore_selected(self):
        if self.busy:
            return
        selected = [row for row in selected_items(self.transactions) if row.get("is_archived")]
        if not selected:
            return
        count = len(selected)
        msg = f"{count} {self.t('transactions')}: {self.t('Restore selected transactions?')}"
        if messagebox.askyesno(self.t("Restore transactions"), msg, parent=self.window):
            self._request("transactions_restore", transaction_ids=[r["id"] for r in selected])

    def _edit_selected(self):
        if self.busy:
            return
        if self.preview is not None or (self.review_views is not None and self.review_views.pending is not None):
            self._error("Apply or cancel the current preview before editing.")
            return
        rows = selected_items(self.transactions)
        if len(rows) != 1:
            self._error("Select one transaction to edit.")
            return
        self._request("edit_get", transaction_id=rows[0]["id"])

    def _error(self, message):
        message = self.t(message)
        self.error_text = message
        self.status.set("")
        self.status.set(message)
        if not self.closing:
            review = self.review_views
            parent = (review.dialog or review.editor) if review is not None else None
            messagebox.showerror(self.t("Personal Finance"), message, parent=parent or self.account_dialog or self.window)

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
                if event.operation == "dashboard" and self.dashboard is not None:
                    self.dashboard.clear(event.error)
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
        self._continue_transaction_refreshes()
        if (self.dashboard is not None and self.dashboard_dirty and not self.transaction_refresh_queue
                and self.ready and not self.busy and not self.closing):
            self.dashboard.refresh()
        self._poll_id = self.window.after(40, self._poll)

    def _continue_transaction_refreshes(self):
        while self.transaction_refresh_queue and self.ready and not self.busy and not self.closing:
            refresh = self.transaction_refresh_queue.pop(0)
            if refresh == "browse":
                if self._request("browse", filters=dict(self.active_filters), page=self.browser_page,
                                 page_size=int(self.page_size.get())):
                    return
            elif refresh == "review" and self.review_views is not None:
                if self._request("review_load"):
                    return
            elif refresh == "budget" and getattr(self, "budget_view", None) is not None:
                self.budget_view.load()
                if self.busy:
                    return

    def _handle(self, operation, payload):
        self.status.set(self.t("Ready"))
        if operation in ("commit", "review_apply", "review_save", "rule_apply", "edit_save", "mapping_apply", "transactions_archive", "transactions_restore"):
            self.dashboard_dirty = True
            if self.dashboard is not None:
                self.dashboard.clear("Transactions changed; refreshing Dashboard…")
        if operation == "restore_preview":
            confirmed = messagebox.askyesno(
                self.t("Confirm restore"),
                translate_format("Validated database v{schema}: {transactions} transactions, {accounts} accounts, {rules} rules.\n\n"
                       "Replace the current database with this snapshot?\n"
                       "A validated safety backup will be saved in the active data folder's backups subfolder first.\n"
                       "Close other app instances. After success, close and reopen this app.\n"
                       "The selected backup is kept. Cancel leaves current data unchanged.",
                           schema=payload.schema, transactions=payload.transactions,
                           accounts=payload.accounts, rules=payload.rules),
                parent=self.window, default="no")
            self._request("restore_confirm", token=payload.token, confirmed=True) if confirmed else self._request("restore_cancel")
        elif operation == "restore_cancel":
            self.status.set(self.t("Restore canceled. The current database is unchanged."))
        elif operation == "restore_confirm":
            self.ready, self.dashboard_dirty = False, False
            self.transactions.set_items(())
            if self.dashboard is not None:
                self.dashboard.clear("Restore complete. Close and reopen the app.")
            self.status.set(translate_format(
                "Restore completed. Close and reopen the app. Safety backup: {path}", path=payload.safety_backup))
            messagebox.showinfo(self.t("Restore complete"), self.status.get(), parent=self.window)
        elif operation == "export_csv":
            self.status.set(translate_format("Exported {count} transactions to: {path}",
                count=payload.count, path=payload.path) if payload.count else
                self.t("No transactions match the applied filters. No export file was created."))
        elif operation == "backup":
            self.status.set(translate_format("Backup completed and validated: {path}", path=payload))
        elif operation == "dashboard":
            self.dashboard.display(payload)
        elif operation.startswith(("review_", "rule_", "edit_")):
            self.review_views.handle(operation, payload)
        elif operation.startswith("mapping_") and self.mapping_view is not None:
            self.mapping_view.handle(operation, payload)
            if operation == "mapping_apply":
                self._browse(self.browser_page)
        elif operation == "ready":
            self.ready = True
            self._set_accounts(payload["accounts"])
            self.categories = payload["categories"]
            self._update_browser_category_choices()
            if self.review_views is not None:
                self.review_views._categories()
            self._browse()
        elif operation in ("category_add", "category_delete"):
            self.categories = payload["categories"]
            if operation == "category_delete":
                deleted_id = payload.get("deleted_id")
                if deleted_id:
                    self.disabled_categories.discard(deleted_id)
                    self.custom_category_names.pop(deleted_id, None)
                    save_category_settings(self.data_dir, self.disabled_categories, self.custom_category_names)
            self._categories_changed()
            if self.categories_dialog is not None:
                self.categories_dialog.refresh_usage()
            self.status.set(self.t("Category saved." if operation == "category_add" else "Category deleted."))
        elif operation == "category_list_usage":
            if self.categories_dialog is not None:
                self.categories_dialog.set_usage(payload)
        elif operation == "account":
            if self.account_dialog is not None:
                self.account_dialog.destroy()
                self.account_dialog = None
            self._set_accounts(payload["accounts"], payload["selected"])
            self.status.set(self.t("Account saved. Select a statement and confirm its account before previewing."))
        elif operation == "preview":
            # Row counts alone do not include statement/account validation errors.
            # Replace every previous diagnostic, even when the rows are all valid.
            self.summary.set("")
            self.preview, self.decisions = payload, {}
            self.candidates.set_items(())
            self.preview_table.set_items(payload.rows, self._preview_values)
            self.issues.set_items(payload.issues, lambda issue: (issue.severity, *issue_location(issue), issue.code, issue.message))
            errors = [issue for issue in payload.issues if issue.severity == "error"]
            self.preview_counts.set(import_preview_counts(
                payload.valid_count, payload.invalid_count, payload.duplicate_count,
                payload.ambiguous_count, len(errors)))
            if not payload.is_valid:
                self.preview_tabs.select(1)
                if any(issue.code == "account_mismatch" for issue in errors):
                    message = ("Import blocked: the statement account/currency does not match the selected account. "
                               "Cancel preview, select or add the matching account, confirm it, and preview again. "
                               "Valid row counts do not mean the statement can be committed.")
                else:
                    message = "Import blocked. Review errors, cancel, and resolve the source problem before creating a new preview."
                message = self.t(message)
                self.summary.set(message)
                self.status.set(message)
            else:
                self.preview_tabs.select(0)
                self.status.set(self.t("Preview validated. Choose Keep/Skip for ambiguous rows, then click Commit import."
                                       if payload.ambiguous_count else
                                       "Preview validated. Click Commit import to save these transactions."))
        elif operation == "cancel":
            self._clear_preview()
            self.summary.set(self.t("Preview canceled. No transactions or import metadata were changed."))
        elif operation == "commit":
            self._clear_preview()
            result = payload["result"]
            unclassified = payload["unclassified"]
            count = str(unclassified) if unclassified is not None else "unavailable — use Review unknown merchants"
            self.summary.set(import_result(
                result.status, result.imported_count, result.skipped_count, count,
                duplicate=payload["duplicate"], invalid=payload["invalid"]))
            # Old browser filters must not hide a successful import. The refresh
            # uses the same worker/connection that completed the atomic write.
            self.tabs.select(self.transactions_tab)
            self._reset_filters()
        elif operation in ("transactions_archive", "transactions_restore"):
            self.status.set(self.t("Transactions archived." if operation == "transactions_archive" else "Transactions restored."))
            self.transaction_refresh_queue = ["browse", "review", "budget"]
        elif operation.startswith("budget_"):
            if self.budget_view is not None:
                self.budget_view.handle(operation, payload)
        elif operation == "browse":
            self.browser_page, self.browser_total = payload["page"], payload["total"]
            self.browser_report = payload.get("report")
            if self.browser_report is not None:
                self.filtered_totals.set(filtered_totals_text(self.browser_report, self.t))
            categories = {c["id"]: self.category_display_name(c) for c in self.categories}
            self.transactions.set_items(
                payload["rows"],
                lambda row: transaction_row_values(row, categories, self.t),
            )
            pages = max(1, (payload["total"] + payload["page_size"] - 1) // payload["page_size"])
            self.browser_caption.set(page_caption(self.browser_page + 1, pages, self.browser_total, "transactions"))

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set(self.t("Closing after the current operation finishes…"))
        self._sync_controls()
        self.worker.stop()
        if not self.worker.thread.is_alive():
            self.window.after_cancel(self._poll_id)
            self.window.destroy()
