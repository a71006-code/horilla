"""Per-check statutory contributions for U.S. federal and California payroll."""

from dataclasses import dataclass, fields
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


ZERO = Decimal("0")
CENT = Decimal("0.01")


def _validate_nonnegative_decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
        raise ValueError(f"{name} must be a finite, nonnegative Decimal")


def _validate_rate(name: str, value: Decimal) -> None:
    _validate_nonnegative_decimal(name, value)
    if value > 1:
        raise ValueError(f"{name} must be expressed as a fraction between 0 and 1")


def _validate_year(year: int) -> None:
    if type(year) is not int or not 1 <= year <= 9999:
        raise ValueError("tax_year must be a valid calendar year")


@dataclass(frozen=True, kw_only=True)
class SubjectWages:
    """Wages subject to each tax before annual caps or thresholds are applied."""

    social_security: Decimal
    medicare: Decimal
    ca_sdi: Decimal
    ca_ui: Decimal
    ca_ett: Decimal
    futa: Decimal

    def __post_init__(self) -> None:
        for field in fields(self):
            _validate_nonnegative_decimal(field.name, getattr(self, field.name))


@dataclass(frozen=True, kw_only=True)
class ContributionRules:
    """Statutory parameters in force for a calendar year."""

    tax_year: int
    social_security_rate: Decimal
    social_security_wage_cap: Decimal
    medicare_rate: Decimal
    additional_medicare_rate: Decimal
    additional_medicare_threshold: Decimal
    ca_sdi_rate: Decimal
    ca_sdi_wage_cap: Optional[Decimal]
    ca_ui_wage_cap: Decimal
    ca_ett_wage_cap: Decimal
    futa_rate_before_credits: Decimal
    futa_wage_cap: Decimal

    def __post_init__(self) -> None:
        _validate_year(self.tax_year)
        for name in (
            "social_security_rate",
            "medicare_rate",
            "additional_medicare_rate",
            "ca_sdi_rate",
            "futa_rate_before_credits",
        ):
            _validate_rate(name, getattr(self, name))
        for name in (
            "social_security_wage_cap",
            "additional_medicare_threshold",
            "ca_ui_wage_cap",
            "ca_ett_wage_cap",
            "futa_wage_cap",
        ):
            _validate_nonnegative_decimal(name, getattr(self, name))
        if self.ca_sdi_wage_cap is not None:
            _validate_nonnegative_decimal("ca_sdi_wage_cap", self.ca_sdi_wage_cap)


@dataclass(frozen=True, kw_only=True)
class CaliforniaEmployerNotice:
    """Employer-specific contribution rates from California EDD notice DE 2088."""

    tax_year: int
    ui_rate: Decimal
    ett_rate: Decimal

    def __post_init__(self) -> None:
        _validate_year(self.tax_year)
        _validate_rate("ui_rate", self.ui_rate)
        _validate_rate("ett_rate", self.ett_rate)


@dataclass(frozen=True, kw_only=True)
class TaxableWages:
    """Current-check wages after applying annual caps and thresholds."""

    social_security: Decimal
    medicare: Decimal
    additional_medicare: Decimal
    ca_sdi: Decimal
    ca_ui: Decimal
    ca_ett: Decimal
    futa: Decimal


@dataclass(frozen=True, kw_only=True)
class Contributions:
    taxable_wages: TaxableWages
    employee_social_security: Decimal
    employer_social_security: Decimal
    employee_medicare: Decimal
    employer_medicare: Decimal
    employee_additional_medicare: Decimal
    employee_ca_sdi: Decimal
    employer_ca_ui: Decimal
    employer_ca_ett: Decimal
    employer_futa_before_credits: Decimal


# IRS Publication 15 (2026): https://www.irs.gov/publications/p15
# California EDD annual rates: https://edd.ca.gov/en/payroll_taxes/rates_and_withholding/
US_CA_CONTRIBUTION_RULES_2026 = ContributionRules(
    tax_year=2026,
    social_security_rate=Decimal("0.062"),
    social_security_wage_cap=Decimal("184500"),
    medicare_rate=Decimal("0.0145"),
    additional_medicare_rate=Decimal("0.009"),
    additional_medicare_threshold=Decimal("200000"),
    ca_sdi_rate=Decimal("0.013"),
    ca_sdi_wage_cap=None,
    ca_ui_wage_cap=Decimal("7000"),
    ca_ett_wage_cap=Decimal("7000"),
    futa_rate_before_credits=Decimal("0.06"),
    futa_wage_cap=Decimal("7000"),
)


def _capped_wages(current: Decimal, prior: Decimal, cap: Optional[Decimal]) -> Decimal:
    if cap is None:
        return current
    return min(current, max(ZERO, cap - prior))


def _contribution(wages: Decimal, rate: Decimal) -> Decimal:
    return (wages * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_us_ca_contributions(
    *,
    pay_date: date,
    current_subject_wages: SubjectWages,
    prior_ytd_subject_wages: SubjectWages,
    rules: ContributionRules,
    employer_notice: CaliforniaEmployerNotice,
) -> Contributions:
    """Calculate contributions in cents for one check.

    Supply earlier wages for the same calendar year and applicable employer,
    including uncapped wages from any earlier checks paid on the same date.
    The caller determines which earnings are subject to each tax. FUTA is the
    gross amount before Form 940 credits or credit-reduction adjustments.
    """
    if not isinstance(pay_date, date):
        raise ValueError("pay_date must be a date")
    if rules.tax_year != pay_date.year:
        raise ValueError("contribution rules must match the pay date's calendar year")
    if employer_notice.tax_year != pay_date.year:
        raise ValueError("employer notice must match the pay date's calendar year")

    current = current_subject_wages
    prior = prior_ytd_subject_wages
    medicare_below_threshold = _capped_wages(
        current.medicare, prior.medicare, rules.additional_medicare_threshold
    )
    taxable_wages = TaxableWages(
        social_security=_capped_wages(
            current.social_security,
            prior.social_security,
            rules.social_security_wage_cap,
        ),
        medicare=current.medicare,
        additional_medicare=current.medicare - medicare_below_threshold,
        ca_sdi=_capped_wages(current.ca_sdi, prior.ca_sdi, rules.ca_sdi_wage_cap),
        ca_ui=_capped_wages(current.ca_ui, prior.ca_ui, rules.ca_ui_wage_cap),
        ca_ett=_capped_wages(current.ca_ett, prior.ca_ett, rules.ca_ett_wage_cap),
        futa=_capped_wages(current.futa, prior.futa, rules.futa_wage_cap),
    )
    social_security = _contribution(
        taxable_wages.social_security, rules.social_security_rate
    )
    medicare = _contribution(taxable_wages.medicare, rules.medicare_rate)

    return Contributions(
        taxable_wages=taxable_wages,
        employee_social_security=social_security,
        employer_social_security=social_security,
        employee_medicare=medicare,
        employer_medicare=medicare,
        employee_additional_medicare=_contribution(
            taxable_wages.additional_medicare, rules.additional_medicare_rate
        ),
        employee_ca_sdi=_contribution(taxable_wages.ca_sdi, rules.ca_sdi_rate),
        employer_ca_ui=_contribution(taxable_wages.ca_ui, employer_notice.ui_rate),
        employer_ca_ett=_contribution(taxable_wages.ca_ett, employer_notice.ett_rate),
        employer_futa_before_credits=_contribution(
            taxable_wages.futa, rules.futa_rate_before_credits
        ),
    )
