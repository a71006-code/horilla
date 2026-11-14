"""Form 941 and DE 9 preview lines for reviewed 2026 California payroll."""

from collections import defaultdict
from decimal import ROUND_HALF_UP

from payroll.methods.us_ca_contributions import US_CA_CONTRIBUTION_RULES_2026
from report.forms.recorded_wages import ZERO


def _tax(wages, rate):
    return (wages * rate).quantize(ZERO, rounding=ROUND_HALF_UP)


def build_adjusted_941_schedule(recorded, schedule, adjustments, expected_tax):
    """Use preparer-allocated adjustments and verify the schedule ties to line 12."""
    if schedule not in ("monthly", "semiweekly"):
        return []
    by_date = defaultdict(lambda: ZERO, recorded)
    for day, adjustment in adjustments.items():
        by_date[day] += adjustment
    amounts = defaultdict(lambda: ZERO)
    for day, amount in by_date.items():
        period = day.isoformat()[:7] if schedule == "monthly" else day.isoformat()
        amounts[period] += amount
    if any(amount < ZERO for amount in amounts.values()):
        raise ValueError("Adjusted liability cannot be negative in any reporting period.")
    if sum(amounts.values(), ZERO) != expected_tax:
        return []
    label = "Adjusted monthly liability" if schedule == "monthly" else "Adjusted Schedule B liability"
    return [(period, label, amount) for period, amount in sorted(amounts.items())]


def build_quarterly_return_rows(worksheet, *, adjustments):
    totals = worksheet["totals"]
    rules = US_CA_CONTRIBUTION_RULES_2026
    ss_tips = adjustments.get("social_security_tips") or ZERO
    if not ZERO <= ss_tips <= totals["social_security_wages"]:
        raise ValueError("Social Security tips cannot exceed the recorded Social Security wage base.")
    ss_wages = totals["social_security_wages"] - ss_tips
    medicare_wages = totals["medicare_wages"]
    additional_wages = totals["additional_medicare_wages"]
    ss_tax = _tax(ss_wages, 2 * rules.social_security_rate)
    ss_tip_tax = _tax(ss_tips, 2 * rules.social_security_rate)
    medicare_tax = _tax(medicare_wages, 2 * rules.medicare_rate)
    additional_tax = _tax(additional_wages, rules.additional_medicare_rate)
    fica = ss_tax + ss_tip_tax + medicare_tax + additional_tax
    notice_tax = adjustments.get("federal_tip_notice") or ZERO
    before_adjustments = totals["federal_income_tax"] + fica + notice_tax
    fractions = adjustments.get("fractions_of_cents") or ZERO
    sick_pay = adjustments.get("sick_pay") or ZERO
    tips_life = adjustments.get("tips_life") or ZERO
    after_adjustments = before_adjustments + fractions + sick_pay + tips_life
    research_credit = adjustments.get("research_credit") or ZERO
    if not ZERO <= research_credit <= after_adjustments:
        raise ValueError("Form 941 adjustments or credits exceed the total tax.")
    federal_tax = after_adjustments - research_credit
    prior_credit = adjustments.get("federal_prior_credit") or ZERO
    deposits = worksheet["federal_deposits"] + prior_credit
    federal_balance = federal_tax - deposits
    federal = [
        ("2", "Wages, tips, and other compensation", totals["federal_income_tax_wages"]),
        ("3", "Federal income tax withheld", totals["federal_income_tax"]),
        ("5a col. 1", "Taxable Social Security wages", ss_wages),
        ("5a col. 2", "Social Security tax", ss_tax),
        ("5b col. 1", "Taxable Social Security tips already included in recorded wages", ss_tips),
        ("5b col. 2", "Social Security tax on tips", ss_tip_tax),
        ("5c col. 1", "Taxable Medicare wages", medicare_wages),
        ("5c col. 2", "Medicare tax", medicare_tax),
        ("5d col. 1", "Wages subject to Additional Medicare Tax", additional_wages),
        ("5d col. 2", "Additional Medicare Tax", additional_tax),
        ("5e", "Total Social Security and Medicare taxes", fica),
        ("5f", "Tax due on unreported tips under IRS notice", notice_tax),
        ("6", "Total taxes before adjustments", before_adjustments),
        ("7", "Fractions-of-cents adjustment", fractions),
        ("8", "Sick pay adjustment", sick_pay),
        ("9", "Tips and group-term life insurance adjustment", tips_life),
        ("10", "Total taxes after adjustments", after_adjustments),
        ("11", "Qualified small business payroll tax credit", research_credit),
        ("12", "Total taxes after adjustments and nonrefundable credits", federal_tax),
        ("13", "Recorded deposits and applied credits", deposits),
        ("14", "Balance due", max(federal_balance, ZERO)),
        ("15a", "Overpayment", max(-federal_balance, ZERO)),
        ("Schedule", "Line 12 less recorded pay-date liability", federal_tax - worksheet["federal_tax_before_adjustments"]),
    ]

    california = [
        ("UI wages", "Taxable unemployment insurance wages", totals["ca_ui_wages"]),
        ("ETT wages", "Recorded taxable employment training wages", totals["ca_ett_wages"]),
        ("SDI wages", "Taxable state disability insurance wages", totals["ca_sdi_wages"]),
        ("SDI withheld", "State disability insurance withheld", totals["employee_ca_sdi"]),
        ("PIT withheld", "California personal income tax withheld", totals["ca_pit_withheld"]),
        ("Deposits", "Confirmed EDD deposits", worksheet["california_deposits"]),
    ]
    if not worksheet["missing_de9c_check_count"]:
        california.insert(0, ("Subject wages", "Total subject wages paid this quarter", worksheet["edd_subject_wages"]))
        ui_rate = adjustments.get("ui_rate_percent")
        ett_rate = adjustments.get("ett_rate_percent")
        if ui_rate is not None and ett_rate is not None:
            if ett_rate and totals["ca_ett_wages"] != totals["ca_ui_wages"]:
                california.append((
                    "ETT wage base difference", "Reconcile recorded ETT and UI wages before calculating the balance",
                    totals["ca_ett_wages"] - totals["ca_ui_wages"],
                ))
                return {"941": federal, "DE 9": california}
            ui_tax = _tax(totals["ca_ui_wages"], ui_rate / 100)
            ett_tax = _tax(totals["ca_ui_wages"], ett_rate / 100)
            sdi_tax = _tax(totals["ca_sdi_wages"], rules.ca_sdi_rate)
            subtotal = ui_tax + ett_tax + sdi_tax + totals["ca_pit_withheld"]
            unrefunded_sdi = adjustments.get("unrefunded_sdi") or ZERO
            edd_credit = adjustments.get("edd_credit") or ZERO
            balance = subtotal + unrefunded_sdi - worksheet["california_deposits"] - edd_credit
            california.extend([
                ("UI", "Employer UI contributions", ui_tax),
                ("ETT", "Employment training tax", ett_tax),
                ("SDI tax", "SDI liability on quarterly taxable wages", sdi_tax),
                ("SDI difference", "SDI liability less recorded withholding", sdi_tax - totals["employee_ca_sdi"]),
                ("Subtotal", "UI, ETT, SDI and PIT", subtotal),
                ("Unrefunded SDI", "Erroneous SDI deductions still to remit", unrefunded_sdi),
                ("Applied credit", "Other verified EDD credit applied to the quarter", edd_credit),
                ("Tax due", "Tax due", max(balance, ZERO)),
                ("Overpayment", "Overpayment", max(-balance, ZERO)),
            ])
    return {"941": federal, "DE 9": california}
