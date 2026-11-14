import json
import zipfile
import io
from django.test import TestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from unittest.mock import MagicMock, patch
from report.views.payroll_report import (
    download_tax_forms, download_w2_w3_csv, download_w2_w3_forms, payroll_pivot, preview_tax_form,
)
from datetime import date

class EmployerLiabilityReportTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_mock = MagicMock()
        self.user_mock.has_perm.return_value = True
        self.user_mock.is_authenticated = True
        self.user_mock.is_superuser = True

    def test_payslip_permission_alone_does_not_grant_tax_export_access(self):
        request = self.factory.get("/report/download-tax-forms")
        request.user = self.user_mock
        request.user.is_superuser = False
        request.session = {}
        for view in (download_tax_forms, preview_tax_form, download_w2_w3_csv, download_w2_w3_forms):
            with self.subTest(view=view), self.assertRaises(PermissionDenied):
                view(request)

    @patch('report.views.payroll_report.Payslip')
    @patch('report.views.payroll_report.PayslipFilter')
    @patch('payroll.methods.tax_reporting.Deduction')
    @patch('payroll.methods.tax_reporting.Payslip')
    def test_employer_liability_pivot(self, MockModelPayslip, MockDeduction, MockPayslipFilter, MockPayslip):
        # Setup Mock Data
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        MockPayslip.objects.all.return_value = mock_qs
        
        # Mock Filter
        mock_filter = MagicMock()
        mock_filter.qs = mock_qs
        MockPayslipFilter.return_value = mock_filter

        # Mock values() call for Payslip List
        mock_qs.values.return_value = [
            {
                "id": 1,
                "employee_id": 1,
                "employee_id__employee_first_name": "John",
                "employee_id__employee_last_name": "Doe",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
                "basic_pay": 1000.0,
                "gross_pay": 1000.0,
                "status": "confirmed",
                "pay_head_data": {
                    "tax_deductions": [
                        {"deduction_id": 101, "title": "Employer Tax Test", "amount": 0.0}
                    ]
                }
            }
        ]
        
        # MockDeduction query
        mock_deduction_qs = MagicMock()
        MockDeduction.objects.filter.return_value = mock_deduction_qs
        mock_deduction_qs.values.return_value = [
            {
                "id": 101,
                "title": "Employer Tax Test",
                "employer_rate": 10.0,
                "based_on": "gross_pay",
                "tax_reporting_type": None,
                "has_max_limit": False,
                "maximum_amount": None
            }
        ]

        # Mock Model Payslip history query
        def side_effect_filter(*args, **kwargs):
            m = MagicMock()
            if 'employee_id__in' in kwargs:
                 m.order_by.return_value.values.return_value = [
                     {"id": 1, "employee_id": 1, "start_date": date(2024, 1, 1), "gross_pay": 1000.0}
                 ]
                 return m
            return m
        MockModelPayslip.objects.filter.side_effect = side_effect_filter

        # Execute
        request = self.factory.get('/report/payroll-pivot', {'model': 'employer_liability'})
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = payroll_pivot(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Verify
        self.assertTrue(len(data) > 0)
        item = data[0]
        self.assertEqual(item['Tax Component'], "Employer Tax Test")
        self.assertEqual(item['Employer Liability'], 100.0) # 10% of 1000
        self.assertEqual(item['Rate'], "10.0%")

    @patch('report.views.payroll_report.Payslip')
    @patch('report.views.payroll_report.Company') # If imported in view
    @patch('report.forms.tax_forms.TaxFormFiller')
    @patch('payroll.methods.tax_reporting.Deduction')
    @patch('payroll.methods.tax_reporting.Payslip')
    def test_download_tax_forms(self, MockModelPayslip, MockDeduction, MockFiller, MockCompany, MockPayslip):
        # Setup Mocks
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        MockPayslip.objects.all.return_value = mock_qs
        
        # Mock Aggregation
        mock_qs.aggregate.return_value = {"gross_pay__sum": 5000.0, "deduction__sum": 100.0}
        
        # Mock Filler
        filler_instance = MockFiller.return_value
        filler_instance.fill_form.return_value = b"%PDF-1.4 Mock PDF Content"

        # Mock Company
        mock_company = MagicMock()
        mock_company.company = "Test Company"
        mock_company.address = "123 Test St"
        mock_company.city = "Test City"
        mock_company.state = "CA"
        mock_company.zip = "12345"
        mock_company.country = "USA"
        mock_company.company_registration_number = "12-3456789"
        MockCompany.objects.first.return_value = mock_company

        # Mock values() call for Payslip List
        def side_effect_values(*args, **kwargs):
            if "employee_id" in args and len(args) == 1:
                m = MagicMock()
                m.distinct.return_value.count.return_value = 1
                return m
            return [
                {
                    "id": 1,
                    "employee_id": 1,
                    "employee_id__employee_first_name": "John",
                    "employee_id__employee_last_name": "Doe",
                    "start_date": date(2024, 1, 1),
                    "end_date": date(2024, 1, 31),
                    "basic_pay": 5000.0,
                    "gross_pay": 5000.0,
                    "pay_head_data": {
                        "tax_deductions": [
                            {"deduction_id": 500, "title": "FUTA Tax", "amount": 0.0}
                        ]
                    }
                }
            ]
        mock_qs.values.side_effect = side_effect_values

        # Mock Model Payslip history
        def side_effect_filter(*args, **kwargs):
            m = MagicMock()
            if 'employee_id__in' in kwargs:
                m.order_by.return_value.values.return_value = [
                    {"id": 1, "employee_id": 1, "start_date": date(2024, 1, 1), "gross_pay": 5000.0}
                ]
                return m
            return m
        MockModelPayslip.objects.filter.side_effect = side_effect_filter

        # Mock Deduction query
        mock_deduction_qs = MagicMock()
        MockDeduction.objects.filter.return_value = mock_deduction_qs
        mock_deduction_qs.values.return_value = [
            {
                "id": 500,
                "title": "FUTA Tax",
                "employer_rate": 6.0,
                "based_on": "gross_pay",
                "tax_reporting_type": "FUTA",
                "has_max_limit": True,
                "maximum_amount": 7000.0
            }
        ]

        # Execute
        request = self.factory.get('/report/download-tax-forms')
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = download_tax_forms(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn("no-store", response["Cache-Control"])
        
        # Verify ZIP
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            files = zf.namelist()
            self.assertIn("Form_941.pdf", files)
            content = zf.read("Form_941.pdf")
            self.assertEqual(content, b"%PDF-1.4 Mock PDF Content")

    @patch('report.views.payroll_report.Payslip')
    @patch('payroll.methods.tax_reporting.Deduction')
    @patch('report.views.payroll_report.PayslipFilter')
    @patch('payroll.methods.tax_reporting.Payslip')
    def test_futa_limit_logic(self, MockModelPayslip, MockPayslipFilter, MockDeduction, MockPayslip):
        # Scenario: 
        # Payslip 1: Jan, Gross 5000. FUTA Taxable = 5000.
        # Payslip 2: Feb, Gross 5000. Cum = 10000. Limit = 7000. Taxable = 2000.
        # We are reporting on Payslip 2.

        # 1. Mock Filter to return Payslip 2 only (Feb)
        mock_qs_filtered = MagicMock()
        mock_qs_filtered.exists.return_value = True
        mock_qs_filtered.values.return_value = [
            {
                "id": 2,
                "employee_id": 99,
                "employee_id__employee_first_name": "Test",
                "employee_id__employee_last_name": "User",
                "start_date": date(2024, 2, 1),
                "end_date": date(2024, 2, 29),
                "basic_pay": 5000.0,
                "gross_pay": 5000.0,
                "status": "confirmed",
                "pay_head_data": {
                    "tax_deductions": [
                        {"deduction_id": 500, "title": "FUTA Tax", "amount": 0.0}
                    ]
                }
            }
        ]
        MockPayslipFilter.return_value.qs = mock_qs_filtered

        # 2. Mock Deduction (FUTA)
        mock_deduction_qs = MagicMock()
        MockDeduction.objects.filter.return_value = mock_deduction_qs
        mock_deduction_qs.values.return_value = [
            {
                "id": 500,
                "title": "FUTA Tax",
                "employer_rate": 6.0,
                "based_on": "gross_pay",
                "tax_reporting_type": "FUTA",
                "has_max_limit": True,
                "maximum_amount": 7000.0
            }
        ]

        # 3. Mock Model Payslip history query
        def side_effect_filter(*args, **kwargs):
            m = MagicMock()
            if 'employee_id__in' in kwargs:
                from datetime import date
                m.order_by.return_value.values.return_value = [
                    {"id": 1, "employee_id": 99, "start_date": date(2024, 1, 1), "gross_pay": 5000.0},
                    {"id": 2, "employee_id": 99, "start_date": date(2024, 2, 1), "gross_pay": 5000.0},
                ]
                return m
            return m
        MockModelPayslip.objects.filter.side_effect = side_effect_filter

        # Execute
        request = self.factory.get('/report/payroll-pivot', {'model': 'employer_liability'})
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = payroll_pivot(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        # Verify
        self.assertTrue(len(data) > 0)
        item = data[0]
        self.assertEqual(item['Tax Component'], "FUTA Tax")
        self.assertEqual(item['Employer Liability'], 120.0)

    @patch('report.views.payroll_report.Payslip')
    @patch('report.views.payroll_report.Company')
    @patch('report.forms.tax_forms.TaxFormFiller')
    @patch('payroll.methods.tax_reporting.Deduction')
    @patch('payroll.methods.tax_reporting.Payslip') # Patch model inside service
    def test_download_tax_forms_with_limits(self, MockModelPayslip, MockModelDeduction, MockFiller, MockCompany, MockViewPayslip):
        # Scenario: FUTA limit check for PDF generation
        # 1 Payslip with $10,000 wages. FUTA limit is $7,000. Rate 6%.
        # Liability should be 7000 * 0.06 = 420.0 (Not 600)
        
        # 1. Mock Payslip Query
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        MockViewPayslip.objects.all.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs

        # Mock Company
        mock_company = MagicMock()
        mock_company.company = "Test Company"
        mock_company.address = "123 Test St"
        mock_company.city = "Test City"
        mock_company.state = "CA"
        mock_company.zip = "12345"
        mock_company.country = "USA"
        mock_company.company_registration_number = "12-3456789"
        MockCompany.objects.first.return_value = mock_company

        # Mock Filler
        filler_instance = MockFiller.return_value
        filler_instance.fill_form.return_value = b"%PDF-1.4 Mock PDF Content"
        
        # Mock Data for Service
        def side_effect_values(*args, **kwargs):
            if "employee_id" in args and len(args) == 1:
                m = MagicMock()
                m.distinct.return_value.count.return_value = 1
                return m
            return [
                 {
                     "id": 1,
                     "employee_id": 99,
                     "employee_id__employee_first_name": "Test",
                     "employee_id__employee_last_name": "User",
                     "start_date": date(2024, 1, 1),
                     "end_date": date(2024, 1, 31),
                     "gross_pay": 10000.0,
                     "basic_pay": 10000.0,
                     "pay_head_data": {
                          "tax_deductions": [{"deduction_id": 500, "amount": 0.0}]
                     }
                 }
            ]
        mock_qs.values.side_effect = side_effect_values
        
        # 2. Mock View Payslip iterate
        p1 = MagicMock()
        p1.gross_pay = 10000.0
        p1.pay_head_data = {"tax_deductions": [{"deduction_id": 500, "amount": 0.0}]}
        p1.employee_id.id = 99
        p1.employee_id.ssn = "123"
        mock_qs.__iter__.return_value = [p1]

        # 3. Mock Deduction Logic (Service connects to DB)
        mock_ded_qs = MagicMock()
        MockModelDeduction.objects.filter.return_value = mock_ded_qs
        mock_ded_qs.values.return_value = [
             {
                 "id": 500,
                 "title": "FUTA Tax",
                 "employer_rate": 6.0,
                 "based_on": "gross_pay",
                 "tax_reporting_type": "FUTA",
                 "has_max_limit": True,
                 "maximum_amount": 7000.0
             }
        ]

        # 4. Mock History (Service connects to DB)
        MockModelPayslip.objects.filter.return_value.order_by.return_value.values.return_value = [] # No prior history

        # Execute
        request = self.factory.get('/report/download-tax-forms')
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = download_tax_forms(request)
        self.assertEqual(response.status_code, 200)

        # Verify calls to Filler
        filler_mock = MockFiller.return_value
        found = False
        for call in filler_mock.fill_form.call_args_list:
             args, kwargs = call
             if args[0] == "940":
                 data = args[1]
                 self.assertEqual(data["futa_liability_dollars"], "420", "FUTA Liability dollars should be capped at 7000 * 6%")
                 self.assertEqual(data["futa_liability_cents"], "00", "FUTA Liability cents should be 00")
                 self.assertEqual(data["total_futa_wages_dollars"], "7000", "FUTA Wages dollars should be capped at 7000")
                 self.assertEqual(data["total_futa_wages_cents"], "00", "FUTA Wages cents should be 00")
                 found = True
        
        self.assertTrue(found, "Form 940 was not filled")
