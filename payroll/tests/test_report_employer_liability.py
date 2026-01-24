import json
import zipfile
import io
from django.test import TestCase, RequestFactory
from unittest.mock import MagicMock, patch
from report.views.payroll_report import payroll_pivot, download_tax_forms

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
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
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
                "based_on": "gross_pay"
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
    @patch('report.views.payroll_report.TaxFormFiller')
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
