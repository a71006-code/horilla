"""Review employee wage lines transcribed from the filed California DE 9C."""

from datetime import date
from urllib.parse import urlencode

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from payroll.methods.ca_de9c_reconciliation import de9c_quarter_has_ended, record_filed_de9c
from payroll.methods.ca_filing_review import quarter_end
from payroll.models.models import CaliforniaEmployerFilingProfile, CaliforniaFiledDe9c, RecordedCaliforniaPaycheck
from report.forms.ca_de9c_reconciliation import compare_filed_de9c, write_de9c_csv
from report.forms.ca_quarterly_worksheet import build_quarterly_worksheet
from report.views.ca_quarterly_worksheet import QuarterSelectionForm


class FiledDe9cForm(forms.Form):
    text = forms.CharField(
        label="Filed employee rows", required=False, max_length=20000,
        widget=forms.Textarea(attrs={"rows": 6, "spellcheck": "false", "autocomplete": "off"}),
        help_text="Enter one line per employee with the Horilla employee record ID, PIT wages and PIT withheld, "
        "separated by commas. Append subject wages and wage plan code to compare those fields too. "
        "Use a dash in the ID column if the employee has no Horilla record. "
        "Combine amounts for repeated filed lines under the same plan code. Review multiple wage plan codes "
        "for one employee with the preparer.",
    )
    no_payroll = forms.BooleanField(label="The filed DE 9C reported no payroll.", required=False)
    verified = forms.BooleanField(label="I checked the employer account, quarter and all rows against the filed DE 9C.")
    replace_current = forms.BooleanField(label="Replace the previous transcription for this quarter.", required=False)
    profile_version = forms.CharField(max_length=40, widget=forms.HiddenInput)
    current_entry_id = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


def _missing_edd_facts(check):
    subject = check.facts.get("ca_edd_subject_wages")
    plan = check.facts.get("ca_wage_plan_code")
    if subject is None and plan is None:
        return getattr(check, "edd_review", None) is None
    return subject is None or plan is None


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def ca_de9c_reconciliation(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied

    is_post = request.method == "POST"
    selection = QuarterSelectionForm(request.POST if is_post else request.GET or None)
    context = {"selection": selection}
    if selection.is_valid():
        employer = selection.cleaned_data["employer"]
        quarter = selection.cleaned_data["quarter"]
        start = date(2026, 3 * quarter - 2, 1)
        profile = CaliforniaEmployerFilingProfile.objects.filter(employer=employer, year=start.year).first()
        latest = CaliforniaFiledDe9c.objects.filter(profile=profile, period_start=start).order_by("-pk").first()
        current = latest if latest is not None and latest.profile_reviewed_at == profile.reviewed_at else None
        initial = {
            "profile_version": profile.reviewed_at.isoformat(),
            "current_entry_id": current.pk if current else 0,
        } if profile else {}
        filing = FiledDe9cForm(request.POST if is_post else None, initial=initial)
        if is_post and filing.is_valid():
            fields = {key: value for key, value in filing.cleaned_data.items() if key != "verified"}
            try:
                record_filed_de9c(employer_id=employer.pk, start=start, reviewer_id=request.user.pk, **fields)
            except ValidationError as error:
                filing.add_error(None, error)
            else:
                query = urlencode({"employer": employer.pk, "quarter": quarter})
                return redirect(f"{reverse('ca-de9c-reconciliation')}?{query}")
        context.update(
            employer=employer, quarter=quarter, filing=filing, profile=profile, current=current,
            prior_profile_filing=latest is not None and current is None,
            can_record=profile is not None and de9c_quarter_has_ended(start),
        )
        try:
            checks = list(RecordedCaliforniaPaycheck.objects.for_period(
                employer.pk, start, quarter_end(start),
            ).select_related("edd_review", "employee"))
            worksheet = build_quarterly_worksheet(checks, [])
            incomplete_employees = {check.employee_id for check in checks if _missing_edd_facts(check)}
            recorded_edd = {
                row["employee_id"]: row for row in worksheet["de9c_rows"]
                if row["employee_id"] not in incomplete_employees
            }
            comparison = compare_filed_de9c(
                worksheet["employees"], current.employee_rows if current else None, recorded_edd=recorded_edd,
            )
        except ValueError as error:
            context["worksheet_error"] = str(error)
        else:
            if not is_post and request.GET.get("export") == "csv":
                response = HttpResponse(
                    write_de9c_csv(comparison, employer_id=employer.pk, quarter=quarter),
                    content_type="text/csv; charset=utf-8",
                )
                response["Content-Disposition"] = f'attachment; filename="ca-de9c-2026-q{quarter}-reconciliation.csv"'
                return response
            names = {check.employee_id: check.employee.get_full_name() for check in checks}
            for row in comparison["rows"]:
                row["employee_name"] = names.get(row["employee_id"], "")
            context["comparison"] = comparison
    return render(request, "report/ca_de9c_reconciliation.html", context)
