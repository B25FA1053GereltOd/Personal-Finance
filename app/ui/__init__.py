"""Tkinter/ttk application window."""

import tkinter as tk
from pathlib import Path
from tkinter import ttk


def create_window(data_dir: Path) -> tk.Tk:
    """Create the main window; the caller owns its event loop."""
    window = tk.Tk()
    window.title("Personal Finance Tool")
    window.geometry("680x340")
    window.minsize(520, 300)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    window.protocol("WM_DELETE_WINDOW", window.destroy)

    content = ttk.Frame(window, padding=28)
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=1)
    content.rowconfigure(4, weight=1)

    ttk.Label(
        content, text="Personal Finance", font=("Segoe UI", 22, "bold")
    ).grid(row=0, column=0, sticky="w")
    ttk.Label(content, text="Your finances, stored locally.").grid(
        row=1, column=0, sticky="w", pady=(6, 24)
    )
    ttk.Label(content, text="Data folder:").grid(row=2, column=0, sticky="w")
    folder = ttk.Label(content, text=str(data_dir), wraplength=600)
    folder.grid(row=3, column=0, sticky="ew", pady=(6, 16))
    content.bind(
        "<Configure>",
        lambda event: folder.configure(wraplength=max(1, event.width - 56)),
    )
    ttk.Button(content, text="Close", command=window.destroy).grid(
        row=5, column=0, sticky="e"
    )
    return window
