from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from payroll.models.models import Contract, Deduction, FilingStatus, Employee, Payslip
from payroll.models.tax_models import TaxBracket
from payroll.methods.tax_calc import calculate_taxable_amount
from employee.models import EmployeeWorkInformation
from base.models import Company
from unittest.mock import MagicMock
from horilla import horilla_middlewares

class FederalTaxW4Test(TestCase):
    def setUp(self):
        # Set up thread-local request to avoid selected_company session checks crashing save()
        from django.contrib.auth.models import AnonymousUser
        self.request = MagicMock()
        self.request.user = AnonymousUser()
        self.request.session = {"selected_company": "all"}
        horilla_middlewares._thread_locals.request = self.request

        # Create Company
        self.company = Company.objects.create(
            company="Test Company",
            address="123 Test St",
            country="USA",
            state="CA",
            city="Test City",
            zip="12345"
        )

        # Create Filing Status
        self.filing_status = FilingStatus.objects.create(
            filing_status="Married",
            based_on="gross_pay",
            company_id=self.company
        )

        # Create Tax Bracket: Flat 10% for range 0 to infinity (using high float to prevent None type comparison issues in tax_calc)
        TaxBracket.objects.create(
            filing_status_id=self.filing_status,
            min_income=0,
            max_income=999999999.0,
            tax_rate=10.0
        )

        # Create User & Employee
        self.user = User.objects.create_user(username="testuser", password="password")
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_work_info=EmployeeWorkInformation.objects.create(company_id=self.company)
        )

        # Create Contract
        self.contract = Contract.objects.create(
            contract_name="Test Contract",
            employee_id=self.employee,
            contract_start_date=date(2024, 1, 1),
            wage=52000,
            filing_status=self.filing_status,
            wage_type="monthly",
            contract_status="active"
        )

    def tearDown(self):
        if hasattr(horilla_middlewares._thread_locals, "request"):
            del horilla_middlewares._thread_locals.request

    def test_standard_tax(self):
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7) # 7 days
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0,
            total_allowance=0.0,
            allowances={"allowances": []}
        )
        self.assertAlmostEqual(tax, 100.0, delta=1.0)

    def test_tax_credit_step3(self):
        # Add $2000 Credit
        # Avoid direct create due to save() force_insert issue and M2M direct assignment prohibited
        d = Deduction(
            title="Federal Tax Credit",
            amount=2000.0,
            is_fixed=True
        )
        d.save()
        d.specific_employees.add(self.employee)
        d.save()

        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7)
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0,
            total_allowance=0.0,
            allowances={"allowances": []}
        )
        
        self.assertAlmostEqual(tax, 61.75, delta=1.0)
        self.assertTrue(tax < 100.0)

    def test_extra_withholding_step4c(self):
        # Add $50 Extra Withholding per period
        # Avoid direct create due to save() force_insert issue
        d = Deduction(
            title="Federal Extra Withholding",
            amount=50.0,
            is_fixed=True
        )
        d.save()
        d.specific_employees.add(self.employee)
        d.save()

        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7)
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0,
            total_allowance=0.0,
            allowances={"allowances": []}
        )
        
        self.assertAlmostEqual(tax, 150.0, delta=1.0)

    def test_additional_medicare_tax_high_earner(self):
        # Scenario: Married employee (Limit $250k)
        # Previous YTD: $249,000 (just under limit)
        # Current Pay: $2,000
        # Total YTD: $251,000
        # Excess: $1,000
        # Tax: $1,000 * 0.9% = $9.00
        
        # 1. Create a previous payslip (Confirmed)
        Payslip.objects.create(
            employee_id=self.employee,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            gross_pay=249000.0,
            status="confirmed",
            pay_head_data={} # Dummy
        )
        
        # 2. Run Calc for current period
        start_date = date(2024, 7, 1)
        end_date = date(2024, 7, 7) # 1 week
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=2000.0,
            gross_pay=2000.0,
            total_allowance=0.0,
            allowances={"allowances": []}
        )
        
        self.assertTrue(tax > 205.0)
        self.assertAlmostEqual(tax, 209.0, delta=1.0)
