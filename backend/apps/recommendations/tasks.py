"""Model training and feature-store refresh."""

import logging

from celery import shared_task

logger = logging.getLogger("snapsphere")


@shared_task
def retrain_models():
    """Retrain, evaluate, and promote only if not worse than the live model."""
    # Implemented in Module 10 (AI Recommendation).
    logger.info("retrain_models: pending Module 10 implementation")
    return {"status": "not_implemented"}


@shared_task
def refresh_trending_photographers():
    """Recompute time-decayed trending scores (hourly)."""
    from apps.profiles import selectors

    scores = selectors.refresh_trending_cache()
    logger.info("Trending scores refreshed", extra={"photographers": len(scores)})
    return {"status": "ok", "photographers": len(scores)}


@shared_task
def refresh_photographer_features():
    """
    Rebuild the PhotographerFeature store from live data (nightly, 02:30).

    Uses the serving path's own `engine.build_feature_frame`, so the stored
    features are exactly what the feed computes — the store is the offline
    snapshot used for training and analysis, never a second definition.
    Relative features (price percentile, popularity) are computed across all
    visible photographers at once, matching how they were trained.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.profiles import selectors
    from apps.recommendations import engine
    from apps.recommendations.models import PhotographerFeature

    photographers = list(selectors.visible_photographers())
    if not photographers:
        return {"status": "ok", "refreshed": 0}

    frame = engine.build_feature_frame(photographers)
    ranker = engine._load_ranker()
    quality = (
        [float(s) for s in ranker.predict(frame)]
        if ranker is not None
        else [float(p.avg_rating or 0) / 5.0 for p in photographers]
    )

    now = timezone.now()
    existing = {
        f.photographer_id: f
        for f in PhotographerFeature.objects.filter(
            photographer_id__in=[p.pk for p in photographers]
        )
    }
    to_create, to_update = [], []
    for p, (_, row), score in zip(photographers, frame.iterrows(), quality):
        feature = existing.get(p.pk) or PhotographerFeature(photographer=p)
        feature.avg_rating = float(p.avg_rating or 0)
        feature.bayesian_rating = float(row["bayesian_rating"])
        feature.reviews_count = int(p.reviews_count or 0)
        feature.years_experience = int(p.years_experience or 0)
        feature.bookings_success_rate = float(row["success_rate"])
        feature.response_time_hours = float(p.avg_response_time_hours or 24)
        feature.portfolio_score = int(p.portfolio_score or 0)
        feature.base_price = float(p.base_price or 0)
        feature.completed_bookings = int(p.completed_bookings or 0)
        feature.total_bookings = int(p.total_bookings or 0)
        feature.profile_views = int(p.profile_views or 0)
        feature.portfolio_image_count = int(row["portfolio_image_count"])
        feature.response_speed_score = float(row["response_speed_score"])
        feature.popularity_score = float(row["popularity_score"])
        feature.engagement_rate = float(row["engagement_rate"])
        feature.recency_score = float(row["recency_score"])
        feature.price_percentile = float(row["price_percentile"])
        feature.sentiment_score = float(row["sentiment_score"])
        feature.is_new_photographer = p.created_at >= now - timedelta(days=30)
        feature.quality_score = score
        feature.last_computed_at = now  # bulk_update skips auto_now
        (to_update if feature.pk else to_create).append(feature)

    PhotographerFeature.objects.bulk_create(to_create, batch_size=200)
    if to_update:
        fields = [
            f.name for f in PhotographerFeature._meta.concrete_fields
            if f.name not in ("id", "photographer", "created_at")
        ]
        PhotographerFeature.objects.bulk_update(to_update, fields, batch_size=200)

    logger.info(
        "Photographer features refreshed",
        extra={"rows_created": len(to_create), "rows_updated": len(to_update)},
    )
    return {"status": "ok", "refreshed": len(photographers)}
