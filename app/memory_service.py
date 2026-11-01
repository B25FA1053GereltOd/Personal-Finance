"""Local classification memory and time-based suggestions service."""

from collections.abc import Iterable
from datetime import datetime

from app.db import Repository
from app.models import normalize_merchant_key


class MemoryService:
    def __init__(self, repository: Repository):
        self.repository = repository
        self._rejected_suggestions: set[int] = set()

    def save_memory_from_transaction(self, row: dict, category_id: int) -> int:
        """Extract match field and save a reusable local memory record."""
        pos_id = row.get("pos_id")
        merchant = row.get("merchant_key") or row.get("merchant_display")
        description = row.get("original_description") or row.get("description")

        if pos_id and str(pos_id).strip():
            match_field = "pos_id"
            match_value = str(pos_id).strip()
        elif merchant and str(merchant).strip():
            match_field = "merchant"
            match_value = str(merchant).strip()
        elif description and str(description).strip():
            match_field = "description"
            match_value = str(description).strip()
        else:
            return 0

        direction = "debit" if row.get("amount_minor", 0) < 0 else "credit"
        bank = row.get("bank")
        if not bank and row.get("import_id"):
            try:
                imp = self.repository._one("imports", row["import_id"])
                acc = self.repository._one("accounts", imp["account_id"])
                bank = acc.get("bank")
            except Exception:
                pass

        return self.repository.save_classification_memory(
            match_field=match_field,
            match_value=match_value,
            category_id=category_id,
            direction=direction,
            bank=bank,
        )

    def find_suggestions(self, rows: list[dict]) -> list[dict]:
        """Compute AI/local suggestions for unclassified transactions."""
        suggestions = []
        time_rules = self.repository.list_time_rules(active=True)

        for row in rows:
            tx_id = row["id"]
            if tx_id in self._rejected_suggestions:
                continue
            if row.get("manual_lock") or (row.get("kind") != "unclassified" and row.get("category_id") is not None):
                continue

            # 1. Check local memory first (highest confidence)
            mem = self.repository.match_classification_memory(row)
            if mem is not None:
                suggestions.append({
                    "transaction_id": tx_id,
                    "category_id": mem["category_id"],
                    "category_name": mem["category_name"],
                    "confidence": "high",
                    "reason": f"Confirmed memory: {mem['match_value']}",
                    "source": "manual_memory",
                    "memory_id": mem["id"],
                    "rule_id": None,
                })
                continue

            # 2. Check time suggestion rules
            time_match = self._match_time_rules(row, time_rules)
            if time_match is not None:
                suggestions.append(time_match)

        return suggestions

    def _match_time_rules(self, row: dict, rules: list[dict]) -> dict | None:
        occurred = row.get("occurred_at")
        if not occurred:
            return None
        try:
            dt = datetime.fromisoformat(occurred.replace(" ", "T"))
        except Exception:
            return None

        weekday = dt.weekday()  # 0=Monday, 6=Sunday
        time_str = f"{dt.hour:02d}:{dt.minute:02d}"
        amount_dir = "debit" if row.get("amount_minor", 0) < 0 else "credit"

        desc_raw = str(row.get("original_description") or row.get("description") or "").strip()
        desc = normalize_merchant_key(desc_raw) if desc_raw else ""
        pos_raw = str(row.get("pos_id") or "").strip()
        pos = normalize_merchant_key(pos_raw) if pos_raw else ""
        m_raw = str(row.get("merchant_display") or row.get("merchant_key") or "").strip()
        merchant = normalize_merchant_key(m_raw) if m_raw else ""

        for rule in rules:
            if rule["target_kind"] != ("expense" if amount_dir == "debit" else "income"):
                continue
            weekdays = rule.get("weekdays_list") or []
            if weekday not in weekdays:
                continue
            if not (rule["start_time"] <= time_str <= rule["end_time"]):
                continue

            # Condition check
            m_field = rule.get("match_field")
            m_val = rule.get("match_value")
            if m_field and m_val and str(m_val).strip():
                norm_val = normalize_merchant_key(str(m_val).strip())
                matched = False
                if m_field == "pos_id" and pos and norm_val in pos:
                    matched = True
                elif m_field == "merchant" and merchant and norm_val in merchant:
                    matched = True
                elif m_field == "description" and desc and norm_val in desc:
                    matched = True
                if matched:
                    return {
                        "transaction_id": row["id"],
                        "category_id": rule["category_id"],
                        "category_name": rule["category_name"],
                        "confidence": "high",
                        "reason": f"{rule['name']} ({rule['start_time']}–{rule['end_time']} + {m_val})",
                        "source": "time_rule",
                        "memory_id": None,
                        "rule_id": rule["id"],
                    }
            elif not m_field and not m_val:
                # Time-only rule -> low confidence
                return {
                    "transaction_id": row["id"],
                    "category_id": rule["category_id"],
                    "category_name": rule["category_name"],
                    "confidence": "low",
                    "reason": f"{rule['name']} ({rule['start_time']}–{rule['end_time']})",
                    "source": "time_rule",
                    "memory_id": None,
                    "rule_id": rule["id"],
                }

        return None

    def accept_suggestion(self, transaction_id: int, category_id: int, reason: str = "Accepted AI suggestion") -> dict:
        row = self.repository.get_transaction(transaction_id)
        if row.get("manual_lock"):
            raise ValueError("Transaction is manually protected.")
        # Assign category
        self.repository.assign_category(transaction_id, category_id, reason=reason)
        # Update classification source to manual_memory
        now_row = self.repository.get_transaction(transaction_id)
        # Save to reusable local memory
        mem_id = self.save_memory_from_transaction(now_row, category_id)
        if mem_id:
            with self.repository._write():
                self.repository._connection.execute(
                    "UPDATE transactions SET applied_memory_id = ? WHERE id = ?",
                    (mem_id, transaction_id),
                )
                self.repository.increment_memory_usage(mem_id)
        self._rejected_suggestions.discard(transaction_id)
        return self.repository.get_transaction(transaction_id)

    def reject_suggestion(self, transaction_id: int) -> None:
        self._rejected_suggestions.add(transaction_id)

    def edit_suggestion(self, transaction_id: int, new_category_id: int, reason: str = "Edited suggestion") -> dict:
        return self.accept_suggestion(transaction_id, new_category_id, reason=reason)

    def classify_import(self, import_id: int) -> int:
        """Auto-classify unclassified transactions in an import using memory and enabled auto-classify rules."""
        count = 0
        time_rules = [r for r in self.repository.list_time_rules(active=True) if r.get("auto_classify")]

        for row in self.repository.classification_rows(import_id=import_id):
            if row.get("manual_lock") or (row.get("kind") != "unclassified" and row.get("category_id") is not None):
                continue

            # 1. Match local memory
            mem = self.repository.match_classification_memory(row)
            if mem is not None:
                self.repository.apply_memory_classification(row["id"], mem["id"])
                count += 1
                continue

            # 2. Match auto-classify time rules
            time_match = self._match_time_rules(row, time_rules)
            if time_match is not None and time_match.get("confidence") == "high":
                self.accept_suggestion(row["id"], time_match["category_id"], reason=f"Auto time rule: {time_match['reason']}")
                count += 1

        return count
