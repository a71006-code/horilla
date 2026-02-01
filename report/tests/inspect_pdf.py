import fitz
import os
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

def inspect_form_fields(form_type="941"):
    base_dir = os.path.join(settings.BASE_DIR, "report", "static", "report", "forms")
    filename = f"f{form_type.lower()}.pdf"
    path = os.path.join(base_dir, filename)
    
    print(f"Inspecting: {path}")
    if not os.path.exists(path):
        print("File not found!")
        return

    doc = fitz.open(path)
    fields = []
    
    for page in doc:
        for widget in page.widgets():
            fields.append(f"Name: '{widget.field_name}', Value: '{widget.field_value}'")

    print(f"Found {len(fields)} fields:")
    for f in sorted(fields):
        print(f)

if __name__ == "__main__":
    inspect_form_fields("941")
