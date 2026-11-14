from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from base.models import Company
from payroll.methods.ca_tax_deposits import record_ca_tax_deposit, void_ca_tax_deposit
from payroll.models.models import RecordedCaliforniaTaxDeposit
from report.views.ca_annual_worksheet import ca_annual_worksheet
from report.views.ca_quarterly_worksheet import ca_quarterly_worksheet


class CaliforniaTaxDepositTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer, = Company._base_manager.bulk_create([Company(company="Synthetic employer")])
        cls.reviewer = get_user_model().objects.create_superuser(username="synthetic-deposit-reviewer")

    def record(self, **overrides):
        return record_ca_tax_deposit(**{
            "employer_id": self.employer.pk, "kind": "federal_941",
            "period_start": date(2026, 1, 1), "deposited_on": date(2026, 4, 15),
            "amount": Decimal("180.23"), "reference": "confirm-001",
            "recorded_by_id": self.reviewer.pk, **overrides,
        })

    def test_same_verified_deposit_is_recorded_once(self):
        first = self.record()
        self.assertEqual(self.record().pk, first.pk)
        self.assertEqual(first.period_start, date(2026, 1, 1))
        self.assertEqual(first.deposited_on, date(2026, 4, 15))
        self.assertEqual(first.recorded_by, self.reviewer)
        with self.assertRaises(ValidationError):
            self.record(amount=Decimal("200.00"))
        self.assertEqual(RecordedCaliforniaTaxDeposit.objects.get().amount, Decimal("180.23"))

    def test_rejects_invalid_tax_period_and_fractional_cent(self):
        for fields in ({"period_start": date(2026, 2, 1)}, {"amount": Decimal("1.001")}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.record(**fields)
        self.assertFalse(RecordedCaliforniaTaxDeposit.objects.exists())

    def test_940_uses_annual_allocation_and_is_separate_from_941(self):
        quarterly = self.record()
        factory = RequestFactory()
        request = factory.post("/", {
            "employer": self.employer.pk, "year": 2026, "kind": "federal_940",
            "deposited_on": "2026-04-15", "amount": "90.50", "reference": "annual-confirm-001",
            "confirmed": "on",
        })
        request.user = self.reviewer
        request._dont_enforce_csrf_checks = True
        self.assertEqual(ca_annual_worksheet(request).status_code, 302)
        annual = RecordedCaliforniaTaxDeposit.objects.get(kind="federal_940")
        self.assertNotEqual(quarterly.pk, annual.pk)
        export = factory.get("/", {"employer": self.employer.pk, "year": 2026, "export": "csv"})
        export.user = self.reviewer
        self.assertIn(b"Recorded 940 deposits,90.50", ca_annual_worksheet(export).content)
        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()) as render:
            get = factory.get("/", {"employer": self.employer.pk, "quarter": 1})
            get.user = self.reviewer
            ca_quarterly_worksheet(get)
            self.assertEqual(render.call_args.args[2]["worksheet"]["federal_deposits"], quarterly.amount)
        with self.assertRaises(ValidationError):
            self.record(kind="federal_940", period_start=date(2026, 4, 1))
        with self.assertRaisesMessage(ValidationError, "different federal return"):
            self.record(kind="federal_940", reference=quarterly.reference)

    def test_void_preserves_history_and_requires_explicit_replacement(self):
        first = self.record()
        void_ca_tax_deposit(
            deposit_id=first.pk, employer_id=self.employer.pk, period_start=first.period_start,
            reason="Agency confirmation shows Q2", reviewer_id=self.reviewer.pk,
        )
        first.refresh_from_db()
        self.assertIsNotNone(first.voided_at)
        self.assertEqual(first.voided_by, self.reviewer)
        with self.assertRaises(ValidationError):
            self.record()
        replacement = self.record(period_start=date(2026, 4, 1), replace_voided=True)
        self.assertNotEqual(replacement.pk, first.pk)
        self.assertEqual(RecordedCaliforniaTaxDeposit.objects.filter(voided_at__isnull=True).count(), 1)

    def test_worksheet_records_post_and_keeps_april_deposit_in_q1(self):
        factory = RequestFactory()
        fields = {"employer": self.employer.pk, "quarter": 1}
        post = factory.post("/", {
            **fields, "kind": "federal_941", "deposited_on": "2026-04-15",
            "amount": "180.23", "reference": "confirmed-941", "confirmed": "on",
        })
        post.user = self.reviewer
        post._dont_enforce_csrf_checks = True
        response = ca_quarterly_worksheet(post)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecordedCaliforniaTaxDeposit.objects.count(), 1)
        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()) as render:
            for quarter, amount in ((1, Decimal("180.23")), (2, Decimal("0.00"))):
                get = factory.get("/", {**fields, "quarter": quarter})
                get.user = self.reviewer
                ca_quarterly_worksheet(get)
                worksheet = render.call_args.args[2]["worksheet"]
                self.assertEqual(worksheet["federal_deposits"], amount)
                self.assertEqual(worksheet["federal_tax_before_adjustments"], Decimal("0.00"))

            void = factory.post("/", {
                **fields, "action": "void", "deposit_id": RecordedCaliforniaTaxDeposit.objects.get().pk,
                "reason": "Wrong quarter on entry",
            })
            void.user = self.reviewer
            void._dont_enforce_csrf_checks = True
            self.assertEqual(ca_quarterly_worksheet(void).status_code, 302)
            get = factory.get("/", fields)
            get.user = self.reviewer
            ca_quarterly_worksheet(get)
            context = render.call_args.args[2]
            self.assertEqual(context["worksheet"]["federal_deposits"], Decimal("0.00"))
            self.assertEqual(context["deposits"][0].void_reason, "Wrong quarter on entry")
