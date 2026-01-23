"""
Module: payroll.tax_calc

This module contains a function for calculating the taxable amount for an employee
based on their contract details and income information.
"""

import datetime
import logging

from payroll.methods.methods import (
    compute_yearly_taxable_amount,
    convert_year_tax_to_period,
)
from payroll.methods.payslip_calc import (
    calculate_gross_pay,
    calculate_taxable_gross_pay,
)
from payroll.models.models import Contract, Deduction, Payslip
from payroll.models.tax_models import TaxBracket
from django.db.models import Sum, Q

logger = logging.getLogger(__name__)


def calculate_taxable_amount(**kwargs):
    """Calculate the taxable amount for a given employee within a specific period.

    Args:
        employee (int): The ID of the employee.
        start_date (datetime.date): The start date of the period.
        end_date (datetime.date): The end date of the period.
        allowances (int): The number of allowances claimed by the employee.
        total_allowance (float): The total allowance amount.
        basic_pay (float): The basic pay amount.
        day_dict (dict): A dictionary containing specific day-related information.

    Returns:
        float: The federal tax amount for the specified period.
    """
    employee = kwargs["employee"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    basic_pay = kwargs["basic_pay"]
    contract = Contract.objects.filter(
        employee_id=employee, contract_status="active"
    ).first()
    filing = contract.filing_status
    if not filing:
        return 0
    federal_tax_for_period = 0
    tax_brackets = TaxBracket.objects.filter(filing_status_id=filing).order_by(
        "min_income"
    )
    num_days = (end_date - start_date).days + 1
    calculation_functions = {
        "taxable_gross_pay": calculate_taxable_gross_pay,
        "gross_pay": calculate_gross_pay,
    }
    based = filing.based_on
    if based in calculation_functions:
        calculation_function = calculation_functions[based]
        income = calculation_function(**kwargs)
        income = float(income[based])
    else:
        income = float(basic_pay)

    year = end_date.year
    check_start_date = datetime.date(year, 1, 1)
    check_end_date = datetime.date(year, 12, 31)
    total_days = (check_end_date - check_start_date).days + 1
    yearly_income = income / num_days * total_days
    yearly_income = compute_yearly_taxable_amount(income, yearly_income)
    yearly_income = round(yearly_income, 2)
    federal_tax = 0
    if filing is not None and not filing.use_py:
        brackets = [
            {
                "rate": item["tax_rate"],
                "min": item["min_income"],
                "max": min(item["max_income"], yearly_income),
            }
            for item in tax_brackets.values("tax_rate", "min_income", "max_income")
        ]
        filterd_brackets = []
        for bracket in brackets:
            if bracket["max"] > bracket["min"]:
                bracket["diff"] = bracket["max"] - bracket["min"]
                bracket["calculated_rate"] = (bracket["rate"] / 100) * bracket["diff"]
                filterd_brackets.append(bracket)
                continue
            break
        federal_tax = sum(bracket["calculated_rate"] for bracket in filterd_brackets)

    elif filing.use_py:
        code = filing.python_code
        code = code.replace("print(", "pass_print(")
        pass_print = """
def pass_print(*args, **kwargs):
    return None
"""
        code = pass_print + code
        code = code.replace("  formated_result(", "#  formated_result(")
        local_vars = {}
        exec(code, {}, local_vars)
        try:
            federal_tax = local_vars["calculate_federal_tax"](yearly_income)
        except Exception as e:
            logger.error(e)

    if federal_tax and (tax_brackets.exists() or filing.use_py):
        # W-4 Step 3: Depedents/Credits (Annual Reduction)
        # Look for a deduction named "Federal Tax Credit"
        credit_deduction = Deduction.objects.filter(
            specific_employees=employee,
            title__iexact="Federal Tax Credit"
        ).first()

        if credit_deduction and credit_deduction.amount:
             # Subtract credit from ANNUAL tax
             # Ensure tax doesn't go below zero
             federal_tax = max(0, federal_tax - credit_deduction.amount)

        daily_federal_tax = federal_tax / total_days
        federal_tax_for_period = daily_federal_tax * num_days

    federal_tax_for_period = convert_year_tax_to_period(
        federal_tax_for_period=federal_tax_for_period,
        yearly_tax=federal_tax,
        total_days=total_days,
        start_date=start_date,
        end_date=end_date,
    )

    # W-4 Step 4(c): Extra Withholding (Per Period Addition)
    # Look for a deduction named "Federal Extra Withholding"
    extra_withholding_deduction = Deduction.objects.filter(
        specific_employees=employee,
        title__iexact="Federal Extra Withholding"
    ).first()

    if extra_withholding_deduction and extra_withholding_deduction.amount:
        federal_tax_for_period += extra_withholding_deduction.amount

    # Additional Medicare Tax (0.9% on wages > $200,000 / $250,000)
    # 1. Get Previous YTD Gross Pay
    current_year = end_date.year
    previous_payslips = Payslip.objects.filter(
        employee_id=employee,
        start_date__year=current_year,
        status__in=["confirmed", "paid"]
    ).exclude(
        # Exclude current slip if it somehow exists (e.g. re-run)
        start_date=start_date,
        end_date=end_date
    )
    previous_ytd_gross = previous_payslips.aggregate(total=Sum("gross_pay"))["total"] or 0.0
    
    # 2. Add Current Pay
    # CORRECT: Use 'gross_pay' from kwargs (guaranteed by component_views.py)
    # If falling back, 'basic_pay' is safer than 'income' (which might be reduced taxable gross)
    current_period_gross = kwargs.get("gross_pay")
    if current_period_gross is None:
         # Fallback if called outside standard payroll loop
         current_period_gross = kwargs.get("basic_pay", 0.0)

    current_ytd_gross = previous_ytd_gross + current_period_gross

    # 3. Determine Threshold
    threshold_amount = 200000.0
    filing_status_str = str(filing).lower()
    if "married" in filing_status_str or "joint" in filing_status_str:
        threshold_amount = 250000.0
    
    # 4. Calculate Tax on Excess
    if current_ytd_gross > threshold_amount:
        # Amount exceeding threshold total
        total_excess = current_ytd_gross - threshold_amount
        # Amount that was ALREADY taxed in previous periods
        previous_excess = max(0, previous_ytd_gross - threshold_amount)
        # Amount to tax THIS period
        taxable_excess_this_period = total_excess - previous_excess
        
        additional_medicare_tax = taxable_excess_this_period * 0.009
        federal_tax_for_period += additional_medicare_tax

    return federal_tax_for_period

