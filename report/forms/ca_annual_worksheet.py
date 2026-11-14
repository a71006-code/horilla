"""Draft W-2, W-3 and FUTA totals from reviewed California payroll."""

import csv
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import StringIO

from payroll.methods.us_ca_contributions import US_CA_CONTRIBUTION_RULES_2026
from report.forms.recorded_wages import ZERO, recorded_amount


W2_FIELDS = {
    "box_1": "Box 1 · Federal income tax wages",
    "box_2": "Box 2 · Federal income tax withheld",
    "box_3": "Box 3 · Social Security wages",
    "box_4": "Box 4 · Employee Social Security withheld",
    "box_5": "Box 5 · Medicare wages and tips",
    "box_6": "Box 6 · Employee Medicare withheld, including Additional Medicare",
    "box_16": "Box 16 · California PIT wages",
    "box_17": "Box 17 · California PIT withheld",
}
CASDI_LABEL = "Box 14a · CASDI"
W2_REVIEW_FIELDS = {
    "box_7": "Box 7 · Social Security tips",
    "box_8": "Box 8 · Allocated tips",
    "box_10": "Box 10 · Dependent care benefits",
    "box_11": "Box 11 · Nonqualified plans",
    "box_12_tp": "Box 12 · Code TP (reported cash tips)",
    "box_12_tt": "Box 12 · Code TT (qualified overtime premium)",
    "box_12_other": "Box 12 · Other codes",
    "box_13": "Box 13 · Checkboxes",
    "box_14b": "Box 14b · Treasury Tipped Occupation Codes",
}
W3_REVIEW_FIELDS = {
    **{field: W2_REVIEW_FIELDS[field] for field in ("box_7", "box_8", "box_10", "box_11")},
    "box_12a": "Box 12a · Deferred compensation",
}
W3_DEFERRED_CODES = frozenset("D E F G H S Y AA BB EE".split())
W2_OTHER_CODES = frozenset(
    "A B C D E F G H J K L M N P Q R S T V W Y Z AA BB DD EE FF GG HH II TA".split()
)
FILED_COMPARISONS = {
    "box_1": ("Form 941 line 2", "W-3 box 1"),
    "box_2": ("Form 941 line 3", "W-3 box 2"),
    "box_3": ("Form 941 line 5a column 1", "W-3 box 3"),
    "box_5": ("Form 941 line 5c column 1", "W-3 box 5"),
    "box_7": ("Form 941 line 5b column 1", "W-3 box 7"),
    "box_16": ("DE 9C total PIT wages", "W-3 box 16"),
    "box_17": ("DE 9C total PIT withheld", "W-3 box 17"),
}
FILED_FICA_FIELDS = {
    "fica_tax": "Form 941 line 5e · Total Social Security and Medicare taxes",
    "fica_rounding": "Form 941 line 7 · Fractions-of-cents adjustment",
    "sick_pay_adjustment": "Form 941 line 8 · Sick pay adjustment",
    "tips_life_adjustment": "Form 941 line 9 · Tips and group-term life insurance adjustment",
}
SIGNED_FILED_FIELDS = FILED_FICA_FIELDS.keys() - {"fica_tax"}
FUTA_FIELDS = {
    "gross_pay": "Recorded gross cash pay",
    "subject_wages": "FUTA subject wages before annual cap",
    "above_wage_base": "FUTA subject wages above the annual cap",
    "taxable_wages": "FUTA taxable wages",
    "before_credits": "Gross FUTA tax before credits or adjustments",
}
FORM_940_LINES = {
    "3": "Total recorded payments",
    "4": "Payments exempt from FUTA",
    "5": "Payments above the annual wage base",
    "6": "Subtotal of exempt and excess payments",
    "7": "Taxable FUTA wages",
    "8": "FUTA tax before adjustments",
    "9": "Adjustment for all taxable FUTA wages excluded from state UI",
    "10": "Adjustment for partial exclusion or late state UI payments",
    "11": "Schedule A California credit reduction",
    "12": "Total FUTA tax after adjustments",
    "13": "Deposits and applied prior-year credit",
    "14": "Balance due",
    "15a": "Overpayment",
    "16a": "First-quarter liability",
    "16b": "Second-quarter liability",
    "16c": "Third-quarter liability",
    "16d": "Fourth-quarter liability",
    "17": "Total liability reported in Part 5",
}


def build_form_940_summary(
    worksheet, *, coverage, deposit_total, prior_credit, adjusted_amount=None,
    covered_wages=None, rate_percent=None, quarterly_liabilities=None,
):
    """Prepare the California-only cash-payroll summary using reviewed state inputs."""
    futa = worksheet["futa"]
    taxable = futa["taxable_wages"]
    exempt = futa["gross_pay"] - futa["subject_wages"]
    excess = futa["above_wage_base"]
    maximum_credit_rate = Decimal("0.054")
    base_rate = US_CA_CONTRIBUTION_RULES_2026.futa_rate_before_credits - maximum_credit_rate

    def cents(amount):
        return amount.quantize(ZERO, rounding=ROUND_HALF_UP)

    lines = dict.fromkeys(FORM_940_LINES)
    lines.update({
        "3": futa["gross_pay"], "4": exempt, "5": excess, "6": exempt + excess,
        "7": taxable, "8": cents(taxable * base_rate), "13": deposit_total + prior_credit,
    })
    if coverage == "excluded":
        if any(value is not None for value in (adjusted_amount, covered_wages, rate_percent)):
            raise ValueError("Leave Schedule A and line 10 blank when all taxable FUTA wages are excluded from state UI.")
        lines["9"] = cents(taxable * maximum_credit_rate)
    elif coverage in ("timely", "adjusted"):
        if coverage == "timely":
            if adjusted_amount is not None or covered_wages is not None:
                raise ValueError("Leave line 10 and covered wages blank when all taxable FUTA wages are covered and state UI was paid on time.")
            covered_wages = taxable
        elif adjusted_amount is None or covered_wages is None:
            raise ValueError("Enter the preparer's line 10 result and Schedule A covered wage base.")
        else:
            if not ZERO <= adjusted_amount <= cents(taxable * maximum_credit_rate) or not ZERO <= covered_wages <= taxable:
                raise ValueError("Line 10 or Schedule A wages exceed the amounts supported by recorded FUTA wages.")
            lines["10"] = adjusted_amount
        if rate_percent is not None:
            if not ZERO <= rate_percent <= Decimal("5.4"):
                raise ValueError("Enter the verified Schedule A rate as a percentage from 0 to 5.4.")
            if covered_wages and rate_percent:
                lines["11"] = cents(covered_wages * rate_percent / 100)
    else:
        raise ValueError("Choose the verified state unemployment coverage and payment situation.")

    status = ""
    if quarterly_liabilities is not None and coverage != "adjusted":
        raise ValueError("Enter preparer quarterly liabilities only for an adjusted Form 940.")
    if coverage != "excluded" and taxable and rate_percent is None:
        status = "Enter the final California Schedule A rate to calculate total tax and balance."
    else:
        liability = sum((lines[line] or ZERO for line in ("8", "9", "10", "11")), ZERO)
        lines["12"] = liability
        balance = liability - lines["13"]
        if balance > ZERO:
            lines["14"] = balance
        elif balance < ZERO:
            lines["15a"] = -balance
        if liability > Decimal("500.00"):
            if coverage == "adjusted":
                if quarterly_liabilities is None:
                    status = "Enter the preparer's quarterly liability figures for Part 5."
                elif len(quarterly_liabilities) != 4 or any(value < ZERO for value in quarterly_liabilities) or sum(quarterly_liabilities, ZERO) != liability:
                    raise ValueError("The four Part 5 liabilities must be nonnegative and add up to Form 940 line 12.")
                else:
                    lines.update(zip(("16a", "16b", "16c", "16d"), quarterly_liabilities))
                    lines["17"] = liability
            else:
                prior_liability = ZERO
                cumulative_wages = ZERO
                for quarter, line in enumerate(("16a", "16b", "16c"), 1):
                    cumulative_wages += worksheet["futa_quarters"][quarter]["taxable_wages"]
                    cumulative_tax = cents(cumulative_wages * base_rate)
                    if coverage == "excluded":
                        cumulative_tax += cents(cumulative_wages * maximum_credit_rate)
                    lines[line] = cumulative_tax - prior_liability or None
                    prior_liability = cumulative_tax
                lines["16d"] = liability - prior_liability or None
                lines["17"] = liability
        elif quarterly_liabilities is not None:
            raise ValueError("Leave Part 5 blank when Form 940 line 12 is $500 or less.")
    return {
        "lines": lines, "status": status, "covered_wages": covered_wages,
        "rate_percent": rate_percent, "prior_credit": prior_credit,
    }


def build_annual_worksheet(checks):
    """Aggregate one employer and paid calendar year, selected by the caller.

    The W-2 boxes here cover regular cash wages only. Report release still
    needs completeness, tax identity, reconciliation, and applicable special
    entries. FUTA totals intentionally omit state credits and credit reduction.
    """
    employee_totals = defaultdict(lambda: dict.fromkeys((*W2_FIELDS, "ca_sdi"), ZERO))
    employee_ss_quarters = defaultdict(lambda: dict.fromkeys(range(1, 5), ZERO))
    futa_by_employee = defaultdict(lambda: ZERO)
    futa_quarters = {quarter: dict.fromkeys(FUTA_FIELDS, ZERO) for quarter in range(1, 5)}
    w3_quarters = {
        quarter: dict.fromkeys((*FILED_COMPARISONS, "fica_employee_withheld"), ZERO) for quarter in futa_quarters
    }
    check_count = 0
    for check in checks:
        if check.facts_version != 1:
            raise ValueError("Unsupported paid-check facts version.")
        try:
            facts = check.facts
            taxes = facts["contributions"]
            wages = taxes["taxable_wages"]
            boxes = {
                "box_1": recorded_amount(facts["federal_income_tax_wages"]),
                "box_2": recorded_amount(facts["federal_income_tax"]),
                "box_3": recorded_amount(wages["social_security"]),
                "box_4": recorded_amount(taxes["employee_social_security"]),
                "box_5": recorded_amount(wages["medicare"]),
                "box_6": recorded_amount(taxes["employee_medicare"]) + recorded_amount(taxes["employee_additional_medicare"]),
                "box_16": recorded_amount(facts["ca_pit_wages"]),
                "box_17": recorded_amount(facts["ca_pit_withheld"]),
                "ca_sdi": recorded_amount(taxes["employee_ca_sdi"]),
            }
            gross = recorded_amount(facts["gross_pay"])
            subject = recorded_amount(facts["subject_wages"]["futa"])
            taxable = recorded_amount(wages["futa"])
            before_credits = recorded_amount(taxes["employer_futa_before_credits"])
            if not taxable <= subject <= gross:
                raise ValueError("Inconsistent FUTA wage bases.")
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise ValueError("A recorded check has missing or invalid year-end tax facts.") from error

        for box, amount in boxes.items():
            employee_totals[check.employee_id][box] += amount
        futa_by_employee[check.employee_id] += taxable
        rules = US_CA_CONTRIBUTION_RULES_2026
        if (
            employee_totals[check.employee_id]["box_3"] > rules.social_security_wage_cap
            or futa_by_employee[check.employee_id] > rules.futa_wage_cap
        ):
            raise ValueError(f"Recorded wages for employee record {check.employee_id} exceed an annual wage cap. Reconcile the prior paid wages used for those checks.")
        quarter_number = (check.paid_on.month - 1) // 3 + 1
        employee_ss_quarters[check.employee_id][quarter_number] += boxes["box_3"]
        for box in FILED_COMPARISONS.keys() & boxes.keys():
            w3_quarters[quarter_number][box] += boxes[box]
        w3_quarters[quarter_number]["fica_employee_withheld"] += boxes["box_4"] + boxes["box_6"]
        quarter = futa_quarters[quarter_number]
        quarter["gross_pay"] += gross
        quarter["subject_wages"] += subject
        quarter["above_wage_base"] += subject - taxable
        quarter["taxable_wages"] += taxable
        quarter["before_credits"] += before_credits
        check_count += 1

    return apply_w2_reviews({
        "check_count": check_count,
        "employees": dict(sorted(employee_totals.items())),
        "employee_ss_quarters": dict(employee_ss_quarters),
        "w3_quarters": w3_quarters,
        "futa": {field: sum((row[field] for row in futa_quarters.values()), ZERO) for field in FUTA_FIELDS},
        "futa_quarters": futa_quarters,
    }, {})


def apply_w2_reviews(worksheet, reviews):
    """Apply independently verified W-2 entries to a recorded-wage draft."""
    employees = {employee: row.copy() for employee, row in worksheet["employees"].items()}
    quarters = {quarter: row.copy() for quarter, row in worksheet["w3_quarters"].items()}
    w2_handoff = {}
    if reviews.keys() - employees.keys():
        raise ValueError("A reviewed employee is outside this employer and year.")
    for employee, row in employees.items():
        supplied = reviews.get(employee, {})
        entries = {field: supplied.get(field) for field in W2_REVIEW_FIELDS}
        tips = supplied.get("box_7_quarters")
        if tips is not None:
            entries["box_7"] = sum(tips, ZERO)
            if entries["box_7"] and (
                entries["box_12_tp"] is None or entries["box_7"] > entries["box_12_tp"]
            ):
                raise ValueError(f"Employee record {employee}: Social Security tips require at least that amount of code TP tips.")
            for quarter, amount in enumerate(tips, 1):
                if amount > worksheet["employee_ss_quarters"][employee][quarter]:
                    raise ValueError(f"Employee record {employee}: Q{quarter} tips exceed recorded Social Security wages.")
                row["box_3"] -= amount
                quarters[quarter]["box_3"] -= amount
                quarters[quarter]["box_7"] += amount
        w2_handoff[employee] = entries

    def total_if_verified(values):
        values = tuple(values)
        return sum(values, ZERO) if values and all(amount is not None for amount in values) else None

    w3_handoff = {
        field: total_if_verified(row[field] for row in w2_handoff.values())
        for field in W3_REVIEW_FIELDS if field != "box_12a"
    }
    w3_handoff["box_12a"] = total_if_verified(
        None if row["box_12_other"] is None else
        sum((amount for code, amount in row["box_12_other"].items() if code in W3_DEFERRED_CODES), ZERO)
        for row in w2_handoff.values()
    )
    return {
        **worksheet,
        "employees": employees,
        "w3_quarters": quarters,
        "w2_handoff": w2_handoff,
        "w3_handoff": w3_handoff,
        "w3_totals": {box: sum((row[box] for row in employees.values()), ZERO) for box in W2_FIELDS},
    }


def format_w2_entry(value):
    if value is None:
        return "Unresolved"
    if isinstance(value, dict):
        return ", ".join(f"{code} {amount:.2f}" for code, amount in value.items()) or "None"
    if isinstance(value, tuple):
        return ", ".join(value) or "None"
    return f"{value:.2f}"


def _expected_adjusted_fica(recorded):
    rules = US_CA_CONTRIBUTION_RULES_2026
    employer = ZERO
    for wages, rate in (
        (recorded["box_3"], rules.social_security_rate),
        (recorded["box_7"], rules.social_security_rate),
        (recorded["box_5"], rules.medicare_rate),
    ):
        share = wages * rate
        combined_tax = (2 * share).quantize(ZERO, rounding=ROUND_HALF_UP)
        employee_tax = share.quantize(ZERO, rounding=ROUND_HALF_UP)
        employer += combined_tax - employee_tax
    return recorded["fica_employee_withheld"] + employer


def compare_filed_quarters(worksheet, filed_totals):
    """Compare regular cash payroll to separately transcribed filed returns."""
    comparisons = {}
    for quarter, recorded in worksheet["w3_quarters"].items():
        if quarter not in filed_totals:
            comparisons[quarter] = {"status": "Missing", "rows": []}
            continue
        filed = filed_totals[quarter]
        rows = []
        for box, (filed_label, w3_label) in FILED_COMPARISONS.items():
            amount = recorded_amount(filed[box])
            rows.append((f"{filed_label} / {w3_label}", recorded[box], amount, recorded[box] - amount))
        has_fica = FILED_FICA_FIELDS.keys() <= filed.keys()
        needs_adjustment_review = False
        if has_fica:
            filed_fica = recorded_amount(filed["fica_tax"]) + recorded_amount(filed["fica_rounding"], allow_negative=True)
            recorded_fica = _expected_adjusted_fica(recorded)
            rows.append((
                "Form 941 lines 5e and 7 / Employee withholding plus statutory employer FICA",
                recorded_fica, filed_fica, recorded_fica - filed_fica,
            ))
            needs_adjustment_review = any(
                recorded_amount(filed[field], allow_negative=True)
                for field in ("sick_pay_adjustment", "tips_life_adjustment")
            )
        if needs_adjustment_review:
            status = "Needs adjustment review"
        elif any(difference for _, _, _, difference in rows):
            status = "Differences"
        else:
            status = "Matched" if has_fica else "FICA amounts missing"
        comparisons[quarter] = {
            "status": status,
            "rows": rows,
        }
    return comparisons


def write_annual_worksheet_csv(
    worksheet, *, deposit_total=ZERO, employer_id=None, year=None, filed_comparison=None, form_940=None,
    employee_de9c=None,
):
    """A reconciliation export with internal IDs and no employee identifiers for filing."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("DRAFT — recorded checks only; for review", "Employee record ID / quarter", "Item", "Amount"))
    if employer_id is not None and year is not None:
        writer.writerow(("Scope", employer_id, "Tax year", year))
    for employee, totals in worksheet["employees"].items():
        for field, label in {**W2_FIELDS, "ca_sdi": CASDI_LABEL}.items():
            writer.writerow(("W-2 draft", employee, label, f"{totals[field]:.2f}"))
        for field, label in W2_REVIEW_FIELDS.items():
            writer.writerow(("W-2 draft", employee, label, format_w2_entry(worksheet["w2_handoff"][employee][field])))
        writer.writerow(("W-2 draft", employee, "Box 15 · State", "CA"))
    for field, label in W2_FIELDS.items():
        writer.writerow(("W-3 draft", "", label, f"{worksheet['w3_totals'][field]:.2f}"))
    for field, label in W3_REVIEW_FIELDS.items():
        writer.writerow(("W-3 draft", "", label, format_w2_entry(worksheet["w3_handoff"][field])))
    writer.writerow(("W-3 draft", "", "Box 15 · State", "CA"))
    writer.writerow(("W-2/W-3 draft", "", "Preparer review", "Verify employer and employee identities and reconcile payments outside recorded cash payroll."))
    writer.writerow(("W-3 draft", "", "Preparer review", "Verify payer and employer type, contact details, total forms transmitted, and any applicable third-party sick pay."))
    for field, label in FUTA_FIELDS.items():
        writer.writerow(("FUTA draft", "Annual", label, f"{worksheet['futa'][field]:.2f}"))
        for quarter, totals in worksheet["futa_quarters"].items():
            writer.writerow(("FUTA draft", quarter, label, f"{totals[field]:.2f}"))
    writer.writerow(("FUTA draft", "Annual", "Recorded 940 deposits", f"{deposit_total:.2f}"))
    if form_940 is not None:
        if form_940["status"]:
            writer.writerow(("Form 940 draft", "Annual", "Status", form_940["status"]))
        for label, key in (
            ("Prior-year credit applied", "prior_credit"),
            ("California Schedule A covered wages", "covered_wages"),
            ("California Schedule A rate (%)", "rate_percent"),
        ):
            amount = form_940[key]
            writer.writerow(("Form 940 draft", "Annual", label, "" if amount is None else str(amount)))
        for line, label in FORM_940_LINES.items():
            amount = form_940["lines"][line]
            writer.writerow(("Form 940 draft", line, label, "" if amount is None else f"{amount:.2f}"))
    if filed_comparison is not None:
        writer.writerow(("Section", "Quarter", "Comparison", "Recorded", "Filed", "Difference"))
        for quarter, result in filed_comparison.items():
            period = f"Q{quarter}"
            writer.writerow(("Filed quarter reconciliation", period, "Status", result["status"]))
            for label, recorded, filed, difference in result["rows"]:
                writer.writerow(("Filed quarter reconciliation", period, label, f"{recorded:.2f}", f"{filed:.2f}", f"{difference:.2f}"))
    for quarter, status in (employee_de9c or {}).items():
        writer.writerow(("DE 9C employee PIT reconciliation", f"Q{quarter}", "Status", status))
    return output.getvalue()
