from payroll.models import TaxBracket, FilingStatus

def fix_ca_tax_brackets():
    try:
        # Get CA Single Filing Status
        ca_status = FilingStatus.objects.filter(filing_status='CA Single 2026').first()
        if not ca_status:
            print("Error: 'CA Single 2026' filing status not found.")
            return

        print(f"Updating tax brackets for: {ca_status}")

        # Delete existing brackets for this status to ensure clean slate
        deleted_count, _ = TaxBracket.objects.filter(filing_status=ca_status).delete()
        print(f"Deleted {deleted_count} existing tax brackets.")

        # Define correct 2026 CA Method B brackets
        # (min_income, max_income, tax_rate)
        # Note: Enter tax_rate as percentage (e.g. 1.1), NOT decimal (0.011)
        brackets = [
            (0.00, 10756.00, 1.10),
            (10756.00, 25499.00, 2.20),
            (25499.00, 40243.00, 4.40),
            (40243.00, 55866.00, 6.60),
            (55866.00, 70611.00, 8.80),
            (70611.00, 361284.00, 10.23),
            (361284.00, 433539.00, 11.33),
            (433539.00, 722564.00, 12.43),
            (722564.00, None, 13.53), # Over 722k
        ]

        for min_inc, max_inc, rate in brackets:
            TaxBracket.objects.create(
                filing_status=ca_status,
                min_income=min_inc,
                max_income=max_inc,
                tax_rate=rate
            )
            print(f"Created bracket: {min_inc} - {max_inc} @ {rate}%")

        print("Successfully updated CA Tax Brackets.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fix_ca_tax_brackets()
