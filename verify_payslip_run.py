import sys
import os
import django
from datetime import date

# Setup Django
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from employee.models import Employee
from payroll.views.component_views import payroll_calculation
from payroll.models.models import Deduction

def verify():
    # 1. Find Alice
    alice = Employee.objects.filter(employee_first_name__icontains="Alice").first()
    if not alice:
        print("❌ Alice not found!")
        return

    print(f"✅ Found Employee: {alice}")

    # 2. Define Period (Feb 2026 as per user context)
    start_date = date(2026, 2, 1)
    end_date = date(2026, 2, 28)

    # 3. Run Calculation
    print(f"Running payroll calculation for {start_date} - {end_date}...")
    try:
        data = payroll_calculation(alice, start_date, end_date)
    except Exception as e:
        print(f"❌ Error during calculation: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. Verify CA Tax
    print("\n--- Tax Deductions ---")
    ca_tax_found = False
    for d in data['tax_deductions']:
        print(f"Description: {d['title']} | Amount: {d['amount']}")
        if "CA" in d['title'] or "California" in d['title']:
            ca_tax_found = True
            if 250 < d['amount'] < 270:
                print(f"✅ CA Tax Amount Verified: {d['amount']} (Target ~$260)")
            else:
                 print(f"❌ CA Tax Amount Mismatch: {d['amount']} (Target ~$260)")

    if not ca_tax_found:
        print("❌ CA Tax Deduction NOT found in result!")

    # 5. Verify Employer Rates (Database check)
    print("\n--- Employer Rates Verification ---")
    # Using first() might pick the wrong one if there are duplicates, filtering by rate range helps confirm correctness
    ss_list = Deduction.objects.filter(title__icontains="Social Security")
    for ss in ss_list:
        print(f"Social Security: {ss.title} Rate: {ss.employer_rate}%")
        if ss.employer_rate == 6.2:
             print("✅ Correct Rate Found")

    med_list = Deduction.objects.filter(title__icontains="Medicare")
    for med in med_list:
        print(f"Medicare: {med.title} Rate: {med.employer_rate}%")
        if med.employer_rate == 1.45:
             print("✅ Correct Rate Found")

if __name__ == "__main__":
    verify()
