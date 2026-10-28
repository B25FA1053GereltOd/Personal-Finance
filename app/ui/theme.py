"""Visual theme system: centralized dark and light palette tokens and ttk styles."""

from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class ThemeTokens:
    name: str  # "dark" or "light"
    bg: str
    surface: str
    card_bg: str
    card_border: str
    sidebar_bg: str
    sidebar_hover: str
    sidebar_active: str
    sidebar_text: str
    sidebar_muted: str
    text: str
    muted: str
    border: str
    primary: str
    primary_hover: str
    primary_disabled: str
    income: str
    expense: str
    net: str
    unclassified: str
    chart_bg: str
    chart_grid: str
    chart_text: str
    tree_bg: str
    tree_alt: str
    tree_selected: str
    tree_text: str
    heading_bg: str
    heading_hover: str
    heading_text: str
    entry_bg: str
    entry_fg: str
    font_family: str = "Segoe UI"


DARK = ThemeTokens(
    name="dark",
    bg="#12161f",
    surface="#181d28",
    card_bg="#1c2230",
    card_border="#2a3447",
    sidebar_bg="#0c1017",
    sidebar_hover="#192233",
    sidebar_active="#24344d",
    sidebar_text="#f1f5f9",
    sidebar_muted="#8292ab",
    text="#f1f5f9",
    muted="#8b9bb4",
    border="#2a3447",
    primary="#2563eb",
    primary_hover="#3b82f6",
    primary_disabled="#1d3557",
    income="#10b981",
    expense="#ef4444",
    net="#38bdf8",
    unclassified="#f59e0b",
    chart_bg="#1c2230",
    chart_grid="#252f42",
    chart_text="#f1f5f9",
    tree_bg="#161b26",
    tree_alt="#1b212f",
    tree_selected="#223656",
    tree_text="#f1f5f9",
    heading_bg="#1e2636",
    heading_hover="#283348",
    heading_text="#f1f5f9",
    entry_bg="#161b26",
    entry_fg="#f1f5f9",
    font_family="Segoe UI",
)

LIGHT = ThemeTokens(
    name="light",
    bg="#f8fafc",
    surface="#f1f5f9",
    card_bg="#ffffff",
    card_border="#d5deea",
    sidebar_bg="#0f1f3d",
    sidebar_hover="#1b3361",
    sidebar_active="#2a4a85",
    sidebar_text="#f1f5f9",
    sidebar_muted="#b6c4de",
    text="#0f172a",
    muted="#475569",
    border="#d5deea",
    primary="#2563eb",
    primary_hover="#1d4ed8",
    primary_disabled="#93b4f5",
    income="#15803d",
    expense="#b91c1c",
    net="#2563eb",
    unclassified="#c2410c",
    chart_bg="#ffffff",
    chart_grid="#f1f5f9",
    chart_text="#0f172a",
    tree_bg="#ffffff",
    tree_alt="#f4f7fb",
    tree_selected="#dbeafe",
    tree_text="#0f172a",
    heading_bg="#e8eef7",
    heading_hover="#d5e1f3",
    heading_text="#0f1f3d",
    entry_bg="#ffffff",
    entry_fg="#0f172a",
    font_family="Segoe UI",
)

THEMES = {
    "dark": DARK,
    "light": LIGHT,
}

_active_tokens = DARK

# Backward compatibility constants (matching default dark theme / legacy names)
NAVY = "#0f1f3d"
NAVY_HOVER = "#1b3361"
NAVY_ACTIVE = "#2a4a85"
ACCENT = "#3b82f6"
BLUE = "#2563eb"
BLUE_HOVER = "#1d4ed8"
BLUE_DISABLED = "#93b4f5"
WHITE = "#ffffff"
SURFACE = "#f8fafc"
BORDER = "#d5deea"
TEXT = "#0f172a"
MUTED = "#475569"
GREEN = "#15803d"
RED = "#b91c1c"
ORANGE = "#c2410c"
SIDEBAR_TEXT = "#f1f5f9"
SIDEBAR_MUTED = "#b6c4de"
FONT = "Segoe UI"


def get_theme_tokens(name: str | ThemeTokens | None = None) -> ThemeTokens:
    if isinstance(name, ThemeTokens):
        return name
    if name is None:
        return _active_tokens
    normalized = str(name).strip().lower()
    if normalized in THEMES:
        return THEMES[normalized]
    raise ValueError(f"Unknown theme: {name}. Available: {list(THEMES.keys())}")


def get_current_theme() -> ThemeTokens:
    return _active_tokens


def apply_theme(root, theme: str | ThemeTokens | None = None) -> ttk.Style:
    """Configure ttk styles for the application window using theme tokens."""
    global _active_tokens
    tokens = get_theme_tokens(theme) if theme is not None else _active_tokens
    _active_tokens = tokens

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    root.configure(background=tokens.bg)
    font_family = tokens.font_family

    style.configure(
        ".",
        font=(font_family, 10),
        background=tokens.bg,
        foreground=tokens.text,
        bordercolor=tokens.border,
        focuscolor=tokens.primary,
    )
    style.configure("TFrame", background=tokens.bg)
    style.configure("TLabel", background=tokens.bg, foreground=tokens.text, font=(font_family, 10))
    style.map("TLabel", foreground=[("disabled", tokens.muted)])
    style.configure("Muted.TLabel", background=tokens.bg, foreground=tokens.muted)
    style.configure("Error.TLabel", background=tokens.bg, foreground=tokens.expense, font=(font_family, 10, "bold"))
    style.configure("TCheckbutton", background=tokens.bg, foreground=tokens.text)
    style.map("TCheckbutton", foreground=[("disabled", tokens.muted)], background=[("active", tokens.bg)])

    style.configure(
        "TEntry",
        foreground=tokens.entry_fg,
        fieldbackground=tokens.entry_bg,
        bordercolor=tokens.border,
        padding=4,
    )
    style.configure(
        "TCombobox",
        foreground=tokens.entry_fg,
        fieldbackground=tokens.entry_bg,
        bordercolor=tokens.border,
        padding=4,
    )
    style.map(
        "TCombobox",
        foreground=[("readonly", tokens.entry_fg), ("disabled", tokens.muted)],
        fieldbackground=[("readonly", tokens.entry_bg), ("disabled", tokens.surface)],
    )

    style.configure("TSeparator", background=tokens.border)
    style.configure("TLabelframe", background=tokens.card_bg, bordercolor=tokens.card_border)
    style.configure(
        "TLabelframe.Label",
        background=tokens.card_bg,
        foreground=tokens.text,
        font=(font_family, 10, "bold"),
    )

    style.configure(
        "TButton",
        background=tokens.card_bg,
        foreground=tokens.text,
        bordercolor=tokens.border,
        padding=(10, 6),
    )
    style.map(
        "TButton",
        background=[("active", tokens.surface), ("disabled", tokens.surface)],
        foreground=[("disabled", tokens.muted), ("!disabled", tokens.text)],
    )

    style.configure(
        "Primary.TButton",
        background=tokens.primary,
        foreground="#ffffff",
        bordercolor=tokens.primary,
        padding=(12, 7),
        font=(font_family, 10, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", tokens.primary_disabled), ("active", tokens.primary_hover)],
        foreground=[("disabled", "#94a3b8"), ("!disabled", "#ffffff")],
        bordercolor=[("focus", tokens.sidebar_bg)],
    )

    style.configure("Hidden.TNotebook", background=tokens.bg, borderwidth=0, tabmargins=0)
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("TNotebook", background=tokens.bg, bordercolor=tokens.border)
    style.configure("TNotebook.Tab", background=tokens.surface, foreground=tokens.text, padding=(12, 6))
    style.map(
        "TNotebook.Tab",
        background=[("selected", tokens.card_bg)],
        foreground=[("selected", tokens.primary), ("!selected", tokens.text)],
    )

    style.configure(
        "Treeview",
        rowheight=28,
        background=tokens.tree_bg,
        fieldbackground=tokens.tree_bg,
        foreground=tokens.tree_text,
        bordercolor=tokens.border,
        font=(font_family, 10),
    )
    style.map(
        "Treeview",
        foreground=[("selected", "#ffffff")],
        background=[("selected", tokens.tree_selected)],
    )
    style.configure(
        "Treeview.Heading",
        background=tokens.heading_bg,
        foreground=tokens.heading_text,
        relief="flat",
        padding=(8, 6),
        font=(font_family, 9, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", tokens.heading_hover)])
    style.configure("Vertical.TScrollbar", background=tokens.border, troughcolor=tokens.bg)
    style.configure("Horizontal.TScrollbar", background=tokens.border, troughcolor=tokens.bg)

    style.configure("Topbar.TFrame", background=tokens.card_bg)
    style.configure("Footer.TFrame", background=tokens.surface)
    style.configure("Footer.TLabel", background=tokens.surface, foreground=tokens.muted, font=(font_family, 9))
    style.configure("FooterStatus.TLabel", background=tokens.surface, foreground=tokens.text, font=(font_family, 10))
    style.configure("FooterError.TLabel", background=tokens.surface, foreground=tokens.expense, font=(font_family, 10, "bold"))
    style.configure("Brand.TLabel", background=tokens.card_bg, foreground=tokens.text, font=(font_family, 17, "bold"))
    style.configure("Tag.TLabel", background=tokens.card_bg, foreground=tokens.muted)

    style.configure("Sidebar.TFrame", background=tokens.sidebar_bg)
    style.configure(
        "SidebarTitle.TLabel",
        background=tokens.sidebar_bg,
        foreground=tokens.sidebar_text,
        font=(font_family, 15, "bold"),
    )
    style.configure(
        "SidebarHint.TLabel",
        background=tokens.sidebar_bg,
        foreground=tokens.sidebar_muted,
        font=(font_family, 9),
    )
    for name, background in (("Sidebar.TButton", tokens.sidebar_bg), ("SidebarActive.TButton", tokens.sidebar_active)):
        is_active = "Active" in name
        style.configure(
            name,
            background=background,
            foreground=tokens.sidebar_text if is_active else tokens.sidebar_muted,
            anchor="w",
            padding=(14, 10),
            borderwidth=0,
            relief="flat",
            font=(font_family, 10, "bold" if is_active else "normal"),
        )
        style.map(
            name,
            background=[
                ("active", tokens.sidebar_hover if not is_active else tokens.sidebar_active),
                ("focus", tokens.sidebar_hover if not is_active else tokens.sidebar_active),
            ],
            foreground=[("disabled", tokens.sidebar_muted), ("!disabled", tokens.sidebar_text)],
        )

    style.configure("PageTitle.TLabel", background=tokens.bg, font=(font_family, 18, "bold"), foreground=tokens.text)
    style.configure("PageDescription.TLabel", background=tokens.bg, foreground=tokens.muted)
    style.configure("Card.TFrame", background=tokens.card_bg, relief="solid", borderwidth=1, bordercolor=tokens.card_border)
    style.configure("CardTitle.TLabel", background=tokens.card_bg, foreground=tokens.muted, font=(font_family, 10, "bold"))
    style.configure("CardValue.TLabel", background=tokens.card_bg, foreground=tokens.text, font=(font_family, 14, "bold"))
    style.configure("Section.TLabel", background=tokens.card_bg, foreground=tokens.text, font=(font_family, 11, "bold"))

    tones = (
        ("Revenue", tokens.income),
        ("Cost", tokens.expense),
        ("Net", tokens.net),
        ("Review", tokens.unclassified),
    )
    for tone, color in tones:
        style.configure(
            f"{tone}Card.TFrame",
            background=tokens.card_bg,
            relief="solid",
            borderwidth=1,
            bordercolor=tokens.card_border,
        )
        style.configure(f"{tone}Bar.TFrame", background=color)
        style.configure(
            f"{tone}Title.TLabel",
            background=tokens.card_bg,
            foreground=color,
            font=(font_family, 11, "bold"),
        )
        size = 24 if tone in ("Revenue", "Cost") else 15
        style.configure(
            f"{tone}Value.TLabel",
            background=tokens.card_bg,
            foreground=color,
            font=(font_family, size, "bold"),
        )

    style.configure("EmptyState.TLabel", background=tokens.tree_bg, foreground=tokens.muted, font=(font_family, 11))
    return style
