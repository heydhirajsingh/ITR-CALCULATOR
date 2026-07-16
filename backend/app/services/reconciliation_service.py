"""AIS and Form 26AS reconciliation summaries based on linked and duplicate transactions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import Document, TaxYear, Transaction


class ReconciliationService:
    def report(self, db: Session, financial_year: str, source_type: str) -> dict:
        tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
        if not tax_year:
            raise ValueError("Unknown financial year")
        source_transactions = db.scalars(
            select(Transaction)
            .join(Document, Transaction.document_id == Document.id)
            .where(Transaction.tax_year_id == tax_year.id, Document.document_type == source_type)
            .order_by(Transaction.transaction_date.desc())
        ).all()
        rows = []
        counts = {"matched": 0, "missing": 0, "duplicate": 0, "mismatch": 0}
        for tx in source_transactions:
            if tx.is_duplicate and tx.duplicate_of_id:
                status = "matched"
                counts["matched"] += 1
                counts["duplicate"] += 1
            elif tx.linked_transaction_id:
                status = "matched"
                counts["matched"] += 1
            else:
                status = "missing_in_other_sources"
                counts["missing"] += 1
            rows.append(
                {
                    "id": tx.id,
                    "date": tx.transaction_date.isoformat(),
                    "description": tx.description,
                    "amount": float(tx.amount),
                    "status": status,
                    "linked_transaction_id": tx.duplicate_of_id or tx.linked_transaction_id,
                    "confidence": float(tx.duplicate_confidence or tx.confidence or 0),
                }
            )
        return {"source": source_type, "financial_year": financial_year, "counts": counts, "items": rows}


reconciliation_service = ReconciliationService()
