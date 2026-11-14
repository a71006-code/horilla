# W-2/W-3 Year-End Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add W-2/W-3 filled PDF generation and W-2/W-3 CSV exports using the existing Horilla payroll report and tax-form pipeline.

**Architecture:** Keep the existing 940/941/DE9/DE9C flow intact and add a focused year-end helper for W-2/W-3 row building, totals, CSV generation, and PDF payload shaping. Views stay thin: they filter payslips, call the helper, zip PDFs/CSVs, and expose buttons on the existing Payroll Report screen.

**Tech Stack:** Django views/templates/tests, existing `Payslip` and `Deduction` models, existing `TaxFormFiller` with PyMuPDF, Python stdlib `csv`, Django `TestCase` and `RequestFactory`.

---

## File Structure

- Create `report/forms/year_end_tax.py`: Builds W-2 employee rows, W-3 totals, CSV bytes, and PDF payloads from confirmed payslips.
- Modify `report/forms/tax_forms.py`: Adds `W2` and `W3` mappings and allows a forms directory that contains only `fw2.pdf`/`fw3.pdf`.
- Modify `report/views/payroll_report.py`: Adds year-end filtering helpers, PDF ZIP endpoint, and CSV ZIP endpoint while reusing selected-company filtering.
- Modify `report/urls.py`: Adds `download-w2-w3-forms` and `download-w2-w3-csv` routes.
- Modify `report/templates/report/payroll_report.html`: Adds year-end buttons beside the existing tax-form controls.
- Modify `employee/models.py`: Adds the missing employee SSN field required for W-2 output.
- Create `employee/migrations/0002_employee_ssn.py`: Persists the SSN field.
- Create `payroll/tests/test_year_end_tax_exports.py`: Covers helper math, CSV output, view ZIP output, and PDF filler integration by mocking actual template filling.

---

### Task 0: Add Employee SSN Field

**Files:**
- Modify: `employee/models.py`
- Create: `employee/migrations/0002_employee_ssn.py`
- Test: `payroll/tests/test_year_end_tax_exports.py`

- [x] **Step 1: Write the failing SSN model test**

Create `payroll/tests/test_year_end_tax_exports.py` with this initial content:

```python
from django.test import TestCase

from employee.models import Employee


class EmployeeTaxIdentityFieldTest(TestCase):
    def test_employee_has_ssn_field_for_year_end_forms(self):
        field = Employee._meta.get_field("ssn")

        self.assertEqual(field.max_length, 11)
        self.assertTrue(field.blank)
        self.assertTrue(field.null)
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.EmployeeTaxIdentityFieldTest -v 2
```

Expected: FAIL with `Employee has no field named 'ssn'`.

- [x] **Step 3: Add SSN field**

In `employee/models.py`, add this field near the other personal identity fields on `Employee`, after `phone`:

```python
    ssn = models.CharField(
        max_length=11,
        null=True,
        blank=True,
        verbose_name=_("SSN"),
        help_text=_("Social Security Number used for US year-end payroll forms."),
    )
```

- [x] **Step 4: Create migration**

Run:

```powershell
python manage.py makemigrations employee
```

Expected: creates `employee/migrations/0002_employee_ssn.py`.

- [x] **Step 5: Run SSN model test**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.EmployeeTaxIdentityFieldTest -v 2
```

Expected: PASS.

- [x] **Step 6: Commit**

Run:

```powershell
git add employee/models.py employee/migrations/0002_employee_ssn.py payroll/tests/test_year_end_tax_exports.py
git commit -m "feat: add employee SSN for year-end payroll forms"
```

Expected: commit succeeds.

---

### Task 1: Add Year-End Row Builder Tests

**Files:**
- Create: `payroll/tests/test_year_end_tax_exports.py`
- Create later: `report/forms/year_end_tax.py`

- [x] **Step 1: Write the failing helper tests**

Extend `payroll/tests/test_year_end_tax_exports.py` so it contains the SSN field test from Task 0 plus these year-end helper tests:

```python
import csv
import io
from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from employee.models import Employee

from report.forms.year_end_tax import (
    build_w2_w3_context,
    generate_w2_csv,
    generate_w3_csv,
)


class EmployeeTaxIdentityFieldTest(TestCase):
    def test_employee_has_ssn_field_for_year_end_forms(self):
        field = Employee._meta.get_field("ssn")

        self.assertEqual(field.max_length, 11)
        self.assertTrue(field.blank)
        self.assertTrue(field.null)


class YearEndTaxExportHelperTest(TestCase):
    @patch("report.forms.year_end_tax.Deduction")
    def test_build_w2_w3_context_groups_tax_boxes_by_employee(self, mock_deduction):
        payslip_qs = MagicMock()
        payslip_qs.exists.return_value = True
        payslip_qs.values.return_value = [
            {
                "id": 1,
                "employee_id": 10,
                "employee_id__employee_first_name": "Ava",
                "employee_id__employee_last_name": "Stone",
                "employee_id__ssn": "111-22-3333",
                "employee_id__email": "ava@example.com",
                "employee_id__badge_id": "E10",
                "employee_id__address": "44 Pine St",
                "employee_id__city": "Sacramento",
                "employee_id__state": "CA",
                "employee_id__zip": "95814",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 15),
                "gross_pay": 100000.0,
                "pay_head_data": {
                    "federal_tax": 90.0,
                    "tax_deductions": [
                        {"deduction_id": 101, "amount": 62.0},
                        {"deduction_id": 102, "amount": 14.5},
                        {"deduction_id": 103, "amount": 10.0},
                    ],
                },
            },
            {
                "id": 2,
                "employee_id": 10,
                "employee_id__employee_first_name": "Ava",
                "employee_id__employee_last_name": "Stone",
                "employee_id__ssn": "111-22-3333",
                "employee_id__email": "ava@example.com",
                "employee_id__badge_id": "E10",
                "employee_id__address": "44 Pine St",
                "employee_id__city": "Sacramento",
                "employee_id__state": "CA",
                "employee_id__zip": "95814",
                "start_date": date(2026, 1, 16),
                "end_date": date(2026, 1, 31),
                "gross_pay": 80000.0,
                "pay_head_data": {
                    "federal_tax": 45.0,
                    "tax_deductions": [
                        {"deduction_id": 101, "amount": 31.0},
                        {"deduction_id": 102, "amount": 7.25},
                        {"deduction_id": 103, "amount": 5.0},
                    ],
                },
            },
        ]

        mock_deduction.objects.filter.return_value.values.return_value = [
            {"id": 101, "title": "Social Security", "tax_reporting_type": None, "has_max_limit": True, "maximum_amount": 168600.0},
            {"id": 102, "title": "Medicare", "tax_reporting_type": None, "has_max_limit": False, "maximum_amount": None},
            {"id": 103, "title": "CA PIT", "tax_reporting_type": None, "has_max_limit": False, "maximum_amount": None},
        ]

        company = MagicMock()
        company.company = "CAC Payroll"
        company.address = "1 Market St"
        company.city = "San Francisco"
        company.state = "CA"
        company.zip = "94105"
        company.company_registration_number = "12-3456789"

        context = build_w2_w3_context(payslip_qs, company=company, year=2026)

        self.assertEqual(len(context["w2_rows"]), 1)
        row = context["w2_rows"][0]
        self.assertEqual(row["employee_ssn"], "111-22-3333")
        self.assertEqual(row["employee_first_name"], "Ava")
        self.assertEqual(row["employee_last_name"], "Stone")
        self.assertEqual(row["box_1_wages"], 180000.0)
        self.assertEqual(row["box_2_federal_income_tax"], 135.0)
        self.assertEqual(row["box_3_social_security_wages"], 168600.0)  # Capped!
        self.assertEqual(row["box_4_social_security_tax"], 93.0)
        self.assertEqual(row["box_5_medicare_wages"], 180000.0)
        self.assertEqual(row["box_6_medicare_tax"], 21.75)
        self.assertEqual(row["box_16_state_wages"], 180000.0)
        self.assertEqual(row["box_17_state_income_tax"], 15.0)

        w3 = context["w3_totals"]
        self.assertEqual(w3["employee_count"], 1)
        self.assertEqual(w3["box_1_wages"], 180000.0)
        self.assertEqual(w3["box_2_federal_income_tax"], 135.0)
        self.assertEqual(w3["box_3_social_security_wages"], 168600.0)  # Capped!
        self.assertEqual(w3["box_4_social_security_tax"], 93.0)
        self.assertEqual(w3["box_5_medicare_wages"], 180000.0)
        self.assertEqual(w3["box_6_medicare_tax"], 21.75)

    def test_generate_w2_and_w3_csv_use_stable_headers(self):
        context = {
            "w2_rows": [
                {
                    "tax_year": 2026,
                    "employer_ein": "12-3456789",
                    "employer_name": "CAC Payroll",
                    "employee_ssn": "111-22-3333",
                    "employee_first_name": "Ava",
                    "employee_last_name": "Stone",
                    "box_1_wages": 1500.0,
                    "box_2_federal_income_tax": 135.0,
                    "box_3_social_security_wages": 1500.0,
                    "box_4_social_security_tax": 93.0,
                    "box_5_medicare_wages": 1500.0,
                    "box_6_medicare_tax": 21.75,
                    "state_code": "CA",
                    "box_16_state_wages": 1500.0,
                    "box_17_state_income_tax": 15.0,
                    "box_14_label": "CASDI",
                    "box_14_amount": 0.0,
                }
            ],
            "w3_totals": {
                "tax_year": 2026,
                "employer_ein": "12-3456789",
                "employer_name": "CAC Payroll",
                "employee_count": 1,
                "box_1_wages": 1500.0,
                "box_2_federal_income_tax": 135.0,
                "box_3_social_security_wages": 1500.0,
                "box_4_social_security_tax": 93.0,
                "box_5_medicare_wages": 1500.0,
                "box_6_medicare_tax": 21.75,
                "box_16_state_wages": 1500.0,
                "box_17_state_income_tax": 15.0,
            },
        }

        w2_rows = list(csv.DictReader(io.StringIO(generate_w2_csv(context).decode("utf-8"))))
        w3_rows = list(csv.DictReader(io.StringIO(generate_w3_csv(context).decode("utf-8"))))

        self.assertEqual(w2_rows[0]["tax_year"], "2026")
        self.assertEqual(w2_rows[0]["employee_ssn"], "111-22-3333")
        self.assertEqual(w2_rows[0]["box_1_wages"], "1500.00")
        self.assertEqual(w2_rows[0]["box_14_label"], "CASDI")
        self.assertEqual(w3_rows[0]["employee_count"], "1")
        self.assertEqual(w3_rows[0]["box_4_social_security_tax"], "93.00")
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports -v 2
```

Expected: FAIL with `ModuleNotFoundError: No module named 'report.forms.year_end_tax'`.

---

### Task 2: Implement Year-End Helper

**Files:**
- Create: `report/forms/year_end_tax.py`
- Test: `payroll/tests/test_year_end_tax_exports.py`

- [x] **Step 1: Add helper implementation**

Create `report/forms/year_end_tax.py`:

```python
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
```

- [x] **Step 2: Run helper tests**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports -v 2
```

Expected: PASS for the two helper tests.

- [x] **Step 3: Commit**

Run:

```powershell
git add report/forms/year_end_tax.py payroll/tests/test_year_end_tax_exports.py
git commit -m "feat: add W-2 W-3 year-end export helpers"
```

Expected: commit succeeds.

---

### Task 3: Add W-2/W-3 PDF Filler Support

**Files:**
- Modify: `report/forms/tax_forms.py`
- Test: `payroll/tests/test_year_end_tax_exports.py`

- [x] **Step 1: Add failing PDF mapping test**

Append this test to `YearEndTaxExportHelperTest` in `payroll/tests/test_year_end_tax_exports.py`:

```python
    def test_tax_form_filler_accepts_w2_and_w3_form_types(self):
        from report.forms.tax_forms import TaxFormFiller

        self.assertIn("W2", TaxFormFiller.FORM_MAPPINGS)
        self.assertIn("W3", TaxFormFiller.FORM_MAPPINGS)
        self.assertEqual(TaxFormFiller.get_template_filename("W2"), "fw2.pdf")
        self.assertEqual(TaxFormFiller.get_template_filename("W3"), "fw3.pdf")
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.YearEndTaxExportHelperTest.test_tax_form_filler_accepts_w2_and_w3_form_types -v 2
```

Expected: FAIL because `W2`, `W3`, and `get_template_filename` do not exist yet.

- [x] **Step 3: Extend `TaxFormFiller`**

In `report/forms/tax_forms.py`, add `W2` and `W3` entries to `FORM_MAPPINGS` after `DE9C`:

```python
        "W2": {
            "tax_year": "tax_year",
            "employer_ein": "employer_ein",
            "employer_name": "employer_name",
            "employer_address": "employer_address",
            "employer_city": "employer_city",
            "employer_state": "employer_state",
            "employer_zip": "employer_zip",
            "employee_ssn": "employee_ssn",
            "employee_first_name": "employee_first_name",
            "employee_last_name": "employee_last_name",
            "employee_address": "employee_address",
            "employee_city": "employee_city",
            "employee_state": "employee_state",
            "employee_zip": "employee_zip",
            "box_1_wages": "box_1_wages",
            "box_2_federal_income_tax": "box_2_federal_income_tax",
            "box_3_social_security_wages": "box_3_social_security_wages",
            "box_4_social_security_tax": "box_4_social_security_tax",
            "box_5_medicare_wages": "box_5_medicare_wages",
            "box_6_medicare_tax": "box_6_medicare_tax",
            "state_code": "state_code",
            "box_16_state_wages": "box_16_state_wages",
            "box_17_state_income_tax": "box_17_state_income_tax",
            "box_14_label": "box_14_label",
            "box_14_amount": "box_14_amount",
        },
        "W3": {
            "tax_year": "tax_year",
            "employer_ein": "employer_ein",
            "employer_name": "employer_name",
            "employer_address": "employer_address",
            "employer_city": "employer_city",
            "employer_state": "employer_state",
            "employer_zip": "employer_zip",
            "employee_count": "employee_count",
            "box_1_wages": "box_1_wages",
            "box_2_federal_income_tax": "box_2_federal_income_tax",
            "box_3_social_security_wages": "box_3_social_security_wages",
            "box_4_social_security_tax": "box_4_social_security_tax",
            "box_5_medicare_wages": "box_5_medicare_wages",
            "box_6_medicare_tax": "box_6_medicare_tax",
            "box_16_state_wages": "box_16_state_wages",
            "box_17_state_income_tax": "box_17_state_income_tax",
        },
```

Add this class method inside `TaxFormFiller` before `fill_form`:

```python
    @classmethod
    def get_template_filename(cls, form_type):
        return f"f{str(form_type).lower()}.pdf"
```

Change the forms directory detection in `__init__` from requiring `f941.pdf` to accepting any supported template:

```python
        for path in candidates:
            if os.path.exists(path):
                template_names = [
                    self.get_template_filename(form_type)
                    for form_type in self.FORM_MAPPINGS
                ]
                if any(os.path.exists(os.path.join(path, name)) for name in template_names):
                    self.forms_dir = path
                    logger.info(f"[TaxFormFiller] Found valid templates at: {path}")
                    break
```

Change `fill_form` filename creation:

```python
        filename = self.get_template_filename(form_type)
```

- [x] **Step 4: Run mapping test**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.YearEndTaxExportHelperTest.test_tax_form_filler_accepts_w2_and_w3_form_types -v 2
```

Expected: PASS.

- [x] **Step 5: Commit**

Run:

```powershell
git add report/forms/tax_forms.py payroll/tests/test_year_end_tax_exports.py
git commit -m "feat: register W-2 W-3 PDF form templates"
```

Expected: commit succeeds.

---

### Task 4: Add Year-End Download Views

**Files:**
- Modify: `report/views/payroll_report.py`
- Modify: `report/urls.py`
- Test: `payroll/tests/test_year_end_tax_exports.py`

- [x] **Step 1: Add failing view tests**

Append this import near the top of `payroll/tests/test_year_end_tax_exports.py`:

```python
import zipfile
from django.test import RequestFactory
from report.views.payroll_report import download_w2_w3_csv, download_w2_w3_forms
```

Append this test class:

```python
class YearEndTaxExportViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_mock = MagicMock()
        self.user_mock.has_perm.return_value = True
        self.user_mock.is_authenticated = True

    @patch("report.views.payroll_report._build_w2_w3_context_from_request")
    def test_download_w2_w3_csv_returns_zip(self, mock_context):
        mock_context.return_value = {
            "w2_rows": [
                {
                    "tax_year": 2026,
                    "employer_ein": "12-3456789",
                    "employer_name": "CAC Payroll",
                    "employee_ssn": "111-22-3333",
                    "employee_first_name": "Ava",
                    "employee_last_name": "Stone",
                    "box_1_wages": 1500.0,
                    "box_2_federal_income_tax": 135.0,
                    "box_3_social_security_wages": 1500.0,
                    "box_4_social_security_tax": 93.0,
                    "box_5_medicare_wages": 1500.0,
                    "box_6_medicare_tax": 21.75,
                    "state_code": "CA",
                    "box_16_state_wages": 1500.0,
                    "box_17_state_income_tax": 15.0,
                    "box_14_label": "CASDI",
                    "box_14_amount": 0.0,
                }
            ],
            "w3_totals": {
                "tax_year": 2026,
                "employer_ein": "12-3456789",
                "employer_name": "CAC Payroll",
                "employee_count": 1,
                "box_1_wages": 1500.0,
                "box_2_federal_income_tax": 135.0,
                "box_3_social_security_wages": 1500.0,
                "box_4_social_security_tax": 93.0,
                "box_5_medicare_wages": 1500.0,
                "box_6_medicare_tax": 21.75,
                "box_16_state_wages": 1500.0,
                "box_17_state_income_tax": 15.0,
            },
        }

        request = self.factory.get("/report/download-w2-w3-csv", {"tax_year": "2026"})
        request.user = self.user_mock
        request.session = {"selected_company": "all"}

        response = download_w2_w3_csv(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            self.assertEqual(sorted(zf.namelist()), ["W2.csv", "W3.csv"])
            self.assertIn("employee_ssn", zf.read("W2.csv").decode("utf-8"))

    @patch("report.forms.tax_forms.TaxFormFiller")
    @patch("report.views.payroll_report._build_w2_w3_context_from_request")
    def test_download_w2_w3_forms_returns_employee_and_summary_pdfs(self, mock_context, mock_filler):
        mock_context.return_value = {
            "w2_rows": [
                {
                    "employee_ssn": "111-22-3333",
                    "employee_first_name": "Ava",
                    "employee_last_name": "Stone",
                }
            ],
            "w3_totals": {"employee_count": 1},
        }
        mock_filler.return_value.fill_form.side_effect = [b"W2PDF", b"W3PDF"]

        request = self.factory.get("/report/download-w2-w3-forms", {"tax_year": "2026"})
        request.user = self.user_mock
        request.session = {"selected_company": "all"}

        response = download_w2_w3_forms(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            self.assertEqual(sorted(zf.namelist()), ["W2_Ava_Stone.pdf", "W3.pdf"])
            self.assertEqual(zf.read("W2_Ava_Stone.pdf"), b"W2PDF")
            self.assertEqual(zf.read("W3.pdf"), b"W3PDF")
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.YearEndTaxExportViewTest -v 2
```

Expected: FAIL because `download_w2_w3_csv` and `download_w2_w3_forms` are not implemented.

- [x] **Step 3: Implement request context builder**

In `report/views/payroll_report.py`, add this helper after `_build_tax_form_data`:

```python
    def _build_w2_w3_context_from_request(request):
        from report.forms.year_end_tax import build_w2_w3_context

        raw_year = str(request.GET.get("tax_year", "")).strip()
        try:
            tax_year = int(raw_year)
        except (TypeError, ValueError):
            tax_year = None

        reference_date = parse_date(request.GET.get("start_date_from", "")) or parse_date(
            request.GET.get("end_date_from", "")
        )
        if not tax_year and reference_date:
            tax_year = reference_date.year
        if not tax_year:
            import datetime
            tax_year = datetime.date.today().year

        payslips = Payslip.objects.filter(start_date__year=tax_year)
        selected_company = request.session.get("selected_company")
        if selected_company and selected_company != "all":
            payslips = payslips.filter(
                employee_id__employee_work_info__company_id=selected_company
            )

        status = request.GET.get("status")
        if status:
            payslips = payslips.filter(status=status)

        comp = None
        if selected_company and selected_company != "all":
            comp = Company.objects.filter(id=selected_company).first()
        if not comp:
            comp = Company.objects.first()

        return build_w2_w3_context(payslips, company=comp, year=tax_year)
```

- [x] **Step 4: Implement CSV ZIP endpoint**

In `report/views/payroll_report.py`, add this view after `download_tax_forms`:

```python
    @login_required
    @permission_required(perm="payroll.view_payslip")
    def download_w2_w3_csv(request):
        import io
        import zipfile
        from django.http import HttpResponse
        from report.forms.year_end_tax import generate_w2_csv, generate_w3_csv

        context = _build_w2_w3_context_from_request(request)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("W2.csv", generate_w2_csv(context))
            zf.writestr("W3.csv", generate_w3_csv(context))

        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="w2_w3_csv.zip"'
        return response
```

- [x] **Step 5: Implement PDF ZIP endpoint**

In `report/views/payroll_report.py`, add:

```python
    @login_required
    @permission_required(perm="payroll.view_payslip")
    def download_w2_w3_forms(request):
        import io
        import re
        import zipfile
        from django.http import HttpResponse
        from report.forms.tax_forms import TaxFormFiller

        def safe_name(value):
            cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
            return cleaned.strip("_") or "Employee"

        context = _build_w2_w3_context_from_request(request)
        filler = TaxFormFiller()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for index, row in enumerate(context.get("w2_rows", []), start=1):
                try:
                    pdf_bytes = filler.fill_form("W2", row)
                except Exception:
                    continue
                filename = "W2_{first}_{last}.pdf".format(
                    first=safe_name(row.get("employee_first_name")),
                    last=safe_name(row.get("employee_last_name")),
                )
                if filename == "W2_Employee_Employee.pdf":
                    filename = f"W2_Employee_{index}.pdf"
                zf.writestr(filename, pdf_bytes)

            try:
                w3_pdf = filler.fill_form("W3", context.get("w3_totals", {}))
            except Exception:
                w3_pdf = None
            if w3_pdf:
                zf.writestr("W3.pdf", w3_pdf)

            if not zf.namelist():
                zf.writestr(
                    "README.txt",
                    "No W-2/W-3 PDF templates found. Add fw2.pdf and fw3.pdf to report/static/report/forms/.",
                )

        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="w2_w3_forms.zip"'
        return response
```

- [x] **Step 6: Add URL routes**

In `report/urls.py`, inside the payroll `urlpatterns.extend`, add:

```python
            path(
                "download-w2-w3-forms",
                payroll_report.download_w2_w3_forms,
                name="download-w2-w3-forms",
            ),
            path(
                "download-w2-w3-csv",
                payroll_report.download_w2_w3_csv,
                name="download-w2-w3-csv",
            ),
```

- [x] **Step 7: Run view tests**

Run:

```powershell
python manage.py test payroll.tests.test_year_end_tax_exports.YearEndTaxExportViewTest -v 2
```

Expected: PASS.

- [x] **Step 8: Commit**

Run:

```powershell
git add report/views/payroll_report.py report/urls.py payroll/tests/test_year_end_tax_exports.py
git commit -m "feat: add W-2 W-3 download endpoints"
```

Expected: commit succeeds.

---

### Task 5: Add Payroll Report UI Buttons

**Files:**
- Modify: `report/templates/report/payroll_report.html`
- Test manually in browser after server starts

- [x] **Step 1: Add buttons beside existing tax form controls**

In `report/templates/report/payroll_report.html`, after `#download-tax-forms-btn`, add:

```html
    <button id="download-w2-w3-forms-btn" class="oh-btn oh-btn--secondary ml-2 mb-2" style="display:none;">
        <ion-icon name="document-attach-outline" class="mr-1"></ion-icon>
        {% trans "Download W-2/W-3 (PDF)" %}
    </button>
    <button id="download-w2-w3-csv-btn" class="oh-btn oh-btn--secondary ml-2 mb-2" style="display:none;">
        <ion-icon name="download-outline" class="mr-1"></ion-icon>
        {% trans "Export W-2/W-3 (CSV)" %}
    </button>
```

- [x] **Step 2: Show/hide buttons with employer liability report**

In the JavaScript blocks that hide tax controls, add:

```javascript
            $("#download-w2-w3-forms-btn").hide();
            $("#download-w2-w3-csv-btn").hide();
```

In the `model === "employer_liability"` branch where existing tax buttons show, add:

```javascript
                $("#download-w2-w3-forms-btn").show();
                $("#download-w2-w3-csv-btn").show();
```

- [x] **Step 3: Add click handlers**

Near the existing `#download-tax-forms-btn` handler, add:

```javascript
        function yearEndParams() {
            const params = new URLSearchParams($("#filterForm").serialize());
            const startDate = params.get("start_date_from") || params.get("end_date_from");
            if (startDate && !params.get("tax_year")) {
                params.set("tax_year", startDate.slice(0, 4));
            }
            return params.toString();
        }

        $("#download-w2-w3-forms-btn").on("click", function (e) {
            e.preventDefault();
            window.location.href = `download-w2-w3-forms?${yearEndParams()}`;
        });

        $("#download-w2-w3-csv-btn").on("click", function (e) {
            e.preventDefault();
            window.location.href = `download-w2-w3-csv?${yearEndParams()}`;
        });
```

- [x] **Step 4: Run existing Django test suite for touched payroll tests**

Run:

```powershell
python manage.py test payroll.tests.test_report_employer_liability payroll.tests.test_year_end_tax_exports -v 2
```

Expected: PASS.

- [x] **Step 5: Commit**

Run:

```powershell
git add report/templates/report/payroll_report.html
git commit -m "feat: expose W-2 W-3 year-end exports"
```

Expected: commit succeeds.

---

### Task 6: Final Verification

**Files:**
- Verify: `report/forms/year_end_tax.py`
- Verify: `report/forms/tax_forms.py`
- Verify: `report/views/payroll_report.py`
- Verify: `report/urls.py`
- Verify: `report/templates/report/payroll_report.html`
- Verify: `payroll/tests/test_year_end_tax_exports.py`
- Verify: `employee/models.py`
- Verify: `employee/migrations/0002_employee_ssn.py`

- [x] **Step 1: Run targeted tests**

Run:

```powershell
python manage.py test payroll.tests.test_report_employer_liability payroll.tests.test_year_end_tax_exports -v 2
```

Expected: PASS.

- [x] **Step 2: Run Django system checks**

Run:

```powershell
python manage.py check
```

Expected: `System check identified no issues`.

- [x] **Step 3: Inspect changed files**

Run:

```powershell
git diff --stat
git diff -- employee/models.py employee/migrations/0002_employee_ssn.py report/forms/year_end_tax.py report/forms/tax_forms.py report/views/payroll_report.py report/urls.py report/templates/report/payroll_report.html payroll/tests/test_year_end_tax_exports.py
```

Expected: diff only includes the SSN field/migration, W-2/W-3 helper, routes, views, UI buttons, and tests.

- [x] **Step 4: Manual template note**

Confirm the deployment has these files before using PDF output:

```text
report/static/report/forms/fw2.pdf
report/static/report/forms/fw3.pdf
```

Expected: CSV export works without these PDFs; PDF ZIP includes actual W-2/W-3 PDFs only when templates exist.

- [x] **Step 5: Commit verification-only adjustments if any**

If verification required small fixes, run:

```powershell
git add employee/models.py employee/migrations/0002_employee_ssn.py report/forms/year_end_tax.py report/forms/tax_forms.py report/views/payroll_report.py report/urls.py report/templates/report/payroll_report.html payroll/tests/test_year_end_tax_exports.py
git commit -m "fix: stabilize W-2 W-3 export flow"
```

Expected: commit succeeds only if there were follow-up fixes.
