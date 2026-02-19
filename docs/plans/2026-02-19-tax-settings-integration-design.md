# Design Doc: Tax Settings Persistence in Horilla Payroll

## 1. Objective
Enable the persistence of Form 941 identity metadata (Designee and Signer info) to reduce manual entry during quarterly reporting.

## 2. Architecture Changes

### 2.1 Model Extension (`payroll/models/tax_models.py`)
Extend the `PayrollSettings` model to include the following fields:
- `tax_designee_name` (CharField, max_length=255, blank=True)
- `tax_designee_phone` (CharField, max_length=20, blank=True)
- `tax_designee_pin` (CharField, max_length=5, blank=True)
- `tax_signer_name` (CharField, max_length=255, blank=True)
- `tax_signer_title` (CharField, max_length=255, blank=True)
- `tax_signer_phone` (CharField, max_length=20, blank=True)
- `tax_seasonal_employer` (BooleanField, default=False)

### 2.2 API Endpoints (`report/views/payroll_report.py`)
- Create a new view `update_tax_settings` (POST) that accepts these fields and updates the `PayrollSettings` record for the current session's selected company.

### 2.3 Logic Updates (`report/views/payroll_report.py`)
- Update `download_tax_forms` to fetch `PayrollSettings`.
- Use saved values as fallbacks for any blank fields in the request's GET parameters.

## 3. UI Changes (`report/templates/report/payroll_report.html`)
- Pre-populate the 941 form fields with data from `PayrollSettings`.
- Add a "Save as Default" button in the Form 941 section of the filter sidebar.
- Implement a simple jQuery AJAX call to the `update_tax_settings` endpoint when the button is clicked.

## 4. Testing Plan
1. Enter data into the fields and click "Save as Default".
2. Verify in the database that `PayrollSettings` is updated.
3. Refresh the page and verify fields are pre-populated.
4. Download Form 941 and verify the PDF contains the saved data.
