"""Recommendation endpoints."""

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.recommendations import engine, matchmaker
from apps.recommendations.serializers import (
    ConversationalMatchSerializer,
    MatchmakerRequestSerializer,
    RecommendationClickSerializer,
    RecommendationSerializer,
    VisualSearchMatchSerializer,
    VisualSearchRequestSerializer,
)

logger = logging.getLogger("snapsphere")


@extend_schema(
    tags=["Recommendations"],
    summary="Ranked photographer recommendations with explanations",
    parameters=[
        OpenApiParameter("category", str, description="Category slug"),
        OpenApiParameter("city", str),
        OpenApiParameter("max_price", float, description="Budget ceiling in PKR"),
        OpenApiParameter("limit", int, description="Default 50, max 200"),
    ],
    responses=RecommendationSerializer(many=True),
)
class RecommendationView(APIView):
    """
    The Home screen's primary feed.

    AllowAny: an anonymous browser gets popularity ranking, a signed-in buyer
    with history gets a personalised hybrid. Both are useful; requiring a
    login to see anything would gate the first screen of the app.
    """

    permission_classes = [AllowAny]
    throttle_scope = "search"

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
        except (TypeError, ValueError):
            limit = 50

        max_price = request.query_params.get("max_price")
        try:
            max_price = float(max_price) if max_price else None
        except (TypeError, ValueError):
            max_price = None

        result = engine.recommend(
            buyer=request.user,
            category=request.query_params.get("category"),
            city=request.query_params.get("city"),
            max_price=max_price,
            limit=limit,
        )

        serializer = RecommendationSerializer(
            result["photographers"], many=True, context=_wishlist_context(request)
        )

        self._log_impressions(request, result)

        return Response(
            {
                "message": "Recommendations retrieved",
                "data": serializer.data,
                "meta": {
                    "strategy": result["strategy"],
                    "personalised": result["personalised"],
                    "model_mode": result["model_mode"],
                    # Non-null when filters matched nobody and were widened.
                    # The UI shows this so the user is not misled into
                    # thinking these were exact matches.
                    "relaxed": result["relaxed"],
                    "count": len(serializer.data),
                },
            }
        )

    def _log_impressions(self, request, result) -> None:
        """
        Record what was shown, at what rank.

        This is the raw material for offline CTR and Precision@K evaluation.
        Skipped for anonymous users (nothing to attribute) and wrapped in a
        try/except, because analytics must never break the feed.
        """
        if not request.user.is_authenticated:
            return
        try:
            from apps.recommendations.models import RecommendationEvent

            RecommendationEvent.objects.bulk_create(
                [
                    RecommendationEvent(
                        buyer=request.user,
                        photographer=photographer,
                        position=index,
                        score=getattr(photographer, "score", 0.0),
                        content_score=getattr(photographer, "content_score", 0.0),
                        collab_score=getattr(photographer, "collab_score", 0.0),
                        business_score=getattr(photographer, "business_score", 0.0),
                        strategy=getattr(photographer, "strategy", "HYBRID"),
                        reason=getattr(photographer, "reason", "")[:200],
                        filters_applied={
                            k: v for k, v in request.query_params.items()
                        },
                    )
                    for index, photographer in enumerate(result["photographers"], start=1)
                ],
                batch_size=50,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not log recommendation impressions: %s", exc)


@extend_schema(
    tags=["Recommendations"],
    summary="Record that a recommendation was clicked",
    request=RecommendationClickSerializer,
    responses={200: OpenApiTypes.OBJECT},
)
class RecommendationClickView(APIView):
    """
    Closes the feedback loop.

    Without click data there is no way to measure whether recommendations are
    any good — CTR and Precision@K are computed from exactly these two events
    (impression and click).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        params = RecommendationClickSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        photographer_id = params.validated_data["photographer_id"]

        from django.utils import timezone

        from apps.recommendations.models import RecommendationEvent

        updated = (
            RecommendationEvent.objects.filter(
                buyer=request.user,
                photographer_id=photographer_id,
                was_clicked=False,
            )
            .order_by("-created_at")[:1]
            .values_list("pk", flat=True)
        )
        RecommendationEvent.objects.filter(pk__in=list(updated)).update(
            was_clicked=True, clicked_at=timezone.now()
        )
        return Response({"message": "Recorded", "data": None})


@extend_schema(
    tags=["Recommendations"],
    summary="Engine status and live model info",
    responses={200: OpenApiTypes.OBJECT},
)
class RecommendationStatusView(APIView):
    """
    Diagnostics for the admin dashboard and for the FYP demo.

    Makes the honest state of the ML visible rather than hidden: which model
    is live, what mode it is in, and what its measured metrics were.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        import json
        from pathlib import Path

        from django.conf import settings

        from apps.recommendations import content as content_model

        ranker = engine._load_ranker()
        cf = engine._load_cf()
        content = content_model.load_model()

        metrics = {}
        metrics_path = Path(settings.ML_ARTIFACTS_DIR) / "metrics.json"
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text())
            except (OSError, ValueError):
                metrics = {}

        return Response(
            {
                "message": "Engine status",
                "data": {
                    "ranker": {
                        "loaded": ranker is not None,
                        "mode": getattr(ranker, "mode", None),
                        "features": len(engine.FEATURE_ORDER),
                        "metrics": metrics.get("ranker", {}).get("metrics", {}),
                    },
                    "collaborative_filter": {
                        "loaded": cf is not None,
                        "photographers": len(cf["photographer_ids"]) if cf else 0,
                        "metrics": metrics.get("cf", {}).get("metrics", {}),
                    },
                    "content_filter": {
                        "loaded": content is not None,
                        "photographers": len(content["photographer_ids"]) if content else 0,
                        "metrics": metrics.get("content", {}).get("metrics", {}),
                    },
                    "sentiment": {
                        "metrics": metrics.get("sentiment", {}).get("metrics", {}),
                    },
                    "weights": {
                        "content": settings.REC_WEIGHT_CONTENT,
                        "collaborative": settings.REC_WEIGHT_COLLAB,
                        "quality": settings.REC_WEIGHT_QUALITY,
                        "business": settings.REC_WEIGHT_BUSINESS,
                    },
                    "exploration_slots": settings.REC_EXPLORATION_SLOTS,
                    "cache_ttl_seconds": settings.REC_CACHE_TTL_SECONDS,
                },
            }
        )


def _wishlist_context(request) -> dict:
    """Serializer context with the caller's wishlist loaded once, not per row."""
    context = {"request": request}
    if request.user.is_authenticated:
        from apps.wishlist.models import WishlistItem

        context["wishlisted_ids"] = set(
            WishlistItem.objects.filter(
                user=request.user, photographer__isnull=False
            ).values_list("photographer_id", flat=True)
        )
    return context


class VisualSearchRecommendationView(APIView):
    """
    Find photographers matching a reference photo via aesthetic cosine similarity.

    Decoding an image and scoring every candidate portfolio is the most
    expensive request the API serves, so it has its own, tighter throttle.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "visual_search"

    @extend_schema(
        tags=["Recommendations"],
        summary="Image-to-Photographer Search ('Find Similar Style')",
        description=(
            "Upload a reference photo to find photographers whose portfolios "
            "share the closest aesthetic cosine similarity."
        ),
        request=VisualSearchRequestSerializer,
        responses=VisualSearchMatchSerializer(many=True),
    )
    def post(self, request):
        params = VisualSearchRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        from apps.portfolio.ai import find_photographers_by_visual_style

        search_result = find_photographers_by_visual_style(
            data["image"],
            category_slug=data.get("category") or None,
            city=data.get("city") or None,
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
            limit=data["limit"],
        )

        photographer_items = []
        for match in search_result["results"]:
            p = match["photographer"]
            p.similarity = match["similarity"]
            p.match_percentage = match["match_percentage"]
            p.reference_style = match["reference_style"]
            p.reason = match["reason"]
            p.best_image = match["best_image"]
            p.best_image_similarity = match["best_image_similarity"]
            photographer_items.append(p)

        serializer = VisualSearchMatchSerializer(
            photographer_items, many=True, context=_wishlist_context(request)
        )
        return Response(
            {
                "message": (
                    f"Found {len(photographer_items)} photographers matching "
                    f"style '{search_result['reference_style']}'"
                ),
                "data": serializer.data,
                "meta": {
                    "reference_style": search_result["reference_style"],
                    "total_matches": search_result["total_matches"],
                },
            }
        )


class ConversationalMatchmakerView(APIView):
    """
    Conversational Shoot Matchmaker: parses a natural-language buyer request
    into structured constraints and queries the recommendation engine.
    """

    permission_classes = [AllowAny]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_scope = "search"

    @extend_schema(
        tags=["Recommendations"],
        summary="Conversational Shoot Matchmaker",
        description=(
            "Buyers describe what they want in natural language; the parser "
            "extracts constraints and returns tailored recommendations."
        ),
        request=MatchmakerRequestSerializer,
        responses=ConversationalMatchSerializer(many=True),
    )
    def post(self, request):
        params = MatchmakerRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        match_data = matchmaker.match_shoot(
            data["prompt"],
            buyer=request.user,
            limit=data["limit"],
            override_filters=data["filters"],
        )

        serializer = ConversationalMatchSerializer(
            match_data["photographers"], many=True, context=_wishlist_context(request)
        )
        return Response(
            {
                "message": "Conversational shoot matches found",
                "data": {
                    "assistant_message": match_data["assistant_message"],
                    "parsed_filters": match_data["parsed_filters"],
                    "suggested_chips": match_data["suggested_chips"],
                    "relaxed_notice": match_data.get("relaxed_notice"),
                    "photographers": serializer.data,
                },
                "meta": {
                    "total_matches": match_data["total_matches"],
                    "confidence": match_data["parsed_filters"].get("confidence", 0.95),
                },
            }
        )
