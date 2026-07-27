from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.entities import (
    Account,
    Bank,
    Document,
    DocumentStatus,
    ImportSession,
    TaxYear,
    Transaction,
    TransactionDirection,
    User,
)
from backend.app.services.duplicate_service import DuplicateDetector
from backend.app.services.transfer_service import SelfTransferDetector


def session_with_schema() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(db: Session):
    user = User(name="Test User")
    bank1 = Bank(name="HDFC Bank")
    bank2 = Bank(name="State Bank of India")
    db.add_all([user, bank1, bank2])
    db.flush()
    account1 = Account(user_id=user.id, bank_id=bank1.id, name="HDFC", masked_number="1111", is_owned=True, metadata_json={"ownership_confirmed": True})
    account2 = Account(user_id=user.id, bank_id=bank2.id, name="SBI", masked_number="2222", is_owned=True, metadata_json={"ownership_confirmed": True})
    session = ImportSession(id="test", total_files=2)
    db.add_all([account1, account2, session])
    db.flush()
    doc1 = Document(import_session_id=session.id, filename="hdfc.csv", stored_path="x", sha256="a" * 64, document_type="Bank Statement", status=DocumentStatus.completed)
    doc2 = Document(import_session_id=session.id, filename="ais.csv", stored_path="y", sha256="b" * 64, document_type="AIS", status=DocumentStatus.completed)
    year = TaxYear(financial_year="FY 2025-26", assessment_year="AY 2026-27", starts_on=date(2025, 4, 1), ends_on=date(2026, 3, 31))
    db.add_all([doc1, doc2, year])
    db.flush()
    return account1, account2, doc1, doc2, year


def test_duplicate_detector_links_cross_document_rows():
    db = session_with_schema()
    account1, _, doc1, doc2, year = seed(db)
    first = Transaction(document_id=doc1.id, account_id=account1.id, tax_year_id=year.id, transaction_date=date(2025, 4, 5), description="SALARY ACME", credit=Decimal("125000"), debit=0, amount=Decimal("125000"), direction=TransactionDirection.credit, reference_number="SALAPR25")
    second = Transaction(document_id=doc2.id, account_id=account1.id, tax_year_id=year.id, transaction_date=date(2025, 4, 5), description="SALARY FROM ACME", credit=Decimal("125000"), debit=0, amount=Decimal("125000"), direction=TransactionDirection.credit, reference_number="SALAPR25")
    db.add_all([first, second]); db.commit()
    DuplicateDetector().process(db, [second.id])
    db.refresh(second)
    assert second.is_duplicate is True
    assert second.duplicate_of_id == first.id
    assert second.ignored is True


def test_self_transfer_detector_links_opposite_sides():
    db = session_with_schema()
    account1, account2, doc1, _, year = seed(db)
    debit = Transaction(document_id=doc1.id, account_id=account1.id, tax_year_id=year.id, transaction_date=date(2025, 4, 6), description="UPI SELF TRANSFER", debit=Decimal("50000"), credit=0, amount=Decimal("50000"), direction=TransactionDirection.debit, utr="UPI10001")
    credit = Transaction(document_id=doc1.id, account_id=account2.id, tax_year_id=year.id, transaction_date=date(2025, 4, 6), description="UPI OWN ACCOUNT", debit=0, credit=Decimal("50000"), amount=Decimal("50000"), direction=TransactionDirection.credit, utr="UPI10001")
    db.add_all([debit, credit]); db.commit()
    SelfTransferDetector().process(db, [debit.id, credit.id])
    db.refresh(debit); db.refresh(credit)
    assert debit.is_self_transfer and credit.is_self_transfer
    assert debit.linked_transaction_id == credit.id
    assert credit.linked_transaction_id == debit.id
    assert debit.ignored and credit.ignored


def test_self_transfer_detector_matches_user_name():
    db = session_with_schema()
    account1, _, doc1, _, year = seed(db)
    tx = Transaction(
        document_id=doc1.id,
        account_id=account1.id,
        tax_year_id=year.id,
        transaction_date=date(2025, 4, 10),
        description="UPI/TEST USER/TRANSFER TO OWN",
        debit=Decimal("15000"),
        credit=0,
        amount=Decimal("15000"),
        direction=TransactionDirection.debit,
    )
    db.add(tx)
    db.commit()
    SelfTransferDetector().process(db, [tx.id])
    db.refresh(tx)
    assert tx.is_self_transfer is True
    assert tx.category == "Self Transfer"
    assert tx.ignored is True
    assert tx.needs_review is False


def test_duplicate_detector_does_not_merge_repeated_same_document_payments():
    db = session_with_schema()
    account1, _, doc1, _, year = seed(db)
    first = Transaction(document_id=doc1.id, account_id=account1.id, tax_year_id=year.id, transaction_date=date(2025, 4, 5), description="MONTHLY RENT", debit=Decimal("25000"), credit=0, amount=Decimal("25000"), direction=TransactionDirection.debit, source_row=2)
    second = Transaction(document_id=doc1.id, account_id=account1.id, tax_year_id=year.id, transaction_date=date(2025, 4, 6), description="MONTHLY RENT", debit=Decimal("25000"), credit=0, amount=Decimal("25000"), direction=TransactionDirection.debit, source_row=3)
    db.add_all([first, second]); db.commit()
    DuplicateDetector().process(db, [second.id])
    db.refresh(second)
    assert second.is_duplicate is False
    assert second.ignored is False
