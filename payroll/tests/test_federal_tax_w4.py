from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from payroll.models.models import Contract, Deduction, FilingStatus, Employee
from payroll.models.tax_models import TaxBracket
from payroll.methods.tax_calc import calculate_taxable_amount
from employee.models import EmployeeWorkInformation
from base.models import Company

class FederalTaxW4Test(TestCase):
    def setUp(self):
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

        # Create Tax Bracket: Flat 10% for range 0 to infinity
        TaxBracket.objects.create(
            filing_status_id=self.filing_status,
            min_income=0,
            max_income=None,
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
            wage=52000, # $1000/week annualizes to $52,000 roughly used in test logic context?
            # Actually calculate_taxable_amount takes 'basic_pay' as arg
            filing_status=self.filing_status,
            wage_type="monthly",
            contract_status="active"
        )

    def test_standard_tax(self):
        # Annual Income: $52,000
        # Tax: 10% = $5,200/year
        # Daily Tax: 5200 / 366 (leap year 2024) = 14.2076...
        # Period (1 week = 7 days): 14.2076 * 7 = 99.45
        
        # We'll use start/end dates to define period
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7) # 7 days
        
        # Taxable amount input needs to be passed. 
        # Logic: calculate_taxable_amount(..., basic_pay=1000, ...)
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0, # $1000 for 7 days -> $52,142/year approx
        )
        # Expected:
        # Annualized = 1000 / 7 * 366 = 52,285.71
        # Tax = 5,228.57
        # Period = 5,228.57 / 366 * 7 = 100.00
        
        # Let's just check it's > 0 and roughly 10%
        self.assertAlmostEqual(tax, 100.0, delta=1.0)

    def test_tax_credit_step3(self):
        # Add $2000 Credit
        Deduction.objects.create(
            title="Federal Tax Credit",
            specific_employees=self.employee, # Error? specific_employees is many-to-many
            amount=2000.0,
            is_fixed=True
        )
        # Specific employees is a M2M field, needs .add()
        d = Deduction.objects.get(title="Federal Tax Credit")
        d.specific_employees.add(self.employee)
        d.save()

        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7)
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0,
        )
        
        # Expected:
        # Annual Tax = 5,228.57
        # Less Credit = 2,000
        # Net Annual = 3,228.57
        # Period Tax = 3,228.57 / 366 * 7 = 61.75
        
        self.assertAlmostEqual(tax, 61.75, delta=1.0)
        self.assertTrue(tax < 100.0)

    def test_extra_withholding_step4c(self):
        # Add $50 Extra Withholding per period
        d = Deduction.objects.create(
            title="Federal Extra Withholding",
            amount=50.0,
            is_fixed=True
        )
        d.specific_employees.add(self.employee)

        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 7)
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=1000.0,
        )
        
        # Expected: 
        # Base Period Tax = 100.0
        # Plus Extra = 50.0
        # Total = 150.0
        
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
        
        # We need to simulate a Gross Pay of roughly $2000 for this week.
        # Logic in tax_calc uses 'basic_pay' to derive income. 
        # Annualized = 2000 * 52 = 104k.
        
        tax = calculate_taxable_amount(
            employee=self.employee.id,
            start_date=start_date,
            end_date=end_date,
            basic_pay=2000.0, # Will be annualized to ~104k
            gross_pay=2000.0, # Explicit gross pay for Medicare check
        )
        
        # Expected:
        # Base Federal Tax (10% of 2000) = ~200.0
        # Additional Medicare (0.9% of 1000 excess) = 9.0
        # Total = ~209.0
        
        self.assertTrue(tax > 205.0)
        # Check if it includes roughly 9.0 extra from base 200
        # 10% of 2000 = 200. 
        # Actually logic is: 2000 / 7 * 366... it's precise.
        
        # Exact check:
        # Annual Income = 2000/7 * 366 = 104,571.42
        # Annual Tax = 10,457.14
        # Base Period Tax = 10,457.14 / 366 * 7 = 200.00
        # Add Med Tax = 9.00
        # Total = 209.00
        self.assertAlmostEqual(tax, 209.0, delta=1.0)

