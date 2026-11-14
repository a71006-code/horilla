from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from report.forms.ca_quarterly_worksheet import build_quarterly_worksheet, write_quarterly_worksheet_csv


class CaliforniaQuarterlyWorksheetTests(TestCase):
    def test_pay_date_liability_and_deposits_are_separate(self):
        facts = {
            "federal_income_tax_wages": "1000.00",
            "ca_pit_wages": "900.00",
            "federal_income_tax": "78.08",
            "ca_pit_withheld": "20.00",
            "contributions": {
                "taxable_wages": dict(social_security="1000", medicare="1000",
                                      additional_medicare="0", ca_sdi="1000", ca_ui="100", ca_ett="100"),
                "employee_social_security": "62.00", "employer_social_security": "62.00",
                "employee_medicare": "14.50", "employer_medicare": "14.50",
                "employee_additional_medicare": "0.00", "employee_ca_sdi": "13.00",
                "employer_ca_ui": "3.40", "employer_ca_ett": "0.10",
            },
        }
        checks = [SimpleNamespace(
            employee_id=42, paid_on=date(2026, month, 5), facts_version=1, facts=facts,
        ) for month in (1, 3)]
        deposits = [SimpleNamespace(kind="federal_941", amount=Decimal("400.00")),
                    SimpleNamespace(kind="ca_de9", amount=Decimal("60.00"))]
        result = build_quarterly_worksheet(checks, deposits)
        self.assertEqual(result["federal_tax_before_adjustments"], Decimal("462.16"))
        self.assertEqual(result["federal_deposits"], Decimal("400.00"))
        self.assertEqual(result["california_tax_before_adjustments"], Decimal("73.00"))
        self.assertEqual(result["california_deposits"], Decimal("60.00"))
        self.assertEqual(result["monthly_federal_liability"], {1: Decimal("231.08"), 3: Decimal("231.08")})
        self.assertEqual(result["daily_federal_liability"][date(2026, 3, 5)], Decimal("231.08"))
        self.assertEqual(result["employees"], {42: {"pit_wages": Decimal("1800.00"), "pit_withheld": Decimal("40.00")}})
        self.assertEqual(result["missing_de9c_check_count"], 2)

        facts.update(ca_edd_subject_wages="1000.00", ca_wage_plan_code="S")
        reviewed = build_quarterly_worksheet(checks, deposits)
        self.assertEqual(reviewed["missing_de9c_check_count"], 0)
        self.assertEqual(reviewed["de9c_rows"], [{
            "employee_id": 42, "plan_code": "S", "subject_wages": Decimal("2000.00"),
            "pit_wages": Decimal("1800.00"), "pit_withheld": Decimal("40.00"),
        }])
        csv = write_quarterly_worksheet_csv(reviewed, employer_id=1, quarter=1)
        self.assertIn("DE 9C draft,42 / S,Subject wages,2000.00", csv)
        self.assertIn("941 daily draft,2026-03-05", csv)
        self.assertNotIn("SSN", csv)

    def test_unsupported_snapshot_version_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "version"):
            build_quarterly_worksheet([SimpleNamespace(facts_version=99)], [])
