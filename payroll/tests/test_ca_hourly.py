from datetime import date, timedelta
from decimal import Decimal
from unittest import TestCase

from payroll.methods.ca_hourly import calculate_hourly_pay, calculate_workweek


WEEK_START = date(2026, 11, 1)
RATE = Decimal("20.00")


def workweek(*minutes, rate=RATE):
    return calculate_workweek(
        WEEK_START,
        {
            WEEK_START + timedelta(days=index): value
            for index, value in enumerate(minutes)
        },
        rate,
    )


class CaliforniaHourlyTests(TestCase):
    def test_daily_overtime_and_double_time_begin_after_8_and_12_hours(self):
        eight, twelve, over_twelve, *_ = workweek(480, 720, 721)

        self.assertEqual(eight.regular_minutes, 480)
        self.assertEqual(eight.overtime_minutes, 0)
        self.assertEqual(twelve.daily_overtime_minutes, 240)
        self.assertEqual(twelve.double_time_minutes, 0)
        self.assertEqual(over_twelve.regular_minutes, 480)
        self.assertEqual(over_twelve.daily_overtime_minutes, 240)
        self.assertEqual(over_twelve.double_time_minutes, 1)

    def test_daily_premiums_do_not_count_toward_weekly_overtime(self):
        days = workweek(720, 720, 720, 720)

        self.assertEqual(sum(day.regular_minutes for day in days), 1920)
        self.assertEqual(sum(day.daily_overtime_minutes for day in days), 960)
        self.assertEqual(sum(day.weekly_overtime_minutes for day in days), 0)

    def test_weekly_overtime_only_reclassifies_remaining_straight_time(self):
        days = workweek(780, 480, 480, 480, 450, 721)
        sixth = days[5]

        self.assertEqual(sixth.regular_minutes, 30)
        self.assertEqual(sixth.weekly_overtime_minutes, 450)
        self.assertEqual(sixth.daily_overtime_minutes, 240)
        self.assertEqual(sixth.double_time_minutes, 1)
        self.assertEqual(sum(day.regular_minutes for day in days), 2400)

    def test_seventh_consecutive_workday_receives_premiums_even_below_40_hours(self):
        seventh = workweek(60, 60, 60, 60, 60, 60, 541)[-1]

        self.assertEqual(seventh.work_date, date(2026, 11, 7))
        self.assertEqual(seventh.regular_minutes, 0)
        self.assertEqual(seventh.seventh_day_overtime_minutes, 480)
        self.assertEqual(seventh.double_time_minutes, 61)

    def test_seventh_day_overtime_does_not_stack_with_weekly_overtime(self):
        seventh = workweek(480, 480, 480, 480, 480, 480, 541)[-1]

        self.assertEqual(seventh.overtime_minutes, 480)
        self.assertEqual(seventh.weekly_overtime_minutes, 0)
        self.assertEqual(seventh.double_time_minutes, 61)

    def test_a_day_without_work_breaks_the_seventh_day_streak(self):
        seventh = workweek(60, 60, 60, 0, 60, 60, 541)[-1]

        self.assertEqual(seventh.regular_minutes, 480)
        self.assertEqual(seventh.daily_overtime_minutes, 61)
        self.assertEqual(seventh.seventh_day_overtime_minutes, 0)
        self.assertEqual(seventh.double_time_minutes, 0)

    def test_paid_non_work_time_is_paid_separately_from_40_worked_hours(self):
        days = workweek(480, 480, 480, 480, 0, 480)
        pay = calculate_hourly_pay(
            days, paid_non_work_minutes=480, paid_non_work_rate=Decimal("18.50")
        )

        self.assertEqual(pay.regular_pay, Decimal("800.00"))
        self.assertEqual(pay.overtime_pay, Decimal("0.00"))
        self.assertEqual(pay.paid_non_work_pay, Decimal("148.00"))
        self.assertEqual(pay.gross_pay, Decimal("948.00"))

    def test_pay_period_slice_keeps_overtime_classified_from_the_whole_week(self):
        days = workweek(480, 480, 480, 480, 480, 750)
        pay = calculate_hourly_pay(days[5:])

        self.assertEqual(pay.regular_pay, Decimal("0.00"))
        self.assertEqual(pay.overtime_pay, Decimal("360.00"))
        self.assertEqual(pay.double_time_pay, Decimal("20.00"))
        self.assertEqual(pay.gross_pay, Decimal("380.00"))

    def test_worked_minutes_are_aggregated_before_converting_to_hourly_pay(self):
        pay = calculate_hourly_pay(workweek(1, 1, 1, rate=Decimal("15.10")))

        self.assertEqual(pay.regular_pay, Decimal("0.755"))
        self.assertEqual(pay.gross_pay, Decimal("0.755"))

    def test_dates_outside_the_workweek_are_rejected(self):
        with self.assertRaises(ValueError):
            calculate_workweek(WEEK_START, {WEEK_START - timedelta(days=1): 1}, RATE)

    def test_non_integer_or_negative_minutes_are_rejected(self):
        for minutes in (-1, Decimal("1.5"), True):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                workweek(minutes)

    def test_rate_must_be_a_positive_finite_decimal(self):
        for rate in (20.0, Decimal("0"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                workweek(480, rate=rate)

    def test_paid_non_work_time_requires_an_explicit_rate(self):
        with self.assertRaises(ValueError):
            calculate_hourly_pay(workweek(), paid_non_work_minutes=60)
