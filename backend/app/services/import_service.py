"""Background document import orchestration and normalized persistence."""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import fitz
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.classification.engine import classifier
from backend.app.classification.rules_service import classification_rule_service
from backend.app.core.config import get_settings
from backend.app.database.session import SessionLocal
from backend.app.models.entities import (
    AISEntry,
    Account,
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
    ReviewQueue,
    ReviewStatus,
    TaxYear,
    Transaction,
    TransactionDirection,
    User,
)
from backend.app.parsers.base import InvalidPasswordError, ParserError, PasswordRequiredError
from backend.app.parsers.registry import registry
from backend.app.schemas.api import ParsedTransaction
from backend.app.services.audit_service import log_event
from backend.app.services.duplicate_service import DuplicateDetector
from backend.app.services.transfer_service import SelfTransferDetector
from backend.app.utils.dates import financial_year_for


class ImportManager:
    """Owns local worker threads and an in-memory PDF password vault."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.executor = ThreadPoolExecutor(max_workers=settings.worker_count, thread_name_prefix="itr-import")
        self._passwords: dict[int, str] = {}
        self._password_lock = threading.Lock()
        self._persistence_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self.duplicate_detector = DuplicateDetector()
        self.transfer_detector = SelfTransferDetector()

    def create_session(self, db: Session, file_count: int) -> ImportSession:
        session = ImportSession(
            id=str(uuid.uuid4()),
            total_files=file_count,
            status="uploaded",
            progress=0,
            message="Files uploaded",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def register_file(
        self,
        db: Session,
        import_session: ImportSession,
        source_path: Path,
        original_filename: str,
        content_type: str | None,
    ) -> Document:
        digest = _sha256(source_path)
        duplicate = db.scalar(
            select(Document)
            .where(Document.sha256 == digest, Document.status != DocumentStatus.skipped)
            .order_by(Document.id)
            .limit(1)
        )
        destination_dir = self.settings.upload_dir / import_session.id
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(original_filename)
        destination = destination_dir / f"{uuid.uuid4().hex[:10]}_{safe_name}"
        shutil.move(str(source_path), destination)
        is_encrypted = False
        status = DocumentStatus.skipped if duplicate else DocumentStatus.queued
        if not duplicate and destination.suffix.lower() == ".pdf":
            try:
                pdf = fitz.open(destination)
                is_encrypted = bool(pdf.needs_pass)
                pdf.close()
                if is_encrypted:
                    status = DocumentStatus.password_required
            except Exception:
                pass
        elif not duplicate and destination.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(destination) as archive:
                    is_encrypted = any(item.flag_bits & 0x1 for item in archive.infolist() if not item.is_dir())
                if is_encrypted:
                    status = DocumentStatus.password_required
            except Exception:
                pass
        document = Document(
            import_session_id=import_session.id,
            filename=original_filename,
            stored_path=str(destination),
            sha256=digest,
            mime_type=content_type or mimetypes.guess_type(original_filename)[0],
            file_size=destination.stat().st_size,
            status=status,
            is_encrypted=is_encrypted,
            warnings=(
                [f"Exact duplicate of {duplicate.filename} (document #{duplicate.id}); no transactions were imported."]
                if duplicate
                else []
            ),
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        log_event(
            db,
            "document_uploaded",
            f"Uploaded {original_filename}",
            entity_type="document",
            entity_id=document.id,
            details={"sha256": digest, "encrypted": is_encrypted, "duplicate_of_document_id": duplicate.id if duplicate else None},
        )
        if duplicate:
            log_event(
                db,
                "duplicate_document_skipped",
                f"Skipped exact duplicate {original_filename}",
                level="WARNING",
                entity_type="document",
                entity_id=document.id,
                details={"duplicate_of_document_id": duplicate.id, "sha256": digest},
            )
        db.commit()
        if status == DocumentStatus.queued:
            self.queue_document(document.id)
        self._refresh_session(db, import_session.id)
        return document

    def delete_document(self, db: Session, document: Document) -> None:
        """Remove one document and all records derived from it."""
        document_id = document.id
        filename = document.filename
        stored_path = Path(document.stored_path)
        session_id = document.import_session_id
        self._clear_document_records(db, document_id)
        db.execute(text(f"DELETE FROM tds WHERE document_id = {document_id}"))
        db.execute(text(f"DELETE FROM review_queue WHERE document_id = {document_id}"))
        db.execute(text(f"DELETE FROM deductions WHERE evidence_document_id = {document_id} AND suggested = 1 AND accepted = 0"))
        db.execute(text(f"UPDATE deductions SET evidence_document_id = NULL WHERE evidence_document_id = {document_id}"))
        db.delete(document)
        session = db.get(ImportSession, session_id)
        if session:
            session.total_files = max(0, session.total_files - 1)
        db.commit()
        try:
            stored_path.unlink(missing_ok=True)
        except OSError as exc:
            log_event(
                db,
                "document_file_cleanup_failed",
                f"Removed database records for {filename}, but could not delete its stored file: {exc}",
                level="WARNING",
                entity_type="document",
                entity_id=document_id,
            )
        log_event(
            db,
            "document_removed",
            f"Removed {filename}",
            entity_type="document",
            entity_id=document_id,
        )
        db.commit()
        self._refresh_session(db, session_id)

    def submit_password(self, document_id: int, password: str) -> None:
        with SessionLocal() as db:
            document = db.get(Document, document_id)
            if not document:
                raise KeyError("Document not found")
            path = Path(document.stored_path)
            if path.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(path) as archive:
                        encrypted = next(
                            (item for item in archive.infolist() if not item.is_dir() and item.flag_bits & 0x1),
                            None,
                        )
                        if encrypted:
                            with archive.open(encrypted, pwd=password.encode("utf-8")) as member:
                                member.read(1)
                except RuntimeError:
                    log_event(
                        db,
                        "password_rejected",
                        f"Incorrect password for {document.filename}",
                        level="WARNING",
                        entity_type="document",
                        entity_id=document.id,
                    )
                    db.commit()
                    raise InvalidPasswordError("The ZIP password is incorrect")
            else:
                pdf = fitz.open(path)
                try:
                    if pdf.needs_pass and not pdf.authenticate(password):
                        log_event(
                            db,
                            "password_rejected",
                            f"Incorrect password for {document.filename}",
                            level="WARNING",
                            entity_type="document",
                            entity_id=document.id,
                        )
                        db.commit()
                        raise InvalidPasswordError("The PDF password is incorrect")
                finally:
                    pdf.close()
            with self._password_lock:
                self._passwords[document_id] = password
            document.status = DocumentStatus.queued
            document.error_message = None
            log_event(
                db,
                "password_accepted",
                f"Session-only password accepted for {document.filename}",
                entity_type="document",
                entity_id=document.id,
            )
            db.commit()
        self.queue_document(document_id)

    def queue_document(self, document_id: int) -> None:
        self.executor.submit(self._process_document, document_id)

    def _process_document(self, document_id: int) -> None:
        with SessionLocal() as db:
            document = db.get(Document, document_id)
            if not document:
                return
            document.status = DocumentStatus.processing
            document.error_message = None
            db.commit()
            password = None
            with self._password_lock:
                password = self._passwords.get(document_id)
            try:
                parser = registry.get_parser(Path(document.stored_path))
                if parser is None:
                    raise ParserError(f"Unsupported file type: {Path(document.stored_path).suffix}")
                result = parser.parse(Path(document.stored_path), password=password)
                document.document_type = result.document_type
                document.parser_used = result.parser_used
                document.page_count = result.page_count
                document.detected_bank = result.bank_name
                document.detected_account = result.account_number
                document.warnings = result.warnings
                self._clear_document_records(db, document.id)
                db.query(DocumentPage).filter(DocumentPage.document_id == document.id).delete()
                for page_number, text, method, confidence in result.page_texts:
                    db.add(
                        DocumentPage(
                            document_id=document.id,
                            page_number=page_number,
                            extraction_method=method,
                            text_content=text,
                            confidence=confidence,
                        )
                    )
                with self._persistence_lock:
                    transaction_ids = self._persist_transactions(db, document, result.transactions)
                    self.duplicate_detector.process(db, transaction_ids)
                    self.transfer_detector.process(db, transaction_ids)
                    self._refresh_review_flags(db, transaction_ids)
                document.status = DocumentStatus.completed
                document.processed_at = datetime.utcnow()
                log_event(
                    db,
                    "document_processed",
                    f"Processed {document.filename}",
                    entity_type="document",
                    entity_id=document.id,
                    details={"transactions": len(transaction_ids), "type": result.document_type},
                )
                db.commit()
            except PasswordRequiredError:
                document.status = DocumentStatus.password_required
                document.is_encrypted = True
                document.error_message = None
                log_event(
                    db,
                    "password_required",
                    f"Password required for {document.filename}",
                    level="WARNING",
                    entity_type="document",
                    entity_id=document.id,
                )
                db.commit()
            except InvalidPasswordError as exc:
                document.status = DocumentStatus.password_required
                document.error_message = str(exc)
                db.commit()
            except Exception as exc:
                document.status = DocumentStatus.failed
                document.error_message = str(exc)
                log_event(
                    db,
                    "document_failed",
                    f"Failed to process {document.filename}: {exc}",
                    level="ERROR",
                    entity_type="document",
                    entity_id=document.id,
                )
                db.commit()
            finally:
                with self._password_lock:
                    self._passwords.pop(document_id, None)
                self._refresh_session(db, document.import_session_id)

    @staticmethod
    def _clear_document_records(db: Session, document_id: int) -> None:
        """Make reprocessing idempotent while preserving data if parsing fails."""
        transaction_ids = list(
            db.scalars(select(Transaction.id).where(Transaction.document_id == document_id)).all()
        )
        if transaction_ids:
            id_list = ", ".join(str(tid) for tid in transaction_ids)
            db.execute(text(f"DELETE FROM income WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM expenses WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM investments WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM interest WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM dividends WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM review_queue WHERE transaction_id IN ({id_list})"))
            db.execute(text(f"DELETE FROM ais_entries WHERE linked_transaction_id IN ({id_list})"))
            db.execute(
                text(
                    f"UPDATE transactions SET duplicate_of_id = NULL, linked_transaction_id = NULL "
                    f"WHERE id IN ({id_list}) OR duplicate_of_id IN ({id_list}) OR linked_transaction_id IN ({id_list})"
                )
            )
            db.execute(text(f"DELETE FROM transactions WHERE id IN ({id_list})"))

        db.execute(text(f"DELETE FROM ais_entries WHERE document_id = {document_id}"))
        db.execute(text(f"DELETE FROM form_26as_entries WHERE document_id = {document_id}"))
        db.execute(text(f"DELETE FROM deductions WHERE evidence_document_id = {document_id}"))
        db.execute(text(f"DELETE FROM review_queue WHERE document_id = {document_id}"))
        db.execute(text(f"DELETE FROM document_pages WHERE document_id = {document_id}"))
        db.flush()

    def _persist_transactions(
        self, db: Session, document: Document, parsed_transactions: list[ParsedTransaction]
    ) -> list[int]:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            user = User(name="Local User")
            db.add(user)
            db.flush()
        tax_years = {item.financial_year: item for item in db.scalars(select(TaxYear)).all()}
        ids: list[int] = []
        for parsed in parsed_transactions:
            account = self._get_or_create_account(
                db,
                user,
                document,
                bank_name=parsed.bank_name or document.detected_bank,
                account_number=parsed.account_number or document.detected_account,
            )
            financial_year = financial_year_for(parsed.transaction_date)
            tax_year = tax_years.get(financial_year)
            if tax_year is None:
                tax_year = self._create_future_tax_year(db, financial_year, parsed.transaction_date)
                tax_years[financial_year] = tax_year
            description = parsed.description or parsed.narration or ""
            result = classifier.classify(
                description,
                debit=parsed.debit,
                credit=parsed.credit,
                document_type=document.document_type,
                user=user,
            )
            direction_value = "credit" if parsed.credit > 0 else "debit"
            learned = classification_rule_service.match(db, description, direction_value)
            if learned:
                result.category = learned.category
                result.income_type = learned.income_type
                result.counterparty = learned.counterparty or result.counterparty
                result.taxable = learned.taxable
                result.exempt = learned.exempt
                result.ignored = learned.ignored
                result.needs_review = False
                result.confidence = 100.0
                result.reason = learned.reason
            amount = parsed.credit if parsed.credit > 0 else parsed.debit
            direction = TransactionDirection.credit if parsed.credit > 0 else TransactionDirection.debit
            transaction = Transaction(
                document_id=document.id,
                account_id=account.id if account else None,
                tax_year_id=tax_year.id,
                transaction_date=parsed.transaction_date,
                value_date=parsed.value_date,
                description=description,
                narration=parsed.narration,
                debit=parsed.debit,
                credit=parsed.credit,
                amount=amount,
                balance=parsed.balance,
                direction=direction,
                reference_number=parsed.reference_number,
                utr=parsed.utr,
                ifsc=parsed.ifsc,
                cheque_number=parsed.cheque_number,
                mode=parsed.mode or result.mode,
                category=result.category,
                income_type=result.income_type,
                counterparty=parsed.counterparty or result.counterparty,
                bank_name=parsed.bank_name or document.detected_bank,
                branch=parsed.branch,
                taxable=result.taxable,
                exempt=result.exempt,
                ignored=result.ignored,
                needs_review=result.needs_review,
                confidence=result.confidence,
                source_row=parsed.source_row,
                raw_data={**parsed.raw_data, "classification_reason": result.reason},
            )
            db.add(transaction)
            db.flush()
            ids.append(transaction.id)
            self._persist_derived_records(db, document, tax_year, transaction)
        db.commit()
        return ids

    def _persist_derived_records(
        self, db: Session, document: Document, tax_year: TaxYear, transaction: Transaction
    ) -> None:
        amount = Decimal(transaction.amount)
        if transaction.direction == TransactionDirection.credit and transaction.income_type:
            db.add(
                Income(
                    transaction_id=transaction.id,
                    tax_year_id=tax_year.id,
                    income_type=transaction.income_type,
                    gross_amount=amount,
                    taxable_amount=amount if transaction.taxable else Decimal("0"),
                    exempt_amount=amount if transaction.exempt else Decimal("0"),
                    notes=transaction.raw_data.get("classification_reason"),
                )
            )
        if transaction.direction == TransactionDirection.debit:
            deductible = transaction.category in {
                "Professional", "Business", "Office", "Fuel", "Maintenance", "Utilities", "Insurance", "Donation"
            }
            db.add(
                Expense(
                    transaction_id=transaction.id,
                    tax_year_id=tax_year.id,
                    category=transaction.category,
                    amount=amount,
                    deductible=deductible,
                    business_use_percent=Decimal("100") if deductible else Decimal("0"),
                )
            )
            self._suggest_deduction(db, tax_year, document, transaction)
        if transaction.category in {"Interest", "FD Interest"} and transaction.direction == TransactionDirection.credit:
            db.add(
                Interest(
                    transaction_id=transaction.id,
                    tax_year_id=tax_year.id,
                    interest_type="FD" if transaction.category == "FD Interest" else "Savings/Other",
                    payer=transaction.counterparty or transaction.bank_name,
                    amount=amount,
                )
            )
        if transaction.category == "Dividend" and transaction.direction == TransactionDirection.credit:
            db.add(
                Dividend(
                    transaction_id=transaction.id,
                    tax_year_id=tax_year.id,
                    company_or_fund=transaction.counterparty,
                    amount=amount,
                )
            )
        if document.document_type == "AIS" and transaction.direction == TransactionDirection.credit:
            db.add(
                AISEntry(
                    tax_year_id=tax_year.id,
                    document_id=document.id,
                    description=transaction.description,
                    amount=amount,
                    reported_on=transaction.transaction_date,
                    source_name=transaction.counterparty,
                    linked_transaction_id=transaction.id,
                    reconciliation_status="imported",
                )
            )
        if document.document_type == "Form 26AS" and transaction.direction == TransactionDirection.credit:
            entry = Form26ASEntry(
                tax_year_id=tax_year.id,
                document_id=document.id,
                deductor_name=transaction.counterparty,
                amount_paid=amount,
                tds_deposited=Decimal("0"),
                transaction_date=transaction.transaction_date,
                reconciliation_status="imported",
            )
            db.add(entry)
        if transaction.needs_review:
            db.add(
                ReviewQueue(
                    transaction_id=transaction.id,
                    document_id=document.id,
                    reason=transaction.raw_data.get("classification_reason", "Needs review"),
                    suggested_action="classify",
                    confidence=transaction.confidence,
                    status=ReviewStatus.pending,
                )
            )

    @staticmethod
    def _suggest_deduction(db: Session, tax_year: TaxYear, document: Document, transaction: Transaction) -> None:
        text_val = transaction.description.lower()
        suggestions: list[tuple[str, str]] = []
        if any(token in text_val for token in ("ppf", "elss", "lic premium", "life insurance", "epf")):
            suggestions.append(("80C", "Potential eligible investment/premium"))
        if "nps" in text_val:
            suggestions.append(("80CCD(1B)", "Potential NPS contribution"))
        if any(token in text_val for token in ("health insurance", "medical insurance", "mediclaim")):
            suggestions.append(("80D", "Potential medical insurance premium"))
        if "education loan" in text_val:
            suggestions.append(("80E", "Potential education-loan interest"))
        if "donation" in text_val:
            suggestions.append(("80G", "Potential eligible donation; verify donee and payment mode"))
        for section, description in suggestions:
            exists = db.scalar(
                select(Deduction.id).where(
                    Deduction.tax_year_id == tax_year.id,
                    Deduction.section == section,
                    Deduction.evidence_document_id == document.id,
                ).limit(1)
            )
            if not exists:
                db.add(
                    Deduction(
                        tax_year_id=tax_year.id,
                        section=section,
                        description=description,
                        amount_claimed=transaction.amount,
                        amount_eligible=transaction.amount,
                        evidence_document_id=document.id,
                        suggested=True,
                        accepted=False,
                    )
                )

    @staticmethod
    def _get_or_create_account(
        db: Session,
        user: User,
        document: Document,
        *,
        bank_name: str | None = None,
        account_number: str | None = None,
    ) -> Account:
        bank = None
        effective_bank = bank_name or document.detected_bank
        if effective_bank:
            bank = db.scalar(select(Bank).where(Bank.name == effective_bank))
            if bank is None:
                bank = Bank(name=effective_bank)
                db.add(bank)
                db.flush()
        masked = account_number or document.detected_account or f"DOC-{document.id}"
        account = db.scalar(
            select(Account).where(
                Account.user_id == user.id,
                Account.masked_number == masked,
                Account.bank_id == (bank.id if bank else None),
            )
        )
        if account is None:
            account = Account(
                user_id=user.id,
                bank_id=bank.id if bank else None,
                name=f"{effective_bank or 'Imported'} account",
                masked_number=masked,
                is_owned=False,
                metadata_json={"ownership_confirmed": False, "source": "automatic import"},
            )
            db.add(account)
            db.flush()
        return account

    @staticmethod
    def _create_future_tax_year(db: Session, financial_year: str, transaction_date) -> TaxYear:  # type: ignore[no-untyped-def]
        start = transaction_date.year if transaction_date.month >= 4 else transaction_date.year - 1
        tax_year = TaxYear(
            financial_year=financial_year,
            assessment_year=f"AY {start + 1}-{str(start + 2)[-2:]}",
            starts_on=transaction_date.replace(year=start, month=4, day=1),
            ends_on=transaction_date.replace(year=start + 1, month=3, day=31),
            rule_version="unconfigured-future-year",
        )
        db.add(tax_year)
        db.flush()
        return tax_year

    @staticmethod
    def _refresh_review_flags(db: Session, transaction_ids: list[int]) -> None:
        for transaction_id in transaction_ids:
            tx = db.get(Transaction, transaction_id)
            if not tx:
                continue
            if tx.is_duplicate or tx.is_self_transfer:
                tx.taxable = False
                tx.ignored = True
            if tx.needs_review:
                existing = db.scalar(
                    select(ReviewQueue.id).where(
                        ReviewQueue.transaction_id == tx.id,
                        ReviewQueue.status == ReviewStatus.pending,
                    ).limit(1)
                )
                if not existing:
                    db.add(
                        ReviewQueue(
                            transaction_id=tx.id,
                            document_id=tx.document_id,
                            reason="Duplicate/self-transfer confidence needs confirmation",
                            suggested_action="verify",
                            confidence=tx.confidence,
                        )
                    )
        db.commit()

    def _refresh_session(self, db: Session, session_id: str) -> None:
        with self._session_lock:
            db.expire_all()
            session = db.get(ImportSession, session_id)
            if not session:
                return
            documents = db.scalars(select(Document).where(Document.import_session_id == session_id)).all()
            done_statuses = {DocumentStatus.completed, DocumentStatus.failed, DocumentStatus.skipped}
            completed = sum(1 for item in documents if item.status in done_statuses)
            waiting = sum(1 for item in documents if item.status == DocumentStatus.password_required)
            processing = sum(1 for item in documents if item.status in {DocumentStatus.processing, DocumentStatus.queued})
            session.processed_files = completed
            session.total_transactions = int(
                db.scalar(
                    select(func.count(Transaction.id))
                    .join(Document, Transaction.document_id == Document.id)
                    .where(Document.import_session_id == session_id)
                )
                or 0
            )
            if session.total_files:
                session.progress = int((completed / session.total_files) * 100)
            if completed == session.total_files:
                session.status = "completed"
                session.progress = 100
                session.completed_at = datetime.utcnow()
                session.message = "Import complete"
            elif waiting and not processing:
                session.status = "password_required"
                session.message = f"Password required for {waiting} PDF(s)"
            else:
                session.status = "processing"
                session.message = f"Processed {completed} of {session.total_files} files"
            db.commit()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(filename: str) -> str:
    cleaned = "".join(char for char in Path(filename).name if char.isalnum() or char in "._- ").strip()
    return cleaned[:180] or "upload.bin"


import_manager = ImportManager()
