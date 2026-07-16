"""Pydantic request and response schemas for API boundaries."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class PasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class TransactionUpdate(BaseModel):
    category: str | None = None
    income_type: str | None = None
    taxable: bool | None = None
    exempt: bool | None = None
    ignored: bool | None = None
    needs_review: bool | None = None
    counterparty: str | None = None
    description: str | None = None


class TransactionSplit(BaseModel):
    parts: list[Decimal] = Field(min_length=2)
    categories: list[str] | None = None


class ReviewAction(BaseModel):
    action: Literal["accept", "reject", "ignore", "merge"]
    notes: str | None = None
    merge_with_transaction_id: int | None = None


class ReviewGroupAction(BaseModel):
    financial_year: str
    pattern: str = Field(min_length=2, max_length=240)
    direction: Literal["credit", "debit"]
    category: str = Field(min_length=1, max_length=80)
    income_type: str | None = Field(default=None, max_length=80)
    counterparty: str | None = Field(default=None, max_length=200)
    taxable: bool = False
    exempt: bool = False
    ignored: bool = False
    save_rule: bool = True


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    is_owned: bool | None = None


class DocumentUpdate(BaseModel):
    document_type: str | None = Field(default=None, max_length=80)
    detected_bank: str | None = Field(default=None, max_length=120)
    detected_account: str | None = Field(default=None, max_length=64)


class DocumentAccountMerge(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=200)
    target_account_id: int | None = None
    bank_name: str | None = Field(default=None, max_length=120)
    account_name: str | None = Field(default=None, max_length=160)
    account_number: str | None = Field(default=None, max_length=32)


class DeductionCreate(BaseModel):
    financial_year: str
    section: str
    description: str
    amount_claimed: Decimal = Field(ge=0)
    amount_eligible: Decimal | None = Field(default=None, ge=0)
    accepted: bool = True


class UserProfileUpdate(BaseModel):
    name: str | None = None
    pan: str | None = None
    aadhaar_last4: str | None = None
    mobile: str | None = None
    upi_ids: list[str] | None = None
    customer_ids: list[str] | None = None
    resident: bool | None = None
    birth_date: date | None = None


class DocumentOut(BaseModel):
    id: int
    filename: str
    document_type: str
    status: str
    is_encrypted: bool
    page_count: int
    parser_used: str | None
    error_message: str | None
    warnings: list[str]
    created_at: datetime


class ImportStatusOut(BaseModel):
    id: str
    status: str
    total_files: int
    processed_files: int
    total_transactions: int
    progress: int
    message: str | None
    documents: list[DocumentOut]


class ParsedTransaction(BaseModel):
    transaction_date: date
    value_date: date | None = None
    description: str = ""
    narration: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal | None = None
    reference_number: str | None = None
    utr: str | None = None
    ifsc: str | None = None
    cheque_number: str | None = None
    mode: str | None = None
    counterparty: str | None = None
    bank_name: str | None = None
    branch: str | None = None
    account_number: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    source_row: int | None = None
