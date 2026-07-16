"""Normalized database entities used by the local ITR preparation system."""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    password_required = "password_required"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    ignored = "ignored"
    merged = "merged"


class TransactionDirection(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="Local User")
    pan: Mapped[str | None] = mapped_column(String(16), index=True)
    aadhaar_last4: Mapped[str | None] = mapped_column(String(4))
    mobile: Mapped[str | None] = mapped_column(String(20))
    upi_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    customer_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    resident: Mapped[bool] = mapped_column(Boolean, default=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    accounts: Mapped[list[Account]] = relationship(back_populates="user")


class Bank(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    ifsc_prefix: Mapped[str | None] = mapped_column(String(8))

    accounts: Mapped[list[Account]] = relationship(back_populates="bank")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "masked_number", "bank_id", name="uq_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bank_id: Mapped[int | None] = mapped_column(ForeignKey("banks.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="Imported Account")
    masked_number: Mapped[str | None] = mapped_column(String(32), index=True)
    account_type: Mapped[str | None] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(160))
    ifsc: Mapped[str | None] = mapped_column(String(16), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_owned: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="accounts")
    bank: Mapped[Bank | None] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")


class TaxYear(Base):
    __tablename__ = "tax_years"

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_year: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    assessment_year: Mapped[str] = mapped_column(String(12))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_version: Mapped[str] = mapped_column(String(30), default="builtin")


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)

    documents: Mapped[list[Document]] = relationship(back_populates="import_session")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_session_id: Mapped[str] = mapped_column(ForeignKey("import_sessions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    stored_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    document_type: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.uploaded, index=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    parser_used: Mapped[str | None] = mapped_column(String(80))
    detected_bank: Mapped[str | None] = mapped_column(String(120))
    detected_account: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    import_session: Mapped[ImportSession] = relationship(back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(back_populates="document", cascade="all, delete-orphan")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="document")


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    extraction_method: Mapped[str] = mapped_column(String(30), default="text")
    text_content: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    document: Mapped[Document] = relationship(back_populates="pages")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_date_amount", "transaction_date", "amount"),
        Index("ix_tx_review", "needs_review", "review_status"),
        Index("ix_tx_income", "income_type", "taxable"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    tax_year_id: Mapped[int | None] = mapped_column(ForeignKey("tax_years.id"), index=True)
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")
    narration: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, index=True)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    direction: Mapped[TransactionDirection] = mapped_column(Enum(TransactionDirection), index=True)
    reference_number: Mapped[str | None] = mapped_column(String(160), index=True)
    utr: Mapped[str | None] = mapped_column(String(80), index=True)
    ifsc: Mapped[str | None] = mapped_column(String(16))
    cheque_number: Mapped[str | None] = mapped_column(String(40))
    mode: Mapped[str | None] = mapped_column(String(30), index=True)
    category: Mapped[str] = mapped_column(String(80), default="Other", index=True)
    income_type: Mapped[str | None] = mapped_column(String(80), index=True)
    counterparty: Mapped[str | None] = mapped_column(String(200), index=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), index=True)
    branch: Mapped[str | None] = mapped_column(String(160))
    taxable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    already_taxed: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    duplicate_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    is_self_transfer: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    linked_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    source_row: Mapped[int | None] = mapped_column(Integer)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[Document | None] = relationship(back_populates="transactions")
    account: Mapped[Account | None] = relationship(back_populates="transactions")


class Income(Base):
    __tablename__ = "income"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    income_type: Mapped[str] = mapped_column(String(80), index=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    exempt_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    tax_year_id: Mapped[int | None] = mapped_column(ForeignKey("tax_years.id"), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    business_use_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    deductible: Mapped[bool] = mapped_column(Boolean, default=False)


class Investment(Base):
    __tablename__ = "investments"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    tax_year_id: Mapped[int | None] = mapped_column(ForeignKey("tax_years.id"), index=True)
    instrument_type: Mapped[str] = mapped_column(String(80), index=True)
    symbol_or_folio: Mapped[str | None] = mapped_column(String(120), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    transaction_kind: Mapped[str] = mapped_column(String(30))
    transaction_date: Mapped[date] = mapped_column(Date)


class Deduction(Base):
    __tablename__ = "deductions"
    __table_args__ = (UniqueConstraint("tax_year_id", "section", "evidence_document_id", name="uq_deduction_evidence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    section: Mapped[str] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(String(240))
    amount_claimed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount_eligible: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    evidence_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)


class CapitalGain(Base):
    __tablename__ = "capital_gains"
    id: Mapped[int] = mapped_column(primary_key=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(80), index=True)
    symbol_or_folio: Mapped[str | None] = mapped_column(String(120), index=True)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    sale_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    sale_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    indexed_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gain_type: Mapped[str] = mapped_column(String(20), index=True)
    gain_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    calculation_method: Mapped[str] = mapped_column(String(30), default="FIFO")


class Interest(Base):
    __tablename__ = "interest"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    interest_type: Mapped[str] = mapped_column(String(50), index=True)
    payer: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tds: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class Dividend(Base):
    __tablename__ = "dividends"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    company_or_fund: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tds: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class TDS(Base):
    __tablename__ = "tds"
    id: Mapped[int] = mapped_column(primary_key=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    deductor_name: Mapped[str | None] = mapped_column(String(200))
    deductor_tan: Mapped[str | None] = mapped_column(String(16), index=True)
    section: Mapped[str | None] = mapped_column(String(20))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_deducted: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_deposited: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    mismatch: Mapped[str | None] = mapped_column(Text)


class AISEntry(Base):
    __tablename__ = "ais_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    information_code: Mapped[str | None] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    reported_on: Mapped[date | None] = mapped_column(Date)
    source_name: Mapped[str | None] = mapped_column(String(200))
    linked_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    reconciliation_status: Mapped[str] = mapped_column(String(30), default="unmatched", index=True)


class Form26ASEntry(Base):
    __tablename__ = "form_26as_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    tax_year_id: Mapped[int] = mapped_column(ForeignKey("tax_years.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    deductor_name: Mapped[str | None] = mapped_column(String(200))
    tan: Mapped[str | None] = mapped_column(String(16), index=True)
    section: Mapped[str | None] = mapped_column(String(20))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tds_deposited: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    linked_tds_id: Mapped[int | None] = mapped_column(ForeignKey("tds.id"))
    reconciliation_status: Mapped[str] = mapped_column(String(30), default="unmatched", index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO", index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    reason: Mapped[str] = mapped_column(String(200), index=True)
    suggested_action: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), default=ReviewStatus.pending, index=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class ClassificationRule(Base):
    """Locally learned narration rule created from an explicit user decision."""

    __tablename__ = "classification_rules"
    __table_args__ = (
        UniqueConstraint("normalized_pattern", "direction", name="uq_classification_rule_pattern"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_pattern: Mapped[str] = mapped_column(String(240), index=True)
    direction: Mapped[str] = mapped_column(String(12), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    income_type: Mapped[str | None] = mapped_column(String(80), index=True)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
