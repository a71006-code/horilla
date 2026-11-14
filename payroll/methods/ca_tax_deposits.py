"""Record confirmed external deposits. This service does not move money."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from base.models import Company
from payroll.models.models import RecordedCaliforniaTaxDeposit


_IRS_KINDS = ("federal_941", "federal_940")


@transaction.atomic
def record_ca_tax_deposit(*, employer_id, kind, period_start, deposited_on, amount, reference, recorded_by_id, replace_voided=False):
    """Record the same external confirmation once per employer and return type."""
    if not employer_id or not recorded_by_id or kind not in RecordedCaliforniaTaxDeposit.Kind.values:
        raise ValidationError("An employer, return type and reviewer are required.")
    if type(period_start) is not date or period_start.year != 2026 or (
        period_start.day != 1 or period_start.month not in (1, 4, 7, 10)
    ):
        raise ValidationError("Select a 2026 quarter for the deposit allocation.")
    if kind == RecordedCaliforniaTaxDeposit.Kind.FEDERAL_940 and period_start.month != 1:
        raise ValidationError("Allocate a Form 940 deposit to the calendar year.")
    if type(deposited_on) is not date or deposited_on > datetime.now(ZoneInfo("America/Los_Angeles")).date():
        raise ValidationError("Enter the date the deposit was actually paid.")
    if not isinstance(amount, Decimal) or not amount.is_finite() or not 0 < amount < Decimal("1000000000000") or (
        amount != amount.quantize(Decimal("0.01"))
    ):
        raise ValidationError("Enter a positive deposit amount in whole cents.")
    reference = reference.strip() if isinstance(reference, str) else ""
    if not reference or len(reference) > 80:
        raise ValidationError("Enter the agency payment confirmation reference.")

    Company._base_manager.select_for_update().get(pk=employer_id)
    kinds = _IRS_KINDS if kind in _IRS_KINDS else (kind,)
    same_reference = RecordedCaliforniaTaxDeposit.objects.filter(
        employer_id=employer_id, kind__in=kinds, reference=reference,
    )
    active = same_reference.filter(voided_at__isnull=True)
    if active.exclude(kind=kind).exists():
        raise ValidationError("That payment confirmation is already recorded for a different federal return.")
    if not active.exists() and same_reference.exists() and not replace_voided:
        raise ValidationError("That confirmation was voided. Confirm that this is a replacement entry.")
    if replace_voided and not same_reference.filter(voided_at__isnull=False).exists():
        raise ValidationError("No voided entry matches this employer, return type and reference.")

    deposit, created = active.get_or_create(
        employer_id=employer_id, kind=kind, reference=reference,
        defaults={
            "period_start": period_start, "deposited_on": deposited_on,
            "amount": amount, "recorded_by_id": recorded_by_id,
        },
    )
    if not created and (deposit.period_start, deposit.deposited_on, deposit.amount) != (
        period_start, deposited_on, amount,
    ):
        raise ValidationError("That confirmation is already recorded with a different allocation, date or amount.")
    return deposit


@transaction.atomic
def void_ca_tax_deposit(*, deposit_id, employer_id, period_start, reason, reviewer_id, allowed_kinds=None):
    """Exclude a mistaken entry without deleting the original confirmation."""
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reviewer_id or not reason or len(reason) > 200:
        raise ValidationError("Enter a reason for voiding this entry.")
    Company._base_manager.select_for_update().get(pk=employer_id)
    records = RecordedCaliforniaTaxDeposit.objects.filter(
        pk=deposit_id, employer_id=employer_id, period_start=period_start,
    )
    if allowed_kinds is not None:
        records = records.filter(kind__in=allowed_kinds)
    deposit = records.first()
    if deposit is None or deposit.voided_at is not None:
        raise ValidationError("No active deposit with that ID exists for the selected employer and quarter.")
    deposit.voided_at = timezone.now()
    deposit.voided_by_id = reviewer_id
    deposit.void_reason = reason
    deposit.save(update_fields=["voided_at", "voided_by", "void_reason"])
