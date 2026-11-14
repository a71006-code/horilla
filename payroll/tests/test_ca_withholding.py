from datetime import date
from decimal import Decimal
from unittest import TestCase

from payroll.methods.ca_withholding import CaliforniaDE4, calculate_ca_withholding


class CaliforniaWithholdingTests(TestCase):
    def calculate(self, wages, frequency, de4=None, *, year=2026):
        return calculate_ca_withholding(
            pay_date=date(year, 6, 1), taxable_wages=Decimal(wages),
            pay_frequency=frequency, de4=de4,
        )

    def test_missing_de4_uses_single_and_low_income_exemption(self):
        self.assertEqual(self.calculate("1575", "monthly"), Decimal("0.00"))
        self.assertEqual(self.calculate("2000", "monthly"), Decimal("23.38"))

    def test_edd_published_annualized_examples(self):
        de4 = CaliforniaDE4(filing_status="married_one_income", regular_allowances=4)
        self.assertEqual(self.calculate("2400", "semi_monthly", de4), Decimal("4.13"))
        self.assertEqual(self.calculate("4750", "monthly", de4), Decimal("7.17"))

    def test_estimated_deductions_and_extra_withholding_are_distinct(self):
        de4 = CaliforniaDE4(regular_allowances=1, estimated_allowances=2,
                            extra_withholding=Decimal("12.34"))
        self.assertEqual(self.calculate("5000", "monthly", de4), Decimal("151.63"))

    def test_estimated_allowance_does_not_raise_married_exemption(self):
        de4 = CaliforniaDE4(
            filing_status="married_one_income", regular_allowances=1, estimated_allowances=1,
        )
        self.assertEqual(self.calculate("600", "weekly", de4), Decimal("2.44"))

    def test_unsupported_period_or_tax_year_is_rejected(self):
        with self.assertRaises(ValueError):
            self.calculate("1500", "daily")
        with self.assertRaises(ValueError):
            self.calculate("1500", "weekly", year=2027)
