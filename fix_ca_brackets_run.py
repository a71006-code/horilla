import os
import django
import math
import sys

# Setup Django environment
sys.path.append('/app')  # Adjust path if necessary
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from payroll.models.tax_models import TaxBracket
from payroll.models.models import FilingStatus

def fix_ca_brackets():
    print("Starting CA Tax Brackets Fix...")

    # 1. Get CA Single Filing Status
    ca_status = FilingStatus.objects.filter(filing_status='CA Single 2026').first()
    if not ca_status:
        print("❌ Error: 'CA Single 2026' Filing Status not found! Please create it first.")
        return

    print(f"✅ Found Filing Status: {ca_status}")

    # 2. Delete existing brackets
    # Note: Using filing_status_id as the field name based on model definition
    deleted_count, _ = TaxBracket.objects.filter(filing_status_id=ca_status).delete()
    print(f"🗑️  Deleted {deleted_count} existing brackets.")

    # 3. Create new brackets (linear list)
    # Rate is entered as PERCENTAGE (e.g. 1.1 for 1.1%)
    # Brackets based on 2026 CA Method B (approximate/user provided values)
    
    brackets_data = [
        (0.00, 10756.00, 1.10),
        (10756.00, 25499.00, 2.20),
        (25499.00, 40243.00, 4.40),
        (40243.00, 55866.00, 6.60),
        (55866.00, 70611.00, 8.80),
        (70611.00, 361284.00, 10.23),
        (361284.00, 433539.00, 11.33),
        (433539.00, 722564.00, 12.43),
        (722564.00, None, 13.53),
    ]

    for min_inc, max_inc, rate in brackets_data:
        # Handle None for infinity
        max_val = max_inc if max_inc is not None else -1 
        # Note: Model might be using math.inf or None. 
        # Looking at tax_models.py: "if self.max_income is None: self.max_income = math.inf" in clean()
        # But let's check what create expects.
        # Actually, let's pass None and let the model handle it or pass math.inf if we can.
        # However, passing None directly to FloatField might be an issue if null=True is not set or if it expects a number.
        # TaxBracket.max_income allows null=True.
        
        TaxBracket.objects.create(
            filing_status_id=ca_status,
            min_income=min_inc,
            max_income=max_inc,
            tax_rate=rate
        )
        print(f"   Created bracket: {min_inc} - {max_inc} @ {rate}%")

    print("✅ CA Tax Brackets Fixed Successfully!")

if __name__ == "__main__":
    fix_ca_brackets()
