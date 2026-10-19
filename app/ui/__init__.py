"""Tkinter/ttk application window."""

import tkinter as tk
from pathlib import Path

from app.ui.desktop import DesktopApp


def create_window(data_dir: Path) -> tk.Tk:
    """Create the main window; the caller owns its event loop."""
    window = tk.Tk()
    window.finance_app = DesktopApp(window, data_dir)
    return window
