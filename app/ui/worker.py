"""One queue-driven owner of repository and import service; no Tk calls or logs."""

from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Thread

from app.db import Repository
from app.import_service import ImportBlocked, ImportService
from app.classification import ClassificationBlocked
from app.review_service import ReviewBlocked, ReviewService


@dataclass(frozen=True)
class Event:
    operation: str
    payload: object = field(default=None, repr=False)
    error: str | None = None


class FinanceWorker:
    """Create, use and close the database in a single persistent worker thread.

    The main thread submits commands and polls events; it never receives a
    connection or service. Shutdown is queued behind any in-flight atomic write.
    """

    def __init__(self, database: Path, *, repository_factory=Repository,
                 service_factory=ImportService):
        self.database = database
        self.events = Queue()
        self._commands = Queue()
        self._repository_factory = repository_factory
        self._service_factory = service_factory
        self._stopping = False
        self.thread = Thread(target=self._run, name="finance-worker", daemon=False)
        self.thread.start()

    def submit(self, operation: str, **payload) -> None:
        if self._stopping or not self.thread.is_alive():
            raise RuntimeError("Finance worker is closed.")
        self._commands.put((operation, payload))

    def stop(self) -> None:
        if not self._stopping:
            self._stopping = True
            self._commands.put(("stop", {}))

    def _run(self) -> None:
        repository = None
        preview = None
        try:
            repository = self._repository_factory(self.database)
            service = self._service_factory(repository)
            review = ReviewService(repository)
            self.events.put(Event("ready", {"accounts": repository.list_accounts(),
                                           "categories": repository.list_categories()}))
            while True:
                operation, payload = self._commands.get()
                if operation == "stop":
                    break
                try:
                    if review.pending is not None and operation in ("account", "preview", "commit"):
                        raise ReviewBlocked("Apply or cancel the review preview before importing.")
                    if operation.startswith(("review_", "rule_", "edit_")):
                        if preview is not None and operation not in ("review_load", "edit_get"):
                            raise ReviewBlocked("Cancel the import preview before reviewing or editing.")
                        actions = {
                            "review_load": review.load,
                            "review_preview": review.preview_assignment,
                            "review_apply": review.confirm_assignment,
                            "review_cancel": review.cancel,
                            "rule_preview": review.preview_rule,
                            "rule_apply": review.apply_rule,
                            "rule_change": review.change_rule,
                            "edit_get": review.edit_get,
                            "edit_save": review.edit_save,
                        }
                        if operation not in actions:
                            raise ReviewBlocked("Unsupported review action.")
                        result = actions[operation](**payload)
                    elif operation == "account":
                        if preview is not None:
                            raise ImportBlocked("Cancel the current preview before adding an account.")
                        name, identifier = payload["name"].strip(), payload["identifier"].strip()
                        if not name or not identifier:
                            raise ImportBlocked("Enter an account name and its statement IBAN.")
                        account_id = repository.create_account(identifier, name)
                        result = {"accounts": repository.list_accounts(), "selected": account_id}
                    elif operation == "preview":
                        if preview is not None:
                            raise ImportBlocked("Cancel the current preview before selecting another statement.")
                        preview = service.preview(payload["path"], payload["account_id"])
                        result = preview
                    elif operation == "cancel":
                        if preview is not None:
                            service.cancel(preview)
                        preview = None
                        result = None
                    elif operation == "commit":
                        if preview is None:
                            raise ImportBlocked("Create a preview before committing.")
                        committed = service.confirm(preview, payload.get("decisions", {}))
                        preview = None
                        # A count failure after commit must never be reported as a failed import.
                        unclassified = None
                        if committed.status == "identical_file":
                            unclassified = 0
                        else:
                            try:
                                unclassified = repository.count_transactions(import_id=committed.import_id, review_only=True)
                            except Exception:
                                pass
                        result = {"result": committed, "unclassified": unclassified}
                    elif operation == "browse":
                        filters = payload.get("filters", {})
                        size = payload.get("page_size", 50)
                        page = payload.get("page", 0)
                        if type(size) is not int or not 1 <= size <= 100 or type(page) is not int or page < 0:
                            raise ImportBlocked("Invalid page selection.")
                        total = repository.count_transactions(**filters)
                        page = min(page, max(0, (total - 1) // size))
                        rows = repository.query_transactions(**filters, limit=size, offset=page * size)
                        result = {"rows": rows, "page": page, "page_size": size, "total": total}
                    else:
                        raise ImportBlocked("Unsupported action.")
                    self.events.put(Event(operation, result))
                except (ImportBlocked, ReviewBlocked, ClassificationBlocked) as error:
                    self.events.put(Event(operation, error=str(error)))
                except Exception:
                    # Exception strings may contain identifiers, SQL or source text.
                    messages = {
                        "account": "Account could not be saved. Check the fields and whether it already exists.",
                        "browse": "Transactions could not be loaded. Check filters and try again.",
                        "preview": "Preview failed. Check the selected file and account, then try again.",
                        "commit": "Import could not be completed. Cancel and create a fresh preview before retrying.",
                    }
                    self.events.put(Event(operation, error=messages.get(operation, "Action failed. Refresh or cancel the preview before trying again; check category and direction compatibility.")))
            if preview is not None:
                service.cancel(preview)
            review.cancel()
        except Exception:
            self.events.put(Event("fatal", error="The local database could not be opened or the worker stopped unexpectedly. Close and reopen the app."))
        finally:
            if repository is not None:
                try:
                    repository.close()
                except Exception:
                    pass
            self.events.put(Event("stopped"))
