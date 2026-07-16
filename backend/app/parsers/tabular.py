"""Generic tabular statement normalization for CSV, Excel and extracted PDF tables."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd

from backend.app.schemas.api import ParsedTransaction
from backend.app.utils.amounts import parse_amount
from backend.app.utils.dates import parse_date

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "txn date", "transaction date", "posting date", "value date", "trade date"),
    "value_date": ("value date", "val date"),
    "description": ("description", "narration", "particulars", "details", "transaction remarks", "remarks"),
    "debit": ("debit", "withdrawal", "withdrawal amt", "debit amount", "dr amount", "paid out"),
    "credit": ("credit", "deposit", "deposit amt", "credit amount", "cr amount", "paid in"),
    "amount": ("amount", "transaction amount", "txn amount"),
    "balance": ("balance", "closing balance", "available balance", "running balance"),
    "reference": ("reference", "reference no", "ref no", "transaction id", "txn id", "chq/ref no", "chq no"),
    "utr": ("utr", "utr no", "bank reference"),
    "mode": ("mode", "transaction type", "type", "channel"),
    "counterparty": ("counterparty", "beneficiary", "payer", "payee", "party name"),
    "account": ("account", "account number", "a/c no", "account no"),
}


def normalize_header(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return re.sub(r"[^a-z0-9/ ]", "", text)


def find_column(columns: Iterable[Any], logical_name: str) -> Any | None:
    normalized = {column: normalize_header(column) for column in columns}
    aliases = COLUMN_ALIASES[logical_name]
    for column, label in normalized.items():
        if label in aliases:
            return column
    for column, label in normalized.items():
        if any(alias in label for alias in aliases):
            return column
    return None


def dataframe_to_transactions(
    frame: pd.DataFrame,
    *,
    bank_name: str | None = None,
    account_number: str | None = None,
) -> list[ParsedTransaction]:
    if frame.empty:
        return []
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    date_col = find_column(frame.columns, "date")
    description_col = find_column(frame.columns, "description")
    debit_col = find_column(frame.columns, "debit")
    credit_col = find_column(frame.columns, "credit")
    amount_col = find_column(frame.columns, "amount")
    balance_col = find_column(frame.columns, "balance")
    reference_col = find_column(frame.columns, "reference")
    utr_col = find_column(frame.columns, "utr")
    mode_col = find_column(frame.columns, "mode")
    counterparty_col = find_column(frame.columns, "counterparty")
    account_col = find_column(frame.columns, "account")
    value_date_col = find_column(frame.columns, "value_date")

    if date_col is None:
        return []

    results: list[ParsedTransaction] = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        transaction_date = parse_date(row.get(date_col))
        if transaction_date is None:
            continue
        description = str(row.get(description_col, "") if description_col else "").strip()
        debit = parse_amount(row.get(debit_col)) if debit_col else Decimal("0")
        credit = parse_amount(row.get(credit_col)) if credit_col else Decimal("0")
        if debit == 0 and credit == 0 and amount_col:
            amount = parse_amount(row.get(amount_col))
            description_lower = description.lower()
            marker = " ".join(str(value) for value in row.tolist()).lower()
            if amount < 0 or any(token in marker for token in (" debit", " dr", "withdrawal")):
                debit = abs(amount)
            elif any(token in marker for token in (" credit", " cr", "deposit")):
                credit = abs(amount)
            else:
                credit = max(amount, Decimal("0"))
                debit = abs(min(amount, Decimal("0")))
        if debit == 0 and credit == 0:
            continue

        raw = {str(key): _safe_value(value) for key, value in row.to_dict().items()}
        reference = str(row.get(reference_col, "")).strip() if reference_col else None
        utr = str(row.get(utr_col, "")).strip() if utr_col else _extract_utr(description)
        mode = str(row.get(mode_col, "")).strip() if mode_col else _infer_mode(description)
        counterparty = str(row.get(counterparty_col, "")).strip() if counterparty_col else None
        acct = str(row.get(account_col, "")).strip() if account_col else account_number
        results.append(
            ParsedTransaction(
                transaction_date=transaction_date,
                value_date=parse_date(row.get(value_date_col)) if value_date_col else None,
                description=description,
                narration=description,
                debit=abs(debit),
                credit=abs(credit),
                balance=parse_amount(row.get(balance_col)) if balance_col else None,
                reference_number=reference or None,
                utr=utr,
                mode=mode,
                counterparty=counterparty or None,
                bank_name=bank_name,
                account_number=acct or account_number,
                raw_data=raw,
                source_row=row_number,
            )
        )
    return results


def rows_to_dataframe(rows: list[list[Any]]) -> pd.DataFrame:
    cleaned = [["" if cell is None else str(cell).strip() for cell in row] for row in rows if row]
    if len(cleaned) < 2:
        return pd.DataFrame()
    header_index = _find_header_row(cleaned)
    header = cleaned[header_index]
    width = len(header)
    data = [row[:width] + [""] * max(0, width - len(row)) for row in cleaned[header_index + 1 :]]
    return pd.DataFrame(data, columns=_dedupe_headers(header))


def _find_header_row(rows: list[list[str]]) -> int:
    best_index = 0
    best_score = -1
    keywords = {alias for aliases in COLUMN_ALIASES.values() for alias in aliases}
    for index, row in enumerate(rows[:15]):
        labels = [normalize_header(cell) for cell in row]
        score = sum(1 for label in labels if any(keyword in label for keyword in keywords))
        if score > best_score:
            best_score, best_index = score, index
    return best_index


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers):
        base = header or f"column_{index + 1}"
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def _extract_utr(text: str) -> str | None:
    match = re.search(r"\b(?:UTR[:\s-]*)?([A-Z0-9]{12,30})\b", text.upper())
    return match.group(1) if match and any(char.isdigit() for char in match.group(1)) else None


def _infer_mode(text: str) -> str | None:
    upper = text.upper()
    for mode in ("UPI", "NEFT", "RTGS", "IMPS", "ACH", "NACH", "CHEQUE", "CASH", "POS", "ATM"):
        if mode in upper:
            return mode
    return None


def _safe_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value) if not isinstance(value, (int, float, bool)) else value
