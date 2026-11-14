"""Review quarterly California payroll facts and externally paid deposits."""

from datetime import date
from decimal import Decimal, InvalidOperation
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

from base.models import Company
from payroll.methods.ca_filing_review import QUARTERLY_KINDS, quarter_end, read_quarter_sources, sign_off_quarter
from payroll.methods.ca_reviewed_reports import (
    complete_filing_ssns, normalized_review_inputs, reviewed_report_digest, reviewed_report_token, save_reviewed_report,
)
from payroll.methods.ca_tax_deposits import record_ca_tax_deposit, void_ca_tax_deposit
from payroll.models.models import CaliforniaQuarterReview, CaliforniaReviewedReport, RecordedCaliforniaTaxDeposit
from report.forms.ca_quarterly_returns import build_adjusted_941_schedule, build_quarterly_return_rows
from report.forms.ca_quarterly_worksheet import write_quarterly_worksheet_csv
from report.forms.recorded_wages import recorded_amount


class QuarterSelectionForm(forms.Form):
    employer = forms.ModelChoiceField(queryset=Company._base_manager.order_by("company", "pk"))
    quarter = forms.TypedChoiceField(
        choices=[(quarter, f"2026 Q{quarter}") for quarter in range(1, 5)], coerce=int,
    )


class DepositConfirmationForm(forms.Form):
    kind = forms.ChoiceField(label="Return to apply the deposit to", choices=RecordedCaliforniaTaxDeposit.Kind.choices)
    deposited_on = forms.DateField(label="Date actually paid", widget=forms.DateInput(attrs={"type": "date"}))
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    reference = forms.CharField(label="Agency confirmation reference", max_length=80)
    confirmed = forms.BooleanField(label="I verified this deposit and quarter against the payment confirmation.")
    replace_voided = forms.BooleanField(label="This replaces a voided confirmation", required=False)

    def __init__(self, *args, kinds=QUARTERLY_KINDS, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [choice for choice in RecordedCaliforniaTaxDeposit.Kind.choices if choice[0] in kinds]


class VoidDepositForm(forms.Form):
    deposit_id = forms.IntegerField(min_value=1)
    reason = forms.CharField(max_length=200)


class QuarterReviewForm(forms.Form):
    fingerprint = forms.CharField(widget=forms.HiddenInput, max_length=64)
    deposit_schedule = forms.ChoiceField(label="Verified 941 deposit schedule", choices=CaliforniaQuarterReview.DepositSchedule.choices)
    federal_headcount = forms.IntegerField(label="941 line 1 headcount for the pay period that includes the 12th of the last month", min_value=0)
    edd_month_1 = forms.IntegerField(label="DE 9C headcount for the pay period that includes the first month’s 12th", min_value=0)
    edd_month_2 = forms.IntegerField(label="DE 9C headcount for the pay period that includes the second month’s 12th", min_value=0)
    edd_month_3 = forms.IntegerField(label="DE 9C headcount for the pay period that includes the third month’s 12th", min_value=0)
    check_count = forms.IntegerField(label="Number of paid checks in the verified register", min_value=0)
    gross_pay = forms.DecimalField(label="Total gross pay in the verified register", min_value=0, max_digits=14, decimal_places=2)
    federal_deposits = forms.DecimalField(label="Confirmed 941 deposits allocated to this quarter", min_value=0, max_digits=14, decimal_places=2)
    california_deposits = forms.DecimalField(label="Confirmed DE 9 deposits allocated to this quarter", min_value=0, max_digits=14, decimal_places=2)
    verified = forms.BooleanField(label="I compared this quarter with the complete payroll register and agency payment confirmations.")


class QuarterReturnsForm(forms.Form):
    schedule_adjustments = forms.CharField(
        label="Verified liability schedule changes (one date and signed amount per line)",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "YYYY-MM-DD,-0.01"}),
        required=False, max_length=4000,
    )
    verified = forms.BooleanField(label="I verified the adjustments, credits, and applicable rates for this employer and quarter.")
    adjustment_note = forms.CharField(
        label="Adjustment source or reason", required=False, max_length=200,
        help_text="Record the preparer’s supporting reference or reason. Omit tax IDs.",
    )

    def __init__(self, *args, start, **kwargs):
        super().__init__(*args, **kwargs)
        self.start = start
        fields = (
            ("social_security_tips", "941 line 5b Social Security tips already included in recorded wages", 0),
            ("fractions_of_cents", "941 line 7 fractions-of-cents adjustment", None),
            ("sick_pay", "941 line 8 sick pay adjustment", None),
            ("tips_life", "941 line 9 tips and group-term life insurance adjustment", None),
            ("federal_tip_notice", "941 line 5f IRS notice tax on unreported tips", 0),
            ("research_credit", "941 line 11 credit from Form 8974", 0),
            ("federal_prior_credit", "IRS overpayment credits applied to this quarter", 0),
            ("unrefunded_sdi", "Erroneous SDI deductions not refunded", 0),
            ("edd_credit", "Other EDD credit applied to this quarter", 0),
        )
        for name, label, minimum in fields:
            self.fields[name] = forms.DecimalField(
                label=label, required=False, min_value=minimum, max_digits=14, decimal_places=2,
            )
        for name, label in (("ui", "Verified UI rate (%)"), ("ett", "Verified ETT rate (%)")):
            self.fields[f"{name}_rate_percent"] = forms.DecimalField(
                label=label, required=False, min_value=0, max_value=100, max_digits=7, decimal_places=4,
            )
        self.order_fields(tuple(name for name, _, _ in fields) + (
            "ui_rate_percent", "ett_rate_percent", "schedule_adjustments", "adjustment_note", "verified",
        ))

    def clean_schedule_adjustments(self):
        changes = {}
        for row in self.cleaned_data["schedule_adjustments"].splitlines():
            if not row.strip():
                continue
            raw_date, _, raw_amount = row.partition(",")
            try:
                day = date.fromisoformat(raw_date.strip())
                amount = recorded_amount(raw_amount.strip(), allow_negative=True)
                if not self.start <= day < quarter_end(self.start) or day in changes or abs(amount) >= Decimal("1000000000000"):
                    raise ValueError
            except (ValueError, InvalidOperation) as error:
                raise forms.ValidationError("Use one date within the quarter and one signed dollar amount per line.") from error
            changes[day] = amount
        return changes

    def clean(self):
        data = super().clean()
        if (data.get("ui_rate_percent") is None) != (data.get("ett_rate_percent") is None):
            raise forms.ValidationError("Enter both DE 9 rates or leave both blank.")
        return data


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def ca_quarterly_worksheet(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied

    is_post = request.method == "POST"
    voiding = is_post and request.POST.get("action") == "void"
    reviewing = is_post and request.POST.get("action") == "review"
    previewing = is_post and request.POST.get("action") == "preview_returns"
    selection = QuarterSelectionForm(request.POST if is_post else (request.GET or None))
    deposit_form = DepositConfirmationForm(request.POST if is_post and not (voiding or reviewing or previewing) else None)
    void_form = VoidDepositForm(request.POST if voiding else None)
    review_form = QuarterReviewForm(request.POST) if reviewing else None
    context = {"selection": selection, "deposit_form": deposit_form, "void_form": void_form}
    if selection.is_valid():
        employer = selection.cleaned_data["employer"]
        quarter = selection.cleaned_data["quarter"]
        start = date(2026, 3 * quarter - 2, 1)
        action_form = review_form if reviewing else (void_form if voiding else deposit_form)
        if is_post and not previewing and action_form.is_valid():
            try:
                if reviewing:
                    values = review_form.cleaned_data.copy()
                    values.pop("verified")
                    headcounts = tuple(values.pop(f"edd_month_{month}") for month in (1, 2, 3))
                    sign_off_quarter(
                        employer_id=employer.pk, start=start, reviewer_id=request.user.pk,
                        edd_headcounts=headcounts, **values,
                    )
                elif voiding:
                    void_ca_tax_deposit(
                        employer_id=employer.pk, period_start=start, reviewer_id=request.user.pk,
                        allowed_kinds=QUARTERLY_KINDS,
                        **void_form.cleaned_data,
                    )
                else:
                    fields = {key: value for key, value in deposit_form.cleaned_data.items() if key != "confirmed"}
                    record_ca_tax_deposit(
                        employer_id=employer.pk, period_start=start, recorded_by_id=request.user.pk,
                        **fields,
                    )
            except (ValidationError, ValueError) as error:
                action_form.add_error(None, str(error) if isinstance(error, ValueError) else error)
            else:
                return redirect(f"{reverse('ca-quarterly-worksheet')}?{urlencode({'employer': employer.pk, 'quarter': quarter})}")

        returns_form = QuarterReturnsForm(request.POST if previewing else None, start=start)
        context.update(employer=employer, quarter=quarter, review_form=review_form, returns_form=returns_form)
        try:
            sources = read_quarter_sources(employer.pk, start)
        except ValueError as error:
            context["worksheet_error"] = str(error)
        else:
            latest_review = CaliforniaQuarterReview.objects.filter(
                employer=employer, period_start=start,
            ).order_by("-pk").first()
            review_is_current = latest_review is not None and latest_review.fingerprint == sources.fingerprint
            context.update(
                worksheet=sources.worksheet, deposits=sources.deposits, profile=sources.profile,
                recorded_gross_pay=sources.gross_pay, latest_review=latest_review, review_is_current=review_is_current,
                review_form=review_form if reviewing else QuarterReviewForm(initial={"fingerprint": sources.fingerprint}),
            )
            return_rows = None
            if previewing and returns_form.is_valid():
                try:
                    if not sources.profile or sources.profile.federal_return != "941":
                        raise ValueError("Verify the employer’s Form 941 filing profile first.")
                    return_rows = build_quarterly_return_rows(sources.worksheet, adjustments=returns_form.cleaned_data)
                    changes = returns_form.cleaned_data["schedule_adjustments"]
                    schedule = latest_review.deposit_schedule if review_is_current else None
                    if changes and schedule not in ("monthly", "semiweekly"):
                        raise ValueError("Record a current monthly or semiweekly quarter review before entering liability changes.")
                    federal_tax = next(amount for line, _, amount in return_rows["941"] if line == "12")
                    schedule_rows = build_adjusted_941_schedule(
                        sources.worksheet["daily_federal_liability"], schedule, changes, federal_tax,
                    )
                    if schedule_rows:
                        return_rows["941 liability schedule"] = schedule_rows
                    elif schedule in ("monthly", "semiweekly") and (
                        federal_tax or changes or sources.worksheet["federal_tax_before_adjustments"]
                    ):
                        context["schedule_needs_reconciliation"] = True
                except ValueError as error:
                    returns_form.add_error(None, str(error))
                    return_rows = None
                else:
                    context["return_rows"] = return_rows
            export_worksheet = not is_post and request.GET.get("export") == "csv"
            export_returns = return_rows is not None and request.POST.get("export") == "csv"
            if export_worksheet or return_rows is not None:
                csv_text = write_quarterly_worksheet_csv(
                    context["worksheet"], employer_id=employer.pk, quarter=quarter,
                    current_review=latest_review if review_is_current else None,
                    return_rows=return_rows,
                )
            if return_rows is not None:
                kind = CaliforniaReviewedReport.Kind.QUARTERLY
                confirmation_forms = []
                if review_is_current:
                    if schedule == "de_minimis" or not context.get("schedule_needs_reconciliation"):
                        confirmation_forms.append("941")
                    if any(line == "Tax due" for line, _, _ in return_rows["DE 9"]):
                        confirmation_forms.append("DE9")
                    if complete_filing_ssns(sources.worksheet["employees"].keys()):
                        confirmation_forms.append("DE9C")
                source_records = {
                    "worksheet_revision": "2026-quarterly-v1", "fingerprint": sources.fingerprint,
                    "checks": sources.check_ids, "deposits": [entry.pk for entry in sources.deposits if not entry.voided_at],
                    "quarter_review": latest_review.pk if review_is_current else None,
                    "profile": sources.profile.pk,
                    "profile_reviewed_at": sources.profile.reviewed_at.isoformat(),
                    "confirmation_forms": confirmation_forms,
                    "review_inputs": normalized_review_inputs({
                        **returns_form.cleaned_data,
                        "schedule_adjustments": {day.isoformat(): amount for day, amount in changes.items()},
                    }),
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
                        returns_form.add_error(None, error)
                    else:
                        return redirect(f"{reverse('ca-reviewed-reports')}?employer={employer.pk}")
            if export_worksheet or export_returns:
                response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
                response["Content-Disposition"] = f'attachment; filename="ca-payroll-2026-q{quarter}-draft.csv"'
                return response
    return render(request, "report/ca_quarterly_worksheet.html", context)
