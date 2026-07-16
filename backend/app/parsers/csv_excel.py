"""CSV and Excel statement parsers with Pandas/Polars fallbacks."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.parsers.base import DocumentParser, ParseResult, ParserError
from backend.app.parsers.detector import detect_bank, detect_document_type
from backend.app.parsers.tabular import dataframe_to_transactions


class CsvExcelParser(DocumentParser):
    extensions = (".csv", ".xlsx", ".xls", ".xlsm")

    def parse(self, path: Path, *, password: str | None = None) -> ParseResult:
        del password
        warnings: list[str] = []
        frames: list[pd.DataFrame] = []
        if path.suffix.lower() == ".csv":
            frames.append(self._read_csv(path, warnings))
        else:
            try:
                sheets = pd.read_excel(path, sheet_name=None, dtype=object)
            except Exception as exc:
                raise ParserError(f"Could not read Excel workbook: {exc}") from exc
            frames.extend(frame for frame in sheets.values() if not frame.empty)

        sample_text = "\n".join(" ".join(map(str, frame.columns)) for frame in frames[:5])
        document_type = detect_document_type(path.name, sample_text)
        bank_name = detect_bank(path.name, sample_text)
        transactions = []
        for frame in frames:
            transactions.extend(dataframe_to_transactions(frame, bank_name=bank_name))

        if not transactions:
            warnings.append("No standard transaction table was detected; the document remains available for review.")
        return ParseResult(
            transactions=transactions,
            document_type=document_type,
            parser_used="pandas/polars",
            warnings=warnings,
            bank_name=bank_name,
        )

    def _read_csv(self, path: Path, warnings: list[str]) -> pd.DataFrame:
        if path.stat().st_size > 50 * 1024 * 1024:
            try:
                import polars as pl

                return pl.read_csv(path, infer_schema_length=10000, ignore_errors=True).to_pandas()
            except Exception as exc:
                warnings.append(f"Polars fast path failed; using Pandas: {exc}")
        attempts = (
            {"encoding": "utf-8-sig"},
            {"encoding": "utf-8"},
            {"encoding": "cp1252"},
            {"encoding": "latin-1"},
        )
        last_error: Exception | None = None
        for options in attempts:
            try:
                return pd.read_csv(path, dtype=object, sep=None, engine="python", **options)
            except Exception as exc:
                last_error = exc
        raise ParserError(f"Could not read CSV: {last_error}")
