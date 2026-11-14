"""Review and export paid-wage year-end totals for one legal employer."""

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import InvalidOperation
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from base.models import Company
from payroll.methods.ca_filing_review import record_filed_quarter_totals
from payroll.methods.ca_payroll_recording import validate_recorded_ytd
from payroll.methods.ca_reviewed_reports import (
    complete_filing_ssns, normalized_review_inputs, reviewed_report_digest, reviewed_report_token, save_reviewed_report,
)
from payroll.methods.ca_tax_deposits import record_ca_tax_deposit, void_ca_tax_deposit
from payroll.models.models import (
    CaliforniaEmployerFilingProfile, CaliforniaFiledDe9c, CaliforniaFiledQuarterTotals, CaliforniaReviewedReport,
    RecordedCaliforniaPaycheck, RecordedCaliforniaTaxDeposit,
)
from report.forms.ca_annual_worksheet import (
    CASDI_LABEL, FILED_COMPARISONS, FILED_FICA_FIELDS, FORM_940_LINES, FUTA_FIELDS, SIGNED_FILED_FIELDS,
    W2_FIELDS, W2_OTHER_CODES, W2_REVIEW_FIELDS, W3_REVIEW_FIELDS, apply_w2_reviews, build_annual_worksheet,
    build_form_940_summary, compare_filed_quarters, format_w2_entry, write_annual_worksheet_csv,
)
from report.forms.recorded_wages import ZERO, recorded_amount
from report.forms.ca_de9c_reconciliation import compare_filed_de9c
from report.views.ca_quarterly_worksheet import DepositConfirmationForm, VoidDepositForm


ANNUAL_KINDS = (RecordedCaliforniaTaxDeposit.Kind.FEDERAL_940,)
OCCUPATION_CODES = {"000"} | {
    str(code) for first, last in (
        (101, 110), (201, 211), (301, 304), (401, 409),
        (501, 510), (601, 611), (701, 706), (801, 810),
    ) for code in range(first, last + 1)
}
W2_BOX_13 = {
    "statutory": "Statutory employee",
    "retirement": "Retirement plan",
    "sick": "Third-party sick pay",
}
W2_REVIEW_INPUT_FIELDS = {
    "7": "box_7_quarters",
    "8": "box_8",
    "10": "box_10",
    "11": "box_11",
    "TP": "box_12_tp",
    "TT": "box_12_tt",
    "12": "box_12_other",
    "13": "box_13",
    "14b": "box_14b",
}


def _compare_employee_de9c(checks, profile):
    entries = {}
    if profile is not None:
        for entry in CaliforniaFiledDe9c.objects.filter(
            profile=profile, profile_reviewed_at=profile.reviewed_at, period_start__year=profile.year,
        ).order_by("-pk"):
            entries.setdefault((entry.period_start.month - 1) // 3 + 1, entry)
    recorded = {quarter: defaultdict(lambda: {"pit_wages": ZERO, "pit_withheld": ZERO}) for quarter in range(1, 5)}
    for check in checks:
        quarter = (check.paid_on.month - 1) // 3 + 1
        employee = recorded[quarter][check.employee_id]
        employee["pit_wages"] += recorded_amount(check.facts["ca_pit_wages"])
        employee["pit_withheld"] += recorded_amount(check.facts["ca_pit_withheld"])
    statuses = {}
    for quarter, employees in recorded.items():
        entry = entries.get(quarter)
        pit_only = None if entry is None else {
            employee_id: {field: row[field] for field in ("pit_wages", "pit_withheld")}
            for employee_id, row in entry.employee_rows.items()
        }
        statuses[quarter] = compare_filed_de9c(employees, pit_only)["status"]
    return statuses, [entries[quarter].pk for quarter in sorted(entries)]


class AnnualSelectionForm(forms.Form):
    employer = forms.ModelChoiceField(queryset=Company._base_manager.order_by("company", "pk"))
    year = forms.TypedChoiceField(choices=[(2026, "2026")], coerce=int)


class Form940PreviewForm(forms.Form):
    annual_register_verified = forms.BooleanField(
        label="I reconciled this closed year against the complete payroll register and deposits.", required=False,
    )
    coverage = forms.ChoiceField(label="State unemployment coverage and payments", choices=(
        ("", "Select the verified situation"),
        ("timely", "All taxable FUTA wages covered by California UI and paid in full on time"),
        ("excluded", "All taxable FUTA wages excluded from state UI"),
        ("adjusted", "Some wages excluded or state UI paid late"),
    ))
    adjusted_amount = forms.DecimalField(
        label="Preparer’s Form 940 line 10 adjustment", required=False, min_value=0, max_digits=14, decimal_places=2,
    )
    covered_wages = forms.DecimalField(
        label="California Schedule A taxable FUTA wages covered by state UI",
        required=False, min_value=0, max_digits=14, decimal_places=2,
    )
    rate_percent = forms.DecimalField(
        label="Verified final California Schedule A rate (%)", required=False,
        min_value=0, max_value=5.4, max_digits=5, decimal_places=3,
    )
    prior_credit = forms.DecimalField(
        label="Prior-year credit applied to this year (enter 0 if none)",
        min_value=0, max_digits=14, decimal_places=2,
    )
    quarterly_liabilities = forms.CharField(
        label="Preparer’s Part 5 liabilities for an adjusted return", required=False, max_length=80,
        help_text="If line 12 exceeds $500, enter four amounts in quarter order separated by commas.",
    )

    def clean_quarterly_liabilities(self):
        value = self.cleaned_data["quarterly_liabilities"]
        if not value:
            return None
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4 or any(not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", part) for part in parts):
            raise ValidationError("Enter four nonnegative amounts in dollars and cents.")
        return tuple(recorded_amount(part) for part in parts)


class W2PreviewForm(forms.Form):
    source = forms.CharField(widget=forms.HiddenInput)
    verified = forms.BooleanField(
        label="I verified the supplied entries and that related wages and taxes are already in the recorded payroll.",
    )
    annual_register_verified = forms.BooleanField(
        label="I reconciled this closed year against the complete payroll register.", required=False,
    )
    entries = forms.CharField(
        label="Verified employee entries",
        widget=forms.Textarea(attrs={"rows": 8, "spellcheck": "false"}),
        max_length=200_000,
        help_text="Enter one line per field as employee record ID, box or code, value.",
    )

    def __init__(self, *args, employee_ids, source, **kwargs):
        self.employee_ids = employee_ids
        self.source = source
        super().__init__(*args, initial={"source": source}, **kwargs)

    def clean_source(self):
        if self.cleaned_data["source"] != self.source:
            raise ValidationError("The selected payroll changed. Review the latest recorded amounts before continuing.")
        return self.source

    def clean_entries(self):
        employee_reviews = {}
        for number, line in enumerate(self.cleaned_data["entries"].splitlines(), 1):
            if not line.strip():
                continue
            columns = line.split(",", 2)
            if len(columns) != 3:
                raise ValidationError(f"Line {number}: enter an employee record ID, a box or code, and a value.")
            employee, field, value = (item.strip() for item in columns)
            if not re.fullmatch(r"[1-9][0-9]{0,18}", employee) or int(employee) not in self.employee_ids:
                raise ValidationError(f"Line {number}: enter an employee record ID shown in this worksheet.")
            fields = employee_reviews.setdefault(int(employee), {})
            field = W2_REVIEW_INPUT_FIELDS.get(field)
            if field is None or field in fields or not value:
                raise ValidationError(f"Line {number}: enter a supported box or code and its value once per employee.")
            try:
                fields[field] = self._parse_entry(field, value)
            except (InvalidOperation, ValueError) as error:
                raise ValidationError(f"Line {number}: {error}") from error

        for employee, fields in employee_reviews.items():
            tp = fields.get("box_12_tp")
            occupations = fields.get("box_14b")
            if tp and not occupations:
                raise ValidationError(f"Employee record {employee}: enter Box 14b occupation codes for reported cash tips.")
            if occupations and not tp:
                raise ValidationError(f"Employee record {employee}: occupation codes require a positive code TP amount.")
            if tp == ZERO:
                fields["box_14b"] = ()
        return employee_reviews

    @staticmethod
    def _parse_entry(field, value):
        def amount(text):
            if not re.fullmatch(r"[0-9]{1,12}(\.[0-9]{1,2})?", text):
                raise ValueError("Enter an amount in dollars with at most two decimal places.")
            return recorded_amount(text)

        parts = value.split()
        if field == "box_7_quarters":
            if len(parts) != 4:
                raise ValueError("Enter four Social Security tip amounts, from Q1 through Q4.")
            return tuple(amount(part) for part in parts)
        if field == "box_12_other":
            if value == "none":
                return {}
            entries = {}
            for part in parts:
                code, _, code_amount = part.partition("=")
                if code not in W2_OTHER_CODES or code in entries:
                    raise ValueError("Enter each other Box 12 code once in CODE=amount format.")
                entries[code] = amount(code_amount)
                if entries[code] == ZERO:
                    raise ValueError("Enter a positive amount for each applicable Box 12 code.")
            return entries
        if field == "box_13":
            if value == "none":
                return ()
            if len(set(parts)) != len(parts) or set(parts) - W2_BOX_13.keys():
                raise ValueError("Enter none or the applicable choices: statutory, retirement, sick.")
            return tuple(W2_BOX_13[part] for part in parts)
        if field == "box_14b":
            if not 1 <= len(parts) <= 2 or len(set(parts)) != len(parts) or set(parts) - OCCUPATION_CODES:
                raise ValueError("Enter one or two distinct IRS occupation codes.")
            return tuple(parts)
        return amount(value)


class FiledQuarterTotalsForm(forms.Form):
    quarter = forms.TypedChoiceField(choices=[(n, f"Q{n}") for n in range(1, 5)], coerce=int)
    profile_version = forms.CharField(max_length=40, widget=forms.HiddenInput)
    verified = forms.BooleanField(label="I verified these amounts and the employer accounts against the filed returns.")
    replace_current = forms.BooleanField(
        label="Replace the previously recorded totals for this quarter.", required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {box: label for box, (label, _) in FILED_COMPARISONS.items()}
        labels.update(FILED_FICA_FIELDS)
        for box, filed_label in labels.items():
            self.fields[box] = forms.DecimalField(
                label=filed_label, min_value=None if box in SIGNED_FILED_FIELDS else 0,
                decimal_places=2, max_digits=14,
            )
        self.order_fields(("quarter", *labels, "verified", "replace_current"))


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def ca_annual_worksheet(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    is_post = request.method == "POST"
    voiding = is_post and request.POST.get("action") == "void"
    recording_filed = is_post and request.POST.get("action") == "filed_totals"
    previewing_940 = is_post and request.POST.get("action") == "preview_940"
    previewing_w2 = is_post and request.POST.get("action") == "preview_w2"
    previewing = previewing_940 or previewing_w2
    selection = AnnualSelectionForm(request.POST if is_post else (request.GET or None))
    deposit_form = DepositConfirmationForm(
        request.POST if is_post and not (voiding or recording_filed or previewing) else None,
        kinds=ANNUAL_KINDS,
    )
    deposit_form.fields["confirmed"].label = "I verified this deposit and tax year against the payment confirmation."
    void_form = VoidDepositForm(request.POST if voiding else None)
    context = {"selection": selection, "deposit_form": deposit_form, "void_form": void_form}
    if selection.is_valid():
        employer = selection.cleaned_data["employer"]
        year = selection.cleaned_data["year"]
        start = date(year, 1, 1)
        profile = CaliforniaEmployerFilingProfile.objects.filter(
            employer=employer, year=year, federal_return=CaliforniaEmployerFilingProfile.FederalReturn.QUARTERLY,
        ).first()
        filed_form = FiledQuarterTotalsForm(
            request.POST if recording_filed else None,
            initial={"profile_version": profile.reviewed_at.isoformat()} if profile else {},
        )
        action_form = filed_form if recording_filed else (void_form if voiding else deposit_form)
        if is_post and not previewing and action_form.is_valid():
            try:
                if recording_filed:
                    fields = filed_form.cleaned_data
                    record_filed_quarter_totals(
                        employer_id=employer.pk, start=date(year, 3 * fields["quarter"] - 2, 1),
                        reviewer_id=request.user.pk, profile_version=fields["profile_version"],
                        amounts={box: fields[box] for box in (*FILED_COMPARISONS, *FILED_FICA_FIELDS)},
                        replace_current=fields["replace_current"],
                    )
                elif voiding:
                    void_ca_tax_deposit(
                        employer_id=employer.pk, period_start=start, reviewer_id=request.user.pk,
                        allowed_kinds=ANNUAL_KINDS, **void_form.cleaned_data,
                    )
                else:
                    fields = {key: value for key, value in deposit_form.cleaned_data.items() if key != "confirmed"}
                    record_ca_tax_deposit(
                        employer_id=employer.pk, period_start=start, recorded_by_id=request.user.pk, **fields,
                    )
            except ValidationError as error:
                action_form.add_error(None, error)
            else:
                return redirect(f"{reverse('ca-annual-worksheet')}?{urlencode({'employer': employer.pk, 'year': year})}")

        deposits = list(RecordedCaliforniaTaxDeposit.objects.filter(
            employer=employer, period_start=start, kind__in=ANNUAL_KINDS,
        ).order_by("deposited_on", "pk"))
        deposit_total = sum((deposit.amount for deposit in deposits if deposit.voided_at is None), ZERO)
        context.update(
            employer=employer, year=year, deposits=deposits, deposit_total=deposit_total,
            profile=profile, filed_form=filed_form,
        )
        form_940 = Form940PreviewForm(request.POST if previewing_940 else None)
        context["form_940"] = form_940
        try:
            checks = list(RecordedCaliforniaPaycheck.objects.for_period(
                employer.pk, start, date(year + 1, 1, 1),
            ))
            validate_recorded_ytd((check.employee_id, check.facts) for check in checks)
            worksheet = build_annual_worksheet(checks)
            source = salted_hmac(
                "ca-annual-w2-source", f"{employer.pk}:{year}:{tuple(check.pk for check in checks)}:{worksheet!r}",
            ).hexdigest()
            w2_form = W2PreviewForm(
                request.POST if previewing_w2 else None,
                employee_ids=worksheet["employees"].keys(), source=source,
            )
            w2_preview = False
            if previewing_w2 and w2_form.is_valid():
                try:
                    worksheet = apply_w2_reviews(worksheet, w2_form.cleaned_data["entries"])
                except ValueError as error:
                    w2_form.add_error("entries", str(error))
                else:
                    w2_preview = True
            filed_entries = {}
            if profile is not None:
                for entry in CaliforniaFiledQuarterTotals.objects.filter(
                    profile=profile, profile_reviewed_at=profile.reviewed_at,
                    period_start__gte=start, period_start__lt=date(year + 1, 1, 1),
                ).order_by("-pk"):
                    filed_entries.setdefault((entry.period_start.month - 1) // 3 + 1, entry)
            filed_comparison = compare_filed_quarters(
                worksheet, {quarter: entry.amounts for quarter, entry in filed_entries.items()},
            )
            employee_de9c, employee_de9c_ids = _compare_employee_de9c(checks, profile)
            for quarter, entry in filed_entries.items():
                filed_comparison[quarter]["reviewed_at"] = entry.reviewed_at
        except ValueError as error:
            context["worksheet_error"] = str(error)
        else:
            summary_940 = None
            if previewing_940 and form_940.is_valid():
                try:
                    summary_940 = build_form_940_summary(
                        worksheet, deposit_total=deposit_total,
                        **{key: value for key, value in form_940.cleaned_data.items() if key != "annual_register_verified"},
                    )
                except ValueError as error:
                    form_940.add_error(None, str(error))
                else:
                    context["summary_940"] = summary_940
                    context["form_940_rows"] = [
                        (line, label, summary_940["lines"][line])
                        for line, label in FORM_940_LINES.items() if summary_940["lines"][line] is not None
                    ]
            export_annual = not is_post and request.GET.get("export") == "csv"
            export_940 = summary_940 is not None and request.POST.get("export") == "csv"
            export_w2 = w2_preview and request.POST.get("export") == "csv"
            has_preview = summary_940 is not None or w2_preview
            if export_annual or has_preview:
                csv_text = write_annual_worksheet_csv(
                    worksheet, deposit_total=deposit_total, employer_id=employer.pk, year=year,
                    filed_comparison=filed_comparison, form_940=summary_940, employee_de9c=employee_de9c,
                )
            if has_preview:
                kinds = CaliforniaReviewedReport.Kind
                kind = kinds.FUTA if summary_940 is not None else kinds.WAGE_STATEMENTS
                confirmation_forms = []
                year_closed = datetime.now(ZoneInfo("America/Los_Angeles")).date().year > year
                if year_closed and profile is not None:
                    if summary_940 is not None:
                        if form_940.cleaned_data["annual_register_verified"] and not summary_940["status"]:
                            confirmation_forms = ["940"]
                    elif (
                        w2_form.cleaned_data["annual_register_verified"]
                        and all(result["status"] == "Matched" for result in filed_comparison.values())
                        and all(status == "Matched" for status in employee_de9c.values())
                        and all(value is not None for row in worksheet["w2_handoff"].values() for value in row.values())
                        and complete_filing_ssns(worksheet["employees"].keys())
                    ):
                        confirmation_forms = ["W2", "W3"]
                source_records = {
                    "worksheet_revision": "2026-annual-v1", "checks": [check.pk for check in checks],
                    "deposits": [entry.pk for entry in deposits if not entry.voided_at],
                    "filed_quarters": [entry.pk for entry in filed_entries.values()],
                    "filed_employee_de9c": employee_de9c_ids,
                    "profile": profile.pk if profile else None,
                    "profile_reviewed_at": profile.reviewed_at.isoformat() if profile else None,
                    "confirmation_forms": confirmation_forms,
                    "review_inputs": normalized_review_inputs(
                        form_940.cleaned_data if summary_940 is not None else {
                            "employee_entries": w2_form.cleaned_data["entries"],
                            "annual_register_verified": w2_form.cleaned_data["annual_register_verified"],
                        },
                    ),
                }
                context["archive_token"] = reviewed_report_token(
                    employer.pk, start, kind, request.user.pk, reviewed_report_digest(csv_text, source_records),
                )
                if request.POST.get("export") == "archive":
                    try:
                        save_reviewed_report(
                            employer_id=employer.pk, period_start=start, kind=kind, reviewer_id=request.user.pk,
                            csv_text=csv_text, source_records=source_records, token=request.POST.get("archive_token", ""),
                        )
                    except ValidationError as error:
                        (form_940 if previewing_940 else w2_form).add_error(None, error)
                    else:
                        return redirect(f"{reverse('ca-reviewed-reports')}?employer={employer.pk}")
            if export_annual or export_940 or export_w2:
                response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
                response["Content-Disposition"] = f'attachment; filename="ca-payroll-{year}-draft.csv"'
                return response
            w3_values = worksheet["w3_totals"] | worksheet["w3_handoff"]
            context.update(
                worksheet=worksheet, box_labels=(*W2_FIELDS.values(), CASDI_LABEL), filed_comparison=filed_comparison,
                employee_de9c=employee_de9c,
                w2_form=w2_form, w2_preview=w2_preview,
                w2_handoff=[
                    (employee, [(label, format_w2_entry(entries[field])) for field, label in W2_REVIEW_FIELDS.items()])
                    for employee, entries in worksheet["w2_handoff"].items()
                ],
                w3_rows=[
                    (label, format_w2_entry(w3_values[field]))
                    for field, label in (W2_FIELDS | W3_REVIEW_FIELDS).items()
                ],
                futa_rows=[(label, worksheet["futa"][field]) for field, label in FUTA_FIELDS.items()],
            )
    return render(request, "report/ca_annual_worksheet.html", context)
