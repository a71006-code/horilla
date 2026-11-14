from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from payroll.methods.ca_payroll_recording import paid_slip_review_state
from payroll.views.ca_paycheck_review import review_ca_paycheck


class CaliforniaPaycheckReviewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.slip = Mock(
            pk=15, status="paid", employee_id_id=12, gross_pay=1000.0, net_pay=816.59,
            start_date=date(2025, 12, 22), end_date=date(2025, 12, 28),
        )
        self.calculation = Mock(pay_date=date(2026, 1, 2), gross_pay=Decimal("1000.00"), net_pay=Decimal("816.59"))

    def request(self, fields=None, *, superuser=True):
        request = self.factory.get("/") if fields is None else self.factory.post("/", fields)
        request.user = Mock(pk=2, is_superuser=superuser, is_authenticated=True)
        # Direct view invocation has no CSRF middleware. The actual route is protected.
        request._dont_enforce_csrf_checks = True
        return request

    def test_non_superuser_cannot_look_up_payslips(self):
        with patch("payroll.views.ca_paycheck_review.get_object_or_404") as lookup:
            with self.assertRaises(PermissionDenied):
                review_ca_paycheck(self.request(superuser=False), 15)
            lookup.assert_not_called()

    def test_post_without_csrf_is_rejected_before_lookup(self):
        request = self.request({"action": "record"})
        request._dont_enforce_csrf_checks = False
        with patch("payroll.views.ca_paycheck_review.get_object_or_404") as lookup:
            self.assertEqual(review_ca_paycheck(request, 15).status_code, 403)
            lookup.assert_not_called()

    @patch("payroll.views.ca_paycheck_review.record_paid_ca_paycheck")
    @patch("payroll.views.ca_paycheck_review.render")
    @patch("payroll.views.ca_paycheck_review.CaliforniaPaycheckReviewForm")
    @patch("payroll.views.ca_paycheck_review.get_object_or_404")
    def test_preview_then_record_requires_review_of_same_inputs(self, lookup, form_class, render, record):
        lookup.return_value = self.slip
        render.side_effect = lambda *args, **kwargs: HttpResponse()
        form = form_class.return_value
        form.is_valid.return_value = True
        form.cleaned_data = {"employer": Mock(pk=10), "verified_payment": True}
        form.calculate.return_value = self.calculation
        fields = {"pay_date": "2026-01-02", "employer": "10"}
        review_ca_paycheck(self.request({**fields, "action": "preview"}), 15)
        record.assert_not_called()
        token = render.call_args.args[2]["review_token"]

        review_ca_paycheck(self.request({**fields, "action": "record"}), 15)
        review_ca_paycheck(self.request({**fields, "employer": "11", "action": "record", "review_token": token}), 15)
        self.slip.employee_id_id = 13
        review_ca_paycheck(self.request({**fields, "action": "record", "review_token": token}), 15)
        self.slip.employee_id_id = 12
        record.assert_not_called()

        review_ca_paycheck(self.request({**fields, "action": "record", "review_token": token}), 15)
        record.assert_called_once_with(
            payslip_id=15, employer_id=10, calculation=self.calculation, recorded_by_id=2,
            expected_slip_state=paid_slip_review_state(self.slip),
        )
