"""High-performance dashboard, transaction and tax summary queries."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, case, cast, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.entities import (
    Deduction,
    Document,
    TaxYear,
    Transaction,
    TransactionDirection,
    User,
)
from backend.app.tax.calculator import tax_calculator
from backend.app.tax.rules import RULES

D = Decimal


class SummaryService:
    @staticmethod
    def tax_year(db: Session, financial_year: str) -> TaxYear:
        tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
        if not tax_year:
            raise ValueError(f"Unknown financial year: {financial_year}")
        return tax_year

    def dashboard(self, db: Session, financial_year: str) -> dict:
        tax_year = self.tax_year(db, financial_year)
        base_filters = [Transaction.tax_year_id == tax_year.id]
        safe_income_filters = base_filters + [
            Transaction.direction == TransactionDirection.credit,
            Transaction.ignored.is_(False),
            Transaction.is_duplicate.is_(False),
            Transaction.is_self_transfer.is_(False),
        ]
        gross_credits = self._sum(db, *base_filters, Transaction.direction == TransactionDirection.credit)
        taxable_income = self._sum(db, *safe_income_filters, Transaction.taxable.is_(True))
        exempt_income = self._sum(db, *safe_income_filters, Transaction.exempt.is_(True))
        income_rows = db.execute(
            select(Transaction.income_type, func.coalesce(func.sum(Transaction.credit), 0))
            .where(
                *safe_income_filters,
                Transaction.income_type.is_not(None),
                or_(Transaction.taxable.is_(True), Transaction.exempt.is_(True)),
            )
            .group_by(Transaction.income_type)
        ).all()
        by_income = {str(name or "Other Sources"): float(amount or 0) for name, amount in income_rows}
        category_rows = db.execute(
            select(Transaction.category, func.coalesce(func.sum(Transaction.credit), 0))
            .where(*safe_income_filters)
            .group_by(Transaction.category)
            .order_by(func.sum(Transaction.credit).desc())
            .limit(10)
        ).all()
        monthly_rows = db.execute(
            select(
                func.strftime("%Y-%m", Transaction.transaction_date).label("month"),
                func.coalesce(func.sum(case((Transaction.direction == TransactionDirection.credit, Transaction.amount), else_=0)), 0),
                func.coalesce(func.sum(case((Transaction.direction == TransactionDirection.debit, Transaction.amount), else_=0)), 0),
            )
            .where(*base_filters, Transaction.ignored.is_(False))
            .group_by("month")
            .order_by("month")
        ).all()
        deductions = self.accepted_deductions(db, tax_year.id)
        salary_income = D(str(by_income.get("Salary Income", 0)))
        tds_credit = D("0")
        comparison = tax_calculator.compare(
            financial_year=financial_year,
            gross_taxable_income=taxable_income,
            salary_income=salary_income,
            deductions=deductions,
            age=self._age(db, tax_year.ends_on),
            resident=self._resident(db),
            tds_credit=tds_credit,
        )
        recommended = comparison[comparison["recommended"]]
        review_count = int(
            db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.tax_year_id == tax_year.id,
                    Transaction.needs_review.is_(True),
                    Transaction.review_status == "pending",
                )
            )
            or 0
        )
        duplicate_count = int(
            db.scalar(select(func.count(Transaction.id)).where(Transaction.tax_year_id == tax_year.id, Transaction.is_duplicate.is_(True)))
            or 0
        )
        transfer_count = int(
            db.scalar(select(func.count(Transaction.id)).where(Transaction.tax_year_id == tax_year.id, Transaction.is_self_transfer.is_(True)))
            or 0
        )
        document_count = int(
            db.scalar(
                select(func.count(func.distinct(Transaction.document_id))).where(Transaction.tax_year_id == tax_year.id)
            )
            or 0
        )
        unresolved_credit_count = int(
            db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.tax_year_id == tax_year.id,
                    Transaction.direction == TransactionDirection.credit,
                    Transaction.needs_review.is_(True),
                    Transaction.review_status == "pending",
                    Transaction.ignored.is_(False),
                )
            )
            or 0
        )
        unresolved_credit_amount = self._sum(
            db,
            Transaction.tax_year_id == tax_year.id,
            Transaction.direction == TransactionDirection.credit,
            Transaction.needs_review.is_(True),
            Transaction.review_status == "pending",
            Transaction.ignored.is_(False),
        )
        evidence_types = {"AIS", "TIS", "Form 26AS", "Form 16", "Form 16A"}
        evidence_count = int(
            db.scalar(select(func.count(Document.id)).where(Document.document_type.in_(evidence_types))) or 0
        )
        readiness_warnings: list[str] = []
        if unresolved_credit_count:
            readiness_warnings.append(
                f"{unresolved_credit_count} unresolved credit(s) must be reviewed before the estimate is final."
            )
        if financial_year not in RULES:
            readiness_warnings.append("No configured tax rule set exists for this financial year.")
        if evidence_count == 0:
            readiness_warnings.append("No AIS, TIS, Form 26AS or Form 16 evidence has been imported.")
        tax_ready = not readiness_warnings
        readiness = {
            "status": "ready" if tax_ready else "incomplete",
            "tax_ready": tax_ready,
            "unresolved_credit_count": unresolved_credit_count,
            "unresolved_credit_amount": float(unresolved_credit_amount),
            "authoritative_evidence_count": evidence_count,
            "warnings": readiness_warnings,
        }
        comparison["readiness"] = readiness
        return {
            "financial_year": financial_year,
            "metrics": {
                "gross_credits": float(gross_credits),
                "taxable_income": float(taxable_income),
                "exempt_income": float(exempt_income),
                "interest_income": by_income.get("Interest Income", 0),
                "dividend_income": by_income.get("Dividend Income", 0),
                "capital_gains": by_income.get("Capital Gains", 0),
                "business_income": by_income.get("Business Income", 0),
                "salary_income": by_income.get("Salary Income", 0),
                "rental_income": by_income.get("Rental Income", 0),
                "agricultural_income": by_income.get("Agricultural Income", 0),
                "other_sources": by_income.get("Other Sources", 0),
                "total_deductions": float(sum(deductions.values(), D("0"))),
                "net_taxable_income": recommended["net_taxable_income"],
                "estimated_tax": recommended["total_tax"],
                "refund_estimate": recommended["refund_estimate"],
            },
            "income_breakdown": [{"name": key, "value": value} for key, value in sorted(by_income.items()) if value],
            "category_breakdown": [{"name": name or "Other", "value": float(amount)} for name, amount in category_rows],
            "monthly_flow": [
                {"month": month, "credits": float(credits), "debits": float(debits)}
                for month, credits, debits in monthly_rows
            ],
            "quality": {
                "review_count": review_count,
                "duplicate_count": duplicate_count,
                "self_transfer_count": transfer_count,
                "document_count": document_count,
                "unresolved_credit_count": unresolved_credit_count,
            },
            "readiness": readiness,
            "tax_comparison": comparison,
        }

    def tax_comparison(self, db: Session, financial_year: str) -> dict:
        dashboard = self.dashboard(db, financial_year)
        return dashboard["tax_comparison"]

    @staticmethod
    def accepted_deductions(db: Session, tax_year_id: int) -> dict[str, Decimal]:
        rows = db.execute(
            select(Deduction.section, func.coalesce(func.sum(Deduction.amount_eligible), 0))
            .where(Deduction.tax_year_id == tax_year_id, Deduction.accepted.is_(True))
            .group_by(Deduction.section)
        ).all()
        return {section: Decimal(amount) for section, amount in rows}

    @staticmethod
    def transaction_query(
        tax_year_id: int | None = None,
        *,
        search: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        income_type: str | None = None,
        account_id: int | None = None,
        month: int | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        review_only: bool = False,
    ):
        query = select(Transaction, Document.filename, Document.document_type).outerjoin(Document, Transaction.document_id == Document.id)
        filters = []
        if tax_year_id:
            filters.append(Transaction.tax_year_id == tax_year_id)
        if search:
            token = f"%{search}%"
            filters.append(
                or_(
                    Transaction.description.ilike(token),
                    Transaction.counterparty.ilike(token),
                    Transaction.reference_number.ilike(token),
                    Transaction.utr.ilike(token),
                )
            )
        if bank:
            filters.append(Transaction.bank_name == bank)
        if category:
            filters.append(Transaction.category == category)
        if income_type:
            filters.append(Transaction.income_type == income_type)
        if account_id:
            filters.append(Transaction.account_id == account_id)
        if month:
            filters.append(cast(func.strftime("%m", Transaction.transaction_date), Integer) == month)
        if min_amount is not None:
            filters.append(Transaction.amount >= min_amount)
        if max_amount is not None:
            filters.append(Transaction.amount <= max_amount)
        if review_only:
            filters.extend([Transaction.needs_review.is_(True), Transaction.review_status == "pending"])
        return query.where(*filters).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())

    @staticmethod
    def _sum(db: Session, *filters) -> Decimal:  # type: ignore[no-untyped-def]
        value = db.scalar(select(func.coalesce(func.sum(Transaction.credit), 0)).where(*filters))
        return Decimal(value or 0)

    @staticmethod
    def _resident(db: Session) -> bool:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        return bool(user.resident) if user else True

    @staticmethod
    def _age(db: Session, on_date: date) -> int:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        return tax_calculator.age_on(user.birth_date if user else None, on_date)


summary_service = SummaryService()
