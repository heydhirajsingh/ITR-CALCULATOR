"""Old/new regime comparison, rebate, surcharge, cess and deduction handling."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from backend.app.tax.rules import DEDUCTION_LIMITS, NEW_ALLOWED_DEDUCTIONS, RULES, TaxRuleSet

D = Decimal
RUPEE = D("1")


@dataclass(slots=True)
class TaxResult:
    regime: str
    financial_year: str
    gross_taxable_income: Decimal
    standard_deduction: Decimal
    chapter_vi_a_deductions: Decimal
    net_taxable_income: Decimal
    slab_tax: Decimal
    special_rate_tax: Decimal
    rebate: Decimal
    surcharge: Decimal
    cess: Decimal
    total_tax: Decimal
    tds_credit: Decimal
    advance_tax: Decimal
    net_payable: Decimal
    refund_estimate: Decimal
    warnings: list[str]

    def to_dict(self) -> dict:
        payload = asdict(self)
        return {key: float(value) if isinstance(value, Decimal) else value for key, value in payload.items()}


class TaxCalculator:
    def calculate(
        self,
        *,
        financial_year: str,
        gross_taxable_income: Decimal,
        salary_income: Decimal = D("0"),
        deductions: dict[str, Decimal] | None = None,
        regime: str,
        age: int = 30,
        resident: bool = True,
        tds_credit: Decimal = D("0"),
        advance_tax: Decimal = D("0"),
        special_rate_tax: Decimal = D("0"),
        special_rate_income: Decimal = D("0"),
    ) -> TaxResult:
        rules = RULES.get(financial_year)
        if not rules:
            raise ValueError(f"No built-in tax rules are configured for {financial_year}")
        deductions = deductions or {}
        warnings: list[str] = []
        regime = regime.lower()
        standard_cap = rules.new_standard_deduction if regime == "new" else rules.old_standard_deduction
        standard_deduction = min(max(salary_income, D("0")), standard_cap)
        chapter_deduction = self._eligible_deductions(deductions, regime, warnings)
        taxable_before_special = max(D("0"), gross_taxable_income - standard_deduction - chapter_deduction)
        ordinary_income = max(D("0"), taxable_before_special - special_rate_income)
        slabs = rules.new_slabs if regime == "new" else self._old_slabs(rules, age)
        slab_tax = self._slab_tax(ordinary_income, slabs)
        pre_rebate_tax = slab_tax + special_rate_tax
        rebate = self._rebate(
            rules=rules,
            regime=regime,
            taxable_income=taxable_before_special,
            tax=pre_rebate_tax,
            resident=resident,
        )
        tax_after_rebate = max(D("0"), pre_rebate_tax - rebate)
        surcharge = self._surcharge_with_marginal_relief(
            taxable_income=taxable_before_special,
            base_tax=tax_after_rebate,
            regime=regime,
            rules=rules,
        )
        cess = (tax_after_rebate + surcharge) * rules.cess_rate
        total_tax = self._round_rupees(tax_after_rebate + surcharge + cess)
        paid = tds_credit + advance_tax
        net_payable = max(D("0"), total_tax - paid)
        refund = max(D("0"), paid - total_tax)
        return TaxResult(
            regime=regime,
            financial_year=financial_year,
            gross_taxable_income=self._round_rupees(gross_taxable_income),
            standard_deduction=self._round_rupees(standard_deduction),
            chapter_vi_a_deductions=self._round_rupees(chapter_deduction),
            net_taxable_income=self._round_rupees(taxable_before_special),
            slab_tax=self._round_rupees(slab_tax),
            special_rate_tax=self._round_rupees(special_rate_tax),
            rebate=self._round_rupees(rebate),
            surcharge=self._round_rupees(surcharge),
            cess=self._round_rupees(cess),
            total_tax=total_tax,
            tds_credit=self._round_rupees(tds_credit),
            advance_tax=self._round_rupees(advance_tax),
            net_payable=self._round_rupees(net_payable),
            refund_estimate=self._round_rupees(refund),
            warnings=warnings,
        )

    def compare(self, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        old = self.calculate(regime="old", **kwargs)
        new = self.calculate(regime="new", **kwargs)
        recommended = "old" if old.total_tax < new.total_tax else "new"
        savings = abs(old.total_tax - new.total_tax)
        return {
            "old": old.to_dict(),
            "new": new.to_dict(),
            "recommended": recommended,
            "estimated_savings": float(savings),
        }

    @staticmethod
    def _slab_tax(income: Decimal, slabs: tuple[tuple[Decimal | None, Decimal], ...]) -> Decimal:
        tax = D("0")
        lower = D("0")
        for upper, rate in slabs:
            if income <= lower:
                break
            taxable_band = income - lower if upper is None else min(income, upper) - lower
            tax += max(D("0"), taxable_band) * rate
            if upper is None or income <= upper:
                break
            lower = upper
        return tax

    @staticmethod
    def _old_slabs(rules: TaxRuleSet, age: int) -> tuple[tuple[Decimal | None, Decimal], ...]:
        if age >= 80:
            return rules.old_slabs_super_senior
        if age >= 60:
            return rules.old_slabs_senior
        return rules.old_slabs_adult

    @staticmethod
    def _eligible_deductions(deductions: dict[str, Decimal], regime: str, warnings: list[str]) -> Decimal:
        allowed = deductions if regime == "old" else {k: v for k, v in deductions.items() if k in NEW_ALLOWED_DEDUCTIONS}
        if regime == "new":
            rejected = sorted(set(deductions) - NEW_ALLOWED_DEDUCTIONS)
            if rejected:
                warnings.append("New regime excludes these supplied deductions: " + ", ".join(rejected))
        total = D("0")
        combined_80c = D("0")
        for section, amount in allowed.items():
            value = max(D("0"), Decimal(amount))
            if section in {"80C", "80CCC", "80CCD(1)"}:
                combined_80c += value
                continue
            limit = DEDUCTION_LIMITS.get(section)
            total += min(value, limit) if limit is not None else value
        total += min(combined_80c, D("150000"))
        return total

    @staticmethod
    def _rebate(
        *, rules: TaxRuleSet, regime: str, taxable_income: Decimal, tax: Decimal, resident: bool
    ) -> Decimal:
        if not resident:
            return D("0")
        threshold = rules.new_rebate_threshold if regime == "new" else rules.old_rebate_threshold
        maximum = rules.new_rebate_max if regime == "new" else rules.old_rebate_max
        if taxable_income <= threshold:
            return min(tax, maximum)
        # Marginal relief for the new-regime rebate cliff.
        if regime == "new":
            excess_income = taxable_income - threshold
            if tax > excess_income:
                return min(tax - excess_income, maximum)
        return D("0")

    def _surcharge_with_marginal_relief(
        self, *, taxable_income: Decimal, base_tax: Decimal, regime: str, rules: TaxRuleSet
    ) -> Decimal:
        thresholds = (
            (D("5000000"), D("0.10")),
            (D("10000000"), D("0.15")),
            (D("20000000"), D("0.25")),
            (D("50000000"), D("0.37")),
        )
        rate = D("0")
        threshold = D("0")
        for candidate_threshold, candidate_rate in thresholds:
            if taxable_income > candidate_threshold:
                threshold, rate = candidate_threshold, candidate_rate
        if regime == "new":
            rate = min(rate, rules.new_surcharge_cap)
        if rate == 0:
            return D("0")
        raw = base_tax * rate
        # Approximate statutory marginal relief at the surcharge threshold.
        tax_at_threshold = self._slab_tax(
            threshold,
            rules.new_slabs if regime == "new" else rules.old_slabs_adult,
        )
        prior_rate = D("0")
        for candidate_threshold, candidate_rate in thresholds:
            if threshold > candidate_threshold:
                prior_rate = candidate_rate
        if regime == "new":
            prior_rate = min(prior_rate, rules.new_surcharge_cap)
        allowed_total = tax_at_threshold * (D("1") + prior_rate) + (taxable_income - threshold)
        actual_total = base_tax + raw
        if actual_total > allowed_total:
            return max(D("0"), allowed_total - base_tax)
        return raw

    @staticmethod
    def age_on(date_of_birth: date | None, on_date: date) -> int:
        if not date_of_birth:
            return 30
        return on_date.year - date_of_birth.year - ((on_date.month, on_date.day) < (date_of_birth.month, date_of_birth.day))

    @staticmethod
    def _round_rupees(value: Decimal) -> Decimal:
        return value.quantize(RUPEE, rounding=ROUND_HALF_UP)


tax_calculator = TaxCalculator()
