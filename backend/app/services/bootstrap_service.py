"""Seed the local profile and supported financial years."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import TaxYear, User


TAX_YEARS = (
    ("FY 2022-23", "AY 2023-24", date(2022, 4, 1), date(2023, 3, 31)),
    ("FY 2023-24", "AY 2024-25", date(2023, 4, 1), date(2024, 3, 31)),
    ("FY 2024-25", "AY 2025-26", date(2024, 4, 1), date(2025, 3, 31)),
    ("FY 2025-26", "AY 2026-27", date(2025, 4, 1), date(2026, 3, 31)),
)


def bootstrap(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is None:
        db.add(User(name="Local User"))
    existing = set(db.scalars(select(TaxYear.financial_year)).all())
    for financial_year, assessment_year, starts_on, ends_on in TAX_YEARS:
        if financial_year not in existing:
            db.add(
                TaxYear(
                    financial_year=financial_year,
                    assessment_year=assessment_year,
                    starts_on=starts_on,
                    ends_on=ends_on,
                    is_active=financial_year == "FY 2025-26",
                    rule_version="builtin-2026-07",
                )
            )
    db.commit()
