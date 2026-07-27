"""Offline transaction classification using explainable weighted rules and fuzzy signals."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

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
    Rule("FD Interest", ("fd interest", "fixed deposit interest", "term deposit interest", "td interest", "int on fd", "fd int cr", "interest cr fd", "stdr int", "tdr int", "term deposit int", "fd int"), "Interest Income", True, confidence=98, credit_only=True),
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
    Rule("Self Transfer", ("self transfer", "own account", "internal transfer", "trf to self", "trf from self", "transfer to own", "to self", "by self", "self cr", "self dr", "self deposit"), None, ignore_credit=True, review_credit=False, confidence=96),
    Rule("Transfer", ("fund transfer", "account transfer", "bank transfer"), None, review_credit=True, confidence=76),
    Rule("Mutual Fund Purchase", ("mutual fund purchase", "mf purchase", "sip", "amc sip", "bse star mf"), None, debit_only=True, confidence=95),
    Rule("Stock Purchase", ("stock purchase", "share purchase", "equity buy", "securities buy"), None, debit_only=True, confidence=94),
    Rule("Stock Sale", ("stock sale", "share sale", "equity sell", "securities sale", "broker payout"), "Capital Gains", review_credit=True, confidence=91, credit_only=True),
    Rule("FD Booking", ("fd booking", "fixed deposit booking", "term deposit booking", "stdr creation", "tdr creation", "fd creation", "auto sweep dr", "sweep out", "mod dr", "trf to fd", "transfer to fd"), None, ignore_credit=True, review_credit=False, debit_only=True, confidence=96),
    Rule("Investment", ("investment", "ppf", "nps contribution", "elss", "lic premium"), None, debit_only=True, confidence=90),
    Rule("FD Maturity", ("fd maturity", "fixed deposit maturity", "term deposit maturity", "fd closure", "fixed deposit closure", "term deposit closure", "stdr closure", "tdr closure", "fd redemption", "fd principal", "fd credit", "fd cr", "sweep in", "auto sweep cr", "mod cr", "fd payout", "fd return", "principal return"), None, ignore_credit=True, review_credit=False, confidence=96, credit_only=True),
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

KNOWN_BANKS = {
    "SBIN": "State Bank of India",
    "ICIC": "ICICI Bank",
    "HDFC": "HDFC Bank",
    "AXIS": "Axis Bank",
    "KKBK": "Kotak Bank",
    "UTIB": "Axis Bank",
    "UBIN": "Union Bank",
    "BARB": "Bank of Baroda",
    "PUNB": "Punjab National Bank",
    "CBIN": "Central Bank of India",
    "IDFB": "IDFC First Bank",
    "YESB": "Yes Bank",
    "DFB": "DFB Bank",
    "DCBL": "DCB Bank",
    "EQUA": "Equitas Bank",
    "FDRL": "Federal Bank",
    "CNRB": "Canara Bank",
    "IDIB": "Indian Bank",
    "BKID": "Bank of India",
    "AUBL": "AU Small Finance Bank",
}

SKIP_TOKENS = {
    "upi", "neft", "rtgs", "imps", "impstxn", "reqpay", "mandaterequest",
    "p2p", "p2m", "p2a", "cr", "dr", "txn", "transaction", "ref", "reference",
    "payment", "transfer", "na", "val", "dt", "head", "office", "on", "pd", "sb", "int",
    "ft", "ifo", "ifi", "upiout", "upiin", "opm", "remarks", "to"
}

COUNTERPARTY_SEPARATORS = re.compile(r"[/|:@#-]+")


def clean_name(s: str) -> str:
    s = re.sub(r"^(?:MR|MRS|MS|DR|PROF|M/S)\.?\s+", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(?:13|0007|3|oka)\b", "", s, flags=re.IGNORECASE).strip()
    return s.title()


def is_ifsc(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$", token, re.IGNORECASE))


class ClassificationEngine:
    """Explainable local classifier; no network or cloud model is used."""

    def classify(
        self,
        description: str,
        *,
        debit: Decimal,
        credit: Decimal,
        document_type: str = "Unknown",
        user=None,
    ) -> ClassificationResult:
        normalized = self.normalize(description)
        direction = "credit" if credit > 0 else "debit"
        candidates: list[tuple[float, Rule, str]] = []
        
        # Build dynamic self keywords from user profile
        dynamic_self_keywords = []
        if user:
            if user.name:
                dynamic_self_keywords.append(user.name.lower())
                parts = user.name.lower().split()
                if len(parts) >= 2:
                    dynamic_self_keywords.append(parts[0])  # First name (e.g. dhiraj)
            if user.upi_ids:
                dynamic_self_keywords.extend([u.strip().lower() for u in user.upi_ids.split(",") if u.strip()])
                
        for rule in RULES:
            if rule.debit_only and direction != "debit":
                continue
            if rule.credit_only and direction != "credit":
                continue
            
            # Combine static rule keywords with dynamic profile keywords if applicable
            effective_keywords = list(rule.keywords)
            if rule.category == "Self Transfer":
                effective_keywords.extend(dynamic_self_keywords)
                
            exact_hits = [keyword for keyword in effective_keywords if keyword in normalized]
            fuzzy = max((partial_ratio(keyword, normalized) for keyword in effective_keywords), default=0)
            if exact_hits:
                score = min(99.0, rule.confidence + min(5, len(exact_hits) - 1))
                candidates.append((score, rule, f"matched {', '.join(exact_hits[:3])}"))
            elif fuzzy >= 88:
                score = min(rule.confidence - 8, float(fuzzy))
                candidates.append((score, rule, f"fuzzy narration match {fuzzy:.0f}%"))

        counterparty = self.extract_counterparty(description, direction=direction)

        if candidates:
            confidence, rule, reason = max(candidates, key=lambda item: item[0])
            needs_review = bool(credit > 0 and (rule.review_credit or confidence < 85))
            taxable = bool(credit > 0 and rule.taxable_credit and not rule.ignore_credit)
            exempt = bool(credit > 0 and rule.exempt_credit)
            ignored = bool(credit > 0 and rule.ignore_credit and not needs_review)
            if document_type in {"AIS", "Form 26AS", "Form 16", "Form 16A"} and credit > 0:
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
                counterparty=counterparty,
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
                counterparty=counterparty,
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
            counterparty=counterparty,
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
    def extract_counterparty(description: str, direction: str = "credit") -> str:
        s = description.strip()
        if not s:
            return "Direct Bank Credit" if direction == "credit" else "Direct Bank Debit"

        # Savings Interest
        if re.search(r"sb\s+int|interest\s+cr|monthly\s+savings\s+interest", s, re.IGNORECASE):
            return "Savings Interest"

        # DCB Bank format: UPI:REC:.../NAME/BANK or UPI:PAY:.../NAME/BANK
        dcb = re.search(r"UPI:(?:REC|PAY):\d+/([^/]+)/([^/]+)", s, re.IGNORECASE)
        if dcb:
            person = clean_name(dcb.group(1))
            bank_raw = dcb.group(2).strip()
            bank_code = bank_raw.upper()[:4]
            bank_name = KNOWN_BANKS.get(bank_code, bank_raw.title())
            return f"{person} ({bank_name})"

        # Federal Bank / IMPS format: FT IMPS/IFI/.../NAME/IMPS or FT IMPS/IFO/.../IFSC/
        fed_imps = re.search(r"FT\s+IMPS/IF[IO]/\d+/([^/]+)", s, re.IGNORECASE)
        if fed_imps:
            val = fed_imps.group(1).strip()
            if is_ifsc(val):
                bank_name = KNOWN_BANKS.get(val[:4].upper(), f"{val[:4].upper()} Bank")
                return f"IMPS Transfer ({bank_name})"
            elif val.lower() != "remarks":
                return clean_name(val)

        # Federal Bank UPI format: UPI OUT/.../vpa@bank/... or UPI IN/.../vpa@bank/...
        fed_upi = re.search(r"UPI\s*(?:IN|OUT)/\d+/([^/@]+)@", s, re.IGNORECASE)
        if fed_upi:
            vpa_user = fed_upi.group(1).strip()
            if not vpa_user.isdigit() and len(vpa_user) >= 2:
                return clean_name(vpa_user)

        # IDFC IMPS OPM format: IMPS-OPM/.../NAME/IFSC/ACCT
        idfc_imps = re.search(r"IMPS-OPM/\d+/([^/]+)/([A-Z0-9]{11})", s, re.IGNORECASE)
        if idfc_imps:
            person = clean_name(idfc_imps.group(1))
            ifsc = idfc_imps.group(2).upper()
            bank_name = KNOWN_BANKS.get(ifsc[:4], f"{ifsc[:4]} Bank")
            return f"{person} ({bank_name})"

        # P2P / P2M pattern (e.g. 102431908637 P2P- SANCHA MAN RAI-UPI-HDFC0001455- HEAD OFFICE)
        p2p = re.search(
            r"P2[PM][-\s]+([A-Za-z0-9\s.'&]+?)(?:-[A-Za-z]{4}0[A-Za-z0-9]{6}|-UPI|-NA|-REFUND|-PAYMENT|-SENT|-HEAD|-SBIN|-HDFC|-ICIC|-AXIS|-IDIB|-FDRL|-UTIB|-KKBK|-BKID|-CNRB|$)",
            s,
            re.IGNORECASE,
        )
        if p2p:
            raw = p2p.group(1).strip()
            raw = re.sub(
                r"\b(?:UPI|OKAXIS|PTSBI|OKICICI|OKHDFC|YBL|SENT|PAYMENT|FROM|USING|HEAD|OFFICE|NA|REFUND)\b.*",
                "",
                raw,
                flags=re.IGNORECASE,
            ).strip()
            if len(raw) >= 2 and not raw.isdigit() and not is_ifsc(raw):
                return clean_name(raw)

        # Standard UPI pattern: UPI-NAME-VPA...
        upi_match = re.search(r"UPI[-/]([A-Za-z0-9\s.'&]+?)[-/]([A-Za-z0-9._@]+)", s, re.IGNORECASE)
        if upi_match:
            raw_name = upi_match.group(1).strip()
            if len(raw_name) >= 2 and not raw_name.isdigit() and not is_ifsc(raw_name):
                return clean_name(raw_name)

        # General cleaning
        parts = [p.strip() for p in COUNTERPARTY_SEPARATORS.split(s) if p.strip()]
        cleaned = []
        for p in parts:
            pl = p.lower()
            if pl in SKIP_TOKENS or p.isdigit() or is_ifsc(p) or re.match(r"^\d+[a-z]+$", pl) or re.match(r"^[a-z]+\d+$", pl) or re.match(r"^[x*]+$", pl):
                continue
            cleaned.append(p)

        if cleaned:
            res = " ".join(cleaned)
            res = re.sub(r"[X*]{3,}\d*", "", res, flags=re.IGNORECASE).strip()
            if res and not res.isdigit() and not is_ifsc(res):
                return clean_name(res)

        return "Direct Bank Credit" if direction == "credit" else "Direct Bank Debit"


classifier = ClassificationEngine()
