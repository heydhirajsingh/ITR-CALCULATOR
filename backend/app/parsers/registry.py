"""Parser registry for supported local document formats."""
from __future__ import annotations

from pathlib import Path

from backend.app.parsers.base import DocumentParser
from backend.app.parsers.csv_excel import CsvExcelParser
from backend.app.parsers.pdf import PdfParser
from backend.app.parsers.text_docx import TextDocxParser
from backend.app.parsers.zip_archive import ZipArchiveParser


class ParserRegistry:
    def __init__(self) -> None:
        self.parsers: list[DocumentParser] = [CsvExcelParser(), PdfParser(), TextDocxParser()]
        self.parsers.append(ZipArchiveParser(lambda: self))

    def get_parser(self, path: Path) -> DocumentParser | None:
        for parser in self.parsers:
            if parser.supports(path):
                return parser
        return None


registry = ParserRegistry()
