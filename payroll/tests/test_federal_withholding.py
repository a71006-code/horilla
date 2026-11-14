from datetime import date
from decimal import Decimal
from unittest import TestCase

from payroll.methods.federal_withholding import (
    FederalW4,
    calculate_federal_withholding,
)


SINGLE = "single_or_married_filing_separately"
JOINT = "married_filing_jointly"
HEAD_OF_HOUSEHOLD = "head_of_household"


class FederalWithholdingTest(TestCase):
    def withholding(self, wages, frequency="monthly", *, pay_date=date(2026, 1, 2), **w4):
        return calculate_federal_withholding(
            pay_date=pay_date,
            taxable_wages=Decimal(wages),
            pay_frequency=frequency,
            w4=FederalW4(**{"form_year": 2026, "filing_status": SINGLE, **w4}),
        )

    def test_uses_the_scheduled_pay_frequency(self):
        for frequency, wages, expected in (
            ("weekly", "1000", "78.08"),
            ("biweekly", "2000", "156.15"),
            ("semi_monthly", "2500", "209.17"),
            ("monthly", "5000", "418.33"),
        ):
            with self.subTest(frequency=frequency):
                self.assertEqual(self.withholding(wages, frequency), Decimal(expected))

    def test_selects_the_schedule_by_filing_status_and_step_2(self):
        for status, multiple_jobs, expected in (
            (SINGLE, False, "418.33"),
            (SINGLE, True, "732.08"),
            (JOINT, False, "236.67"),
            (JOINT, True, "418.33"),
            (HEAD_OF_HOUSEHOLD, False, "329.00"),
            (HEAD_OF_HOUSEHOLD, True, "582.83"),
        ):
            with self.subTest(status=status, multiple_jobs=multiple_jobs):
                self.assertEqual(
                    self.withholding(
                        "5000", filing_status=status, multiple_jobs=multiple_jobs
                    ),
                    Decimal(expected),
                )

    def test_uses_irs_base_amounts_at_joint_bracket_boundaries(self):
        self.assertEqual(
            self.withholding("20300", filing_status=JOINT), Decimal("2994.33")
        )
        self.assertEqual(
            self.withholding("36312.50", filing_status=JOINT), Decimal("6837.33")
        )

    def test_uses_published_base_amount_in_top_single_step_2_bracket(self):
        self.assertEqual(
            self.withholding("30000", multiple_jobs=True), Decimal("9016.68")
        )

    def test_applies_annual_adjustments_and_per_check_extra_withholding(self):
        self.assertEqual(
            self.withholding(
                "1000",
                "weekly",
                annual_credits=Decimal("1040"),
                annual_other_income=Decimal("5200"),
                annual_deductions=Decimal("2600"),
                extra_withholding=Decimal("13.25"),
            ),
            Decimal("77.33"),
        )

    def test_clamps_withholding_before_adding_extra(self):
        self.assertEqual(
            self.withholding(
                "1000",
                "weekly",
                annual_credits=Decimal("4400"),
                extra_withholding=Decimal("17.35"),
            ),
            Decimal("17.35"),
        )

    def test_rounds_an_exact_half_cent_up_after_credits(self):
        self.assertEqual(
            self.withholding("1000", "weekly", annual_credits=Decimal("4059.74")),
            Decimal("0.01"),
        )

    def test_applies_2026_rules_to_an_older_modern_form(self):
        self.assertEqual(self.withholding("5000", form_year=2020), Decimal("418.33"))

    def test_honors_an_exemption_for_the_pay_year(self):
        self.assertEqual(
            self.withholding("5000", filing_status=None, exempt=True), Decimal("0.00")
        )

    def test_prior_year_exemption_through_2026_renewal_deadline(self):
        fields = {"filing_status": None, "form_year": 2025, "exempt": True}
        self.assertEqual(self.withholding("5000", pay_date=date(2026, 2, 17), **fields), Decimal("0.00"))
        self.assertEqual(self.withholding("5000", pay_date=date(2026, 2, 18), **fields), Decimal("418.33"))

    def test_no_certificate_uses_new_employee_default(self):
        self.assertEqual(calculate_federal_withholding(
            pay_date=date(2026, 3, 1), taxable_wages=Decimal("1000"), pay_frequency="weekly",
        ), Decimal("78.08"))

    def test_rejects_out_of_scope_pay_year_and_form_year(self):
        for pay_date, form_year in (
            (date(2025, 12, 31), 2025),
            (date(2027, 1, 1), 2026),
            (date(2026, 1, 1), 2019),
            (date(2026, 1, 1), 2027),
        ):
            with self.subTest(pay_date=pay_date, form_year=form_year):
                with self.assertRaises(ValueError):
                    self.withholding("5000", pay_date=pay_date, form_year=form_year)

    def test_rejects_expired_or_conflicting_exemption_inputs(self):
        for fields in (
            {"filing_status": None, "form_year": 2024},
            {"filing_status": SINGLE},
            {"filing_status": None, "multiple_jobs": True},
            {"filing_status": None, "extra_withholding": Decimal("10")},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    self.withholding("5000", exempt=True, **fields)

    def test_rejects_unsupported_frequency_and_malformed_inputs(self):
        for wages, frequency, w4 in (
            ("5000", "daily", {}),
            ("-0.01", "monthly", {}),
            ("NaN", "monthly", {}),
            ("5000", "monthly", {"filing_status": None}),
            ("5000", "monthly", {"filing_status": "Married"}),
            ("5000", "monthly", {"multiple_jobs": 1}),
            ("5000", "monthly", {"annual_deductions": Decimal("-0.01")}),
            ("5000", "monthly", {"annual_credits": 100.0}),
        ):
            with self.subTest(wages=wages, frequency=frequency, w4=w4):
                with self.assertRaises(ValueError):
                    self.withholding(wages, frequency, **w4)
