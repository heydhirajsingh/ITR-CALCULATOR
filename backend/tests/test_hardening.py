from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.classification.engine import classifier
from backend.app.classification.rules_service import classification_rule_service, narration_pattern
from backend.app.core.config import get_settings
from backend.app.database.base import Base
from backend.app.api.routes import merge_documents_into_account
from backend.app.models.entities import (
    Account,
    Bank,
    ClassificationRule,
    Document,
    DocumentStatus,
    ImportSession,
    TaxYear,
    Transaction,
    TransactionDirection,
    User,
)
from backend.app.parsers.detector import detect_bank, detect_document_type
from backend.app.parsers.validation import validate_statement
from backend.app.schemas.api import DocumentAccountMerge, ParsedTransaction
from backend.app.services.import_service import ImportManager


def test_filename_and_header_beat_counterparty_bank_mentions():
    body = "SBI NEFT COUNTERPARTY\nHDFC PAYMENT\n" * 100
    assert detect_bank("IDFCFIRSTBankstatement.pdf", body) == "IDFC First Bank"
    assert detect_document_type("IDFCFIRSTBankstatement.pdf", "debit credit opening balance ledger") == "Bank Statement"


def test_body_bank_names_do_not_claim_statement_issuer():
    text = "Your Account Statement\nStatement Period from Apr 01, 2025 to Apr 30, 2025\n"
    text += " " * 1300 + "SBI HDFC ICICI beneficiary narrations"
    assert detect_bank("monthly-statement.pdf", text) is None


def test_balance_reconciliation_accepts_consistent_rows():
    rows = [
        ParsedTransaction(transaction_date=date(2025, 4, 1), description="A", credit=Decimal("100"), balance=Decimal("100")),
        ParsedTransaction(transaction_date=date(2025, 4, 2), description="B", debit=Decimal("25"), balance=Decimal("75")),
    ]
    warnings = validate_statement(rows, "Statement Period from Apr 01, 2025 to Apr 30, 2025\n")
    assert not any("reconciliation" in warning.lower() for warning in warnings)


def test_low_confidence_debit_does_not_enter_tax_review_queue():
    result = classifier.classify(
        "RAILWAY HOTEL TRAVEL",
        debit=Decimal("1500"),
        credit=Decimal("0"),
        document_type="Bank Statement",
    )
    assert result.category == "Travel"
    assert result.needs_review is False


def test_user_rule_applies_to_matching_narrations_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    year = TaxYear(
        financial_year="FY 2025-26",
        assessment_year="AY 2026-27",
        starts_on=date(2025, 4, 1),
        ends_on=date(2026, 3, 31),
    )
    db.add(year); db.flush()
    matching = Transaction(tax_year_id=year.id, transaction_date=date(2025, 4, 5), description="NEFT ACME SALARY APR25 REF123", debit=0, credit=Decimal("100000"), amount=Decimal("100000"), direction=TransactionDirection.credit, needs_review=True)
    other = Transaction(tax_year_id=year.id, transaction_date=date(2025, 4, 5), description="TRANSFER FROM FRIEND", debit=0, credit=Decimal("5000"), amount=Decimal("5000"), direction=TransactionDirection.credit, needs_review=True)
    db.add_all([matching, other]); db.flush()
    rule = classification_rule_service.save(db, pattern=matching.description, direction="credit", category="Salary", income_type="Salary Income", counterparty="Acme", taxable=True, exempt=False, ignored=False)
    assert isinstance(rule, ClassificationRule)
    assert narration_pattern(matching.description) == rule.normalized_pattern
    assert classification_rule_service.apply_to_matching(db, rule, year.id) == 1
    assert matching.taxable is True and matching.needs_review is False
    assert other.needs_review is True


def test_exact_duplicate_file_is_skipped_even_when_renamed(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    payload = b"date,description,credit\n2025-04-01,Receipt,100\n"
    digest = hashlib.sha256(payload).hexdigest()
    test_root = get_settings().temp_dir / f"duplicate-test-{uuid.uuid4().hex}"
    test_root.mkdir(parents=True)
    session = ImportSession(id="duplicate-test", total_files=1, status="uploaded")
    original = Document(
        import_session_id=session.id,
        filename="original.csv",
        stored_path=str(test_root / "original.csv"),
        sha256=digest,
        document_type="Bank Statement",
        status=DocumentStatus.completed,
    )
    db.add_all([session, original])
    db.commit()

    renamed_copy = test_root / "renamed-copy.csv"
    renamed_copy.write_bytes(payload)
    manager = ImportManager()
    monkeypatch.setattr(manager.settings, "data_dir", test_root / "runtime")
    monkeypatch.setattr(manager, "queue_document", lambda _document_id: None)
    monkeypatch.setattr(manager, "_refresh_session", lambda _db, _session_id: None)
    duplicate = manager.register_file(db, session, renamed_copy, "renamed-copy.csv", "text/csv")
    manager.executor.shutdown(wait=False, cancel_futures=True)

    assert duplicate.status == DocumentStatus.skipped
    assert "exact duplicate" in duplicate.warnings[0].lower()
    assert f"#{original.id}" in duplicate.warnings[0]
    Path(duplicate.stored_path).unlink()
    Path(duplicate.stored_path).parent.rmdir()
    manager.settings.upload_dir.rmdir()
    manager.settings.data_dir.rmdir()
    test_root.rmdir()


def test_selected_documents_merge_into_account_without_changing_tax_year():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(name="Merge Test")
    bank = Bank(name="Merge Bank")
    year = TaxYear(
        financial_year="FY 2025-26",
        assessment_year="AY 2026-27",
        starts_on=date(2025, 4, 1),
        ends_on=date(2026, 3, 31),
    )
    session = ImportSession(id="merge-session", total_files=2, status="completed")
    db.add_all([user, bank, year, session])
    db.flush()
    target = Account(user_id=user.id, bank_id=bank.id, name="Main account", masked_number="1234", is_owned=False, metadata_json={"ownership_confirmed": False})
    fallback_one = Account(user_id=user.id, name="Imported 1", masked_number="DOC-1", is_owned=False, metadata_json={"ownership_confirmed": False, "source": "automatic import"})
    fallback_two = Account(user_id=user.id, name="Imported 2", masked_number="DOC-2", is_owned=False, metadata_json={"ownership_confirmed": False, "source": "automatic import"})
    db.add_all([target, fallback_one, fallback_two])
    db.flush()
    documents = [
        Document(import_session_id=session.id, filename=f"part-{index}.pdf", stored_path=f"part-{index}.pdf", sha256=str(index) * 64, document_type="Bank Statement", status=DocumentStatus.completed)
        for index in (1, 2)
    ]
    db.add_all(documents)
    db.flush()
    transactions = [
        Transaction(document_id=documents[0].id, account_id=fallback_one.id, tax_year_id=year.id, transaction_date=date(2025, 5, 1), description="A", debit=0, credit=100, amount=100, direction=TransactionDirection.credit),
        Transaction(document_id=documents[1].id, account_id=fallback_two.id, tax_year_id=year.id, transaction_date=date(2025, 6, 1), description="B", debit=0, credit=200, amount=200, direction=TransactionDirection.credit),
    ]
    db.add_all(transactions)
    db.commit()

    result = merge_documents_into_account(
        DocumentAccountMerge(document_ids=[item.id for item in documents], target_account_id=target.id),
        db,
    )

    assert result["documents"] == 2 and result["transactions"] == 2
    assert all(item.account_id == target.id for item in transactions)
    assert all(item.tax_year_id == year.id for item in transactions)
    assert all(item.detected_account == "1234" for item in documents)
    assert db.get(Account, fallback_one.id) is None
    assert db.get(Account, fallback_two.id) is None
