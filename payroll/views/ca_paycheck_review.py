"""Superuser review and recording for verified paid California checks."""

import hashlib
import json
from decimal import InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from payroll.forms.ca_paycheck_review import CaliforniaPaycheckReviewForm, LegacyEddReviewForm
from payroll.methods.ca_payroll_recording import (
    _recorded_amount, paid_slip_review_state, record_paid_ca_paycheck, supplement_edd_wages,
)
from payroll.models.models import Payslip, RecordedCaliforniaPaycheck


_REVIEW_SALT = "payroll.california.paid-check-review.v1"


def _review_context(request, slip):
    fields = sorted(
        (key, values) for key, values in request.POST.lists()
        if key not in {"csrfmiddlewaretoken", "action", "review_token", "verified_payment"}
    )
    digest = hashlib.sha256(json.dumps(fields).encode()).hexdigest()
    return {
        "user": request.user.pk, "slip": slip.pk, "input": digest,
        "payment": paid_slip_review_state(slip),
    }


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def review_ca_paycheck(request, payslip_id):
    # No delegated payroll tax permission exists yet. A company selector is
    # not an authorization check, especially for historical employer records.
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    slip = get_object_or_404(Payslip._base_manager, pk=payslip_id, status="paid")
    is_supplement = request.method == "POST" and request.POST.get("action") == "supplement_edd"
    if request.method == "GET" or is_supplement:
        recorded = RecordedCaliforniaPaycheck.objects.filter(payslip_id=slip.pk).select_related("employer", "edd_review").first()
        if recorded is not None:
            context = {"payslip": slip, "recorded": recorded, "edd_review": getattr(recorded, "edd_review", None)}
            if not context["edd_review"] and all(
                recorded.facts.get(field) is None for field in ("ca_edd_subject_wages", "ca_wage_plan_code")
            ):
                edd_form = LegacyEddReviewForm(request.POST if is_supplement else None)
                context["edd_form"] = edd_form
                if is_supplement and edd_form.is_valid():
                    try:
                        supplement_edd_wages(
                            record_id=recorded.pk, subject_wages=edd_form.cleaned_data["subject_wages"],
                            plan_code=edd_form.cleaned_data["plan_code"], reviewer_id=request.user.pk,
                        )
                    except ValidationError as error:
                        edd_form.add_error(None, error)
                    else:
                        return redirect("review-ca-paycheck", payslip_id=slip.pk)
            return render(request, "payroll/payslip/ca_paycheck_review.html", context)
        if is_supplement:
            raise Http404
    form = CaliforniaPaycheckReviewForm(request.POST if request.method == "POST" else None)
    context = {"form": form, "payslip": slip}
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")
        try:
            expected_review = _review_context(request, slip)
            if action == "record":
                if signing.loads(request.POST.get("review_token", ""), salt=_REVIEW_SALT, max_age=900) != expected_review:
                    raise signing.BadSignature
            elif action != "preview":
                raise ValidationError("Choose Preview or Record reviewed check.")

            calculation = form.calculate(gross_pay=slip.gross_pay)
            context["calculation"] = calculation
            context["matches_payment"] = calculation.net_pay == _recorded_amount(slip.net_pay)
            context["review_token"] = signing.dumps(expected_review, salt=_REVIEW_SALT)
            if action == "record":
                if not form.cleaned_data["verified_payment"]:
                    form.add_error("verified_payment", "Confirm the payment register review first.")
                elif not context["matches_payment"]:
                    raise ValidationError("Reconcile the paid net amount before recording this check.")
                else:
                    context["recorded"] = record_paid_ca_paycheck(
                        payslip_id=slip.pk, employer_id=form.cleaned_data["employer"].pk,
                        calculation=calculation, recorded_by_id=request.user.pk,
                        expected_slip_state=expected_review["payment"],
                    )
        except signing.BadSignature:
            form.add_error(None, "Preview these inputs again before recording the check.")
        except (ValidationError, ValueError, InvalidOperation) as error:
            form.add_error(None, str(error))
    return render(request, "payroll/payslip/ca_paycheck_review.html", context)
