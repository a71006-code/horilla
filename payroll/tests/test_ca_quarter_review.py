from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from base.models import Company
from payroll.methods.ca_filing_review import save_filing_profile, sign_off_quarter
from payroll.methods.ca_tax_deposits import record_ca_tax_deposit
from payroll.models.models import CaliforniaQuarterReview
from report.views.ca_quarterly_worksheet import ca_quarterly_worksheet
from report.views.ca_filing_profile import ca_filing_profile


class CaliforniaQuarterReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer, = Company._base_manager.bulk_create([Company(company="Synthetic filing employer")])
        cls.reviewer = get_user_model().objects.create_superuser(username="synthetic-quarter-reviewer")

    def profile(self, **overrides):
        return save_filing_profile(**{
            "employer_id": self.employer.pk, "year": 2026, "legal_name": "Test Employer LLC",
            "ein": "12-3456789", "edd_account": "012-3456-7", "federal_return": "941",
            "reviewer_id": self.reviewer.pk, **overrides,
        })

    def sign(self, fingerprint, **overrides):
        return sign_off_quarter(**{
            "employer_id": self.employer.pk, "start": date(2026, 1, 1), "fingerprint": fingerprint,
            "reviewer_id": self.reviewer.pk, "deposit_schedule": "monthly",
            "federal_headcount": 0, "edd_headcounts": (0, 0, 0), "check_count": 0,
            "gross_pay": Decimal("0.00"), "federal_deposits": Decimal("0.00"),
            "california_deposits": Decimal("0.00"), **overrides,
        })

    def context(self):
        request = RequestFactory().get("/", {"employer": self.employer.pk, "quarter": 1})
        request.user = self.reviewer
        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()) as render:
            ca_quarterly_worksheet(request)
        return render.call_args.args[2]

    def test_profile_validates_distinct_agency_identifiers(self):
        self.assertEqual(self.profile().ein, "123456789")
        self.assertEqual(self.profile().edd_account, "01234567")
        with self.assertRaises(ValidationError):
            self.profile(edd_account="000-0000-0")

    def test_zero_wage_quarter_review_matches_source_and_detects_profile_change(self):
        self.profile()
        fingerprint = self.context()["review_form"].initial["fingerprint"]
        with self.assertRaisesMessage(ValidationError, "register"):
            self.sign(fingerprint, check_count=1)
        self.assertFalse(CaliforniaQuarterReview.objects.exists())
        first = self.sign(fingerprint)
        self.assertEqual(self.sign(fingerprint).pk, first.pk)
        with self.assertRaises(ValidationError):
            CaliforniaQuarterReview.objects.filter(pk=first.pk).update(federal_headcount=10)
        self.assertTrue(self.context()["review_is_current"])
        self.profile(edd_account="023-4567-8")
        self.assertFalse(self.context()["review_is_current"])
        with self.assertRaisesMessage(ValidationError, "changed"):
            self.sign(fingerprint)

    def test_post_previews_return_adjustments_without_recording_deposits(self):
        self.profile()
        request = RequestFactory().post("/", {
            "employer": self.employer.pk, "quarter": 1, "action": "preview_returns", "export": "csv",
            "verified": "on", "ui_rate_percent": "3.4", "ett_rate_percent": "0.1",
            "federal_prior_credit": "1.00", "edd_credit": "2.00",
        })
        request.user = self.reviewer
        request._dont_enforce_csrf_checks = True
        response = ca_quarterly_worksheet(request)
        self.assertIn(b"941 draft,15a,Overpayment,1.00", response.content)
        self.assertIn(b"DE 9 draft,Overpayment,Overpayment,2.00", response.content)
        self.assertEqual(self.context()["deposits"], [])

    def test_reviewed_quarter_csv_can_be_saved_only_for_the_previewed_values(self):
        from payroll.models.models import CaliforniaFiledReportConfirmation, CaliforniaReviewedReport
        from report.views.ca_reviewed_reports import ca_reviewed_report_confirmations, ca_reviewed_reports

        self.profile()
        self.sign(self.context()["review_form"].initial["fingerprint"])
        factory = RequestFactory()
        fields = {
            "employer": self.employer.pk, "quarter": 1, "action": "preview_returns",
            "verified": "on", "ui_rate_percent": "3.4", "ett_rate_percent": "0.1",
            "federal_prior_credit": "1.00",
        }

        def post(**overrides):
            request = factory.post("/", {**fields, **overrides})
            request.user = self.reviewer
            request._dont_enforce_csrf_checks = True
            return request

        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()) as render:
            ca_quarterly_worksheet(post())
            token = render.call_args.args[2]["archive_token"]
            ca_quarterly_worksheet(post(export="archive", archive_token=token, federal_prior_credit="2.00"))
            self.assertFalse(CaliforniaReviewedReport.objects.exists())
        response = ca_quarterly_worksheet(post(export="archive", archive_token=token))
        self.assertEqual(response.status_code, 302)
        ca_quarterly_worksheet(post(export="archive", archive_token=token))
        record = CaliforniaReviewedReport.objects.get()
        self.assertEqual(record.reviewed_by, self.reviewer)
        self.assertIn("941 draft,15a,Overpayment,1.00", record.csv_text)
        self.assertEqual(record.source_records["checks"], [])
        request = factory.get("/")
        request.user = self.reviewer
        download = ca_reviewed_reports(request, report_id=record.pk)
        self.assertIn("no-store", download["Cache-Control"])
        self.assertEqual(download.content.decode(), record.csv_text)

        for _ in range(2):
            request = factory.post("/", {
                "form_code": "941", "filed_on": "2026-04-15", "reference": "synthetic-receipt", "verified": "on",
            })
            request.user = self.reviewer
            request._dont_enforce_csrf_checks = True
            self.assertEqual(ca_reviewed_report_confirmations(request, record.pk).status_code, 302)
        self.assertEqual(CaliforniaFiledReportConfirmation.objects.get(report=record).reference, "synthetic-receipt")
        record_ca_tax_deposit(
            employer_id=self.employer.pk, kind="federal_941", period_start=date(2026, 1, 1),
            deposited_on=date(2026, 4, 1), amount=Decimal("3.00"), reference="later-deposit",
            recorded_by_id=self.reviewer.pk,
        )
        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()):
            ca_quarterly_worksheet(post(export="archive", archive_token=token))
        self.assertEqual(CaliforniaReviewedReport.objects.count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.csv_text, download.content.decode())
        self.profile(legal_name="Corrected name")
        request = factory.get("/")
        request.user = self.reviewer
        with patch("report.views.ca_reviewed_reports.render", return_value=HttpResponse()) as render:
            ca_reviewed_report_confirmations(request, record.pk)
        self.assertEqual(render.call_args.args[2]["identity"].legal_name, "Test Employer LLC")

        receipt = CaliforniaFiledReportConfirmation.objects.get(report=record)
        request = factory.post("/", {"action": "void", "confirmation_id": receipt.pk, "reason": "Wrong receipt"})
        request.user = self.reviewer
        request._dont_enforce_csrf_checks = True
        self.assertEqual(ca_reviewed_report_confirmations(request, record.pk).status_code, 302)
        self.assertEqual(receipt.void_record.reason, "Wrong receipt")
        self.assertEqual(CaliforniaFiledReportConfirmation.objects.count(), 1)

    def test_post_review_and_deposit_change_invalidates_it(self):
        factory = RequestFactory()
        profile = factory.post("/", {
            "employer": self.employer.pk, "legal_name": "Test Employer LLC", "ein": "12-3456789",
            "edd_account": "012-3456-7", "federal_return": "941", "verified": "on",
        })
        profile.user = self.reviewer
        profile._dont_enforce_csrf_checks = True
        self.assertEqual(ca_filing_profile(profile).status_code, 302)
        fingerprint = self.context()["review_form"].initial["fingerprint"]
        review = factory.post("/", {
            "employer": self.employer.pk, "quarter": 1, "action": "review", "fingerprint": fingerprint,
            "deposit_schedule": "monthly", "federal_headcount": 0, "edd_month_1": 0,
            "edd_month_2": 0, "edd_month_3": 0, "check_count": 0, "gross_pay": "0.00",
            "federal_deposits": "0.00", "california_deposits": "0.00", "verified": "on",
        })
        review.user = self.reviewer
        review._dont_enforce_csrf_checks = True
        self.assertEqual(ca_quarterly_worksheet(review).status_code, 302)
        self.assertEqual(CaliforniaQuarterReview.objects.get().reviewed_by, self.reviewer)
        export = factory.get("/", {"employer": self.employer.pk, "quarter": 1, "export": "csv"})
        export.user = self.reviewer
        self.assertIn(b"Line 1 headcount,0", ca_quarterly_worksheet(export).content)
        record_ca_tax_deposit(
            employer_id=self.employer.pk, kind="federal_941", period_start=date(2026, 1, 1),
            deposited_on=date(2026, 4, 1), amount=Decimal("1.00"), reference="late-test-record",
            recorded_by_id=self.reviewer.pk,
        )
        self.assertFalse(self.context()["review_is_current"])
        content = ca_quarterly_worksheet(export).content
        self.assertIn(b"Not recorded or stale", content)
        self.assertNotIn(b"Line 1 headcount", content)
