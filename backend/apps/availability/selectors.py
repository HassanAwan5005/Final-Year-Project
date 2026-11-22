"""
Read-side availability computation — Module 7 support.

WHY AVAILABILITY IS DERIVED, NOT STORED
---------------------------------------
See `availability/models.py`: storing "free" days would mean roughly 73,000
rows a year for 200 photographers, almost all of them saying "yes". The rules
and the exceptions are stored; the answer is computed.

The computation costs a fixed **three queries for any window length** — the
weekly rules (at most 7 rows), the blackouts overlapping the window, and the
blocking bookings inside it. Everything after that is arithmetic in Python, so
a 90-day calendar costs the same as a single-day check.

DEFAULT IS AVAILABLE
--------------------
A photographer with no `AvailabilityRule` rows is treated as working every
day. The opposite default would make every newly-registered account invisible
to the calendar and unable to receive a first booking — a silent dead end. The
same choice is made in `profiles/filters.filter_available_on`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.availability.models import AvailabilityRule, BlackoutDate, TimeSlot
from apps.bookings.constants import package_days

#: How many days a calendar request may span. A buyer planning a wedding looks
#: months ahead; nobody needs three years, and an unbounded window is a cheap
#: way for a caller to make the server do pointless work.
DEFAULT_WINDOW_DAYS = 60
MAX_WINDOW_DAYS = 180

#: How far back to look for shoots still running on a given date.
_SPILLOVER = timedelta(days=7)

#: A part-day block such as 22:00-02:00 runs into the next date.
_OVERNIGHT = timedelta(days=1)


class UnavailableReason:
    """
    Machine-readable codes. The mobile app branches on these to decide whether
    to grey a date out, hide it, or show "fully booked — try another date", so
    they are part of the API contract.
    """

    PAST = "PAST"
    TOO_SOON = "TOO_SOON"
    WEEKLY_OFF = "WEEKLY_OFF"
    BLACKOUT = "BLACKOUT"
    FULLY_BOOKED = "FULLY_BOOKED"
    NOT_ACCEPTING = "NOT_ACCEPTING"
    SLOT_TAKEN = "SLOT_TAKEN"
    NOT_ENOUGH_HOURS = "NOT_ENOUGH_HOURS"


@dataclass(slots=True)
class DayAvailability:
    """One cell of the booking calendar."""

    date: date_cls
    is_available: bool
    reason: str = ""
    message: str = ""
    booked_times: list[str] = field(default_factory=list)
    remaining_slots: int = 0
    start_time: time | None = None
    end_time: time | None = None


# ═══════════════════════════════════════════════════════════════════════════
# WINDOW HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def earliest_bookable_date() -> date_cls:
    """
    The first date a buyer may request.

    `BOOKING_MIN_LEAD_HOURS` exists because a request for "in two hours" is
    almost never real, and a photographer who misses it looks unresponsive
    through no fault of their own.
    """
    # Starts are on the hour, so 23:30 rounds up into the next day.
    almost_an_hour = timedelta(hours=1) - timedelta(microseconds=1)
    return (earliest_bookable_start() + almost_an_hour).date()


def earliest_bookable_start() -> datetime:
    """
    The notice period, down to the minute.

    Naive Pakistan time, because that is what a booking's date and start time
    are. The server itself runs in UTC, five hours behind.
    """
    lead = timedelta(hours=settings.BOOKING_MIN_LEAD_HOURS)
    local = timezone.localtime(
        timezone.now() + lead, ZoneInfo(settings.DISPLAY_TIME_ZONE)
    )
    return local.replace(tzinfo=None)


def clamp_window(start: date_cls | None, days: int | None) -> tuple[date_cls, date_cls]:
    """Normalise a caller-supplied window to something sane and bounded."""
    start = start or timezone.localdate()
    span = days or DEFAULT_WINDOW_DAYS
    span = max(1, min(int(span), MAX_WINDOW_DAYS))
    return start, start + timedelta(days=span - 1)


# ═══════════════════════════════════════════════════════════════════════════
# THE CALENDAR
# ═══════════════════════════════════════════════════════════════════════════
def availability_calendar(
    photographer,
    start: date_cls | None = None,
    days: int | None = None,
    duration_hours: int | None = None,
) -> list[DayAvailability]:
    """
    Availability for every date in the window, in order.

    With `duration_hours`, a date is only available when it has that many free
    hours in a row — a 6-hour shoot cannot go on a date with 4 left. A 1 or 2 day
    package needs that many completely free dates, starting on the date itself.

    Three queries regardless of how long the window is.
    """
    start, end = clamp_window(start, days)
    # A 2-day package on the last date also needs the date after the window.
    last = end + timedelta(days=max(package_days(duration_hours) - 1, 0))

    rules = _rules_by_weekday(photographer)
    blackouts = _blackouts_in(photographer, start - _OVERNIGHT, last)
    bookings = _blocking_bookings_in(photographer, start - _SPILLOVER, last)
    spans = _spans(bookings) + _part_day_spans(blackouts)
    floor = earliest_bookable_date()
    earliest = earliest_bookable_start()
    accepting = bool(getattr(photographer, "is_accepting_bookings", True))

    calendar = []
    cursor = start
    while cursor <= end:
        calendar.append(
            _day_status(
                cursor,
                rules=rules,
                blackouts=blackouts,
                booked=bookings.get(cursor, []),
                spans=spans,
                floor=floor,
                earliest=earliest,
                duration_hours=duration_hours,
                accepting=accepting,
            )
        )
        cursor += timedelta(days=1)
    return calendar


def day_availability(
    photographer, date: date_cls, duration_hours: int | None = None
) -> DayAvailability:
    """Single-date check — the same logic, scoped to one day."""
    return availability_calendar(
        photographer, start=date, days=1, duration_hours=duration_hours
    )[0]


def suggested_start_times(
    photographer, date: date_cls, duration_hours: int = 4
) -> list[str]:
    """
    Start times that can still be booked on a date.

    Every hour of the day (00:00-23:00) is open except those where the shoot
    would overlap an existing booking or a part-day block, would not finish by
    midnight, or that fall inside the notice period. The booking form shows all
    24 hours and disables the ones missing from this list. Returns [] when the
    date is not bookable at all. A 1 or 2 day package always starts at 00:00.
    """
    if not day_availability(photographer, date, duration_hours).is_available:
        return []
    if package_days(duration_hours):
        return ["00:00"]

    candidates = _explicit_slots(photographer, date)
    if candidates is None:
        candidates = [time(hour, 0) for hour in range(24)]

    spans = booked_spans_on(photographer, date) + blocked_spans_on(photographer, date)
    earliest = earliest_bookable_start()
    return [
        start.strftime("%H:%M")
        for start in candidates
        if datetime.combine(date, start) >= earliest
        and finishes_same_day(start, duration_hours)
        and find_clash(spans, date, start, duration_hours) is None
    ]


def booked_spans_on(
    photographer, date: date_cls
) -> list[tuple[datetime, datetime]]:
    """
    (start, end) of every booking that could occupy hours of `date`, including
    an earlier one that ran past midnight into it.
    """
    return _spans(_blocking_bookings_in(photographer, date - _SPILLOVER, date))


def blocked_spans_on(
    photographer, date: date_cls
) -> list[tuple[datetime, datetime]]:
    """(start, end) of every part-day block that could cover hours of `date`."""
    return _part_day_spans(_blackouts_in(photographer, date - _OVERNIGHT, date))


def finishes_same_day(start_time: time, duration_hours: int) -> bool:
    """A shoot measured in hours must be over by midnight."""
    minutes = start_time.hour * 60 + start_time.minute + max(duration_hours, 1) * 60
    return minutes <= 24 * 60


def fully_booked_photographer_ids(date: date_cls) -> set[int]:
    """Photographers with no free hour left on `date` — for discovery search."""
    from apps.bookings.constants import BLOCKING_STATUSES
    from apps.bookings.models import Booking

    spans: dict[int, list[tuple[datetime, datetime]]] = {}

    for photographer_id, event_date, start_time, duration in Booking.objects.filter(
        event_date__gte=date - _SPILLOVER,
        event_date__lte=date,
        status__in=BLOCKING_STATUSES,
    ).values_list("photographer_id", "event_date", "start_time", "duration_hours"):
        spans.setdefault(photographer_id, []).extend(
            _spans({event_date: [(start_time, int(duration or 4))]})
        )

    for blackout in BlackoutDate.objects.filter(
        start_date__lte=date, end_date__gte=date - _OVERNIGHT, is_full_day=False
    ):
        spans.setdefault(blackout.photographer_id, []).extend(
            _part_day_spans([blackout])
        )

    return {pk for pk, taken in spans.items() if not _open_hours(taken, date)}


def find_clash(
    spans: list[tuple[datetime, datetime]],
    date: date_cls,
    start_time: time,
    duration_hours: int,
) -> tuple[datetime, datetime] | None:
    """The first booked span a shoot would overlap, or None when it is free."""
    start = datetime.combine(date, start_time)
    end = start + timedelta(hours=max(duration_hours, 1))
    for span in spans:
        if start < span[1] and end > span[0]:
            return span
    return None


def booked_times_on(photographer, date: date_cls) -> list[str]:
    """Start times already occupied by a PENDING or ACCEPTED booking."""
    rows = _blocking_bookings_in(photographer, date, date).get(date, [])
    return [b[0].strftime("%H:%M") for b in rows]


# ═══════════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════════
def _rules_by_weekday(photographer) -> dict[int, AvailabilityRule]:
    return {
        rule.weekday: rule
        for rule in AvailabilityRule.objects.filter(photographer=photographer)
    }


def _blackouts_in(photographer, start: date_cls, end: date_cls) -> list[BlackoutDate]:
    """Ranges that *overlap* the window — not ranges contained by it."""
    return list(
        BlackoutDate.objects.filter(
            photographer=photographer, start_date__lte=end, end_date__gte=start
        )
    )


def _blocking_bookings_in(
    photographer, start: date_cls, end: date_cls
) -> dict[date_cls, list[tuple[time, int]]]:
    """{event_date: [(start_time, duration_hours), ...]} for bookings that occupy a slot."""
    from apps.bookings.constants import BLOCKING_STATUSES
    from apps.bookings.models import Booking

    rows = Booking.objects.filter(
        photographer=photographer,
        event_date__gte=start,
        event_date__lte=end,
        status__in=BLOCKING_STATUSES,
    ).values_list("event_date", "start_time", "duration_hours")

    grouped: dict[date_cls, list[tuple[time, int]]] = {}
    for event_date, start_time, duration in rows:
        grouped.setdefault(event_date, []).append((start_time, int(duration or 4)))
    return grouped


def _spans(
    bookings: dict[date_cls, list[tuple[time, int]]],
) -> list[tuple[datetime, datetime]]:
    """Flatten grouped bookings into real (start, end) datetimes."""
    spans = []
    for event_date, rows in bookings.items():
        for start_time, duration in rows:
            start = datetime.combine(event_date, start_time)
            spans.append((start, start + timedelta(hours=max(duration, 1))))
    return spans


def _part_day_spans(
    blackouts: list[BlackoutDate],
) -> list[tuple[datetime, datetime]]:
    """One (start, end) per date for every block that covers only some hours."""
    spans = []
    for blackout in blackouts:
        if blackout.is_full_day or not blackout.start_time or not blackout.end_time:
            continue
        cursor = blackout.start_date
        while cursor <= blackout.end_date:
            start = datetime.combine(cursor, blackout.start_time)
            end = datetime.combine(cursor, blackout.end_time)
            if end <= start:  # 22:00-02:00
                end += _OVERNIGHT
            spans.append((start, end))
            cursor += timedelta(days=1)
    return spans


def _open_hours(
    spans: list[tuple[datetime, datetime]],
    date: date_cls,
    earliest: datetime | None = None,
) -> list[int]:
    """Which of the date's 24 hours are still open."""
    return [
        hour
        for hour in range(24)
        if (earliest is None or datetime.combine(date, time(hour, 0)) >= earliest)
        and find_clash(spans, date, time(hour, 0), 1) is None
    ]


def _whole_date_free(
    date: date_cls,
    rules: dict[int, AvailabilityRule],
    blackouts: list[BlackoutDate],
    spans: list[tuple[datetime, datetime]],
) -> bool:
    """Nothing at all on the date: no day off, no block, no booking."""
    rule = rules.get(date.weekday())
    if rule and not rule.is_available:
        return False
    if any(b.is_full_day and b.covers(date) for b in blackouts):
        return False
    return find_clash(spans, date, time(0, 0), 24) is None


def _longest_run(hours: list[int]) -> int:
    """Length of the longest unbroken stretch: [1, 2, 3, 9, 10] -> 3."""
    best = run = 0
    previous = None
    for hour in hours:
        run = run + 1 if previous is not None and hour == previous + 1 else 1
        best = max(best, run)
        previous = hour
    return best


def _explicit_slots(photographer, date: date_cls) -> list[time] | None:
    """
    Free start times from explicit TimeSlot rows, or None when the photographer
    has not defined any for this date.

    Most photographers sell whole days and never create these; when they do
    exist they are authoritative and the derived hourly grid is not used.
    """
    slots = list(
        TimeSlot.objects.filter(photographer=photographer, date=date).order_by(
            "start_time"
        )
    )
    if not slots:
        return None
    return [s.start_time for s in slots if not s.is_booked]


def _day_status(
    date: date_cls,
    *,
    rules: dict[int, AvailabilityRule],
    blackouts: list[BlackoutDate],
    booked: list[tuple[time, int]],
    spans: list[tuple[datetime, datetime]],
    floor: date_cls,
    earliest: datetime,
    accepting: bool,
    duration_hours: int | None,
) -> DayAvailability:
    """
    Decide one day.

    Order matters: the most absolute reasons are checked first so the message a
    buyer sees is the most useful one. "That date has passed" beats "fully
    booked" for a date in 2024.
    """
    rule = rules.get(date.weekday())
    hours = (rule.start_time, rule.end_time) if rule else (time(9, 0), time(18, 0))
    # A booking closes its own hours, not the whole date.
    open_hours = _open_hours(spans, date, earliest)
    remaining = len(open_hours)
    booked_start_times = [b[0].strftime("%H:%M") for b in booked]

    def unavailable(reason: str, message: str) -> DayAvailability:
        return DayAvailability(
            date=date,
            is_available=False,
            reason=reason,
            message=message,
            booked_times=sorted(booked_start_times),
            remaining_slots=0,
            start_time=hours[0],
            end_time=hours[1],
        )

    if date < timezone.localdate():
        return unavailable(UnavailableReason.PAST, "That date has already passed.")
    if not accepting:
        return unavailable(
            UnavailableReason.NOT_ACCEPTING,
            "This photographer is not accepting bookings at the moment.",
        )
    days = package_days(duration_hours)
    if date < floor or (days and datetime.combine(date, time(0, 0)) < earliest):
        return unavailable(
            UnavailableReason.TOO_SOON,
            f"Bookings need at least {settings.BOOKING_MIN_LEAD_HOURS} hours' notice.",
        )
    if rule and not rule.is_available:
        return unavailable(
            UnavailableReason.WEEKLY_OFF,
            f"This photographer does not work on {date:%A}s.",
        )
    for blackout in blackouts:
        if blackout.covers(date) and blackout.is_full_day:
            return unavailable(
                UnavailableReason.BLACKOUT,
                blackout.reason or "The photographer is unavailable on this date.",
            )
    if remaining <= 0:
        return unavailable(UnavailableReason.FULLY_BOOKED, "Fully booked on this date.")
    for offset in range(days):
        needed = date + timedelta(days=offset)
        if not _whole_date_free(needed, rules, blackouts, spans):
            return unavailable(
                UnavailableReason.NOT_ENOUGH_HOURS,
                f"A {days}-day package needs the whole day free, but {needed:%d %b} "
                f"is not completely free.",
            )
    longest = _longest_run(open_hours)
    if duration_hours and not days and longest < duration_hours:
        unit = "hour" if longest == 1 else "hours in a row"
        return unavailable(
            UnavailableReason.NOT_ENOUGH_HOURS,
            f"Only {longest} {unit} left on this date, which is not enough for this "
            f"{duration_hours}-hour shoot.",
        )

    return DayAvailability(
        date=date,
        is_available=True,
        booked_times=sorted(booked_start_times),
        remaining_slots=remaining,
        start_time=hours[0],
        end_time=hours[1],
    )
