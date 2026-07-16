from decimal import Decimal

from backend.app.classification.engine import classifier


def test_salary_credit_is_taxable_with_high_confidence():
    result = classifier.classify(
        "NEFT SALARY ACME PRIVATE LIMITED APRIL",
        debit=Decimal("0"),
        credit=Decimal("125000"),
        document_type="Bank Statement",
    )
    assert result.category == "Salary"
    assert result.income_type == "Salary Income"
    assert result.taxable is True
    assert result.confidence >= 95


def test_unknown_credit_is_sent_to_review_not_taxed():
    result = classifier.classify(
        "TRANSFER FROM RAHUL",
        debit=Decimal("0"),
        credit=Decimal("50000"),
        document_type="Bank Statement",
    )
    assert result.needs_review is True
    assert result.taxable is False


def test_refund_is_ignored():
    result = classifier.classify(
        "AMAZON ORDER REFUND",
        debit=Decimal("0"),
        credit=Decimal("2499"),
        document_type="Bank Statement",
    )
    assert result.category == "Refund"
    assert result.ignored is True
