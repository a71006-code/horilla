"""Federal income tax withholding for regular wages paid in 2026."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


_TAX_YEAR = 2026
# The IRS 2026 first-quarter tax calendar moves the deadline past the weekend and holiday.
_EXEMPTION_RENEWAL_DEADLINE = date(2026, 2, 17)
_ZERO = Decimal("0")
_CENT = Decimal("0.01")

_SINGLE = "single_or_married_filing_separately"
_JOINT = "married_filing_jointly"
_HEAD_OF_HOUSEHOLD = "head_of_household"

# IRS Publication 15-T (2026), Worksheet 1A and section 1.
# https://www.irs.gov/publications/p15t
_PAY_PERIODS = {"weekly": 52, "biweekly": 26, "semi_monthly": 24, "monthly": 12}

# Rows contain the inclusive lower limit, base tax in dollars, and marginal
# percentage. Use the published base amounts, including the cents in column C.
_STANDARD_SCHEDULES = {
    _SINGLE: (
        (0, 0, 0),
        (7_500, 0, 10),
        (19_900, 1_240, 12),
        (57_900, 5_800, 22),
        (113_200, 17_966, 24),
        (209_275, 41_024, 32),
        (263_725, 58_448, 35),
        (648_100, Decimal("192979.25"), 37),
    ),
    _JOINT: (
        (0, 0, 0),
        (19_300, 0, 10),
        (44_100, 2_480, 12),
        (120_100, 11_600, 22),
        (230_700, 35_932, 24),
        (422_850, 82_048, 32),
        (531_750, 116_896, 35),
        (788_000, Decimal("206583.50"), 37),
    ),
    _HEAD_OF_HOUSEHOLD: (
        (0, 0, 0),
        (15_550, 0, 10),
        (33_250, 1_770, 12),
        (83_000, 7_740, 22),
        (121_250, 16_155, 24),
        (217_300, 39_207, 32),
        (271_750, 56_631, 35),
        (656_150, 191_171, 37),
    ),
}

_STEP_2_SCHEDULES = {
    _SINGLE: (
        (0, 0, 0),
        (8_050, 0, 10),
        (14_250, 620, 12),
        (33_250, 2_900, 22),
        (60_900, 8_983, 24),
        (108_938, 20_512, 32),
        (136_163, 29_224, 35),
        (328_350, Decimal("96489.63"), 37),
    ),
    _JOINT: (
        (0, 0, 0),
        (16_100, 0, 10),
        (28_500, 1_240, 12),
        (66_500, 5_800, 22),
        (121_800, 17_966, 24),
        (217_875, 41_024, 32),
        (272_325, 58_448, 35),
        (400_450, Decimal("103291.75"), 37),
    ),
    _HEAD_OF_HOUSEHOLD: (
        (0, 0, 0),
        (12_075, 0, 10),
        (20_925, 885, 12),
        (45_800, 3_870, 22),
        (64_925, Decimal("8077.50"), 24),
        (112_950, Decimal("19603.50"), 32),
        (140_175, Decimal("28315.50"), 35),
        (332_375, Decimal("95585.50"), 37),
    ),
}


def _validate_amount(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < _ZERO:
        raise ValueError(f"{name} must be a finite, nonnegative Decimal")


@dataclass(frozen=True, kw_only=True)
class FederalW4:
    """Entries from the employee's applicable 2020-or-later Form W-4.

    Use Step 1(c) for filing status, Step 2(c) for multiple jobs, Step 3 for
    annual credits, and Steps 4(a), 4(b), and 4(c) for other income, deductions,
    and extra withholding. For a certified exemption use filing_status=None
    and leave the adjustments blank.
    """

    form_year: int
    filing_status: Optional[str]
    multiple_jobs: bool = False
    annual_credits: Decimal = _ZERO
    annual_other_income: Decimal = _ZERO
    annual_deductions: Decimal = _ZERO
    extra_withholding: Decimal = _ZERO
    exempt: bool = False

    def __post_init__(self) -> None:
        if type(self.form_year) is not int or self.form_year < 2020:
            raise ValueError("form_year must identify a 2020-or-later Form W-4")
        if type(self.multiple_jobs) is not bool or type(self.exempt) is not bool:
            raise ValueError("multiple_jobs and exempt must be booleans")
        amounts = {
            "annual_credits": self.annual_credits,
            "annual_other_income": self.annual_other_income,
            "annual_deductions": self.annual_deductions,
            "extra_withholding": self.extra_withholding,
        }
        for name, value in amounts.items():
            _validate_amount(name, value)

        if self.exempt:
            has_adjustments = self.multiple_jobs or any(amounts.values())
            if self.filing_status is not None or has_adjustments:
                raise ValueError("An exempt Form W-4 must omit Steps 1(c), 2, 3, and 4")
        elif (
            not isinstance(self.filing_status, str)
            or self.filing_status not in _STANDARD_SCHEDULES
        ):
            raise ValueError("Unsupported Form W-4 filing status")


def calculate_federal_withholding(
    *, pay_date: date, taxable_wages: Decimal, pay_frequency: str, w4: FederalW4 | None = None
) -> Decimal:
    """Return per-check withholding in cents using IRS Pub. 15-T Worksheet 1A.

    Supply regular federal taxable wages and the Form W-4 in effect on the
    actual pay date. This calculation is for employees using the standard
    Worksheet 1A procedure without special withholding adjustments. Use None
    for a new employee without a completed certificate.
    """
    if type(pay_date) is not date or pay_date.year != _TAX_YEAR:
        raise ValueError("pay_date must be a calendar date in 2026")
    if not isinstance(pay_frequency, str) or pay_frequency not in _PAY_PERIODS:
        raise ValueError("Unsupported federal withholding pay frequency")
    _validate_amount("taxable_wages", taxable_wages)
    if w4 is None:
        w4 = FederalW4(form_year=_TAX_YEAR, filing_status=_SINGLE)
    if not isinstance(w4, FederalW4) or w4.form_year > pay_date.year:
        raise ValueError("An applicable modern Form W-4 is required")
    if w4.exempt:
        if w4.form_year == _TAX_YEAR:
            return Decimal("0.00")
        if w4.form_year != _TAX_YEAR - 1:
            raise ValueError("An exemption from an earlier tax year is no longer in effect")
        if pay_date <= _EXEMPTION_RENEWAL_DEADLINE:
            return Decimal("0.00")
        w4 = FederalW4(form_year=_TAX_YEAR, filing_status=_SINGLE)

    periods = _PAY_PERIODS[pay_frequency]
    adjusted_wages = (
        taxable_wages * periods + w4.annual_other_income - w4.annual_deductions
    )
    schedules = _STEP_2_SCHEDULES if w4.multiple_jobs else _STANDARD_SCHEDULES
    if not w4.multiple_jobs:
        adjusted_wages -= 12_900 if w4.filing_status == _JOINT else 8_600
    adjusted_wages = max(_ZERO, adjusted_wages)

    lower, base, percent = next(
        row for row in reversed(schedules[w4.filing_status]) if adjusted_wages >= row[0]
    )
    annual_tax = base + (adjusted_wages - lower) * percent / 100
    # Apply the annual credit before dividing to avoid two rounded divisions.
    per_check = max(_ZERO, annual_tax - w4.annual_credits) / periods
    return (per_check + w4.extra_withholding).quantize(_CENT, rounding=ROUND_HALF_UP)
