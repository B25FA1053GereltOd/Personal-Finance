"""Local Windows integration: paths passed as arguments, never shell text."""

import os
from pathlib import Path

APP_VERSION = "0.9.0"


def open_data_folder(folder):
    try:
        path = Path(folder)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError
        if os.name != "nt":
            raise OSError
        os.startfile(str(path.resolve()), "open")
    except (OSError, ValueError):
        raise ValueError("Could not open the data folder. Check that it exists and open it in File Explorer.") from None
