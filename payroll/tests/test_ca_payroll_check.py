from datetime import date
from decimal import Decimal
from unittest import TestCase

from payroll.methods.ca_hourly import calculate_hourly_pay, calculate_workweek
from payroll.methods.ca_payroll_check import calculate_ca_payroll_check
from payroll.methods.federal_withholding import FederalW4
from payroll.methods.us_ca_contributions import CaliforniaEmployerNotice, SubjectWages


def subject_wages(amount):
    return SubjectWages(
        social_security=amount, medicare=amount, ca_sdi=amount,
        ca_ui=amount, ca_ett=amount, futa=amount,
    )


class CaliforniaPaycheckTests(TestCase):
    def calculate(self, gross, wages, prior=Decimal("0")):
        return calculate_ca_payroll_check(
            pay_date=date(2026, 6, 5), pay_frequency="weekly", gross_pay=gross,
            federal_income_tax_wages=wages, ca_pit_wages=wages,
            current_subject_wages=subject_wages(wages),
            prior_ytd_subject_wages=subject_wages(prior),
            w4=FederalW4(form_year=2026, filing_status="single_or_married_filing_separately"),
            employer_notice=CaliforniaEmployerNotice(
                tax_year=2026, ui_rate=Decimal(".034"), ett_rate=Decimal(".001"),
            ),
        )

    def test_hourly_overtime_flows_to_pay_and_taxable_wages(self):
        start = date(2026, 6, 1)
        day = calculate_workweek(start, {start: 600}, Decimal("20"))
        gross = calculate_hourly_pay(day).gross_pay
        result = self.calculate(gross, gross)
        self.assertEqual(result.gross_pay, Decimal("220.00"))
        self.assertEqual(result.contributions.taxable_wages.social_security, gross)
        self.assertEqual(result.employee_tax_total, Decimal("19.69"))
        self.assertEqual(result.net_pay, Decimal("200.31"))

    def test_salary_keeps_employer_taxes_out_of_net_pay(self):
        result = self.calculate(Decimal("1000"), Decimal("1000"), Decimal("6900"))
        self.assertEqual(result.federal_income_tax, Decimal("78.08"))
        self.assertEqual(result.contributions.taxable_wages.futa, Decimal("100"))
        self.assertEqual(result.contributions.employer_futa_before_credits, Decimal("6.00"))
        self.assertEqual(result.employer_tax_before_futa_credits, Decimal("86.00"))
        self.assertEqual(result.net_pay, Decimal("1000") - result.employee_tax_total)

    def test_blocks_taxable_wages_above_gross_in_regular_cash_scope(self):
        with self.assertRaisesRegex(ValueError, "gross pay"):
            self.calculate(Decimal("100"), Decimal("101"))

    def test_prior_paid_wages_must_be_in_whole_cents(self):
        with self.assertRaisesRegex(ValueError, "whole cents"):
            self.calculate(Decimal("100"), Decimal("100"), Decimal("6999.995"))
