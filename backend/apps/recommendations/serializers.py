"""Recommendation serializers."""

from rest_framework import serializers

from apps.profiles.serializers import PhotographerListSerializer


class RecommendationSerializer(PhotographerListSerializer):
    """
    A photographer plus why they were recommended.

    `reason` is not decoration — see engine._reason(). A score with no
    explanation is a score users will not act on.
    """

    score = serializers.FloatField(read_only=True)
    reason = serializers.CharField(read_only=True)
    strategy = serializers.CharField(read_only=True)

    # Component scores, useful for the evaluation dashboard and for debugging
    # why a particular photographer ranked where they did.
    quality_score = serializers.FloatField(read_only=True, default=None)
    content_score = serializers.FloatField(read_only=True)
    collab_score = serializers.FloatField(read_only=True)
    business_score = serializers.FloatField(read_only=True)

    class Meta(PhotographerListSerializer.Meta):
        fields = PhotographerListSerializer.Meta.fields + (
            "score", "reason", "strategy",
            "quality_score", "content_score", "collab_score", "business_score",
        )


class VisualMatchingImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    caption = serializers.CharField(required=False, default="")
    visual_style = serializers.CharField(required=False, default="")
    shot_type = serializers.CharField(required=False, default="")
    similarity = serializers.FloatField(required=False, default=0.0)
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    def get_image_url(self, obj) -> str | None:
        from apps.profiles.serializers import _absolute
        return _absolute(self.context.get("request"), getattr(obj, "image", None))

    def get_thumbnail_url(self, obj) -> str | None:
        from apps.profiles.serializers import _absolute
        return _absolute(self.context.get("request"), getattr(obj, "thumbnail", None) or getattr(obj, "image", None))


class VisualSearchMatchSerializer(PhotographerListSerializer):
    """
    Photographer matched via Image-to-Photographer aesthetic cosine similarity.
    """
    similarity = serializers.FloatField(read_only=True)
    match_percentage = serializers.FloatField(read_only=True)
    reference_style = serializers.CharField(read_only=True)
    reason = serializers.CharField(read_only=True)
    strategy = serializers.CharField(default="VISUAL_STYLE_MATCH", read_only=True)
    matching_image = serializers.SerializerMethodField()

    class Meta(PhotographerListSerializer.Meta):
        fields = PhotographerListSerializer.Meta.fields + (
            "similarity",
            "match_percentage",
            "reference_style",
            "reason",
            "strategy",
            "matching_image",
        )

    def get_matching_image(self, obj) -> dict | None:
        best_img = getattr(obj, "best_image", None)
        if not best_img:
            return None
        best_img.similarity = getattr(obj, "best_image_similarity", getattr(obj, "similarity", 0.0))
        return VisualMatchingImageSerializer(best_img, context=self.context).data


class ConversationalMatchSerializer(PhotographerListSerializer):
    """
    Photographer tailored by Conversational Shoot Matchmaker.
    """
    match_score = serializers.FloatField(read_only=True)
    match_percentage = serializers.FloatField(read_only=True)
    match_reason = serializers.CharField(read_only=True)
    reason = serializers.CharField(source="match_reason", read_only=True)
    strategy = serializers.CharField(default="CONVERSATIONAL_MATCH", read_only=True)
    matching_service_title = serializers.CharField(read_only=True, allow_null=True)
    matching_service_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    matching_delivery_days = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta(PhotographerListSerializer.Meta):
        fields = PhotographerListSerializer.Meta.fields + (
            "match_score",
            "match_percentage",
            "match_reason",
            "reason",
            "strategy",
            "matching_service_title",
            "matching_service_price",
            "matching_delivery_days",
        )




# ═══════════════════════════════════════════════════════════════════════════
# REQUEST SERIALIZERS — validate input and document the endpoints in OpenAPI
# ═══════════════════════════════════════════════════════════════════════════
class VisualSearchRequestSerializer(serializers.Serializer):
    """A reference photo plus optional filters for "Find Similar Style"."""

    image = serializers.ImageField()
    category = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    min_price = serializers.FloatField(required=False, allow_null=True, min_value=0)
    max_price = serializers.FloatField(required=False, allow_null=True, min_value=0)
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    def validate_image(self, value):
        from apps.core.validators import validate_image_file

        validate_image_file(value)  # size, real MIME by magic bytes, allowed type
        return value


class MatchmakerRequestSerializer(serializers.Serializer):
    """A natural-language shoot description, plus optional wizard-chip overrides."""

    prompt = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    query = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    filters = serializers.JSONField(required=False, default=dict)
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    def validate_filters(self, value):
        # Multipart / form posts deliver `filters` as a JSON string.
        if isinstance(value, str):
            import json

            if not value.strip():
                return {}
            try:
                value = json.loads(value)
            except ValueError:
                raise serializers.ValidationError("Must be a JSON object.") from None
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        return value

    def validate(self, attrs):
        prompt = (attrs.get("prompt") or attrs.get("query") or "").strip()
        if not prompt:
            raise serializers.ValidationError(
                {"prompt": ["Please describe the shoot you are looking for."]}
            )
        attrs["prompt"] = prompt
        return attrs


class RecommendationClickSerializer(serializers.Serializer):
    photographer_id = serializers.IntegerField(min_value=1)
