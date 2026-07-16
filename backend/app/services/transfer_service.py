"""Self-transfer matching across owned accounts with reference and narration similarity."""
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
        matched = 0
        for transaction_id in transaction_ids:
            tx = db.get(Transaction, transaction_id)
            if tx is None or tx.is_self_transfer or tx.is_duplicate or tx.amount <= 0:
                continue
            source_account = db.get(Account, tx.account_id) if tx.account_id else None
            if not self._ownership_confirmed(source_account):
                continue
            opposite = TransactionDirection.debit if tx.direction == TransactionDirection.credit else TransactionDirection.credit
            candidates = db.scalars(
                select(Transaction).join(Account, Transaction.account_id == Account.id).where(
                    and_(
                        Transaction.id != tx.id,
                        Transaction.direction == opposite,
                        Transaction.amount.between(tx.amount - Decimal("1.00"), tx.amount + Decimal("1.00")),
                        Transaction.transaction_date.between(
                            tx.transaction_date - timedelta(days=self.day_window),
                            tx.transaction_date + timedelta(days=self.day_window),
                        ),
                        Account.is_owned.is_(True),
                        Transaction.is_duplicate.is_(False),
                    )
                ).limit(40)
            ).all()
            best: tuple[float, Transaction] | None = None
            for candidate in candidates:
                if candidate.account_id == tx.account_id:
                    continue
                candidate_account = db.get(Account, candidate.account_id) if candidate.account_id else None
                if not self._ownership_confirmed(candidate_account):
                    continue
                score = self.score(tx, candidate)
                if score >= 82 and (best is None or score > best[0]):
                    best = (score, candidate)
            if best:
                score, candidate = best
                for item, other in ((tx, candidate), (candidate, tx)):
                    item.is_self_transfer = True
                    item.linked_transaction_id = other.id
                    item.category = "Transfer"
                    item.taxable = False
                    item.exempt = False
                    item.ignored = True
                    item.needs_review = score < 92
                    item.confidence = max(float(item.confidence or 0), score)
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
