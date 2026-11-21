"""
Ranking features — computed AS OF a point in time.

ONE BUILDER FOR TRAINING AND SERVING
------------------------------------
    serving   build_feature_frame(candidates)                 as_of = now
    training  build_feature_frame(photographers, as_of=T)     history before T

Every feature is computed from timestamped records (bookings, reviews, daily
engagement stats, buyer interactions, recommendation clicks) restricted to
what had happened before `as_of`. That is what lets ml/pipelines/
train_ranker.py learn "features at time T → bookings after T" without the
answer leaking into the inputs, and it guarantees that the live engine
describes a photographer exactly the way the model was trained to read one.

THE FEATURES (order is a contract — see FEATURE_ORDER)
------------------------------------------------------
  Reviews
    bayesian_rating          avg rating smoothed toward the platform prior
    reviews_count_log        log1p(review count)
    sentiment_score          rating-derived sentiment, 5★ → 1.0, 1★ → 0.0
    recent_review_rating     smoothed avg rating of the last 180 days
    review_velocity_log      log1p(reviews in the last 180 days)
  Engagement (last 90 days)
    engagement_rate          portfolio interactions per profile view (depth)
    views_90d_log            log1p(profile views)
    clicks_90d_log           log1p(card + recommendation clicks)
    portfolio_90d_log        log1p(portfolio interactions)
    inquiries_90d_log        log1p(messages / inquiries)
    wishlist_saves_log       log1p(times saved to a wishlist, all time)
    rec_click_rate           smoothed click-through rate on recommendations
    conversion_rate_90d      smoothed bookings per profile view
  Performance, price, experience, portfolio
    years_experience, success_rate, response_speed_score, popularity_score,
    recency_score, price_percentile, portfolio_score_norm,
    portfolio_image_count

Review dates: a review is dated by the completion of the booking it reviews
(reviews can only be left after completion, and seeded reviews carry the
seed time as created_at, which would otherwise hide all review history).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

FEATURE_ORDER = [
    # existing
    "bayesian_rating",
    "reviews_count_log",
    "years_experience",
    "success_rate",
    "response_speed_score",
    "portfolio_score_norm",
    "popularity_score",
    "engagement_rate",
    "recency_score",
    "price_percentile",
    "sentiment_score",
    "portfolio_image_count",
    # reviews
    "recent_review_rating",
    "review_velocity_log",
    # engagement
    "views_90d_log",
    "clicks_90d_log",
    "portfolio_90d_log",
    "inquiries_90d_log",
    "wishlist_saves_log",
    "rec_click_rate",
    "conversion_rate_90d",
]

ENGAGEMENT_WINDOW_DAYS = 90
RECENT_REVIEW_WINDOW_DAYS = 180
RECENCY_HALF_LIFE_DAYS = 90
PORTFOLIO_IMAGE_CAP = 60
DEFAULT_RESPONSE_HOURS = 24.0

#: Laplace smoothing for rates, so 1 click from 1 impression is not "100%".
REC_CTR_PRIOR_CLICKS, REC_CTR_PRIOR_IMPRESSIONS = 1.0, 20.0
CONVERSION_PRIOR_BOOKINGS, CONVERSION_PRIOR_VIEWS = 1.0, 20.0


def recency_score(last_completed, today) -> float:
    """1.0 for a shoot completed today, halving every RECENCY_HALF_LIFE_DAYS; 0.0 if never."""
    if last_completed is None:
        return 0.0
    days = max((today - last_completed).days, 0)
    return 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


def _bayesian(avg: float, n: int, prior_rating: float, prior_count: float) -> float:
    if n <= 0:
        return prior_rating
    return (n / (n + prior_count)) * avg + (prior_count / (n + prior_count)) * prior_rating


def build_feature_frame(photographers: list, as_of=None):
    """
    Feature frame (columns in FEATURE_ORDER, one row per photographer).

    `as_of` — a timezone-aware datetime. None means now (the serving path).
    Relative features (popularity, price percentile) are computed across the
    rows passed in, in training and in serving alike.
    """
    import pandas as pd
    from django.conf import settings
    from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Q, Sum
    from django.db.models.functions import Coalesce, TruncDate
    from django.utils import timezone

    from apps.analytics.models import DailyPhotographerStat
    from apps.bookings.constants import BookingStatus
    from apps.bookings.models import Booking
    from apps.portfolio.models import PortfolioImage
    from apps.recommendations.models import BuyerInteraction, RecommendationEvent
    from apps.reviews.models import Review

    if not photographers:
        return pd.DataFrame(columns=FEATURE_ORDER)

    as_of = as_of or timezone.now()
    as_of_date = timezone.localdate(as_of)
    engagement_since = as_of - timedelta(days=ENGAGEMENT_WINDOW_DAYS)
    review_since_date = as_of_date - timedelta(days=RECENT_REVIEW_WINDOW_DAYS)
    ids = [p.pk for p in photographers]
    prior_m = float(settings.BAYESIAN_PRIOR_COUNT)
    prior_c = float(settings.BAYESIAN_PRIOR_RATING)

    # ─── Bookings known before as_of ─────────────────────────────────────────
    done_on = Coalesce(TruncDate("completed_at"), "event_date")
    bookings = Booking.objects.filter(photographer_id__in=ids, created_at__lt=as_of)
    booking_stats = {
        row["photographer_id"]: row
        for row in bookings.annotate(done_on=done_on)
        .values("photographer_id")
        .annotate(
            completed=Count(
                "id", filter=Q(status=BookingStatus.COMPLETED, done_on__lt=as_of_date)
            ),
            cancelled=Count(
                "id", filter=Q(status=BookingStatus.CANCELLED, cancelled_at__lt=as_of)
            ),
            rejected=Count(
                "id", filter=Q(status=BookingStatus.REJECTED, responded_at__lt=as_of)
            ),
            last_done=Max(
                "done_on", filter=Q(status=BookingStatus.COMPLETED, done_on__lt=as_of_date)
            ),
            recent=Count("id", filter=Q(created_at__gte=engagement_since)),
        )
    }
    response_hours = {
        row["photographer_id"]: row["avg"].total_seconds() / 3600 if row["avg"] else None
        for row in bookings.filter(responded_at__lt=as_of)
        .annotate(
            delta=ExpressionWrapper(
                F("responded_at") - F("created_at"), output_field=DurationField()
            )
        )
        .values("photographer_id")
        .annotate(avg=Avg("delta"))
    }

    # ─── Reviews, dated by the completion of the reviewed booking ────────────
    reviews = (
        Review.objects.visible()
        .filter(photographer_id__in=ids)
        .annotate(done_on=Coalesce(TruncDate("booking__completed_at"), "booking__event_date"))
        .filter(done_on__lt=as_of_date)
    )
    review_stats = {
        row["photographer_id"]: row
        for row in reviews.values("photographer_id").annotate(
            n=Count("id"),
            avg=Avg("rating"),
            recent_n=Count("id", filter=Q(done_on__gte=review_since_date)),
            recent_avg=Avg("rating", filter=Q(done_on__gte=review_since_date)),
        )
    }

    # ─── Engagement in the window before as_of ───────────────────────────────
    engagement = defaultdict(lambda: defaultdict(float))
    for row in (
        DailyPhotographerStat.objects.filter(
            photographer_id__in=ids,
            date__gte=timezone.localdate(engagement_since),
            date__lt=as_of_date,
        )
        .values("photographer_id")
        .annotate(
            views=Sum("profile_views"),
            clicks=Sum("clicks"),
            portfolio=Sum("portfolio_interactions"),
            inquiries=Sum("inquiries"),
        )
    ):
        e = engagement[row["photographer_id"]]
        for key in ("views", "clicks", "portfolio", "inquiries"):
            e[key] += float(row[key] or 0)

    interaction_key = {
        "VIEW": "views", "CLICK": "clicks", "PORTFOLIO": "portfolio", "INQUIRY": "inquiries",
    }
    for row in (
        BuyerInteraction.objects.filter(
            photographer_id__in=ids,
            created_at__gte=engagement_since,
            created_at__lt=as_of,
            interaction_type__in=list(interaction_key),
        )
        .values("photographer_id", "interaction_type")
        .annotate(n=Count("id"))
    ):
        engagement[row["photographer_id"]][interaction_key[row["interaction_type"]]] += row["n"]

    wishlist_saves = dict(
        BuyerInteraction.objects.filter(
            photographer_id__in=ids, interaction_type="WISHLIST", created_at__lt=as_of
        )
        .values("photographer_id")
        .annotate(n=Count("id"))
        .values_list("photographer_id", "n")
    )

    rec_stats = {
        row["photographer_id"]: row
        for row in RecommendationEvent.objects.filter(
            photographer_id__in=ids, created_at__gte=engagement_since, created_at__lt=as_of
        )
        .values("photographer_id")
        .annotate(
            shown=Count("id"),
            clicked=Count("id", filter=Q(was_clicked=True, clicked_at__lt=as_of)),
        )
    }
    for pid, row in rec_stats.items():
        engagement[pid]["clicks"] += row["clicked"]

    image_counts = dict(
        PortfolioImage.objects.filter(photographer_id__in=ids, is_deleted=False)
        .values("photographer_id")
        .annotate(n=Count("id"))
        .values_list("photographer_id", "n")
    )

    # ─── Assemble ────────────────────────────────────────────────────────────
    prices = [float(p.base_price or 0) for p in photographers]
    sorted_prices = sorted(prices)
    log_completed = [
        math.log1p(booking_stats.get(p.pk, {}).get("completed", 0)) for p in photographers
    ]
    lo, hi = min(log_completed), max(log_completed)
    span = (hi - lo) or 1.0

    rows = []
    for p, price, log_c in zip(photographers, prices, log_completed):
        b = booking_stats.get(p.pk, {})
        r = review_stats.get(p.pk, {})
        e = engagement.get(p.pk, {})
        rec = rec_stats.get(p.pk, {})

        completed = b.get("completed", 0)
        finished = completed + b.get("cancelled", 0) + b.get("rejected", 0)
        hours = response_hours.get(p.pk)
        hours = DEFAULT_RESPONSE_HOURS if hours is None else max(0.0, min(hours, 999.0))

        n_reviews = r.get("n", 0)
        avg_rating = float(r.get("avg") or 0)
        bayes = _bayesian(avg_rating, n_reviews, prior_c, prior_m)
        recent_n = r.get("recent_n", 0)
        recent_avg = float(r.get("recent_avg") or 0)

        views = e.get("views", 0.0)
        portfolio = e.get("portfolio", 0.0)

        rows.append(
            {
                "bayesian_rating": bayes,
                "reviews_count_log": math.log1p(n_reviews),
                "years_experience": float(p.years_experience or 0),
                "success_rate": completed / finished if finished else 0.0,
                # INVERTED: a fast reply is good.
                "response_speed_score": 1.0 / (1.0 + hours),
                "portfolio_score_norm": float(p.portfolio_score or 0) / 999.0,
                "popularity_score": (log_c - lo) / span,
                "engagement_rate": min(portfolio / (views + 1.0), 1.0),
                "recency_score": recency_score(b.get("last_done"), as_of_date),
                "price_percentile": sorted_prices.index(price) / max(len(prices) - 1, 1),
                "sentiment_score": max(min((avg_rating - 1.0) / 4.0, 1.0), 0.0)
                if n_reviews else 0.5,
                "portfolio_image_count": float(
                    min(image_counts.get(p.pk, 0), PORTFOLIO_IMAGE_CAP)
                ),
                # Recent reviews, smoothed toward this photographer's own
                # long-run rating: two recent reviews nudge it, fifty define it.
                "recent_review_rating": _bayesian(recent_avg, recent_n, bayes, prior_m),
                "review_velocity_log": math.log1p(recent_n),
                "views_90d_log": math.log1p(views),
                "clicks_90d_log": math.log1p(e.get("clicks", 0.0)),
                "portfolio_90d_log": math.log1p(portfolio),
                "inquiries_90d_log": math.log1p(e.get("inquiries", 0.0)),
                "wishlist_saves_log": math.log1p(wishlist_saves.get(p.pk, 0)),
                "rec_click_rate": (rec.get("clicked", 0) + REC_CTR_PRIOR_CLICKS)
                / (rec.get("shown", 0) + REC_CTR_PRIOR_IMPRESSIONS),
                "conversion_rate_90d": min(
                    (b.get("recent", 0) + CONVERSION_PRIOR_BOOKINGS)
                    / (views + CONVERSION_PRIOR_VIEWS),
                    1.0,
                ),
            }
        )
    return pd.DataFrame(rows, columns=FEATURE_ORDER)
