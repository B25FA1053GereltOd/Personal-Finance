"""Data location configuration, independent of the working directory."""

import os
from pathlib import Path


def _absolute_path(value: str, variable: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path; got {value!r}.")
    return path


def get_data_dir() -> Path:
    """Return the data folder without creating it or accessing financial data.

    PERSONAL_FINANCE_DATA_DIR overrides LOCALAPPDATA/PersonalFinanceTool.
    If LOCALAPPDATA is absent or empty, use ~/PersonalFinanceTool.
    Empty overrides are treated as unset; relative paths are rejected.
    """
    override = os.environ.get("PERSONAL_FINANCE_DATA_DIR")
    if override:
        return _absolute_path(override, "PERSONAL_FINANCE_DATA_DIR")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return _absolute_path(local_app_data, "LOCALAPPDATA") / "PersonalFinanceTool"

    return Path.home() / "PersonalFinanceTool"
