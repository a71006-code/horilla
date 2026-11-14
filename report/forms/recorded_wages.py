"""Money fields shared by worksheets based on recorded payroll facts."""

from decimal import Decimal


ZERO = Decimal("0.00")


def recorded_amount(value, *, allow_negative=False):
    amount = Decimal(value)
    if not amount.is_finite() or (amount < 0 and not allow_negative) or amount != amount.quantize(ZERO):
        raise ValueError("Invalid recorded tax amount.")
    return amount
