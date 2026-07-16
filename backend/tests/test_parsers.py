from pathlib import Path
import uuid
import zipfile

from backend.app.core.config import get_settings
from backend.app.parsers.csv_excel import CsvExcelParser
from backend.app.parsers.registry import registry


def test_sample_bank_csv_parses_transactions():
    path = Path(__file__).resolve().parents[2] / "sample_data" / "sample_bank_statement.csv"
    result = CsvExcelParser().parse(path)
    assert result.document_type == "Bank Statement"
    assert len(result.transactions) >= 8
    assert any(transaction.credit > 0 for transaction in result.transactions)
    assert any(transaction.debit > 0 for transaction in result.transactions)


def test_zip_bundle_preserves_bank_account_and_skips_repeated_members():
    root = get_settings().temp_dir / f"zip-parser-test-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    archive_path = root / "statement-parts.zip"
    csv_content = (
        "Date,Description,Debit,Credit,Balance,Account Number\n"
        "01-04-2025,Client receipt,0,1000,1000,1234567890\n"
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("IDFCFIRSTBankstatement_part1.csv", csv_content)
        archive.writestr("renamed-copy.csv", csv_content)

    result = registry.get_parser(archive_path).parse(archive_path)

    assert result.bank_name == "IDFC First Bank"
    assert result.account_number == "1234567890"
    assert len(result.transactions) == 1
    assert result.transactions[0].raw_data["archive_member_sha256"]
    assert any("duplicate ZIP member" in warning for warning in result.warnings)
    archive_path.unlink()
    root.rmdir()
