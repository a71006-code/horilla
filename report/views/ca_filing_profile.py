"""Superuser setup for a verified California employer filing profile."""

import re
from datetime import date

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from base.models import Company
from employee.models import Employee
from payroll.methods.ca_filing_review import save_filing_profile
from payroll.models.models import CaliforniaEmployerFilingProfile, RecordedCaliforniaPaycheck


class FilingProfileForm(forms.Form):
    legal_name = forms.CharField(label="Legal employer name", max_length=160)
    ein = forms.CharField(label="Federal employer identification number", max_length=10)
    edd_account = forms.CharField(label="California EDD payroll tax account number", max_length=10)
    federal_return = forms.ChoiceField(choices=CaliforniaEmployerFilingProfile.FederalReturn.choices)
    verified = forms.BooleanField(label="I verified the legal name, both tax IDs and federal return type against the employer records.")


def _paid_employee_identities(employer_id):
    paid_employee_ids = RecordedCaliforniaPaycheck.objects.for_period(
        employer_id, date(2026, 1, 1), date(2027, 1, 1),
    ).values("employee_id")
    employees = Employee._base_manager.filter(pk__in=paid_employee_ids).order_by("pk").values_list(
        "pk", "employee_first_name", "employee_last_name", "ssn",
    )
    rows = []
    for pk, first_name, last_name, ssn in employees:
        candidate = (ssn or "").strip()
        valid_shape = re.fullmatch(r"(?:[0-9]{9}|[0-9]{3}-[0-9]{2}-[0-9]{4})", candidate)
        rows.append({
            "id": pk, "name": " ".join(filter(None, (first_name, last_name))),
            "masked_ssn": f"•••-••-{candidate[-4:]}" if valid_shape else None,
        })
    return rows


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def ca_filing_profile(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    selector = forms.ModelChoiceField(queryset=Company._base_manager.order_by("company", "pk"))
    is_post = request.method == "POST"
    employer = None
    if is_post or request.GET.get("employer"):
        try:
            employer = selector.clean((request.POST if is_post else request.GET).get("employer"))
        except ValidationError:
            employer = None
    profile = None if employer is None else CaliforniaEmployerFilingProfile.objects.filter(
        employer=employer, year=2026,
    ).first()
    initial = {} if profile is None else {
        name: getattr(profile, name) for name in ("legal_name", "ein", "edd_account", "federal_return")
    }
    form = FilingProfileForm(request.POST if is_post else None, initial=initial)
    if employer and is_post and form.is_valid():
        values = {key: value for key, value in form.cleaned_data.items() if key != "verified"}
        try:
            save_filing_profile(employer_id=employer.pk, year=2026, reviewer_id=request.user.pk, **values)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect(f"{reverse('ca-filing-profile')}?employer={employer.pk}")
    return render(request, "report/ca_filing_profile.html", {
        "employer": employer, "companies": selector.queryset, "form": form, "profile": profile,
        "employee_identities": _paid_employee_identities(employer.pk) if employer else [],
    })
