"""Collect reviewed payroll register inputs for a California paycheck."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django import forms

from base.models import Company
from payroll.methods.ca_payroll_check import calculate_ca_payroll_check
from payroll.methods.ca_withholding import CaliforniaDE4
from payroll.methods.federal_withholding import FederalW4
from payroll.methods.us_ca_contributions import CaliforniaEmployerNotice, SubjectWages


WAGE_LABELS = {
    "social_security": "Social Security",
    "medicare": "Medicare",
    "ca_sdi": "California SDI",
    "ca_ui": "California UI",
    "ca_ett": "California ETT",
    "futa": "Federal unemployment (FUTA)",
}


def amount_field(*, required=True, label=None):
    return forms.DecimalField(
        required=required, label=label, min_value=0, max_digits=14, decimal_places=2,
    )


class LegacyEddReviewForm(forms.Form):
    subject_wages = amount_field(label="California EDD total subject wages before caps")
    plan_code = forms.ChoiceField(
        label="Verified EDD wage plan code", choices=(("", "Select a plan"), ("S", "S · Standard UI and SDI account")),
    )
    verified = forms.BooleanField(label="I verified these EDD entries against the payroll register.")


class CaliforniaPaycheckReviewForm(forms.Form):
    employer = forms.ModelChoiceField(queryset=Company._base_manager.none())
    pay_date = forms.DateField(label="Actual payment date", widget=forms.DateInput(attrs={"type": "date"}))
    pay_frequency = forms.ChoiceField(choices=(
        ("weekly", "Weekly"), ("biweekly", "Every two weeks"),
        ("semi_monthly", "Twice a month"), ("monthly", "Monthly"),
    ))
    federal_income_tax_wages = amount_field(label="Federal income tax wages")
    ca_pit_wages = amount_field(label="California income tax wages")
    ca_edd_subject_wages = amount_field(label="California EDD total subject wages before caps")
    ca_wage_plan_code = forms.ChoiceField(
        label="Verified EDD wage plan code", choices=(("", "Select a plan"), ("S", "S · Standard UI and SDI account")),
    )
    other_employee_deductions = amount_field(required=False, label="Other employee deductions")
    ui_rate = forms.DecimalField(label="UI rate from DE 2088 (%)", min_value=0, max_value=100, max_digits=7, decimal_places=4)
    ett_rate = forms.DecimalField(label="ETT rate from DE 2088 (%)", min_value=0, max_value=100, max_digits=7, decimal_places=4)
    federal_status = forms.ChoiceField(choices=(
        ("", "No W-4 on file for a new employee"),
        ("single_or_married_filing_separately", "Single or married filing separately"),
        ("married_filing_jointly", "Married filing jointly"),
        ("head_of_household", "Head of household"),
        ("exempt", "Certified exempt from federal income tax withholding"),
    ), required=False)
    w4_year = forms.IntegerField(label="Applicable W-4 year", min_value=2020, max_value=2026, required=False)
    multiple_jobs = forms.BooleanField(label="W-4 Step 2(c) checked", required=False)
    annual_credits = amount_field(required=False, label="W-4 Step 3 annual credits")
    annual_other_income = amount_field(required=False, label="W-4 Step 4(a) other income")
    annual_deductions = amount_field(required=False, label="W-4 Step 4(b) deductions")
    federal_extra = amount_field(required=False, label="W-4 Step 4(c) extra withholding per check")
    ca_status = forms.ChoiceField(choices=(
        ("single_or_dual_income", "Single, dual income, or no valid DE 4"),
        ("married_one_income", "Married with one income"),
        ("head_of_household", "Head of household"),
    ))
    regular_allowances = forms.IntegerField(label="DE 4 regular allowances", min_value=0, max_value=999, required=False)
    estimated_allowances = forms.IntegerField(label="DE 4 estimated deduction allowances", min_value=0, max_value=999, required=False)
    ca_extra = amount_field(required=False, label="DE 4 extra withholding per check")
    verified_payment = forms.BooleanField(
        label="I verified the employer, payment date, wage bases and calculated taxes against the payroll register.",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employer"].queryset = Company._base_manager.order_by("company", "pk")
        for key, label in WAGE_LABELS.items():
            self.fields[f"wages_{key}"] = amount_field(label=f"{label} wages this check")
            self.fields[f"prior_{key}"] = amount_field(label=f"{label} wages previously paid this year")

    def clean_pay_date(self):
        day = self.cleaned_data["pay_date"]
        if day.year != 2026 or day > datetime.now(ZoneInfo("America/Los_Angeles")).date():
            raise forms.ValidationError("Enter an actual 2026 California payment date that has passed or is today.")
        return day

    def clean(self):
        data = super().clean()
        adjustments = ("multiple_jobs", "annual_credits", "annual_other_income", "annual_deductions", "federal_extra")
        if not data.get("federal_status") and (data.get("w4_year") or any(data.get(key) for key in adjustments)):
            self.add_error("federal_status", "Select the filing status on the W-4 for these entries.")
        elif data.get("federal_status") and not data.get("w4_year"):
            self.add_error("w4_year", "Enter the year of the W-4 used for this payment.")
        return data

    def calculate(self, *, gross_pay):
        data = self.cleaned_data
        zero = Decimal("0.00")
        w4 = None
        status = data["federal_status"]
        if status:
            w4 = FederalW4(
                form_year=data["w4_year"], filing_status=None if status == "exempt" else status,
                exempt=status == "exempt", multiple_jobs=data["multiple_jobs"],
                annual_credits=data["annual_credits"] or zero,
                annual_other_income=data["annual_other_income"] or zero,
                annual_deductions=data["annual_deductions"] or zero,
                extra_withholding=data["federal_extra"] or zero,
            )
        return calculate_ca_payroll_check(
            pay_date=data["pay_date"], pay_frequency=data["pay_frequency"],
            gross_pay=Decimal(str(gross_pay)), federal_income_tax_wages=data["federal_income_tax_wages"],
            ca_pit_wages=data["ca_pit_wages"],
            ca_edd_subject_wages=data["ca_edd_subject_wages"], ca_wage_plan_code=data["ca_wage_plan_code"],
            current_subject_wages=SubjectWages(**{key: data[f"wages_{key}"] for key in WAGE_LABELS}),
            prior_ytd_subject_wages=SubjectWages(**{key: data[f"prior_{key}"] for key in WAGE_LABELS}),
            employer_notice=CaliforniaEmployerNotice(
                tax_year=data["pay_date"].year, ui_rate=data["ui_rate"] / 100,
                ett_rate=data["ett_rate"] / 100,
            ),
            w4=w4, de4=CaliforniaDE4(
                filing_status=data["ca_status"], regular_allowances=data["regular_allowances"] or 0,
                estimated_allowances=data["estimated_allowances"] or 0,
                extra_withholding=data["ca_extra"] or zero,
            ),
            other_employee_deductions=data["other_employee_deductions"] or zero,
        )
