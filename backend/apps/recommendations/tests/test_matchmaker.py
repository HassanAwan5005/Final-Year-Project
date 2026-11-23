"""
The Home screen's AI search box — the conversational matchmaker.

THE PROPERTY UNDER TEST
----------------------
A buyer who types a city and a budget is stating requirements, not
preferences. "Wedding in Lahore under 50k" must never return a Karachi
photographer, or one whose cheapest shoot is above Rs 50,000.

This was a real defect: budget was only a score factor, the "too few results"
fallback dropped every filter (city included), and "within 7 days" was read as
a budget of Rs 7.
"""

from decimal import Decimal

import pytest

from apps.recommendations.matchmaker import match_shoot, parse_shoot_prompt

pytestmark = pytest.mark.django_db


# ═══════════════════════════════════════════════════════════════════════════
# PARSING
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "prompt, city, min_price, max_price",
    [
        ("wedding photographer in Lahore under 50k", "Lahore", None, 50000),
        ("mehndi in karachi budget 40,000", "Karachi", None, 40000),
        ("birthday shoot pindi 25k budget", "Rawalpindi", None, 25000),
        ("corporate event Multan between 20k and 60k", "Multan", 20000, 60000),
        ("fashion shoot in Sialkot 20 to 50k", "Sialkot", 20000, 50000),
        ("walima Lahore 1.5 lakh max", "Lahore", None, 150000),
        ("wedding in Faisalabad for 2 people under 1,50,000", "Faisalabad", None, 150000),
        ("candid photographer Peshawar Rs 45000", "Peshawar", None, 45000),
        ("graduation Hyderabad upto 35k", "Hyderabad", None, 35000),
        ("4k video wedding in Lahore under 80 thousand", "Lahore", None, 80000),
    ],
)
def test_city_and_budget_are_read_from_the_prompt(prompt, city, min_price, max_price):
    parsed = parse_shoot_prompt(prompt)
    assert parsed.city == city
    assert parsed.min_price == min_price
    assert parsed.max_price == max_price


@pytest.mark.parametrize(
    "prompt",
    [
        "photographer in Islamabad within 7 days",
        "baraat Quetta within 15 days",
        "wedding in Lahore for 3 hours",
        "wedding in Lahore under 5",
    ],
)
def test_a_number_that_is_not_money_is_not_a_budget(prompt):
    assert parse_shoot_prompt(prompt).max_price is None


def test_a_delivery_time_does_not_hide_the_budget_after_it():
    parsed = parse_shoot_prompt("Islamabad within 7 days under Rs 30000")
    assert parsed.delivery_days == 7
    assert parsed.max_price == 30000


def test_a_city_photographers_registered_with_is_recognised(category):
    """A city outside the built-in list must still become a filter."""
    _photographer("gujrat@test.pk", "Gujrat", [("Shoot", "20000")], category)
    assert parse_shoot_prompt("wedding photographer in Gujrat").city == "Gujrat"


# ═══════════════════════════════════════════════════════════════════════════
# MATCHING
# ═══════════════════════════════════════════════════════════════════════════
def _photographer(email, city, services, category, *, specialist=False, base_price="99000"):
    from django.contrib.auth import get_user_model

    from apps.catalog.models import Service
    from apps.profiles.services import create_photographer_profile

    user = get_user_model().objects.create_photographer(
        email=email,
        password="TestPass123!",
        full_name=email.split("@")[0],
        city=city,
        is_email_verified=True,
    )
    profile = create_photographer_profile(user)
    profile.is_approved = True
    # Deliberately stale, like the seeded data: higher than any service.
    profile.base_price = Decimal(base_price)
    profile.save()
    if specialist:
        profile.categories.add(category)
    for title, price in services:
        Service.objects.create(
            photographer=profile, category=category, title=title,
            price=Decimal(price), duration_hours=4,
        )
    return profile


@pytest.fixture
def market(category):
    return {
        "lahore_cheap": _photographer(
            "lc@test.pk", "Lahore", [("Basic", "30000"), ("Full", "90000")], category,
            specialist=True,
        ),
        "lahore_dear": _photographer(
            "ld@test.pk", "Lahore", [("Premium", "120000")], category, specialist=True,
        ),
        "lahore_other": _photographer(
            "lo@test.pk", "Lahore", [("Session", "45000")], category,
        ),
        "karachi_cheap": _photographer(
            "kc@test.pk", "Karachi", [("Basic", "20000")], category, specialist=True,
        ),
    }


def _ids(result):
    return {p.pk for p in result["photographers"]}


def test_only_photographers_in_the_named_city_are_returned(market):
    result = match_shoot("photographer in Lahore")
    assert market["karachi_cheap"].pk not in _ids(result)
    assert {p.user.city for p in result["photographers"]} == {"Lahore"}


def test_photographers_above_the_budget_are_not_returned(market):
    result = match_shoot("photographer in Lahore under 50k")
    assert _ids(result) == {market["lahore_cheap"].pk, market["lahore_other"].pk}


def test_a_budget_range_needs_a_service_inside_it(market):
    result = match_shoot("photographer in Lahore between 40k and 60k")
    assert _ids(result) == {market["lahore_other"].pk}


def test_only_the_requested_kind_of_photographer_is_returned(market):
    """
    Only one Lahore wedding photographer fits 50k. The search must NOT fill
    the list with photographers of other categories to make up the numbers.
    """
    result = match_shoot("mehndi in Lahore under 50k")
    assert result["relaxed_notice"] is None
    assert _ids(result) == {market["lahore_cheap"].pk}


@pytest.mark.parametrize(
    "prompt, category",
    [
        ("mehndi in Lahore", "wedding"),
        ("barat photography Karachi", "wedding"),
        ("walima shoot", "wedding"),
        ("nikkah and rukhsati", "wedding"),
        ("our company annual dinner", "corporate"),
        ("headshots for our organization", "corporate"),
        ("CEO portrait at the office", "corporate"),
        ("office party", "corporate"),
        ("product launch for a startup", "corporate"),
        ("lookbook for my clothing brand", "fashion"),
        ("models for a fashion shoot", "fashion"),
        ("my son's birthday party", "birthday"),
        ("bday shoot", "birthday"),
        ("university convocation", "graduation"),
        ("graduation day photos", "graduation"),
    ],
)
def test_the_request_is_matched_to_its_category(prompt, category):
    assert parse_shoot_prompt(prompt).category == category


def test_no_photographer_of_that_kind_names_the_kind(market):
    message = match_shoot("corporate event in Lahore")["assistant_message"]
    assert "No corporate photographers are listed in Lahore" in message


def test_a_budget_too_low_for_that_kind_names_the_kind(market):
    result = match_shoot("mehndi in Lahore under 10k")
    assert result["photographers"] == []
    assert "Nothing in Lahore for wedding shoots fits your budget" in result["assistant_message"]


def test_the_card_price_is_the_real_cheapest_service(market):
    """The card reads base_price; a stale one made in-budget results look over budget."""
    result = match_shoot("photographer in Lahore under 50k")
    by_id = {p.pk: p for p in result["photographers"]}
    assert by_id[market["lahore_cheap"].pk].base_price == Decimal("30000")
    assert by_id[market["lahore_cheap"].pk].matching_service_price == Decimal("30000")


def test_no_match_returns_nothing_rather_than_other_cities(market):
    result = match_shoot("photographer in Lahore under 10k")
    assert result["photographers"] == []


# ═══════════════════════════════════════════════════════════════════════════
# WHEN NOTHING FITS — the message says which requirement failed
# ═══════════════════════════════════════════════════════════════════════════
def test_an_empty_city_is_named(market):
    message = match_shoot("photographer in Quetta under 50k")["assistant_message"]
    assert "No photographers are listed in Quetta" in message


def test_a_known_city_with_no_photographers_is_not_ignored(market):
    """Not recognising the city would silently search all of Pakistan."""
    result = match_shoot("wedding photographer in Gujrat under 50k")
    assert result["photographers"] == []
    assert "No photographers are listed in Gujrat" in result["assistant_message"]


def test_a_budget_below_every_price_names_the_lowest_price(market):
    message = match_shoot("photographer in Lahore under 10k")["assistant_message"]
    assert "Nothing in Lahore fits your budget of Rs. 10,000" in message
    assert "Rs. 30,000" in message  # the cheapest Lahore service


def test_a_range_with_nothing_inside_names_the_real_range(market):
    message = match_shoot("photographer in Lahore between 50k and 80k")["assistant_message"]
    assert "Nothing in Lahore is priced between Rs. 50,000 and Rs. 80,000" in message
    assert "Rs. 30,000 to Rs. 120,000" in message


def test_a_rating_requirement_is_named(market):
    message = match_shoot("top rated photographer in Lahore under 50k")["assistant_message"]
    assert "rated 4.5★ or higher" in message
