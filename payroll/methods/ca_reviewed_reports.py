"""Preserve the exact worksheet and sources that an authorized reviewer saw."""

import json
import re
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.crypto import constant_time_compare, salted_hmac

from employee.models import Employee
from payroll.models.models import CaliforniaReviewedReport


def reviewed_report_digest(csv_text, source_records):
    payload = json.dumps([csv_text, source_records], sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def normalized_review_inputs(values):
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder))


def complete_filing_ssns(employee_ids):
    expected = set(employee_ids)
    employees = dict(Employee._base_manager.filter(pk__in=expected).values_list("pk", "ssn"))
    if employees.keys() != expected:
        return False
    seen = set()
    for value in employees.values():
        value = (value or "").strip()
        if not re.fullmatch(r"(?:[0-9]{9}|[0-9]{3}-[0-9]{2}-[0-9]{4})", value):
            return False
        number = value.replace("-", "")
        if (
            number[:3] in ("000", "666") or number[0] == "9" or number[3:5] == "00"
            or number[5:] == "0000" or number in {"111111111", "333333333", "123456789"} or number in seen
        ):
            return False
        seen.add(number)
    return True


def reviewed_report_token(employer_id, period_start, kind, reviewer_id, digest):
    value = f"{employer_id}:{period_start.isoformat()}:{kind}:{reviewer_id}:{digest}"
    return salted_hmac("payroll.ca-reviewed-report.v1", value, algorithm="sha256").hexdigest()


def save_reviewed_report(*, employer_id, period_start, kind, reviewer_id, csv_text, source_records, token):
    digest = reviewed_report_digest(csv_text, source_records)
    expected = reviewed_report_token(employer_id, period_start, kind, reviewer_id, digest)
    if not constant_time_compare(expected, token):
        raise ValidationError("The worksheet or its sources changed. Preview the report again before saving.")
    report, _ = CaliforniaReviewedReport.objects.get_or_create(
        employer_id=employer_id, period_start=period_start, kind=kind, digest=digest,
        defaults={"reviewed_by_id": reviewer_id, "csv_text": csv_text, "source_records": source_records},
    )
    return report
