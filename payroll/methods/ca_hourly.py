"""California standard nonexempt hourly wages for a single effective rate.

Rules: https://www.dir.ca.gov/dlse/FAQ_Overtime.htm
Overtime overlap: https://www.dir.ca.gov/dlse/ab60update.htm
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


MINUTES_PER_HOUR = 60
DAILY_REGULAR_LIMIT = 8 * MINUTES_PER_HOUR
DAILY_OVERTIME_LIMIT = 12 * MINUTES_PER_HOUR
WEEKLY_REGULAR_LIMIT = 40 * MINUTES_PER_HOUR
OVERTIME_MULTIPLIER = Decimal("1.5")


@dataclass(frozen=True)
class HourlyDay:
    work_date: date
    regular_minutes: int
    daily_overtime_minutes: int
    weekly_overtime_minutes: int
    seventh_day_overtime_minutes: int
    double_time_minutes: int
    regular_rate: Decimal

    @property
    def overtime_minutes(self) -> int:
        return (
            self.daily_overtime_minutes
            + self.weekly_overtime_minutes
            + self.seventh_day_overtime_minutes
        )


@dataclass(frozen=True)
class HourlyPay:
    regular_pay: Decimal
    overtime_pay: Decimal
    double_time_pay: Decimal
    paid_non_work_pay: Decimal
    gross_pay: Decimal


def _validate_minutes(minutes: int) -> None:
    if type(minutes) is not int or minutes < 0:
        raise ValueError("Minutes must be a nonnegative integer.")


def _validate_rate(rate: Decimal) -> None:
    if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
        raise ValueError("Hourly rate must be a positive, finite Decimal.")


def calculate_workweek(
    week_start: date,
    worked_minutes_by_date: Mapping[date, int],
    regular_rate: Decimal,
) -> tuple[HourlyDay, ...]:
    """Classify minutes for all seven workdays in the employer's workweek.

    The caller must supply all worked time, grouped by the employer's local
    workday boundaries. Omitted dates mean zero work. Pass only actual worked
    minutes here and classify the whole week before selecting pay-period dates.
    The rate is the single rate for both straight time and overtime. The caller
    determines eligibility for standard rules and handles bonuses, multiple
    rates within a week, and exceptions such as alternative workweeks.
    """
    if type(week_start) is not date:
        raise ValueError("Workweek start must be a local work date.")
    _validate_rate(regular_rate)

    work_dates = tuple(week_start + timedelta(days=offset) for offset in range(7))
    for work_date, minutes in worked_minutes_by_date.items():
        if type(work_date) is not date or work_date not in work_dates:
            raise ValueError("Worked minutes must belong to the specified workweek.")
        _validate_minutes(minutes)

    worked_all_week = all(worked_minutes_by_date.get(day, 0) for day in work_dates)
    remaining_regular = WEEKLY_REGULAR_LIMIT
    days = []
    for work_date in work_dates:
        minutes = worked_minutes_by_date.get(work_date, 0)
        first_eight = min(minutes, DAILY_REGULAR_LIMIT)
        if work_date == work_dates[-1] and worked_all_week:
            days.append(
                HourlyDay(
                    work_date=work_date,
                    regular_minutes=0,
                    daily_overtime_minutes=0,
                    weekly_overtime_minutes=0,
                    seventh_day_overtime_minutes=first_eight,
                    double_time_minutes=minutes - first_eight,
                    regular_rate=regular_rate,
                )
            )
            continue

        # Only minutes that are eligible for straight time count toward 40 hours.
        regular = min(first_eight, remaining_regular)
        remaining_regular -= regular
        days.append(
            HourlyDay(
                work_date=work_date,
                regular_minutes=regular,
                daily_overtime_minutes=min(minutes, DAILY_OVERTIME_LIMIT) - first_eight,
                weekly_overtime_minutes=first_eight - regular,
                seventh_day_overtime_minutes=0,
                double_time_minutes=max(minutes - DAILY_OVERTIME_LIMIT, 0),
                regular_rate=regular_rate,
            )
        )

    return tuple(days)


def calculate_hourly_pay(
    days: Iterable[HourlyDay],
    *,
    paid_non_work_minutes: int = 0,
    paid_non_work_rate: Decimal | None = None,
) -> HourlyPay:
    """Price classified pay-period days and optional separately rated leave.

    Amounts retain sub-cent precision for the caller's pay-period rounding.
    """
    _validate_minutes(paid_non_work_minutes)
    paid_non_work = Decimal(0)
    if paid_non_work_rate is not None:
        _validate_rate(paid_non_work_rate)
        paid_non_work = paid_non_work_minutes * paid_non_work_rate
    elif paid_non_work_minutes:
        raise ValueError("Paid non-work minutes require an explicit hourly rate.")

    regular = overtime = double_time = Decimal(0)
    for day in days:
        regular += day.regular_minutes * day.regular_rate
        overtime += day.overtime_minutes * day.regular_rate * OVERTIME_MULTIPLIER
        double_time += day.double_time_minutes * day.regular_rate * 2

    return HourlyPay(
        regular_pay=regular / MINUTES_PER_HOUR,
        overtime_pay=overtime / MINUTES_PER_HOUR,
        double_time_pay=double_time / MINUTES_PER_HOUR,
        paid_non_work_pay=paid_non_work / MINUTES_PER_HOUR,
        gross_pay=(regular + overtime + double_time + paid_non_work) / MINUTES_PER_HOUR,
    )
