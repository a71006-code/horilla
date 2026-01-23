
import sys
import os
import django

sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from payroll.models.models import Deduction

def fix_deductions():
    # Fix Social Security - Employer
    ss_employer = Deduction.objects.filter(title__icontains='Social Security - Employer').first()
    if ss_employer:
        print(f"Fixing {ss_employer.title}...")
        ss_employer.is_fixed = False
        ss_employer.amount = 0.0 # Clear fixed amount
        ss_employer.save()
        print(f"Updated {ss_employer.title}: IsFixed={ss_employer.is_fixed}, Amount={ss_employer.amount}")

    # Fix Medicare - Employer
    med_employer = Deduction.objects.filter(title__icontains='Medicare - Employer').first()
    if med_employer:
        print(f"Fixing {med_employer.title}...")
        med_employer.is_fixed = False
        med_employer.amount = 0.0 # Clear fixed amount
        med_employer.save()
        print(f"Updated {med_employer.title}: IsFixed={med_employer.is_fixed}, Amount={med_employer.amount}")

if __name__ == "__main__":
    fix_deductions()
