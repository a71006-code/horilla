import os
import sys
import django
from django.conf import settings
from django.test import RequestFactory
from django.contrib.auth import get_user_model

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from report.views.payroll_report import download_tax_forms

def verify_pdf_generation():
    print("Verifying PDF generation...")
    User = get_user_model()
    # Find any user to act as logged in user
    user = User.objects.first()
    if not user:
        print("No user found! Cannot mock request.")
        return

    factory = RequestFactory()
    # Add some date params to ensure logic triggers
    request = factory.get('/report/download_tax_forms/?start_date_from=2024-01-01&start_date_till=2024-12-31')
    request.user = user
    request.session = {"selected_company": "all"}

    try:
        response = download_tax_forms(request)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            ctype = response.get('Content-Type')
            print(f"Content-Type: {ctype}")
            
            content_len = len(response.content)
            print(f"Content Length: {content_len} bytes")
            
            if content_len > 100: # Arbitrary small size check
                print("SUCCESS: PDF/ZIP content generated.")
            else:
                print("WARNING: Content size is very small.")
        else:
            print(f"FAILURE: Status code {response.status_code}")
            
    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_pdf_generation()
