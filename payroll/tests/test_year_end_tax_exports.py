import csv
import io
from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from employee.models import Employee

from report.forms.year_end_tax import (
    build_w2_w3_context,
    generate_w2_csv,
    generate_w3_csv,
)


class EmployeeTaxIdentityFieldTest(TestCase):
    def test_employee_has_ssn_field_for_year_end_forms(self):
        field = Employee._meta.get_field("ssn")

        self.assertEqual(field.max_length, 11)
        self.assertTrue(field.blank)
        self.assertTrue(field.null)


class YearEndTaxExportHelperTest(TestCase):
    @patch("report.forms.year_end_tax.Deduction")
    def test_build_w2_w3_context_groups_tax_boxes_by_employee(self, mock_deduction):
        payslip_qs = MagicMock()
        payslip_qs.exists.return_value = True
        payslip_qs.values.return_value = [
            {
                "id": 1,
                "employee_id": 10,
                "employee_id__employee_first_name": "Ava",
                "employee_id__employee_last_name": "Stone",
                "employee_id__ssn": "111-22-3333",
                "employee_id__email": "ava@example.com",
                "employee_id__badge_id": "E10",
                "employee_id__address": "44 Pine St",
                "employee_id__city": "Sacramento",
                "employee_id__state": "CA",
                "employee_id__zip": "95814",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 15),
                "gross_pay": 100000.0,
                "pay_head_data": {
                    "federal_tax": 90.0,
                    "tax_deductions": [
                        {"deduction_id": 101, "amount": 62.0},
                        {"deduction_id": 102, "amount": 14.5},
                        {"deduction_id": 103, "amount": 10.0},
                    ],
                },
            },
            {
                "id": 2,
                "employee_id": 10,
                "employee_id__employee_first_name": "Ava",
                "employee_id__employee_last_name": "Stone",
                "employee_id__ssn": "111-22-3333",
                "employee_id__email": "ava@example.com",
                "employee_id__badge_id": "E10",
                "employee_id__address": "44 Pine St",
                "employee_id__city": "Sacramento",
                "employee_id__state": "CA",
                "employee_id__zip": "95814",
                "start_date": date(2026, 1, 16),
                "end_date": date(2026, 1, 31),
                "gross_pay": 80000.0,
                "pay_head_data": {
                    "federal_tax": 45.0,
                    "tax_deductions": [
                        {"deduction_id": 101, "amount": 31.0},
                        {"deduction_id": 102, "amount": 7.25},
                        {"deduction_id": 103, "amount": 5.0},
                    ],
                },
            },
        ]

        mock_deduction.objects.filter.return_value.values.return_value = [
            {"id": 101, "title": "Social Security", "tax_reporting_type": None, "has_max_limit": True, "maximum_amount": 168600.0},
            {"id": 102, "title": "Medicare", "tax_reporting_type": None, "has_max_limit": False, "maximum_amount": None},
            {"id": 103, "title": "CA PIT", "tax_reporting_type": None, "has_max_limit": False, "maximum_amount": None},
        ]

        company = MagicMock()
        company.company = "CAC Payroll"
        company.address = "1 Market St"
        company.city = "San Francisco"
        company.state = "CA"
        company.zip = "94105"
        company.company_registration_number = "12-3456789"

        context = build_w2_w3_context(payslip_qs, company=company, year=2026)

        self.assertEqual(len(context["w2_rows"]), 1)
        row = context["w2_rows"][0]
        self.assertEqual(row["employee_ssn"], "111-22-3333")
        self.assertEqual(row["employee_first_name"], "Ava")
        self.assertEqual(row["employee_last_name"], "Stone")
        self.assertEqual(row["box_1_wages"], 180000.0)
        self.assertEqual(row["box_2_federal_income_tax"], 135.0)
        self.assertEqual(row["box_3_social_security_wages"], 168600.0)  # Capped!
        self.assertEqual(row["box_4_social_security_tax"], 93.0)
        self.assertEqual(row["box_5_medicare_wages"], 180000.0)
        self.assertEqual(row["box_6_medicare_tax"], 21.75)
        self.assertEqual(row["box_16_state_wages"], 180000.0)
        self.assertEqual(row["box_17_state_income_tax"], 15.0)

        w3 = context["w3_totals"]
        self.assertEqual(w3["employee_count"], 1)
        self.assertEqual(w3["box_1_wages"], 180000.0)
        self.assertEqual(w3["box_2_federal_income_tax"], 135.0)
        self.assertEqual(w3["box_3_social_security_wages"], 168600.0)  # Capped!
        self.assertEqual(w3["box_4_social_security_tax"], 93.0)
        self.assertEqual(w3["box_5_medicare_wages"], 180000.0)
        self.assertEqual(w3["box_6_medicare_tax"], 21.75)

    def test_generate_w2_and_w3_csv_use_stable_headers(self):
        context = {
            "w2_rows": [
                {
                    "tax_year": 2026,
                    "employer_ein": "12-3456789",
                    "employer_name": "CAC Payroll",
                    "employee_ssn": "111-22-3333",
                    "employee_first_name": "Ava",
                    "employee_last_name": "Stone",
                    "box_1_wages": 1500.0,
                    "box_2_federal_income_tax": 135.0,
                    "box_3_social_security_wages": 1500.0,
                    "box_4_social_security_tax": 93.0,
                    "box_5_medicare_wages": 1500.0,
                    "box_6_medicare_tax": 21.75,
                    "state_code": "CA",
                    "box_16_state_wages": 1500.0,
                    "box_17_state_income_tax": 15.0,
                    "box_14_label": "CASDI",
                    "box_14_amount": 0.0,
                }
            ],
            "w3_totals": {
                "tax_year": 2026,
                "employer_ein": "12-3456789",
                "employer_name": "CAC Payroll",
                "employee_count": 1,
                "box_1_wages": 1500.0,
                "box_2_federal_income_tax": 135.0,
                "box_3_social_security_wages": 1500.0,
                "box_4_social_security_tax": 93.0,
                "box_5_medicare_wages": 1500.0,
                "box_6_medicare_tax": 21.75,
                "box_16_state_wages": 1500.0,
                "box_17_state_income_tax": 15.0,
            },
        }

        w2_rows = list(csv.DictReader(io.StringIO(generate_w2_csv(context).decode("utf-8"))))
        w3_rows = list(csv.DictReader(io.StringIO(generate_w3_csv(context).decode("utf-8"))))

        self.assertEqual(w2_rows[0]["tax_year"], "2026")
        self.assertEqual(w2_rows[0]["employee_ssn"], "111-22-3333")
        self.assertEqual(w2_rows[0]["box_1_wages"], "1500.00")
        self.assertEqual(w2_rows[0]["box_14_label"], "CASDI")
        self.assertEqual(w3_rows[0]["employee_count"], "1")
        self.assertEqual(w3_rows[0]["box_4_social_security_tax"], "93.00")
