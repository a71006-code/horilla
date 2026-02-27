from django.utils.translation import gettext as _
from payroll.models.models import Payslip, Deduction
from django.db.models import Sum

def calculate_tax_liability(payslips, company=None):
    """
    Calculates employer tax liability and employee withholdings for the provided payslips.
    Handles Annual Wage Base Limits for FUTA, Social Security, etc.
    
    Args:
        payslips (QuerySet): Filtered Payslip queryset.
    
    Returns:
        dict: {
            "detailed_liability": [list of detailed row dicts for UI],
            "form_aggregates": {
                "total_wages": float,
                "941": { ... },
                "940": { "futa_liability": float, ... },
                "DE9": { ... }
            },
            "employee_aggregates": [list of per-employee DE9C rows]
        }
    """
    
    # 1. Prepare Data Structures
    data_list = []
    
    # Aggregates for Forms
    form_aggregates = {
        "total_wages": 0.0,
        "941": {
            "federal_income_tax": 0.0,
            "social_security_wages": 0.0,
            "social_security_tax": 0.0, # Employer + Employee
            "medicare_wages": 0.0,
            "medicare_tax": 0.0, # Employer + Employee
        },
        "940": {
            "futa_liability": 0.0,
            "total_futa_wages": 0.0, # Wages subject to FUTA (up to limit)
        },
        "DE9": {
            "pit_wages": 0.0,
            "pit_withheld": 0.0,
            "unemployment_insurance_wages": 0.0,
            "unemployment_insurance_tax": 0.0,
            "ett_wages": 0.0,
            "ett_tax": 0.0,
            "sdi_wages": 0.0,
            "sdi_tax": 0.0,
        }
    }

    # Helper to safe float
    def safefloat(val):
        try: return float(val or 0)
        except: return 0.0

    if not payslips.exists():
        return {
            "detailed_liability": [],
            "form_aggregates": form_aggregates,
            "employee_aggregates": [],
        }

    # 2. Pre-fetch Data
    # We need to calculate YTD for Wage Limits. 
    # Since limits are Annual, we need all payslips for these employees in the current year UP TO these payslips.
    
    # Extract IDs and mapping
    payslip_values = list(payslips.values(
        "id", "employee_id", "employee_id__employee_first_name", "employee_id__employee_last_name",
        "start_date", "end_date", "gross_pay", "basic_pay", "pay_head_data"
    ))
    
    relevant_emp_ids = set(p["employee_id"] for p in payslip_values)
    current_years = set(p["start_date"].year for p in payslip_values)
    min_date = min(p["start_date"] for p in payslip_values)
    
    # Fetch HISTORY for YTD (All payslips for these employees, this year, BEFORE or EQUAL to max date)
    # Actually, strictly BEFORE the current payslip is better for incremental calculation, 
    # but we are processing a batch. 
    # Correct approach: For each payslip in the batch, we need its specific prior YTD.
    
    # Let's fetch ALL payslips for these employees in these years to build a history map.
    history_qs = Payslip.objects.filter(
        employee_id__in=relevant_emp_ids,
        start_date__year__in=current_years,
        start_date__lt=min_date # Optimization: fetch only prior if batch is sequential? 
        # No, simpler to fetch all YTD for the year and filter in python.
    ).values("id", "employee_id", "start_date", "gross_pay")
    
    # But wait, if the batch itself contains multiple payslips for same employee (e.g. Jan and Feb), 
    # we need to process them in order.
    
    all_history = list(Payslip.objects.filter(
        employee_id__in=relevant_emp_ids,
        start_date__year__in=current_years
    ).order_by('start_date').values("id", "employee_id", "start_date", "gross_pay"))

    # Build YTD Lookup
    # We need to know "Cumulative Gross BEFORE this payslip"
    # Map: payslip_id -> prior_ytd_gross
    ytd_map = {} 
    
    # We also track cumulative per employee to handle multiple payslips in ONE batch
    emp_running_ytd = {e_id: 0.0 for e_id in relevant_emp_ids} # This usually starts at 0 for start of year
    
    # But `all_history` includes the current batch too.
    # So we iterate `all_history` and populate `ytd_map`.
    
    temp_emp_ytd = {e_id: {} for e_id in relevant_emp_ids} # year -> cum_amount
    
    for h in all_history:
        emp_id = h["employee_id"]
        year = h["start_date"].year
        if year not in temp_emp_ytd[emp_id]:
            temp_emp_ytd[emp_id][year] = 0.0
            
        ytd_map[h["id"]] = temp_emp_ytd[emp_id][year]
        temp_emp_ytd[emp_id][year] += safefloat(h["gross_pay"])

    # Deduction Config Map
    # Extract all deduction IDs from payslips in batch
    all_deduction_ids = set()
    for item in payslip_values:
        ph_data = item["pay_head_data"] or {}
        deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])
        for d in deductions:
            if "deduction_id" in d:
                all_deduction_ids.add(d["deduction_id"])

    deduction_configs = {
        d["id"]: d for d in Deduction.objects.filter(id__in=all_deduction_ids).values(
            "id", "title", "employer_rate", "based_on", "tax_reporting_type",
            "has_max_limit", "maximum_amount"
        )
    }

    employee_aggregates_map = {}

    # 3. Process Each Payslip
    for item in payslip_values:
        pid = item["id"]
        emp_id = item["employee_id"]
        gross = safefloat(item["gross_pay"])
        ytd_gross_prior = ytd_map.get(pid, 0.0)

        if emp_id not in employee_aggregates_map:
            employee_aggregates_map[emp_id] = {
                "employee_id": emp_id,
                "first_name": item["employee_id__employee_first_name"],
                "last_name": item["employee_id__employee_last_name"],
                "total_wages": 0.0,
                "pit_wages": 0.0,
                "pit_withheld": 0.0,
            }
        
        ph_data = item["pay_head_data"] or {}
        deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])
        
        # Aggregate Total Wages
        form_aggregates["total_wages"] += gross
        employee_aggregates_map[emp_id]["total_wages"] += gross
        
        # Federal Income Tax (Direct Field)
        fit = safefloat(ph_data.get("federal_tax", 0))
        form_aggregates["941"]["federal_income_tax"] += fit

        # Process Deductions
        for d_item in deductions:
            did = d_item.get("deduction_id")
            config = deduction_configs.get(did)
            if not config: continue
            
            title_lower = config["title"].lower()
            reporting_type = config["tax_reporting_type"]
            
            # --- Auto-Detect Logic (Migration compatibility) ---
            # If tax_reporting_type is None, guess based on title (Backward Compat)
            if not reporting_type:
                # Social Security / OASDI
                if any(x in title_lower for x in ["social security", "soc sec", "fica ss", "oasdi", "social", "ss tax"]): reporting_type = "FICA_SS"
                # Medicare
                elif any(x in title_lower for x in ["medicare", "fica med", "med tax", "hospital"]): reporting_type = "FICA_MED"
                # FUTA
                elif any(x in title_lower for x in ["futa", "federal unemployment", "fed unemp", "unemployment tax"]): reporting_type = "FUTA"
                # CA SDI
                elif any(x in title_lower for x in ["ca sdi", "casdi", "disability", "state disability", "sdi", "s.d.i."]): reporting_type = "CA_SDI"
                # CA ETT
                elif any(x in title_lower for x in ["ca ett", "caett", "training tax", "employment training", "ett", "e.t.t."]): reporting_type = "CA_ETT"
                # CA UI
                elif any(x in title_lower for x in ["ca ui", "caui", "ca unemployment", "state unemployment", "sui", "u.i."]): reporting_type = "CA_UI"
                # CA PIT / State Income Tax
                elif any(x in title_lower for x in ["ca tax", "california", "ca pit", "state income", "sit", "personal income", "pit", "ca withholding", "state withholding", "ca sit", "ca p.i.t."]): reporting_type = "CA_PIT"
                # Federal Income Tax
                elif any(x in title_lower for x in ["federal tax", "fed tax", "fit", "federal withholding", "income tax", "withholding"]): reporting_type = "FIT"

            employer_rate = safefloat(config["employer_rate"])
            
            # Override Rates for standard taxes if config is wrong (Standard Horilla issue)
            if reporting_type == "FICA_SS": employer_rate = 6.2
            elif reporting_type == "FICA_MED": employer_rate = 1.45
            elif reporting_type in ["CA_PIT", "CA_SDI"]: employer_rate = 0.0 # Employer doesn't pay these usually
            
            # Allow Payslip specific override
            if "employer_contribution_rate" in d_item and safefloat(d_item["employer_contribution_rate"]) > 0:
                 if reporting_type not in ["CA_PIT", "CA_SDI"]: # Don't allow override for employee-only taxes
                    employer_rate = safefloat(d_item["employer_contribution_rate"])

            # Amounts
            employee_withheld = safefloat(d_item.get("amount", 0))
            
            # Base Amount
            base_amount = gross # Default
            if config["based_on"] == "basic_pay": base_amount = safefloat(item["basic_pay"])
            elif config["based_on"] == "taxable_gross_pay": 
                 base_amount = safefloat(ph_data.get("taxable_gross_pay", {}).get("taxable_gross_pay", gross))

            # --- Calculate Employer Liability with LIMITS ---
            liability_amount = 0.0
            taxable_wages_for_component = 0.0
            
            # Determine Limit
            limit = None
            if config.get("has_max_limit") and config.get("maximum_amount") is not None:
                limit = safefloat(config["maximum_amount"])
            
            # Fallback for standard taxes if user forgot to set limit?
            # Maybe for FICA_SS we still force it if not set? 
            # Ideally we trust the model. But to be safe during transition:
            if limit is None:
                 if reporting_type in ["FUTA", "CA_UI", "CA_ETT"]:
                     limit = 7000.0 # Safe fallback
                 elif reporting_type == "FICA_SS":
                     limit = 168600.0 # Safe fallback
                 elif reporting_type == "CA_SDI":
                     # 2024/2025 CA SDI wage base fallback.
                     limit = 153164.0
            
            if employer_rate > 0 or employee_withheld > 0 or reporting_type in ["FUTA", "CA_UI", "CA_ETT", "CA_SDI"]:
                if limit is not None:
                     # Taxable part is the portion of CURRENT wages that falls below the cumulative limit
                     # max(0, min(amount, limit - prior_ytd))
                     taxable_part = max(0.0, min(base_amount, limit - ytd_gross_prior))
                     taxable_wages_for_component = taxable_part
                     liability_amount = (taxable_part * employer_rate) / 100.0
                else:
                     taxable_wages_for_component = base_amount
                     liability_amount = (base_amount * employer_rate) / 100.0

            # --- Aggregate to Forms ---
            if reporting_type == "FICA_SS":
                form_aggregates["941"]["social_security_wages"] += taxable_wages_for_component
                form_aggregates["941"]["social_security_tax"] += (liability_amount + employee_withheld)
            elif reporting_type == "FICA_MED":
                form_aggregates["941"]["medicare_wages"] += base_amount # No limit for Medicare
                form_aggregates["941"]["medicare_tax"] += (liability_amount + employee_withheld)
            elif reporting_type == "FIT":
                # Only add if it wasn't already added from the direct 'federal_tax' field
                # (Standard Horilla uses direct field, but custom setups might use deductions)
                if not safefloat(ph_data.get("federal_tax", 0)):
                    form_aggregates["941"]["federal_income_tax"] += employee_withheld
            elif reporting_type == "FUTA":
                form_aggregates["940"]["total_futa_wages"] += taxable_wages_for_component
                form_aggregates["940"]["futa_liability"] += liability_amount
            elif reporting_type == "CA_PIT":
                form_aggregates["DE9"]["pit_wages"] += base_amount
                form_aggregates["DE9"]["pit_withheld"] += employee_withheld
                employee_aggregates_map[emp_id]["pit_wages"] += base_amount
                employee_aggregates_map[emp_id]["pit_withheld"] += employee_withheld
            elif reporting_type == "CA_SDI":
                form_aggregates["DE9"]["sdi_wages"] += taxable_wages_for_component
                form_aggregates["DE9"]["sdi_tax"] += employee_withheld # Employee pays SDI
            elif reporting_type == "CA_UI":
                form_aggregates["DE9"]["unemployment_insurance_wages"] += taxable_wages_for_component
                form_aggregates["DE9"]["unemployment_insurance_tax"] += liability_amount
            elif reporting_type == "CA_ETT":
                 form_aggregates["DE9"]["ett_wages"] += taxable_wages_for_component
                 form_aggregates["DE9"]["ett_tax"] += liability_amount

            # --- Add to Detailed List (for Payroll Pivot UI) ---
            if employer_rate > 0 or employee_withheld > 0:
                data_list.append({
                    "Employee": f"{item['employee_id__employee_first_name']} {item['employee_id__employee_last_name']}",
                    "Tax Component": config["title"], # Keep original title for UI consistency
                    "Employer Liability": round(liability_amount, 2),
                    "Employee Withheld": round(employee_withheld, 2),
                    "Rate": f"{employer_rate}%" if employer_rate > 0 else "-",
                    "Start Date": item["start_date"],
                    "End Date": item["end_date"],
                    "Reporting Type": reporting_type # Debug info
                })

    employee_aggregates = [
        {
            "employee_id": emp["employee_id"],
            "first_name": emp["first_name"],
            "last_name": emp["last_name"],
            "total_wages": round(emp["total_wages"], 2),
            "pit_wages": round(emp["pit_wages"], 2),
            "pit_withheld": round(emp["pit_withheld"], 2),
        }
        for emp in sorted(
            employee_aggregates_map.values(),
            key=lambda x: (
                str(x.get("last_name") or "").lower(),
                str(x.get("first_name") or "").lower(),
                x.get("employee_id") or 0,
            ),
        )
    ]

    return {
        "detailed_liability": data_list,
        "form_aggregates": form_aggregates,
        "employee_aggregates": employee_aggregates,
    }
