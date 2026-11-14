"""Compare filed DE 9C employee wage lines with reviewed payroll."""

import csv
import re
from io import StringIO

from report.forms.recorded_wages import recorded_amount


# EDD DE 8300, Appendix G. Paid-check reviews currently support plan S.
WAGE_PLAN_CODES = frozenset("AJLPRSU")


def parse_filed_de9c(text, *, no_payroll=False):
    """Normalize an independent transcription for storage in JSON."""
    lines = [(number, line) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    if no_payroll:
        if lines:
            raise ValueError("Clear the employee rows when the filing reported no payroll.")
        return {}
    if not lines:
        raise ValueError("Enter the filed employee rows or confirm a no-payroll filing.")
    filed = {}
    unassigned_count = 0
    for number, line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) not in (3, 5):
            raise ValueError(f"Line {number} needs three columns, or five if including subject wages and wage plan code.")
        money = parts[1:4]
        if any(not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", amount) for amount in money):
            raise ValueError(f"Line {number} needs valid amounts in dollars and cents.")
        if parts[0] == "-":
            unassigned_count += 1
            employee_id = str(-unassigned_count)
        elif re.fullmatch(r"[0-9]{1,18}", parts[0]) and int(parts[0]) > 0:
            employee_id = str(int(parts[0]))
        else:
            raise ValueError(f"Line {number} needs a Horilla employee record ID or a dash for an unassigned employee.")
        if employee_id in filed:
            raise ValueError(f"Line {number} repeats an employee record ID. Combine all filed entries for the same employee.")
        row = {
            field: f"{recorded_amount(amount):.2f}"
            for field, amount in zip(("pit_wages", "pit_withheld", "subject_wages"), money)
        }
        if len(parts) == 5:
            plan_code = parts[4].upper()
            if plan_code not in WAGE_PLAN_CODES:
                raise ValueError(f"Line {number} needs a valid EDD wage plan code.")
            row["plan_code"] = plan_code
        filed[employee_id] = row
    return filed


def compare_filed_de9c(recorded, filed, *, recorded_edd=None):
    """Preserve missing rows separately from amounts that are actually zero."""
    filed_by_employee = {int(employee): values for employee, values in (filed or {}).items()}
    rows = []
    employee_ids = sorted(recorded.keys() | filed_by_employee.keys(), key=lambda employee: (employee < 0, abs(employee)))
    for employee_id in employee_ids:
        paid = recorded.get(employee_id)
        paid_edd = (recorded_edd or {}).get(employee_id, {})
        reported = filed_by_employee.get(employee_id)
        row = {"employee_id": employee_id if employee_id > 0 else f"Unassigned row {-employee_id}"}
        for field, name in (("pit_wages", "wages"), ("pit_withheld", "withheld")):
            paid_amount = paid[field] if paid is not None else None
            filed_amount = recorded_amount(reported[field]) if reported is not None else None
            row[f"recorded_{name}"] = paid_amount
            row[f"filed_{name}"] = filed_amount
            row[f"{name}_difference"] = (
                filed_amount - paid_amount if paid_amount is not None and filed_amount is not None else None
            )
        row["recorded_subject_wages"] = paid_edd.get("subject_wages")
        filed_subject = (reported or {}).get("subject_wages")
        row["filed_subject_wages"] = recorded_amount(filed_subject) if filed_subject is not None else None
        row["subject_wages_difference"] = (
            row["filed_subject_wages"] - row["recorded_subject_wages"]
            if row["filed_subject_wages"] is not None and row["recorded_subject_wages"] is not None else None
        )
        row["recorded_plan_code"] = paid_edd.get("plan_code")
        row["filed_plan_code"] = (reported or {}).get("plan_code")
        if filed is None:
            status = "Filed rows needed"
        elif paid is None:
            status = "Unexpected filed row"
        elif reported is None:
            status = "Missing from filing"
        elif row["wages_difference"] or row["withheld_difference"] or row["subject_wages_difference"]:
            status = "Amounts differ"
        elif row["filed_plan_code"] and row["recorded_plan_code"] and row["filed_plan_code"] != row["recorded_plan_code"]:
            status = "Wage plan differs"
        elif row["filed_plan_code"] and not paid_edd:
            status = "Recorded EDD fields needed"
        else:
            status = "Matched"
        rows.append({**row, "status": status})
    statuses = {row["status"] for row in rows}
    if filed is None:
        status = "Filed rows needed"
    elif statuses - {"Matched", "Recorded EDD fields needed"}:
        status = "Differences found"
    elif "Recorded EDD fields needed" in statuses:
        status = "Recorded EDD fields needed"
    else:
        status = "Matched"

    if filed is None:
        coverage = ""
    elif not filed:
        coverage = "No payroll filing"
    elif all("plan_code" in row for row in filed.values()):
        coverage = "PIT and EDD fields transcribed"
    elif any("plan_code" in row for row in filed.values()):
        coverage = "PIT fields and some EDD fields transcribed"
    else:
        coverage = "PIT wages and withholding only"
    return {"status": status, "coverage": coverage, "rows": rows}


def write_de9c_csv(comparison, *, employer_id, quarter):
    """Export only internal record IDs and comparison values."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("DE 9C employee reconciliation", "Employer record ID", "Quarter", "Status", "Filed coverage"))
    writer.writerow(("", employer_id, f"2026 Q{quarter}", comparison["status"], comparison["coverage"]))
    writer.writerow((
        "Employee record ID", "Status",
        "Recorded PIT wages", "Filed PIT wages", "PIT wages difference (filed minus recorded)",
        "Recorded PIT withheld", "Filed PIT withheld", "PIT withheld difference (filed minus recorded)",
        "Recorded subject wages", "Filed subject wages", "Subject wages difference (filed minus recorded)",
        "Recorded wage plan code", "Filed wage plan code",
    ))
    fields = (
        "recorded_wages", "filed_wages", "wages_difference",
        "recorded_withheld", "filed_withheld", "withheld_difference",
        "recorded_subject_wages", "filed_subject_wages", "subject_wages_difference",
    )
    for row in comparison["rows"]:
        values = [f"{row[field]:.2f}" if row[field] is not None else "" for field in fields]
        writer.writerow((row["employee_id"], row["status"], *values, row["recorded_plan_code"], row["filed_plan_code"]))
    return output.getvalue()
