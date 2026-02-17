
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
            # Form 941 (Rev. 2026/2024 XFA) - CORRECTED PATHS based on dump
            "employer_ein": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_1[0]",
            "employer_name": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_2[0]",
            "employer_address": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_4[0]", # Street
            "employer_city": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_6[0]",
            "employer_state": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_7[0]",
            "employer_zip": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_8[0]",
            
            # Line 2: Wages, tips, other compensation
            "total_wages": "topmostSubform[0].Page1[0].f1_12[0]",
            # Line 3: Federal income tax withheld
            "federal_income_tax": "topmostSubform[0].Page1[0].f1_13[0]",
            # Line 5a: Taxable social security wages (Column 1)
            "taxable_social_security_wages": "topmostSubform[0].Page1[0].f1_14[0]",
            # Line 5c: Taxable Medicare wages (Column 1)
            "taxable_medicare_wages": "topmostSubform[0].Page1[0].f1_18[0]",
        },
        "940": {
            # Form 940 (2023)
            # XFA paths based on inspection
            "employer_name": "topmostSubform[0].Page1[0].EmployerName[0].f1_2[0]",
            "employer_ein": "topmostSubform[0].Page1[0].EIN[0].f1_4[0]",
            "employer_address": "topmostSubform[0].Page1[0].Address[0].f1_5[0]",
            "employer_city": "topmostSubform[0].Page1[0].City[0].f1_6[0]",
            "employer_state": "topmostSubform[0].Page1[0].State[0].f1_7[0]", 
            "employer_zip": "topmostSubform[0].Page1[0].Zip[0].f1_8[0]",
            "futa_liability": "topmostSubform[0].Page1[0].f1_38[0]", # Line 12 Total FUTA Tax
        },
        "DE9": {
            # CA DE 9 (AcroForm - Simple Names)
            "employer_name": "Business Name",
            "employer_account_number": "Employer Account No", # Note: "No" vs "Number"
            "employer_address": "Address",
            "employer_city": "City",
            "employer_state": "State", 
            "employer_zip": "ZIP Code",
            "quarter": "Quarter",
            "year": "Year",
            "total_wages": "Total Subject Wages", 
            "pit_wages": "PIT Wages",
            "pit_withheld": "PIT Withheld",
        },
        "DE9C": {
             # CA DE 9C (Continuation)
             "employer_name": "Business Name",
             "employer_account_number": "Employer Account No",
             "quarter_ended": "Quarter Ended", 
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
            raise FileNotFoundError(f"Template for Form {form_type} not found at {form_path}")

        try:
            doc = fitz.open(form_path)
            mapping = self.FORM_MAPPINGS.get(form_type, {})
            
            filled_fields = 0
            
            for page in doc:
                widgets = page.widgets()
                if not widgets: continue
                
                for widget in widgets:
                    field_name = widget.field_name
                    val_to_set = None

                    # Strategy 1: Direct Match (Data Key == PDF Field Name)
                    if field_name in data:
                        val_to_set = data[field_name]

                    # Strategy 2: Mapping Match (Internal Key -> PDF Field Name)
                    if val_to_set is None:
                        for internal_key, pdf_key in mapping.items():
                            if pdf_key == field_name and internal_key in data:
                                val_to_set = data[internal_key]
                                break
                    
                    # Strategy 3: Simple Name Fallback
                    if val_to_set is None:
                        for internal_key, pdf_key in mapping.items():
                             if field_name == pdf_key.split('.')[-1].replace('[0]', ''):
                                 if internal_key in data:
                                     val_to_set = data[internal_key]
                                     break
                    
                    # Strategy 4: DE9C Dynamic Rows
                    if val_to_set is None and "employees" in data:
                        import re
                        match = re.search(r"(\D+)(\d+)$", field_name)
                        if match:
                             field_prefix = match.group(1).strip()
                             row_index = int(match.group(2)) - 1
                             employee_list = data["employees"]
                             
                             if 0 <= row_index < len(employee_list):
                                 emp = employee_list[row_index]
                                 if "SSN" in field_prefix: val_to_set = emp.get("ssn", "")
                                 elif "First Name" in field_prefix: val_to_set = emp.get("first_name", "")
                                 elif "Last Name" in field_prefix: val_to_set = emp.get("last_name", "")
                                 elif "Subject Wages" in field_prefix: val_to_set = emp.get("total_wages", 0.0)
                                 elif "PIT Wages" in field_prefix: val_to_set = emp.get("pit_wages", 0.0)
                                 elif "PIT Withheld" in field_prefix: val_to_set = emp.get("pit_withheld", 0.0)

                    if val_to_set is not None:
                        widget.field_value = str(val_to_set)
                        widget.update()
                        filled_fields += 1
            
            logger.info(f"Filled {filled_fields} fields for {form_type}")
            return doc.write()
            
        except Exception as e:
            logger.exception(f"Error filling form {form_type}: {e}")
            raise
