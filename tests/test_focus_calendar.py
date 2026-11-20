from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app.focus_calendar import day_windows


def test_spring_gap_and_autumn_fold_have_correct_day_lengths():
    zone = ZoneInfo("America/New_York")
    for local_day, hours in ((date(2025, 3, 9), 23), (date(2025, 11, 2), 25)):
        assert sum((end - start for _, start, end in day_windows(local_day, local_day, zone)),
                   timedelta()) == timedelta(hours=hours)


def test_skipped_date_has_no_utc_window():
    zone = ZoneInfo("Pacific/Apia")
    skipped = date(2011, 12, 30)
    assert day_windows(skipped, skipped, zone) == []
