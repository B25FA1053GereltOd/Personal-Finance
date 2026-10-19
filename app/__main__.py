"""Run the desktop application with ``python -m app``."""

from app.config import get_data_dir
from app.ui import create_window


def main() -> None:
    """Resolve the data location and run the Tk event loop."""
    try:
        data_dir = get_data_dir()
    except ValueError as error:
        raise SystemExit(f"Cannot start Personal Finance Tool: {error}") from error

    window = create_window(data_dir)
    try:
        window.mainloop()
    finally:
        # Also cover console interruption or an externally destroyed window.
        # The worker finishes any atomic commit and closes its own connection.
        window.finance_app.worker.stop()
        window.finance_app.worker.thread.join()


if __name__ == "__main__":
    main()
