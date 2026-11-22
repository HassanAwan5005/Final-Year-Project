"""
Availability computation.

The rule these tests pin down: a date is bookable unless something explicitly
says otherwise, and the *reason* it is not bookable is the most useful one
available — a buyer looking at a greyed-out date needs to know whether to try
a different time or a different photographer.
"""

from datetime import date as date_cls
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.availability import selectors
from apps.availability.models import AvailabilityRule, BlackoutDate, TimeSlot
from apps.availability.selectors import UnavailableReason
from conftest import working_date

pytestmark = pytest.mark.django_db


def _set_length(service, hours: int) -> None:
    """Make the photographer's service a shoot of this many hours."""
    service.duration_hours = hours
    service.save(update_fields=["duration_hours"])


def _overnight_booking(make_booking, date):
    """A 22:00-02:00 booking, as older data can contain."""
    from apps.bookings.models import Booking

    booking = make_booking(event_date=date, start_time=time(14, 0))
    Booking.objects.filter(pk=booking.pk).update(
        start_time=time(22, 0), duration_hours=4
    )


# ═══════════════════════════════════════════════════════════════════════════
# THE WINDOW
# ═══════════════════════════════════════════════════════════════════════════
def test_calendar_defaults_to_the_standard_window(photographer):
    calendar = selectors.availability_calendar(photographer)
    assert len(calendar) == selectors.DEFAULT_WINDOW_DAYS
    assert calendar[0].date == timezone.localdate()


def test_calendar_window_is_capped(photographer):
    """An unbounded window is a cheap way to make the server do pointless work."""
    calendar = selectors.availability_calendar(photographer, days=10_000)
    assert len(calendar) == selectors.MAX_WINDOW_DAYS


def test_calendar_costs_the_same_for_any_window(photographer, django_assert_num_queries):
    """Three queries — rules, blackouts, bookings — regardless of length."""
    with django_assert_num_queries(3):
        selectors.availability_calendar(photographer, days=180)


# ═══════════════════════════════════════════════════════════════════════════
# REASONS, IN PRIORITY ORDER
# ═══════════════════════════════════════════════════════════════════════════
def test_past_dates_say_so(photographer):
    yesterday = timezone.localdate() - timedelta(days=1)
    day = selectors.day_availability(photographer, yesterday)

    assert day.is_available is False
    assert day.reason == UnavailableReason.PAST


def test_today_is_inside_the_minimum_lead_time(photographer):
    day = selectors.day_availability(photographer, timezone.localdate())

    assert day.is_available is False
    assert day.reason == UnavailableReason.TOO_SOON


def test_a_paused_photographer_beats_every_other_reason(photographer):
    photographer.is_accepting_bookings = False
    photographer.save(update_fields=["is_accepting_bookings"])

    day = selectors.day_availability(photographer, working_date(10))
    assert day.reason == UnavailableReason.NOT_ACCEPTING


def test_no_weekday_is_off_by_default(photographer):
    """Functions are often on a Sunday, so it is open like any other day."""
    week = [working_date(days) for days in range(7, 14)]

    assert {date.weekday() for date in week} == set(range(7))
    assert all(selectors.day_availability(photographer, d).is_available for d in week)


def test_the_weekly_rule_marks_days_off(photographer):
    """A weekday the photographer has turned off themselves."""
    date = working_date(7)
    AvailabilityRule.objects.filter(
        photographer=photographer, weekday=date.weekday()
    ).update(is_available=False)

    day = selectors.day_availability(photographer, date)
    assert day.reason == UnavailableReason.WEEKLY_OFF
    assert f"{date:%A}" in day.message


def test_a_blackout_beats_the_weekly_rule(photographer):
    date = working_date(10)
    BlackoutDate.objects.create(
        photographer=photographer,
        start_date=date,
        end_date=date + timedelta(days=3),
        reason="Shooting abroad",
    )

    day = selectors.day_availability(photographer, date + timedelta(days=2))
    assert day.reason == UnavailableReason.BLACKOUT
    assert day.message == "Shooting abroad"


def test_a_partial_day_blackout_does_not_close_the_date(photographer):
    """Half-day blackouts narrow the day; they do not remove it."""
    date = working_date(10)
    BlackoutDate.objects.create(
        photographer=photographer,
        start_date=date,
        end_date=date,
        is_full_day=False,
        start_time=time(9, 0),
        end_time=time(12, 0),
    )

    assert selectors.day_availability(photographer, date).is_available is True


def test_a_booking_closes_only_its_own_hours(photographer, booking):
    """14:00-22:00 is taken; the other 16 hours stay open."""
    day = selectors.day_availability(photographer, booking.event_date)

    assert day.is_available is True
    assert day.booked_times == ["14:00"]
    assert day.remaining_slots == 16


def test_a_day_with_no_free_hour_is_fully_booked(photographer, service, make_booking):
    date = working_date(12)
    _set_length(service, 24)
    make_booking(event_date=date, start_time=time(0, 0))

    day = selectors.day_availability(photographer, date)
    assert day.is_available is False
    assert day.reason == UnavailableReason.FULLY_BOOKED


def test_a_photographer_with_no_rules_is_available(photographer):
    """
    The default must be 'available'. The opposite would make every newly
    registered account invisible and unable to take a first booking.
    """
    AvailabilityRule.objects.filter(photographer=photographer).delete()
    day = selectors.day_availability(photographer, working_date(10))

    assert day.is_available is True
    assert day.start_time == time(9, 0)


# ═══════════════════════════════════════════════════════════════════════════
# START TIMES
# ═══════════════════════════════════════════════════════════════════════════
def test_every_start_that_finishes_by_midnight_is_offered(photographer):
    times = selectors.suggested_start_times(photographer, working_date(10), 4)

    assert times == [f"{hour:02d}:00" for hour in range(21)]


def test_a_longer_shoot_offers_fewer_starts(photographer, booking):
    short = selectors.suggested_start_times(photographer, booking.event_date, 2)
    long = selectors.suggested_start_times(photographer, booking.event_date, 8)

    assert len(short) > len(long)


def test_taken_times_are_removed(photographer, booking):
    """Booked 14:00-22:00, so a 2-hour shoot must end by 14:00 or run 22:00-24:00."""
    times = selectors.suggested_start_times(photographer, booking.event_date, 2)

    assert times == [f"{hour:02d}:00" for hour in [*range(0, 13), 22]]


def test_a_shoot_past_midnight_blocks_the_next_morning(photographer, make_booking):
    date = working_date(12)
    _overnight_booking(make_booking, date)

    times = selectors.suggested_start_times(photographer, date + timedelta(days=1), 1)
    assert times == [f"{hour:02d}:00" for hour in range(2, 24)]


@pytest.mark.parametrize("hours, last", [(3, "21:00"), (6, "18:00"), (10, "14:00")])
def test_the_last_start_depends_on_the_shoot_length(photographer, hours, last):
    times = selectors.suggested_start_times(photographer, working_date(10), hours)
    assert times[-1] == last


# ═══════════════════════════════════════════════════════════════════════════
# DOES THE SHOOT FIT THE DAY
# ═══════════════════════════════════════════════════════════════════════════
def test_a_6_hour_shoot_is_refused_when_4_hours_are_left(
    photographer, service, make_booking
):
    date = working_date(12)
    _set_length(service, 20)
    make_booking(event_date=date, start_time=time(0, 0))  # 20:00-24:00 is left

    assert selectors.day_availability(photographer, date, 3).is_available is True
    assert selectors.suggested_start_times(photographer, date, 3) == ["20:00", "21:00"]

    day = selectors.day_availability(photographer, date, 6)
    assert day.is_available is False
    assert day.reason == UnavailableReason.NOT_ENOUGH_HOURS
    assert "Only 4 hours" in day.message and "6-hour shoot" in day.message
    assert selectors.suggested_start_times(photographer, date, 6) == []


@pytest.mark.parametrize("hours", [3, 6, 10])
def test_a_shoot_fits_when_exactly_enough_hours_are_left(
    photographer, service, make_booking, hours
):
    date = working_date(12)
    _set_length(service, 24 - hours)
    make_booking(event_date=date, start_time=time(0, 0))

    assert selectors.day_availability(photographer, date, hours).is_available is True
    assert selectors.day_availability(photographer, date, hours + 1).is_available is False
    assert selectors.suggested_start_times(photographer, date, hours) == [
        f"{24 - hours:02d}:00"
    ]


def test_free_hours_must_be_in_a_row(photographer, service, make_booking):
    """Free 00:00-04:00 and 20:00-24:00: 8 hours in total, but never 6 together."""
    date = working_date(12)
    _set_length(service, 16)
    make_booking(event_date=date, start_time=time(4, 0))

    day = selectors.day_availability(photographer, date, 6)
    assert day.reason == UnavailableReason.NOT_ENOUGH_HOURS
    assert selectors.day_availability(photographer, date, 4).is_available is True


def test_shoot_duration_blocks_overlapping_hours(photographer, service, make_booking):
    """
    If a 4-hour shoot is booked starting at 11:00 (11:00 - 15:00), another
    4-hour shoot must finish by 11:00 or start at/after 15:00.
    """
    date = working_date(12)
    _set_length(service, 4)
    make_booking(event_date=date, start_time=time(11, 0))

    times = selectors.suggested_start_times(photographer, date, duration_hours=4)

    assert times == [f"{hour:02d}:00" for hour in [*range(0, 8), *range(15, 21)]]


def test_an_unavailable_date_offers_nothing(photographer):
    assert selectors.suggested_start_times(photographer, timezone.localdate()) == []


def test_explicit_slots_override_the_hourly_grid(photographer):
    """
    A studio selling "10:00-13:00" and "14:00-17:00" gets exactly those two,
    not a nine-entry hourly list.
    """
    date = working_date(10)
    TimeSlot.objects.create(
        photographer=photographer, date=date, start_time=time(10, 0), end_time=time(13, 0)
    )
    TimeSlot.objects.create(
        photographer=photographer, date=date, start_time=time(14, 0), end_time=time(17, 0)
    )

    assert selectors.suggested_start_times(photographer, date) == ["10:00", "14:00"]


def test_a_booked_explicit_slot_is_not_offered(photographer):
    date = working_date(10)
    TimeSlot.objects.create(
        photographer=photographer, date=date, start_time=time(10, 0), end_time=time(13, 0)
    )
    TimeSlot.objects.create(
        photographer=photographer, date=date, start_time=time(14, 0),
        end_time=time(17, 0), is_booked=True,
    )

    assert selectors.suggested_start_times(photographer, date) == ["10:00"]


def test_earliest_bookable_date_respects_the_lead_time(settings):
    settings.BOOKING_MIN_LEAD_HOURS = 48
    assert selectors.earliest_bookable_date() >= timezone.localdate() + timedelta(days=1)


# ═══════════════════════════════════════════════════════════════════════════
# NOTICE PERIOD
# ═══════════════════════════════════════════════════════════════════════════
def _freeze(monkeypatch, *args):
    """Fix "now" to a UTC moment. Pakistan is five hours ahead."""
    now = datetime(*args, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, "now", lambda: now)


def test_hours_inside_the_notice_period_are_not_offered(photographer, monkeypatch):
    # 15:30 on Monday in Pakistan, so Tuesday opens at 16:00.
    _freeze(monkeypatch, 2027, 3, 1, 10, 30)
    tuesday = date_cls(2027, 3, 2)

    times = selectors.suggested_start_times(photographer, tuesday, 1)
    assert times == [f"{hour:02d}:00" for hour in range(16, 24)]
    assert selectors.day_availability(photographer, tuesday).remaining_slots == 8


def test_a_date_with_no_hour_past_the_notice_period_is_too_soon(
    photographer, monkeypatch
):
    # 23:30 on Monday in Pakistan: Tuesday's last start, 23:00, is too soon.
    _freeze(monkeypatch, 2027, 3, 1, 18, 30)

    day = selectors.day_availability(photographer, date_cls(2027, 3, 2))
    assert day.reason == UnavailableReason.TOO_SOON
    assert selectors.suggested_start_times(photographer, date_cls(2027, 3, 3), 1)[0] == "00:00"


# ═══════════════════════════════════════════════════════════════════════════
# PART-DAY BLOCKS
# ═══════════════════════════════════════════════════════════════════════════
def test_a_part_day_block_disables_its_hours(photographer):
    date = working_date(10)
    BlackoutDate.objects.create(
        photographer=photographer, start_date=date, end_date=date,
        is_full_day=False, start_time=time(9, 0), end_time=time(12, 0),
    )

    times = selectors.suggested_start_times(photographer, date, 2)
    assert times == [f"{hour:02d}:00" for hour in [*range(0, 8), *range(12, 23)]]


def test_an_overnight_block_covers_the_next_morning(photographer):
    date = working_date(10)
    BlackoutDate.objects.create(
        photographer=photographer, start_date=date, end_date=date,
        is_full_day=False, start_time=time(22, 0), end_time=time(2, 0),
    )

    assert selectors.suggested_start_times(photographer, date, 1)[-1] == "21:00"
    next_day = date + timedelta(days=1)
    assert selectors.suggested_start_times(photographer, next_day, 1)[0] == "02:00"


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH BY DATE
# ═══════════════════════════════════════════════════════════════════════════
def _search(date):
    from apps.profiles.filters import PhotographerFilterSet
    from apps.profiles.models import PhotographerProfile

    return PhotographerFilterSet(
        {"available_on": date.isoformat()}, queryset=PhotographerProfile.objects.all()
    ).qs


def test_search_keeps_a_photographer_with_free_hours(photographer, booking):
    assert photographer in _search(booking.event_date)


def test_search_hides_a_photographer_with_no_free_hour(photographer, service, make_booking):
    date = working_date(12)
    _set_length(service, 24)
    make_booking(event_date=date, start_time=time(0, 0))

    assert photographer not in _search(date)


@pytest.mark.parametrize("is_full_day", [True, False])
def test_search_hides_full_day_blocks_only(photographer, is_full_day):
    date = working_date(12)
    BlackoutDate.objects.create(
        photographer=photographer, start_date=date, end_date=date,
        is_full_day=is_full_day, start_time=time(9, 0), end_time=time(12, 0),
    )

    assert (photographer in _search(date)) is not is_full_day


# ═══════════════════════════════════════════════════════════════════════════
# 1 AND 2 DAY PACKAGES
# ═══════════════════════════════════════════════════════════════════════════
def test_a_day_package_needs_no_start_time_choice(photographer):
    date = working_date(12)

    assert selectors.suggested_start_times(photographer, date, 24) == ["00:00"]
    assert selectors.suggested_start_times(photographer, date, 48) == ["00:00"]


def test_one_booked_hour_closes_the_date_to_a_day_package(
    photographer, service, make_booking
):
    date = working_date(12)
    _set_length(service, 1)
    make_booking(event_date=date, start_time=time(23, 0))

    assert selectors.day_availability(photographer, date, 6).is_available is True
    day = selectors.day_availability(photographer, date, 24)
    assert day.reason == UnavailableReason.NOT_ENOUGH_HOURS
    assert "1-day package" in day.message


def test_a_2_day_package_needs_the_next_date_too(photographer, service, make_booking):
    date = working_date(12)
    _set_length(service, 1)
    make_booking(event_date=date + timedelta(days=1), start_time=time(23, 0))

    assert selectors.day_availability(photographer, date, 24).is_available is True
    day = selectors.day_availability(photographer, date, 48)
    assert day.reason == UnavailableReason.NOT_ENOUGH_HOURS
    assert f"{date + timedelta(days=1):%d %b}" in day.message
    # The last date of a window is checked against the day after it as well.
    window = selectors.availability_calendar(
        photographer, start=date - timedelta(days=2), days=3, duration_hours=48
    )
    assert window[-1].date == date and window[-1].is_available is False


@pytest.mark.parametrize("kind", ["blackout", "part_day", "day_off"])
def test_a_2_day_package_is_refused_when_the_next_date_is_closed(photographer, kind):
    date = working_date(12)
    following = date + timedelta(days=1)
    if kind == "day_off":
        AvailabilityRule.objects.filter(
            photographer=photographer, weekday=following.weekday()
        ).update(is_available=False)
    else:
        BlackoutDate.objects.create(
            photographer=photographer, start_date=following, end_date=following,
            is_full_day=kind == "blackout", start_time=time(9, 0), end_time=time(12, 0),
        )

    assert selectors.day_availability(photographer, date, 24).is_available is True
    assert selectors.day_availability(photographer, date, 48).is_available is False


def test_a_2_day_package_closes_both_dates(photographer, service, make_booking):
    date = working_date(12)
    _set_length(service, 48)
    make_booking(event_date=date, start_time=time(0, 0))

    for taken in (date, date + timedelta(days=1)):
        day = selectors.day_availability(photographer, taken, 3)
        assert day.reason == UnavailableReason.FULLY_BOOKED
    for free in (date - timedelta(days=1), date + timedelta(days=2)):
        assert selectors.day_availability(photographer, free, 24).is_available is True


def test_a_day_package_respects_the_notice_period(photographer, monkeypatch):
    # 15:30 on Monday in Pakistan: Tuesday 00:00 is under 24 hours away.
    _freeze(monkeypatch, 2027, 3, 1, 10, 30)

    tuesday = selectors.day_availability(photographer, date_cls(2027, 3, 2), 24)
    assert tuesday.reason == UnavailableReason.TOO_SOON
    wednesday = selectors.day_availability(photographer, date_cls(2027, 3, 3), 24)
    assert wednesday.is_available is True
