"""
Endpoints the admin app's screens read that the older tests do not cover:
the Bookings list / detail, and ads reported from the shop.
"""

import pytest

from apps.administration.models import ModerationFlag

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/admin/"
SHOP = "/api/v1/marketplace/"


# ═══════════════════════════════════════════════════════════════════════════
# BOOKINGS
# ═══════════════════════════════════════════════════════════════════════════
def test_admin_lists_every_booking(admin_client_authed, booking):
    response = admin_client_authed.get(f"{ADMIN}bookings/")

    assert response.status_code == 200
    rows = response.json()["data"]
    assert [row["id"] for row in rows] == [booking.pk]
    assert rows[0]["reference"] == booking.reference
    assert rows[0]["can_force_cancel"] is True


def test_admin_booking_list_filters_and_searches(admin_client_authed, booking):
    def ids(query):
        return [row["id"] for row in admin_client_authed.get(f"{ADMIN}bookings/{query}").json()["data"]]

    assert ids("?status=pending") == [booking.pk]
    assert ids("?status=COMPLETED") == []
    assert ids(f"?q={booking.reference}") == [booking.pk]
    assert ids(f"?q={booking.buyer.email}") == [booking.pk]
    assert ids("?q=nobody-matches-this") == []


def test_admin_booking_detail_has_the_timeline(admin_client_authed, booking):
    response = admin_client_authed.get(f"{ADMIN}bookings/{booking.pk}/")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == booking.pk
    assert data["history"][0]["to_status"] == "PENDING"


def test_admin_booking_detail_404s_for_a_missing_booking(admin_client_authed):
    assert admin_client_authed.get(f"{ADMIN}bookings/999999/").status_code == 404


def test_a_cancelled_booking_cannot_be_force_cancelled_again(admin_client_authed, booking):
    admin_client_authed.post(
        f"{ADMIN}bookings/{booking.pk}/force-cancel/",
        {"reason": "Duplicate booking created by a client-side retry."},
        format="json",
    )
    data = admin_client_authed.get(f"{ADMIN}bookings/{booking.pk}/").json()["data"]

    assert data["status"] == "CANCELLED"
    assert data["can_force_cancel"] is False


def test_non_admins_cannot_list_bookings(buyer_client, photographer_client):
    assert buyer_client.get(f"{ADMIN}bookings/").status_code == 403
    assert photographer_client.get(f"{ADMIN}bookings/").status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# REPORTING AN AD
# ═══════════════════════════════════════════════════════════════════════════
def test_a_buyer_can_report_an_ad(buyer_client, product):
    response = buyer_client.post(
        f"{SHOP}products/{product.slug}/report/",
        {"reason": "FAKE", "detail": "Stock photos, not the real item."},
        format="json",
    )

    assert response.status_code == 200
    flag = ModerationFlag.objects.get(pk=response.json()["data"]["flag_id"])
    assert flag.content_type == "PRODUCT"
    assert flag.object_id == product.pk
    assert flag.status == "OPEN"


def test_a_seller_cannot_report_their_own_ad(photographer_client, product):
    response = photographer_client.post(
        f"{SHOP}products/{product.slug}/report/", {"reason": "SPAM"}, format="json"
    )
    assert response.status_code in (400, 422)
    assert not ModerationFlag.objects.exists()


def test_reporting_needs_a_login(api_client, product):
    response = api_client.post(
        f"{SHOP}products/{product.slug}/report/", {"reason": "SPAM"}, format="json"
    )
    assert response.status_code == 401


def test_an_unknown_reason_is_refused(buyer_client, product):
    response = buyer_client.post(
        f"{SHOP}products/{product.slug}/report/", {"reason": "BORING"}, format="json"
    )
    assert response.status_code == 400


def test_actioning_an_ad_report_takes_the_ad_down(admin_client_authed, buyer_client, product):
    flag_id = buyer_client.post(
        f"{SHOP}products/{product.slug}/report/", {"reason": "FAKE"}, format="json"
    ).json()["data"]["flag_id"]

    queue = admin_client_authed.get(f"{ADMIN}flags/?content_type=PRODUCT").json()["data"]
    assert [row["id"] for row in queue] == [flag_id]
    assert queue[0]["target_preview"] == product.title

    response = admin_client_authed.post(
        f"{ADMIN}flags/{flag_id}/resolve/",
        {"action": "ACTIONED", "note": "Fake listing — removed from the shop."},
        format="json",
    )
    product.refresh_from_db()

    assert response.status_code == 200
    # Removal keeps the row (purchase history) but takes it out of the shop.
    assert product.is_approved is False
    shop = admin_client_authed.get(f"{SHOP}products/").json()["data"]
    assert product.pk not in [row["id"] for row in shop]
