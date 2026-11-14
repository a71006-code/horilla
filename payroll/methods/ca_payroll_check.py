"""Calculate a reviewable 2026 California paycheck from classified cash wages."""

from dataclasses import dataclass, fields
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from payroll.methods.ca_withholding import CaliforniaDE4, calculate_ca_withholding
from payroll.methods.federal_withholding import FederalW4, calculate_federal_withholding
from payroll.methods.us_ca_contributions import (
    US_CA_CONTRIBUTION_RULES_2026,
    CaliforniaEmployerNotice,
    Contributions,
    SubjectWages,
    calculate_us_ca_contributions,
)


@dataclass(frozen=True, kw_only=True)
class CaliforniaPaycheck:
    pay_date: date
    pay_frequency: str
    employer_notice: CaliforniaEmployerNotice
    gross_pay: Decimal
    federal_income_tax_wages: Decimal
    ca_pit_wages: Decimal
    subject_wages: SubjectWages
    prior_ytd_subject_wages: SubjectWages
    federal_income_tax: Decimal
    ca_pit_withheld: Decimal
    other_employee_deductions: Decimal
    contributions: Contributions
    ca_edd_subject_wages: Decimal | None = None
    ca_wage_plan_code: str | None = None

    @property
    def employee_tax_total(self) -> Decimal:
        tax = self.contributions
        return (
            self.federal_income_tax + self.ca_pit_withheld + tax.employee_social_security
            + tax.employee_medicare + tax.employee_additional_medicare + tax.employee_ca_sdi
        )

    @property
    def employer_tax_before_futa_credits(self) -> Decimal:
        tax = self.contributions
        return (
            tax.employer_social_security + tax.employer_medicare
            + tax.employer_ca_ui + tax.employer_ca_ett + tax.employer_futa_before_credits
        )

    @property
    def net_pay(self) -> Decimal:
        return self.gross_pay - self.employee_tax_total - self.other_employee_deductions


def _money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Pay and wage amounts must be nonnegative finite Decimals.")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_ca_payroll_check(
    *, pay_date: date, pay_frequency: str, gross_pay: Decimal,
    federal_income_tax_wages: Decimal, ca_pit_wages: Decimal,
    current_subject_wages: SubjectWages, prior_ytd_subject_wages: SubjectWages,
    employer_notice: CaliforniaEmployerNotice, w4: FederalW4 | None = None,
    de4: CaliforniaDE4 | None = None, other_employee_deductions: Decimal = Decimal("0"),
    ca_edd_subject_wages: Decimal | None = None, ca_wage_plan_code: str | None = None,
) -> CaliforniaPaycheck:
    """Calculate regular cash payroll from explicit wage bases and prior paid YTD.

    The caller classifies earnings and deductions before invoking this function.
    Prior wages must belong to the same employee, employer and calendar year.
    Employer contributions do not reduce employee net pay.
    """
    gross = _money(gross_pay)
    federal_wages = _money(federal_income_tax_wages)
    ca_wages = _money(ca_pit_wages)
    if ca_edd_subject_wages is not None:
        ca_edd_subject_wages = _money(ca_edd_subject_wages)
        if ca_wage_plan_code != "S" or ca_edd_subject_wages > gross:
            raise ValueError("Enter verified EDD subject wages within gross pay and standard wage plan code S.")
    elif ca_wage_plan_code is not None:
        raise ValueError("A wage plan code requires verified EDD subject wages.")
    subject_wages = SubjectWages(**{
        field.name: _money(getattr(current_subject_wages, field.name))
        for field in fields(SubjectWages)
    })
    paid_ytd = {}
    for field in fields(SubjectWages):
        amount = getattr(prior_ytd_subject_wages, field.name)
        paid_ytd[field.name] = _money(amount)
        if paid_ytd[field.name] != amount:
            raise ValueError("Prior paid wages must be in whole cents.")
    prior_wages = SubjectWages(**paid_ytd)
    if any(wages > gross for wages in (
        federal_wages, ca_wages,
        *(getattr(subject_wages, field.name) for field in fields(SubjectWages)),
    )):
        raise ValueError("Taxable cash wages cannot exceed gross pay.")

    result = CaliforniaPaycheck(
        pay_date=pay_date,
        pay_frequency=pay_frequency,
        employer_notice=employer_notice,
        gross_pay=gross,
        federal_income_tax_wages=federal_wages,
        ca_pit_wages=ca_wages,
        ca_edd_subject_wages=ca_edd_subject_wages,
        ca_wage_plan_code=ca_wage_plan_code,
        subject_wages=subject_wages,
        prior_ytd_subject_wages=prior_wages,
        federal_income_tax=calculate_federal_withholding(
            pay_date=pay_date, taxable_wages=federal_wages, pay_frequency=pay_frequency, w4=w4,
        ),
        ca_pit_withheld=calculate_ca_withholding(
            pay_date=pay_date, taxable_wages=ca_wages, pay_frequency=pay_frequency, de4=de4,
        ),
        other_employee_deductions=_money(other_employee_deductions),
        contributions=calculate_us_ca_contributions(
            pay_date=pay_date, current_subject_wages=subject_wages,
            prior_ytd_subject_wages=prior_wages,
            rules=US_CA_CONTRIBUTION_RULES_2026, employer_notice=employer_notice,
        ),
    )
    if ca_edd_subject_wages is not None:
        state_wages = result.contributions.taxable_wages
        if ca_edd_subject_wages < max(state_wages.ca_ui, state_wages.ca_ett, state_wages.ca_sdi):
            raise ValueError("EDD subject wages cannot be less than the California contribution wage bases.")
    if result.net_pay < 0:
        raise ValueError("Withholdings and employee deductions exceed gross pay.")
    return result
