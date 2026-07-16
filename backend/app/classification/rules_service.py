"""Persistent, user-approved narration rules for repeatable local classification."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.classification.engine import classifier
from backend.app.models.entities import ClassificationRule, Income, Transaction, TransactionDirection


REFERENCE_TOKEN = re.compile(r"\b(?:[a-z]*\d[a-z0-9]*|\d+[a-z][a-z0-9]*)\b", re.IGNORECASE)
NOISE_TOKENS = {
    "upi", "neft", "rtgs", "imps", "ach", "nach", "txn", "transaction", "ref", "reference",
    "cr", "dr", "credit", "debit", "transfer", "payment", "inr",
}


def narration_pattern(value: str) -> str:
    """Create a stable but conservative signature without account/reference identifiers."""
    normalized = classifier.normalize(value)
    normalized = REFERENCE_TOKEN.sub(" ", normalized)
    tokens = [token for token in normalized.split() if token not in NOISE_TOKENS and len(token) > 1]
    return " ".join(tokens[:16])[:240] or "unidentified narration"


@dataclass(slots=True)
class LearnedClassification:
    category: str
    income_type: str | None
    counterparty: str | None
    taxable: bool
    exempt: bool
    ignored: bool
    reason: str


class ClassificationRuleService:
    def match(self, db: Session, description: str, direction: str) -> LearnedClassification | None:
        pattern = narration_pattern(description)
        rule = db.scalar(
            select(ClassificationRule).where(
                ClassificationRule.normalized_pattern == pattern,
                ClassificationRule.direction == direction,
            )
        )
        if rule is None:
            return None
        rule.hit_count += 1
        return LearnedClassification(
            category=rule.category,
            income_type=rule.income_type,
            counterparty=rule.counterparty,
            taxable=rule.taxable,
            exempt=rule.exempt,
            ignored=rule.ignored,
            reason="matched a user-approved local narration rule",
        )

    @staticmethod
    def save(
        db: Session,
        *,
        pattern: str,
        direction: str,
        category: str,
        income_type: str | None,
        counterparty: str | None,
        taxable: bool,
        exempt: bool,
        ignored: bool,
    ) -> ClassificationRule:
        normalized = narration_pattern(pattern)
        rule = db.scalar(
            select(ClassificationRule).where(
                ClassificationRule.normalized_pattern == normalized,
                ClassificationRule.direction == direction,
            )
        )
        if rule is None:
            rule = ClassificationRule(normalized_pattern=normalized, direction=direction, category=category)
            db.add(rule)
        rule.category = category
        rule.income_type = income_type
        rule.counterparty = counterparty
        rule.taxable = taxable
        rule.exempt = exempt
        rule.ignored = ignored
        return rule

    @staticmethod
    def apply_to_matching(db: Session, rule: ClassificationRule, tax_year_id: int | None = None) -> int:
        direction = TransactionDirection(rule.direction)
        query = select(Transaction).where(Transaction.direction == direction)
        if tax_year_id is not None:
            query = query.where(Transaction.tax_year_id == tax_year_id)
        count = 0
        for transaction in db.scalars(query).all():
            if narration_pattern(transaction.description) != rule.normalized_pattern:
                continue
            transaction.category = rule.category
            transaction.income_type = rule.income_type
            transaction.counterparty = rule.counterparty or transaction.counterparty
            transaction.taxable = rule.taxable
            transaction.exempt = rule.exempt
            transaction.ignored = rule.ignored
            transaction.needs_review = False
            transaction.review_status = "accepted"
            transaction.user_override = True
            income = db.scalar(select(Income).where(Income.transaction_id == transaction.id))
            if transaction.direction == TransactionDirection.credit and rule.income_type:
                if income is None:
                    income = Income(
                        transaction_id=transaction.id,
                        tax_year_id=transaction.tax_year_id,
                        income_type=rule.income_type,
                        gross_amount=transaction.amount,
                        taxable_amount=transaction.amount if rule.taxable else 0,
                        exempt_amount=transaction.amount if rule.exempt else 0,
                        notes="User-approved narration rule",
                    )
                    db.add(income)
                else:
                    income.income_type = rule.income_type
                    income.gross_amount = transaction.amount
                    income.taxable_amount = transaction.amount if rule.taxable else 0
                    income.exempt_amount = transaction.amount if rule.exempt else 0
            count += 1
        return count


classification_rule_service = ClassificationRuleService()
