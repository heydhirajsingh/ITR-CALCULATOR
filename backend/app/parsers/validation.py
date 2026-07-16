"""Post-extraction integrity checks for financial statement transactions."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from backend.app.schemas.api import ParsedTransaction
from backend.app.utils.dates import parse_date


PERIOD_PATTERNS = (
    re.compile(r"statement period\s+from\s+(.{6,20}?)\s+to\s+(.{6,20}?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"period\s*[:\-]\s*(.{6,20}?)\s+(?:to|through|-)\s+(.{6,20}?)(?:\n|$)", re.IGNORECASE),
)


def validate_statement(transactions: list[ParsedTransaction], text: str) -> list[str]:
    warnings: list[str] = []
    if not transactions:
        return ["Completeness check failed: no transaction rows were extracted."]

    invalid_amounts = sum(1 for item in transactions if item.debit <= 0 and item.credit <= 0)
    both_sides = sum(1 for item in transactions if item.debit > 0 and item.credit > 0)
    if invalid_amounts:
        warnings.append(f"Integrity check: {invalid_amounts} row(s) have no positive debit or credit amount.")
    if both_sides:
        warnings.append(f"Integrity check: {both_sides} row(s) contain both debit and credit amounts.")

    balance_pairs = 0
    balance_matches = 0
    for previous, current in zip(transactions, transactions[1:]):
        if previous.balance is None or current.balance is None:
            continue
        balance_pairs += 1
        expected = previous.balance + current.credit - current.debit
        if abs(expected - current.balance) <= Decimal("1.00"):
            balance_matches += 1
    if balance_pairs:
        match_rate = balance_matches / balance_pairs
        if match_rate < 0.98:
            warnings.append(
                f"Running-balance reconciliation is {match_rate:.1%} "
                f"({balance_matches}/{balance_pairs} adjacent rows); verify completeness and account boundaries."
            )
    else:
        warnings.append("Running-balance reconciliation unavailable because fewer than two balances were extracted.")

    period = _statement_period(text)
    if period:
        start, end = period
        outside = sum(1 for item in transactions if item.transaction_date < start or item.transaction_date > end)
        if outside:
            warnings.append(f"Statement-period check: {outside} transaction date(s) fall outside {start} to {end}.")

    return warnings


def _statement_period(text: str) -> tuple[date, date] | None:
    for pattern in PERIOD_PATTERNS:
        match = pattern.search(text[:20000])
        if not match:
            continue
        start = parse_date(match.group(1).strip(" ."))
        end = parse_date(match.group(2).strip(" ."))
        if start and end and start <= end:
            return start, end
    return None
