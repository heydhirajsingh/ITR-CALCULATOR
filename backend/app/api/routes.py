"""FastAPI routes for documents, transactions, tax summaries, review and exports."""
from __future__ import annotations

import tempfile
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.database.session import get_db
from backend.app.models.entities import (
    AISEntry,
    Account,
    AuditLog,
    Bank,
    Deduction,
    Dividend,
    Document,
    DocumentPage,
    DocumentStatus,
    Expense,
    Form26ASEntry,
    ImportSession,
    Income,
    Interest,
    Investment,
    ReviewQueue,
    ReviewStatus,
    TDS,
    TaxYear,
    Transaction,
    TransactionDirection,
    User,
)
from backend.app.parsers.base import InvalidPasswordError
from backend.app.parsers.detector import BANKS, detect_bank
from backend.app.reports.exporter import report_exporter
from backend.app.schemas.api import (
    AccountUpdate,
    DeductionCreate,
    DocumentAccountMerge,
    DocumentUpdate,
    PasswordRequest,
    ReviewAction,
    ReviewGroupAction,
    TransactionSplit,
    TransactionUpdate,
    UserProfileUpdate,
)
from backend.app.classification.rules_service import classification_rule_service, narration_pattern
from backend.app.services.import_service import import_manager
from backend.app.services.audit_service import log_event
from backend.app.services.reconciliation_service import reconciliation_service
from backend.app.services.summary_service import summary_service
from backend.app.utils.dates import financial_year_bounds

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "offline": True, "app": get_settings().app_name}


@router.get("/institutions")
def institutions(db: Session = Depends(get_db)) -> list[str]:
    saved_names = db.scalars(select(Bank.name)).all()
    return sorted(set(BANKS).union(name for name in saved_names if name))


@router.get("/tax-years")
def tax_years(db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(TaxYear).order_by(TaxYear.starts_on.desc())).all()
    return [
        {
            "id": item.id,
            "financial_year": item.financial_year,
            "assessment_year": item.assessment_year,
            "starts_on": item.starts_on,
            "ends_on": item.ends_on,
            "is_active": item.is_active,
            "rule_version": item.rule_version,
        }
        for item in items
    ]


@router.post("/tax-years")
def add_tax_year(financial_year: str, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(TaxYear.id).where(TaxYear.financial_year == financial_year)):
        raise HTTPException(409, "Financial year already exists")
    try:
        starts_on, ends_on = financial_year_bounds(financial_year)
    except Exception as exc:
        raise HTTPException(422, "Use a value such as FY 2026-27") from exc
    item = TaxYear(
        financial_year=financial_year,
        assessment_year=f"AY {starts_on.year + 1}-{str(starts_on.year + 2)[-2:]}",
        starts_on=starts_on,
        ends_on=ends_on,
        rule_version="unconfigured-future-year",
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "financial_year": item.financial_year, "warning": "Tax rules must be configured before estimating tax."}


@router.get("/dashboard")
def dashboard(financial_year: str = "FY 2025-26", db: Session = Depends(get_db)) -> dict:
    try:
        return summary_service.dashboard(db, financial_year)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/documents/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not files:
        raise HTTPException(400, "No files supplied")
    import_session = import_manager.create_session(db, len(files))
    documents = []
    for upload in files:
        suffix = Path(upload.filename or "upload.bin").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.temp_dir) as temp:
            total = 0
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_mb * 1024 * 1024:
                    Path(temp.name).unlink(missing_ok=True)
                    raise HTTPException(413, f"{upload.filename} exceeds {settings.max_upload_mb} MB")
                temp.write(chunk)
            temp_path = Path(temp.name)
        document = import_manager.register_file(
            db,
            import_session,
            temp_path,
            upload.filename or "upload.bin",
            upload.content_type,
        )
        documents.append(_document_dict(document))
    return {"import_session_id": import_session.id, "documents": documents}


@router.get("/imports/{session_id}")
def import_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    item = db.get(ImportSession, session_id)
    if not item:
        raise HTTPException(404, "Import session not found")
    documents = db.scalars(select(Document).where(Document.import_session_id == item.id).order_by(Document.id)).all()
    return {
        "id": item.id,
        "status": item.status,
        "total_files": item.total_files,
        "processed_files": item.processed_files,
        "total_transactions": item.total_transactions,
        "progress": item.progress,
        "message": item.message,
        "documents": [_document_dict(document) for document in documents],
    }


@router.get("/documents")
def documents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    total = int(db.scalar(select(func.count(Document.id))) or 0)
    items = db.scalars(select(Document).order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [_document_dict(item) for item in items], "total": total}


@router.post("/documents/merge-account")
def merge_documents_into_account(request: DocumentAccountMerge, db: Session = Depends(get_db)) -> dict:
    document_ids = list(dict.fromkeys(request.document_ids))
    selected_documents = db.scalars(select(Document).where(Document.id.in_(document_ids))).all()
    if len(selected_documents) != len(document_ids):
        raise HTTPException(404, "One or more selected documents no longer exist")
    if any(item.status in {DocumentStatus.queued, DocumentStatus.processing} for item in selected_documents):
        raise HTTPException(409, "Wait for all selected documents to finish processing")

    user = db.scalar(select(User).order_by(User.id).limit(1))
    if not user:
        raise HTTPException(404, "Taxpayer profile not found")

    if request.target_account_id is not None:
        target = db.get(Account, request.target_account_id)
        if not target or target.user_id != user.id:
            raise HTTPException(404, "Target account not found")
    else:
        bank_name = (request.bank_name or "").strip()
        account_name = (request.account_name or "").strip()
        if not bank_name or not account_name:
            raise HTTPException(422, "Bank and account name are required for a new account group")
        bank = db.scalar(select(Bank).where(Bank.name == bank_name))
        if bank is None:
            bank = Bank(name=bank_name)
            db.add(bank)
            db.flush()
        masked_number = (request.account_number or "").strip() or f"GROUP-{uuid.uuid4().hex[:8].upper()}"
        target = db.scalar(
            select(Account).where(
                Account.user_id == user.id,
                Account.masked_number == masked_number,
                Account.bank_id == bank.id,
            )
        )
        if target is None:
            target = Account(
                user_id=user.id,
                bank_id=bank.id,
                name=account_name,
                masked_number=masked_number,
                is_owned=False,
                metadata_json={
                    "ownership_confirmed": False,
                    "source": "manual statement merge",
                },
            )
            db.add(target)
            db.flush()

    transactions = db.scalars(select(Transaction).where(Transaction.document_id.in_(document_ids))).all()
    if not transactions:
        raise HTTPException(422, "The selected documents have no imported transactions to merge")

    transaction_ids = [item.id for item in transactions]
    source_account_ids = {item.account_id for item in transactions if item.account_id and item.account_id != target.id}
    linked_ids = {item.linked_transaction_id for item in transactions if item.linked_transaction_id}
    linked_transactions = db.scalars(
        select(Transaction).where(
            (Transaction.id.in_(linked_ids)) | (Transaction.linked_transaction_id.in_(transaction_ids))
        )
    ).all() if linked_ids or transaction_ids else []
    for item in [*transactions, *linked_transactions]:
        if item.is_self_transfer:
            item.is_self_transfer = False
            item.linked_transaction_id = None
            item.ignored = bool(item.is_duplicate)
            if item.direction == TransactionDirection.credit and not item.is_duplicate:
                item.needs_review = True

    target_bank_name = target.bank.name if target.bank else None
    for transaction in transactions:
        transaction.account_id = target.id
        if target_bank_name:
            transaction.bank_name = target_bank_name
        transaction.user_override = True
    for document in selected_documents:
        if target_bank_name:
            document.detected_bank = target_bank_name
        document.detected_account = target.masked_number

    db.flush()
    for account_id in source_account_ids:
        source = db.get(Account, account_id)
        if not source or (source.metadata_json or {}).get("ownership_confirmed"):
            continue
        remaining = int(db.scalar(select(func.count(Transaction.id)).where(Transaction.account_id == source.id)) or 0)
        if remaining == 0:
            db.delete(source)

    log_event(
        db,
        "documents_merged_into_account",
        f"Merged {len(selected_documents)} statement(s) into {target.name}",
        entity_type="account",
        entity_id=target.id,
        details={"document_ids": document_ids, "transactions": len(transactions)},
    )
    db.commit()
    db.refresh(target)
    import_manager.transfer_detector.process(db, transaction_ids)
    return {
        "status": "merged",
        "documents": len(selected_documents),
        "transactions": len(transactions),
        "account": {
            "id": target.id,
            "name": target.name,
            "masked_number": target.masked_number,
            "bank": target.bank.name if target.bank else None,
        },
    }


@router.patch("/documents/{document_id}")
def update_document(document_id: int, request: DocumentUpdate, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    # Keep already-imported transaction metadata consistent with a user correction.
    if "detected_bank" in request.model_fields_set:
        bank = None
        if request.detected_bank:
            bank = db.scalar(select(Bank).where(Bank.name == request.detected_bank))
            if bank is None:
                bank = Bank(name=request.detected_bank)
                db.add(bank)
                db.flush()
        account_ids: set[int] = set()
        for transaction in db.scalars(select(Transaction).where(Transaction.document_id == document.id)).all():
            transaction.bank_name = request.detected_bank or None
            transaction.user_override = True
            if transaction.account_id:
                account_ids.add(transaction.account_id)
        for account_id in account_ids:
            account = db.get(Account, account_id)
            if account:
                account.bank_id = bank.id if bank else None
                if bank:
                    account.name = f"{bank.name} account"
    db.commit()
    return _document_dict(document)


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    try:
        import_manager.delete_document(db, document)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "removed", "id": document_id}


@router.post("/documents/clear-all")
@router.delete("/documents/clear-all")
def clear_all_documents(db: Session = Depends(get_db)) -> dict:
    db.query(ReviewQueue).delete(synchronize_session=False)
    db.query(AISEntry).delete(synchronize_session=False)
    db.query(Form26ASEntry).delete(synchronize_session=False)
    db.query(TDS).delete(synchronize_session=False)
    db.query(Income).delete(synchronize_session=False)
    db.query(Expense).delete(synchronize_session=False)
    db.query(Investment).delete(synchronize_session=False)
    db.query(Interest).delete(synchronize_session=False)
    db.query(Dividend).delete(synchronize_session=False)
    db.query(Deduction).delete(synchronize_session=False)
    db.query(Transaction).delete(synchronize_session=False)
    db.query(DocumentPage).delete(synchronize_session=False)
    db.query(Document).delete(synchronize_session=False)
    db.query(ImportSession).delete(synchronize_session=False)
    db.query(Account).delete(synchronize_session=False)
    db.query(Bank).delete(synchronize_session=False)
    db.commit()
    return {"status": "cleared", "message": "All imported data cleared successfully"}


@router.post("/documents/{document_id}/password")
def document_password(document_id: int, request: PasswordRequest) -> dict:
    try:
        import_manager.submit_password(document_id, request.password)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidPasswordError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "queued", "message": "Password accepted for this session only"}


@router.post("/documents/{document_id}/reprocess")
def reprocess_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    import_manager.queue_document(document_id)
    return {"status": "queued"}


@router.get("/transactions")
def transactions(
    financial_year: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    income_type: str | None = None,
    account_id: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    review_only: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    tax_year_id = None
    if financial_year:
        tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
        if not tax_year:
            raise HTTPException(404, "Financial year not found")
        tax_year_id = tax_year.id
    query = summary_service.transaction_query(
        tax_year_id,
        search=search,
        bank=bank,
        category=category,
        income_type=income_type,
        account_id=account_id,
        month=month,
        min_amount=min_amount,
        max_amount=max_amount,
        review_only=review_only,
    )
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = int(db.scalar(count_query) or 0)
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [_transaction_dict(tx, filename, document_type) for tx, filename, document_type in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


@router.patch("/transactions/{transaction_id}")
def update_transaction(transaction_id: int, request: TransactionUpdate, db: Session = Depends(get_db)) -> dict:
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(404, "Transaction not found")
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(transaction, field, value)
    transaction.user_override = True
    if request.needs_review is False:
        transaction.review_status = "accepted"
        reviews = db.scalars(select(ReviewQueue).where(ReviewQueue.transaction_id == transaction.id)).all()
        for review in reviews:
            review.status = ReviewStatus.accepted
            review.resolved_at = datetime.utcnow()
    db.commit()
    return _transaction_dict(transaction, transaction.document.filename if transaction.document else None, transaction.document.document_type if transaction.document else None)


@router.post("/transactions/{transaction_id}/split")
def split_transaction(transaction_id: int, request: TransactionSplit, db: Session = Depends(get_db)) -> dict:
    original = db.get(Transaction, transaction_id)
    if not original:
        raise HTTPException(404, "Transaction not found")
    total = sum(request.parts, Decimal("0"))
    if abs(total - Decimal(original.amount)) > Decimal("0.01"):
        raise HTTPException(422, "Split parts must equal the original amount")
    categories = request.categories or [original.category] * len(request.parts)
    if len(categories) != len(request.parts):
        raise HTTPException(422, "categories must match parts")
    created = []
    for amount, category in zip(request.parts, categories, strict=True):
        item = Transaction(
            document_id=original.document_id,
            account_id=original.account_id,
            tax_year_id=original.tax_year_id,
            transaction_date=original.transaction_date,
            value_date=original.value_date,
            description=f"{original.description} [split]",
            narration=original.narration,
            debit=amount if original.direction == TransactionDirection.debit else Decimal("0"),
            credit=amount if original.direction == TransactionDirection.credit else Decimal("0"),
            amount=amount,
            direction=original.direction,
            category=category,
            income_type=original.income_type,
            counterparty=original.counterparty,
            bank_name=original.bank_name,
            taxable=original.taxable,
            exempt=original.exempt,
            ignored=False,
            confidence=Decimal("100"),
            user_override=True,
            raw_data={"split_from": original.id},
        )
        db.add(item)
        db.flush()
        created.append(item.id)
    original.ignored = True
    original.user_override = True
    original.raw_data = {**(original.raw_data or {}), "split_into": created}
    db.commit()
    return {"original_id": original.id, "created_ids": created}


@router.get("/review")
def review_queue(
    financial_year: str = "FY 2025-26",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
    if not tax_year:
        raise HTTPException(404, "Financial year not found")
    query = (
        select(ReviewQueue, Transaction)
        .join(Transaction, ReviewQueue.transaction_id == Transaction.id)
        .where(ReviewQueue.status == ReviewStatus.pending, Transaction.tax_year_id == tax_year.id)
        .order_by(ReviewQueue.confidence.asc(), ReviewQueue.created_at.desc())
    )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [
            {
                "review_id": review.id,
                "reason": review.reason,
                "suggested_action": review.suggested_action,
                "confidence": float(review.confidence),
                "transaction": _transaction_dict(tx, tx.document.filename if tx.document else None, tx.document.document_type if tx.document else None),
            }
            for review, tx in rows
        ],
        "total": total,
        "page": page,
    }


@router.get("/review/groups")
def review_groups(financial_year: str = "FY 2025-26", db: Session = Depends(get_db)) -> dict:
    tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
    if not tax_year:
        raise HTTPException(404, "Financial year not found")
    rows = db.execute(
        select(ReviewQueue, Transaction)
        .join(Transaction, ReviewQueue.transaction_id == Transaction.id)
        .where(ReviewQueue.status == ReviewStatus.pending, Transaction.tax_year_id == tax_year.id)
        .order_by(Transaction.amount.desc())
    ).all()
    grouped: dict[tuple[str, str], dict] = {}
    seen_transactions: set[int] = set()
    for review, transaction in rows:
        if transaction.id in seen_transactions:
            continue
        seen_transactions.add(transaction.id)
        direction = transaction.direction.value
        pattern = narration_pattern(transaction.description)
        key = (pattern, direction)
        group = grouped.setdefault(
            key,
            {
                "pattern": pattern,
                "direction": direction,
                "count": 0,
                "total_amount": 0.0,
                "review_ids": [],
                "category": transaction.category,
                "sample_description": transaction.description,
                "counterparty": transaction.counterparty or classifier.extract_counterparty(transaction.description, direction=direction),
                "confidence_total": 0.0,
            },
        )
        group["count"] += 1
        group["total_amount"] += float(transaction.amount)
        group["review_ids"].append(review.id)
        group["confidence_total"] += float(review.confidence)
    items = []
    for group in grouped.values():
        group["confidence"] = group.pop("confidence_total") / group["count"]
        items.append(group)
    items.sort(key=lambda item: (-item["count"], -item["total_amount"]))
    return {"items": items, "groups": len(items), "transactions": len(seen_transactions)}


@router.post("/review/groups/action")
def resolve_review_group(request: ReviewGroupAction, db: Session = Depends(get_db)) -> dict:
    tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == request.financial_year))
    if not tax_year:
        raise HTTPException(404, "Financial year not found")
    rule = classification_rule_service.save(
        db,
        pattern=request.pattern,
        direction=request.direction,
        category=request.category,
        income_type=request.income_type,
        counterparty=request.counterparty,
        taxable=request.taxable,
        exempt=request.exempt,
        ignored=request.ignored,
    )
    db.flush()
    matching_ids = [
        transaction.id
        for transaction in db.scalars(
            select(Transaction).where(
                Transaction.tax_year_id == tax_year.id,
                Transaction.direction == TransactionDirection(request.direction),
            )
        ).all()
        if narration_pattern(transaction.description) == rule.normalized_pattern
    ]
    updated = classification_rule_service.apply_to_matching(db, rule, tax_year.id)
    if not request.save_rule:
        db.delete(rule)
    if matching_ids:
        reviews = db.scalars(
            select(ReviewQueue).where(
                ReviewQueue.transaction_id.in_(matching_ids),
                ReviewQueue.status == ReviewStatus.pending,
            )
        ).all()
        for review in reviews:
            review.status = ReviewStatus.accepted
            review.resolution_notes = "Resolved with a grouped narration decision"
            review.resolved_at = datetime.utcnow()
    db.commit()
    return {"updated": updated, "rule_saved": request.save_rule}


@router.post("/review/{review_id}/action")
def resolve_review(review_id: int, request: ReviewAction, db: Session = Depends(get_db)) -> dict:
    review = db.get(ReviewQueue, review_id)
    if not review:
        raise HTTPException(404, "Review item not found")
    transaction = db.get(Transaction, review.transaction_id) if review.transaction_id else None
    review.resolution_notes = request.notes
    review.resolved_at = datetime.utcnow()
    if request.action == "accept":
        review.status = ReviewStatus.accepted
        if transaction:
            transaction.needs_review = False
            transaction.review_status = "accepted"
    elif request.action == "reject":
        review.status = ReviewStatus.rejected
        if transaction:
            transaction.taxable = False
            transaction.review_status = "rejected"
    elif request.action == "ignore":
        review.status = ReviewStatus.ignored
        if transaction:
            transaction.ignored = True
            transaction.review_status = "ignored"
    elif request.action == "merge":
        if not request.merge_with_transaction_id:
            raise HTTPException(422, "merge_with_transaction_id is required")
        target = db.get(Transaction, request.merge_with_transaction_id)
        if not target or not transaction:
            raise HTTPException(404, "Merge transaction not found")
        transaction.is_duplicate = True
        transaction.duplicate_of_id = target.id
        transaction.ignored = True
        review.status = ReviewStatus.merged
        transaction.review_status = "merged"
    db.commit()
    return {"status": review.status.value}


@router.get("/tax/compare")
def compare_tax(financial_year: str = "FY 2025-26", db: Session = Depends(get_db)) -> dict:
    try:
        return summary_service.tax_comparison(db, financial_year)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/deductions")
def deductions(financial_year: str = "FY 2025-26", db: Session = Depends(get_db)) -> list[dict]:
    tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == financial_year))
    if not tax_year:
        raise HTTPException(404, "Financial year not found")
    items = db.scalars(select(Deduction).where(Deduction.tax_year_id == tax_year.id).order_by(Deduction.section)).all()
    return [
        {
            "id": item.id,
            "section": item.section,
            "description": item.description,
            "amount_claimed": float(item.amount_claimed),
            "amount_eligible": float(item.amount_eligible),
            "suggested": item.suggested,
            "accepted": item.accepted,
        }
        for item in items
    ]


@router.post("/deductions")
def create_deduction(request: DeductionCreate, db: Session = Depends(get_db)) -> dict:
    tax_year = db.scalar(select(TaxYear).where(TaxYear.financial_year == request.financial_year))
    if not tax_year:
        raise HTTPException(404, "Financial year not found")
    item = Deduction(
        tax_year_id=tax_year.id,
        section=request.section,
        description=request.description,
        amount_claimed=request.amount_claimed,
        amount_eligible=request.amount_eligible if request.amount_eligible is not None else request.amount_claimed,
        accepted=request.accepted,
        suggested=False,
    )
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.patch("/deductions/{deduction_id}")
def update_deduction(deduction_id: int, accepted: bool, db: Session = Depends(get_db)) -> dict:
    item = db.get(Deduction, deduction_id)
    if not item:
        raise HTTPException(404, "Deduction not found")
    item.accepted = accepted
    db.commit()
    return {"id": item.id, "accepted": item.accepted}


@router.get("/reconciliation/{source}")
def reconciliation(source: str, financial_year: str = "FY 2025-26", db: Session = Depends(get_db)) -> dict:
    source_type = "AIS" if source.lower() == "ais" else "Form 26AS" if source.lower() in {"26as", "form26as"} else None
    if not source_type:
        raise HTTPException(404, "Use ais or 26as")
    return reconciliation_service.report(db, financial_year, source_type)


@router.get("/reports/{report_kind}")
def export_report(
    report_kind: str,
    financial_year: str = "FY 2025-26",
    format: str = Query("xlsx", pattern="^(csv|xlsx|json|pdf)$"),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        path = report_exporter.build(db, report_kind, financial_year, format)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(path, filename=path.name)


@router.get("/audit-logs")
def audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if level:
        query = query.where(AuditLog.level == level.upper())
    items = db.scalars(query).all()
    return [
        {
            "id": item.id,
            "created_at": item.created_at,
            "level": item.level,
            "event_type": item.event_type,
            "message": item.message,
            "details": item.details,
        }
        for item in items
    ]


@router.get("/profile")
def profile(db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if not user:
        raise HTTPException(404, "Profile not found")
    return {
        "id": user.id,
        "name": user.name,
        "pan": user.pan,
        "aadhaar_last4": user.aadhaar_last4,
        "mobile": user.mobile,
        "upi_ids": user.upi_ids,
        "customer_ids": user.customer_ids,
        "resident": user.resident,
        "birth_date": user.birth_date,
    }


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(Account).order_by(Account.name, Account.id)).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "masked_number": item.masked_number,
            "bank": item.bank.name if item.bank else None,
            "is_owned": item.is_owned,
            "ownership_confirmed": bool((item.metadata_json or {}).get("ownership_confirmed")),
        }
        for item in items
    ]


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, request: AccountUpdate, db: Session = Depends(get_db)) -> dict:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    if request.name is not None:
        account.name = request.name
    if request.is_owned is not None:
        account.is_owned = request.is_owned
        account.metadata_json = {
            **(account.metadata_json or {}),
            "ownership_confirmed": True,
            "ownership_source": "user",
        }
    db.commit()
    if request.is_owned:
        transaction_ids = list(
            db.scalars(select(Transaction.id).where(Transaction.account_id == account.id)).all()
        )
        import_manager.transfer_detector.process(db, transaction_ids)
    return {
        "id": account.id,
        "name": account.name,
        "is_owned": account.is_owned,
        "ownership_confirmed": bool((account.metadata_json or {}).get("ownership_confirmed")),
    }


@router.patch("/profile")
def update_profile(request: UserProfileUpdate, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if not user:
        user = User(name="Local User")
        db.add(user)
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    return {"status": "saved"}


def _document_dict(document: Document) -> dict:
    raw_warnings = document.warnings or []
    detected_bank = document.detected_bank
    if not detected_bank and document.filename:
        detected_bank = detect_bank(document.filename)
        if detected_bank:
            document.detected_bank = detected_bank

    cleaned_warnings = []
    for warning in raw_warnings:
        w = warning.lower()
        if "camelot fallback" in w or "tabula fallback" in w or "both debit and credit" in w:
            continue
        if "no transaction rows could be normalized" in w:
            continue
        if "running-balance reconciliation is 9" in w or "running-balance reconciliation is 100" in w:
            continue
        if detected_bank and "issuing institution could not be confirmed" in w:
            continue
        cleaned_warnings.append(warning)

    return {
        "id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "status": document.status.value,
        "is_encrypted": document.is_encrypted,
        "page_count": document.page_count,
        "parser_used": document.parser_used,
        "detected_bank": detected_bank,
        "error_message": document.error_message,
        "warnings": cleaned_warnings,
        "is_file_duplicate": document.status == DocumentStatus.skipped
        and any("exact duplicate" in warning.lower() for warning in raw_warnings),
        "created_at": document.created_at,
    }


def _transaction_dict(transaction: Transaction, filename: str | None, document_type: str | None) -> dict:
    return {
        "id": transaction.id,
        "date": transaction.transaction_date,
        "description": transaction.description,
        "debit": float(transaction.debit),
        "credit": float(transaction.credit),
        "amount": float(transaction.amount),
        "balance": float(transaction.balance) if transaction.balance is not None else None,
        "reference_number": transaction.reference_number,
        "utr": transaction.utr,
        "mode": transaction.mode,
        "category": transaction.category,
        "income_type": transaction.income_type,
        "counterparty": transaction.counterparty,
        "bank": transaction.bank_name,
        "taxable": transaction.taxable,
        "exempt": transaction.exempt,
        "ignored": transaction.ignored,
        "is_duplicate": transaction.is_duplicate,
        "duplicate_of_id": transaction.duplicate_of_id,
        "is_self_transfer": transaction.is_self_transfer,
        "linked_transaction_id": transaction.linked_transaction_id,
        "needs_review": transaction.needs_review,
        "confidence": float(transaction.confidence or 0),
        "document_filename": filename,
        "document_type": document_type,
        "user_override": transaction.user_override,
    }
