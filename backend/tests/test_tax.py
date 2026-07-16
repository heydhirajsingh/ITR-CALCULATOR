from decimal import Decimal

from backend.app.tax.calculator import tax_calculator


def test_fy_2025_26_salary_at_rebate_limit_has_no_tax():
    result = tax_calculator.calculate(
        financial_year="FY 2025-26",
        gross_taxable_income=Decimal("1275000"),
        salary_income=Decimal("1275000"),
        regime="new",
        resident=True,
    )
    assert result.net_taxable_income == Decimal("1200000")
    assert result.total_tax == Decimal("0")


def test_old_regime_80c_combined_limit_is_capped():
    result = tax_calculator.calculate(
        financial_year="FY 2024-25",
        gross_taxable_income=Decimal("1200000"),
        salary_income=Decimal("1200000"),
        deductions={
            "80C": Decimal("150000"),
            "80CCC": Decimal("100000"),
            "80CCD(1B)": Decimal("50000"),
        },
        regime="old",
    )
    assert result.chapter_vi_a_deductions == Decimal("200000")


def test_compare_returns_recommendation():
    result = tax_calculator.compare(
        financial_year="FY 2025-26",
        gross_taxable_income=Decimal("2000000"),
        salary_income=Decimal("2000000"),
        deductions={"80C": Decimal("150000"), "80D": Decimal("25000")},
    )
    assert result["recommended"] in {"old", "new"}
    assert result["estimated_savings"] >= 0
