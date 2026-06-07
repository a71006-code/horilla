import csv
import io
from collections import OrderedDict

from payroll.models.models import Deduction


W2_CSV_FIELDS = [
    "tax_year",
    "employer_ein",
    "employer_name",
    "employer_address",
    "employer_city",
    "employer_state",
    "employer_zip",
    "employee_ssn",
    "employee_first_name",
    "employee_last_name",
    "employee_address",
    "employee_city",
    "employee_state",
    "employee_zip",
    "box_1_wages",
    "box_2_federal_income_tax",
    "box_3_social_security_wages",
    "box_4_social_security_tax",
    "box_5_medicare_wages",
    "box_6_medicare_tax",
    "state_code",
    "box_16_state_wages",
    "box_17_state_income_tax",
    "box_14_label",
    "box_14_amount",
]

W3_CSV_FIELDS = [
    "tax_year",
    "employer_ein",
    "employer_name",
    "employer_address",
    "employer_city",
    "employer_state",
    "employer_zip",
    "employee_count",
    "box_1_wages",
    "box_2_federal_income_tax",
    "box_3_social_security_wages",
    "box_4_social_security_tax",
    "box_5_medicare_wages",
    "box_6_medicare_tax",
    "box_16_state_wages",
    "box_17_state_income_tax",
]


def safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def money(value):
    return round(safe_float(value), 2)


def _company_data(company, year):
    return {
        "tax_year": year,
        "employer_ein": getattr(company, "company_registration_number", "00-0000000") if company else "00-0000000",
        "employer_name": getattr(company, "company", "Horilla HR") if company else "Horilla HR",
        "employer_address": getattr(company, "address", "") if company else "",
        "employer_city": getattr(company, "city", "") if company else "",
        "employer_state": getattr(company, "state", "") if company else "",
        "employer_zip": getattr(company, "zip", "") if company else "",
    }


def _deduction_reporting_map(payslip_values):
    deduction_ids = set()
    for item in payslip_values:
        pay_head_data = item.get("pay_head_data") or {}
        deductions = (
            pay_head_data.get("pretax_deductions", []) +
            pay_head_data.get("post_tax_deductions", []) +
            pay_head_data.get("tax_deductions", [])
        )
        for deduction in deductions:
            deduction_id = deduction.get("deduction_id")
            if deduction_id:
                deduction_ids.add(deduction_id)

    if not deduction_ids:
        return {}

    return {
        item["id"]: item
        for item in Deduction.objects.filter(id__in=deduction_ids).values(
            "id", "title", "tax_reporting_type", "has_max_limit", "maximum_amount"
        )
    }


def _blank_w2_row(base, item):
    return {
        **base,
        "employee_ssn": item.get("employee_id__ssn", ""),
        "employee_first_name": item.get("employee_id__employee_first_name", ""),
        "employee_last_name": item.get("employee_id__employee_last_name", ""),
        "employee_address": item.get("employee_id__address", ""),
        "employee_city": item.get("employee_id__city", ""),
        "employee_state": item.get("employee_id__state", "CA") or "CA",
        "employee_zip": item.get("employee_id__zip", ""),
        "box_1_wages": 0.0,
        "box_2_federal_income_tax": 0.0,
        "box_3_social_security_wages": 0.0,
        "box_4_social_security_tax": 0.0,
        "box_5_medicare_wages": 0.0,
        "box_6_medicare_tax": 0.0,
        "state_code": "CA",
        "box_16_state_wages": 0.0,
        "box_17_state_income_tax": 0.0,
        "box_14_label": "CASDI",
        "box_14_amount": 0.0,
    }


def _payslip_values(payslips):
    return list(
        payslips.values(
            "id",
            "employee_id",
            "employee_id__employee_first_name",
            "employee_id__employee_last_name",
            "employee_id__ssn",
            "employee_id__address",
            "employee_id__city",
            "employee_id__state",
            "employee_id__zip",
            "start_date",
            "end_date",
            "gross_pay",
            "pay_head_data",
        )
    )


def build_w2_w3_context(payslips, company=None, year=None):
    if hasattr(payslips, "exists") and not payslips.exists():
        base = _company_data(company, year)
        return {"w2_rows": [], "w3_totals": {**base, "employee_count": 0}}

    values = _payslip_values(payslips)
    if year is None:
        year = values[0]["start_date"].year if values else None

    base = _company_data(company, year)
    deduction_map = _deduction_reporting_map(values)
    rows_by_employee = OrderedDict()

    # Track maximum limit for Social Security
    ss_limit = 168600.0  # default fallback
    for config in deduction_map.values():
        title_lower = (config.get("title") or "").lower()
        reporting_type = config.get("tax_reporting_type")
        if not reporting_type:
            if any(x in title_lower for x in ["social security", "soc sec", "fica ss", "oasdi", "social", "ss tax"]):
                reporting_type = "FICA_SS"
        if reporting_type == "FICA_SS" and config.get("has_max_limit") and config.get("maximum_amount") is not None:
            try:
                ss_limit = float(config.get("maximum_amount"))
            except (TypeError, ValueError):
                pass

    for item in values:
        employee_id = item.get("employee_id")
        row = rows_by_employee.setdefault(employee_id, _blank_w2_row(base, item))
        gross_pay = safe_float(item.get("gross_pay"))
        pay_head_data = item.get("pay_head_data") or {}

        row["box_1_wages"] += gross_pay
        row["box_2_federal_income_tax"] += safe_float(pay_head_data.get("federal_tax"))

        # Scan pretax, posttax, and tax deductions lists
        deductions = (
            pay_head_data.get("pretax_deductions", []) +
            pay_head_data.get("post_tax_deductions", []) +
            pay_head_data.get("tax_deductions", [])
        )

        for deduction in deductions:
            config = deduction_map.get(deduction.get("deduction_id"), {})
            title_lower = (config.get("title") or "").lower()
            reporting_type = config.get("tax_reporting_type")
            amount = safe_float(deduction.get("amount"))

            # Fallback auto-detection matching tax_reporting.py
            if not reporting_type and title_lower:
                if any(x in title_lower for x in ["social security", "soc sec", "fica ss", "oasdi", "social", "ss tax"]):
                    reporting_type = "FICA_SS"
                elif any(x in title_lower for x in ["medicare", "fica med", "med tax", "hospital"]):
                    reporting_type = "FICA_MED"
                elif any(x in title_lower for x in ["futa", "federal unemployment", "fed unemp", "unemployment tax"]):
                    reporting_type = "FUTA"
                elif any(x in title_lower for x in ["ca sdi", "casdi", "disability", "state disability", "sdi"]):
                    reporting_type = "CA_SDI"
                elif any(x in title_lower for x in ["ca ett", "caett", "training tax", "employment training", "ett"]):
                    reporting_type = "CA_ETT"
                elif any(x in title_lower for x in ["ca ui", "caui", "ca unemployment", "state unemployment", "sui"]):
                    reporting_type = "CA_UI"
                elif any(x in title_lower for x in ["ca tax", "california", "ca pit", "state income", "sit", "personal income", "pit"]):
                    reporting_type = "CA_PIT"
                elif any(x in title_lower for x in ["federal tax", "fed tax", "fit", "federal withholding", "income tax", "withholding"]):
                    reporting_type = "FIT"

            if reporting_type == "FICA_SS":
                row["box_3_social_security_wages"] += gross_pay
                row["box_4_social_security_tax"] += amount
            elif reporting_type == "FICA_MED":
                row["box_5_medicare_wages"] += gross_pay
                row["box_6_medicare_tax"] += amount
            elif reporting_type == "FIT":
                row["box_2_federal_income_tax"] += amount
            elif reporting_type == "CA_PIT":
                row["box_16_state_wages"] += gross_pay
                row["box_17_state_income_tax"] += amount
            elif reporting_type == "CA_SDI":
                row["box_14_amount"] += amount

    w2_rows = []
    for row in rows_by_employee.values():
        # Apply Social Security wages limit capping
        row["box_3_social_security_wages"] = min(row["box_3_social_security_wages"], ss_limit)

        rounded = row.copy()
        for key, value in row.items():
            if key.startswith("box_"):
                rounded[key] = money(value)
        w2_rows.append(rounded)

    w3_totals = {**base, "employee_count": len(w2_rows)}
    for key in [
        "box_1_wages",
        "box_2_federal_income_tax",
        "box_3_social_security_wages",
        "box_4_social_security_tax",
        "box_5_medicare_wages",
        "box_6_medicare_tax",
        "box_16_state_wages",
        "box_17_state_income_tax",
    ]:
        w3_totals[key] = money(sum(row.get(key, 0.0) for row in w2_rows))

    return {"w2_rows": w2_rows, "w3_totals": w3_totals}


def _write_csv(rows, fieldnames):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        normalized = {}
        for key in fieldnames:
            value = row.get(key, "")
            normalized[key] = f"{value:.2f}" if isinstance(value, float) else value
        writer.writerow(normalized)
    return output.getvalue().encode("utf-8")


def generate_w2_csv(context):
    return _write_csv(context.get("w2_rows", []), W2_CSV_FIELDS)


def generate_w3_csv(context):
    return _write_csv([context.get("w3_totals", {})], W3_CSV_FIELDS)
