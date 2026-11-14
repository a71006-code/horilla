# US Payroll (CA Model) — Minimum Modification Design

**Date:** 2026-05-27

**Repo:** `Horilla-CAC` (Horilla fork)

**Approach Selected:** A — reuse existing Horilla payroll + extend reporting only

## Goal

Enable a client to enter time, run payroll, and generate:
- **Federal:** Form **940**, **941**
- **California:** **DE9**, **DE9C**
- **Year-end:** **W‑2**, **W‑3**

Outputs required:
- Filled **PDF** forms (using provided template PDFs in `report/static/report/forms/`)
- **CSV / e-file-friendly exports** for W‑2 / W‑3 (and optionally DE9C)

Non-goals (for MVP):
- Full multi-state payroll (only CA modeled)
- e-file submission / transmission to IRS/EDD (exports only)
- Handling every special payroll edge case (fringe benefits, multi-jurisdiction reciprocity, etc.)

## Current System (Observed)

The repo already contains:
- Attendance/time infrastructure (`attendance/`) and payroll (`payroll/`).
- Tax aggregation logic in `payroll/methods/tax_reporting.py` for 940/941/DE9 (+ DE9C employee aggregates).
- PDF tax form filling via `report/forms/tax_forms.py` and report endpoints in `report/views/payroll_report.py`.
- Report endpoints already define `TAX_FORM_TYPES = ("941", "940", "DE9", "DE9C")` and a ZIP download.

## MVP Scope Definition

### 1) Timesheet Entry → Payroll Inputs

MVP requirement is *not* to reinvent timekeeping. The system must support:
- Employees (or client/admin on their behalf) entering or approving time that results in payroll pay (hours × rate).

Implementation rule:
- Prefer existing Horilla attendance/time models and existing payroll “payslip” creation workflow.
- Any work here should be limited to ensuring a “confirmed payslip” exists for the pay period.

### 2) Payroll Run Definition (No New Ledger in Approach A)

For minimal changes, forms will be generated from:
- A user-selected date range (quarter or year) over **confirmed** payslips.

Constraints:
- Avoid introducing a new “PayrollRun” persistence model in MVP (that would be Approach B).

### 3) Tax Mapping Requirements

To compute form lines/boxes, each withholding/employer tax must map to a reporting category:
- Federal: `FIT`, `FICA_SS`, `FICA_MED`, `FUTA`
- California: `CA_PIT`, `CA_SDI`, `CA_UI`, `CA_ETT`

Assumption:
- The repo already supports deduction configuration for these reporting types and wage base limits.

### 4) Forms and Exports

#### Federal Quarterly/Annual
- **941** (quarterly)
- **940** (annual FUTA)

#### California Quarterly
- **DE9** (summary)
- **DE9C** (employee wage/withholding listing)

#### Year-end
- **W‑2** (per employee)
- **W‑3** (summary of W‑2s)

PDF generation requirements:
- Continue using the existing PDF filler pipeline.
- Add `W2` and `W3` as additional “form types” that:
  - Load `fw2.pdf` and `fw3.pdf` (or repo-standard naming to be finalized) from `report/static/report/forms/`.
  - Fill a minimal set of boxes/fields required for useful output.
- Graceful template fallback: Catch missing template exceptions and return the ZIP file with CSV files and a `README.txt` rather than failing the request, to support environments where templates are not placed locally (e.g. stored on DS725+).

CSV export requirements:
- Add exports that produce:
  - `W2.csv` (one row per employee per year)
  - `W3.csv` (one summary row per year)
- “e-file-friendly” means: stable columns, correct numeric formatting, and clean identifiers; it does **not** mean official SSA/IRS EFW2 submission format in MVP.

## Data Requirements (Minimum)

The following data must be available to produce the forms:
- Employer: EIN, legal name, address (from `Company` + payroll settings)
- Employee: SSN, legal name, address
- Payroll totals by period/year:
  - Wages and taxable wages as needed
  - Withheld FIT, employee FICA, employer FICA, FUTA liability
  - CA PIT wages/withholding, SDI wages/withholding, UI/ETT taxable wages + liabilities

Minimum modification:
- Add an optional `Employee.ssn` field because W-2 output requires it and this fork references `employee_id.ssn` in reporting without a concrete model field.
- Employer identity exists in `Company` and/or payroll settings already used for 941/DE9.

## Calculation Rules (MVP)

### Wage base limits
Use existing wage-base cap logic already present for:
- FUTA taxable wage base
- Social Security wage base
- CA UI / ETT taxable wage base
- CA SDI wage base

### Tax mapping fallback
- Mirror the title-based auto-detection fallback logic of [tax_reporting.py](file:///c:/Users/user/Documents/Docker/horilla/payroll/methods/tax_reporting.py) (matching strings like `"social security"`, `"medicare"`, `"ca sdi"` in deduction titles if `tax_reporting_type` is `None` in the database).

### W‑2 box mapping (MVP subset)
At minimum support:
- **Box 1** Wages, tips, other comp (from taxable wages definition in payroll)
- **Box 2** Federal income tax withheld (`FIT`)
- **Box 3/4** Social Security wages/tax (`FICA_SS`)
- **Box 5/6** Medicare wages/tax (`FICA_MED`)
- **Box 16/17** State wages and state income tax (CA) (`CA_PIT`)
- **Box 14** optional: CA SDI withheld (configurable label)

Notes:
- Detailed pre-tax deductions, retirement plans, dependent care, etc. are out of scope for MVP unless already modeled in existing payroll data.

### W‑3
W‑3 totals are sums across all generated W‑2s for the year.

## UX / Workflow (MVP)

Minimal UI changes:
- Extend the existing payroll report page/actions to add:
  - “Generate W‑2/W‑3 (PDF)” for a selected tax year
  - “Export W‑2/W‑3 (CSV)” for a selected tax year
- Reuse existing permission model (`payroll.view_payslip`) for access control.

## File/Endpoint Strategy (High Level)

Keep changes localized to reporting:
- Extend `report/views/payroll_report.py` to add year-end generation endpoints and/or include `W2/W3` in existing download ZIP.
- Extend `report/forms/tax_forms.py` to add mapping and template lookup for W‑2/W‑3 PDF templates.
- Add a small “W‑2/W‑3 data builder” that aggregates from confirmed payslips, reusing the tax aggregation output where possible.

## Risks / Open Items (Explicit)

- Template field mappings for W‑2/W‑3 PDFs depend on the exact PDFs you provide (AcroForm/XFA field names).
- Definitions of “Box 1 wages” vs other taxable wage concepts can be nuanced; MVP will align to existing payroll/tax reporting types and document any assumptions.
- E-file output in MVP is CSV only; official EFW2/SSA formats are a later phase.
- W-2/W-3 PDF template availability: The template files are stored externally on DS725+ and are not included in the workspace repository. The fallback mechanism will allow standard operation and testing.

## Acceptance Criteria

For a selected year (e.g., 2026):
- The system produces:
  - `W2.pdf` per employee (or a ZIP containing one PDF per employee)
  - `W3.pdf` summary
  - `W2.csv` and `W3.csv`
- Existing outputs remain working:
  - `941`, `940`, `DE9`, `DE9C` PDF ZIP generation continues to function.
