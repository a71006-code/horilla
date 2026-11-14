from csv import reader
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from base.models import Company
from employee.models import Employee
from payroll.methods.ca_de9c_reconciliation import record_filed_de9c
from payroll.methods.ca_filing_review import save_filing_profile
from payroll.models.models import CaliforniaFiledDe9c, Payslip, RecordedCaliforniaPaycheck
from report.views.ca_de9c_reconciliation import ca_de9c_reconciliation


class FiledDe9cTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer, cls.other_employer = Company._base_manager.bulk_create([
            Company(company="DE 9C test employer"), Company(company="Other DE 9C employer"),
        ])
        cls.employee, cls.other_employee = Employee._base_manager.bulk_create([
            Employee(employee_first_name="Test worker", email="first-de9c@example.com", is_active=False),
            Employee(employee_first_name="Other worker", email="second-de9c@example.com", is_active=False),
        ])
        cls.reviewer = get_user_model().objects.create_superuser(username="de9c-reviewer")
        cls.profile_fields = {
            "employer_id": cls.employer.pk, "year": 2026, "legal_name": "DE 9C Test Employer LLC",
            "ein": "12-3456789", "edd_account": "012-3456-7", "federal_return": "944",
            "reviewer_id": cls.reviewer.pk,
        }
        cls.profile = save_filing_profile(**cls.profile_fields)

    def make_check(self, employer, employee, paid_on, *, verified_edd=True):
        start = date(2025, 12, 22)
        end = date(2025, 12, 28)
        slip, = Payslip._base_manager.bulk_create([
            Payslip(employee_id=employee, start_date=start, end_date=end, status="paid", pay_head_data={}),
        ])
        RecordedCaliforniaPaycheck.objects.create(
            employer=employer, employee=employee, payslip=slip, work_period_start=start, work_period_end=end,
            paid_on=paid_on, facts={
                **({"ca_edd_subject_wages": "300.00", "ca_wage_plan_code": "S"} if verified_edd else {}),
                "federal_income_tax_wages": "300.00", "federal_income_tax": "20.00",
                "ca_pit_wages": "280.00", "ca_pit_withheld": "10.00",
                "contributions": {
                    "taxable_wages": dict(social_security="300", medicare="300", additional_medicare="0",
                                          ca_sdi="300", ca_ui="300", ca_ett="300"),
                    "employee_social_security": "18.60", "employer_social_security": "18.60",
                    "employee_medicare": "4.35", "employer_medicare": "4.35",
                    "employee_additional_medicare": "0.00", "employee_ca_sdi": "3.90",
                    "employer_ca_ui": "10.20", "employer_ca_ett": "0.30",
                },
            },
        )

    def save_rows(self, **overrides):
        return record_filed_de9c(**{
            "employer_id": self.employer.pk, "start": date(2026, 1, 1),
            "profile_version": self.profile.reviewed_at.isoformat(), "reviewer_id": self.reviewer.pk,
            "text": f"{self.employee.pk},280.00,10.00", "no_payroll": False,
            "current_entry_id": 0, "replace_current": False, **overrides,
        })

    def test_replacements_are_versioned_and_stale_forms_cannot_overwrite(self):
        first = self.save_rows()
        self.assertEqual(self.save_rows().pk, first.pk)
        replacement = f"{self.employee.pk},285.00,10.00"
        with self.assertRaisesMessage(ValidationError, "Confirm"):
            self.save_rows(text=replacement, current_entry_id=first.pk)
        second = self.save_rows(text=replacement, current_entry_id=first.pk, replace_current=True)
        with self.assertRaisesMessage(ValidationError, "changed"):
            self.save_rows(current_entry_id=first.pk, replace_current=True)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(CaliforniaFiledDe9c.objects.get(pk=first.pk).employee_rows[str(self.employee.pk)]["pit_wages"], "280.00")
        self.assertEqual(second.reviewed_by, self.reviewer)

    def test_view_records_and_exports_only_selected_employer_and_paid_quarter(self):
        self.make_check(self.employer, self.employee, date(2026, 1, 3))
        self.make_check(self.employer, self.employee, date(2026, 4, 3))
        self.make_check(self.other_employer, self.other_employee, date(2026, 1, 3))
        path = reverse("ca-de9c-reconciliation")
        factory = RequestFactory()
        request = factory.post(path, {
            "employer": self.employer.pk, "quarter": 1, "verified": "on",
            "profile_version": self.profile.reviewed_at.isoformat(), "current_entry_id": 0,
            "text": f"{self.employee.pk},280.00,10.01,300.00,S",
        })
        request.user = self.reviewer
        request._dont_enforce_csrf_checks = True
        self.assertEqual(ca_de9c_reconciliation(request).status_code, 302)

        export = factory.get(path, {"employer": self.employer.pk, "quarter": 1, "export": "csv"})
        export.user = self.reviewer
        response = ca_de9c_reconciliation(export)
        data = list(reader(StringIO(response.content.decode())))
        self.assertEqual(data[3:], [[
            str(self.employee.pk), "Amounts differ", "280.00", "280.00", "0.00", "10.00", "10.01", "0.01",
            "300.00", "300.00", "0.00", "S", "S",
        ]])
        self.assertNotIn(b"Test worker", response.content)
        self.assertNotIn(b"01234567", response.content)
        self.assertIn("no-store", response["Cache-Control"])

        save_filing_profile(**{**self.profile_fields, "edd_account": "023-4567-8"})
        self.assertIn(b"Filed rows needed", ca_de9c_reconciliation(export).content)

    def test_partially_reviewed_subject_wages_do_not_produce_a_difference(self):
        self.make_check(self.employer, self.employee, date(2026, 1, 3))
        self.make_check(self.employer, self.employee, date(2026, 2, 3), verified_edd=False)
        self.save_rows(text=f"{self.employee.pk},560,20,600,S")
        request = RequestFactory().get(reverse("ca-de9c-reconciliation"), {
            "employer": self.employer.pk, "quarter": 1, "export": "csv",
        })
        request.user = self.reviewer
        data = list(reader(StringIO(ca_de9c_reconciliation(request).content.decode())))
        self.assertEqual(data[-1][1], "Recorded EDD fields needed")
        self.assertEqual(data[-1][8:], ["", "600.00", "", "", "S"])

    def test_staff_cannot_access_reconciliation_or_download(self):
        request = RequestFactory().get(reverse("ca-de9c-reconciliation"), {"export": "csv"})
        request.user = get_user_model().objects.create_user(username="de9c-staff", is_staff=True)
        with self.assertRaises(PermissionDenied):
            ca_de9c_reconciliation(request)

    def test_unknown_numeric_identifier_is_rejected_without_storing_it(self):
        with self.assertRaisesMessage(ValidationError, "existing Horilla employee record IDs"):
            self.save_rows(text="999999999,0.00,0.00")
        self.assertFalse(CaliforniaFiledDe9c.objects.exists())
        entry = self.save_rows(text="-,0.00,0.00")
        self.assertEqual(entry.employee_rows, {"-1": {"pit_wages": "0.00", "pit_withheld": "0.00"}})
