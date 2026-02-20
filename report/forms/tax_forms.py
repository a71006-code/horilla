
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
            # Form 941 (Rev. March 2026) - UPDATED FOR MARCH 2026 DRAFT (XFA Mapping)
            "employer_ein_part1": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_1[0]",
            "employer_ein_part2": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_2[0]",
            "employer_name": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_3[0]",
            "employer_trade_name": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_4[0]",
            
            # Address Mapping Corrected for March 2026 Draft
            "employer_address_number": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_5[0]",
            "employer_address_street": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_6[0]",
            "employer_address_suite": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_7[0]",
            "employer_city": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_8[0]",
            "employer_state": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_9[0]",
            "employer_zip": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_10[0]",
            "foreign_country": "topmostSubform[0].Page1[0].Header[0].EntityArea[0].f1_11[0]",
            
            # Quarter Checkboxes (c1_1[0-3])
            "quarter_1": "topmostSubform[0].Page1[0].Header[0].ReportForQuarter[0].c1_1[0]",
            "quarter_2": "topmostSubform[0].Page1[0].Header[0].ReportForQuarter[0].c1_1[1]",
            "quarter_3": "topmostSubform[0].Page1[0].Header[0].ReportForQuarter[0].c1_1[2]",
            "quarter_4": "topmostSubform[0].Page1[0].Header[0].ReportForQuarter[0].c1_1[3]",

            # Line 1: Number of employees (Single field)
            "employee_count": "topmostSubform[0].Page1[0].f1_12[0]",
            
            # Line 2: Wages (Uses f1_13/f1_14 - split into dollars and cents)
            "total_wages_dollars": "topmostSubform[0].Page1[0].f1_13[0]",
            "total_wages_cents": "topmostSubform[0].Page1[0].f1_14[0]",
            
            # Line 3: FIT (Uses f1_15/f1_16)
            "federal_income_tax_dollars": "topmostSubform[0].Page1[0].f1_15[0]",
            "federal_income_tax_cents": "topmostSubform[0].Page1[0].f1_16[0]",
            
            # Line 5a: SS Wages (Col 1: f1_17/18, Col 2: f1_19/20)
            "taxable_social_security_wages_dollars": "topmostSubform[0].Page1[0].f1_17[0]",
            "taxable_social_security_wages_cents": "topmostSubform[0].Page1[0].f1_18[0]",
            "taxable_social_security_tax_dollars": "topmostSubform[0].Page1[0].f1_19[0]",
            "taxable_social_security_tax_cents": "topmostSubform[0].Page1[0].f1_20[0]",
            
            # Line 5c: Medicare (Col 1: f1_21/22, Col 2: f1_23/24)
            "taxable_medicare_wages_dollars": "topmostSubform[0].Page1[0].f1_21[0]",
            "taxable_medicare_wages_cents": "topmostSubform[0].Page1[0].f1_22[0]",
            "taxable_medicare_tax_dollars": "topmostSubform[0].Page1[0].f1_23[0]",
            "taxable_medicare_tax_cents": "topmostSubform[0].Page1[0].f1_24[0]",
            
            # Line 5e: Total SS and Medicare Tax (f1_33/34)
            "total_social_security_and_medicare_tax_dollars": "topmostSubform[0].Page1[0].f1_33[0]",
            "total_social_security_and_medicare_tax_cents": "topmostSubform[0].Page1[0].f1_34[0]",
            
            # Line 6: Total Taxes (f1_37/38)
            "total_taxes_before_adjustments_dollars": "topmostSubform[0].Page1[0].f1_37[0]",
            "total_taxes_before_adjustments_cents": "topmostSubform[0].Page1[0].f1_38[0]",

            # Line 10: Total taxes after adjustments (f1_45/46)
            "total_taxes_after_adjustments_dollars": "topmostSubform[0].Page1[0].f1_45[0]",
            "total_taxes_after_adjustments_cents": "topmostSubform[0].Page1[0].f1_46[0]",

            # Line 12: Total taxes after adjustments and credits (f1_49/50)
            "total_taxes_after_credits_dollars": "topmostSubform[0].Page1[0].f1_49[0]",
            "total_taxes_after_credits_cents": "topmostSubform[0].Page1[0].f1_50[0]",

            # Line 13: Total Deposits (f1_51/52)
            "total_deposits_dollars": "topmostSubform[0].Page1[0].f1_51[0]",
            "total_deposits_cents": "topmostSubform[0].Page1[0].f1_52[0]",

            # Line 14: Balance Due (f1_53/54)
            "balance_due_dollars": "topmostSubform[0].Page1[0].f1_53[0]",
            "balance_due_cents": "topmostSubform[0].Page1[0].f1_54[0]",

            # Page 2 Header Continuation
            "employer_name_page2": "topmostSubform[0].Page2[0].Name_ReadOrder[0].f1_3[0]",
            "employer_ein_page2_part1": "topmostSubform[0].Page2[0].EIN_Number[0].f1_1[0]",
            "employer_ein_page2_part2": "topmostSubform[0].Page2[0].EIN_Number[0].f1_2[0]",

            # Part 2: Deposit Schedule
            "deposit_schedule_line12_less_2500": "topmostSubform[0].Page2[0].c2_1[0]",
            "deposit_schedule_monthly": "topmostSubform[0].Page2[0].c2_1[1]",
            "deposit_schedule_semiweekly": "topmostSubform[0].Page2[0].c2_1[2]",
            "month_1_tax_liability_dollars": "topmostSubform[0].Page2[0].f2_1[0]",
            "month_1_tax_liability_cents": "topmostSubform[0].Page2[0].f2_2[0]",
            "month_2_tax_liability_dollars": "topmostSubform[0].Page2[0].f2_3[0]",
            "month_2_tax_liability_cents": "topmostSubform[0].Page2[0].f2_4[0]",
            "month_3_tax_liability_dollars": "topmostSubform[0].Page2[0].f2_5[0]",
            "month_3_tax_liability_cents": "topmostSubform[0].Page2[0].f2_6[0]",
            "quarter_total_tax_liability_dollars": "topmostSubform[0].Page2[0].f2_7[0]",
            "quarter_total_tax_liability_cents": "topmostSubform[0].Page2[0].f2_8[0]",

            # Part 3: About Your Business
            "business_closed_or_stopped_paying_wages": "topmostSubform[0].Page2[0].c2_2[0]",
            "final_date_wages_paid": "topmostSubform[0].Page2[0].f2_9[0]",
            "seasonal_employer": "topmostSubform[0].Page2[0].c2_3[0]",

            # Part 4: Third-Party Designee
            "third_party_designee_yes": "topmostSubform[0].Page2[0].c2_4[0]",
            "third_party_designee_name": "topmostSubform[0].Page2[0].f2_10[0]",
            "third_party_designee_phone": "topmostSubform[0].Page2[0].f2_11[0]",
            "third_party_designee_pin": "topmostSubform[0].Page2[0].f2_12[0]",
            "third_party_designee_no": "topmostSubform[0].Page2[0].c2_4[1]",

            # Part 5: Signature / Paid Preparer
            "signer_name": "topmostSubform[0].Page2[0].f2_13[0]",
            "signer_title": "topmostSubform[0].Page2[0].f2_14[0]",
            "signer_daytime_phone": "topmostSubform[0].Page2[0].f2_15[0]",
            "paid_preparer_self_employed": "topmostSubform[0].Page2[0].c2_5[0]",
            "paid_preparer_name": "topmostSubform[0].Page2[0].f2_16[0]",
            "paid_preparer_ptin": "topmostSubform[0].Page2[0].f2_17[0]",
            "paid_preparer_firm_name": "topmostSubform[0].Page2[0].f2_18[0]",
            "paid_preparer_ein": "topmostSubform[0].Page2[0].f2_19[0]",
            "paid_preparer_address": "topmostSubform[0].Page2[0].f2_20[0]",
            "paid_preparer_phone": "topmostSubform[0].Page2[0].f2_21[0]",
            "paid_preparer_city": "topmostSubform[0].Page2[0].f2_22[0]",
            "paid_preparer_state": "topmostSubform[0].Page2[0].f2_23[0]",
            "paid_preparer_zip": "topmostSubform[0].Page2[0].f2_24[0]",

            # --- Form 941-V (Payment Voucher) ---
            "voucher_ein_part1": "topmostSubform[0].Page3[0].EIN_Number[0].f1_1[0]",
            "voucher_ein_part2": "topmostSubform[0].Page3[0].EIN_Number[0].f1_2[0]",
            "voucher_amount_dollars": "topmostSubform[0].Page3[0].f4_2[0]",
            "voucher_amount_cents": "topmostSubform[0].Page3[0].f4_3[0]",
            "voucher_q1": "topmostSubform[0].Page3[0].Line3_ReadOrder[0].c4_1[0]",
            "voucher_q2": "topmostSubform[0].Page3[0].Line3_ReadOrder[0].c4_1[1]",
            "voucher_q3": "topmostSubform[0].Page3[0].Line3_ReadOrder[0].c4_1[2]",
            "voucher_q4": "topmostSubform[0].Page3[0].Line3_ReadOrder[0].c4_1[3]",
            "voucher_business_name": "topmostSubform[0].Page3[0].f1_3[0]",
            "voucher_address": "topmostSubform[0].Page3[0].f4_5[0]",
            "voucher_city_state_zip": "topmostSubform[0].Page3[0].f4_6[0]",
        },
        "940": {
            # Form 940 (2023)
            # XFA paths based on inspection
            "employer_name": "topmostSubform[0].Page1[0].EmployerName[0].f1_2[0]",
            "employer_ein_part1": "topmostSubform[0].Page1[0].EIN[0].f1_3[0]",
            "employer_ein_part2": "topmostSubform[0].Page1[0].EIN[0].f1_4[0]",
            "employer_address": "topmostSubform[0].Page1[0].Address[0].f1_5[0]",
            "employer_city": "topmostSubform[0].Page1[0].City[0].f1_6[0]",
            "employer_state": "topmostSubform[0].Page1[0].State[0].f1_7[0]", 
            "employer_zip": "topmostSubform[0].Page1[0].Zip[0].f1_8[0]",
            
            # Line 3: Total wages (Col 1: f1_17/18)
            "total_wages_dollars": "topmostSubform[0].Page1[0].f1_17[0]",
            "total_wages_cents": "topmostSubform[0].Page1[0].f1_18[0]",

            # Line 7: Total FUTA taxable wages (Col 1: f1_28/29)
            "total_futa_wages_dollars": "topmostSubform[0].Page1[0].f1_28[0]",
            "total_futa_wages_cents": "topmostSubform[0].Page1[0].f1_29[0]",

            # Line 8: FUTA Tax (Col 1: f1_30/31)
            "futa_liability_dollars": "topmostSubform[0].Page1[0].f1_30[0]",
            "futa_liability_cents": "topmostSubform[0].Page1[0].f1_31[0]",

            # Line 12: Total FUTA tax (f1_38/39)
            "futa_liability_total_dollars": "topmostSubform[0].Page1[0].f1_38[0]",
            "futa_liability_total_cents": "topmostSubform[0].Page1[0].f1_39[0]",
        },
        "DE9": {
            # CA DE 9 (AcroForm - Simple Names + standard indices)
            "employer_name": "Business Name",
            "employer_account_number": "Employer Account No",
            "employer_address": "Address",
            "employer_city": "City",
            "employer_state": "State", 
            "employer_zip": "ZIP Code",
            "quarter": "Quarter",
            "year": "Year",
            
            # Column Mapping (Items C-K)
            # Item C: Total Subject Wages
            "total_wages": "Total Subject Wages", 
            # Item D: UI Subject Wages
            "ui_wages": "UI Subject Wages",
            # Item E: UI Tax
            "ui_tax": "UI Tax",
            # Item F: ETT Tax
            "ett_tax": "ETT Tax",
            # Item G: SDI Subject Wages
            "sdi_wages": "SDI Subject Wages",
            # Item H: SDI Withheld
            "sdi_tax": "SDI Withheld",
            # Item I: PIT Wages
            "pit_wages": "PIT Wages",
            # Item J: PIT Withheld
            "pit_withheld": "PIT Withheld",
            # Item K: Total Taxes Due
            "total_taxes_due": "Total Taxes Due",

            # Split Field support for DE 9 (Common in some versions)
            "ui_wages_dollars": "UI Subject Wages_Dollars",
            "ui_wages_cents": "UI Subject Wages_Cents",
            "ui_tax_dollars": "UI Tax_Dollars",
            "ui_tax_cents": "UI Tax_Cents",
            "ett_tax_dollars": "ETT Tax_Dollars",
            "ett_tax_cents": "ETT Tax_Cents",
            "sdi_wages_dollars": "SDI Subject Wages_Dollars",
            "sdi_wages_cents": "SDI Subject Wages_Cents",
            "sdi_tax_dollars": "SDI Withheld_Dollars",
            "sdi_tax_cents": "SDI Withheld_Cents",
            "pit_wages_dollars": "PIT Wages_Dollars",
            "pit_wages_cents": "PIT Wages_Cents",
            "pit_withheld_dollars": "PIT Withheld_Dollars",
            "pit_withheld_cents": "PIT Withheld_Cents",
            "total_taxes_due_dollars": "Total Taxes Due_Dollars",
            "total_taxes_due_cents": "Total Taxes Due_Cents",

            # Fallback mappings for some DE 9 versions (using f1_xx indices)
            "total_wages": "f1_09",
            "ui_wages": "f1_10",
            "ui_tax": "f1_11",
            "ett_tax": "f1_12",
            "sdi_wages": "f1_13",
            "sdi_tax": "f1_14",
            "pit_wages": "f1_15",
            "pit_withheld": "f1_16",
            "total_taxes_due": "f1_17",
        },
        "DE9C": {
             # CA DE 9C (Continuation)
             "employer_name": "Business Name",
             "employer_account_number": "Employer Account No",
             "quarter_ended": "Quarter Ended", 
             "year": "Year",
        }
    }

    def __init__(self, forms_dir=None):
        self.forms_dir = None
        
        # Candidate paths to check
        candidates = []
        if forms_dir:
            candidates.append(forms_dir)
            
        # 1. Check mapped path from settings (Standard Django structure)
        # settings.BASE_DIR usually points to project root. 
        # Inside Docker, if app is at /app/horilla, BASE_DIR might be /app/horilla or /app depending on structure.
        # We assume standard structure: BASE_DIR/report/static/report/forms
        path_via_settings = os.path.join(settings.BASE_DIR, "report", "static", "report", "forms")
        candidates.append(path_via_settings)

        # 2. Check explicit Docker internal path (based on docker-compose volume mapping)
        # docker-compose.yaml maps to: /app/report/static/report/forms
        candidates.append("/app/report/static/report/forms")
        
        # 3. Check for specific common dev paths just in case
        candidates.append("/app/staticfiles/report/forms")

        logger.info(f"[TaxFormFiller] Initializing. Checking paths: {candidates}")
        
        for path in candidates:
            if os.path.exists(path):
                # Verify it contains at least one of the expected files
                if os.path.exists(os.path.join(path, "f941.pdf")):
                    self.forms_dir = path
                    logger.info(f"[TaxFormFiller] Found valid templates at: {path}")
                    try:
                        files = os.listdir(path)
                        logger.info(f"[TaxFormFiller] Directory contents: {files}")
                    except Exception as e:
                        logger.error(f"[TaxFormFiller] Error listing directory {path}: {e}")
                    break
                else:
                    logger.warning(f"[TaxFormFiller] Directory exists but f941.pdf not found: {path}")
            else:
                logger.debug(f"[TaxFormFiller] Path not found: {path}")

        if not self.forms_dir:
            logger.error("[TaxFormFiller] No valid template directory found in candidates.")
            # Fallback to the settings path even if check failed, to produce a clear error message later
            self.forms_dir = path_via_settings 

    def fill_form(self, form_type, data):
        """
        Fills a PDF form of the specified type with the provided data.
        
        Args:
            form_type (str): "941", "940", "DE9", or "DE9C"
            data (dict): Dictionary containing data to populate the form.
            
        Returns:
            bytes: The filled PDF content as bytes.
        """
        if not self.forms_dir:
             raise FileNotFoundError("[TaxFormFiller] Template directory not configured.")

        filename = f"f{form_type.lower()}.pdf" # e.g., f941.pdf
        form_path = os.path.join(self.forms_dir, filename)
        
        logger.info(f"[TaxFormFiller] Attempting to fill {form_type} using template: {form_path}")
        
        if not os.path.exists(form_path):
            logger.error(f"[TaxFormFiller] Template file missing: {form_path}")
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
            
            logger.info(f"[TaxFormFiller] Successfully filled {filled_fields} fields for {form_type}")
            return doc.write()
            
        except Exception as e:
            logger.exception(f"[TaxFormFiller] detailed error filling form {form_type}: {e}")
            raise
