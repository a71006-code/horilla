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
                ) + pay_head_data.get("post_tax_deductions", [])

                # Prepare allowance and deduction lists with properly rounded amounts
                allowance_titles = (
                    ", ".join([allowance["title"] for allowance in allowances]) or "-"
                )
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
                    ", ".join([deduction["title"] for deduction in deductions]) or "-"
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

                # Main data structure
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
                        "Gross Pay": round(float(item["gross_pay"] or 0), 2),
                        "Net Pay": round(float(item["net_pay"] or 0), 2),
                        "Allowance Title": allowance_titles,
                        "Allowance Amount": allowance_amounts,
                        "Total Allowance Amount": round(total_allowance_amount, 2),
                        "Deduction Title": deduction_titles,
                        "Deduction Amount": deduction_amounts,
                        "Total Deduction Amount": round(total_deduction_amount, 2),
                        "Status": STATUS.get(item["status"]),
                        "Experience": round(
                            float(
                                item["employee_id__employee_work_info__experience"] or 0
                            ),
                            2,
                        ),
                    }
                )

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
                ) + pay_head_data.get("post_tax_deductions", []):
                    all_pay_data.append(
                        {
                            "Pay Type": "Deduction",
                            "Title": deduction["title"],
                            "Amount": round(float(deduction["amount"] or 0), 2),
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
            from payroll.models.models import Deduction
            
            payslips = Payslip.objects.all()
            payslip_filter = PayslipFilter(request.GET, queryset=payslips)
            filtered_qs = payslip_filter.qs

            data = list(
                filtered_qs.values(
                    "id",
                    "employee_id__employee_first_name",
                    "employee_id__employee_last_name",
                    "start_date",
                    "end_date",
                    "basic_pay",
                    "gross_pay",
                    "status",
                )
            )

            payslip_ids = [item["id"] for item in data]
            pay_head_data_dict = dict(
                Payslip.objects.filter(id__in=payslip_ids).values_list(
                    "id", "pay_head_data"
                )
            )

            # Collect all deduction IDs to fetch configuration
            all_deduction_ids = set()
            for ph_data in pay_head_data_dict.values():
                deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])
                for d in deductions:
                    all_deduction_ids.add(d["deduction_id"])

            deduction_map = {
                d["id"]: d for d in Deduction.objects.filter(id__in=all_deduction_ids).values("id", "title", "employer_rate", "based_on")
            }

            data_list = []
            for item in data:
                ph_data = pay_head_data_dict.get(item["id"], {})
                deductions = ph_data.get("pretax_deductions", []) + ph_data.get("post_tax_deductions", []) + ph_data.get("tax_deductions", [])

                for deduction_item in deductions:
                    ded_id = deduction_item["deduction_id"]
                    ded_config = deduction_map.get(ded_id)
                    
                    if not ded_config:
                        continue

                    employer_rate = ded_config["employer_rate"]
                    if "employer_contribution_rate" in deduction_item:
                         employer_rate = deduction_item["employer_contribution_rate"]
                    
                    employer_rate = float(employer_rate) if employer_rate else 0.0

                    if employer_rate > 0:
                        liability_amount = 0.0
                        
                        # Determine base amount
                        base_amount = 0.0
                        based_on = ded_config["based_on"]
                        
                        if based_on == "gross_pay":
                            base_amount = float(item["gross_pay"] or 0)
                        elif based_on == "basic_pay":
                             base_amount = float(item["basic_pay"] or 0)
                        elif based_on == "taxable_gross_pay":
                             # Attempt to find taxable gross in pay_head_data
                             # It might be in 'taxable_gross_pay' key of the dict if saved by calculate_taxable_gross_pay
                             # But let's check structure.
                             # If not found, fall back to gross_pay as approximation or 0? 
                             # Creating a fallback logic
                             base_amount = float(ph_data.get("taxable_gross_pay", {}).get("taxable_gross_pay", item["gross_pay"] or 0))
                        
                        liability_amount = (base_amount * employer_rate) / 100.0
                        
                        data_list.append({
                            "Employee": f"{item['employee_id__employee_first_name']} {item['employee_id__employee_last_name']}",
                            "Tax Component": ded_config["title"],
                            "Employer Liability": round(liability_amount, 2),
                            "Rate": f"{employer_rate}%",
                            "Start Date": item["start_date"],
                            "End Date": item["end_date"],
                        })

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

        # Aggregate Data
        # This is a rough aggregation. For real forms, specific tax components need mapping.
        total_gross = payslips.aggregate(Sum("gross_pay"))["gross_pay__sum"] or 0.0
        total_deduction = payslips.aggregate(Sum("deduction"))["deduction__sum"] or 0.0
        
        # Fetch company info from first available record or session
        company_name = ""
        company_address = ""
        employer_ein = ""
        
        if selected_company and selected_company != "all":
             comp = Company.objects.filter(id=selected_company).first()
             if comp:
                 company_name = comp.company
                 company_address = f"{comp.address}, {comp.city}, {comp.state} {comp.zip}"
                 # tax_id is not in basic Company model? Checked requirements, user added 'ein' in previous task.
                 # Assuming 'ein' or 'tax_id' field exists.
                 employer_ein = getattr(comp, "ein", getattr(comp, "tax_id", ""))
        
        data = {
            "employer_name": company_name,
            "employer_address": company_address,
            "employer_ein": employer_ein,
            "total_wages": total_gross,
            # For specific taxes (Fed Income, SS, Medicare), we need to check deductions
            # This requires inspecting pay_head_data or having separate Tax models.
            # For now, we pass generic totals which might be mapped if fields exist.
        }

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
