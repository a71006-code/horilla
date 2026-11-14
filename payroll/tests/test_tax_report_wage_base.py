from datetime import date
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from payroll.methods.tax_reporting import calculate_tax_liability


class TaxReportWageBaseTests(SimpleTestCase):
    def test_reports_read_current_and_legacy_taxable_wage_payloads(self):
        check_period = date(2026, 1, 1)
        for saved_wages, expected in (
            (900.0, 900.0),
            ({"taxable_gross_pay": 900.0}, 900.0),
            (0.0, 0.0),
            ({"taxable_gross_pay": ""}, 0.0),
        ):
            with self.subTest(saved_wages=saved_wages):
                row = {
                    "id": 1,
                    "employee_id": 2,
                    "employee_id__employee_first_name": "Test",
                    "employee_id__employee_last_name": "Employee",
                    "start_date": check_period,
                    "end_date": check_period,
                    "gross_pay": 1000.0,
                    "basic_pay": 1000.0,
                    "pay_head_data": {
                        "taxable_gross_pay": saved_wages,
                        "tax_deductions": [{"deduction_id": 3, "amount": 0.0}],
                    },
                }
                selected = Mock()
                selected.exists.return_value = True
                selected.values.return_value = [row]
                with (
                    patch("payroll.methods.tax_reporting.Payslip") as payslips,
                    patch("payroll.methods.tax_reporting.Deduction") as deductions,
                ):
                    history = payslips.objects.filter.return_value
                    history.order_by.return_value.values.return_value = [row]
                    deductions.objects.filter.return_value.values.return_value = [
                        {
                            "id": 3,
                            "title": "Medicare",
                            "employer_rate": 1.45,
                            "based_on": "taxable_gross_pay",
                            "tax_reporting_type": "FICA_MED",
                            "has_max_limit": False,
                            "maximum_amount": None,
                        }
                    ]
                    result = calculate_tax_liability(selected)
                self.assertEqual(
                    result["form_aggregates"]["941"]["medicare_wages"], expected
                )
