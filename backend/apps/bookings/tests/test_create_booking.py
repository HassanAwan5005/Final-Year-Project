"""
`services.create_booking` — the guards, the price snapshot and idempotency.

The transition tests live in test_state_machine.py; this file is about getting
a booking into existence correctly in the first place.
"""

from datetime import date as date_cls
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone

from apps.bookings.constants import BookingStatus
from apps.bookings.models import Booking, BookingPayment, BookingStatusHistory
from apps.bookings.services import create_booking
from apps.core.exceptions import BusinessRuleViolation, ConflictError
from conftest import working_date

pytestmark = pytest.mark.django_db


def _set_length(service, hours: int) -> None:
    """Make the photographer's service a shoot of this many hours."""
    service.duration_hours = hours
    service.save(update_fields=["duration_hours"])


def _set_daily_capacity(photographer, date, capacity: int) -> None:
    """Let the photographer take more than one shoot on `date`'s weekday."""
    from apps.availability.models import AvailabilityRule

    AvailabilityRule.objects.filter(
        photographer=photographer, weekday=date.weekday()
    ).update(max_bookings=capacity)


# ═══════════════════════════════════════════════════════════════════════════
# HAPPY PATH
# ═══════════════════════════════════════════════════════════════════════════
def test_creates_a_pending_booking(make_booking, buyer, photographer, service):
    booking = make_booking()

    assert booking.status == BookingStatus.PENDING
    assert booking.buyer_id == buyer.id
    assert booking.photographer_id == photographer.pk
    assert booking.category_id == service.category_id
    assert booking.reference == f"SNP-{booking.pk:06d}"


def test_writes_the_opening_history_row(make_booking, buyer):
    booking = make_booking()
    history = BookingStatusHistory.objects.filter(booking=booking)

    assert history.count() == 1
    row = history.first()
    assert row.from_status == ""
    assert row.to_status == BookingStatus.PENDING
    assert row.changed_by_id == buyer.id
    assert row.actor_role == "BUYER"


def test_creates_an_unpaid_payment_record(make_booking):
    booking = make_booking()
    payment = BookingPayment.objects.get(booking=booking)

    assert payment.status == "UNPAID"
    assert payment.paid_amount == Decimal("0.00")
    assert payment.outstanding == booking.total_price


def test_notifies_the_photographer(make_booking, photographer):
    from apps.notifications.models import Notification

    booking = make_booking()
    notification = Notification.objects.filter(
        recipient=photographer.user, notification_type="BOOKING_REQUEST"
    ).first()

    assert notification is not None
    assert notification.action_id == str(booking.pk)


def test_derives_end_time_from_the_duration(make_booking, service):
    booking = make_booking(start_time=time(9, 0))
    assert booking.duration_hours == service.duration_hours
    assert booking.end_time == time(17, 0)


# ═══════════════════════════════════════════════════════════════════════════
# PRICE SNAPSHOT
# The single most important property of this table: history must not change
# when the catalogue does.
# ═══════════════════════════════════════════════════════════════════════════
def test_snapshots_the_price(make_booking, service):
    booking = make_booking()

    assert booking.unit_price == service.price
    assert booking.quantity == 1
    assert booking.total_price == Decimal("85000.00")


def test_price_survives_the_service_changing(make_booking, service):
    booking = make_booking()

    service.price = Decimal("150000.00")
    service.save(update_fields=["price"])
    booking.refresh_from_db()

    assert booking.unit_price == Decimal("85000.00")
    assert booking.total_price == Decimal("85000.00")


def test_commission_and_payout_are_computed(make_booking):
    booking = make_booking()
    expected_commission = (
        booking.total_price * Decimal(str(settings.PLATFORM_COMMISSION_PERCENT)) / 100
    )

    assert booking.commission_amount == expected_commission
    assert booking.photographer_payout == booking.total_price - expected_commission


def test_hourly_service_multiplies_by_hours(buyer, hourly_service, event_date):
    booking = create_booking(
        buyer=buyer,
        service=hourly_service,
        event_date=event_date,
        start_time=time(10, 0),
        duration_hours=5,
        location_address="Gulberg, Lahore",
        location_city="Lahore",
    )

    assert booking.quantity == 5
    assert booking.unit_price == Decimal("6000.00")
    assert booking.total_price == Decimal("30000.00")


def test_hourly_service_respects_the_minimum(buyer, hourly_service, event_date):
    """A one-hour request on a two-hour minimum is billed for two."""
    booking = create_booking(
        buyer=buyer,
        service=hourly_service,
        event_date=event_date,
        start_time=time(10, 0),
        duration_hours=1,
        location_address="Gulberg, Lahore",
        location_city="Lahore",
    )

    assert booking.quantity == 2
    assert booking.duration_hours == 2


def test_package_price_wins_over_the_service_price(buyer, service, package, event_date):
    booking = create_booking(
        buyer=buyer,
        service=service,
        package=package,
        event_date=event_date,
        start_time=time(11, 0),
        duration_hours=3,  # ignored: a package has a fixed length
        location_address="F-7 Markaz",
        location_city="Islamabad",
    )

    assert booking.unit_price == Decimal("120000.00")
    assert booking.duration_hours == 10
    assert booking.quantity == 1


# ═══════════════════════════════════════════════════════════════════════════
# EXPIRY
# ═══════════════════════════════════════════════════════════════════════════
def test_expiry_uses_the_configured_window(make_booking):
    booking = make_booking()
    expected = timezone.now() + timedelta(hours=settings.BOOKING_EXPIRY_HOURS)

    assert abs((booking.expires_at - expected).total_seconds()) < 60


def test_expiry_never_outlives_the_event(buyer, service):
    """
    A 48-hour response window on a shoot 30 hours away would leave the request
    'awaiting a reply' after the event had already happened.
    """
    soon = working_date(2)
    booking = create_booking(
        buyer=buyer,
        service=service,
        event_date=soon,
        start_time=time(9, 0),
        location_address="F-7 Markaz",
        location_city="Islamabad",
    )

    assert booking.expires_at <= timezone.now() + timedelta(days=3)
    assert booking.expires_at.date() <= soon


# ═══════════════════════════════════════════════════════════════════════════
# GUARDS
# ═══════════════════════════════════════════════════════════════════════════
def test_photographer_cannot_book_themselves(photographer, service, event_date):
    with pytest.raises(BusinessRuleViolation, match="Only buyer accounts"):
        create_booking(
            buyer=photographer.user,
            service=service,
            event_date=event_date,
            start_time=time(14, 0),
            location_address="F-7",
            location_city="Islamabad",
        )


def test_refuses_an_inactive_service(buyer, service, event_date):
    service.is_active = False
    service.save(update_fields=["is_active"])

    with pytest.raises(BusinessRuleViolation, match="no longer available"):
        create_booking(
            buyer=buyer,
            service=service,
            event_date=event_date,
            start_time=time(14, 0),
            location_address="F-7",
            location_city="Islamabad",
        )


def test_refuses_a_photographer_who_paused_bookings(make_booking, photographer):
    photographer.is_accepting_bookings = False
    photographer.save(update_fields=["is_accepting_bookings"])

    with pytest.raises(BusinessRuleViolation, match="not accepting new bookings"):
        make_booking()


def test_refuses_an_unapproved_photographer(make_booking, photographer):
    photographer.is_approved = False
    photographer.save(update_fields=["is_approved"])

    with pytest.raises(BusinessRuleViolation, match="not available right now"):
        make_booking()


def test_refuses_a_date_inside_the_minimum_lead_time(make_booking):
    with pytest.raises(BusinessRuleViolation, match="hours' notice"):
        make_booking(event_date=timezone.localdate())


def test_refuses_a_weekday_the_photographer_does_not_work(
    make_booking, photographer, event_date
):
    from apps.availability.models import AvailabilityRule

    AvailabilityRule.objects.filter(
        photographer=photographer, weekday=event_date.weekday()
    ).update(is_available=False)

    with pytest.raises(BusinessRuleViolation, match=f"does not work on {event_date:%A}s"):
        make_booking(event_date=event_date)


def test_a_sunday_can_be_booked(make_booking):
    sunday = working_date(7)
    while sunday.weekday() != 6:
        sunday += timedelta(days=1)

    assert make_booking(event_date=sunday).event_date == sunday


def test_refuses_a_blacked_out_date(make_booking, photographer, event_date):
    from apps.availability.models import BlackoutDate

    BlackoutDate.objects.create(
        photographer=photographer,
        start_date=event_date - timedelta(days=1),
        end_date=event_date + timedelta(days=1),
        reason="Away for a family wedding",
    )

    with pytest.raises(BusinessRuleViolation, match="family wedding"):
        make_booking()


def test_a_free_hour_on_a_booked_date_can_still_be_booked(make_booking, other_buyer, service):
    """A booking blocks its own hours (14:00-22:00), not the whole date."""
    make_booking()

    _set_length(service, 2)
    second = make_booking(buyer=other_buyer, start_time=time(22, 0))
    assert second.status == BookingStatus.PENDING


def test_refuses_a_shoot_overlapping_one_from_the_night_before(
    make_booking, other_buyer, event_date
):
    first = make_booking(event_date=event_date)
    Booking.objects.filter(pk=first.pk).update(  # as older data can contain
        start_time=time(22, 0), duration_hours=4
    )

    with pytest.raises(ConflictError, match="already booked"):
        make_booking(
            buyer=other_buyer,
            event_date=event_date + timedelta(days=1),
            start_time=time(1, 0),
        )


def test_refuses_a_slot_that_is_already_taken(make_booking, other_buyer, photographer, event_date):
    """
    Same photographer, same date, same start time — the second request loses.

    Capacity is raised to two first, so this exercises the exact-slot guard
    rather than the daily limit. This is the application-level defence; the
    database constraint underneath is tested in test_concurrency.py.
    """
    _set_daily_capacity(photographer, event_date, 2)
    make_booking()

    with pytest.raises(ConflictError, match="already booked"):
        make_booking(buyer=other_buyer)


def test_refuses_overlapping_shoot_time(make_booking, other_buyer, photographer, event_date):
    """
    If a 4-hour shoot is booked at 14:00 (14:00 - 18:00),
    a second booking starting at 15:00 overlaps and must be refused.
    """
    _set_daily_capacity(photographer, event_date, 2)
    make_booking()  # 14:00 - 18:00

    with pytest.raises(ConflictError, match="overlaps with an existing booking"):
        make_booking(buyer=other_buyer, start_time=time(15, 0), duration_hours=2)


def test_a_second_booking_at_another_time_is_allowed_when_it_fits(
    make_booking, other_buyer
):
    """Two 8-hour shoots on one date: 14:00-22:00, then 06:00-14:00."""
    first = make_booking()
    second = make_booking(buyer=other_buyer, start_time=time(6, 0))

    assert first.pk != second.pk
    assert second.status == BookingStatus.PENDING


def test_a_cancelled_booking_frees_its_slot(make_booking, buyer):
    from apps.bookings.services import cancel_booking

    first = make_booking()
    cancel_booking(first, buyer)

    second = make_booking()
    assert second.pk != first.pk
    assert second.status == BookingStatus.PENDING


def test_caps_concurrent_pending_requests(buyer, service, settings):
    settings.MAX_PENDING_BOOKINGS_PER_BUYER = 2

    for offset in (7, 14):
        create_booking(
            buyer=buyer,
            service=service,
            event_date=working_date(offset),
            start_time=time(9, 0),
            location_address="F-7",
            location_city="Islamabad",
        )

    with pytest.raises(BusinessRuleViolation, match="awaiting a reply"):
        create_booking(
            buyer=buyer,
            service=service,
            event_date=working_date(21),
            start_time=time(9, 0),
            location_address="F-7",
            location_city="Islamabad",
        )


# ═══════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════════════════
def test_the_same_key_returns_the_same_booking(make_booking):
    first = make_booking(idempotency_key="abc-123")
    second = make_booking(idempotency_key="abc-123")

    assert first.pk == second.pk
    assert Booking.objects.count() == 1


def test_a_different_key_creates_a_new_booking(make_booking):
    first = make_booking(idempotency_key="abc-123")
    second = make_booking(idempotency_key="def-456", event_date=working_date(14))

    assert first.pk != second.pk
    assert Booking.objects.count() == 2


def test_a_failed_attempt_releases_its_key(make_booking, photographer):
    """
    A key burned by a failure would make the buyer's legitimate retry fail
    forever with a stale error.
    """
    photographer.is_accepting_bookings = False
    photographer.save(update_fields=["is_accepting_bookings"])
    with pytest.raises(BusinessRuleViolation):
        make_booking(idempotency_key="retry-me")

    photographer.is_accepting_bookings = True
    photographer.save(update_fields=["is_accepting_bookings"])

    booking = make_booking(idempotency_key="retry-me")
    assert booking.status == BookingStatus.PENDING


def test_refuses_an_hour_inside_the_notice_period(make_booking, monkeypatch):
    """Same date, but 14:00 is under 24 hours away and 16:00 is not."""
    # 15:30 on Monday in Pakistan.
    now = datetime(2027, 3, 1, 10, 30, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, "now", lambda: now)
    tuesday = date_cls(2027, 3, 2)

    with pytest.raises(BusinessRuleViolation, match="hours' notice"):
        make_booking(event_date=tuesday, start_time=time(14, 0))

    assert make_booking(event_date=tuesday, start_time=time(16, 0)).pk


def test_refuses_a_shoot_inside_a_part_day_block(make_booking, photographer, event_date):
    from apps.availability.models import BlackoutDate

    BlackoutDate.objects.create(
        photographer=photographer, start_date=event_date, end_date=event_date,
        is_full_day=False, start_time=time(9, 0), end_time=time(12, 0),
    )

    with pytest.raises(BusinessRuleViolation, match="unavailable at that time"):
        make_booking(start_time=time(10, 0))

    assert make_booking(start_time=time(12, 0)).pk


# ═══════════════════════════════════════════════════════════════════════════
# SHOOT LENGTH
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hours", [3, 6, 10])
def test_a_booking_always_takes_the_services_full_length(make_booking, service, hours):
    """A caller cannot shrink a fixed-price shoot to squeeze it in."""
    _set_length(service, hours)

    assert make_booking(start_time=time(9, 0), duration_hours=1).duration_hours == hours


def test_refuses_a_6_hour_shoot_when_4_hours_are_left(
    make_booking, other_buyer, service
):
    _set_length(service, 20)
    make_booking(start_time=time(0, 0))  # 20:00-24:00 is left

    _set_length(service, 6)
    with pytest.raises(BusinessRuleViolation, match="Only 4 hours in a row left"):
        make_booking(buyer=other_buyer, start_time=time(20, 0))

    _set_length(service, 3)
    assert make_booking(buyer=other_buyer, start_time=time(20, 0)).pk


def test_refuses_a_shoot_that_runs_past_midnight(make_booking, service):
    _set_length(service, 6)
    with pytest.raises(BusinessRuleViolation, match="would not finish"):
        make_booking(start_time=time(19, 0))

    assert make_booking(start_time=time(18, 0)).end_time == time(0, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 1 AND 2 DAY PACKAGES
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hours, days", [(24, 1), (48, 2)])
def test_a_day_package_books_whole_days(make_booking, service, event_date, hours, days):
    """Whatever time is sent, the booking starts at midnight."""
    _set_length(service, hours)
    booking = make_booking(start_time=time(15, 0))

    assert booking.start_time == time(0, 0)
    assert booking.duration_hours == hours
    assert booking.last_date == event_date + timedelta(days=days - 1)
    assert booking.total_price == service.price


def test_a_day_package_notification_has_no_time(make_booking, service, photographer):
    from apps.notifications.models import Notification

    _set_length(service, 48)
    make_booking()

    body = Notification.objects.get(
        recipient=photographer.user, notification_type="BOOKING_REQUEST"
    ).body
    assert "for 2 days" in body and "00:00" not in body


def test_refuses_a_shoot_on_the_second_day_of_a_package(
    make_booking, other_buyer, service, event_date
):
    _set_length(service, 48)
    make_booking()

    _set_length(service, 3)
    with pytest.raises(BusinessRuleViolation, match="Fully booked"):
        make_booking(buyer=other_buyer, event_date=event_date + timedelta(days=1))


def test_refuses_a_day_package_when_an_hour_is_taken(
    make_booking, other_buyer, service, event_date
):
    _set_length(service, 3)
    make_booking(event_date=event_date + timedelta(days=1))

    _set_length(service, 48)
    with pytest.raises(BusinessRuleViolation, match="not completely free"):
        make_booking(buyer=other_buyer)

    _set_length(service, 24)
    assert make_booking(buyer=other_buyer).pk


def test_a_2_day_package_cannot_be_completed_on_its_first_day(
    make_booking, service, photographer
):
    from apps.bookings.services import accept_booking, complete_booking

    _set_length(service, 48)
    booking = accept_booking(make_booking(), photographer.user)
    booking.event_date = timezone.localdate()
    booking.save(update_fields=["event_date"])

    with pytest.raises(BusinessRuleViolation, match="not happened yet"):
        complete_booking(booking, photographer.user)
