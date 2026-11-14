"""Draft quarterly tax totals from reviewed paid-check facts and deposits."""

import csv
from collections import defaultdict
from decimal import InvalidOperation
from io import StringIO

from report.forms.recorded_wages import ZERO as _ZERO, recorded_amount as _amount

_CONTRIBUTION_FIELDS = (
    "employee_social_security", "employer_social_security", "employee_medicare",
    "employer_medicare", "employee_additional_medicare", "employee_ca_sdi",
    "employer_ca_ui", "employer_ca_ett",
)
_WAGE_FIELDS = ("social_security", "medicare", "additional_medicare", "ca_sdi", "ca_ui", "ca_ett")


def build_quarterly_worksheet(checks, deposits):
    """Aggregate checks already selected by employer and actual paid quarter.

    This is a reconciliation worksheet. It does not establish quarter
    completeness or calculate adjustments, credits, or the deposit schedule.
    """
    totals = {
        **dict.fromkeys(_CONTRIBUTION_FIELDS, _ZERO),
        **{f"{key}_wages": _ZERO for key in _WAGE_FIELDS},
        "federal_income_tax_wages": _ZERO, "federal_income_tax": _ZERO,
        "ca_pit_wages": _ZERO, "ca_pit_withheld": _ZERO,
    }
    employees = defaultdict(lambda: {"pit_wages": _ZERO, "pit_withheld": _ZERO})
    de9c = defaultdict(lambda: {"subject_wages": _ZERO, "pit_wages": _ZERO, "pit_withheld": _ZERO})
    missing_de9c_check_count = 0
    daily = defaultdict(lambda: _ZERO)
    monthly = defaultdict(lambda: _ZERO)
    check_count = 0
    for check in checks:
        if check.facts_version != 1:
            raise ValueError("Unsupported paid-check facts version.")
        try:
            facts = check.facts
            contributions = facts["contributions"]
            wages = contributions["taxable_wages"]
            amounts = {key: _amount(contributions[key]) for key in _CONTRIBUTION_FIELDS}
            for key, amount in amounts.items():
                totals[key] += amount
            for key in _WAGE_FIELDS:
                totals[f"{key}_wages"] += _amount(wages[key])
            for key in ("federal_income_tax_wages", "federal_income_tax", "ca_pit_wages", "ca_pit_withheld"):
                totals[key] += _amount(facts[key])
            federal = _amount(facts["federal_income_tax"]) + sum(
                amounts[key] for key in _CONTRIBUTION_FIELDS[:5]
            )
            employees[check.employee_id]["pit_wages"] += _amount(facts["ca_pit_wages"])
            employees[check.employee_id]["pit_withheld"] += _amount(facts["ca_pit_withheld"])
            subject_wages = facts.get("ca_edd_subject_wages")
            plan_code = facts.get("ca_wage_plan_code")
            supplement = getattr(check, "edd_review", None)
            if subject_wages is None and plan_code is None and supplement is not None:
                subject_wages = supplement.subject_wages
                plan_code = supplement.plan_code
            if subject_wages is None or plan_code is None:
                missing_de9c_check_count += 1
            else:
                if plan_code != "S":
                    raise ValueError("Unsupported EDD wage plan code.")
                subject_wages = _amount(subject_wages)
                if subject_wages < max(_amount(wages[key]) for key in ("ca_ui", "ca_ett", "ca_sdi")):
                    missing_de9c_check_count += 1
                else:
                    row = de9c[(check.employee_id, plan_code)]
                    row["subject_wages"] += subject_wages
                    row["pit_wages"] += _amount(facts["ca_pit_wages"])
                    row["pit_withheld"] += _amount(facts["ca_pit_withheld"])
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise ValueError("A recorded check has missing or invalid tax facts.") from error
        daily[check.paid_on] += federal
        monthly[check.paid_on.month] += federal
        check_count += 1

    deposit_totals = {"federal_941": _ZERO, "ca_de9": _ZERO}
    for deposit in deposits:
        if deposit.kind not in deposit_totals:
            raise ValueError("A deposit was assigned to an unsupported quarterly return.")
        deposit_totals[deposit.kind] += _amount(deposit.amount)

    return {
        "check_count": check_count,
        "totals": totals,
        "employees": dict(employees),
        "missing_de9c_check_count": missing_de9c_check_count,
        "de9c_rows": [
            {"employee_id": employee, "plan_code": plan_code, **amounts}
            for (employee, plan_code), amounts in sorted(de9c.items())
        ],
        "edd_subject_wages": sum((row["subject_wages"] for row in de9c.values()), _ZERO),
        "daily_federal_liability": dict(sorted(daily.items())),
        "monthly_federal_liability": dict(sorted(monthly.items())),
        "federal_tax_before_adjustments": sum(daily.values(), _ZERO),
        "california_tax_before_adjustments": sum(
            totals[key] for key in ("employee_ca_sdi", "employer_ca_ui", "employer_ca_ett", "ca_pit_withheld")
        ),
        "federal_deposits": deposit_totals["federal_941"],
        "california_deposits": deposit_totals["ca_de9"],
    }


def write_quarterly_worksheet_csv(worksheet, *, employer_id, quarter, current_review=None, return_rows=None):
    """Export review figures without names or tax identifiers."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("DRAFT — recorded checks only; for review", "Record or period", "Item", "Amount"))
    writer.writerow(("Scope", employer_id, "Quarter", f"2026 Q{quarter}"))
    writer.writerow(("Scope", "", "Recorded check count", worksheet["check_count"]))
    if current_review is None:
        writer.writerow(("Review", "Quarter", "Current reconciliation", "Not recorded or stale"))
    else:
        writer.writerow(("Review", "Quarter", "Recorded sources reconciled", "Draft only"))
        writer.writerow(("941 draft", "Quarter", "Verified liability schedule", current_review.get_deposit_schedule_display()))
        writer.writerow(("941 draft", "Quarter", "Line 1 headcount", current_review.federal_headcount))
        for month, count in enumerate(current_review.edd_headcounts, start=1):
            writer.writerow(("DE 9C draft", month, "Monthly headcount", count))
    for field, amount in worksheet["totals"].items():
        writer.writerow(("Payroll tax draft", "Quarter", field.replace("_", " "), f"{amount:.2f}"))
    for label, field in (
        ("Federal liability before adjustments and credits", "federal_tax_before_adjustments"),
        ("Recorded 941 deposits", "federal_deposits"),
        ("California liability before adjustments and credits", "california_tax_before_adjustments"),
        ("Recorded DE 9 deposits", "california_deposits"),
    ):
        writer.writerow(("Reconciliation", "Quarter", label, f"{worksheet[field]:.2f}"))
    for day, amount in worksheet["daily_federal_liability"].items():
        writer.writerow(("941 daily draft", day.isoformat(), "Recorded liability", f"{amount:.2f}"))
    for month, amount in worksheet["monthly_federal_liability"].items():
        writer.writerow(("941 monthly draft", month, "Recorded liability", f"{amount:.2f}"))
    writer.writerow(("DE 9C draft", "Quarter", "Checks missing subject wages or plan code", worksheet["missing_de9c_check_count"]))
    for row in worksheet["de9c_rows"]:
        employee_plan = f"{row['employee_id']} / {row['plan_code']}"
        for field, label in (("subject_wages", "Subject wages"), ("pit_wages", "PIT wages"), ("pit_withheld", "PIT withheld")):
            writer.writerow(("DE 9C draft", employee_plan, label, f"{row[field]:.2f}"))
    for report, rows in (return_rows or {}).items():
        for line, label, amount in rows:
            writer.writerow((f"{report} draft", line, label, f"{amount:.2f}"))
    return output.getvalue()
