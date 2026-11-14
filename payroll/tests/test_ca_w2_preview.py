from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from report.views.ca_annual_worksheet import W2PreviewForm, _compare_employee_de9c


class CaliforniaW2PreviewTests(SimpleTestCase):
    def test_employee_de9c_catches_errors_that_cancel_in_the_quarter_total(self):
        checks = [
            SimpleNamespace(employee_id=pk, paid_on=date(2026, 3, 5), facts={
                "ca_pit_wages": "100.00", "ca_pit_withheld": "5.00",
            })
            for pk in (1, 2)
        ]
        filing = SimpleNamespace(pk=10, period_start=date(2026, 1, 1), employee_rows={
            "1": {"pit_wages": "99.00", "pit_withheld": "5.00"},
            "2": {"pit_wages": "101.00", "pit_withheld": "5.00"},
        })
        entries = MagicMock()
        entries.order_by.return_value = [filing]
        with patch("report.views.ca_annual_worksheet.CaliforniaFiledDe9c.objects.filter", return_value=entries):
            status, versions = _compare_employee_de9c(checks, SimpleNamespace(year=2026, reviewed_at=None))
        self.assertEqual(status[1], "Differences found")
        self.assertEqual(status[2], "Filed rows needed")
        self.assertEqual(versions, [10])

    def form(self, entries, **overrides):
        return W2PreviewForm(
            {"source": "current", "verified": "on", "entries": entries, **overrides},
            source="current", employee_ids={42},
        )

    def test_distinguishes_confirmed_absence_from_an_omitted_entry(self):
        form = self.form("42,TP,0\n42,12,none")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["entries"][42], {
            "box_12_tp": Decimal("0.00"), "box_12_other": {}, "box_14b": (),
        })

    def test_requires_verified_tips_and_occupation_codes_together(self):
        self.assertFalse(self.form("42,TP,100.00").is_valid())
        self.assertFalse(self.form("42,TP,100.00\n42,14b,999").is_valid())
        form = self.form("42,TP,100.00\n42,14b,000 102")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["entries"][42]["box_14b"], ("000", "102"))

    def test_rejects_stale_unverified_and_unscoped_entries(self):
        self.assertFalse(self.form("42,TT,100.00", source="stale").is_valid())
        self.assertFalse(self.form("42,TT,100.00", verified="").is_valid())
        self.assertFalse(self.form("43,TT,100.00").is_valid())
        self.assertFalse(self.form("42,TT,100.00\n42,TT,200.00").is_valid())
