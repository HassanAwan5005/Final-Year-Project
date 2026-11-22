"""
Marketplace write logic — Module 8.

BUYING HAPPENS IN CHAT, NOT HERE
--------------------------------
The shop is a classifieds board: a seller posts an ad, an interested buyer
messages them from the product page, and the two agree a deal in chat. There
is no cart, no checkout and no payment. Orders placed before that change stay
in the database so their downloads and reviews keep working.

THE DOWNLOAD FLOW
-----------------
Files never sit at a reachable URL (see `core/storage.py`). A buyer asks for a
token, gets a single-use ticket valid for 15 minutes, and redeems it once.
Even if that URL is copied out of a proxy log it is dead on arrival.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, ResourceGone
from apps.marketplace.models import (
    DigitalProduct,
    DownloadToken,
    OrderItem,
    OrderStatus,
    ProductFile,
)

logger = logging.getLogger("snapsphere")


# ═══════════════════════════════════════════════════════════════════════════
# DOWNLOADS
# ═══════════════════════════════════════════════════════════════════════════
@transaction.atomic
def issue_download_token(user, order_item: OrderItem, product_file: ProductFile) -> DownloadToken:
    """
    Mint a single-use, short-lived ticket for one file.

    The download counter is incremented HERE, when the ticket is issued, not
    when the bytes finish streaming. Counting on completion sounds fairer but
    is unenforceable — a client that disconnects at 99% has still received the
    file, and making the count depend on the client's honesty makes
    `max_downloads` decorative.
    """
    if order_item.order.buyer_id != user.id:
        raise BusinessRuleViolation("This purchase is not yours.")
    if order_item.order.status != OrderStatus.PAID:
        raise BusinessRuleViolation("This order has not been paid.")
    if product_file.product_id != order_item.product_id:
        raise BusinessRuleViolation("That file is not part of this purchase.")

    locked = OrderItem.objects.select_for_update().get(pk=order_item.pk)
    if locked.downloads_remaining <= 0:
        raise BusinessRuleViolation(
            f"You have used all {locked.max_downloads} downloads for this item. "
            f"Contact support if you need it again."
        )

    locked.download_count += 1
    locked.save(update_fields=["download_count", "updated_at"])

    token = DownloadToken.objects.create(
        order_item=locked,
        product_file=product_file,
        user=user,
        token=secrets.token_urlsafe(32),
        expires_at=timezone.now()
        + timedelta(minutes=settings.DOWNLOAD_TOKEN_TTL_MINUTES),
    )
    logger.info(
        "Download token issued",
        extra={"user_id": user.id, "order_item_id": locked.pk},
    )
    return token


@transaction.atomic
def redeem_download_token(token_value: str, *, ip_address: str | None = None) -> DownloadToken:
    """
    Spend a ticket. Raises rather than returning None so the view stays thin.

    The row is locked and re-read before the used_at check: without it, two
    parallel requests with the same token both see `used_at is None` and both
    get the file — which is exactly the reuse the token exists to prevent.
    """
    token = (
        DownloadToken.objects.select_for_update()
        .select_related("product_file", "order_item")
        .filter(token=token_value)
        .first()
    )
    if token is None:
        raise ResourceGone("This download link is not valid.")
    if token.used_at is not None:
        raise ResourceGone("This download link has already been used.")
    if timezone.now() >= token.expires_at:
        raise ResourceGone("This download link has expired. Request a new one.")

    token.used_at = timezone.now()
    token.ip_address = ip_address
    token.save(update_fields=["used_at", "ip_address", "updated_at"])
    return token


# ═══════════════════════════════════════════════════════════════════════════
# SELLING
# ═══════════════════════════════════════════════════════════════════════════
@transaction.atomic
def create_listing(
    user, *, title: str, description: str, price, product_type: str, address: str,
    photos: list,
) -> DigitalProduct:
    """
    List a product for sale — open to buyers and photographers alike.

    The listing is published straight away but NOT approved: it waits in the
    admin moderation queue (`is_published=True, is_approved=False`) and only
    appears in the shop once an admin approves it.

    The first photo becomes the thumbnail; every photo is kept as a preview,
    stored as a storage-relative path like the seeded products.
    """
    if getattr(user, "role", None) not in ("BUYER", "PHOTOGRAPHER"):
        raise BusinessRuleViolation("Only buyer and photographer accounts can sell.")

    product = DigitalProduct(
        seller=user,
        title=title.strip(),
        description=description.strip(),
        price=price,
        product_type=product_type,
        address=address.strip(),
        file_count=0,
        is_published=True,
        is_approved=False,
        published_at=timezone.now(),
    )
    _set_cover(product, photos[0])
    product.preview_images = [_store_photo(photo) for photo in photos]

    product.save()
    logger.info("Listing created", extra={"product_id": product.pk, "seller_id": user.pk})
    return product


def listing_photos(product: DigitalProduct) -> list[str]:
    """The listing's photos as storage paths, cover first."""
    if product.preview_images:
        return [str(path) for path in product.preview_images]
    return [product.thumbnail.name] if product.thumbnail else []


@transaction.atomic
def update_listing(
    user, product_id: int, *, title: str, description: str, price, product_type: str,
    address: str, keep_photos: list[str], photos: list,
) -> DigitalProduct:
    """
    Edit every part of your own ad, including adding and removing photos.

    `keep_photos` are the existing photos to keep, in order; `photos` are new
    uploads added after them. Anything not kept is removed.

    Moderation still holds: changing only the price or address leaves a live
    ad live, but changing what the admin judged (photos, title, description,
    category) sends it back to the review queue. Otherwise an approved ad could
    be swapped for anything. Editing an ad that is not live submits it again.
    """
    product = (
        DigitalProduct.objects.select_for_update()
        .filter(pk=product_id, seller=user)
        .first()
    )
    if product is None:
        raise BusinessRuleViolation("This listing is not yours.")

    current = listing_photos(product)
    if len(set(keep_photos)) != len(keep_photos) or not set(keep_photos) <= set(current):
        raise BusinessRuleViolation(
            "The photos of this ad have changed. Reopen it and try again."
        )
    paths = keep_photos + [_store_photo(photo) for photo in photos]
    if not paths:
        raise BusinessRuleViolation("Add at least one photo of the product.")

    title = title.strip()
    description = description.strip()
    content_changed = (
        paths != current
        or title != product.title
        or _plain(description) != _plain(product.description)
        or product_type != product.product_type
    )
    needs_review = content_changed or not product.is_purchasable

    old_thumbnail = product.thumbnail.name if product.thumbnail else ""
    if not old_thumbnail or paths[0] != current[0]:
        if keep_photos:
            from django.core.files.storage import default_storage

            with default_storage.open(paths[0], "rb") as cover:
                _set_cover(product, cover)
        else:
            _set_cover(product, photos[0])

    product.title = title
    product.description = description
    product.price = price
    product.product_type = product_type
    product.address = address.strip()
    product.preview_images = paths
    if needs_review:
        product.is_published = True
        product.is_approved = False
    product.save()

    removed = ({*current, old_thumbnail} - {*paths, product.thumbnail.name}) - {""}
    transaction.on_commit(lambda: _delete_unused_photos(removed))

    logger.info(
        "Listing updated",
        extra={"product_id": product.pk, "seller_id": user.pk, "review": needs_review},
    )
    return product


def _plain(text: str) -> str:
    """Multipart bodies may carry CRLF line endings; they are not an edit."""
    return text.replace("\r\n", "\n").strip()


def _set_cover(product: DigitalProduct, photo) -> None:
    from apps.core.utils import process_image

    photo.seek(0)
    thumb = process_image(photo, size_key="medium")
    product.thumbnail.save(thumb.name, thumb, save=False)


def _store_photo(photo) -> str:
    """Resize and re-encode, which also strips EXIF (phone photos carry GPS)."""
    from django.core.files.storage import default_storage

    from apps.core.utils import process_image

    photo.seek(0)
    large = process_image(photo, size_key="large")
    return default_storage.save(f"products/previews/{large.name}", large)


def _delete_unused_photos(paths) -> None:
    """Remove files no listing uses. Seeded products share preview files."""
    from django.core.files.storage import default_storage

    for path in paths:
        in_use = DigitalProduct.all_objects.filter(
            Q(preview_images__icontains=path.rsplit("/", 1)[-1]) | Q(thumbnail=path)
        ).exists()
        if not in_use:
            default_storage.delete(path)
