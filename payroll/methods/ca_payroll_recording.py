"""Record reviewed tax facts against an existing, verified paid payslip."""

import json
from bisect import bisect_right
from dataclasses import asdict, fields
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from base.models import Company
from payroll.methods.ca_payroll_check import CaliforniaPaycheck
from payroll.methods.us_ca_contributions import SubjectWages
from payroll.models.models import CaliforniaPaidCheckEddReview, Payslip, RecordedCaliforniaPaycheck
from report.forms.recorded_wages import recorded_amount


_YTD_BASES = tuple(field.name for field in fields(SubjectWages))


def validate_recorded_ytd(records):
    """Validate successive YTD wage bases, allowing documented payroll outside Horilla."""
    ending_wages = {}
    for employee_id, facts in records:
        try:
            prior = {base: recorded_amount(facts["prior_ytd_subject_wages"][base]) for base in _YTD_BASES}
            current = {base: recorded_amount(facts["subject_wages"][base]) for base in _YTD_BASES}
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Employee record {employee_id} has invalid prior or current subject wages.") from error
        preceding = ending_wages.get(employee_id)
        if preceding is not None and any(prior[base] < preceding[base] for base in _YTD_BASES):
            raise ValueError(f"Paid checks overlap in the year-to-date wage bases for employee record {employee_id}.")
        ending_wages[employee_id] = {base: prior[base] + current[base] for base in _YTD_BASES}


def _recorded_amount(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def paid_slip_review_state(slip):
    return {
        "employee": slip.employee_id_id,
        "period_start": slip.start_date.isoformat(),
        "period_end": slip.end_date.isoformat(),
        "gross": str(slip.gross_pay),
        "net": str(slip.net_pay),
        "status": slip.status,
    }


@transaction.atomic
def record_paid_ca_paycheck(
    *, payslip_id, employer_id, calculation: CaliforniaPaycheck, recorded_by_id=None,
    expected_slip_state=None,
):
    """Capture verified payment facts once. Call only after employer authorization.

    The caller confirms the actual check date and legal employer against the
    payment register. The employee's current employer and the payslip's work
    period cannot establish either fact. Conflicting retries require review.
    Use PostgreSQL for concurrent posting. SQLite may require a retry if two
    transactions try to record the same check simultaneously.
    """
    if not employer_id or not isinstance(calculation, CaliforniaPaycheck):
        raise ValidationError("A verified calculation and legal employer are required.")
    Company._base_manager.select_for_update().get(pk=employer_id)
    try:
        slip = Payslip._base_manager.select_for_update().get(pk=payslip_id)
    except Payslip.DoesNotExist as error:
        raise ValidationError("The reviewed payslip no longer exists.") from error
    if expected_slip_state is not None and paid_slip_review_state(slip) != expected_slip_state:
        raise ValidationError("The payslip changed. Preview it again before recording.")

    payload = asdict(calculation)
    payload.pop("pay_date")
    for name in ("ca_edd_subject_wages", "ca_wage_plan_code"):
        if payload[name] is None:
            payload.pop(name)
    payload["net_pay"] = calculation.net_pay
    for name in ("ui_rate", "ett_rate"):
        rate = payload["employer_notice"][name]
        payload["employer_notice"][name] = format(rate.normalize(), "f")
    facts = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))

    prior = RecordedCaliforniaPaycheck.objects.filter(payslip_id=slip.pk).first()
    if prior is not None:
        if (prior.employer_id, prior.paid_on, prior.facts_version, prior.facts) == (
            employer_id, calculation.pay_date, 1, facts,
        ):
            return prior
        raise ValidationError("This check already has different recorded tax facts.")

    if slip.status != "paid":
        raise ValidationError("Tax facts can be recorded only after the check is paid.")
    if (_recorded_amount(slip.gross_pay), _recorded_amount(slip.net_pay)) != (
        calculation.gross_pay, calculation.net_pay,
    ):
        raise ValidationError("The reviewed calculation does not match paid gross and net pay.")

    year = calculation.pay_date.year
    records = list(RecordedCaliforniaPaycheck.objects.for_period(
        employer_id, date(year, 1, 1), date(year + 1, 1, 1),
    ).filter(employee_id=slip.employee_id_id).values_list("paid_on", "facts"))
    position = bisect_right(records, calculation.pay_date, key=lambda record: record[0])
    records.insert(position, (calculation.pay_date, facts))
    try:
        validate_recorded_ytd((slip.employee_id_id, record_facts) for _, record_facts in records)
    except ValueError as error:
        raise ValidationError(str(error)) from error

    return RecordedCaliforniaPaycheck.objects.create(
        payslip_id=slip.pk, employer_id=employer_id, employee_id=slip.employee_id_id,
        paid_on=calculation.pay_date, work_period_start=slip.start_date,
        work_period_end=slip.end_date, facts=facts, recorded_by_id=recorded_by_id,
    )


@transaction.atomic
def supplement_edd_wages(*, record_id, subject_wages, plan_code, reviewer_id):
    """Append separately verified EDD facts without changing the paid check."""
    if (
        not reviewer_id or plan_code != "S" or not isinstance(subject_wages, Decimal)
        or not subject_wages.is_finite() or not 0 <= subject_wages < Decimal("1000000000000")
        or subject_wages != _recorded_amount(subject_wages)
    ):
        raise ValidationError("Enter verified EDD subject wages in cents and standard plan code S.")
    check = RecordedCaliforniaPaycheck.objects.get(pk=record_id)
    Company._base_manager.select_for_update().get(pk=check.employer_id)
    if check.facts.get("ca_edd_subject_wages") is not None or check.facts.get("ca_wage_plan_code") is not None:
        raise ValidationError("This paid check already contains EDD facts.")
    if subject_wages > Decimal(check.facts["gross_pay"]):
        raise ValidationError("EDD subject wages cannot exceed the recorded cash gross pay.")
    taxable = check.facts["contributions"]["taxable_wages"]
    if subject_wages < max(recorded_amount(taxable[key]) for key in ("ca_ui", "ca_ett", "ca_sdi")):
        raise ValidationError("EDD subject wages cannot be less than the recorded California contribution wage bases.")
    review, created = CaliforniaPaidCheckEddReview.objects.get_or_create(
        paid_check=check, defaults={"subject_wages": subject_wages, "plan_code": plan_code, "reviewed_by_id": reviewer_id},
    )
    if not created and (review.subject_wages, review.plan_code) != (subject_wages, plan_code):
        raise ValidationError("Different EDD facts have already been recorded for this paid check.")
    return review
