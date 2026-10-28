"""Explicit UI workflows composed from classification and audited edit APIs."""

from uuid import uuid4

from app.classification import ClassificationService
from app.db import classification_revision
from app.models import KINDS, money_to_minor, validate_iso


class ReviewBlocked(ValueError):
    """Static, safe-to-display validation message."""


class ReviewService:
    def __init__(self, repository):
        self.repository = repository
        self.classification = ClassificationService(repository)
        self.pending = None

    def load(self):
        return {"queue": self.classification.review(),
                "rules": self.repository.list_rules(include_disabled=True)}

    def _category(self, category_id, amounts):
        category = next((c for c in self.repository.list_categories() if c["id"] == category_id), None)
        if category is None:
            raise ReviewBlocked("Choose a category.")
        if any((amount <= 0 if category["direction"] == "income" else amount >= 0) for amount in amounts):
            raise ReviewBlocked("Choose a category compatible with every selected transaction's direction.")
        return category

    def _idle(self):
        if self.pending is not None:
            raise ReviewBlocked("Apply or cancel the current review preview first.")

    def preview_assignment(self, transaction_ids, category_id, save_rule=False):
        self._idle()
        ids = tuple(transaction_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ReviewBlocked("Select distinct transactions to preview.")
        queue = self.classification.review()
        items = {i.transaction_id: i for g in queue.groups for i in g.items}
        items.update({i.transaction_id: i for i in queue.individual})
        if not set(ids) <= items.keys():
            raise ReviewBlocked("Review items changed; refresh and select again.")
        rows = tuple(self.repository.get_transaction(i) for i in ids)
        self._category(category_id, [r["amount_minor"] for r in rows])
        scope = None
        if save_rule:
            group = next((g for g in queue.groups if set(ids) <= {i.transaction_id for i in g.items}), None)
            if group is None:
                raise ReviewBlocked("A future rule requires one reliable, unlocked merchant group and direction.")
            scope = (group.bank, group.merchant_key, group.direction)
        existing = self._scope_rule(scope)
        token = uuid4().hex
        self.pending = ("assignment", token, rows, category_id, scope, existing)
        return {"token": token, "rows": rows, "category_id": category_id,
                "scope": scope, "replaces_rule": existing is not None}

    def _scope_rule(self, scope):
        if scope is None:
            return None
        return next((r for r in self.repository.list_rules(include_disabled=True)
                     if (r["bank"], r["merchant_key"], r["direction"]) == scope), None)

    def confirm_assignment(self, token):
        if self.pending is None or self.pending[:2] != ("assignment", token):
            raise ReviewBlocked("Create a new assignment preview.")
        _, _, rows, category, scope, old_rule = self.pending
        with self.repository.atomic():
            if any(self.repository.get_transaction(r["id"]) != r for r in rows):
                raise ReviewBlocked("Selected transactions changed; cancel and preview again.")
            if self._scope_rule(scope) != old_rule:
                raise ReviewBlocked("The merchant rule changed; cancel and preview again.")
            count = self.classification.assign_category([r["id"] for r in rows], category)
            rule_id = self.classification.save_rule(*scope, category) if scope else None
        self.pending = None
        return {"count": count, "rule_id": rule_id}

    def save_assignment(self, transaction_ids, category_id, save_rule=False):
        preview = self.preview_assignment(transaction_ids, category_id, save_rule=save_rule)
        return self.confirm_assignment(preview["token"])

    def preview_rule(self, rule_id):
        self._idle()
        preview = self.classification.preview_rule(rule_id)
        self.pending = ("rule", preview.token, preview)
        return preview

    def apply_rule(self, token, transaction_ids):
        if self.pending is None or self.pending[:2] != ("rule", token):
            raise ReviewBlocked("Create a new rule preview.")
        if not transaction_ids:
            raise ReviewBlocked("Select the eligible rows to apply; no rows are selected by default.")
        count = self.classification.apply_rule(self.pending[2], transaction_ids)
        self.pending = None
        return {"count": count}

    def cancel(self):
        if self.pending is not None and self.pending[0] == "rule":
            self.classification.cancel_rule_preview(self.pending[2])
        self.pending = None

    def change_rule(self, rule_id, revision, category_id=None, disable=False):
        self._idle()
        with self.repository.atomic():
            rule = self.repository.get_rule(rule_id)
            if rule["revision"] != revision:
                raise ReviewBlocked("The rule changed; refresh before editing it.")
            if disable:
                self.classification.disable_rule(rule_id)
            else:
                self._category(category_id, [-1 if rule["direction"] == "debit" else 1])
                self.classification.save_rule(rule["bank"], rule["display_text"], rule["direction"], category_id)
        return {"rule_id": rule_id}

    def edit_get(self, transaction_id):
        row = self.repository.get_transaction(transaction_id)
        return {"row": row, "revision": classification_revision(row),
                "history": self.repository.get_history(transaction_id)}

    def edit_save(self, transaction_id, revision, fields, clear_protection=False):
        self._idle()
        expected = {"occurred_at", "amount", "description", "merchant_display", "category_id", "kind", "note"}
        if set(fields) != expected or type(clear_protection) is not bool:
            raise ReviewBlocked("Supply only the supported effective edit fields.")
        try:
            occurred_at = validate_iso(fields["occurred_at"].strip())
        except (ValueError, TypeError, AttributeError):
            raise ReviewBlocked("Enter a valid ISO date or date/time (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).") from None
        try:
            amount = money_to_minor(fields["amount"])
        except ValueError:
            raise ReviewBlocked("Enter signed decimal money with at most two decimal places, without grouping.") from None
        kind, category = fields["kind"], fields["category_id"]
        if kind not in KINDS:
            raise ReviewBlocked("Choose a supported transaction kind.")
        if kind in ("income", "expense"):
            selected = self._category(category, [amount])
            if selected["direction"] != kind:
                raise ReviewBlocked("Kind and category must agree. Choose a new category or explicit unclassified status.")
        elif category is not None:
            raise ReviewBlocked("Unclassified, transfer and excluded kinds require no category.")
        if any(not isinstance(fields[k], str) for k in ("description", "merchant_display", "note")):
            raise ReviewBlocked("Description, merchant display and note must be text.")
        with self.repository.atomic():
            row = self.repository.get_transaction(transaction_id)
            if classification_revision(row) != revision:
                raise ReviewBlocked("This transaction changed. Close and reopen the editor before saving.")
            result = self.repository.edit_transaction(
                transaction_id, reason="Manual transaction editor correction", occurred_at=occurred_at,
                amount_minor=amount, description=fields["description"],
                merchant_display=fields["merchant_display"] or None, category_id=category,
                kind=kind, note=fields["note"], manual_lock=not clear_protection)
        return {"row": result}
