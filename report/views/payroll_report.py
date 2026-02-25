from django.apps import apps
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date

if apps.is_installed("payroll"):
    import base64

    from base.models import Company
    from horilla.decorators import login_required, permission_required
    from payroll.filters import PayslipFilter
    from payroll.models.models import Payslip
    from payroll.models.tax_models import PayrollSettings

    TAX_FORM_TYPES = ("941", "940", "DE9", "DE9C")

    def split_dollars_cents(amount):
        """Splits a float amount into (dollars, cents) strings."""
        if amount is None:
            return "", ""
        try:
            val = float(amount)
            dollars = int(val)
            cents = int(round((val - dollars) * 100))
            return str(dollars), f"{cents:02d}"
        except (ValueError, TypeError):
            return "", ""

    def _get_selected_company(request):
        selected_company = request.session.get("selected_company")
        if not selected_company or selected_company == "all":
            return None
        return Company.objects.filter(id=selected_company).first()

    def _get_payroll_settings(request, create=False):
        company = _get_selected_company(request)
        if company:
            if create:
                settings, _ = PayrollSettings.objects.get_or_create(company_id=company)
                return settings
            return PayrollSettings.objects.filter(company_id=company).first()
        if create:
            settings, _ = PayrollSettings.objects.get_or_create(company_id=None)
            return settings
        return PayrollSettings.objects.filter(company_id=None).first() or PayrollSettings.objects.first()

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
        tax_settings = _get_payroll_settings(request, create=False)

        return render(
            request,
            "report/payroll_report.html",
            {"company": company, "f": filter_form, "tax_settings": tax_settings},
        )

    @login_required
    @permission_required(perm="payroll.view_payslip")
    def update_tax_settings(request):
        if request.method != "POST":
            return JsonResponse(
                {"success": False, "message": "Only POST method is allowed."}, status=405
            )

        settings = _get_payroll_settings(request, create=True)

        settings.tax_designee_name = request.POST.get("third_party_designee_name", "").strip()
        settings.tax_designee_phone = request.POST.get("third_party_designee_phone", "").strip()
        settings.tax_designee_pin = request.POST.get("third_party_designee_pin", "").strip()
        settings.tax_signer_name = request.POST.get("signer_name", "").strip()
        settings.tax_signer_title = request.POST.get("signer_title", "").strip()
        settings.tax_signer_phone = request.POST.get("signer_daytime_phone", "").strip()
        settings.tax_seasonal_employer = str(
            request.POST.get("seasonal_employer", "")
        ).strip().lower() in {"1", "true", "yes", "on", "y"}

        settings.save(
            update_fields=[
                "tax_designee_name",
                "tax_designee_phone",
                "tax_designee_pin",
                "tax_signer_name",
                "tax_signer_title",
                "tax_signer_phone",
                "tax_seasonal_employer",
            ]
        )

        return JsonResponse(
            {"success": True, "message": "Tax settings saved successfully."}
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
    def _build_tax_form_data(request):
        from django.db.models import Sum
        from payroll.methods.tax_reporting import calculate_tax_liability

        payslips = Payslip.objects.all()
        selected_company = request.session.get("selected_company")
        if selected_company and selected_company != "all":
            payslips = payslips.filter(
                employee_id__employee_work_info__company_id=selected_company
            )

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

        comp = None
        company_name = "Horilla HR"
        company_address = "123 Business Rd"
        employer_ein = "00-0000000"

        if selected_company and selected_company != "all":
            comp = Company.objects.filter(id=selected_company).first()
        if not comp:
            comp = Company.objects.first()

        if comp:
            company_name = comp.company
            addr_parts = [comp.address, comp.city, comp.state, comp.zip, comp.country]
            company_address = ", ".join([p for p in addr_parts if p])
            employer_ein = getattr(comp, "company_registration_number", "00-0000000")
        
        state_employer_id = request.GET.get("state_employer_id", employer_ein)
        tax_settings = _get_payroll_settings(request, create=False)

        result = calculate_tax_liability(
            payslips, company=comp if selected_company and selected_company != "all" else None
        )
        aggregates = result["form_aggregates"]
        total_gross = payslips.aggregate(Sum("gross_pay"))["gross_pay__sum"] or 0.0
        employee_count = payslips.values("employee_id").distinct().count()

        emp_addr = getattr(comp, "address", "")
        emp_city = getattr(comp, "city", "") if comp else ""
        emp_state = getattr(comp, "state", "") if comp else ""
        emp_zip = getattr(comp, "zip", "") if comp else ""

        addr_parts = emp_addr.split(" ", 1)
        addr_number = addr_parts[0] if len(addr_parts) > 0 else ""
        addr_street = addr_parts[1] if len(addr_parts) > 1 else ""
        addr_suite = ""

        def split_amt(val):
            v = round(float(val or 0), 2)
            sign = ""
            if v < 0:
                sign = "-"
            dollars = int(abs(v))
            cents = int(round((abs(v) - dollars) * 100))
            return f"{sign}{dollars}", f"{cents:02d}"

        def parse_bool_param(name, default=False):
            raw = request.GET.get(name, "")
            if raw == "":
                return default
            return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}

        def parse_text_param(name, default=""):
            raw = str(request.GET.get(name, "")).strip()
            return raw if raw else default

        def parse_amount_param(name):
            raw = str(request.GET.get(name, "")).strip()
            if not raw:
                return None
            try:
                return round(float(raw), 2)
            except (TypeError, ValueError):
                return None

        import datetime

        today = datetime.date.today()
        reference_date = start_date_from or end_date_from or start_date_to or end_date_to or today
        quarter_idx = (reference_date.month - 1) // 3

        q_val = "Yes"
        q_map = {"quarter_1": "", "quarter_2": "", "quarter_3": "", "quarter_4": ""}
        if quarter_idx == 0:
            q_map["quarter_1"] = q_val
        elif quarter_idx == 1:
            q_map["quarter_2"] = q_val
        elif quarter_idx == 2:
            q_map["quarter_3"] = q_val
        else:
            q_map["quarter_4"] = q_val

        w_d, w_c = split_amt(total_gross)
        ui_w_val = float(aggregates["DE9"]["unemployment_insurance_wages"] or 0)
        # Item D2 expects whole dollars only to avoid layout displacement in the PDF box
        # We also pad with spaces to align right if necessary, or just provide the integer string.
        ui_w_d = f"{int(round(ui_w_val))}"
        ui_w_c = ""

        sdi_w_val = float(aggregates["DE9"]["sdi_wages"] or 0)
        # Item F2 also expects whole dollars only for visual alignment in this template
        sdi_w_d = f"{int(round(sdi_w_val))}"
        sdi_w_c = ""

        # Item C: Total Subject Wages split
        total_w_d, total_w_c = split_amt(total_gross)
        
        fit_val = float(aggregates["941"]["federal_income_tax"] or 0)
        ssw_val = float(aggregates["941"]["social_security_wages"] or 0)
        sst_val = float(aggregates["941"]["social_security_tax"] or 0)
        medw_val = float(aggregates["941"]["medicare_wages"] or 0)
        medt_val = float(aggregates["941"]["medicare_tax"] or 0)
        total_ssmed_val = sst_val + medt_val
        total_tax_val = fit_val + sst_val + medt_val

        fit_d, fit_c = split_amt(fit_val)
        ssw_d, ssw_c = split_amt(ssw_val)
        sst_d, sst_c = split_amt(sst_val)
        medw_d, medw_c = split_amt(medw_val)
        medt_d, medt_c = split_amt(medt_val)
        total_ssmed_d, total_ssmed_c = split_amt(total_ssmed_val)
        total_tax_d, total_tax_c = split_amt(total_tax_val)
        futa_w_d, futa_w_c = split_amt(aggregates["940"]["total_futa_wages"])
        futa_l_d, futa_l_c = split_amt(aggregates["940"]["futa_liability"])

        # Part 2 (Deposit Schedule) automation
        deposit_schedule = str(request.GET.get("deposit_schedule", "")).strip().lower()
        if deposit_schedule not in {"line12_less_2500", "monthly", "semiweekly"}:
            deposit_schedule = "line12_less_2500" if total_tax_val < 2500 else "monthly"

        month1_manual = parse_amount_param("monthly_tax_liability_month1")
        month2_manual = parse_amount_param("monthly_tax_liability_month2")
        month3_manual = parse_amount_param("monthly_tax_liability_month3")
        quarter_total_manual = parse_amount_param("quarter_total_tax_liability")

        quarter_months = [quarter_idx * 3 + 1, quarter_idx * 3 + 2, quarter_idx * 3 + 3]
        month_liabilities = [0.0, 0.0, 0.0]
        if any(v is not None for v in [month1_manual, month2_manual, month3_manual]):
            month_liabilities = [month1_manual or 0.0, month2_manual or 0.0, month3_manual or 0.0]
        else:
            month_gross = {quarter_months[0]: 0.0, quarter_months[1]: 0.0, quarter_months[2]: 0.0}
            for payslip in payslips:
                pay_date = getattr(payslip, "start_date", None) or getattr(payslip, "end_date", None)
                if not pay_date or pay_date.month not in month_gross:
                    continue
                month_gross[pay_date.month] += float(getattr(payslip, "gross_pay", 0) or 0)

            gross_total = sum(month_gross.values())
            if gross_total > 0:
                raw_m1 = round(total_tax_val * (month_gross[quarter_months[0]] / gross_total), 2)
                raw_m2 = round(total_tax_val * (month_gross[quarter_months[1]] / gross_total), 2)
                raw_m3 = round(total_tax_val - raw_m1 - raw_m2, 2)
                month_liabilities = [raw_m1, raw_m2, raw_m3]

        quarter_total_liability = round(
            quarter_total_manual if quarter_total_manual is not None else sum(month_liabilities), 2
        )

        month1_d, month1_c = split_amt(month_liabilities[0])
        month2_d, month2_c = split_amt(month_liabilities[1])
        month3_d, month3_c = split_amt(month_liabilities[2])
        qtotal_d, qtotal_c = split_amt(quarter_total_liability)

        business_closed = parse_bool_param("business_closed", default=False)
        seasonal_employer = parse_bool_param(
            "seasonal_employer",
            default=bool(
                getattr(tax_settings, "tax_seasonal_employer", False) if tax_settings else False
            ),
        )
        final_wage_date = parse_date(request.GET.get("final_wage_date", ""))
        final_wage_date_str = final_wage_date.strftime("%m/%d/%Y") if final_wage_date else ""

        third_party_choice = str(request.GET.get("third_party_designee", "")).strip().lower()
        if third_party_choice == "yes":
            third_party_yes = "Yes"
            third_party_no = ""
        elif third_party_choice == "no":
            third_party_yes = ""
            third_party_no = "Yes"
        else:
            third_party_yes = ""
            third_party_no = "Yes"

        designee_name = parse_text_param(
            "third_party_designee_name",
            default=getattr(tax_settings, "tax_designee_name", "") if tax_settings else "",
        )
        designee_phone = parse_text_param(
            "third_party_designee_phone",
            default=getattr(tax_settings, "tax_designee_phone", "") if tax_settings else "",
        )
        designee_pin = parse_text_param(
            "third_party_designee_pin",
            default=getattr(tax_settings, "tax_designee_pin", "") if tax_settings else "",
        )
        signer_name = parse_text_param(
            "signer_name",
            default=(
                getattr(tax_settings, "tax_signer_name", "") if tax_settings else ""
            ) or company_name,
        )
        signer_title = parse_text_param(
            "signer_title",
            default=getattr(tax_settings, "tax_signer_title", "") if tax_settings else "",
        )
        signer_daytime_phone = parse_text_param(
            "signer_daytime_phone",
            default=getattr(tax_settings, "tax_signer_phone", "") if tax_settings else "",
        )

        ein_digits = "".join(ch for ch in str(employer_ein or "") if ch.isdigit())
        ein_part1 = ein_digits[:2]
        ein_part2 = ein_digits[2:]

        data = {
            "employer_name": company_name,
            "employer_trade_name": getattr(comp, "company_trade_name", ""),
            "employer_address": company_address, # Combined address for DE9 Text3 mapping
            "employer_address_number": addr_number,
            "employer_address_street": addr_street,
            "employer_address_suite": addr_suite,
            "employer_city": emp_city,
            "employer_state": emp_state,
            "employer_zip": emp_zip,
            "employer_ein_part1": ein_part1,
            "employer_ein_part2": ein_part2,
            "employer_ein": employer_ein,
            "employer_name_page2": company_name,
            "employer_ein_page2_part1": ein_part1,
            "employer_ein_page2_part2": ein_part2,
            "employer_account_number": state_employer_id, 
            "employee_count": employee_count,

            **q_map,

            "total_wages_dollars": w_d,
            "total_wages_cents": w_c,
            "total_wages": f"{total_w_d}.{total_w_c}", # Combined with decimal for single box Item C

            "federal_income_tax_dollars": fit_d,
            "federal_income_tax_cents": fit_c,

            "taxable_social_security_wages_dollars": ssw_d,
            "taxable_social_security_wages_cents": ssw_c,
            "taxable_social_security_tax_dollars": sst_d,
            "taxable_social_security_tax_cents": sst_c,

            "taxable_medicare_wages_dollars": medw_d,
            "taxable_medicare_wages_cents": medw_c,
            "taxable_medicare_tax_dollars": medt_d,
            "taxable_medicare_tax_cents": medt_c,

            "total_social_security_and_medicare_tax_dollars": total_ssmed_d,
            "total_social_security_and_medicare_tax_cents": total_ssmed_c,

            "total_taxes_before_adjustments_dollars": total_tax_d,
            "total_taxes_before_adjustments_cents": total_tax_c,
            "total_taxes_after_adjustments_dollars": total_tax_d,
            "total_taxes_after_adjustments_cents": total_tax_c,
            "total_taxes_after_credits_dollars": total_tax_d,
            "total_taxes_after_credits_cents": total_tax_c,
            "balance_due_dollars": total_tax_d,
            "balance_due_cents": total_tax_c,

            "deposit_schedule_line12_less_2500": "Yes" if deposit_schedule == "line12_less_2500" else "",
            "deposit_schedule_monthly": "Yes" if deposit_schedule == "monthly" else "",
            "deposit_schedule_semiweekly": "Yes" if deposit_schedule == "semiweekly" else "",
            "month_1_tax_liability_dollars": month1_d if deposit_schedule == "monthly" else "",
            "month_1_tax_liability_cents": month1_c if deposit_schedule == "monthly" else "",
            "month_2_tax_liability_dollars": month2_d if deposit_schedule == "monthly" else "",
            "month_2_tax_liability_cents": month2_c if deposit_schedule == "monthly" else "",
            "month_3_tax_liability_dollars": month3_d if deposit_schedule == "monthly" else "",
            "month_3_tax_liability_cents": month3_c if deposit_schedule == "monthly" else "",
            "quarter_total_tax_liability_dollars": qtotal_d if deposit_schedule == "monthly" else "",
            "quarter_total_tax_liability_cents": qtotal_c if deposit_schedule == "monthly" else "",

            "business_closed_or_stopped_paying_wages": "Yes" if business_closed else "",
            "final_date_wages_paid": final_wage_date_str,
            "seasonal_employer": "Yes" if seasonal_employer else "",

            "third_party_designee_yes": third_party_yes,
            "third_party_designee_name": designee_name,
            "third_party_designee_phone": designee_phone,
            "third_party_designee_pin": designee_pin,
            "third_party_designee_no": third_party_no,

            "signer_name": signer_name,
            "signer_title": signer_title,
            "signer_daytime_phone": signer_daytime_phone,
            "paid_preparer_self_employed": "Yes" if parse_bool_param("paid_preparer_self_employed", default=False) else "",
            "paid_preparer_name": request.GET.get("paid_preparer_name", ""),
            "paid_preparer_ptin": request.GET.get("paid_preparer_ptin", ""),
            "paid_preparer_firm_name": request.GET.get("paid_preparer_firm_name", ""),
            "paid_preparer_ein": request.GET.get("paid_preparer_ein", ""),
            "paid_preparer_address": request.GET.get("paid_preparer_address", ""),
            "paid_preparer_phone": request.GET.get("paid_preparer_phone", ""),
            "paid_preparer_city": request.GET.get("paid_preparer_city", ""),
            "paid_preparer_state": request.GET.get("paid_preparer_state", ""),
            "paid_preparer_zip": request.GET.get("paid_preparer_zip", ""),

            "voucher_ein_part1": ein_part1,
            "voucher_ein_part2": ein_part2,
            "voucher_amount_dollars": total_tax_d,
            "voucher_amount_cents": total_tax_c,
            "voucher_q1": q_map["quarter_1"],
            "voucher_q2": q_map["quarter_2"],
            "voucher_q3": q_map["quarter_3"],
            "voucher_q4": q_map["quarter_4"],
            "voucher_business_name": company_name,
            "voucher_address": getattr(comp, "address", ""),
            "voucher_city_state_zip": f"{emp_city}, {emp_state} {emp_zip}",

            "total_futa_wages_dollars": futa_w_d,
            "total_futa_wages_cents": futa_w_c,
            "futa_liability_dollars": futa_l_d,
            "futa_liability_cents": futa_l_c,
            "futa_liability_total_dollars": futa_l_d,
            "futa_liability_total_cents": futa_l_c,

            "pit_wages": round(aggregates["DE9"]["pit_wages"], 2),
            "total_pit_wages": round(aggregates["DE9"]["pit_wages"], 2),
            "pit_withheld": round(aggregates["DE9"]["pit_withheld"], 2),
            "ui_wages": round(aggregates["DE9"]["unemployment_insurance_wages"], 2),
            "ui_tax": round(aggregates["DE9"]["unemployment_insurance_tax"], 2),
            "ett_wages": round(aggregates["DE9"]["ett_wages"], 2),
            "ett_tax": round(aggregates["DE9"]["ett_tax"], 2),
            "sdi_wages": round(aggregates["DE9"]["sdi_wages"], 2),
            "F2": sdi_w_d,
            "F2_cents": "",
            "sdi_tax": round(aggregates["DE9"]["sdi_tax"], 2),
            "subtotal": round(
                (aggregates["DE9"]["unemployment_insurance_tax"] or 0) + 
                (aggregates["DE9"]["ett_tax"] or 0) + 
                (aggregates["DE9"]["sdi_tax"] or 0) + 
                (aggregates["DE9"]["pit_withheld"] or 0), 2
            ),
            "less": 0.0,
            "total_taxes_due": round(
                (aggregates["DE9"]["unemployment_insurance_tax"] or 0) + 
                (aggregates["DE9"]["ett_tax"] or 0) + 
                (aggregates["DE9"]["sdi_tax"] or 0) + 
                (aggregates["DE9"]["pit_withheld"] or 0), 2
            ),
        }

        # Handle split dollars/cents for DE9
        for key in ["pit_wages", "pit_withheld", "ui_wages", "ui_tax", "ett_wages", "ett_tax", "sdi_wages", "sdi_tax", "subtotal", "less", "total_taxes_due"]:
            val = data.get(key, 0.0)
            d, c = split_dollars_cents(val)
            data[f"{key}_dollars"] = d
            data[f"{key}_cents"] = c

        data.update({
            "ui_rate": result.get("ui_rate", "3.4"), 
            "D1": result.get("ui_rate", "3.4"), 
            "D2": ui_w_d,
            "D2_cents": "",
            "ett_rate": result.get("ett_rate", "0.1"),
            "E1": result.get("ett_rate", "0.1"), 
            "sdi_rate": result.get("sdi_rate", "1.1"),
            "F1": result.get("sdi_rate", "1.1"), 
            "quarter": f"{quarter_idx + 1}",
            "year": f"{reference_date.year}",
            "quarter_ended": f"{(quarter_idx + 1) * 3}/{31 if (quarter_idx + 1) in [1, 4] else 30}/{reference_date.year}",

            "employees": []
        })

        employee_aggregates = result.get("employee_aggregates", [])
        ssn_by_employee_id = {}
        for payslip in payslips.select_related("employee_id"):
            employee = payslip.employee_id
            if employee and employee.id not in ssn_by_employee_id:
                ssn_by_employee_id[employee.id] = getattr(employee, "ssn", "")

        data["employees"] = [
            {
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "ssn": ssn_by_employee_id.get(row.get("employee_id"), ""),
                "total_wages": round(float(row.get("total_wages", 0.0) or 0.0), 2),
                "pit_wages": round(float(row.get("pit_wages", 0.0) or 0.0), 2),
                "pit_withheld": round(float(row.get("pit_withheld", 0.0) or 0.0), 2),
            }
            for row in employee_aggregates
        ]
        return data

    def _fill_tax_forms(form_data, form_types):
        from report.forms.tax_forms import TaxFormFiller

        filler = TaxFormFiller()
        filled_forms = {}
        for form_type in form_types:
            try:
                pdf_bytes = filler.fill_form(form_type, form_data)
            except Exception:
                continue
            if pdf_bytes:
                filled_forms[form_type] = pdf_bytes
        return filled_forms

    @login_required
    @permission_required(perm="payroll.view_payslip")
    def download_tax_forms(request):
        import io
        import zipfile
        from django.http import HttpResponse

        form_data = _build_tax_form_data(request)
        filled_forms = _fill_tax_forms(form_data, TAX_FORM_TYPES)

        zip_buffer = io.BytesIO()
        has_files = bool(filled_forms)
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for form_type, pdf_bytes in filled_forms.items():
                zf.writestr(f"Form_{form_type}.pdf", pdf_bytes)

        if not has_files:
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("README.txt", "No PDF templates found in report/static/report/forms/. Please add f941.pdf, f940.pdf, etc.")

        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        response['Content-Disposition'] = 'attachment; filename="tax_forms.zip"'
        return response

    @login_required
    @permission_required(perm="payroll.view_payslip")
    def preview_tax_form(request):
        form_type = str(request.GET.get("form_type", "941")).strip().upper()
        if form_type not in TAX_FORM_TYPES:
            return JsonResponse(
                {"success": False, "message": f"Unsupported form_type: {form_type}"},
                status=400,
            )

        form_data = _build_tax_form_data(request)
        filled_forms = _fill_tax_forms(form_data, [form_type])
        pdf_bytes = filled_forms.get(form_type)
        if not pdf_bytes:
            return JsonResponse(
                {"success": False, "message": f"Unable to generate PDF for form {form_type}."},
                status=404,
            )

        return render(
            request,
            "report/pdf_editor.html",
            {"pdf_base64": base64.b64encode(pdf_bytes).decode("ascii")},
        )
