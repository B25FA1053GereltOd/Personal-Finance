"""Check data location precedence and independence from the working folder."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import get_data_dir


class DataDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path.home()

    def test_explicit_directory_takes_precedence(self) -> None:
        expected = self.home / "synthetic-finance-data"
        with patch.dict(os.environ, {
            "PERSONAL_FINANCE_DATA_DIR": str(expected),
            "LOCALAPPDATA": str(self.home / "synthetic-local-data"),
        }, clear=True):
            self.assertEqual(get_data_dir(), expected)

    def test_default_uses_local_app_data(self) -> None:
        local = self.home / "synthetic-local-data"
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=True):
            self.assertEqual(get_data_dir(), local / "PersonalFinanceTool")

    def test_missing_or_empty_variables_use_home_fallback(self) -> None:
        for values in ({}, {"PERSONAL_FINANCE_DATA_DIR": "", "LOCALAPPDATA": ""}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                with patch("app.config.Path.home", return_value=self.home):
                    self.assertEqual(get_data_dir(), self.home / "PersonalFinanceTool")

    def test_empty_override_uses_local_app_data(self) -> None:
        with patch.dict(os.environ, {
            "PERSONAL_FINANCE_DATA_DIR": "", "LOCALAPPDATA": str(self.home),
        }, clear=True):
            self.assertEqual(get_data_dir(), self.home / "PersonalFinanceTool")

    def test_relative_environment_paths_are_rejected(self) -> None:
        for variable in ("PERSONAL_FINANCE_DATA_DIR", "LOCALAPPDATA"):
            with self.subTest(variable=variable):
                with patch.dict(os.environ, {variable: "relative-data"}, clear=True):
                    with self.assertRaisesRegex(ValueError, variable):
                        get_data_dir()

    def test_paths_do_not_depend_on_working_directory_or_create_folders(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            expected = base / "PersonalFinanceTool"
            environments = (
                {"PERSONAL_FINANCE_DATA_DIR": str(expected)},
                {"LOCALAPPDATA": str(base)},
                {},
            )
            try:
                for values in environments:
                    with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                        with patch("app.config.Path.home", return_value=base):
                            os.chdir(original)
                            before = get_data_dir()
                            os.chdir(base)
                            self.assertEqual(get_data_dir(), before)
                            self.assertEqual(get_data_dir(), expected)
                            self.assertFalse(expected.exists())
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
