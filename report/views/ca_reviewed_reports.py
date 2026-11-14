"""Access the exact CSVs retained for the California payroll handoff."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from base.models import Company
from payroll.methods.ca_filing_review import quarter_end
from payroll.models.models import (
    CaliforniaFiledReportConfirmation, CaliforniaFilingConfirmationVoid, CaliforniaFilingProfileRevision,
    CaliforniaReviewedReport,
)


REPORT_FORMS = {
    CaliforniaReviewedReport.Kind.QUARTERLY: (("941", "Form 941"), ("DE9", "DE 9"), ("DE9C", "DE 9C")),
    CaliforniaReviewedReport.Kind.FUTA: (("940", "Form 940"),),
    CaliforniaReviewedReport.Kind.WAGE_STATEMENTS: (("W2", "W-2"), ("W3", "W-3")),
}


class FilingConfirmationForm(forms.Form):
    form_code = forms.ChoiceField(label="Filed return")
    filed_on = forms.DateField(label="Date filed", widget=forms.DateInput(attrs={"type": "date"}))
    reference = forms.RegexField(
        r"^[a-zA-Z0-9][a-zA-Z0-9._ /-]*$", max_length=80,
        label="Agency confirmation reference", help_text="Use the agency receipt or submission ID.",
    )
    verified = forms.BooleanField(label="I verified the filing against the agency receipt.")

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.report = report
        allowed = report.source_records.get("confirmation_forms", [])
        self.fields["form_code"].choices = [choice for choice in REPORT_FORMS[report.kind] if choice[0] in allowed]

    def clean_filed_on(self):
        filed_on = self.cleaned_data["filed_on"]
        start = self.report.period_start
        earliest = quarter_end(start) if self.report.kind == CaliforniaReviewedReport.Kind.QUARTERLY else date(start.year + 1, 1, 1)
        if not earliest <= filed_on <= datetime.now(ZoneInfo("America/Los_Angeles")).date():
            raise ValidationError("Enter a filing date after the reporting period ended and no later than today.")
        return filed_on


class VoidFilingConfirmationForm(forms.Form):
    confirmation_id = forms.IntegerField(min_value=1)
    reason = forms.CharField(label="Reason for voiding", max_length=200)


@login_required
@never_cache
@require_safe
def ca_reviewed_reports(request, report_id=None):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    if report_id is not None:
        report = get_object_or_404(CaliforniaReviewedReport, pk=report_id)
        response = HttpResponse(report.csv_text, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="ca-reviewed-draft-{report.pk}.csv"'
        return response

    selector = forms.ModelChoiceField(queryset=Company._base_manager.order_by("company", "pk"))
    try:
        employer = selector.clean(request.GET.get("employer"))
    except ValidationError:
        employer = None
    reports = CaliforniaReviewedReport.objects.none()
    if employer is not None:
        reports = CaliforniaReviewedReport.objects.filter(employer=employer).select_related("reviewed_by").defer(
            "csv_text", "source_records",
        ).order_by("-pk")
    return render(request, "report/ca_reviewed_reports.html", {
        "companies": selector.queryset, "employer": employer, "reports": reports,
    })


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def ca_reviewed_report_confirmations(request, report_id):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    report = get_object_or_404(CaliforniaReviewedReport.objects.defer("csv_text"), pk=report_id)
    source = report.source_records
    identity = None
    if source.get("profile") and source.get("profile_reviewed_at"):
        identity = CaliforniaFilingProfileRevision.objects.filter(
            profile_id=source["profile"], reviewed_at=source["profile_reviewed_at"],
        ).first()
    is_post = request.method == "POST"
    voiding = is_post and request.POST.get("action") == "void"
    form = FilingConfirmationForm(request.POST if is_post and not voiding else None, report=report)
    void_form = VoidFilingConfirmationForm(request.POST if voiding else None)
    if voiding and void_form.is_valid():
        with transaction.atomic():
            Company._base_manager.select_for_update().get(pk=report.employer_id)
            entry = report.filing_confirmations.filter(
                pk=void_form.cleaned_data["confirmation_id"], void_record__isnull=True,
            ).first()
            if entry is not None:
                CaliforniaFilingConfirmationVoid.objects.create(
                    confirmation=entry, reason=void_form.cleaned_data["reason"], reviewed_by_id=request.user.pk,
                )
                return redirect("ca-reviewed-report-confirmations", report_id=report.pk)
        void_form.add_error(None, "Select an active confirmation on this reviewed report.")
    if is_post and not voiding and form.is_valid():
        fields = form.cleaned_data
        with transaction.atomic():
            Company._base_manager.select_for_update().get(pk=report.employer_id)
            matching = CaliforniaFiledReportConfirmation.objects.filter(
                report__employer_id=report.employer_id, report__period_start=report.period_start,
                form_code=fields["form_code"], reference=fields["reference"],
                void_record__isnull=True,
            )
            if matching.exclude(report=report).exists():
                form.add_error("reference", "This agency receipt already belongs to a different reviewed version.")
            else:
                entry = matching.filter(report=report).first()
                if entry is None:
                    entry = CaliforniaFiledReportConfirmation.objects.create(
                        report=report, form_code=fields["form_code"], reference=fields["reference"],
                        filed_on=fields["filed_on"], reviewed_by_id=request.user.pk,
                    )
                if entry.filed_on == fields["filed_on"]:
                    return redirect("ca-reviewed-report-confirmations", report_id=report.pk)
                form.add_error("filed_on", "This confirmation reference is already recorded with a different filing date.")
    return render(request, "report/ca_reviewed_report_confirmations.html", {
        "report": report, "identity": identity, "form": form, "void_form": void_form,
        "source_summary": json.dumps(source, ensure_ascii=False, indent=2),
        "confirmations": report.filing_confirmations.select_related("void_record").order_by("-pk"),
    })
