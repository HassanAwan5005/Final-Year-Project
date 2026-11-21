"""
Read-side queries for photographer discovery.

THE ONE RULE THIS MODULE ENFORCES
---------------------------------
`visible_photographers()` is the only entry point for public listings, and
every other selector builds on it. Centralising the visibility predicate means
a suspended photographer cannot leak through one endpoint because someone
forgot a filter — there is exactly one place to get it right.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.core.utils import bounding_box, haversine_km
from apps.profiles.models import PhotographerProfile, Wallet


def visible_photographers() -> QuerySet[PhotographerProfile]:
    """
    Photographers a buyer is allowed to see.

    Four conditions, all required:
      · approved by an admin
      · profile not soft-deleted
      · the underlying account is active
      · the account is not blocked
    """
    return (
        PhotographerProfile.objects.filter(
            is_approved=True,
            is_deleted=False,
            user__is_active=True,
            user__is_blocked=False,
        )
        .select_related("user")
        .prefetch_related("categories", "specializations")
    )


def photographers_for_list() -> QuerySet[PhotographerProfile]:
    """
    List queryset with everything the card renders, pre-joined.

    `annotate(service_count=...)` replaces a COUNT query per row. Combined
    with the select_related/prefetch above, a 20-row page costs 3 queries
    instead of 61.
    """
    return visible_photographers().annotate(
        service_count=Count("services", filter=Q(services__is_active=True), distinct=True)
    )


def photographer_detail(photographer_id: int) -> PhotographerProfile | None:
    """
    Full profile with services, packages, featured portfolio and recent reviews.

    Everything the detail screen needs arrives in one round trip. The mobile
    client should never have to fire four requests to paint one screen.
    """
    from apps.catalog.models import Service
    from apps.portfolio.models import PortfolioImage
    from apps.reviews.models import Review

    return (
        visible_photographers()
        .prefetch_related(
            Prefetch(
                "services",
                queryset=Service.objects.filter(is_active=True, is_deleted=False)
                .select_related("category")
                .prefetch_related("packages")
                .order_by("display_order", "price"),
            ),
            Prefetch(
                "portfolio_images",
                queryset=PortfolioImage.objects.filter(is_deleted=False).order_by(
                    "-is_featured", "display_order", "-created_at"
                )[:18],
                to_attr="preview_images",
            ),
            Prefetch(
                "reviews",
                queryset=Review.objects.visible()
                .select_related("buyer")
                .prefetch_related("images", "reply")
                .order_by("-created_at")[:5],
                to_attr="recent_reviews",
            ),
        )
        .filter(pk=photographer_id)
        .first()
    )


def wallet_balance(user) -> Decimal:
    """
    The authoritative balance — read from the database, never from `user.wallet`.

    Django caches a reverse one-to-one on the instance as soon as it is
    touched (creating `Wallet(user=user)` is enough), and `credit_wallet` /
    `debit_wallet` update a *different* Wallet instance fetched under
    `select_for_update`. So `user.wallet.balance` can report the balance as it
    was before the transaction that just changed it — which is exactly the
    number a cart summary or a checkout response must not show.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return Decimal("0.00")
    balance = (
        Wallet.objects.filter(user=user).values_list("balance", flat=True).first()
    )
    return balance if balance is not None else Decimal("0.00")


def photographer_self(user) -> PhotographerProfile | None:
    """
    A photographer's own profile, for their Profile tab.

    Deliberately does NOT go through `visible_photographers()`: someone still
    awaiting approval must be able to see and edit their own listing. Hiding
    it from them would mean the only way to fix an incomplete profile is to
    already have an approved one.
    """
    from apps.catalog.models import Service
    from apps.portfolio.models import PortfolioImage

    return (
        PhotographerProfile.objects.filter(user=user)
        .select_related("user")
        .prefetch_related(
            "categories",
            "specializations",
            Prefetch(
                "services",
                queryset=Service.objects.filter(is_deleted=False)
                .select_related("category")
                .prefetch_related("packages")
                .order_by("display_order", "price"),
            ),
            Prefetch(
                "portfolio_images",
                queryset=PortfolioImage.objects.filter(is_deleted=False).order_by(
                    "-is_featured", "display_order"
                )[:12],
                to_attr="preview_images",
            ),
        )
        .first()
    )


def featured_photographers(limit: int = 10) -> QuerySet[PhotographerProfile]:
    """
    Editorially featured, best-rated first.

    Ordered by `avg_rating` — the number the card actually prints — with review
    volume as the tiebreaker. It was `-bayesian_rating`, which is *better*
    ranking but sorts on a value the user cannot see: 4.76 (bayes 4.74) then
    4.75 (bayes 4.75) reads as a list that is not sorted at all. `is_featured`
    is already an editorial gate, so a thin-evidence 5.0 cannot arrive here on
    its average alone.
    """
    return photographers_for_list().filter(is_featured=True).order_by(
        "-avg_rating", "-reviews_count", "-completed_bookings"
    )[:limit]


# ─── Trending ────────────────────────────────────────────────────────────────
#
# "Trending" means popular RIGHT NOW, not best-rated of all time. A photographer
# trends when buyers have recently been viewing, saving, messaging, booking and
# reviewing them. Activity is counted only inside a short window, and older
# activity inside that window counts less (exponential time decay), so the
# list moves as buyer attention moves.

TRENDING_WINDOW_DAYS = 14
TRENDING_HALF_LIFE_DAYS = 3.5
TRENDING_CACHE_KEY = "trending:scores:v1"
TRENDING_CACHE_TTL_SECONDS = 2 * 60 * 60  # refreshed hourly by Celery; 2h survives one missed run

#: How strongly each recent signal counts towards trending.
TRENDING_WEIGHTS = {
    "VIEW": 1.0,          # profile opened
    "PORTFOLIO": 3.0,     # portfolio interaction
    "INQUIRY": 5.0,       # buyer messaged the photographer
    "WISHLIST": 6.0,      # saved to wishlist
    "REC_CLICK": 2.0,     # recommendation card tapped
    "BOOKING": 8.0,       # booking request created
    "COMPLETED": 10.0,    # booking completed
    "REVIEW": 4.0,        # new review, scaled by stars (5★ = full weight)
}


def _trending_decay(occurred_at, now) -> float:
    """1.0 for activity happening now, 0.5 after one half-life, and so on."""
    age_days = max((now - occurred_at).total_seconds(), 0.0) / 86400.0
    return 0.5 ** (age_days / TRENDING_HALF_LIFE_DAYS)


def compute_trending_scores() -> dict[int, float]:
    """
    Trending score per photographer from the last TRENDING_WINDOW_DAYS days.

    score = Σ (signal weight × time decay) over every recent event.

    Sources (each event counted once):
      · BuyerInteraction — views, portfolio interactions, inquiries, wishlist
      · RecommendationEvent — recommendation clicks
      · Booking — requests created, and bookings completed, in the window
      · Review — new visible reviews, weighted by star rating
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.bookings.constants import BookingStatus
    from apps.bookings.models import Booking
    from apps.recommendations.models import BuyerInteraction, RecommendationEvent
    from apps.reviews.models import Review

    now = timezone.now()
    since = now - timedelta(days=TRENDING_WINDOW_DAYS)
    scores: dict[int, float] = {}

    def add(photographer_id, weight, occurred_at):
        if photographer_id is None or occurred_at is None:
            return
        scores[photographer_id] = (
            scores.get(photographer_id, 0.0) + weight * _trending_decay(occurred_at, now)
        )

    # Bookings come from the Booking table below, so their interaction rows are
    # skipped here to avoid counting the same booking twice.
    for pid, itype, at in BuyerInteraction.objects.filter(
        created_at__gte=since,
        interaction_type__in=["VIEW", "PORTFOLIO", "INQUIRY", "WISHLIST"],
    ).values_list("photographer_id", "interaction_type", "created_at"):
        add(pid, TRENDING_WEIGHTS[itype], at)

    for pid, at in RecommendationEvent.objects.filter(
        was_clicked=True, clicked_at__gte=since
    ).values_list("photographer_id", "clicked_at"):
        add(pid, TRENDING_WEIGHTS["REC_CLICK"], at)

    for pid, at in Booking.objects.filter(created_at__gte=since).exclude(
        status__in=[BookingStatus.REJECTED, BookingStatus.CANCELLED, BookingStatus.EXPIRED]
    ).values_list("photographer_id", "created_at"):
        add(pid, TRENDING_WEIGHTS["BOOKING"], at)

    for pid, at in Booking.objects.filter(
        status=BookingStatus.COMPLETED, completed_at__gte=since
    ).values_list("photographer_id", "completed_at"):
        add(pid, TRENDING_WEIGHTS["COMPLETED"], at)

    for pid, rating, at in Review.objects.visible().filter(
        created_at__gte=since
    ).values_list("photographer_id", "rating", "created_at"):
        add(pid, TRENDING_WEIGHTS["REVIEW"] * (rating / 5.0), at)

    return scores


def refresh_trending_cache() -> dict[int, float]:
    """Recompute trending scores and store them (called hourly by Celery)."""
    from django.core.cache import cache

    scores = compute_trending_scores()
    try:
        cache.set(TRENDING_CACHE_KEY, scores, TRENDING_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — cache down must not break the feed
        pass
    return scores


def _get_trending_scores() -> dict[int, float]:
    """Cached scores, or a live recompute if the cache is empty or unreachable."""
    from django.core.cache import cache

    try:
        scores = cache.get(TRENDING_CACHE_KEY)
    except Exception:  # noqa: BLE001
        scores = None
    if scores is None:
        scores = refresh_trending_cache()
    return scores


def trending_photographers(city: str | None = None, limit: int = 10):
    """
    "Trending near you": photographers with the most recent buyer activity.

    Ranked by the time-decayed trending score (see compute_trending_scores).
    If fewer than `limit` photographers had any recent activity, the remaining
    slots are filled with the best-rated photographers so the section is never
    empty during quiet periods.
    """
    qs = photographers_for_list().filter(is_accepting_bookings=True)
    if city:
        qs = qs.filter(user__city__iexact=city)

    scores = _get_trending_scores()
    active_ids = [pid for pid, score in scores.items() if score > 0]

    trending = list(qs.filter(pk__in=active_ids)) if active_ids else []
    trending.sort(
        key=lambda p: (scores.get(p.pk, 0.0), float(p.avg_rating or 0)), reverse=True
    )
    trending = trending[:limit]

    if len(trending) < limit:
        chosen = [p.pk for p in trending]
        trending += list(
            qs.exclude(pk__in=chosen).order_by(
                "-avg_rating", "-completed_bookings", "-reviews_count"
            )[: limit - len(trending)]
        )
    return trending


def photographers_by_category(slug: str, limit: int | None = None):
    qs = photographers_for_list().filter(categories__slug=slug).order_by(
        "-avg_rating", "-reviews_count", "-completed_bookings"
    )
    return qs[:limit] if limit else qs


def annotate_distance(photographers, lat: float, lng: float) -> list:
    """
    Attach `distance_km` to each row, computed in Python.

    WHY NOT IN SQL
    --------------
    MySQL cannot use a B-tree index for a trigonometric distance expression,
    so `ORDER BY haversine(...)` degrades into a full scan plus a sort. The
    filter step narrows candidates with an indexed bounding box first (see
    `filter_by_radius`), and the exact distance is then computed on the
    handful of rows that survive — where the cost is trivial.
    """
    out = []
    for p in photographers:
        if p.user.latitude is None or p.user.longitude is None:
            p.distance_km = None
        else:
            p.distance_km = round(
                haversine_km(lat, lng, float(p.user.latitude), float(p.user.longitude)),
                1,
            )
        out.append(p)
    return out


def filter_by_radius(qs: QuerySet, lat: float, lng: float, radius_km: float):
    """Indexed bounding-box pre-filter — the cheap half of a distance query."""
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    return qs.filter(
        user__latitude__gte=Decimal(str(min_lat)),
        user__latitude__lte=Decimal(str(max_lat)),
        user__longitude__gte=Decimal(str(min_lng)),
        user__longitude__lte=Decimal(str(max_lng)),
    )
