"""Tests for centralized theme tokens, theme application, and mode switching."""

import tempfile
import unittest
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from app.ui.theme import (
    DARK,
    LIGHT,
    THEMES,
    apply_theme,
    get_current_theme,
    get_theme_tokens,
)
from app.ui.dashboard import ChartCanvas
from tests.test_ui import ROOT


class ThemeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
            self.addCleanup(self.root.destroy)
        except tk.TclError:
            self.root = None

    def test_theme_tokens_structure_and_palettes(self):
        self.assertIn("dark", THEMES)
        self.assertIn("light", THEMES)
        dark_tokens = get_theme_tokens("dark")
        self.assertEqual(dark_tokens.name, "dark")
        self.assertEqual(dark_tokens.bg, "#12161f")
        self.assertEqual(dark_tokens.sidebar_bg, "#0c1017")
        self.assertEqual(dark_tokens.text, "#f1f5f9")
        self.assertEqual(dark_tokens.card_bg, "#1c2230")

        light_tokens = get_theme_tokens("light")
        self.assertEqual(light_tokens.name, "light")
        self.assertEqual(light_tokens.bg, "#f8fafc")
        self.assertEqual(light_tokens.sidebar_bg, "#0f1f3d")
        self.assertEqual(light_tokens.text, "#0f172a")
        self.assertEqual(light_tokens.card_bg, "#ffffff")

        # Unknown theme raises ValueError
        with self.assertRaises(ValueError):
            get_theme_tokens("solarized")

    def test_apply_theme_configures_root_and_ttk_style(self):
        if self.root is None:
            self.skipTest("Tkinter display not available")
        style = apply_theme(self.root, "dark")
        current = get_current_theme()
        self.assertEqual(current.name, "dark")
        self.assertEqual(self.root.cget("background"), "#12161f")
        self.assertEqual(style.lookup("TFrame", "background"), "#12161f")
        self.assertEqual(style.lookup("Card.TFrame", "background"), "#1c2230")

        # Switch to light mode
        style = apply_theme(self.root, "light")
        current = get_current_theme()
        self.assertEqual(current.name, "light")
        self.assertEqual(self.root.cget("background"), "#f8fafc")
        self.assertEqual(style.lookup("TFrame", "background"), "#f8fafc")
        self.assertEqual(style.lookup("Card.TFrame", "background"), "#ffffff")

    def test_chart_canvas_adapts_to_theme(self):
        if self.root is None:
            self.skipTest("Tkinter display not available")
        apply_theme(self.root, "dark")
        chart = ChartCanvas(self.root, "month")
        chart.render(())
        self.assertEqual(chart.drawn_items[0]["type"], "empty")

        # Switch chart theme to light
        chart.set_theme(LIGHT)
        self.assertEqual(chart.theme_tokens.name, "light")
        self.assertEqual(chart.canvas.cget("background"), "#ffffff")

        # Switch chart theme back to dark
        chart.set_theme(DARK)
        self.assertEqual(chart.theme_tokens.name, "dark")
        self.assertEqual(chart.canvas.cget("background"), "#1c2230")


if __name__ == "__main__":
    unittest.main()
