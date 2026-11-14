from datetime import date
from decimal import Decimal
from unittest import TestCase

from report.forms.ca_quarterly_returns import build_adjusted_941_schedule, build_quarterly_return_rows


class QuarterlyReturnSummaryTests(TestCase):
    def worksheet(self, *, missing=0):
        return {
            "totals": {
                "federal_income_tax_wages": Decimal("1000.00"),
                "federal_income_tax": Decimal("78.08"),
                "social_security_wages": Decimal("1000.00"),
                "medicare_wages": Decimal("1000.00"),
                "additional_medicare_wages": Decimal("0.00"),
                "ca_ui_wages": Decimal("1000.00"),
                "ca_ett_wages": Decimal("1000.00"),
                "ca_sdi_wages": Decimal("1000.00"),
                "employee_ca_sdi": Decimal("13.00"),
                "ca_pit_withheld": Decimal("20.00"),
            },
            "missing_de9c_check_count": missing,
            "edd_subject_wages": Decimal("1000.00"),
            "federal_tax_before_adjustments": Decimal("231.08"),
            "federal_deposits": Decimal("225.00"),
            "california_deposits": Decimal("65.00"),
        }

    def test_adjustments_and_prior_credit_apply_to_the_correct_return(self):
        rows = build_quarterly_return_rows(
            self.worksheet(), adjustments={
                "fractions_of_cents": Decimal("-0.01"), "federal_prior_credit": Decimal("6.08"),
                "ui_rate_percent": Decimal("3.4"), "ett_rate_percent": Decimal("0.1"),
            },
        )
        federal = {line: amount for line, _, amount in rows["941"]}
        california = {line: amount for line, _, amount in rows["DE 9"]}
        self.assertEqual(federal["6"], Decimal("231.08"))
        self.assertEqual(federal["12"], Decimal("231.07"))
        self.assertEqual(federal["15a"], Decimal("0.01"))
        self.assertEqual(california["Subject wages"], Decimal("1000.00"))
        self.assertEqual(california["Tax due"], Decimal("3.00"))

    def test_missing_subject_wages_omits_de9_balance(self):
        rows = build_quarterly_return_rows(
            self.worksheet(missing=1), adjustments={"ui_rate_percent": Decimal("3.4"), "ett_rate_percent": Decimal("0.1")},
        )
        self.assertNotIn("Tax due", {line for line, _, _ in rows["DE 9"]})

    def test_de9_uses_quarterly_sdi_and_flags_inconsistent_ett_wages(self):
        worksheet = self.worksheet()
        worksheet["totals"].update(ca_sdi_wages=Decimal("13004.94"), employee_ca_sdi=Decimal("169.00"))
        rates = {"ui_rate_percent": Decimal("3.4"), "ett_rate_percent": Decimal("0.1")}
        rows = build_quarterly_return_rows(worksheet, adjustments=rates)
        california = {line: amount for line, _, amount in rows["DE 9"]}
        self.assertEqual(california["SDI tax"], Decimal("169.06"))
        self.assertEqual(california["SDI difference"], Decimal("0.06"))
        worksheet["totals"]["ca_ett_wages"] = Decimal("500")
        rows = build_quarterly_return_rows(worksheet, adjustments=rates)
        self.assertNotIn("Tax due", {line for line, _, _ in rows["DE 9"]})

    def test_social_security_tips_are_reclassified_without_adding_wages(self):
        rows = build_quarterly_return_rows(self.worksheet(), adjustments={"social_security_tips": Decimal("100.00")})
        federal = {line: amount for line, _, amount in rows["941"]}
        self.assertEqual(federal["5a col. 1"], Decimal("900.00"))
        self.assertEqual(federal["5b col. 1"], Decimal("100.00"))
        self.assertEqual(federal["5e"], Decimal("153.00"))
        with self.assertRaisesRegex(ValueError, "exceed"):
            build_quarterly_return_rows(self.worksheet(), adjustments={"social_security_tips": Decimal("1000.01")})

    def test_schedule_exports_only_when_adjusted_liability_ties_to_line_12(self):
        january = date(2026, 1, 2)
        march = date(2026, 3, 31)
        recorded = {january: Decimal("100"), march: Decimal("200")}
        amount = Decimal("299.99")
        self.assertEqual(build_adjusted_941_schedule(recorded, "monthly", {}, amount), [])
        rows = build_adjusted_941_schedule(recorded, "monthly", {march: Decimal("-0.01")}, amount)
        self.assertEqual(rows[-1], ("2026-03", "Adjusted monthly liability", Decimal("199.99")))
        with self.assertRaisesRegex(ValueError, "negative"):
            build_adjusted_941_schedule(recorded, "semiweekly", {march: Decimal("-200.01")}, Decimal("99.99"))
