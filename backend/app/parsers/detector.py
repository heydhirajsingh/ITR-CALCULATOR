"""Offline document-type and institution detection using weighted keyword rules."""
from __future__ import annotations

import re
from pathlib import Path

DOCUMENT_RULES: list[tuple[str, tuple[str, ...], int]] = [
    ("AIS", ("annual information statement", "ais", "information category"), 100),
    ("TIS", ("taxpayer information summary", "tis"), 100),
    ("Form 26AS", ("form 26as", "tax credit statement", "tds-cpc"), 100),
    ("Form 16A", ("form no. 16a", "certificate under section 203", "tan of deductor"), 95),
    ("Form 16", ("form no. 16", "part b annexure", "salary as per provisions"), 95),
    ("Broker Ledger", ("broker ledger", "contract note", "trade date", "settlement no", "securities transaction tax"), 90),
    ("Demat Statement", ("demat", "depository participant", "isin", "nsdl", "cdsl"), 85),
    ("Mutual Fund Statement", ("folio", "nav", "scheme name", "cas consolidated account statement"), 82),
    ("Credit Card Statement", ("credit card", "minimum amount due", "payment due date", "credit limit"), 80),
    ("GST Report", ("gstr-", "gstin", "taxable outward supplies", "input tax credit"), 80),
    ("Salary Slip", ("salary slip", "pay slip", "basic salary", "gross earnings", "net pay"), 75),
    ("Interest Certificate", ("interest certificate", "interest accrued", "fixed deposit interest"), 75),
    ("Dividend Statement", ("dividend", "dividend income", "corporate action"), 72),
    ("Rental Statement", ("rental income", "tenant", "monthly rent", "rent received"), 70),
    ("UPI Statement", ("upi transaction", "google pay", "phonepe", "paytm", "amazon pay"), 68),
    ("Foreign Remittance Statement", ("wise", "paypal", "foreign remittance", "swift", "inward remittance"), 68),
    ("Bank Statement", ("bank statement", "account statement", "withdrawal", "deposit", "balance", "transaction date"), 60),
    ("Business Ledger", ("ledger", "cash book", "voucher", "debit", "credit", "opening balance"), 55),
]

BANKS = (
    "HDFC Bank", "State Bank of India", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank",
    "Punjab National Bank", "Bank of Baroda", "Canara Bank", "Union Bank of India", "IDFC First Bank",
    "IndusInd Bank", "Yes Bank", "Federal Bank", "RBL Bank", "AU Small Finance Bank",
    "DCB Bank", "Equitas Bank", "Central Bank of India", "Indian Bank", "Bank of India",
    "Bandhan Bank", "UCO Bank", "South Indian Bank", "Karur Vysya Bank", "City Union Bank",
    "Karnataka Bank", "Standard Chartered", "HSBC", "Citi Bank",
)


def detect_document_type(filename: str, text: str = "") -> str:
    filename_text = Path(filename).stem.lower()
    header = text[:6000].lower()
    haystack = f"{filename_text} {header}"
    if any(token in filename_text for token in ("bankstatement", "bank_statement", "accountstatement", "account_statement", "acct statement")):
        return "Bank Statement"
    if any(token in header[:2000] for token in ("your account statement", "bank account statement", "statement period", "account summary")):
        return "Bank Statement"
    best_type = "Unknown"
    best_score = 0
    for document_type, keywords, weight in DOCUMENT_RULES:
        matches = sum(1 for keyword in keywords if _keyword_present(keyword, haystack))
        score = matches * weight
        if score > best_score:
            best_type, best_score = document_type, score
    return best_type if best_score else _filename_fallback(filename)


def _filename_fallback(filename: str) -> str:
    name = Path(filename).stem.lower()
    if any(token in name for token in ("statement", "passbook", "account", "acct")):
        return "Bank Statement"
    if any(token in name for token in ("ledger", "contract", "broker")):
        return "Broker Ledger"
    return "Unknown"


def detect_bank(filename: str, text: str = "") -> str | None:
    filename_text = filename.lower()
    compact_filename = re.sub(r"[^a-z0-9]", "", filename_text)
    header = text[:800].lower()
    aliases = {
        "HDFC Bank": ("hdfc", "chq./ref.no.", r"HDFC0[A-Z0-9]{6}"),
        "State Bank of India": ("state bank of india", "sbi", r"SBIN0[A-Z0-9]{6}"),
        "ICICI Bank": ("icici", r"ICIC0[A-Z0-9]{6}"),
        "Axis Bank": ("axis bank", "axis", r"UTIB0[A-Z0-9]{6}"),
        "Kotak Mahindra Bank": ("kotak", r"KKBK0[A-Z0-9]{6}"),
        "IDFC First Bank": ("idfc first", "idfc", r"IDFB0[A-Z0-9]{6}"),
        "Punjab National Bank": ("punjab national bank", "pnb", r"PUNB0[A-Z0-9]{6}"),
        "Bank of Baroda": ("bank of baroda", "bob", r"BARB0[A-Z0-9]{6}"),
        "DCB Bank": ("dcb bank", "dcb", r"DCBL0[A-Z0-9]{6}"),
        "Federal Bank": ("federal bank", "federal", "fedmobile", r"FDRL0[A-Z0-9]{6}"),
        "Equitas Bank": ("equitas bank", "equitas", "equitas small finance bank", r"ESFB0[A-Z0-9]{6}", "e q u i t a s"),
        "AU Small Finance Bank": ("au bank", "au small finance", "au small finance bank", "aubank", r"AUBL0[A-Z0-9]{6}"),
        "Canara Bank": ("canara bank", "canara", r"CNRB0[A-Z0-9]{6}"),
        "Union Bank of India": ("union bank of india", "union bank", "ubi", r"UBIN0[A-Z0-9]{6}"),
        "IndusInd Bank": ("indusind bank", "indusind", r"INDB0[A-Z0-9]{6}"),
        "Yes Bank": ("yes bank", "yesbank", r"YESB0[A-Z0-9]{6}"),
        "RBL Bank": ("rbl bank", "rbl", "ratnakar", r"RATN0[A-Z0-9]{6}"),
        "Central Bank of India": ("central bank", "cbi", r"CBIN0[A-Z0-9]{6}"),
        "Indian Bank": ("indian bank", r"IDIB0[A-Z0-9]{6}"),
        "Bank of India": ("bank of india", "boi", r"BKID0[A-Z0-9]{6}"),
        "Bandhan Bank": ("bandhan bank", "bandhan", r"BDBL0[A-Z0-9]{6}"),
        "UCO Bank": ("uco bank", "uco", r"UCBA0[A-Z0-9]{6}"),
        "South Indian Bank": ("south indian bank", "sib", r"SIBL0[A-Z0-9]{6}"),
        "Karur Vysya Bank": ("karur vysya", "kvb", r"KVBL0[A-Z0-9]{6}"),
        "City Union Bank": ("city union bank", "cub", r"CIUB0[A-Z0-9]{6}"),
        "Karnataka Bank": ("karnataka bank", r"KARB0[A-Z0-9]{6}"),
        "Standard Chartered": ("standard chartered", "scb", r"SCBL0[A-Z0-9]{6}"),
        "HSBC": ("hsbc", r"HSBC0[A-Z0-9]{6}"),
        "Citi Bank": ("citibank", "citi", r"CITI0[A-Z0-9]{6}"),
    }
    scored: list[tuple[int, str]] = []
    for bank, names in aliases.items():
        score = 0
        for alias in names:
            if alias.startswith(r"^[A-Z]{4}0") or "0[" in alias:  # Quick heuristic for IFSC regex
                pattern = alias
                compact_alias = ""
            else:
                pattern = rf"(?<!@)\b{re.escape(alias)}\b"
                compact_alias = re.sub(r"[^a-z0-9]", "", alias)

            if compact_alias and compact_alias in compact_filename:
                score += 100
            if re.search(pattern, header, re.IGNORECASE):
                score += 20
        if score:
            scored.append((score, bank))
    return max(scored)[1] if scored else None


def _keyword_present(keyword: str, value: str) -> bool:
    if len(keyword) <= 4 and keyword.isalnum():
        return bool(re.search(rf"\b{re.escape(keyword)}\b", value))
    return keyword in value
