from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import TestCase

from payroll.methods import us_ca_contributions as calculator


class USCAContributionsTest(TestCase):
    def setUp(self):
        self.rules = calculator.US_CA_CONTRIBUTION_RULES_2026
        self.notice = calculator.CaliforniaEmployerNotice(
            tax_year=2026, ui_rate=Decimal("0.027"), ett_rate=Decimal("0.001")
        )

    def wages(self, **amounts):
        fields = ("social_security", "medicare", "ca_sdi", "ca_ui", "ca_ett", "futa")
        return calculator.SubjectWages(
            **{field: Decimal(amounts.get(field, "0")) for field in fields}
        )

    def calculate(self, current, prior=None, **overrides):
        inputs = {
            "pay_date": date(2026, 6, 19),
            "current_subject_wages": current,
            "prior_ytd_subject_wages": prior if prior is not None else self.wages(),
            "rules": self.rules,
            "employer_notice": self.notice,
        }
        return calculator.calculate_us_ca_contributions(**(inputs | overrides))

    def test_uses_separate_subject_wages_for_each_contribution(self):
        result = self.calculate(
            self.wages(
                social_security="1000",
                medicare="1250",
                ca_sdi="1500",
                ca_ui="2000",
                ca_ett="2300",
                futa="2500",
            )
        )

        self.assertEqual(
            result,
            calculator.Contributions(
                taxable_wages=calculator.TaxableWages(
                    social_security=Decimal("1000"),
                    medicare=Decimal("1250"),
                    additional_medicare=Decimal("0"),
                    ca_sdi=Decimal("1500"),
                    ca_ui=Decimal("2000"),
                    ca_ett=Decimal("2300"),
                    futa=Decimal("2500"),
                ),
                employee_social_security=Decimal("62.00"),
                employer_social_security=Decimal("62.00"),
                employee_medicare=Decimal("18.13"),
                employer_medicare=Decimal("18.13"),
                employee_additional_medicare=Decimal("0.00"),
                employee_ca_sdi=Decimal("19.50"),
                employer_ca_ui=Decimal("54.00"),
                employer_ca_ett=Decimal("2.30"),
                employer_futa_before_credits=Decimal("150.00"),
            ),
        )

    def test_applies_each_annual_cap_to_its_own_prior_subject_wages(self):
        result = self.calculate(
            self.wages(
                social_security="1000",
                medicare="500",
                ca_sdi="2000",
                ca_ui="600",
                ca_ett="500",
                futa="400",
            ),
            self.wages(
                social_security="184400",
                medicare="199800",
                ca_sdi="500000",
                ca_ui="6900",
                ca_ett="7100",
                futa="6950",
            ),
        )

        self.assertEqual(
            result.taxable_wages,
            calculator.TaxableWages(
                social_security=Decimal("100"),
                medicare=Decimal("500"),
                additional_medicare=Decimal("300"),
                ca_sdi=Decimal("2000"),
                ca_ui=Decimal("100"),
                ca_ett=Decimal("0"),
                futa=Decimal("50"),
            ),
        )
        self.assertEqual(result.employee_social_security, Decimal("6.20"))
        self.assertEqual(result.employer_social_security, Decimal("6.20"))
        self.assertEqual(result.employee_ca_sdi, Decimal("26.00"))
        self.assertEqual(result.employer_ca_ui, Decimal("2.70"))
        self.assertEqual(result.employer_ca_ett, Decimal("0.00"))
        self.assertEqual(result.employer_futa_before_credits, Decimal("3.00"))

    def test_withholds_additional_medicare_only_on_current_wages_above_threshold(self):
        cases = (("199500", "0.00"), ("199800", "2.70"), ("210000", "4.50"))
        for prior, expected in cases:
            with self.subTest(prior=prior):
                result = self.calculate(
                    self.wages(medicare="500"), self.wages(medicare=prior)
                )

                self.assertEqual(result.employee_additional_medicare, Decimal(expected))
                self.assertEqual(result.employee_medicare, Decimal("7.25"))
                self.assertEqual(result.employer_medicare, Decimal("7.25"))

    def test_honors_zero_ett_rate_from_the_employer_notice(self):
        result = self.calculate(
            self.wages(ca_ett="1000"),
            employer_notice=replace(self.notice, ett_rate=Decimal("0")),
        )

        self.assertEqual(result.employer_ca_ett, Decimal("0.00"))

    def test_pay_date_must_match_both_rule_years(self):
        for overrides in (
            {"pay_date": date(2027, 1, 1)},
            {"employer_notice": replace(self.notice, tax_year=2025)},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.calculate(self.wages(), **overrides)

    def test_rejects_invalid_subject_wages(self):
        for invalid in (Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), 0.01):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                replace(self.wages(), ca_ui=invalid)

    def test_rejects_invalid_rate_inputs(self):
        for invalid in (Decimal("-0.01"), Decimal("NaN"), Decimal("1.1"), 0.01):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                replace(self.notice, ui_rate=invalid)
