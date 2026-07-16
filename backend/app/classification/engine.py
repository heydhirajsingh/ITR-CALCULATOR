"""Offline transaction classification using explainable weighted rules and fuzzy signals."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from rapidfuzz.fuzz import partial_ratio


@dataclass(slots=True)
class ClassificationResult:
    category: str
    income_type: str | None
    taxable: bool
    exempt: bool
    ignored: bool
    needs_review: bool
    confidence: float
    reason: str
    mode: str | None = None
    counterparty: str | None = None


@dataclass(frozen=True, slots=True)
class Rule:
    category: str
    keywords: tuple[str, ...]
    income_type: str | None = None
    taxable_credit: bool = False
    exempt_credit: bool = False
    ignore_credit: bool = False
    review_credit: bool = False
    confidence: float = 90.0
    debit_only: bool = False
    credit_only: bool = False


RULES: tuple[Rule, ...] = (
    Rule("Salary", ("salary", "payroll", "sal cr", "monthly pay", "emolument"), "Salary Income", True, confidence=98, credit_only=True),
    Rule("Interest", ("interest credit", "int cr", "interest paid", "sb interest", "savings interest"), "Interest Income", True, confidence=96, credit_only=True),
    Rule("FD Interest", ("fd interest", "fixed deposit interest", "term deposit interest", "td interest"), "Interest Income", True, confidence=98, credit_only=True),
    Rule("Dividend", ("dividend", "div payout", "corporate action dividend"), "Dividend Income", True, confidence=98, credit_only=True),
    Rule("Rent", ("rent received", "rental income", "tenant rent", "monthly rent"), "Rental Income", True, confidence=94, credit_only=True),
    Rule("Professional Income", ("professional fee", "consulting fee", "consultancy", "freelance", "retainer"), "Professional Income", True, confidence=92, credit_only=True),
    Rule("Business Receipt", ("razorpay", "stripe payout", "merchant settlement", "business receipt", "sales receipt", "shopify", "cashfree"), "Business Income", True, confidence=91, credit_only=True),
    Rule("Foreign Income", ("paypal", "wise", "swift credit", "inward remittance", "foreign remittance", "export proceeds", "adsense"), "Foreign Income", True, review_credit=True, confidence=84, credit_only=True),
    Rule("Commission", ("commission", "brokerage income", "affiliate payout"), "Other Sources", True, confidence=90, credit_only=True),
    Rule("Royalty", ("royalty",), "Other Sources", True, confidence=92, credit_only=True),
    Rule("Agricultural Income", ("agri income", "agricultural income", "crop sale", "mandi payment"), "Agricultural Income", exempt_credit=True, review_credit=True, confidence=82, credit_only=True),
    Rule("Gift", ("gift", "birthday gift", "wedding gift"), "Gift", review_credit=True, confidence=70, credit_only=True),
    Rule("Refund", ("refund", "reversal", "rev txn", "chargeback", "cashback", "returned payment"), None, ignore_credit=True, confidence=92, credit_only=True),
    Rule("Tax Refund", ("income tax refund", "it refund", "tax refund"), "Other Sources", review_credit=True, confidence=94, credit_only=True),
    Rule("Credit Card Refund", ("card refund", "credit card refund", "merchant refund"), None, ignore_credit=True, confidence=95, credit_only=True),
    Rule("Loan Received", ("loan received", "loan disbursal", "loan disbursement", "personal loan credit", "home loan disb"), None, ignore_credit=True, confidence=96, credit_only=True),
    Rule("Loan Repaid", ("loan emi", "emi", "loan repayment", "instalment"), None, debit_only=True, confidence=91),
    Rule("Cash Deposit", ("cash deposit", "cash dep", "cash paid in"), None, review_credit=True, confidence=80, credit_only=True),
    Rule("Cash Withdrawal", ("cash withdrawal", "atm cash", "cash wd", "self cheque"), None, debit_only=True, confidence=96),
    Rule("Transfer", ("self transfer", "own account", "internal transfer", "fund transfer", "account transfer"), None, review_credit=True, confidence=76),
    Rule("Mutual Fund Purchase", ("mutual fund purchase", "mf purchase", "sip", "amc sip", "bse star mf"), None, debit_only=True, confidence=95),
    Rule("Stock Purchase", ("stock purchase", "share purchase", "equity buy", "securities buy"), None, debit_only=True, confidence=94),
    Rule("Stock Sale", ("stock sale", "share sale", "equity sell", "securities sale", "broker payout"), "Capital Gains", review_credit=True, confidence=91, credit_only=True),
    Rule("Investment", ("investment", "ppf", "nps contribution", "elss", "lic premium", "fixed deposit booking"), None, debit_only=True, confidence=90),
    Rule("FD Maturity", ("fd maturity", "fixed deposit maturity", "term deposit maturity"), None, ignore_credit=True, review_credit=True, confidence=88, credit_only=True),
    Rule("Reimbursement", ("reimbursement", "expense reimb", "travel reimb", "medical reimb"), None, ignore_credit=True, confidence=91, credit_only=True),
    Rule("TDS", ("tds", "tax deducted at source"), None, confidence=94),
    Rule("TCS", ("tcs", "tax collected at source"), None, confidence=94),
    Rule("GST", ("gst", "cgst", "sgst", "igst", "gstr"), None, confidence=93),
    Rule("Tax Payment", ("income tax", "advance tax", "self assessment tax", "challan 280"), None, debit_only=True, confidence=96),
    Rule("Insurance", ("insurance", "premium", "policy premium"), None, debit_only=True, confidence=90),
    Rule("Credit Card Payment", ("credit card payment", "cc payment", "card bill payment"), None, debit_only=True, confidence=96),
    Rule("Rent", ("rent", "landlord"), None, debit_only=True, confidence=83),
    Rule("Medical", ("hospital", "pharmacy", "medical", "doctor", "clinic"), None, debit_only=True, confidence=84),
    Rule("Education", ("school fee", "college fee", "tuition", "education"), None, debit_only=True, confidence=85),
    Rule("Travel", ("airlines", "flight", "railway", "irctc", "hotel", "travel"), None, debit_only=True, confidence=80),
    Rule("Fuel", ("petrol", "diesel", "fuel", "indian oil", "bharat petroleum", "hpcl"), None, debit_only=True, confidence=86),
    Rule("Utilities", ("electricity", "water bill", "broadband", "mobile bill", "utility"), None, debit_only=True, confidence=84),
    Rule("Donation", ("donation", "charity", "relief fund"), None, debit_only=True, confidence=85),
)

MODE_PATTERNS = {
    "UPI": ("upi/", "upi-", " upi ", "phonepe", "google pay", "gpay", "paytm"),
    "NEFT": ("neft",),
    "RTGS": ("rtgs",),
    "IMPS": ("imps",),
    "Cheque": ("cheque", "chq"),
    "Cash": ("cash", "atm"),
    "Card": ("pos", "card", "ecom"),
}

COUNTERPARTY_SEPARATORS = re.compile(r"[/|:@#-]+")


class ClassificationEngine:
    """Explainable local classifier; no network or cloud model is used."""

    def classify(
        self,
        description: str,
        *,
        debit: Decimal,
        credit: Decimal,
        document_type: str = "Unknown",
    ) -> ClassificationResult:
        normalized = self.normalize(description)
        direction = "credit" if credit > 0 else "debit"
        candidates: list[tuple[float, Rule, str]] = []
        for rule in RULES:
            if rule.debit_only and direction != "debit":
                continue
            if rule.credit_only and direction != "credit":
                continue
            exact_hits = [keyword for keyword in rule.keywords if keyword in normalized]
            fuzzy = max((partial_ratio(keyword, normalized) for keyword in rule.keywords), default=0)
            if exact_hits:
                score = min(99.0, rule.confidence + min(5, len(exact_hits) - 1))
                candidates.append((score, rule, f"matched {', '.join(exact_hits[:3])}"))
            elif fuzzy >= 88:
                score = min(rule.confidence - 8, float(fuzzy))
                candidates.append((score, rule, f"fuzzy narration match {fuzzy:.0f}%"))

        if candidates:
            confidence, rule, reason = max(candidates, key=lambda item: item[0])
            # Expense categories may be low-confidence without affecting tax. Keep the
            # review queue focused on credits and explicit tax-sensitive exceptions.
            needs_review = bool(credit > 0 and (rule.review_credit or confidence < 85))
            taxable = bool(credit > 0 and rule.taxable_credit and not rule.ignore_credit)
            exempt = bool(credit > 0 and rule.exempt_credit)
            ignored = bool(credit > 0 and rule.ignore_credit and not needs_review)
            if document_type in {"AIS", "Form 26AS", "Form 16", "Form 16A"} and credit > 0:
                # These are evidence sources. Deduplication decides whether they count independently.
                confidence = min(99.0, confidence + 2)
            return ClassificationResult(
                category=rule.category,
                income_type=rule.income_type,
                taxable=taxable,
                exempt=exempt,
                ignored=ignored,
                needs_review=needs_review,
                confidence=confidence,
                reason=reason,
                mode=self.detect_mode(normalized),
                counterparty=self.extract_counterparty(description),
            )

        if credit > 0:
            return ClassificationResult(
                category="Other",
                income_type="Other Sources",
                taxable=False,
                exempt=False,
                ignored=False,
                needs_review=True,
                confidence=40.0,
                reason="unclassified credit; conservative review required",
                mode=self.detect_mode(normalized),
                counterparty=self.extract_counterparty(description),
            )
        return ClassificationResult(
            category="Other",
            income_type=None,
            taxable=False,
            exempt=False,
            ignored=False,
            needs_review=False,
            confidence=55.0,
            reason="unclassified debit",
            mode=self.detect_mode(normalized),
            counterparty=self.extract_counterparty(description),
        )

    @staticmethod
    def normalize(value: str) -> str:
        value = value.lower().replace("\n", " ")
        value = re.sub(r"\b\d{6,}\b", " ", value)
        value = re.sub(r"[^a-z0-9@._/ -]", " ", value)
        return " ".join(value.split())

    @staticmethod
    def detect_mode(normalized: str) -> str | None:
        padded = f" {normalized} "
        for mode, patterns in MODE_PATTERNS.items():
            if any(pattern in padded for pattern in patterns):
                return mode
        return None

    @staticmethod
    def extract_counterparty(description: str) -> str | None:
        tokens = [token.strip() for token in COUNTERPARTY_SEPARATORS.split(description) if token.strip()]
        skip = {"upi", "neft", "rtgs", "imps", "cr", "dr", "txn", "ref", "transfer", "payment"}
        candidates = [token for token in tokens if token.lower() not in skip and not token.isdigit()]
        for token in reversed(candidates):
            if 3 <= len(token) <= 80 and sum(char.isalpha() for char in token) >= 2:
                return token.title()
        return None


classifier = ClassificationEngine()
