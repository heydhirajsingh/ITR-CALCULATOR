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
)


def detect_document_type(filename: str, text: str = "") -> str:
    filename_text = Path(filename).stem.lower()
    header = text[:6000].lower()
    haystack = f"{filename_text} {header}"
    # Statement headers and filenames are issuer-authored evidence. Generic debit/credit
    # words in the body must not turn a bank statement into a business ledger.
    if any(token in filename_text for token in ("bankstatement", "bank_statement", "accountstatement", "account_statement")):
        return "Bank Statement"
    if any(token in header[:2000] for token in ("your account statement", "bank account statement", "statement period")):
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
    if any(token in name for token in ("statement", "passbook", "account")):
        return "Bank Statement"
    if any(token in name for token in ("ledger", "contract", "broker")):
        return "Broker Ledger"
    return "Unknown"


def detect_bank(filename: str, text: str = "") -> str | None:
    filename_text = filename.lower()
    compact_filename = re.sub(r"[^a-z0-9]", "", filename_text)
    # Limit content evidence to the issuer header. Bank names in transaction narrations
    # identify counterparties, not the institution that issued the statement.
    header = text[:600].lower()
    aliases = {
        "HDFC Bank": ("hdfc",),
        "State Bank of India": ("state bank of india", "sbi"),
        "ICICI Bank": ("icici",),
        "Axis Bank": ("axis bank", "axis"),
        "Kotak Mahindra Bank": ("kotak",),
        "IDFC First Bank": ("idfc first", "idfc"),
        "Punjab National Bank": ("punjab national bank", "pnb"),
        "Bank of Baroda": ("bank of baroda", "bob"),
    }
    scored: list[tuple[int, str]] = []
    for bank, names in aliases.items():
        score = 0
        for alias in names:
            pattern = rf"\b{re.escape(alias)}\b"
            compact_alias = re.sub(r"[^a-z0-9]", "", alias)
            if compact_alias in compact_filename:
                score += 100
            if re.search(pattern, header):
                score += 20
        if score:
            scored.append((score, bank))
    return max(scored)[1] if scored else None


def _keyword_present(keyword: str, value: str) -> bool:
    if len(keyword) <= 4 and keyword.isalnum():
        return bool(re.search(rf"\b{re.escape(keyword)}\b", value))
    return keyword in value
