
import os
import django
import sys

# Setup Django environment
sys.path.append('/app') 
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from payroll.models.models import Deduction, Employee, Contract
from payroll.models.tax_models import TaxBracket, FilingStatus

def diagnose():
    print("--- Diagnosing Payroll Configuration ---")
    
    # 1. Check CA State Tax Deduction
    ca_tax_deductions = Deduction.objects.filter(title__icontains="CA State Tax")
    print(f"Found {ca_tax_deductions.count()} 'CA State Tax' deductions.")
    
    for ded in ca_tax_deductions:
        print(f"\nDeduction: {ded.title} (ID: {ded.id})")
        print(f"  based_on: {ded.based_on}")
        print(f"  is_fixed: {ded.is_fixed}")
        print(f"  is_pretax: {ded.is_pretax}")
        print(f"  is_tax: {ded.is_tax}")
        print(f"  rate: {ded.rate}")
        
    # 2. Check Alice's Contract
    # Assuming 'Alice' is the name. Search for employee.
    employees = Employee.objects.filter(employee_first_name__icontains="Alice")
    if not employees.exists():
         employees = Employee.objects.all()[:1]
         print(f"Alice not found, checking first employee: {employees[0]}")
    
    for emp in employees:
        print(f"\nEmployee: {emp} (ID: {emp.id})")
        contract = Contract.objects.filter(employee_id=emp, contract_status="active").first()
        if contract:
            print(f"  Active Contract ID: {contract.id}")
            print(f"  CA Filing Status: {contract.ca_filing_status}")
            print(f"  CA Allowances: {contract.ca_allowances}")
            
            if contract.ca_filing_status:
                brackets = TaxBracket.objects.filter(filing_status_id=contract.ca_filing_status)
                print(f"  Tax Brackets for status {contract.ca_filing_status}: {brackets.count()} found.")
                for b in brackets:
                    print(f"    Min: {b.min_income}, Max: {b.max_income}, Rate: {b.tax_rate}")
        else:
            print("  No active contract found.")

if __name__ == "__main__":
    diagnose()
