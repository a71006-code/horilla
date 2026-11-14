import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from base.models import Company
from employee.models import Employee
from payroll.methods.ca_filing_review import read_quarter_sources, save_filing_profile, sign_off_quarter
from payroll.methods.ca_payroll_check import calculate_ca_payroll_check
from payroll.methods.ca_payroll_recording import paid_slip_review_state, record_paid_ca_paycheck
from payroll.methods.us_ca_contributions import CaliforniaEmployerNotice, SubjectWages
from payroll.models.models import Payslip, RecordedCaliforniaPaycheck
from payroll.views.ca_paycheck_review import review_ca_paycheck
from report.views.ca_annual_worksheet import ca_annual_worksheet
from report.views.ca_filing_profile import ca_filing_profile
from report.views.ca_quarterly_worksheet import ca_quarterly_worksheet
from report.views.ca_reviewed_reports import ca_reviewed_reports


class RecordedCaliforniaPaycheckTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer, cls.other_employer = Company._base_manager.bulk_create([
            Company(company="Synthetic CA employer"), Company(company="Another employer"),
        ])
        cls.employee, = Employee._base_manager.bulk_create([
            Employee(employee_first_name="Synthetic", email="payroll-test@example.com", is_active=False),
        ])
        zero = Decimal("0.00")
        wages = Decimal("1000.00")
        cls.calculation = calculate_ca_payroll_check(
            pay_date=date(2026, 1, 2), pay_frequency="weekly", gross_pay=wages,
            federal_income_tax_wages=wages, ca_pit_wages=wages,
            current_subject_wages=SubjectWages(
                social_security=wages, medicare=wages, ca_sdi=wages,
                ca_ui=wages, ca_ett=wages, futa=wages,
            ),
            prior_ytd_subject_wages=SubjectWages(
                social_security=zero, medicare=zero, ca_sdi=zero,
                ca_ui=zero, ca_ett=zero, futa=zero,
            ),
            employer_notice=CaliforniaEmployerNotice(
                tax_year=2026, ui_rate=Decimal("0.034"), ett_rate=Decimal("0.001"),
            ),
        )

    def make_payslip(self, *, status="paid", net_pay=None):
        slip, = Payslip._base_manager.bulk_create([
            Payslip(
                employee_id=self.employee, start_date=date(2025, 12, 22),
                end_date=date(2025, 12, 28), status=status, pay_head_data={},
                gross_pay=1000.0,
                net_pay=float(self.calculation.net_pay) if net_pay is None else net_pay,
            ),
        ])
        return slip

    def record(self, slip, employer=None):
        return record_paid_ca_paycheck(
            payslip_id=slip.pk, employer_id=(employer or self.employer).pk,
            calculation=self.calculation,
        )

    def test_reporting_follows_paid_date_and_recorded_employer_for_former_employee(self):
        record = self.record(self.make_payslip())
        record.refresh_from_db()
        self.assertEqual(record.facts["federal_income_tax"], "78.08")
        self.assertEqual(record.facts["subject_wages"]["medicare"], "1000.00")
        self.assertEqual(record.facts["employer_notice"]["ui_rate"], "0.034")
        self.assertEqual(record.facts["contributions"]["taxable_wages"]["social_security"], "1000.00")
        january = date(2026, 1, 1), date(2026, 2, 1)
        records = RecordedCaliforniaPaycheck.objects.for_period(self.employer.pk, *january)
        self.assertEqual(list(records), [record])
        self.assertFalse(RecordedCaliforniaPaycheck.objects.for_period(self.other_employer.pk, *january).exists())
        self.assertFalse(RecordedCaliforniaPaycheck.objects.for_period(
            self.employer.pk, date(2025, 12, 1), january[0],
        ).exists())

    def test_paid_review_rejects_overlapping_ytd_wages(self):
        self.record(self.make_payslip())
        with self.assertRaisesMessage(ValidationError, "overlap"):
            self.record(self.make_payslip())

    def test_repeated_recording_is_idempotent_and_conflicting_employer_is_rejected(self):
        slip = self.make_payslip()
        first = self.record(slip)
        self.assertEqual(self.record(slip).pk, first.pk)
        with self.assertRaises(ValidationError):
            self.record(slip, self.other_employer)

    def test_unpaid_slip_and_mismatched_payment_are_rejected(self):
        for slip in (self.make_payslip(status="confirmed"), self.make_payslip(net_pay=0.0)):
            with self.subTest(status=slip.status), self.assertRaises(ValidationError):
                self.record(slip)
        self.assertFalse(RecordedCaliforniaPaycheck.objects.exists())

    def test_recorded_facts_are_write_once(self):
        slip = self.make_payslip()
        record = self.record(slip)
        Payslip._base_manager.filter(pk=slip.pk).update(net_pay=0)
        self.assertEqual(self.record(slip).facts["net_pay"], str(self.calculation.net_pay))
        for mutate in (
            lambda: record.save(),
            lambda: record.delete(),
            lambda: RecordedCaliforniaPaycheck.objects.filter(pk=record.pk).update(facts={}),
            lambda: RecordedCaliforniaPaycheck.objects.filter(pk=record.pk).delete(),
        ):
            with self.assertRaises(ValidationError):
                mutate()

    def test_recording_checks_reviewed_work_period_under_lock(self):
        slip = self.make_payslip()
        expected = paid_slip_review_state(slip)
        Payslip._base_manager.filter(pk=slip.pk).update(end_date=date(2025, 12, 29))
        with self.assertRaisesMessage(ValidationError, "payslip changed"):
            record_paid_ca_paycheck(
                payslip_id=slip.pk, employer_id=self.employer.pk, calculation=self.calculation,
                expected_slip_state=expected,
            )
        self.assertFalse(RecordedCaliforniaPaycheck.objects.exists())

    def test_review_form_records_actual_inputs_and_reviewer(self):
        reviewer = get_user_model().objects.create_superuser(username="payroll-reviewer")
        slip = self.make_payslip()
        fields = {
            "employer": self.employer.pk, "pay_date": "2026-01-02", "pay_frequency": "weekly",
            "federal_income_tax_wages": "1000.00", "ca_pit_wages": "1000.00",
            "ca_edd_subject_wages": "1000.00", "ca_wage_plan_code": "S",
            "ui_rate": "3.4", "ett_rate": "0.1", "ca_status": "single_or_dual_income",
        }
        for tax in ("social_security", "medicare", "ca_sdi", "ca_ui", "ca_ett", "futa"):
            fields[f"wages_{tax}"] = "1000.00"
            fields[f"prior_{tax}"] = "0.00"

        def post(**changes):
            request = RequestFactory().post("/", {**fields, **changes})
            request.user = reviewer
            request._dont_enforce_csrf_checks = True
            return request

        with patch("payroll.views.ca_paycheck_review.render", side_effect=lambda *args, **kwargs: HttpResponse()) as render:
            review_ca_paycheck(post(action="preview"), slip.pk)
            context = render.call_args.args[2]
            self.assertTrue(context.get("matches_payment"), context["form"].errors)
            self.assertFalse(RecordedCaliforniaPaycheck.objects.exists())
            review_ca_paycheck(post(
                action="record", review_token=context["review_token"], verified_payment="on",
            ), slip.pk)

        record = RecordedCaliforniaPaycheck.objects.get(payslip_id=slip.pk)
        self.assertEqual(record.recorded_by, reviewer)
        self.assertEqual(record.paid_on, date(2026, 1, 2))
        self.assertEqual(record.facts["federal_income_tax"], "78.08")
        self.assertEqual(record.facts["ca_edd_subject_wages"], "1000.00")
        request = RequestFactory().get("/", {"employer": self.employer.pk, "quarter": 1, "export": "csv"})
        request.user = reviewer
        response = ca_quarterly_worksheet(request)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn(b"Subject wages,1000.00", response.content)

    def test_annual_csv_reads_checks_by_payment_year_and_employer(self):
        self.record(self.make_payslip())
        reviewer = get_user_model().objects.create_superuser(username="annual-reviewer")
        factory = RequestFactory()
        for employer, expected in ((self.employer, True), (self.other_employer, False)):
            request = factory.get("/", {"employer": employer.pk, "year": 2026, "export": "csv"})
            request.user = reviewer
            response = ca_annual_worksheet(request)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("draft.csv", response["Content-Disposition"])
            self.assertEqual(b"78.08" in response.content, expected)

    def test_annual_csv_compares_independently_entered_filed_quarter(self):
        self.record(self.make_payslip())
        reviewer = get_user_model().objects.create_superuser(username="filed-totals-reviewer")
        profile = {
            "employer_id": self.employer.pk, "year": 2026, "legal_name": "Synthetic employer",
            "ein": "12-3456789", "edd_account": "012-3456-7", "federal_return": "941",
            "reviewer_id": reviewer.pk,
        }
        verified_profile = save_filing_profile(**profile)
        factory = RequestFactory()
        fields = {"employer": self.employer.pk, "year": 2026}
        amounts = {
            "box_1": "1000.00", "box_2": "78.08", "box_3": "1000.00", "box_5": "1000.00",
            "box_7": "0.00", "box_16": "1000.00", "box_17": str(self.calculation.ca_pit_withheld),
            "fica_tax": "153.01", "fica_rounding": "-0.01", "sick_pay_adjustment": "0.00",
            "tips_life_adjustment": "0.00",
        }

        def record_filed(**overrides):
            request = factory.post("/", {
                **fields, "action": "filed_totals", "quarter": 1, "verified": "on",
                "profile_version": verified_profile.reviewed_at.isoformat(), **amounts, **overrides,
            })
            request.user = reviewer
            request._dont_enforce_csrf_checks = True
            with patch("report.views.ca_annual_worksheet.render", return_value=HttpResponse()):
                return ca_annual_worksheet(request)

        def export():
            request = factory.get("/", {**fields, "export": "csv"})
            request.user = reviewer
            return ca_annual_worksheet(request).content

        self.assertEqual(record_filed(verified="").status_code, 200)
        self.assertIn(b"Filed quarter reconciliation,Q1,Status,Missing", export())
        self.assertEqual(record_filed().status_code, 302)
        self.assertIn(b"Filed quarter reconciliation,Q1,Status,Matched", export())
        self.assertIn(b"Employee withholding plus statutory employer FICA,153.00,153.00,0.00", export())
        self.assertIn(b"Filed quarter reconciliation,Q2,Status,Missing", export())
        self.assertEqual(record_filed(box_2="80.08").status_code, 200)
        self.assertIn(b"Filed quarter reconciliation,Q1,Status,Matched", export())
        self.assertEqual(record_filed(box_2="80.08", replace_current="on").status_code, 302)
        self.assertIn(b"Filed quarter reconciliation,Q1,Status,Differences", export())
        self.assertIn(b"Form 941 line 3 / W-3 box 2,78.08,80.08,-2.00", export())
        save_filing_profile(**{**profile, "edd_account": "023-4567-8"})
        self.assertEqual(record_filed().status_code, 200)
        self.assertIn(b"Filed quarter reconciliation,Q1,Status,Missing", export())

    def test_annual_csv_exports_form_940_preview_from_recorded_checks(self):
        self.record(self.make_payslip())
        reviewer = get_user_model().objects.create_superuser(username="form-940-reviewer")
        request = RequestFactory().post("/", {
            "employer": self.employer.pk, "year": 2026, "action": "preview_940",
            "coverage": "timely", "rate_percent": "1.50", "prior_credit": "1.00", "export": "csv",
        })
        request.user = reviewer
        request._dont_enforce_csrf_checks = True
        response = ca_annual_worksheet(request)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn(b"Form 940 draft,8,FUTA tax before adjustments,6.00", response.content)
        self.assertIn(b"Form 940 draft,11,Schedule A California credit reduction,15.00", response.content)
        self.assertIn(b"Form 940 draft,14,Balance due,20.00", response.content)

    def test_filing_profile_lists_only_masked_identities_from_selected_employer(self):
        self.record(self.make_payslip())
        Employee._base_manager.filter(pk=self.employee.pk).update(ssn="123-45-6789")
        reviewer = get_user_model().objects.create_superuser(username="identity-reviewer")
        for company, expected in ((self.employer, "•••-••-6789"), (self.other_employer, None)):
            request = RequestFactory().get("/", {"employer": company.pk})
            request.user = reviewer
            with patch("report.views.ca_filing_profile.render", return_value=HttpResponse()) as render:
                response = ca_filing_profile(request)
            self.assertIn("no-store", response["Cache-Control"])
            rows = render.call_args.args[2]["employee_identities"]
            self.assertEqual([row["masked_ssn"] for row in rows], [expected] if expected else [])

    def test_annual_csv_exports_verified_w2_entries_and_leaves_other_fields_unresolved(self):
        from payroll.models.models import CaliforniaReviewedReport

        self.record(self.make_payslip())
        reviewer = get_user_model().objects.create_superuser(username="w2-handoff-reviewer")
        factory = RequestFactory()
        selection = {"employer": self.employer.pk, "year": 2026}
        request = factory.get("/", selection)
        request.user = reviewer
        with patch("report.views.ca_annual_worksheet.render", return_value=HttpResponse()) as render:
            ca_annual_worksheet(request)
        source = render.call_args.args[2]["w2_form"].initial["source"]
        preview_fields = {
            **selection, "action": "preview_w2", "verified": "on", "export": "csv",
            "source": source, "entries": f"{self.employee.pk},TT,10.00",
        }
        request = factory.post("/", preview_fields)
        request.user = reviewer
        request._dont_enforce_csrf_checks = True
        response = ca_annual_worksheet(request)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Code TT (qualified overtime premium),10.00", response.content.decode())
        self.assertIn("Allocated tips,Unresolved", response.content.decode())
        with patch("report.views.ca_annual_worksheet.render", return_value=HttpResponse()) as render:
            request = factory.post("/", {**preview_fields, "export": ""})
            request.user = reviewer
            request._dont_enforce_csrf_checks = True
            ca_annual_worksheet(request)
            token = render.call_args.args[2]["archive_token"]
        request = factory.post("/", {**preview_fields, "export": "archive", "archive_token": token})
        request.user = reviewer
        request._dont_enforce_csrf_checks = True
        self.assertEqual(ca_annual_worksheet(request).status_code, 302)
        archived = CaliforniaReviewedReport.objects.get()
        self.assertEqual(archived.kind, CaliforniaReviewedReport.Kind.WAGE_STATEMENTS)
        self.assertEqual(archived.csv_text, response.content.decode())
        request = factory.get("/")
        request.user = get_user_model().objects.create_user(username="archive-view-denied")
        with self.assertRaises(PermissionDenied):
            ca_reviewed_reports(request, report_id=archived.pk)

    def test_nine_employee_close_reconciles_quarterly_and_annual_wage_bases(self):
        employees = Employee._base_manager.bulk_create([
            Employee(employee_first_name="Synthetic", employee_last_name="Employee", email=f"close-{number}@example.com")
            for number in range(9)
        ])
        reviewer = get_user_model().objects.create_superuser(username="synthetic-close-reviewer")
        save_filing_profile(
            employer_id=self.employer.pk, year=2026, legal_name="Synthetic close employer",
            ein="12-3456789", edd_account="012-3456-7", federal_return="941", reviewer_id=reviewer.pk,
        )
        bases = ("social_security", "medicare", "ca_sdi", "ca_ui", "ca_ett", "futa")
        for index, employee in enumerate(employees):
            periods = [(date(2026, 1, 2), 4000, 0), (date(2026, 2, 5), 4000, 4000)] if index == 0 else [
                (date(2026, 3, 5), 1000, 0),
            ]
            for paid_on, gross, prior in periods:
                calculation = calculate_ca_payroll_check(
                    pay_date=paid_on, pay_frequency="weekly", gross_pay=Decimal(gross),
                    federal_income_tax_wages=Decimal(gross), ca_pit_wages=Decimal(gross),
                    ca_edd_subject_wages=Decimal(gross), ca_wage_plan_code="S",
                    current_subject_wages=SubjectWages(**dict.fromkeys(bases, Decimal(gross))),
                    prior_ytd_subject_wages=SubjectWages(**dict.fromkeys(bases, Decimal(prior))),
                    employer_notice=self.calculation.employer_notice,
                )
                slip, = Payslip._base_manager.bulk_create([Payslip(
                    employee_id=employee, start_date=date(2025, 12, 22), end_date=date(2025, 12, 28),
                    status="paid", pay_head_data={}, gross_pay=float(gross), net_pay=float(calculation.net_pay),
                )])
                record_paid_ca_paycheck(
                    payslip_id=slip.pk, employer_id=self.employer.pk, calculation=calculation,
                    recorded_by_id=reviewer.pk,
                )

        def export(view, fields):
            request = RequestFactory().post("/", {"employer": self.employer.pk, "export": "csv", **fields})
            request.user = reviewer
            request._dont_enforce_csrf_checks = True
            response = view(request)
            self.assertEqual(response.status_code, 200)
            return list(csv.reader(StringIO(response.content.decode())))

        quarterly = export(ca_quarterly_worksheet, {
            "quarter": 1, "action": "preview_returns", "verified": "on", "ui_rate_percent": "3.4", "ett_rate_percent": "0.1",
        })
        self.assertIn(["941 draft", "5e", "Total Social Security and Medicare taxes", "2448.00"], quarterly)
        self.assertIn(["DE 9 draft", "Subject wages", "Total subject wages paid this quarter", "16000.00"], quarterly)
        self.assertIn(["DE 9 draft", "UI", "Employer UI contributions", "510.00"], quarterly)
        employee_rows = [row for row in quarterly if row[0] == "DE 9C draft" and row[2] == "Subject wages"]
        self.assertEqual(len(employee_rows), 9)
        self.assertEqual(sum(Decimal(row[3]) for row in employee_rows), Decimal("16000.00"))
        start = date(2026, 1, 1)
        source = read_quarter_sources(self.employer.pk, start)
        sign_off_quarter(
            employer_id=self.employer.pk, start=start, fingerprint=source.fingerprint,
            reviewer_id=reviewer.pk, deposit_schedule="monthly", federal_headcount=9,
            edd_headcounts=(1, 1, 9), check_count=10, gross_pay=Decimal("16000"),
            federal_deposits=Decimal("0"), california_deposits=Decimal("0"),
        )
        line_6 = next(row[3] for row in quarterly if row[:2] == ["941 draft", "6"])
        request = RequestFactory().post("/", {
            "employer": self.employer.pk, "quarter": 1, "action": "preview_returns",
            "verified": "on", "sick_pay": f"-{line_6}",
        })
        request.user = reviewer
        request._dont_enforce_csrf_checks = True
        with patch("report.views.ca_quarterly_worksheet.render", return_value=HttpResponse()) as render:
            ca_quarterly_worksheet(request)
        self.assertTrue(render.call_args.args[2]["schedule_needs_reconciliation"])

        annual = export(ca_annual_worksheet, {
            "year": 2026, "action": "preview_940", "coverage": "timely", "rate_percent": "1.50", "prior_credit": "0",
        })
        self.assertIn(["Form 940 draft", "7", "Taxable FUTA wages", "15000.00"], annual)
        self.assertIn(["Form 940 draft", "12", "Total FUTA tax after adjustments", "315.00"], annual)
        w2_rows = [row for row in annual if row[0] == "W-2 draft" and row[2].startswith("Box 5 ")]
        self.assertEqual(len(w2_rows), 9)
        w3_box_5 = next(Decimal(row[3]) for row in annual if row[0] == "W-3 draft" and row[2].startswith("Box 5 "))
        self.assertEqual(sum(Decimal(row[3]) for row in w2_rows), w3_box_5)
        self.assertEqual(w3_box_5, Decimal("16000.00"))

    def test_legacy_check_gets_edd_fields_without_changing_original(self):
        record = self.record(self.make_payslip())
        reviewer = get_user_model().objects.create_superuser(username="edd-supplement-reviewer")
        original = read_quarter_sources(self.employer.pk, date(2026, 1, 1))
        self.assertEqual(original.worksheet["missing_de9c_check_count"], 1)
        request = RequestFactory().post("/", {
            "action": "supplement_edd", "subject_wages": "1000.00", "plan_code": "S", "verified": "on",
        })
        request.user = reviewer
        request._dont_enforce_csrf_checks = True
        self.assertEqual(review_ca_paycheck(request, record.payslip_id).status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.edd_review.reviewed_by, reviewer)
        self.assertNotIn("ca_edd_subject_wages", record.facts)
        updated = read_quarter_sources(self.employer.pk, date(2026, 1, 1))
        self.assertEqual(updated.worksheet["missing_de9c_check_count"], 0)
        self.assertEqual(updated.worksheet["edd_subject_wages"], Decimal("1000.00"))
        self.assertNotEqual(original.fingerprint, updated.fingerprint)
