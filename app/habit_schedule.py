from calendar import monthrange
from collections import Counter
from datetime import date

from app.habit_schemas import Progress
from app.models import Habit


def monday(ordinal: int) -> int:
    return ordinal - (ordinal - 1) % 7


def is_scheduled(habit: Habit, day: date) -> bool:
    return day >= habit.starts_on and (
        habit.frequency != "weekdays" or bool(habit.weekday_mask & (1 << day.weekday()))
    )


def month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def weekday_slots(mask: int, through: int) -> int:
    weeks, days = divmod(through, 7)
    return weeks * mask.bit_count() + (mask & ((1 << days) - 1)).bit_count()


def weekly_quota(habit: Habit, week: int, start: int, end: int) -> int:
    return min(habit.weekly_target, min(end, week + 6) - max(week, start) + 1)


def progress(completed: int, target: int) -> Progress:
    return Progress(
        completed=completed, target=target,
        completion_percentage=round(100 * completed / target, 2) if target else 0,
    )


def period_progress(
    habit: Habit, qualified: list[date], start: date, period_end: date, today: date
) -> Progress:
    first = max(start, habit.starts_on).toordinal()
    cutoff = min(period_end, today).toordinal()
    if first > cutoff:
        return progress(0, 0)
    days = [day.toordinal() for day in qualified
            if first <= day.toordinal() <= cutoff and is_scheduled(habit, day)]
    if habit.frequency == "daily":
        return progress(len(days), cutoff - first + 1)
    if habit.frequency == "weekdays":
        target = weekday_slots(habit.weekday_mask, cutoff) - weekday_slots(habit.weekday_mask, first - 1)
        return progress(len(days), target)

    first_week, last_week = monday(first), monday(cutoff)
    end = min(period_end.toordinal(), last_week + 6)
    target = weekly_quota(habit, first_week, first, end)
    if first_week != last_week:
        target += weekly_quota(habit, last_week, first, end)
        target += ((last_week - first_week) // 7 - 1) * habit.weekly_target
    weeks = Counter(monday(day) for day in days)
    return progress(sum(min(count, weekly_quota(habit, week, first, end))
                        for week, count in weeks.items()), target)


def streaks(habit: Habit, qualified: list[date], today: date) -> tuple[int, int]:
    days = [day.toordinal() for day in qualified if day <= today and is_scheduled(habit, day)]
    as_of = today.toordinal()
    if habit.frequency == "weekly":
        weeks = Counter(monday(day) for day in days)
        first = habit.starts_on.toordinal()
        units = [week // 7 for week, count in sorted(weeks.items())
                 if count >= weekly_quota(habit, week, first, date.max.toordinal())]
        expected, grace = monday(as_of) // 7, True
    elif habit.frequency == "weekdays":
        units = [weekday_slots(habit.weekday_mask, day) for day in days]
        expected = weekday_slots(habit.weekday_mask, as_of)
        grace = is_scheduled(habit, today)
    else:
        units = days
        expected, grace = as_of, True

    longest = run = 0
    previous = None
    for unit in units:
        run = run + 1 if previous is not None and unit == previous + 1 else 1
        longest = max(longest, run)
        previous = unit
    current = run if previous == expected or (grace and previous == expected - 1) else 0
    return current, longest


def daily_status(habit: Habit, counts: dict[date, int], day: date) -> tuple[int, bool, bool]:
    """Return the count, whether the habit is due, and whether it met its daily target."""
    count = counts.get(day, 0)
    eligible = is_scheduled(habit, day)
    due = eligible
    if eligible and habit.frequency == "weekly":
        start = monday(day.toordinal())
        end = min(start + 6, date.max.toordinal())
        first = max(start, habit.starts_on.toordinal())
        quota = weekly_quota(habit, start, first, end)
        met = sum(
            first <= logged_on.toordinal() < day.toordinal() and value >= habit.target_count
            for logged_on, value in counts.items()
        )
        due = met < quota
    return count, due, eligible and count >= habit.target_count
