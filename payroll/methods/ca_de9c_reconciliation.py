"""Record independent DE 9C employee wage lines from a filed quarter."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction

from base.models import Company
from employee.models import Employee
from payroll.methods.ca_filing_review import quarter_end
from payroll.models.models import CaliforniaEmployerFilingProfile, CaliforniaFiledDe9c
from report.forms.ca_de9c_reconciliation import parse_filed_de9c


def de9c_quarter_has_ended(start):
    return quarter_end(start) <= datetime.now(ZoneInfo("America/Los_Angeles")).date()


@transaction.atomic
def record_filed_de9c(
    *, employer_id, start, profile_version, reviewer_id, text, no_payroll,
    current_entry_id, replace_current,
):
    if not de9c_quarter_has_ended(start):
        raise ValidationError("Filed DE 9C amounts can be recorded after the quarter ends.")
    try:
        rows = parse_filed_de9c(text, no_payroll=no_payroll)
    except ValueError as error:
        raise ValidationError(str(error)) from error

    Company._base_manager.select_for_update().get(pk=employer_id)
    profile = CaliforniaEmployerFilingProfile.objects.filter(employer_id=employer_id, year=start.year).first()
    if not profile or profile.reviewed_at.isoformat() != profile_version:
        raise ValidationError("Verify the employer filing profile and reload this page.")
    employee_ids = {int(employee) for employee in rows if employee.isdecimal()}
    known_ids = set(Employee._base_manager.filter(pk__in=employee_ids).values_list("pk", flat=True))
    if employee_ids != known_ids:
        raise ValidationError("Use existing Horilla employee record IDs for the filed rows.")
    current = CaliforniaFiledDe9c.objects.filter(
        profile=profile, profile_reviewed_at=profile.reviewed_at, period_start=start,
    ).order_by("-pk").first()
    if current is not None and current.employee_rows == rows:
        return current
    if current_entry_id != (current.pk if current else 0):
        raise ValidationError("The recorded filing changed. Reload this page before saving.")
    if current is not None and not replace_current:
        raise ValidationError("Confirm that this transcription replaces the recorded filed rows.")
    return CaliforniaFiledDe9c.objects.create(
        profile=profile, profile_reviewed_at=profile.reviewed_at, period_start=start,
        employee_rows=rows, reviewed_by_id=reviewer_id,
    )
