"""Self-transfer matching across owned accounts with reference, name, and narration similarity."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.entities import Account, Transaction, TransactionDirection, User


class SelfTransferDetector:
    def __init__(self) -> None:
        self.day_window = get_settings().self_transfer_day_window

    def process(self, db: Session, transaction_ids: list[int]) -> int:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        user_name_parts: set[str] = set()
        user_upi_parts: set[str] = set()
        if user:
            if user.name and user.name.strip():
                for word in user.name.split():
                    w = word.lower().strip()
                    if len(w) >= 3 and w not in {"mr", "mrs", "dr", "shri", "smt"}:
                        user_name_parts.add(w)
            if user.upi_ids:
                for upi in user.upi_ids:
                    user_upi_parts.add(upi.lower().strip())

        matched = 0
        for transaction_id in transaction_ids:
            tx = db.get(Transaction, transaction_id)
            if tx is None or tx.is_duplicate or tx.amount <= 0:
                continue

            desc_lower = (tx.description or "").lower()
            counterparty_lower = (tx.counterparty or "").lower()

            # 1. Taxpayer Name Match
            name_match = False
            if user_name_parts:
                matched_parts = sum(1 for part in user_name_parts if part in desc_lower or part in counterparty_lower)
                if len(user_name_parts) >= 2 and matched_parts >= 2:
                    name_match = True
                elif len(user_name_parts) == 1 and matched_parts == 1:
                    name_match = True

            # 2. Taxpayer UPI Match
            upi_match = False
            if user_upi_parts:
                upi_match = any(upi in desc_lower or upi in counterparty_lower for upi in user_upi_parts)

            # 3. Explicit Self Transfer Keywords
            self_keywords = (
                "self transfer", "own account", "internal transfer", "trf to self",
                "trf from self", "transfer to own", "to self", "by self", "self cr",
                "self dr", "self deposit", "to own a/c", "from own a/c"
            )
            keyword_match = any(kw in desc_lower or kw in counterparty_lower for kw in self_keywords)

            # 4. Cross-account transfer candidate matching
            opposite = TransactionDirection.debit if tx.direction == TransactionDirection.credit else TransactionDirection.credit
            candidates = db.scalars(
                select(Transaction).where(
                    and_(
                        Transaction.id != tx.id,
                        Transaction.direction == opposite,
                        Transaction.amount.between(tx.amount - Decimal("1.00"), tx.amount + Decimal("1.00")),
                        Transaction.transaction_date.between(
                            tx.transaction_date - timedelta(days=self.day_window),
                            tx.transaction_date + timedelta(days=self.day_window),
                        ),
                        Transaction.is_duplicate.is_(False),
                    )
                ).limit(40)
            ).all()
            best: tuple[float, Transaction] | None = None
            for candidate in candidates:
                if candidate.account_id and tx.account_id and candidate.account_id == tx.account_id:
                    continue
                score = self.score(tx, candidate)
                if score >= 75 and (best is None or score > best[0]):
                    best = (score, candidate)

            if best:
                score, candidate = best
                for item, other in ((tx, candidate), (candidate, tx)):
                    item.is_self_transfer = True
                    item.linked_transaction_id = other.id
                    item.category = "Self Transfer"
                    item.taxable = False
                    item.exempt = False
                    item.ignored = True
                    item.needs_review = False
                    item.confidence = max(float(item.confidence or 0), score)
                matched += 1
            elif name_match or upi_match or keyword_match:
                tx.is_self_transfer = True
                tx.category = "Self Transfer"
                tx.taxable = False
                tx.exempt = False
                tx.ignored = True
                tx.needs_review = False
                tx.confidence = 98.0
                matched += 1

        db.commit()
        return matched

    @staticmethod
    def _ownership_confirmed(account: Account | None) -> bool:
        return bool(
            account
            and account.is_owned
            and (account.metadata_json or {}).get("ownership_confirmed") is True
        )

    @staticmethod
    def score(left: Transaction, right: Transaction) -> float:
        score = 50.0
        gap = abs((left.transaction_date - right.transaction_date).days)
        score += max(0, 15 - gap * 5)
        if left.utr and right.utr and left.utr.upper() == right.utr.upper():
            score += 35
        elif left.reference_number and right.reference_number and left.reference_number.upper() == right.reference_number.upper():
            score += 30
        narration = token_set_ratio(left.description or "", right.description or "")
        score += narration * 0.2
        if any(token in (left.description + " " + right.description).lower() for token in ("self", "own", "internal")):
            score += 12
        return min(100.0, score)
