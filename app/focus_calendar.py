from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.errors import APIError

MICROSECOND = timedelta(microseconds=1)
DAY = timedelta(days=1)


def microseconds(value: timedelta) -> int:
    return value // MICROSECOND


def validate_dates(start: date | None, end: date | None) -> None:
    if ((start is not None and not 2 <= start.year <= 9998)
            or (end is not None and not 2 <= end.year <= 9998)
            or (start is not None and end is not None and start > end)):
        raise APIError(422, "invalid_input", "Provide an ordered date range between years 2 and 9998.")


def utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def day_windows(start: date, end: date, zone: ZoneInfo):
    """Map UTC instants to local dates, including folds or gaps around midnight."""
    first = utc_midnight(start)
    last = utc_midnight(end + DAY)
    left, stop = first - DAY, last + DAY
    windows = []
    step = timedelta(hours=12)
    while left < stop:
        offset = left.astimezone(zone).utcoffset()
        right = min(left + step, stop)
        if right.astimezone(zone).utcoffset() != offset:
            low, high = left, right
            while high - low > MICROSECOND:
                mid = low + ((high - low) // 2)
                if mid.astimezone(zone).utcoffset() == offset:
                    low = mid
                else:
                    high = mid
            right = high

        cursor = max(left, first - offset)
        limit = min(right, last - offset)
        while cursor < limit:
            local_day = (cursor + offset).date()
            boundary = min(limit, utc_midnight(local_day + DAY) - offset)
            if windows and windows[-1][0] == local_day and windows[-1][2] == cursor:
                windows[-1] = (local_day, windows[-1][1], boundary)
            else:
                windows.append((local_day, cursor, boundary))
            cursor = boundary
        left = right
    return windows
