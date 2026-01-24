
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
            # Form 941 (Rev. January 2024)
            "employer_name": "Name",
            "employer_ein": "EIN",
            "employer_address": "Address",
            "employer_city": "City", 
            "employer_state": "State",
            "employer_zip": "Zip",
            "tax_year": "Year",
            "quarter": "Quarter",
            # Standard lines
            "total_wages": "f1_2", # "Wages, tips, and other compensation"
            "federal_income_tax": "f1_3", # "Federal income tax withheld"
            "taxable_social_security_wages": "f1_5a1", # "Taxable social security wages"
            "taxable_social_security_tips": "f1_5b1", # "Taxable social security tips"
            "taxable_medicare_wages": "f1_5c1", # "Taxable Medicare wages & tips"
            "total_taxes_before_adjustments": "f1_6", # "Total taxes before adjustments"
            "total_taxes_after_adjustments": "f1_10", # "Total taxes after adjustments"
            "total_deposits": "f1_11", # "Total deposits"
        },
        "940": {
            # Form 940 (2023)
            "employer_name": "Name",
            "employer_ein": "EIN",
            "employer_address": "Address",
             # ... simplified for now
        },
        "DE9": {
            # CA DE 9
            "employer_name": "Business Name",
            "employer_account_number": "Account Number",
            "employer_address": "Address",
            "quarter": "Quarter",
            "year": "Year",
            "total_wages": "Total Wages", 
            "pit_wages": "PIT Wages",
            "pit_withheld": "PIT Withheld",
        },
        "DE9C": {
             # CA DE 9C (Continuation)
             "employer_name": "Business Name",
             "employer_account_number": "Account Number",
             "quarter_ended": "Quarter Ended", 
             # Employee Rows (handled dynamically in code roughly)
             # But for mapping we can put prefixes if needed, 
             # though the code logic might need to iterate 'SSN{i}', 'Name{i}'...
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


            # --- Dynamic Row Handling (for DE9C etc.) ---
            if "employees" in data and isinstance(data["employees"], list):
                employee_list = data["employees"]
                # We need to distribute these employees across the fields.
                # Assuming typical DE9C structure: rows are numbered 1..N
                
                # Iterate pages again or just find widgets by pattern
                for page in doc:
                    widgets = page.widgets()
                    if not widgets: continue

                    for widget in widgets:
                        name = widget.field_name
                        # Check for pattern like "SSN1", "Last Name1"
                        # We need to detect the index "1" and map to employee_list[0]
                        
                        import re
                        # Pattern: Any text followed by a number (and optional suffix)
                        # e.g. "SSN1", "First Name1", "Total Subject Wages1"
                        match = re.search(r"(\D+)(\d+)$", name)
                        if match:
                             field_prefix = match.group(1).strip()
                             row_index = int(match.group(2)) - 1 # 0-indexed
                             
                             if 0 <= row_index < len(employee_list):
                                 emp = employee_list[row_index]
                                 
                                 # Map prefix to data key
                                 # This mapping needs to be robust.
                                 # Based on inspection: "SSN", "First Name", "Last Name", "Total Subject Wages", "PIT Wages", "PIT Withheld"
                                 
                                 val = None
                                 if "SSN" in field_prefix:
                                     val = emp.get("ssn", "")
                                 elif "First Name" in field_prefix:
                                     val = emp.get("first_name", "")
                                 elif "Last Name" in field_prefix:
                                     val = emp.get("last_name", "")
                                 elif "MI" in field_prefix:
                                      val = "" # Middle Initial, blank for now
                                 elif "Subject Wages" in field_prefix:
                                      val = emp.get("total_wages", 0.0)
                                 elif "PIT Wages" in field_prefix:
                                      val = emp.get("pit_wages", 0.0)
                                 elif "PIT Withheld" in field_prefix:
                                      val = emp.get("pit_withheld", 0.0)
                                      
                                 if val is not None:
                                     widget.field_value = str(val)
                                     widget.update()
            
            # doc.save(output_path) # We want bytes
            return doc.write()
            
        except Exception as e:
            logger.exception(f"Error filling form {form_type}: {e}")
            raise
