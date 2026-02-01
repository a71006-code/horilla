import json
import zipfile
import io
from django.test import TestCase, RequestFactory
from unittest.mock import MagicMock, patch
from report.views.payroll_report import payroll_pivot, download_tax_forms
from datetime import date

class EmployerLiabilityReportTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_mock = MagicMock()
        self.user_mock.has_perm.return_value = True
        self.user_mock.is_authenticated = True

    @patch('report.views.payroll_report.Payslip')
    @patch('report.views.payroll_report.PayslipFilter')
    @patch('payroll.models.models.Deduction') 
    # Note: Deduction is imported inside the elif block in payroll_pivot usually, 
    # check import in views/payroll_report.py. Step 160 shows "from payroll.models.models import Deduction" inside the block.
    # So we need to patch specifically where it is imported or used.
    # Since it is a local import inside the function, patching 'payroll.models.models.Deduction' might work if the view imports it from there.
    # Or we can patch 'report.views.payroll_report.Deduction' if it was global. 
    # It is local. So we have to patch 'payroll.models.models.Deduction'.
    def test_employer_liability_pivot(self, MockDeduction, MockPayslipFilter, MockPayslip):
        # Setup Mock Data
        mock_qs = MagicMock()
        MockPayslip.objects.all.return_value = mock_qs
        
        # Mock Filter
        mock_filter = MagicMock()
        mock_filter.qs = mock_qs
        MockPayslipFilter.return_value = mock_filter # PayslipFilter(request.GET, queryset) returns this

        # Mock values() call for Payslip List
        mock_qs.values.return_value = [
            {
                "id": 1,
                "employee_id__employee_first_name": "John",
                "employee_id__employee_last_name": "Doe",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
                "basic_pay": 1000.0,
                "gross_pay": 1000.0,
                "status": "confirmed"
            }
        ]
        
        # Mock pay_head_data query (Payslip.objects.filter(...).values_list(...))
        # This is deeper: Payslip.objects.filter(id__in=...).values_list(...)
        # We need to ensure the chain returns the right thing.
        # Since we mocked Payslip.objects.all (or filter), we need to handle the chain.
        
        # MockDeduction query
        # Deduction.objects.filter(id__in=...).values(...)
        mock_deduction_qs = MagicMock()
        MockDeduction.objects.filter.return_value = mock_deduction_qs
        mock_deduction_qs.values.return_value = [
            {
                "id": 101,
                "title": "Employer Tax Test",
                "employer_rate": 10.0,
                "title": "Employer Tax Test",
                "employer_rate": 10.0,
                "based_on": "gross_pay",
                "tax_reporting_type": None,
                "has_max_limit": False,
                "maximum_amount": None
            }
        ]

        # We need to intercept the second Payslip query for pay_head_data
        # The view code does: Payslip.objects.filter(id__in=payslip_ids).values_list("id", "pay_head_data")
        # We can configure MockPayslip.objects.filter to return a mock that has values_list
        
        def side_effect_filter(*args, **kwargs):
            m = MagicMock()
            if 'id__in' in kwargs:
                 # This is likely the pay_head_data query if ids match, or deduction query
                 # Return list of (id, pay_head_data)
                 m.values_list.return_value = [
                     (1, {
                         "tax_deductions": [
                             {"deduction_id": 101, "title": "Employer Tax Test", "employer_contribution_rate": 10.0}
                         ]
                     })
                 ]
            return m

        MockPayslip.objects.filter.side_effect = side_effect_filter

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
    def test_download_tax_forms(self, MockFiller, MockCompany, MockPayslip):
        # Setup Mocks
        mock_qs = MagicMock()
        MockPayslip.objects.all.return_value = mock_qs
        
        # Mock Aggregation
        # payslips.aggregate(Sum("gross_pay")) -> {"gross_pay__sum": 5000}
        mock_qs.aggregate.return_value = {"gross_pay__sum": 5000.0, "deduction__sum": 100.0}
        
        # Mock Filler
        filler_instance = MockFiller.return_value
        filler_instance.fill_form.return_value = b"%PDF-1.4 Mock PDF Content"

        # Execute
        request = self.factory.get('/report/download-tax-forms')
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = download_tax_forms(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        
        # Verify ZIP
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            files = zf.namelist()
            self.assertIn("Form_941.pdf", files)
            content = zf.read("Form_941.pdf")
            self.assertEqual(content, b"%PDF-1.4 Mock PDF Content")

    @patch('report.views.payroll_report.Payslip')
    @patch('payroll.models.models.Deduction')
    @patch('report.views.payroll_report.PayslipFilter')
    def test_futa_limit_logic(self, MockPayslipFilter, MockDeduction, MockPayslip):
        # Scenario: 
        # Payslip 1: Jan, Gross 5000. FUTA Taxable = 5000.
        # Payslip 2: Feb, Gross 5000. Cum = 10000. Limit = 7000. Taxable = 2000.
        # We are reporting on Payslip 2.

        # 1. Mock Filter to return Payslip 2 only (Feb)
        mock_qs_filtered = MagicMock()
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
                "status": "confirmed"
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
                "title": "FUTA Tax",
                "employer_rate": 6.0,
                "based_on": "gross_pay",
                "tax_reporting_type": "FUTA",
                "has_max_limit": True,
                "maximum_amount": 7000.0
            }
        ]

        # 3. Mock Payslip Queries
        def side_effect_filter(*args, **kwargs):
            m = MagicMock()
            
            # A. pay_head_data query (id__in=[2])
            if 'id__in' in kwargs and 2 in kwargs['id__in']:
                 m.values_list.return_value = [
                     (2, {
                         "tax_deductions": [
                             {"deduction_id": 500, "title": "FUTA Tax", "amount": 0.0} # Employee pays 0
                         ]
                     })
                 ]
                 return m

            # B. history query (employee_id__in=[99])
            # We return BOTH payslips here to simulate history
            if 'employee_id__in' in kwargs:
                # values("id", "employee_id", "start_date", "gross_pay")
                from datetime import date
                m.values.return_value = [
                    {"id": 1, "employee_id": 99, "start_date": date(2024, 1, 1), "gross_pay": 5000.0},
                    {"id": 2, "employee_id": 99, "start_date": date(2024, 2, 1), "gross_pay": 5000.0},
                ]
                return m
            
            return m

        MockPayslip.objects.filter.side_effect = side_effect_filter

        # Execute
        request = self.factory.get('/report/payroll-pivot', {'model': 'employer_liability'})
        request.user = self.user_mock
        request.session = {'selected_company': 'all'}
        
        response = payroll_pivot(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        # Verify
        # Expected Liability:
        # Prior YTD (Jan) = 5000.
        # Limit = 7000.
        # Remaining Limit = 2000.
        # Current Gross = 5000.
        # Taxable = min(5000, 2000) = 2000.
        # Liability = 2000 * 6.0% = 120.0
        
        self.assertTrue(len(data) > 0)
        item = data[0]
        self.assertEqual(item['Tax Component'], "FUTA Tax")
        self.assertEqual(item['Employer Liability'], 120.0)

    @patch('report.views.payroll_report.Payslip')
    @patch('report.views.payroll_report.Company')
    @patch('report.forms.tax_forms.TaxFormFiller')
    @patch('payroll.models.models.Deduction')
    @patch('payroll.models.models.Payslip') # Patch model inside service
    def test_download_tax_forms_with_limits(self, MockModelPayslip, MockModelDeduction, MockFiller, MockCompany, MockViewPayslip):
        # Scenario: FUTA limit check for PDF generation
        # 1 Payslip with $10,000 wages. FUTA limit is $7,000. Rate 6%.
        # Liability should be 7000 * 0.06 = 420.0 (Not 600)
        
        # 1. Mock Payslip Query
        mock_qs = MagicMock()
        MockViewPayslip.objects.all.return_value = mock_qs
        # Filter returns same qs
        mock_qs.filter.return_value = mock_qs
        
        # Mock Data for Service
        # We need mock_qs.values(...) to return list
        mock_qs.values.return_value = [
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
        
        # 2. Mock View Payslip iterate
        p1 = MagicMock()
        p1.gross_pay = 10000.0
        p1.pay_head_data = {"tax_deductions": [{"deduction_id": 500, "amount": 0.0}]}
        p1.employee_id.id = 99
        p1.employee_id.ssn = "123"
        mock_qs.__iter__.return_value = [p1]

        # 3. Mock Deduction Logic (Service connects to DB)
        # Service uses Deduction.objects.filter...
        mock_ded_qs = MagicMock()
        MockModelDeduction.objects.filter.return_value = mock_ded_qs
        mock_ded_qs.values.return_value = [
             {
                 "id": 500,
                 "title": "FUTA Tax",
                 "employer_rate": 6.0,
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
        # We expect fill_form("940", data) where data["futa_liability"] == 420.0
        filler_mock = MockFiller.return_value
        
        # Find call args for '940'
        found = False
        for call in filler_mock.fill_form.call_args_list:
             args, kwargs = call
             if args[0] == "940":
                 data = args[1]
                 self.assertEqual(data["futa_liability"], 420.0, "FUTA Liability should be capped at 7000 * 6%")
                 self.assertEqual(data["total_futa_wages"], 7000.0, "FUTA Wages should be capped at 7000")
                 found = True
        
        self.assertTrue(found, "Form 940 was not filled")

