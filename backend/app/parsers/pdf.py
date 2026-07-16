"""PDF parser using PyMuPDF, pdfplumber, Camelot/Tabula and Tesseract fallbacks."""
from __future__ import annotations

import re
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
        # Account identifiers must come from statement headers, never beneficiary rows.
        account_number = _extract_account_number(full_text[:5000])
        if document_type in {"Bank Statement", "Credit Card Statement"} and not bank_name:
            warnings.append("Issuing institution could not be confirmed from filename/header evidence; user confirmation is required.")
        if document_type == "Bank Statement" and not account_number:
            warnings.append("Account number could not be confirmed from the statement header; account grouping requires review.")

        transactions: list[ParsedTransaction] = []
        try:
            transactions.extend(self._extract_pdfplumber_tables(path, password, bank_name, account_number))
        except Exception as exc:
            warnings.append(f"pdfplumber table extraction warning: {exc}")
        if not transactions:
            transactions.extend(self._extract_camelot(path, bank_name, account_number, warnings))
        if not transactions:
            transactions.extend(self._extract_tabula(path, bank_name, account_number, warnings))
        if not transactions:
            transactions.extend(_parse_text_lines(full_text, bank_name, account_number))
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
        self, path: Path, bank_name: str | None, account_number: str | None, warnings: list[str]
    ) -> list[ParsedTransaction]:
        try:
            import camelot

            tables = camelot.read_pdf(str(path), pages="all", flavor="stream")
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
        except Exception as exc:
            warnings.append(f"Camelot fallback unavailable or failed: {exc}")
            return []

    def _extract_tabula(
        self, path: Path, bank_name: str | None, account_number: str | None, warnings: list[str]
    ) -> list[ParsedTransaction]:
        try:
            import tabula

            frames: list[pd.DataFrame] = tabula.read_pdf(str(path), pages="all", multiple_tables=True)
            transactions: list[ParsedTransaction] = []
            for frame in frames:
                transactions.extend(
                    dataframe_to_transactions(frame, bank_name=bank_name, account_number=account_number)
                )
            return transactions
        except Exception as exc:
            warnings.append(f"Tabula fallback unavailable or failed: {exc}")
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


def _parse_text_lines(
    text: str, bank_name: str | None, account_number: str | None
) -> list[ParsedTransaction]:
    results: list[ParsedTransaction] = []
    date_pattern = re.compile(r"^\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[- ][A-Za-z]{3}[- ]\d{2,4})\s+")
    amount_pattern = re.compile(r"(?:\(?-?\d[\d,]*\.\d{2}\)?)(?:\s*(?:Cr|Dr))?", re.IGNORECASE)
    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        line = " ".join(raw_line.split())
        date_match = date_pattern.match(line)
        if not date_match:
            continue
        day = parse_date(date_match.group(1))
        if not day:
            continue
        amounts = list(amount_pattern.finditer(line))
        if not amounts:
            continue
        parsed = [parse_amount(match.group(0)) for match in amounts]
        description_end = amounts[0].start()
        description = line[date_match.end() : description_end].strip(" -|")
        debit = parse_amount(0)
        credit = parse_amount(0)
        balance = None
        if len(parsed) >= 3:
            debit, credit, balance = abs(parsed[-3]), abs(parsed[-2]), parsed[-1]
        elif len(parsed) == 2:
            marker = line[amounts[0].end() : amounts[1].start()].lower()
            if "dr" in marker or any(token in description.lower() for token in ("withdraw", "debit", "purchase", "payment")):
                debit, balance = abs(parsed[0]), parsed[1]
            else:
                credit, balance = abs(parsed[0]), parsed[1]
        else:
            marker = line.lower()
            if " dr" in marker or any(token in description.lower() for token in ("withdraw", "debit", "purchase", "payment")):
                debit = abs(parsed[0])
            else:
                credit = abs(parsed[0])
        if debit == 0 and credit == 0:
            continue
        results.append(
            ParsedTransaction(
                transaction_date=day,
                description=description or line,
                narration=line,
                debit=debit,
                credit=credit,
                balance=balance,
                bank_name=bank_name,
                account_number=account_number,
                raw_data={"line": line},
                source_row=row_number,
            )
        )
    return results
