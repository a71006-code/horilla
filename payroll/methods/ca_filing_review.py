"""Verified employer identity and reconciliation of a recorded quarter."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils.crypto import constant_time_compare, salted_hmac

from base.models import Company
from payroll.methods.ca_payroll_recording import validate_recorded_ytd
from payroll.models.models import (
    CaliforniaEmployerFilingProfile, CaliforniaFiledQuarterTotals, CaliforniaFilingProfileRevision, CaliforniaQuarterReview,
    RecordedCaliforniaPaycheck, RecordedCaliforniaTaxDeposit,
)
from report.forms.ca_annual_worksheet import FILED_COMPARISONS, FILED_FICA_FIELDS, SIGNED_FILED_FIELDS
from report.forms.ca_quarterly_worksheet import build_quarterly_worksheet
from report.forms.recorded_wages import ZERO, recorded_amount


QUARTERLY_KINDS = (
    RecordedCaliforniaTaxDeposit.Kind.FEDERAL_941, RecordedCaliforniaTaxDeposit.Kind.CALIFORNIA_DE9,
)


def _tax_id(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value.strip()):
        raise ValidationError(f"Enter the {label} in the correct format.")
    number = value.strip().replace("-", "")
    if not number.strip("0"):
        raise ValidationError(f"Enter the verified {label}, not a placeholder.")
    return number


def _capture_filing_profile(profile):
    CaliforniaFilingProfileRevision.objects.get_or_create(
        profile=profile, reviewed_at=profile.reviewed_at,
        defaults={
            "legal_name": profile.legal_name, "ein": profile.ein, "edd_account": profile.edd_account,
            "federal_return": profile.federal_return, "reviewed_by_id": profile.reviewed_by_id,
        },
    )


@transaction.atomic
def save_filing_profile(*, employer_id, year, legal_name, ein, edd_account, federal_return, reviewer_id):
    """Save verified identity for one legal employer and year."""
    if year != 2026 or not reviewer_id or federal_return not in CaliforniaEmployerFilingProfile.FederalReturn.values:
        raise ValidationError("Select a supported tax year and federal return.")
    legal_name = legal_name.strip()
    if not legal_name or len(legal_name) > 160:
        raise ValidationError("Enter the verified legal employer name.")
    values = {
        "legal_name": legal_name, "ein": _tax_id(ein, r"[0-9]{2}-?[0-9]{7}", "federal EIN"),
        "edd_account": _tax_id(edd_account, r"(?:[0-9]{8}|[0-9]{3}-[0-9]{4}-[0-9])", "EDD account number"),
        "federal_return": federal_return,
    }
    Company._base_manager.select_for_update().get(pk=employer_id)
    profile = CaliforniaEmployerFilingProfile.objects.filter(employer_id=employer_id, year=year).first()
    if profile is not None:
        _capture_filing_profile(profile)
        if all(getattr(profile, name) == value for name, value in values.items()):
            return profile
    try:
        profile, _ = CaliforniaEmployerFilingProfile.objects.update_or_create(
            employer_id=employer_id, year=year, defaults={**values, "reviewed_by_id": reviewer_id},
        )
    except IntegrityError as error:
        raise ValidationError("A tax ID is already assigned to another employer for this year.") from error
    _capture_filing_profile(profile)
    return profile


def quarter_end(start):
    if type(start) is not date or start.year != 2026 or start.day != 1 or start.month not in (1, 4, 7, 10):
        raise ValidationError("Select a 2026 reporting quarter.")
    return date(2027, 1, 1) if start.month == 10 else date(2026, start.month + 3, 1)


@transaction.atomic
def record_filed_quarter_totals(*, employer_id, start, profile_version, reviewer_id, amounts, replace_current=False):
    if quarter_end(start) > datetime.now(ZoneInfo("America/Los_Angeles")).date():
        raise ValidationError("Filed totals can be recorded after the quarter ends.")
    if not reviewer_id or amounts.keys() != FILED_COMPARISONS.keys() | FILED_FICA_FIELDS.keys():
        raise ValidationError("Enter each comparison amount from the filed returns.")
    try:
        normalized = {}
        for box, value in amounts.items():
            amount = recorded_amount(value, allow_negative=box in SIGNED_FILED_FIELDS)
            if abs(amount) >= Decimal("1000000000000"):
                raise ValueError("Amount exceeds the supported range.")
            normalized[box] = f"{amount:.2f}"
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError("Enter valid filed amounts in dollars and cents.") from error

    Company._base_manager.select_for_update().get(pk=employer_id)
    profile = CaliforniaEmployerFilingProfile.objects.filter(
        employer_id=employer_id, year=start.year, federal_return=CaliforniaEmployerFilingProfile.FederalReturn.QUARTERLY,
    ).first()
    if profile is None or profile.reviewed_at.isoformat() != profile_version:
        raise ValidationError("Verify the Form 941 employer profile and reload the year-end worksheet.")
    current = CaliforniaFiledQuarterTotals.objects.filter(
        profile=profile, profile_reviewed_at=profile.reviewed_at, period_start=start,
    ).order_by("-pk").first()
    if current is not None:
        if current.amounts == normalized:
            return current
        if not replace_current:
            raise ValidationError("Confirm that the new amounts should replace the recorded comparison totals.")
    return CaliforniaFiledQuarterTotals.objects.create(
        profile=profile, profile_reviewed_at=profile.reviewed_at, period_start=start,
        amounts=normalized, reviewed_by_id=reviewer_id,
    )


@dataclass(frozen=True)
class QuarterSources:
    profile: CaliforniaEmployerFilingProfile | None
    deposits: list
    worksheet: dict
    gross_pay: Decimal
    fingerprint: str
    check_ids: list


def read_quarter_sources(employer_id, start):
    end = quarter_end(start)
    profile = CaliforniaEmployerFilingProfile.objects.filter(employer_id=employer_id, year=start.year).first()
    year_checks = list(RecordedCaliforniaPaycheck.objects.for_period(
        employer_id, date(start.year, 1, 1), end,
    ).select_related("edd_review"))
    validate_recorded_ytd((check.employee_id, check.facts) for check in year_checks)
    checks = [check for check in year_checks if check.paid_on >= start]
    deposits = list(RecordedCaliforniaTaxDeposit.objects.filter(
        employer_id=employer_id, period_start=start, kind__in=QUARTERLY_KINDS,
    ).order_by("deposited_on", "pk"))
    active = [deposit for deposit in deposits if deposit.voided_at is None]
    worksheet = build_quarterly_worksheet(checks, active)
    try:
        gross = sum((recorded_amount(check.facts["gross_pay"]) for check in checks), ZERO)
    except (InvalidOperation, KeyError, TypeError, ValueError) as error:
        raise ValueError("A recorded check is missing valid gross pay.") from error
    identity = None if profile is None else [
        profile.pk, profile.reviewed_at.isoformat(), profile.legal_name,
        profile.ein, profile.edd_account, profile.federal_return,
    ]
    payload = [
        employer_id, start, identity,
        [[c.pk, c.employee_id, c.paid_on, c.work_period_start, c.work_period_end, c.facts_version, c.facts] for c in checks],
        [[d.pk, d.kind, d.deposited_on, d.reference, d.amount] for d in active],
        {
            **worksheet,
            "daily_federal_liability": [(day.isoformat(), amount) for day, amount in worksheet["daily_federal_liability"].items()],
        },
    ]
    data = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    fingerprint = salted_hmac("payroll.ca-quarter-review.v1", data, algorithm="sha256").hexdigest()
    return QuarterSources(profile, deposits, worksheet, gross, fingerprint, [check.pk for check in checks])


@transaction.atomic
def sign_off_quarter(
    *, employer_id, start, fingerprint, reviewer_id, deposit_schedule, federal_headcount,
    edd_headcounts, check_count, gross_pay, federal_deposits, california_deposits,
):
    if quarter_end(start) > datetime.now(ZoneInfo("America/Los_Angeles")).date():
        raise ValidationError("A quarter can be reviewed after it ends.")
    if not reviewer_id or deposit_schedule not in CaliforniaQuarterReview.DepositSchedule.values:
        raise ValidationError("Select the verified 941 deposit schedule.")
    if len(edd_headcounts) != 3 or any(type(n) is not int or n < 0 for n in (*edd_headcounts, federal_headcount, check_count)):
        raise ValidationError("Enter valid payroll and employee counts.")
    Company._base_manager.select_for_update().get(pk=employer_id)
    sources = read_quarter_sources(employer_id, start)
    if not constant_time_compare(sources.fingerprint, fingerprint):
        raise ValidationError("Recorded payroll, deposits or employer identity changed. Reload the worksheet.")
    if not sources.profile or sources.profile.federal_return != CaliforniaEmployerFilingProfile.FederalReturn.QUARTERLY:
        raise ValidationError("Verify the employer's Form 941 filing profile before signing off.")
    if sources.worksheet["missing_de9c_check_count"]:
        raise ValidationError("Recorded checks are missing verified EDD subject wages or wage plan codes.")
    expected = (sources.worksheet["check_count"], sources.gross_pay, sources.worksheet["federal_deposits"], sources.worksheet["california_deposits"])
    if expected != (check_count, gross_pay, federal_deposits, california_deposits):
        raise ValidationError("The payroll register or deposit totals do not match the recorded quarter.")

    values = {
        "fingerprint": fingerprint, "deposit_schedule": deposit_schedule, "federal_headcount": federal_headcount,
        "edd_headcounts": list(edd_headcounts), "check_count": check_count, "gross_pay": gross_pay,
        "federal_deposits": federal_deposits, "california_deposits": california_deposits,
    }
    latest = CaliforniaQuarterReview.objects.filter(employer_id=employer_id, period_start=start).order_by("-pk").first()
    if latest is not None and all(getattr(latest, key) == value for key, value in values.items()):
        return latest
    return CaliforniaQuarterReview.objects.create(
        employer_id=employer_id, period_start=start, reviewed_by_id=reviewer_id, **values,
    )
