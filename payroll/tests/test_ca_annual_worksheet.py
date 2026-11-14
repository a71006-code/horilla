from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from report.forms.ca_annual_worksheet import (
    apply_w2_reviews, build_annual_worksheet, build_form_940_summary, compare_filed_quarters, write_annual_worksheet_csv,
)


def check(employee, month):
    return SimpleNamespace(employee_id=employee, paid_on=date(2026, month, 5), facts_version=1, facts={
        "gross_pay": "1000.00", "federal_income_tax_wages": "900.00", "ca_pit_wages": "850.00",
        "federal_income_tax": "78.08", "ca_pit_withheld": "20.00", "subject_wages": {"futa": "950.00"},
        "contributions": {
            "taxable_wages": {"social_security": "950.00", "medicare": "950.00", "futa": "100.00"},
            "employee_social_security": "58.90", "employer_social_security": "58.90",
            "employee_medicare": "13.78", "employer_medicare": "13.78",
            "employee_additional_medicare": "4.50", "employee_ca_sdi": "13.00",
            "employer_futa_before_credits": "6.00",
        },
    })


class CaliforniaAnnualWorksheetTests(TestCase):
    def test_unverified_w2_entries_stay_unresolved_in_employee_and_w3_drafts(self):
        worksheet = build_annual_worksheet([check(2, 1)])
        self.assertIsNone(worksheet["w2_handoff"][2]["box_12_tt"])
        self.assertIsNone(worksheet["w3_handoff"]["box_7"])
        export = write_annual_worksheet_csv(worksheet)
        self.assertIn("Box 14a · CASDI,13.00", export)
        self.assertIn("Box 12 · Code TT (qualified overtime premium),Unresolved", export)

    def test_verified_tips_split_social_security_wages_and_reconcile_both_941_lines(self):
        worksheet = build_annual_worksheet([check(2, 1), check(2, 4)])
        reviewed = apply_w2_reviews(worksheet, {2: {
            "box_7_quarters": (Decimal("100.00"), Decimal("60.00"), Decimal("0.00"), Decimal("0.00")),
            "box_12_tp": Decimal("170.00"), "box_12_tt": Decimal("42.50"), "box_14b": ("102", "000"),
        }})
        self.assertEqual(reviewed["employees"][2]["box_3"], Decimal("1740.00"))
        self.assertEqual(reviewed["w3_handoff"]["box_7"], Decimal("160.00"))
        self.assertEqual(reviewed["w3_quarters"][1]["box_3"], Decimal("850.00"))
        self.assertEqual(reviewed["w3_quarters"][2]["box_7"], Decimal("60.00"))
        self.assertEqual(reviewed["w3_quarters"][2]["fica_employee_withheld"], Decimal("77.18"))
        self.assertEqual(reviewed["w3_totals"]["box_5"], Decimal("1900.00"))
        self.assertEqual(worksheet["w3_quarters"][1]["box_3"], Decimal("950.00"))
        self.assertNotIn("box_12_tt", reviewed["w3_handoff"])

    def test_tip_reclassification_cannot_exceed_recorded_social_security_wages_in_a_quarter(self):
        worksheet = build_annual_worksheet([check(2, 1), check(2, 4)])
        with self.assertRaisesRegex(ValueError, "Q1"):
            apply_w2_reviews(worksheet, {2: {
                "box_7_quarters": (Decimal("951.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
                "box_12_tp": Decimal("951.00"),
            }})

    def test_only_reportable_deferred_compensation_codes_flow_to_w3_box_12a(self):
        worksheet = build_annual_worksheet([check(2, 1), check(3, 1)])
        reviewed = apply_w2_reviews(worksheet, {
            2: {"box_12_other": {"D": Decimal("200.00"), "DD": Decimal("100.00")}},
            3: {"box_12_other": {"AA": Decimal("300.00"), "TA": Decimal("50.00")}},
        })
        self.assertEqual(reviewed["w3_handoff"]["box_12a"], Decimal("500.00"))
        self.assertIsNone(apply_w2_reviews(worksheet, {2: {"box_12_other": {}}})["w3_handoff"]["box_12a"])

    def test_fica_comparison_rounds_social_security_wages_and_tips_separately(self):
        recorded_check = check(2, 1)
        recorded_check.facts["contributions"]["taxable_wages"]["social_security"] = "950.01"
        worksheet = apply_w2_reviews(build_annual_worksheet([recorded_check]), {2: {
            "box_7_quarters": (Decimal("0.05"), Decimal("0"), Decimal("0"), Decimal("0")),
            "box_12_tp": Decimal("0.05"),
        }})
        filed = {box: str(amount) for box, amount in worksheet["w3_quarters"][1].items() if box.startswith("box_")}
        filed.update(fica_tax="149.86", fica_rounding="0.00", sick_pay_adjustment="0.00", tips_life_adjustment="0.00")
        self.assertEqual(compare_filed_quarters(worksheet, {1: filed})[1]["status"], "Matched")

    def test_form_940_uses_net_rate_and_requires_a_verified_schedule_a_rate(self):
        worksheet = build_annual_worksheet([check(2, 1)])
        details = {"coverage": "timely", "deposit_total": Decimal("0.25"), "prior_credit": Decimal("0.10")}
        provisional = build_form_940_summary(worksheet, **details)
        self.assertEqual(provisional["lines"]["8"], Decimal("0.60"))
        self.assertIsNone(provisional["lines"]["12"])
        summary = build_form_940_summary(worksheet, rate_percent=Decimal("1.50"), **details)
        self.assertEqual(summary["lines"]["4"], Decimal("50.00"))
        self.assertEqual(summary["lines"]["11"], Decimal("1.50"))
        self.assertEqual(summary["lines"]["12"], Decimal("2.10"))
        self.assertEqual(summary["lines"]["14"], Decimal("1.75"))
        self.assertIn("1.50", write_annual_worksheet_csv(worksheet, form_940=summary))

    def test_form_940_all_excluded_restores_full_rate_without_schedule_a(self):
        worksheet = build_annual_worksheet([check(2, 1)])
        summary = build_form_940_summary(
            worksheet, coverage="excluded", deposit_total=Decimal("7.00"), prior_credit=Decimal("0.00"),
        )
        self.assertEqual(summary["lines"]["9"], Decimal("5.40"))
        self.assertIsNone(summary["lines"]["11"])
        self.assertEqual(summary["lines"]["15a"], Decimal("1.00"))

    def test_adjusted_form_940_part_5_requires_four_quarters_that_match_line_12(self):
        worksheet = {"futa": {
            "gross_pay": Decimal("35000"), "subject_wages": Decimal("35000"),
            "above_wage_base": Decimal("0"), "taxable_wages": Decimal("35000"),
        }}
        inputs = {
            "coverage": "adjusted", "adjusted_amount": Decimal("400"), "covered_wages": Decimal("10000"),
            "rate_percent": Decimal("1.50"), "deposit_total": Decimal("0"), "prior_credit": Decimal("0"),
        }
        self.assertTrue(build_form_940_summary(worksheet, **inputs)["status"])
        with self.assertRaisesRegex(ValueError, "line 12"):
            build_form_940_summary(worksheet, quarterly_liabilities=(Decimal("100"),) * 4, **inputs)
        quarters = tuple(map(Decimal, ("100", "200", "300", "160")))
        summary = build_form_940_summary(worksheet, quarterly_liabilities=quarters, **inputs)
        self.assertEqual(summary["lines"]["16d"], Decimal("160.00"))
        self.assertEqual(summary["lines"]["17"], Decimal("760.00"))

    def test_fica_uses_quarterly_employer_tax_and_actual_employee_withholding(self):
        worksheet = build_annual_worksheet([check(2, 1)])
        filed = {box: str(amount) for box, amount in worksheet["w3_quarters"][1].items() if box.startswith("box_")}
        self.assertEqual(compare_filed_quarters(worksheet, {1: filed})[1]["status"], "FICA amounts missing")
        filed.update(fica_tax="149.86", fica_rounding="-0.01", sick_pay_adjustment="0.00", tips_life_adjustment="0.00")
        result = compare_filed_quarters(worksheet, {1: filed})[1]
        self.assertEqual(result["status"], "Matched")
        self.assertEqual(result["rows"][-1][1:], (Decimal("149.85"), Decimal("149.85"), Decimal("0.00")))
        filed["sick_pay_adjustment"] = "-1.00"
        self.assertEqual(compare_filed_quarters(worksheet, {1: filed})[1]["status"], "Needs adjustment review")

    def test_employee_and_employer_totals_reuse_the_recorded_tax_bases(self):
        worksheet = build_annual_worksheet([check(2, 1), check(2, 12), check(3, 12)])
        self.assertEqual(worksheet["employees"][2]["box_1"], Decimal("1800.00"))
        self.assertEqual(worksheet["employees"][2]["box_2"], Decimal("156.16"))
        self.assertEqual(worksheet["employees"][2]["box_3"], Decimal("1900.00"))
        self.assertEqual(worksheet["employees"][2]["box_6"], Decimal("36.56"))
        self.assertEqual(worksheet["employees"][2]["box_16"], Decimal("1700.00"))
        self.assertEqual(worksheet["w3_totals"]["box_6"], Decimal("54.84"))
        self.assertNotIn("ca_sdi", worksheet["w3_totals"])
        self.assertEqual(worksheet["futa"]["subject_wages"], Decimal("2850.00"))
        self.assertEqual(worksheet["futa"]["above_wage_base"], Decimal("2550.00"))
        self.assertEqual(worksheet["futa"]["before_credits"], Decimal("18.00"))
        self.assertEqual(worksheet["futa_quarters"][4]["before_credits"], Decimal("12.00"))

    def test_year_end_csv_is_labeled_draft_and_has_no_tax_ids(self):
        output = write_annual_worksheet_csv(build_annual_worksheet([check(2, 12)]))
        self.assertIn("DRAFT", output)
        self.assertIn("Employee record ID", output)
        self.assertNotIn("SSN", output)
        self.assertIn("18.28", output)

    def test_missing_wage_base_is_an_error_instead_of_zero(self):
        malformed = check(2, 12)
        del malformed.facts["contributions"]["taxable_wages"]["medicare"]
        with self.assertRaisesRegex(ValueError, "missing or invalid"):
            build_annual_worksheet([malformed])

    def test_rejects_two_checks_using_the_same_futa_wage_base_capacity(self):
        checks = [check(2, 1), check(2, 2)]
        for row in checks:
            row.facts["gross_pay"] = "4000.00"
            row.facts["subject_wages"]["futa"] = "4000.00"
            row.facts["contributions"]["taxable_wages"]["futa"] = "4000.00"
        with self.assertRaisesRegex(ValueError, "annual wage cap"):
            build_annual_worksheet(checks)
