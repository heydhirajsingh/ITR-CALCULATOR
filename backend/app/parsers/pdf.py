"""PDF parser using PyMuPDF, pdfplumber, Camelot/Tabula and Tesseract fallbacks."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import fitz
import pandas as pd
import pdfplumber

from backend.app.ocr.engine import TesseractOCREngine
from backend.app.parsers.base import (
    DocumentParser,
    InvalidPasswordError,
    ParseResult,
    ParserError,
    PasswordRequiredError,
)
from backend.app.parsers.detector import detect_bank, detect_document_type
from backend.app.parsers.tabular import dataframe_to_transactions, rows_to_dataframe
from backend.app.parsers.validation import validate_statement
from backend.app.schemas.api import ParsedTransaction
from backend.app.utils.amounts import parse_amount
from backend.app.utils.dates import parse_date


class PdfParser(DocumentParser):
    extensions = (".pdf",)

    def __init__(self) -> None:
        self.ocr = TesseractOCREngine()

    def parse(self, path: Path, *, password: str | None = None) -> ParseResult:
        try:
            document = fitz.open(path)
        except Exception as exc:
            raise ParserError(f"Could not open PDF: {exc}") from exc
        if document.needs_pass:
            if not password:
                document.close()
                raise PasswordRequiredError("PDF password is required")
            if not document.authenticate(password):
                document.close()
                raise InvalidPasswordError("The PDF password is incorrect")

        page_texts: list[tuple[int, str, str, float]] = []
        text_parts: list[str] = []
        warnings: list[str] = []
        for number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            method = "pymupdf"
            confidence = 99.0 if text else 0.0
            if len(text) < 40:
                try:
                    ocr = self.ocr.page_to_text(page)
                    if len(ocr.text) > len(text):
                        text = ocr.text
                        method = "tesseract"
                        confidence = ocr.confidence
                except Exception as exc:
                    warnings.append(f"OCR failed on page {number}: {exc}")
            page_texts.append((number, text, method, confidence))
            text_parts.append(text)
        page_count = len(document)
        document.close()
        full_text = "\n".join(text_parts)
        document_type = detect_document_type(path.name, full_text)
        bank_name = detect_bank(path.name, full_text)
        account_number = _extract_account_number(full_text[:5000])
        if document_type in {"Bank Statement", "Credit Card Statement"} and not bank_name:
            warnings.append("Issuing institution could not be confirmed from filename/header evidence; user confirmation is required.")
        if document_type == "Bank Statement" and not account_number:
            warnings.append("Account number could not be confirmed from the statement header; account grouping requires review.")

        transactions: list[ParsedTransaction] = []
        try:
            transactions.extend(self._extract_by_coordinates(path, password, bank_name, account_number))
        except Exception:
            pass
        transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]

        if not transactions:
            try:
                transactions.extend(self._extract_pdfplumber_tables(path, password, bank_name, account_number))
            except Exception:
                pass
            transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]

        if not transactions:
            transactions.extend(self._extract_camelot(path, password, bank_name, account_number))
            transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]
        if not transactions:
            transactions.extend(self._extract_tabula(path, password, bank_name, account_number))
            transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]
        if not transactions:
            transactions.extend(_parse_text_lines(full_text, bank_name, account_number))
            transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]
        if not transactions:
            transactions.extend(_parse_multiline_blocks(full_text, bank_name, account_number))
            transactions = [t for t in transactions if t.debit > 0 or t.credit > 0]

        if not transactions:
            warnings.append("No transaction rows could be normalized automatically; extracted text is retained for review.")
        else:
            warnings.extend(validate_statement(transactions, full_text))

        return ParseResult(
            transactions=transactions,
            document_type=document_type,
            parser_used="PyMuPDF/pdfplumber/Camelot/Tabula/Tesseract",
            page_texts=page_texts,
            warnings=warnings,
            bank_name=bank_name,
            account_number=account_number,
            page_count=page_count,
        )

    def _extract_by_coordinates(
        self, path: Path, password: str | None, bank_name: str | None, account_number: str | None
    ) -> list[ParsedTransaction]:
        txs: list[ParsedTransaction] = []
        date_pat = re.compile(r"^\d{2}/\d{2}/\d{2}$")
        bal_pat = re.compile(r"^[\d,]+\.\d{2}$")
        try:
            with pdfplumber.open(path, password=password) as pdf:
                # 1. Check for Federal Bank 9+ column structure first
                for page in pdf.pages:
                    for t in page.extract_tables() or []:
                        for row in t:
                            if not row:
                                continue
                            if len(row) >= 9 and parse_date(row[0]):
                                d_val = parse_date(row[0])
                                narr = row[2].replace("\n", " ").strip() if len(row) > 2 and row[2] else ""
                                dr = parse_amount(row[6]) if len(row) > 6 and row[6] and parse_amount(row[6]) else Decimal("0")
                                cr = parse_amount(row[7]) if len(row) > 7 and row[7] and parse_amount(row[7]) else Decimal("0")
                                bal = parse_amount(row[8]) if len(row) > 8 and row[8] and parse_amount(row[8]) else None
                                if dr > 0 or cr > 0:
                                    txs.append(
                                        ParsedTransaction(
                                            transaction_date=d_val,
                                            value_date=d_val,
                                            description=narr,
                                            narration=narr,
                                            debit=dr,
                                            credit=cr,
                                            balance=bal,
                                            bank_name=bank_name or "Federal Bank",
                                            account_number=account_number,
                                            source_row=len(txs),
                                            raw_data={"page": page.page_number, "line": len(txs) + 1},
                                        )
                                    )
                if txs:
                    return txs

                # 2. HDFC Bank Coordinate Box Extraction
                for page in pdf.pages:
                    words = page.extract_words()
                    lines_by_top: dict[float, list[dict]] = {}
                    for w in words:
                        top_key = round(w["top"], 0)
                        lines_by_top.setdefault(top_key, []).append(w)

                    sorted_tops = sorted(lines_by_top.keys())
                    row_starts = []
                    for top in sorted_tops:
                        lwords = sorted(lines_by_top[top], key=lambda x: x["x0"])
                        has_date = any(date_pat.match(w["text"]) and w["x0"] < 80 for w in lwords)
                        has_bal = any(bal_pat.match(w["text"]) and w["x0"] > 550 for w in lwords)
                        if has_date and has_bal:
                            row_starts.append(top)

                    for i, start_top in enumerate(row_starts):
                        end_top = row_starts[i + 1] if i + 1 < len(row_starts) else 9999.0
                        row_words = []
                        for top in sorted_tops:
                            if start_top <= top < end_top:
                                row_words.extend(lines_by_top[top])

                        num_words = [w for w in row_words if bal_pat.match(w["text"]) and w["x0"] > 300]
                        d_words = [w for w in row_words if date_pat.match(w["text"]) and w["x0"] < 80]
                        if d_words and len(num_words) >= 2:
                            t_date = parse_date(d_words[0]["text"])
                            balance = parse_amount(num_words[-1]["text"])
                            txn_amount = parse_amount(num_words[-2]["text"])
                            is_debit = bool(num_words[-2]["x0"] < 480.0)
                            debit = txn_amount if is_debit else Decimal("0")
                            credit = Decimal("0") if is_debit else txn_amount
                            desc_words = [w for w in row_words if 70 <= w["x0"] <= 340]
                            desc = " ".join(w["text"] for w in desc_words).strip()
                            txs.append(
                                ParsedTransaction(
                                    transaction_date=t_date,
                                    value_date=t_date,
                                    description=desc,
                                    narration=desc,
                                    debit=debit,
                                    credit=credit,
                                    balance=balance,
                                    bank_name=bank_name or "HDFC Bank",
                                    account_number=account_number,
                                    source_row=i,
                                    raw_data={"page": page.page_number, "line": i + 1},
                                )
                            )
        except Exception:
            pass
        return txs

    def _extract_pdfplumber_tables(
        self, path: Path, password: str | None, bank_name: str | None, account_number: str | None
    ) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        with pdfplumber.open(path, password=password) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    frame = rows_to_dataframe(table)
                    transactions.extend(
                        dataframe_to_transactions(frame, bank_name=bank_name, account_number=account_number)
                    )
        return transactions

    def _extract_camelot(
        self, path: Path, password: str | None, bank_name: str | None, account_number: str | None
    ) -> list[ParsedTransaction]:
        try:
            import camelot

            kwargs = {"pages": "all", "flavor": "stream"}
            if password:
                kwargs["password"] = password
            tables = camelot.read_pdf(str(path), **kwargs)
            transactions: list[ParsedTransaction] = []
            for table in tables:
                raw = table.df
                if raw.empty:
                    continue
                frame = rows_to_dataframe(raw.values.tolist())
                transactions.extend(
                    dataframe_to_transactions(frame, bank_name=bank_name, account_number=account_number)
                )
            return transactions
        except Exception:
            return []

    def _extract_tabula(
        self, path: Path, password: str | None, bank_name: str | None, account_number: str | None
    ) -> list[ParsedTransaction]:
        try:
            import tabula

            kwargs = {"pages": "all", "multiple_tables": True}
            if password:
                kwargs["password"] = password
            frames: list[pd.DataFrame] = tabula.read_pdf(str(path), **kwargs)
            transactions: list[ParsedTransaction] = []
            for frame in frames:
                transactions.extend(
                    dataframe_to_transactions(frame, bank_name=bank_name, account_number=account_number)
                )
            return transactions
        except Exception:
            return []


def _extract_account_number(text: str) -> str | None:
    patterns = (
        r"(?:account|a/c)\s*(?:number|no\.?|#)?\s*[:\-]?\s*([xX*\d]{6,24})",
        r"\b([xX*]{4,}\d{4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _parse_text_lines(text: str, bank_name: str | None, account_number: str | None) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines, start=1):
        parsed = _try_parse_line(line, bank_name=bank_name, account_number=account_number, source_row=index)
        if parsed:
            transactions.append(parsed)
    return transactions


def _try_parse_line(
    line: str, *, bank_name: str | None, account_number: str | None, source_row: int
) -> ParsedTransaction | None:
    match = re.search(
        r"^(?P<date>\d{1,2}[-/\.][A-Za-z0-9]{2,3}[-/\.]\d{2,4})\s+(?P<desc>.+?)\s+(?P<amount>-?[\d,]+\.\d{2})(?:\s+(?P<bal>[\d,]+\.\d{2}))?$",
        line,
    )
    if not match:
        return None
    date_val = parse_date(match.group("date"))
    if not date_val:
        return None
    raw_amount = parse_amount(match.group("amount"))
    description = match.group("desc").strip()
    debit = Decimal("0")
    credit = Decimal("0")
    if raw_amount < 0 or any(token in description.lower() for token in ("dr", "debit", "withdrawal")):
        debit = abs(raw_amount)
    else:
        credit = abs(raw_amount)
    return ParsedTransaction(
        transaction_date=date_val,
        value_date=None,
        description=description,
        narration=description,
        debit=debit,
        credit=credit,
        balance=parse_amount(match.group("bal")) if match.group("bal") else None,
        bank_name=bank_name,
        account_number=account_number,
        source_row=source_row,
    )


def _parse_multiline_blocks(
    full_text: str, bank_name: str | None, account_number: str | None
) -> list[ParsedTransaction]:
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    if not lines:
        return []

    date_re = re.compile(r"^\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}$")
    amount_re = re.compile(r"^[\d,]+\.\d{2}$")
    ref_re = re.compile(r"^\d{10,22}$")

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if date_re.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    results: list[ParsedTransaction] = []
    prev_balance: Decimal | None = None

    for row_index, block in enumerate(blocks, start=1):
        t_date = parse_date(block[0])
        if not t_date:
            continue
        amounts = [parse_amount(line) for line in block if amount_re.match(line)]
        refs = [line for line in block if ref_re.match(line)]
        text_lines = [
            line
            for line in block[1:]
            if not amount_re.match(line) and not ref_re.match(line) and not date_re.match(line)
        ]
        desc = " ".join(text_lines).strip()
        if not desc:
            desc = f"Transaction on {block[0]}"
        if not amounts:
            continue

        balance = amounts[-1] if len(amounts) >= 2 else None
        txn_amount = amounts[0] if len(amounts) >= 2 else amounts[0]
        if txn_amount <= 0:
            continue

        debit = Decimal("0")
        credit = Decimal("0")
        if prev_balance is not None and balance is not None:
            if balance > prev_balance:
                credit = txn_amount
            else:
                debit = txn_amount
        else:
            if any(kw in desc.lower() for kw in ("cr", "deposit", "interest", "refund", "salary")):
                credit = txn_amount
            else:
                debit = txn_amount

        if balance is not None:
            prev_balance = balance

        results.append(
            ParsedTransaction(
                transaction_date=t_date,
                value_date=None,
                description=desc,
                narration=desc,
                debit=debit,
                credit=credit,
                balance=balance,
                reference_number=refs[0] if refs else None,
                utr=refs[0] if refs else None,
                bank_name=bank_name,
                account_number=account_number,
                source_row=row_index,
            )
        )

    return results
