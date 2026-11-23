"""
The Shop HTTP surface.

Covers what the service tests cannot: visibility rules at the endpoint, the
per-request flag loading that keeps the grid at a constant query count, and
the shapes the mobile app parses.
"""

import pytest

from apps.marketplace.models import DigitalProduct

pytestmark = pytest.mark.django_db

URL = "/api/v1/marketplace/"


# ═══════════════════════════════════════════════════════════════════════════
# BROWSING
# ═══════════════════════════════════════════════════════════════════════════
def test_browsing_is_public(api_client, product):
    response = api_client.get(f"{URL}products/")

    assert response.status_code == 200
    assert [row["slug"] for row in response.json()["data"]] == [product.slug]


def test_anonymous_flags_are_all_false(api_client, product):
    row = api_client.get(f"{URL}products/").json()["data"][0]

    assert row["is_owned"] is False
    assert row["is_wishlisted"] is False


def test_unapproved_products_are_hidden(api_client, product):
    product.is_approved = False
    product.save(update_fields=["is_approved"])
    assert api_client.get(f"{URL}products/").json()["data"] == []


def test_a_suspended_sellers_catalogue_disappears(api_client, product, photographer):
    """
    A blocked photographer's products must not stay on sale — they would take
    a buyer's money and credit a wallet the platform has disabled.
    """
    photographer.user.is_blocked = True
    photographer.user.save(update_fields=["is_blocked"])

    assert api_client.get(f"{URL}products/").json()["data"] == []


def test_detail_by_slug(api_client, product):
    body = api_client.get(f"{URL}products/{product.slug}/").json()["data"]

    assert body["title"] == product.title
    assert body["discount_percent"] == 30
    assert len(body["files"]) == 2


def test_detail_counts_a_view(api_client, product):
    api_client.get(f"{URL}products/{product.slug}/")
    product.refresh_from_db()
    assert product.view_count == 1


def test_unknown_slug_is_404(api_client):
    assert api_client.get(f"{URL}products/nope/").status_code == 404


def test_search_and_filters(api_client, product, second_product):
    def slugs(query):
        return {r["slug"] for r in api_client.get(f"{URL}products/?{query}").json()["data"]}

    assert slugs("q=desi") == {product.slug}
    assert slugs("product_type=LENS") == {second_product.slug}
    assert slugs("max_price=2500") == {second_product.slug}
    assert slugs("on_sale=true") == {product.slug}
    assert slugs("ordering=price") == {product.slug, second_product.slug}


def test_affordable_filter_uses_the_callers_balance(
    buyer_client, funded_buyer, product, second_product
):
    """Resolved in the view — the FilterSet has no idea who is asking."""
    from decimal import Decimal

    from apps.profiles.models import Wallet

    Wallet.objects.filter(user=funded_buyer).update(balance=Decimal("2500.00"))
    rows = buyer_client.get(f"{URL}products/?affordable=true").json()["data"]

    assert {r["slug"] for r in rows} == {second_product.slug}


def test_filter_options_come_from_the_data(api_client, product, second_product):
    body = api_client.get(f"{URL}products/filters/").json()["data"]

    assert body["price_range"] == {"min": 2000.0, "max": 3500.0}
    assert {t["value"] for t in body["types"]} == {"CAMERA_ACCESSORY", "LENS"}
    assert body["sort_options"]


def test_featured_and_bestsellers(api_client, product, second_product):
    product.is_featured = True
    product.save(update_fields=["is_featured"])

    featured = api_client.get(f"{URL}products/featured/").json()["data"]
    best = api_client.get(f"{URL}products/bestsellers/").json()["data"]

    assert [r["slug"] for r in featured] == [product.slug]
    assert len(best) == 2


def test_the_grid_costs_a_constant_number_of_queries(
    buyer_client, product, second_product, django_assert_max_num_queries
):
    """
    Ownership and wishlist membership are loaded once per request. Read per
    row instead, a 20-card grid would cost 40 extra queries.
    """
    with django_assert_max_num_queries(9):
        buyer_client.get(f"{URL}products/")


# ═══════════════════════════════════════════════════════════════════════════
# PAST ORDERS
# ═══════════════════════════════════════════════════════════════════════════
def test_buying_endpoints_are_gone(buyer_client, product):
    """Deals are made in chat — there is no cart or checkout to post to."""
    assert buyer_client.get(f"{URL}cart/").status_code == 404
    assert (
        buyer_client.post(f"{URL}cart/add/", {"product": product.pk}).status_code == 404
    )
    assert buyer_client.post(f"{URL}orders/checkout/", {}).status_code in (404, 405)


def test_past_orders_list_and_detail(buyer_client, funded_buyer, product, make_order):
    order = make_order(funded_buyer, product)

    listed = buyer_client.get(f"{URL}orders/").json()["data"]
    assert [row["order_number"] for row in listed] == [order.order_number]

    detail = buyer_client.get(f"{URL}orders/{order.pk}/").json()["data"]
    assert detail["items"][0]["product_title"] == product.title


def test_someone_elses_order_is_404(
    other_buyer_client, funded_buyer, product, make_order
):
    order = make_order(funded_buyer, product)
    assert other_buyer_client.get(f"{URL}orders/{order.pk}/").status_code == 404


def test_ownership_shows_up_in_the_grid(
    buyer_client, funded_buyer, product, make_order
):
    make_order(funded_buyer, product)

    row = buyer_client.get(f"{URL}products/").json()["data"][0]
    assert row["is_owned"] is True


# ═══════════════════════════════════════════════════════════════════════════
# SELLER VIEW
# ═══════════════════════════════════════════════════════════════════════════
def test_seller_sees_their_own_catalogue(photographer_client, product):
    rows = photographer_client.get(f"{URL}seller/products/").json()["data"]
    assert [r["slug"] for r in rows] == [product.slug]


def test_seller_summary_reflects_a_past_sale(
    photographer_client, funded_buyer, product, make_order
):
    make_order(funded_buyer, product)

    body = photographer_client.get(f"{URL}seller/products/summary/").json()["data"]
    assert body["sales_count"] == 1
    assert body["gross_revenue"] == "3500.00"
    assert body["net_earnings"] == "2975.00"   # 15% commission


def test_a_buyer_starts_with_an_empty_seller_catalogue(buyer_client):
    response = buyer_client.get(f"{URL}seller/products/")
    assert response.status_code == 200
    assert response.json()["data"] == []


# ═══════════════════════════════════════════════════════════════════════════
# SELLING
# ═══════════════════════════════════════════════════════════════════════════
def _photo(name="item.png"):
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _listing(**overrides):
    data = {
        "title": "Canon 50mm f/1.8 lens",
        "description": "Lightly used, no scratches, comes with both caps.",
        "price": "18000",
        "product_type": "LENS",
        "address": "Gulberg III, Lahore",
        "photos": [_photo("a.png"), _photo("b.png")],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("client_fixture", ["buyer_client", "photographer_client"])
def test_buyers_and_photographers_can_list_a_product(request, client_fixture, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client = request.getfixturevalue(client_fixture)

    response = client.post(f"{URL}seller/products/", _listing(), format="multipart")

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["title"] == "Canon 50mm f/1.8 lens"
    assert body["is_published"] is True
    assert body["is_approved"] is True           # live at once — no admin approval
    assert body["thumbnail_url"]
    rows = client.get(f"{URL}seller/products/").json()["data"]
    assert [r["slug"] for r in rows] == [body["slug"]]


def test_a_listing_needs_a_photo(buyer_client):
    response = buyer_client.post(
        f"{URL}seller/products/", _listing(photos=[]), format="multipart"
    )
    assert response.status_code == 400


def test_a_new_listing_is_in_the_shop_straight_away(
    buyer_client, other_buyer_client, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    slug = buyer_client.post(
        f"{URL}seller/products/", _listing(), format="multipart"
    ).json()["data"]["slug"]

    rows = other_buyer_client.get(f"{URL}products/").json()["data"]
    assert slug in [r["slug"] for r in rows]


def test_an_ad_an_admin_removed_is_not_in_the_shop(
    buyer_client, other_buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    DigitalProduct.objects.filter(pk=listing.pk).update(is_approved=False)

    rows = other_buyer_client.get(f"{URL}products/").json()["data"]
    assert listing.slug not in [r["slug"] for r in rows]


@pytest.mark.parametrize("address", [None, "", "    ", "abc"])
def test_a_listing_needs_an_address(buyer_client, address):
    data = _listing(address=address)
    if address is None:
        del data["address"]
    response = buyer_client.post(f"{URL}seller/products/", data, format="multipart")

    assert response.status_code == 400
    assert DigitalProduct.objects.count() == 0


def test_everyone_sees_an_approved_listings_photos_and_address(
    api_client, buyer, buyer_client, other_buyer_client, photographer_client,
    settings, tmp_path,
):
    listing = _live_listing(buyer_client, settings, tmp_path)

    for client in (api_client, buyer_client, other_buyer_client, photographer_client):
        detail = client.get(f"{URL}products/{listing.slug}/").json()["data"]
        assert detail["seller"]["display_name"] == buyer.full_name
        assert detail["seller"]["id"] == buyer.pk
        assert len(detail["preview_image_urls"]) == 2
        assert detail["address"] == "Gulberg III, Lahore"


# ═══════════════════════════════════════════════════════════════════════════
# EDITING AN AD
# ═══════════════════════════════════════════════════════════════════════════
def _live_listing(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    slug = client.post(
        f"{URL}seller/products/", _listing(), format="multipart"
    ).json()["data"]["slug"]
    DigitalProduct.objects.filter(slug=slug).update(is_approved=True)
    return DigitalProduct.objects.get(slug=slug)


def _edit(client, listing, *, keep=None, photos=(), **overrides):
    data = _listing(**overrides)
    data["keep_photos"] = listing.preview_images if keep is None else keep
    data["photos"] = list(photos)
    return client.patch(
        f"{URL}seller/products/{listing.pk}/", data, format="multipart"
    )


def test_the_edit_form_gets_the_whole_ad(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    body = buyer_client.get(f"{URL}seller/products/{listing.pk}/").json()["data"]

    assert body["description"] == listing.description
    assert body["address"] == "Gulberg III, Lahore"
    assert [photo["path"] for photo in body["photos"]] == listing.preview_images
    assert all(photo["url"].startswith("http") for photo in body["photos"])


def test_a_seller_can_add_and_remove_photos_of_a_live_ad(
    buyer_client, settings, tmp_path, django_capture_on_commit_callbacks
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    first, second = listing.preview_images
    old_thumbnail = listing.thumbnail.name

    with django_capture_on_commit_callbacks(execute=True):
        response = _edit(
            buyer_client, listing, keep=[second], photos=[_photo("c.png"), _photo("d.png")]
        )

    assert response.status_code == 200, response.content
    listing.refresh_from_db()
    assert len(listing.preview_images) == 3
    assert listing.preview_images[0] == second
    assert first not in listing.preview_images
    # A new cover, and the removed files are gone from storage.
    assert listing.thumbnail.name != old_thumbnail
    assert not (tmp_path / first).exists()
    assert not (tmp_path / old_thumbnail).exists()
    assert all((tmp_path / path).exists() for path in listing.preview_images)
    assert (tmp_path / listing.thumbnail.name).exists()


def test_every_photo_can_be_replaced(
    buyer_client, settings, tmp_path, django_capture_on_commit_callbacks
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    old = listing.preview_images

    with django_capture_on_commit_callbacks(execute=True):
        assert _edit(buyer_client, listing, keep=[], photos=[_photo("n.png")]).status_code == 200

    listing.refresh_from_db()
    assert len(listing.preview_images) == 1
    assert not set(old) & set(listing.preview_images)


def test_adding_a_photo_keeps_the_cover(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    thumbnail = listing.thumbnail.name

    assert _edit(buyer_client, listing, photos=[_photo("c.png")]).status_code == 200
    listing.refresh_from_db()
    assert listing.thumbnail.name == thumbnail
    assert len(listing.preview_images) == 3


def test_a_photo_shared_with_another_listing_is_not_deleted(
    buyer_client, second_product, settings, tmp_path, django_capture_on_commit_callbacks
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    first, second = listing.preview_images
    second_product.preview_images = [first]
    second_product.save(update_fields=["preview_images"])

    with django_capture_on_commit_callbacks(execute=True):
        assert _edit(buyer_client, listing, keep=[second]).status_code == 200
    assert (tmp_path / first).exists()


def test_changing_the_content_of_a_live_ad_keeps_it_live(
    buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    assert _edit(buyer_client, listing, title="Canon 85mm f/1.8 lens").status_code == 200

    listing.refresh_from_db()
    assert listing.title == "Canon 85mm f/1.8 lens"
    assert listing.is_published is True
    assert listing.is_approved is True


def test_changing_only_the_price_or_address_keeps_the_ad_live(
    buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    response = _edit(buyer_client, listing, price="16500", address="DHA Phase 5, Lahore")

    assert response.status_code == 200
    listing.refresh_from_db()
    assert str(listing.price) == "16500.00"
    assert listing.address == "DHA Phase 5, Lahore"
    assert listing.is_approved is True


def test_editing_an_ad_an_admin_removed_does_not_put_it_back(
    buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    DigitalProduct.objects.filter(pk=listing.pk).update(is_approved=False)
    assert _edit(buyer_client, listing, title="Edited after removal").status_code == 200

    listing.refresh_from_db()
    assert listing.title == "Edited after removal"
    assert listing.is_approved is False


def test_an_ad_keeps_between_one_and_five_photos(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)

    assert _edit(buyer_client, listing, keep=[]).status_code == 400
    too_many = [_photo(f"{n}.png") for n in range(4)]
    assert _edit(buyer_client, listing, photos=too_many).status_code == 400

    before = listing.preview_images
    listing.refresh_from_db()
    assert listing.preview_images == before


def test_an_edit_needs_an_address(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    assert _edit(buyer_client, listing, address="").status_code == 400


def test_an_edit_cannot_pull_in_someone_elses_file(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    response = _edit(buyer_client, listing, keep=["avatars/private.webp"])

    assert response.status_code >= 400
    listing.refresh_from_db()
    assert "avatars/private.webp" not in listing.preview_images


def test_nobody_else_can_open_or_edit_the_ad(
    buyer_client, other_buyer_client, photographer_client, api_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    url = f"{URL}seller/products/{listing.pk}/"

    for client in (other_buyer_client, photographer_client):
        assert client.get(url).status_code == 404
        assert _edit(client, listing, title="Hijacked ad").status_code == 404
    assert api_client.get(url).status_code == 401


def test_a_seller_can_open_their_own_ad_while_in_review(
    buyer_client, other_buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    DigitalProduct.objects.filter(pk=listing.pk).update(is_approved=False)
    url = f"{URL}products/{listing.slug}/"

    assert buyer_client.get(url).status_code == 200
    assert other_buyer_client.get(url).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# MARK AS SOLD / DELETE
# ═══════════════════════════════════════════════════════════════════════════
def test_a_sold_ad_leaves_the_shop_but_stays_in_my_listings(
    buyer_client, other_buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    response = buyer_client.post(f"{URL}seller/products/{listing.pk}/mark-sold/")

    assert response.status_code == 200
    assert response.json()["data"]["is_sold"] is True
    assert other_buyer_client.get(f"{URL}products/").json()["data"] == []
    assert other_buyer_client.get(f"{URL}products/{listing.slug}/").status_code == 404

    mine = buyer_client.get(f"{URL}seller/products/").json()["data"]
    assert [(row["id"], row["is_sold"]) for row in mine] == [(listing.pk, True)]
    summary = buyer_client.get(f"{URL}seller/products/summary/").json()["data"]
    assert summary["products_live"] == 0
    # The seller can still open their own sold ad.
    assert buyer_client.get(f"{URL}products/{listing.slug}/").json()["data"]["is_sold"] is True


def test_a_sold_ad_can_go_back_on_sale_without_a_new_review(
    buyer_client, other_buyer_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    buyer_client.post(f"{URL}seller/products/{listing.pk}/mark-sold/")
    response = buyer_client.post(f"{URL}seller/products/{listing.pk}/mark-available/")

    assert response.status_code == 200
    listing.refresh_from_db()
    assert (listing.is_sold, listing.sold_at, listing.is_approved) == (False, None, True)
    assert [row["slug"] for row in other_buyer_client.get(f"{URL}products/").json()["data"]] == [
        listing.slug
    ]


def test_repricing_a_sold_ad_does_not_send_it_to_review(buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    buyer_client.post(f"{URL}seller/products/{listing.pk}/mark-sold/")

    assert _edit(buyer_client, listing, price="9000").status_code == 200
    listing.refresh_from_db()
    assert (listing.is_sold, listing.is_approved) == (True, True)


def test_a_chat_about_a_sold_ad_shows_it_unavailable(
    buyer_client, other_buyer_client, other_buyer, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    seller = listing.seller
    thread = other_buyer_client.post(
        "/api/v1/chat/conversations/", {"user": seller.pk, "product": listing.pk}
    ).json()["data"]
    buyer_client.post(f"{URL}seller/products/{listing.pk}/mark-sold/")

    again = other_buyer_client.get(f"/api/v1/chat/conversations/{thread['id']}/").json()["data"]
    assert again["product"]["is_available"] is False


def test_a_seller_can_delete_their_ad(buyer_client, other_buyer_client, settings, tmp_path):
    listing = _live_listing(buyer_client, settings, tmp_path)
    response = buyer_client.delete(f"{URL}seller/products/{listing.pk}/")

    assert response.status_code == 204
    assert buyer_client.get(f"{URL}seller/products/").json()["data"] == []
    assert other_buyer_client.get(f"{URL}products/").json()["data"] == []
    assert buyer_client.get(f"{URL}seller/products/{listing.pk}/").status_code == 404
    # Soft delete: the row stays for past orders and chat history.
    assert DigitalProduct.all_objects.filter(pk=listing.pk, is_deleted=True).exists()


def test_nobody_else_can_sell_out_or_delete_the_ad(
    buyer_client, other_buyer_client, photographer_client, api_client, settings, tmp_path
):
    listing = _live_listing(buyer_client, settings, tmp_path)
    base = f"{URL}seller/products/{listing.pk}/"

    for client in (other_buyer_client, photographer_client):
        assert client.post(f"{base}mark-sold/").status_code == 404
        assert client.delete(base).status_code == 404
    assert api_client.delete(base).status_code == 401
    listing.refresh_from_db()
    assert (listing.is_sold, listing.is_deleted) == (False, False)
