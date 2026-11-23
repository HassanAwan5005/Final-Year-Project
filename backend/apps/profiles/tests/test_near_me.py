"""
"Near me" on the Home screen — photographers by distance from the buyer.

The app sends the phone's lat/lng with a radius. The list must be the nearest
first across ALL results (not re-sorted inside each page), and must not include
photographers outside the radius that the square bounding-box pre-filter lets
through at its corners.
"""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db

URL = "/api/v1/profiles/photographers/"

# Central Islamabad
HERE = (33.6844, 73.0479)


def _photographer(email, lat, lng):
    from django.contrib.auth import get_user_model

    from apps.profiles.services import create_photographer_profile

    user = get_user_model().objects.create_photographer(
        email=email,
        password="TestPass123!",
        full_name=email.split("@")[0],
        city="Islamabad",
        is_email_verified=True,
    )
    user.latitude = Decimal(str(lat))
    user.longitude = Decimal(str(lng))
    user.save(update_fields=["latitude", "longitude"])
    profile = create_photographer_profile(user)
    profile.is_approved = True
    profile.save()
    return profile


@pytest.fixture
def spread():
    return {
        # ~1 km north
        "near": _photographer("near@test.pk", 33.6934, 73.0479),
        # ~10 km north
        "mid": _photographer("mid@test.pk", 33.7744, 73.0479),
        # ~20 km north
        "far": _photographer("far@test.pk", 33.8644, 73.0479),
        # Inside the 25 km square but ~31 km away, in its corner
        "corner": _photographer("corner@test.pk", 33.8834, 73.2879),
        # Lahore, ~270 km away
        "lahore": _photographer("lahore@test.pk", 31.5204, 74.3587),
    }


def _get(client, **params):
    response = client.get(URL, {"lat": HERE[0], "lng": HERE[1], **params})
    assert response.status_code == 200
    return response.json()


def test_nearest_first_across_every_page(api_client, spread):
    """Page size 2: page one must hold the two nearest overall, not two random ones."""
    first = _get(api_client, radius_km=25, page_size=2, page=1)
    second = _get(api_client, radius_km=25, page_size=2, page=2)

    ids = [row["id"] for row in first["data"] + second["data"]]
    assert ids == [spread["near"].pk, spread["mid"].pk, spread["far"].pk]
    assert first["meta"]["pagination"]["total_items"] == 3


def test_the_radius_is_a_circle_not_a_square(api_client, spread):
    rows = _get(api_client, radius_km=25)["data"]
    ids = {row["id"] for row in rows}
    assert spread["corner"].pk not in ids
    assert spread["lahore"].pk not in ids
    assert all(row["distance_km"] <= 25 for row in rows)


def test_each_card_carries_its_distance(api_client, spread):
    rows = _get(api_client, radius_km=25)["data"]
    distances = [row["distance_km"] for row in rows]
    assert distances == sorted(distances)
    assert 0.5 < distances[0] < 1.5


def test_an_explicit_ordering_still_wins(api_client, spread):
    """A caller who asks for another order (here rating) still gets the radius filter."""
    rows = _get(api_client, radius_km=25, ordering="-rating")["data"]
    assert {row["id"] for row in rows} >= {spread["near"].pk, spread["mid"].pk}
