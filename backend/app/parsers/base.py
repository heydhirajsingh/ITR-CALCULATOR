"""Shared parser interfaces and errors."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.app.schemas.api import ParsedTransaction


class ParserError(RuntimeError):
    pass


class PasswordRequiredError(ParserError):
    pass


class InvalidPasswordError(ParserError):
    pass


@dataclass(slots=True)
class ParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    document_type: str = "Unknown"
    parser_used: str = "unknown"
    page_texts: list[tuple[int, str, str, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bank_name: str | None = None
    account_number: str | None = None
    page_count: int = 0
    extra_records: dict[str, list[dict]] = field(default_factory=dict)


class DocumentParser:
    extensions: tuple[str, ...] = ()

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def parse(self, path: Path, *, password: str | None = None) -> ParseResult:
        raise NotImplementedError
