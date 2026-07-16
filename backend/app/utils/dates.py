"""Date parsing and financial-year helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from dateutil import parser as date_parser


COMMON_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d %B %Y",
)


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    for fmt in COMMON_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return date_parser.parse(text, dayfirst=True, fuzzy=False).date()
    except (ValueError, TypeError, OverflowError):
        return None


def financial_year_for(day: date) -> str:
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"FY {start_year}-{str(start_year + 1)[-2:]}"


def financial_year_bounds(financial_year: str) -> tuple[date, date]:
    cleaned = financial_year.upper().replace("FY", "").strip()
    start = int(cleaned.split("-")[0])
    return date(start, 4, 1), date(start + 1, 3, 31)
