"""Versioned Indian individual income-tax rules used by the estimator.

The system is an ITR preparation aid, not a filing engine. Rules are isolated here so a
qualified reviewer can update them without touching ingestion or reconciliation code.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True, slots=True)
class TaxRuleSet:
    financial_year: str
    new_slabs: tuple[tuple[Decimal | None, Decimal], ...]
    old_slabs_adult: tuple[tuple[Decimal | None, Decimal], ...]
    old_slabs_senior: tuple[tuple[Decimal | None, Decimal], ...]
    old_slabs_super_senior: tuple[tuple[Decimal | None, Decimal], ...]
    new_rebate_threshold: Decimal
    new_rebate_max: Decimal
    old_rebate_threshold: Decimal = D("500000")
    old_rebate_max: Decimal = D("12500")
    new_standard_deduction: Decimal = D("0")
    old_standard_deduction: Decimal = D("50000")
    cess_rate: Decimal = D("0.04")
    new_surcharge_cap: Decimal = D("0.25")


OLD_ADULT = ((D("250000"), D("0")), (D("500000"), D("0.05")), (D("1000000"), D("0.20")), (None, D("0.30")))
OLD_SENIOR = ((D("300000"), D("0")), (D("500000"), D("0.05")), (D("1000000"), D("0.20")), (None, D("0.30")))
OLD_SUPER = ((D("500000"), D("0")), (D("1000000"), D("0.20")), (None, D("0.30")))

RULES: dict[str, TaxRuleSet] = {
    "FY 2022-23": TaxRuleSet(
        financial_year="FY 2022-23",
        new_slabs=((D("250000"), D("0")), (D("500000"), D("0.05")), (D("750000"), D("0.10")), (D("1000000"), D("0.15")), (D("1250000"), D("0.20")), (D("1500000"), D("0.25")), (None, D("0.30"))),
        old_slabs_adult=OLD_ADULT,
        old_slabs_senior=OLD_SENIOR,
        old_slabs_super_senior=OLD_SUPER,
        new_rebate_threshold=D("500000"),
        new_rebate_max=D("12500"),
        new_standard_deduction=D("0"),
    ),
    "FY 2023-24": TaxRuleSet(
        financial_year="FY 2023-24",
        new_slabs=((D("300000"), D("0")), (D("600000"), D("0.05")), (D("900000"), D("0.10")), (D("1200000"), D("0.15")), (D("1500000"), D("0.20")), (None, D("0.30"))),
        old_slabs_adult=OLD_ADULT,
        old_slabs_senior=OLD_SENIOR,
        old_slabs_super_senior=OLD_SUPER,
        new_rebate_threshold=D("700000"),
        new_rebate_max=D("25000"),
        new_standard_deduction=D("50000"),
    ),
    "FY 2024-25": TaxRuleSet(
        financial_year="FY 2024-25",
        new_slabs=((D("300000"), D("0")), (D("700000"), D("0.05")), (D("1000000"), D("0.10")), (D("1200000"), D("0.15")), (D("1500000"), D("0.20")), (None, D("0.30"))),
        old_slabs_adult=OLD_ADULT,
        old_slabs_senior=OLD_SENIOR,
        old_slabs_super_senior=OLD_SUPER,
        new_rebate_threshold=D("700000"),
        new_rebate_max=D("25000"),
        new_standard_deduction=D("75000"),
    ),
    "FY 2025-26": TaxRuleSet(
        financial_year="FY 2025-26",
        new_slabs=((D("400000"), D("0")), (D("800000"), D("0.05")), (D("1200000"), D("0.10")), (D("1600000"), D("0.15")), (D("2000000"), D("0.20")), (D("2400000"), D("0.25")), (None, D("0.30"))),
        old_slabs_adult=OLD_ADULT,
        old_slabs_senior=OLD_SENIOR,
        old_slabs_super_senior=OLD_SUPER,
        new_rebate_threshold=D("1200000"),
        new_rebate_max=D("60000"),
        new_standard_deduction=D("75000"),
    ),
}

NEW_ALLOWED_DEDUCTIONS = {"80CCD(2)", "80CCH", "80JJAA"}

DEDUCTION_LIMITS: dict[str, Decimal | None] = {
    "80C": D("150000"),
    "80CCC": D("150000"),
    "80CCD(1)": D("150000"),
    "80CCD(1B)": D("50000"),
    "80D": D("100000"),
    "80DD": D("125000"),
    "80E": None,
    "80EE": D("50000"),
    "80EEA": D("150000"),
    "80G": None,
    "80GG": D("60000"),
    "80TTA": D("10000"),
    "80TTB": D("50000"),
    "80U": D("125000"),
    "80CCD(2)": None,
    "80CCH": None,
    "80JJAA": None,
}
