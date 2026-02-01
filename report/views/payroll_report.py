from django.apps import apps
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date

if apps.is_installed("payroll"):

    from base.models import Company
    from horilla.decorators import login_required, permission_required
    from payroll.filters import PayslipFilter
    from payroll.models.models import Payslip

    @login_required
    @permission_required(perm="payroll.view_payslip")
    def payroll_report(request):
        company = "all"
        selected_company = request.session.get("selected_company")
        if selected_company != "all":
            company = Company.objects.filter(id=selected_company).first()

        if request.user.has_perm("payroll.view_payslip"):
            payslips = Payslip.objects.all()
        else:
            payslips = Payslip.objects.filter(
                employee_id__employee_user_id=request.user
            )

        filter_form = PayslipFilter(request.GET, payslips)

        return render(
            request,
            "report/payroll_report.html",
            {"company": company, "f": filter_form},
        )

    @login_required
    @permission_required(perm="payroll.view_payslip")
    def payroll_pivot(request):
        model_type = request.GET.get("model", "payslip")

        if model_type == "payslip":
            qs = Payslip.objects.all()

            if employee_id := request.GET.getlist("employee_id"):
                qs = qs.filter(employee_id__id__in=employee_id)
            if status := request.GET.get("status"):
                qs = qs.filter(status=status)
            if group_name := request.GET.get("group_name"):
                qs = qs.filter(group_name=group_name)

            start_date_from = parse_date(request.GET.get("start_date_from", ""))
            start_date_to = parse_date(request.GET.get("start_date_till", ""))
            if start_date_from:
                qs = qs.filter(start_date__gte=start_date_from)
            if start_date_to:
                qs = qs.filter(start_date__lte=start_date_to)

            end_date_from = parse_date(request.GET.get("end_date_from", ""))
            end_date_to = parse_date(request.GET.get("end_date_till", ""))
            if end_date_from:
                qs = qs.filter(end_date__gte=end_date_from)
            if end_date_to:
                qs = qs.filter(end_date__lte=end_date_to)

            # Gross Pay Range
            gross_pay_gte = request.GET.get("gross_pay__gte")
            gross_pay_lte = request.GET.get("gross_pay__lte")
            if gross_pay_gte:
                qs = qs.filter(gross_pay__gte=gross_pay_gte)
            if gross_pay_lte:
                qs = qs.filter(gross_pay__lte=gross_pay_lte)

            # Deduction Range
            deduction_gte = request.GET.get("deduction__gte")
            deduction_lte = request.GET.get("deduction__lte")
            if deduction_gte:
                qs = qs.filter(deduction__gte=deduction_gte)
            if deduction_lte:
                qs = qs.filter(deduction__lte=deduction_lte)

            # Net Pay Range
            net_pay_gte = request.GET.get("net_pay__gte")
            net_pay_lte = request.GET.get("net_pay__lte")
            if net_pay_gte:
                qs = qs.filter(net_pay__gte=net_pay_gte)
            if net_pay_lte:
                qs = qs.filter(net_pay__lte=net_pay_lte)

            data = list(
                qs.values(
                    "id",  # Include payslip ID to fetch pay_head_data later
                    "employee_id__employee_first_name",
                    "employee_id__employee_last_name",
                    "employee_id__gender",
                    "employee_id__email",
                    "employee_id__phone",
                    "start_date",
                    "end_date",
                    "contract_wage",
                    "basic_pay",
                    "gross_pay",
                    "deduction",
                    "net_pay",
                    "group_name",
                    "status",
                    "employee_id__employee_work_info__department_id__department",
                    "employee_id__employee_work_info__job_role_id__job_role",
                    "employee_id__employee_work_info__job_position_id__job_position",
                    "employee_id__employee_work_info__work_type_id__work_type",
                    "employee_id__employee_work_info__shift_id__employee_shift",
                    "employee_id__employee_work_info__employee_type_id__employee_type",
                    "employee_id__employee_work_info__experience",
                )
            )

            choice_gender = {
                "male": "Male",
                "female": "Female",
                "other": "Other",
            }

            STATUS = {
                "draft": "Draft",
                "review_ongoing": "Review Ongoing",
                "confirmed": "Confirmed",
                "paid": "Paid",
            }

            # Fetch pay_head_data separately and map by payslip ID
            payslip_ids = [item["id"] for item in data]
            pay_head_data_dict = dict(
                Payslip.objects.filter(id__in=payslip_ids).values_list(
                    "id", "pay_head_data"
                )
            )

            data_list = []
            for item in data:
                # Load pay_head_data for current payslip
                pay_head_data = pay_head_data_dict.get(item["id"], {})

                # Extract allowances and deductions
                allowances = pay_head_data.get("allowances", [])
                deductions = pay_head_data.get(
                    "pretax_deductions", []
                ) + pay_head_data.get("post_tax_deductions", []) + pay_head_data.get("tax_deductions", [])

                # Prepare allowance and deduction lists with properly rounded amounts
                # Format: "Title (Amount)" for better readability
                allowance_titles = (
                    ", ".join([f"{allowance['title']} ({round(float(allowance['amount'] or 0), 2)})" for allowance in allowances]) or "-"
                )
                
                # We keep the raw amount lists for the separate columns if needed, 
                # but valid CSV export often benefits from the paired string.
                allowance_amounts = (
                    ", ".join(
                        [
                            str(round(float(allowance["amount"] or 0), 2))
                            for allowance in allowances
                        ]
                    )
                    or "-"
                )

                deduction_titles = (
                    ", ".join([f"{deduction['title']} ({round(float(deduction['amount'] or 0), 2)})" for deduction in deductions]) or "-"
                )
                
                deduction_amounts = (
                    ", ".join(
                        [
                            str(round(float(deduction["amount"] or 0), 2))
                            for deduction in deductions
                        ]
                    )
                    or "-"
                )

                # Calculate total allowance amount
                total_allowance_amount = sum(
                    [
                        round(float(allowance["amount"] or 0), 2)
                        for allowance in allowances
                    ]
                )

                # Calculate total deduction amount
                total_deduction_amount = sum(
                    [
                        round(float(deduction["amount"] or 0), 2)
                        for deduction in deductions
                    ]
                )
                
                # Add Federal Tax to Total Deductions
                # It is stored as a direct key in pay_head_data
                federal_tax_amount = round(float(pay_head_data.get("federal_tax", 0) or 0), 2)
                total_deduction_amount += federal_tax_amount

                # Main data structure
                row_data = {
                        "Employee": f"{item['employee_id__employee_first_name']} {item['employee_id__employee_last_name']}",
                        "Gender": choice_gender.get(item["employee_id__gender"]),
                        "Email": item["employee_id__email"],
                        "Phone": item["employee_id__phone"],
                        "Department": (
                            item[
                                "employee_id__employee_work_info__department_id__department"
                            ]
                            if item[
                                "employee_id__employee_work_info__department_id__department"
                            ]
                            else "-"
                        ),
                        "Job Position": (
                            item[
                                "employee_id__employee_work_info__job_position_id__job_position"
                            ]
                            if item[
                                "employee_id__employee_work_info__job_position_id__job_position"
                            ]
                            else "-"
                        ),
                        "Job Role": (
                            item[
                                "employee_id__employee_work_info__job_role_id__job_role"
                            ]
                            if item[
                                "employee_id__employee_work_info__job_role_id__job_role"
                            ]
                            else "-"
                        ),
                        "Work Type": (
                            item[
                                "employee_id__employee_work_info__work_type_id__work_type"
                            ]
                            if item[
                                "employee_id__employee_work_info__work_type_id__work_type"
                            ]
                            else "-"
                        ),
                        "Shift": (
                            item[
                                "employee_id__employee_work_info__shift_id__employee_shift"
                            ]
                            if item[
                                "employee_id__employee_work_info__shift_id__employee_shift"
                            ]
                            else "-"
                        ),
                        "Employee Type": (
                            item[
                                "employee_id__employee_work_info__employee_type_id__employee_type"
                            ]
                            if item[
                                "employee_id__employee_work_info__employee_type_id__employee_type"
                            ]
                            else "-"
                        ),
                        "Payslip Start Date": item["start_date"],
                        "Payslip End Date": item["end_date"],
                        "Batch Name": item["group_name"] if item["group_name"] else "-",
                        "Contract Wage": round(float(item["contract_wage"] or 0), 2),
                        "Basic Salary": round(float(item["basic_pay"] or 0), 2),
                        
                        # Consolidated columns (Optional, kept for backward compat or summary)
                        "Allowance Title": allowance_titles,
                        "Allowance Amount": allowance_amounts, 
                        "Total Allowance Amount": round(total_allowance_amount, 2),
                        
                        "Gross Pay": round(float(item["gross_pay"] or 0), 2),
                        
                        "Deduction Title": deduction_titles,
                        "Deduction Amount": deduction_amounts,
                        "Total Deductions": round(total_deduction_amount, 2),
                        
                        # Net Pay should be Gross - Total Deductions
                        # We use the calculated totals to ensure math adds up visually
                        "Net Pay": round(float(item["gross_pay"] or 0) - total_deduction_amount, 2),
                        "Status": STATUS.get(item["status"]),
                        "Experience": round(
                            float(
                                item["employee_id__employee_work_info__experience"] or 0
                            ),
                            2,
                        ),
                }

                # --- FLATTEN DYNAMIC COLUMNS ---
                # Add each Allowance as a separate column
                for allowance in allowances:
                    col_name = f"Allowance - {allowance['title']}"
                    row_data[col_name] = round(float(allowance["amount"] or 0), 2)

                # Add each Deduction as a separate column
                for deduction in deductions:
                    col_name = f"Deduction - {deduction['title']}"
                    row_data[col_name] = round(float(deduction["amount"] or 0), 2)

                # Add Federal Tax as a specific Deduction column
                # It is stored as a direct key in pay_head_data, not in the deductions list
                federal_tax_amount = round(float(pay_head_data.get("federal_tax", 0) or 0), 2)
                if federal_tax_amount > 0:
                    row_data["Deduction - Federal Withholding"] = federal_tax_amount

                data_list.append(row_data)

        elif model_type == "allowance":

            payslips = Payslip.objects.all()

            payslip_filter = PayslipFilter(request.GET, queryset=payslips)
            filtered_qs = payslip_filter.qs  # This uses all custom filters you defined

            data = list(
                filtered_qs.values(
                    "id",  # Include payslip ID to fetch pay_head_data later
                    "employee_id__employee_first_name",
                    "employee_id__employee_last_name",
                    "employee_id__gender",
                    "employee_id__email",
                    "employee_id__phone",
                    "start_date",
                    "end_date",
                    "status",
                    "employee_id__employee_work_info__department_id__department",
                    "employee_id__employee_work_info__job_role_id__job_role",
                    "employee_id__employee_work_info__job_position_id__job_position",
                    "employee_id__employee_work_info__work_type_id__work_type",
                    "employee_id__employee_work_info__shift_id__employee_shift",
                )
            )

            choice_gender = {
                "male": "Male",
                "female": "Female",
                "other": "Other",
            }

            STATUS = {
                "draft": "Draft",
                "review_ongoing": "Review Ongoing",
                "confirmed": "Confirmed",
                "paid": "Paid",
            }

            # Fetch pay_head_data separately and map by payslip ID
            payslip_ids = [item["id"] for item in data]
            pay_head_data_dict = dict(
                Payslip.objects.filter(id__in=payslip_ids).values_list(
                    "id", "pay_head_data"
                )
            )

            data_list = []
            for item in data:
                # Load pay_head_data for current payslip
                pay_head_data = pay_head_data_dict.get(item["id"], {})

                # Combine Allowances and Deductions in a single section
                all_pay_data = []

                # Add Allowances to combined data
                for allowance in pay_head_data.get("allowances", []):
                    all_pay_data.append(
                        {
                            "Pay Type": "Allowance",
                            "Title": allowance["title"],
                            "Amount": round(float(allowance["amount"] or 0), 2),
                        }
                    )

                # Add Deductions to combined data
                for deduction in pay_head_data.get(
                    "pretax_deductions", []
                ) + pay_head_data.get("post_tax_deductions", []) + pay_head_data.get("tax_deductions", []):
                    all_pay_data.append(
                        {
                            "Pay Type": "Deduction",
                            "Title": deduction["title"],
                            "Amount": round(float(deduction["amount"] or 0), 2),
                        }
                    )

                # Add Federal Tax as a specific Deduction
                federal_tax_amount = round(float(pay_head_data.get("federal_tax", 0) or 0), 2)
                if federal_tax_amount > 0:
                    all_pay_data.append(
                        {
                            "Pay Type": "Deduction",
                            "Title": "Federal Withholding",
                            "Amount": federal_tax_amount,
                        }
                    )

                # Add combined data to main data list
                for pay_item in all_pay_data:
                    data_list.append(
                        {
                            "Employee": f"{item['employee_id__employee_first_name']} {item['employee_id__employee_last_name']}",
                            "Gender": choice_gender.get(item["employee_id__gender"]),
                            "Email": item["employee_id__email"],
                            "Phone": item["employee_id__phone"],
                            "Department": (
                                item[
                                    "employee_id__employee_work_info__department_id__department"
                                ]
                                if item[
                                    "employee_id__employee_work_info__department_id__department"
                                ]
                                else "-"
                            ),
                            "Job Position": (
                                item[
                                    "employee_id__employee_work_info__job_position_id__job_position"
                                ]
                                if item[
                                    "employee_id__employee_work_info__job_position_id__job_position"
                                ]
                                else "-"
                            ),
                            "Job Role": (
                                item[
                                    "employee_id__employee_work_info__job_role_id__job_role"
                                ]
                                if item[
                                    "employee_id__employee_work_info__job_role_id__job_role"
                                ]
                                else "-"
                            ),
                            "Work Type": (
                                item[
                                    "employee_id__employee_work_info__work_type_id__work_type"
                                ]
                                if item[
                                    "employee_id__employee_work_info__work_type_id__work_type"
                                ]
                                else "-"
                            ),
                            "Shift": (
                                item[
                                    "employee_id__employee_work_info__shift_id__employee_shift"
                                ]
                                if item[
                                    "employee_id__employee_work_info__shift_id__employee_shift"
                                ]
                                else "-"
                            ),
                            "Payslip Start Date": item["start_date"],
                            "Payslip End Date": item["end_date"],
                            "Allowance & Deduction": pay_item["Pay Type"],
                            "Allowance & Deduction Title": pay_item["Title"],
                            "Allowance & Deduction Amount": pay_item["Amount"],
                            "Status": STATUS.get(item["status"]),
                        }
                    )

        elif model_type == "employer_liability":
            from payroll.methods.tax_reporting import calculate_tax_liability
            
            payslips = Payslip.objects.all()
            payslip_filter = PayslipFilter(request.GET, queryset=payslips)
            filtered_qs = payslip_filter.qs

            # Use Unified Tax Logic
            result = calculate_tax_liability(filtered_qs)
            data_list = result["detailed_liability"]

        elif model_type == "cash_requirement":
            from django.db.models import Sum
            
            payslips = Payslip.objects.all()
            payslip_filter = PayslipFilter(request.GET, queryset=payslips)
            filtered_qs = payslip_filter.qs
            
            # 1. Net Pay (Transfer to Employees)
            total_net_pay = filtered_qs.aggregate(Sum("net_pay"))["net_pay__sum"] or 0.0
            
            # 2. Taxes (Transfer to IRS/State)
            # We need to sum (Employer Liability + Employee Withheld)
            # Iterate to calculate exact tax liability
            total_tax_liability = 0.0
            total_benefit_liability = 0.0

            # Using a simplified iteration similar to employer_liability reporting
            # but aggregating totals instead of per-employee list
            
            # We need to inspect deductions to separate Taxes vs Benefits if possible.
            # Currently 'tax_deductions' are usually separated in pay_head_data structure.
            # Or we look at DeductionConfig.title / type if available.
            
            # Let's fetch all relevant data
            data = list(filtered_qs.values("id", "gross_pay", "basic_pay"))
            payslip_ids = [item["id"] for item in data]
            pay_head_data_dict = dict(
                Payslip.objects.filter(id__in=payslip_ids).values_list("id", "pay_head_data")
            )
            
            from payroll.models.models import Deduction
            all_deduction_ids = set()
            for ph_data in pay_head_data_dict.values():
                 # Look at all deduction types
                 deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])
                 for d in deductions:
                     all_deduction_ids.add(d["deduction_id"])
            
            deduction_map = {
                d["id"]: d for d in Deduction.objects.filter(id__in=all_deduction_ids).values("id", "title", "employer_rate", "based_on")
            }
            
            for item in data:
                ph_data = pay_head_data_dict.get(item["id"], {})
                # Aggregate Taxes
                for d in ph_data.get("tax_deductions", []):
                    # For tax_deductions list, it's usually statutory taxes
                    amount = float(d.get("amount", 0)) # Employee share
                    
                    # Calculate Employer share
                    ded_config = deduction_map.get(d["deduction_id"])
                    employer_share = 0.0
                    if ded_config:
                        rate = float(ded_config["employer_rate"]) if ded_config["employer_rate"] else 0.0
                        if "employer_contribution_rate" in d:
                             rate = float(d["employer_contribution_rate"])
                        
                        if rate > 0:
                            base = 0.0
                            if ded_config["based_on"] == "gross_pay": base = float(item["gross_pay"] or 0)
                            elif ded_config["based_on"] == "basic_pay": base = float(item["basic_pay"] or 0)
                            elif ded_config["based_on"] == "taxable_gross_pay": 
                                base = float(ph_data.get("taxable_gross_pay", {}).get("taxable_gross_pay", item["gross_pay"] or 0))
                            
                            employer_share = (base * rate) / 100.0
                    
                    total_tax_liability += (amount + employer_share)

                # Aggregate Other Deductions (Benefits)
                # Assuming pretax/posttax are non-statutory benefits/insurance
                for d in ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []):
                     amount = float(d.get("amount", 0))
                     # Add employer share if any? (Complex benefit logic might be here, ignoring for basic cash req)
                     total_benefit_liability += amount

            data_list = [
                {
                    "Category": "Net Pay",
                    "Payee": "Employees",
                    "Amount": round(total_net_pay, 2)
                },
                {
                    "Category": "Taxes",
                    "Payee": "Federal/State Agencies",
                    "Amount": round(total_tax_liability, 2)
                },
                {
                    "Category": "Deductions/Benefits",
                    "Payee": "Benefit Vendors",
                    "Amount": round(total_benefit_liability, 2)
                },
                {
                    "Category": "TOTAL CASH REQUIRED",
                    "Payee": "-",
                    "Amount": round(total_net_pay + total_tax_liability + total_benefit_liability, 2)
                }
            ]

        else:
            data_list = []

        return JsonResponse(data_list, safe=False)


    @login_required
    @permission_required(perm="payroll.view_payslip")
    def download_tax_forms(request):
        import io
        import zipfile
        from django.http import HttpResponse
        from report.forms.tax_forms import TaxFormFiller
        from django.db.models import Sum

        # Filter Logic (Simplified overlap with payroll_pivot logic)
        payslips = Payslip.objects.all()
        
        # Apply company filter if selected
        selected_company = request.session.get("selected_company")
        if selected_company and selected_company != "all":
             payslips = payslips.filter(employee_id__employee_work_info__company_id=selected_company)

        # Apply basic date filters directly from request
        start_date_from = parse_date(request.GET.get("start_date_from", ""))
        start_date_to = parse_date(request.GET.get("start_date_till", ""))
        if start_date_from:
            payslips = payslips.filter(start_date__gte=start_date_from)
        if start_date_to:
            payslips = payslips.filter(start_date__lte=start_date_to)

        end_date_from = parse_date(request.GET.get("end_date_from", ""))
        end_date_to = parse_date(request.GET.get("end_date_till", ""))
        if end_date_from:
            payslips = payslips.filter(end_date__gte=end_date_from)
        if end_date_to:
            payslips = payslips.filter(end_date__lte=end_date_to)

        # Retrieve Company Info
        from base.models import Company
        comp = None
        company_name = "Horilla HR"
        company_address = "123 Business Rd"
        employer_ein = "00-0000000"

        if selected_company and selected_company != "all":
            comp = Company.objects.filter(id=selected_company).first()
        
        if not comp:
             # Fallback to first company if exists, or defaults
             comp = Company.objects.first()
        
        if comp:
            company_name = comp.company
            # Construct address if available
            addr_parts = [comp.address, comp.city, comp.state, comp.zip, comp.country]
            company_address = ", ".join([p for p in addr_parts if p])
            # Assuming EIN might be in a field or just default for now as it's not standard on Company model usually?
            # We'll check if there's a field for tax id, otherwise leave blank
            employer_ein = getattr(comp, "company_registration_number", "00-0000000")

        # Aggregate Data using Unified Logic
        from payroll.methods.tax_reporting import calculate_tax_liability
        
        # Calculate Taxes
        # We pass the company object (comp) if available, though currently not used by calc logic
        result = calculate_tax_liability(payslips, company=comp if selected_company and selected_company != "all" else None)
        
        aggregates = result["form_aggregates"]
        
        # Calculate Total Gross for summary
        total_gross = payslips.aggregate(Sum("gross_pay"))["gross_pay__sum"] or 0.0

        # Prepare granular address for forms that need it (e.g. 941)
        # and combined for others
        emp_city = getattr(comp, "city", "") if comp else ""
        emp_state = getattr(comp, "state", "") if comp else ""
        emp_zip = getattr(comp, "zip", "") if comp else ""

        data = {
            "employer_name": company_name,
            "employer_address": company_address,
            "employer_city": emp_city,
            "employer_state": emp_state,
            "employer_zip": emp_zip,
            "employer_ein": employer_ein,
            "employer_account_number": employer_ein, # Use EIN as State ID fallback for now if no separate field
            "total_wages": round(total_gross, 2),
            
            # --- 941 Data ---
            "federal_income_tax": round(aggregates["941"]["federal_income_tax"], 2),
            "taxable_social_security_wages": round(aggregates["941"]["social_security_wages"], 2),
            "taxable_medicare_wages": round(aggregates["941"]["medicare_wages"], 2),
            "total_taxes_before_adjustments": round(
                aggregates["941"]["federal_income_tax"] + 
                aggregates["941"]["social_security_tax"] + 
                aggregates["941"]["medicare_tax"], 2
            ),
            
            # --- 940 Data ---
            "total_futa_wages": round(aggregates["940"]["total_futa_wages"], 2),
            "futa_liability": round(aggregates["940"]["futa_liability"], 2),
            
            # --- DE9 Data ---
            "pit_wages": round(aggregates["DE9"]["pit_wages"], 2),
            "pit_withheld": round(aggregates["DE9"]["pit_withheld"], 2),
            "ui_wages": round(aggregates["DE9"]["unemployment_insurance_wages"], 2),
            "ui_tax": round(aggregates["DE9"]["unemployment_insurance_tax"], 2),
            "ett_wages": round(aggregates["DE9"]["ett_wages"], 2),
            "ett_tax": round(aggregates["DE9"]["ett_tax"], 2),
            "sdi_wages": round(aggregates["DE9"]["sdi_wages"], 2),
            "sdi_tax": round(aggregates["DE9"]["sdi_tax"], 2),
            
            # --- Employee List for DE9C ---
            "employees": [] 
        }

        # Populate Employee List for DE9C
        # We need to re-iterate payslips to get per-employee totals including valid SSN and Wages
        emp_data = {} # emp_id -> data dict
        
        for payslip in payslips:
            eid = payslip.employee_id.id
            if eid not in emp_data:
                emp_data[eid] = {
                    "first_name": payslip.employee_id.employee_first_name,
                    "last_name": payslip.employee_id.employee_last_name,
                    "ssn": getattr(payslip.employee_id, "ssn", ""), 
                    "total_wages": 0.0,
                    "pit_wages": 0.0,
                    "pit_withheld": 0.0
                }
            
            gross = float(payslip.gross_pay or 0)
            emp_data[eid]["total_wages"] += gross
            
            # Extract PIT from this payslip's deductions
            ph_data = payslip.pay_head_data or {}
            deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])
            
            pit_amt = 0.0
            for d in deductions:
                 # We still check title or type if available, simple fallback:
                 if "ca tax" in d.get("title", "").lower() or "california state" in d.get("title", "").lower():
                     pit_amt += float(d.get("amount", 0))
            
            emp_data[eid]["pit_withheld"] += pit_amt
            if pit_amt > 0:
                 emp_data[eid]["pit_wages"] += gross

        data["employees"] = list(emp_data.values())

        filler = TaxFormFiller()
        zip_buffer = io.BytesIO()
        has_files = False
        
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for form_type in ["941", "940", "DE9", "DE9C"]:
                 try:
                     pdf_bytes = filler.fill_form(form_type, data)
                     if pdf_bytes:
                         zf.writestr(f"Form_{form_type}.pdf", pdf_bytes)
                         has_files = True
                 except Exception:
                     # Skip if template missing
                     pass
        
        if not has_files:
             # Create a dummy text file saying no templates found
             with zipfile.ZipFile(zip_buffer, "w") as zf:
                 zf.writestr("README.txt", "No PDF templates found in report/static/report/forms/. Please add f941.pdf, f940.pdf, etc.")

        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        response['Content-Disposition'] = 'attachment; filename="tax_forms.zip"'
        return response
