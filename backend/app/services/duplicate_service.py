"""Cross-document duplicate detection with amount/date/reference/fuzzy confidence scoring."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.entities import Document, Transaction

SOURCE_PRIORITY = {
    "Bank Statement": 100,
    "Credit Card Statement": 95,
    "Broker Ledger": 90,
    "Mutual Fund Statement": 88,
    "Salary Slip": 80,
    "Form 16": 75,
    "Form 16A": 75,
    "AIS": 65,
    "Form 26AS": 65,
    "TIS": 60,
    "Unknown": 50,
}


class DuplicateDetector:
    def __init__(self) -> None:
        settings = get_settings()
        self.day_window = settings.duplicate_day_window
        self.amount_tolerance = Decimal(str(settings.duplicate_amount_tolerance))

    def process(self, db: Session, transaction_ids: list[int]) -> int:
        count = 0
        for transaction_id in transaction_ids:
            tx = db.get(Transaction, transaction_id)
            if tx is None or tx.is_duplicate:
                continue
            lower_date = tx.transaction_date - timedelta(days=self.day_window)
            upper_date = tx.transaction_date + timedelta(days=self.day_window)
            candidates = db.scalars(
                select(Transaction).where(
                    and_(
                        Transaction.id != tx.id,
                        Transaction.transaction_date.between(lower_date, upper_date),
                        Transaction.direction == tx.direction,
                        Transaction.amount.between(tx.amount - self.amount_tolerance, tx.amount + self.amount_tolerance),
                        Transaction.ignored.is_(False),
                    )
                ).limit(50)
            ).all()
            best: tuple[float, Transaction] | None = None
            for candidate in candidates:
                if candidate.document_id == tx.document_id and candidate.source_row == tx.source_row:
                    continue
                if candidate.document_id == tx.document_id and not self._same_document_identity(tx, candidate):
                    # Repeated rent, SIP, EMI and merchant payments inside one statement
                    # are legitimate unless the statement supplies the same durable ID.
                    continue
                score = self.score(tx, candidate)
                if score >= 86 and (best is None or score > best[0]):
                    best = (score, candidate)
            if best:
                score, candidate = best
                if candidate.document_id != tx.document_id and score < 94:
                    tx.duplicate_confidence = score
                    tx.needs_review = True
                    tx.raw_data = {**(tx.raw_data or {}), "possible_duplicate_of": candidate.id}
                    continue
                canonical, duplicate = self._choose_canonical(db, tx, candidate)
                duplicate.is_duplicate = True
                duplicate.duplicate_of_id = canonical.id
                duplicate.duplicate_confidence = score
                duplicate.ignored = True
                duplicate.needs_review = score < 94
                count += 1
        db.commit()
        return count

    @staticmethod
    def _same_document_identity(left: Transaction, right: Transaction) -> bool:
        return bool(
            (left.utr and right.utr and left.utr.upper() == right.utr.upper())
            or (
                left.reference_number
                and right.reference_number
                and left.reference_number.upper() == right.reference_number.upper()
            )
        )

    @staticmethod
    def score(left: Transaction, right: Transaction) -> float:
        left_member_hash = (left.raw_data or {}).get("archive_member_sha256")
        right_member_hash = (right.raw_data or {}).get("archive_member_sha256")
        if (
            left_member_hash
            and left_member_hash == right_member_hash
            and left.source_row == right.source_row
        ):
            return 100.0
        score = 45.0  # amount/date already constrained
        day_gap = abs((left.transaction_date - right.transaction_date).days)
        score += max(0, 15 - day_gap * 5)
        if left.utr and right.utr and left.utr.upper() == right.utr.upper():
            score += 35
        elif left.reference_number and right.reference_number and left.reference_number.upper() == right.reference_number.upper():
            score += 30
        narration_score = token_set_ratio(left.description or "", right.description or "")
        score += narration_score * 0.25
        if left.counterparty and right.counterparty:
            score += token_set_ratio(left.counterparty, right.counterparty) * 0.1
        return min(100.0, score)

    @staticmethod
    def _choose_canonical(db: Session, left: Transaction, right: Transaction) -> tuple[Transaction, Transaction]:
        left_doc = db.get(Document, left.document_id) if left.document_id else None
        right_doc = db.get(Document, right.document_id) if right.document_id else None
        left_priority = SOURCE_PRIORITY.get(left_doc.document_type if left_doc else "Unknown", 50)
        right_priority = SOURCE_PRIORITY.get(right_doc.document_type if right_doc else "Unknown", 50)
        if left_priority == right_priority:
            return (left, right) if left.id < right.id else (right, left)
        return (left, right) if left_priority > right_priority else (right, left)
