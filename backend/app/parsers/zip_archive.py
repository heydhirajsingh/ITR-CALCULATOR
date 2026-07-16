"""Safe ZIP archive parser for batches of local financial documents."""
from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from backend.app.parsers.base import (
    DocumentParser,
    InvalidPasswordError,
    ParseResult,
    ParserError,
    PasswordRequiredError,
)

SUPPORTED = {".pdf", ".csv", ".xlsx", ".xls", ".xlsm", ".txt", ".docx"}


class ZipArchiveParser(DocumentParser):
    extensions = (".zip",)

    def __init__(self, registry_provider) -> None:  # type: ignore[no-untyped-def]
        self.registry_provider = registry_provider

    def parse(self, path: Path, *, password: str | None = None) -> ParseResult:
        transactions = []
        warnings: list[str] = []
        page_texts: list[tuple[int, str, str, float]] = []
        types: list[str] = []
        bank_names: set[str] = set()
        account_numbers: set[str] = set()
        member_hashes: set[str] = set()
        try:
            archive = zipfile.ZipFile(path)
        except Exception as exc:
            raise ParserError(f"Could not open ZIP archive: {exc}") from exc
        with archive, tempfile.TemporaryDirectory(prefix="itr_zip_") as temp_dir:
            encrypted_members = [item for item in archive.infolist() if not item.is_dir() and item.flag_bits & 0x1]
            if encrypted_members and not password:
                raise PasswordRequiredError("Password required for this ZIP archive")
            zip_password = password.encode("utf-8") if password else None
            base = Path(temp_dir).resolve()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                pure = PurePosixPath(member.filename)
                if pure.is_absolute() or ".." in pure.parts:
                    warnings.append(f"Skipped unsafe ZIP member: {member.filename}")
                    continue
                if pure.suffix.lower() not in SUPPORTED:
                    warnings.append(f"Skipped unsupported ZIP member: {member.filename}")
                    continue
                target = (base / Path(*pure.parts)).resolve()
                if base not in target.parents:
                    warnings.append(f"Skipped unsafe ZIP member: {member.filename}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(member, pwd=zip_password) as source:
                        content = source.read()
                except RuntimeError as exc:
                    if member.flag_bits & 0x1:
                        raise InvalidPasswordError("The ZIP password is incorrect") from exc
                    warnings.append(f"Could not read ZIP member {member.filename}: {exc}")
                    continue
                member_hash = hashlib.sha256(content).hexdigest()
                if member_hash in member_hashes:
                    warnings.append(f"Skipped duplicate ZIP member: {member.filename}")
                    continue
                member_hashes.add(member_hash)
                target.write_bytes(content)
                parser = self.registry_provider().get_parser(target)
                if parser is None:
                    continue
                try:
                    result = parser.parse(target, password=password)
                except (PasswordRequiredError, InvalidPasswordError):
                    # Let the document workflow request/retry a password instead of
                    # silently dropping a protected statement from the bundle.
                    raise
                except Exception as exc:
                    warnings.append(f"Could not parse {member.filename}: {exc}")
                    continue
                if result.bank_name:
                    bank_names.add(result.bank_name)
                if result.account_number:
                    account_numbers.add(result.account_number)
                for transaction in result.transactions:
                    if transaction.bank_name:
                        bank_names.add(transaction.bank_name)
                    if transaction.account_number:
                        account_numbers.add(transaction.account_number)
                    transaction.raw_data = {
                        **(transaction.raw_data or {}),
                        "archive_member": member.filename,
                        "archive_member_sha256": member_hash,
                    }
                    transactions.append(transaction)
                types.append(result.document_type)
                warnings.extend(f"{member.filename}: {warning}" for warning in result.warnings)
                for _, text, method, confidence in result.page_texts:
                    page_texts.append((len(page_texts) + 1, text, method, confidence))
        bank_name = next(iter(bank_names)) if len(bank_names) == 1 else None
        account_number = next(iter(account_numbers)) if len(account_numbers) == 1 else None
        if len(bank_names) > 1:
            warnings.append("ZIP contains statements from multiple banks; transactions remain grouped by their individual bank.")
        if len(account_numbers) > 1:
            warnings.append("ZIP contains multiple accounts; transactions remain grouped by their individual account.")
        return ParseResult(
            transactions=transactions,
            document_type="ZIP Statement Bundle",
            parser_used="zipfile + parser registry",
            page_texts=page_texts,
            warnings=warnings,
            bank_name=bank_name,
            account_number=account_number,
            page_count=len(page_texts),
            extra_records={
                "member_types": [{"type": value} for value in types],
                "member_hashes": [{"sha256": value} for value in sorted(member_hashes)],
            },
        )
