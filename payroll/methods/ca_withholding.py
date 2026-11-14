"""2026 California PIT on regular wages using EDD Method B annualization.

Source: https://edd.ca.gov/siteassets/files/pdf_pub_ctr/26methb.pdf
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
# Table 1. Columns are periods per year, lower exemption, higher exemption.
_PAY_PERIODS = {
    "weekly": (52, 363, 727),
    "biweekly": (26, 727, 1454),
    "semi_monthly": (24, 787, 1575),
    "monthly": (12, 1575, 3149),
}
_RATES = tuple(map(Decimal, (
    ".011", ".022", ".044", ".066", ".088", ".1023", ".1133", ".1243", ".1353", ".1463",
)))
# Tables 5–7. Each pair is the lower threshold and the published base tax.
_ANNUAL_TABLES = {
    "single_or_dual_income": (
        (0, "0"), (11079, "121.87"), (26264, "455.94"), (41452, "1124.21"),
        (57542, "2186.15"), (72724, "3522.17"), (371479, "34084.81"),
        (445771, "42502.09"), (742953, "79441.81"), (1000000, "114220.27"),
    ),
    "married_one_income": (
        (0, "0"), (22158, "243.74"), (52528, "911.88"), (82904, "2248.42"),
        (115084, "4372.30"), (145448, "7044.33"), (742958, "68169.60"),
        (891542, "85004.17"), (1000000, "98485.50"), (1485906, "164228.58"),
    ),
    "head_of_household": (
        (0, "0"), (22173, "243.90"), (52530, "911.75"), (67716, "1579.93"),
        (83805, "2641.80"), (98990, "3978.08"), (505208, "45534.18"),
        (606251, "56982.35"), (1000000, "105925.35"), (1010417, "107334.77"),
    ),
}


def _validate_amount(amount):
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise ValueError("Wages and withholding amounts must be nonnegative finite Decimals.")


@dataclass(frozen=True, kw_only=True)
class CaliforniaDE4:
    filing_status: str = "single_or_dual_income"
    regular_allowances: int = 0
    estimated_allowances: int = 0
    extra_withholding: Decimal = _ZERO

    def __post_init__(self):
        if self.filing_status not in _ANNUAL_TABLES:
            raise ValueError("Unsupported California filing status.")
        for count in (self.regular_allowances, self.estimated_allowances):
            if type(count) is not int or count < 0:
                raise ValueError("DE 4 allowance counts must be nonnegative integers.")
        _validate_amount(self.extra_withholding)


def calculate_ca_withholding(
    *, pay_date: date, taxable_wages: Decimal, pay_frequency: str,
    de4: CaliforniaDE4 | None = None,
) -> Decimal:
    """Withhold PIT on 2026 regular wages. A missing DE 4 uses single/zero.

    The caller supplies wages subject to CA PIT and must route special cases,
    such as an exemption certificate or separately paid supplemental wages.
    """
    if type(pay_date) is not date or pay_date.year != 2026:
        raise ValueError("California withholding rules are available for 2026 only.")
    if pay_frequency not in _PAY_PERIODS:
        raise ValueError("Unsupported California pay frequency.")
    _validate_amount(taxable_wages)
    if de4 is None:
        de4 = CaliforniaDE4()
    periods, low, high = _PAY_PERIODS[pay_frequency]
    higher_allowance = de4.filing_status == "head_of_household" or (
        de4.filing_status == "married_one_income"
        and de4.regular_allowances >= 2
    )
    if taxable_wages <= (high if higher_allowance else low):
        return de4.extra_withholding.quantize(_CENT, rounding=ROUND_HALF_UP)

    annual_wages = taxable_wages * periods
    standard_deduction = 11412 if higher_allowance else 5706
    adjusted_wages = max(
        _ZERO, annual_wages - 1000 * de4.estimated_allowances - standard_deduction
    )
    table = _ANNUAL_TABLES[de4.filing_status]
    bracket = max(index for index, (floor, _) in enumerate(table) if adjusted_wages >= floor)
    floor, base = table[bracket]
    annual_tax = Decimal(base) + (adjusted_wages - floor) * _RATES[bracket]
    annual_tax -= Decimal("168.30") * de4.regular_allowances
    withheld = max(_ZERO, annual_tax) / periods + de4.extra_withholding
    return withheld.quantize(_CENT, rounding=ROUND_HALF_UP)
