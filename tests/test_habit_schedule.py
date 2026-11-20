from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.habit_schedule import period_progress, streaks
from app.models import Habit


def day(value):
    return date.fromisoformat(value)


def test_daily_grace_missed_day_and_leap_day():
    habit = Habit(frequency="daily", starts_on=day("2024-02-27"))
    qualified = [day("2024-02-28"), day("2024-02-29"), day("2024-03-01")]
    assert streaks(habit, qualified, day("2024-03-02")) == (3, 3)
    assert streaks(habit, qualified, day("2024-03-03")) == (0, 3)
    assert streaks(habit, [], day("2024-03-03")) == (0, 0)


def test_selected_weekdays_grace_and_missed_occurrences():
    habit = Habit(frequency="weekdays", weekday_mask=(1 << 0) | (1 << 4), starts_on=day("2025-01-01"))
    qualified = [day("2025-01-03"), day("2025-01-06")]
    assert streaks(habit, qualified, day("2025-01-09")) == (2, 2)
    assert streaks(habit, qualified, day("2025-01-10")) == (2, 2)
    assert streaks(habit, qualified, day("2025-01-11")) == (0, 2)
    assert period_progress(habit, qualified, day("2025-01-01"), day("2025-01-31"),
                           day("2025-01-11")).completion_percentage == 66.67


def test_weekly_year_boundary_partial_first_week_and_current_grace():
    habit = Habit(frequency="weekly", weekly_target=3, starts_on=day("2024-12-28"))
    qualified = [day(value) for value in (
        "2024-12-28", "2024-12-29", "2024-12-30", "2024-12-31", "2025-01-05", "2025-01-06"
    )]
    assert streaks(habit, qualified, day("2025-01-07")) == (2, 2)
    assert streaks(habit, qualified, day("2025-01-13")) == (0, 2)
    monthly = period_progress(habit, qualified, day("2025-01-01"), day("2025-01-31"), day("2025-01-07"))
    assert (monthly.completed, monthly.target) == (2, 6)


def test_dst_transition_preserves_local_calendar_streak():
    zone = ZoneInfo("America/New_York")
    instants = [datetime(2025, 3, 9, 4, 30, tzinfo=UTC), datetime(2025, 3, 10, 3, 30, tzinfo=UTC)]
    local_dates = [instant.astimezone(zone).date() for instant in instants]
    assert local_dates == [day("2025-03-08"), day("2025-03-09")]
    habit = Habit(frequency="daily", starts_on=local_dates[0])
    assert streaks(habit, local_dates, day("2025-03-10")) == (2, 2)
