"""
Marketplace serializers.

WHAT IS DELIBERATELY ABSENT
---------------------------
No field below exposes `ProductFile.file`. The manifest
(`ProductFileSerializer`) carries names and sizes so a buyer can see what they
are paying for, and nothing else — the bytes are reachable only through a
redeemed download token. A serializer that helpfully added a `url` here would
silently undo `core/storage.py`.
"""

from decimal import Decimal

from django.core.files.storage import default_storage
from rest_framework import serializers

from apps.catalog.serializers import CategoryMiniSerializer
from apps.marketplace.models import (
    DigitalProduct,
    Order,
    OrderItem,
    ProductFile,
)


def _absolute(request, file_field) -> str | None:
    if not file_field:
        return None
    return request.build_absolute_uri(file_field.url) if request else file_field.url


def seller_display_name(user) -> str:
    """A photographer seller shows their studio name; anyone else, their name."""
    profile = getattr(user, "photographer_profile", None)
    return profile.display_name if profile else user.full_name


class SellerMiniSerializer(serializers.Serializer):
    """The seller is a user account — a photographer or a buyer."""

    id = serializers.IntegerField()
    display_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    def get_display_name(self, obj) -> str:
        return seller_display_name(obj)

    def get_avatar_url(self, obj) -> str | None:
        return _absolute(self.context.get("request"), obj.avatar)

    def get_is_verified(self, obj) -> bool:
        profile = getattr(obj, "photographer_profile", None)
        return bool(profile and profile.is_verified)


class ProductFileSerializer(serializers.ModelSerializer):
    """The manifest — names and sizes only. No URL, by design."""

    class Meta:
        model = ProductFile
        fields = ("id", "name", "file_size_mb", "display_order")


class ProductListSerializer(serializers.ModelSerializer):
    """Grid card payload."""

    seller = SellerMiniSerializer(read_only=True)
    category = CategoryMiniSerializer(read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    discount_percent = serializers.IntegerField(read_only=True)
    type_label = serializers.CharField(source="get_product_type_display", read_only=True)
    is_owned = serializers.SerializerMethodField()
    is_wishlisted = serializers.SerializerMethodField()

    class Meta:
        model = DigitalProduct
        fields = (
            "id", "uuid", "slug", "title", "product_type", "type_label",
            "license_type", "price", "compare_at_price", "discount_percent",
            "thumbnail_url", "file_count", "total_size_mb",
            "sales_count", "avg_rating", "reviews_count",
            "seller", "category", "is_featured",
            "is_owned", "is_wishlisted",
        )

    def get_thumbnail_url(self, obj) -> str | None:
        return _absolute(self.context.get("request"), obj.thumbnail)

    # These two read from sets the view loaded in one query each, rather than
    # firing a query per card. A 20-row grid would otherwise cost 40 extra.
    def get_is_owned(self, obj) -> bool:
        return obj.pk in (self.context.get("owned_ids") or set())

    def get_is_wishlisted(self, obj) -> bool:
        return obj.pk in (self.context.get("wishlisted_ids") or set())


class ProductDetailSerializer(ProductListSerializer):
    files = ProductFileSerializer(many=True, read_only=True)
    preview_image_urls = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "description", "address", "compatible_with", "tags",
            "preview_images", "preview_image_urls", "preview_video_url",
            "files", "view_count", "wishlist_count", "published_at",
        )

    def get_preview_image_urls(self, obj) -> list[str]:
        """
        `preview_images` is a JSON list of storage paths, not URLs.

        Resolving them here means the app renders them directly instead of
        every client reimplementing the same string concatenation.
        """
        from django.conf import settings

        request = self.context.get("request")
        urls = []
        for path in obj.preview_images or []:
            if str(path).startswith("http"):
                urls.append(str(path))
                continue
            relative = f"{settings.MEDIA_URL}{str(path).lstrip('/')}"
            urls.append(request.build_absolute_uri(relative) if request else relative)
        return urls


# ═══════════════════════════════════════════════════════════════════════════
# ORDERS
# ═══════════════════════════════════════════════════════════════════════════
class OrderItemSerializer(serializers.ModelSerializer):
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    downloads_remaining = serializers.IntegerField(read_only=True)
    files = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id", "product", "product_slug", "product_title", "thumbnail_url",
            "seller_name", "price", "download_count", "max_downloads",
            "downloads_remaining", "has_review", "files", "created_at",
        )

    def get_thumbnail_url(self, obj) -> str | None:
        return _absolute(self.context.get("request"), obj.product.thumbnail)

    def get_seller_name(self, obj) -> str:
        return seller_display_name(obj.seller)

    def get_files(self, obj) -> list:
        return ProductFileSerializer(obj.product.files.all(), many=True).data


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Order
        fields = (
            "id", "uuid", "order_number", "status", "status_label",
            "subtotal", "discount", "total", "payment_method",
            "delivery_address", "delivery_phone",
            "paid_at", "created_at", "items", "item_count",
        )

    def get_item_count(self, obj) -> int:
        return obj.items.count()


class DownloadRequestSerializer(serializers.Serializer):
    file = serializers.IntegerField(
        required=False,
        help_text="ProductFile id. Omit to get the first file in the product.",
    )


class DownloadTokenSerializer(serializers.Serializer):
    download_url = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
    file_name = serializers.CharField(read_only=True)
    downloads_remaining = serializers.IntegerField(read_only=True)


class SellerProductSerializer(ProductListSerializer):
    """
    A seller's own listing.

    Adds the two moderation flags, which the seller list needs because it
    includes unpublished drafts. They stay off `ProductListSerializer` so the
    public grid does not carry two booleans that are true by definition of
    being visible there at all.
    """

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "is_published", "is_approved", "published_at", "view_count",
            "wishlist_count", "total_revenue",
        )


class SellerProductDetailSerializer(SellerProductSerializer):
    """Everything the seller's edit form needs, with a handle per photo."""

    photos = serializers.SerializerMethodField()

    class Meta(SellerProductSerializer.Meta):
        fields = SellerProductSerializer.Meta.fields + (
            "description", "address", "photos",
        )

    def get_photos(self, obj) -> list[dict]:
        from apps.marketplace.services import listing_photos

        request = self.context.get("request")
        rows = []
        for path in listing_photos(obj):
            url = default_storage.url(path)
            rows.append(
                {"path": path, "url": request.build_absolute_uri(url) if request else url}
            )
        return rows


class SellerProductCreateSerializer(serializers.Serializer):
    """A new listing from the Sell screen: photos, details and a price."""

    MAX_PHOTOS = 5

    title = serializers.CharField(min_length=3, max_length=160)
    description = serializers.CharField(min_length=10, max_length=5000)
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("1")
    )
    product_type = serializers.ChoiceField(
        choices=DigitalProduct._meta.get_field("product_type").choices
    )
    address = serializers.CharField(
        min_length=5, max_length=300,
        error_messages={
            "required": "Enter the address of the product.",
            "blank": "Enter the address of the product.",
            "min_length": "Enter the area and city of the product.",
        },
    )
    photos = serializers.ListField(
        child=serializers.ImageField(),
        min_length=1,
        max_length=MAX_PHOTOS,
        error_messages={"min_length": "Add at least one photo of the product."},
    )

    def validate_photos(self, photos):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.core.validators import validate_image_file

        for photo in photos:
            try:
                validate_image_file(photo)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.messages) from exc
            photo.seek(0)
        return photos


class SellerProductUpdateSerializer(SellerProductCreateSerializer):
    """The whole ad again: existing photos to keep, plus any new ones."""

    keep_photos = serializers.ListField(
        child=serializers.CharField(max_length=300),
        required=False, default=list,
        max_length=SellerProductCreateSerializer.MAX_PHOTOS,
    )
    photos = serializers.ListField(
        child=serializers.ImageField(),
        required=False, default=list,
        max_length=SellerProductCreateSerializer.MAX_PHOTOS,
    )

    def validate(self, attrs):
        total = len(attrs["keep_photos"]) + len(attrs["photos"])
        if total < 1:
            raise serializers.ValidationError(
                {"photos": "Add at least one photo of the product."}
            )
        if total > self.MAX_PHOTOS:
            raise serializers.ValidationError(
                {"photos": f"An ad can have up to {self.MAX_PHOTOS} photos."}
            )
        return attrs


class SellerSummarySerializer(serializers.Serializer):
    products_total = serializers.IntegerField(read_only=True)
    products_live = serializers.IntegerField(read_only=True)
    sales_count = serializers.IntegerField(read_only=True)
    gross_revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    net_earnings = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
