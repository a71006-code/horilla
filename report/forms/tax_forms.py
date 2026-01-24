
import os
import logging
import fitz  # PyMuPDF
from django.conf import settings

logger = logging.getLogger(__name__)

class TaxFormFiller:
    """
    Handles filling of PDF tax forms using PyMuPDF.
    """
    
    FORM_MAPPINGS = {
        "941": {
            # Map internal data keys to PDF field names
            # Example mapping based on standard IRS Form 941 (2024/2025)
            # These field names must be verified against the actual PDF template widget names.
            "employer_name": "Name",
            "employer_ein": "EIN",
            "employer_address": "Address",
            "total_wages": "f1_1", # Wages, tips, other compensation
            "federal_income_tax": "f1_2", # Federal income tax withheld
            "taxable_social_security_wages": "f1_5a_c1", # Column 1
            "taxable_social_security_tips": "f1_5b_c1",
            "taxable_medicare_wages": "f1_5c_c1",
            # ... add more mappings as needed based on actual PDF inspection
        },
        "940": {
            "employer_name": "Name",
            "employer_ein": "EIN",
            # ...
        },
        "DE9": {
             # California DE 9
        },
        "DE9C": {
             # California DE 9C
        }
    }

    def __init__(self, forms_dir=None):
        if forms_dir:
            self.forms_dir = forms_dir
        else:
            # Default to report/static/report/forms/
            self.forms_dir = os.path.join(settings.BASE_DIR, "report", "static", "report", "forms")

    def fill_form(self, form_type, data):
        """
        Fills a PDF form of the specified type with the provided data.
        
        Args:
            form_type (str): "941", "940", "DE9", or "DE9C"
            data (dict): Dictionary containing data to populate the form.
            
        Returns:
            bytes: The filled PDF content as bytes.
        """
        filename = f"f{form_type.lower()}.pdf" # e.g., f941.pdf
        form_path = os.path.join(self.forms_dir, filename)
        
        if not os.path.exists(form_path):
            logger.error(f"PDF template not found at {form_path}")
            # Identify missing template gracefully?
            # For now return None or raise error
            raise FileNotFoundError(f"Template for Form {form_type} not found.")

        try:
            doc = fitz.open(form_path)
            # Iterate through pages? Usually form fields are document-wide in PyMuPDF's new versions,
            # but sometimes access via page.
            
            # Use page 0 for simplified single page forms or iterate
            for page in doc:
                # Get existing widgets
                widgets = page.widgets()
                if not widgets:
                    continue
                
                # We can also use doc.get_form_text_fields() to see names?
                # But to set, we iterate widgets usually or use dedicated method?
                pass 
            
            # PyMuPDF typical filling approach:
            # Find widget by name and set value.
            
            mapping = self.FORM_MAPPINGS.get(form_type, {})
            
            for page in doc:
                widgets = page.widgets()
                for widget in widgets:
                    # check if widget name is in our data/mapping
                    # Widget name might need normalization
                    field_name = widget.field_name
                    
                    # Check if we have data for this field directly
                    if field_name in data:
                        widget.field_value = str(data[field_name])
                        widget.update()
                        continue
                    
                    # Check mapping
                    # Inverted mapping check (Value -> Key) or usually we iterate our data and find widget?
                    # Better to iterate widgets and lookup.
                    
                    # Reverse lookup in mapping? 
                    # Actually mapping is Internal Key -> PDF Field Name.
                    # So we iterate our data, find the PDF Field Name, then find the widget?
                    # No, that's slow.
                    
                    # Let's create a map PDF_NAME -> VALUE using `mapping` and `data`
                    
                    value_to_set = None
                    
                    # 1. Check if mapping has this field_name as a value
                    for internal_key, pdf_key in mapping.items():
                        if pdf_key == field_name and internal_key in data:
                            value_to_set = data[internal_key]
                            break
                    
                    if value_to_set is not None:
                         widget.field_value = str(value_to_set)
                         widget.update()
            
            # doc.save(output_path) # We want bytes
            return doc.write()
            
        except Exception as e:
            logger.exception(f"Error filling form {form_type}: {e}")
            raise
