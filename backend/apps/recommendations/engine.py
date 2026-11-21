"""
The recommendation engine — Module 10's serving path.

ARCHITECTURE (see docs/01-system-architecture.md §8)
----------------------------------------------------
    candidate generation  (indexed SQL — narrow 200 → ~40)
        ↓
    feature assembly      (pandas frame in FEATURE_ORDER)
        ↓
    quality score         (the trained ranker artifact — how good a photographer is)
        ↓
    content score         (TF-IDF similarity to the buyer's taste profile — content.py)
        ↓
    collaborative score   (item-item similarity, if the buyer has history)
        ↓
    business rules        (exploration slots, availability boost)
        ↓
    hybrid blend + reason string + cache

    final = w_content·content + w_collab·collab + w_quality·quality + w_business·business
    (weights of signals that are unavailable for this buyer are redistributed)

THE SINGLE MOST IMPORTANT PROPERTY OF THIS MODULE
-------------------------------------------------
It never raises. Every failure path — missing artifact, corrupt pickle, Redis
down, pandas error — degrades to popularity ranking and logs. A recommendation
screen that returns slightly worse results is a minor problem; one that
returns HTTP 500 is the home screen of the app being broken.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("snapsphere")

from apps.recommendations.ranking_features import FEATURE_ORDER  # noqa: E402

# FEATURE_ORDER must match ml/pipelines/features.py exactly. A mismatch scores
# garbage silently, so it is asserted at load time in _load_ranker().

#: Added to the final score of photographers in the signed-in buyer's own city
#: (from their account). Same scale as the ±0.15 budget adjustment: enough to
#: bring strong local photographers into the feed, not enough to lift a weak
#: local one over a much better photographer elsewhere.
CITY_BOOST = 0.10

#: "Browsing city": among the buyer's last RECENT_VIEWS_WINDOW different
#: photographers viewed, at least RECENT_VIEWS_SAME_CITY in one city puts that
#: city's photographers at the top of their personalised list.
RECENT_VIEWS_WINDOW = 4
RECENT_VIEWS_SAME_CITY = 3

_ranker = None
_ranker_loaded = False
_cf = None
_cf_loaded = False


# ═══════════════════════════════════════════════════════════════════════════
# ARTIFACT LOADING (once per process, at first use)
# ═══════════════════════════════════════════════════════════════════════════
def _artifact_dir() -> Path:
    return Path(settings.ML_ARTIFACTS_DIR)


def _load_ranker():
    """Load and validate the ranker. Returns None if unusable."""
    global _ranker, _ranker_loaded
    if _ranker_loaded:
        return _ranker
    _ranker_loaded = True

    path = _artifact_dir() / "ranker.joblib"
    if not path.exists():
        logger.warning(
            "Ranker artifact missing at %s — falling back to popularity ranking. "
            "Run: python -m ml.train", path,
        )
        return None

    try:
        import joblib

        model = joblib.load(path)
        order = getattr(model, "feature_order", None)
        if order and list(order) != FEATURE_ORDER:
            # Loud, because a silent mismatch produces confident nonsense.
            logger.error(
                "FEATURE ORDER MISMATCH — engine expects %s but the artifact "
                "was trained on %s. Refusing to use it.", FEATURE_ORDER, list(order),
            )
            return None
        _ranker = model
        logger.info("Ranker loaded (mode=%s)", getattr(model, "mode", "unknown"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not load the ranker artifact: %s", exc)
        _ranker = None
    return _ranker


def warm_up() -> None:
    """
    Load the models and the scientific stack before the first request.

    Otherwise the first Home-feed request after a server start pays ~2-3 s
    for pandas/numpy imports and joblib loads. Never raises.
    """
    try:
        import pandas  # noqa: F401

        from apps.recommendations import content

        _load_ranker()
        _load_cf()
        content.load_model()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recommender warm-up failed (will load lazily): %s", exc)


def _load_cf():
    """Load the collaborative-filtering similarity matrix."""
    global _cf, _cf_loaded
    if _cf_loaded:
        return _cf
    _cf_loaded = True

    path = _artifact_dir() / "cf.joblib"
    if not path.exists():
        return None
    try:
        import joblib

        _cf = joblib.load(path)
        logger.info(
            "CF matrix loaded (%s photographers)", len(_cf.get("photographer_ids", []))
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load the CF artifact: %s", exc)
        _cf = None
    return _cf


def reset_artifact_cache() -> None:
    """Force a reload — called after a nightly retrain promotes a new model."""
    global _ranker, _ranker_loaded, _cf, _cf_loaded
    from apps.recommendations import content

    _ranker, _ranker_loaded = None, False
    _cf, _cf_loaded = None, False
    content.reset_model_cache()


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════
def build_feature_frame(photographers: list):
    """
    Turn PhotographerProfile rows into the ranker's input frame, as of now.

    Delegates to ranking_features.build_feature_frame — the SAME function the
    training pipeline calls with a past `as_of`, so the live engine describes
    a photographer exactly the way the model learned to read one. Features
    come from the live booking, review and engagement records, so a stale or
    unbuilt feature store can never serve wrong scores.
    """
    from apps.recommendations.ranking_features import build_feature_frame as build

    return build(photographers)


# ═══════════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════════
def _quality_scores(photographers: list) -> list[float]:
    """
    How good each photographer is, from the trained ranker (or a rating proxy).

    The same for every buyer. The buyer-specific signals are the content
    score (content.content_similarity_scores) and the collaborative score.
    """
    ranker = _load_ranker()
    if ranker is None:
        return [float(p.avg_rating or 0) / 5.0 for p in photographers]
    try:
        frame = build_feature_frame(photographers)
        return [float(s) for s in ranker.predict(frame)]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ranker scoring failed, using rating proxy: %s", exc)
        return [float(p.avg_rating or 0) / 5.0 for p in photographers]


def _collab_scores(buyer_id: int | None, photographers: list) -> list[float]:
    """
    Item-item collaborative score for this buyer.

    Returns zeros when the buyer has too little history — the model has
    nothing to generalise from below REC_MIN_INTERACTIONS_FOR_CF, and a
    confident-looking score built on one interaction is worse than none.
    """
    zeros = [0.0] * len(photographers)
    if buyer_id is None:
        return zeros

    cf = _load_cf()
    if cf is None:
        return zeros

    try:
        import numpy as np

        from apps.recommendations.models import BuyerInteraction

        history = list(
            BuyerInteraction.objects.filter(buyer_id=buyer_id).values_list(
                "photographer_id", "weight"
            )
        )
        if len(history) < settings.REC_MIN_INTERACTIONS_FOR_CF:
            return zeros

        index = cf["photographer_index"]
        similarity = cf["similarity"]

        profile = np.zeros(similarity.shape[0], dtype=np.float32)
        for photographer_id, weight in history:
            col = index.get(photographer_id)
            if col is not None:
                profile[col] += float(weight)

        if not profile.any():
            return zeros

        raw = profile @ similarity
        peak = float(raw.max())
        if peak <= 0:
            return zeros

        return [
            float(raw[index[p.pk]] / peak) if p.pk in index else 0.0
            for p in photographers
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Collaborative scoring failed: %s", exc)
        return zeros



def _get_buyer_budget_preference(buyer_id: int | None) -> tuple[float, float] | None:
    """
    Learn the buyer's spending comfort zone based on their interactions, cart additions,
    clicked services/products, and past bookings.

    Returns (target_price, tolerance) in PKR, or None if insufficient signal.
    """
    if not buyer_id:
        return None

    try:
        from apps.bookings.models import Booking
        from apps.marketplace.models import CartItem
        from apps.recommendations.models import BuyerInteraction

        prices = []

        # 1. Past bookings (highest intent signal: actual money spent or committed)
        booking_prices = list(
            Booking.objects.filter(buyer_id=buyer_id)
            .exclude(total_price=0)
            .values_list("total_price", flat=True)[:15]
        )
        for p in booking_prices:
            prices.append(float(p))

        # 2. Cart items (strong current purchase intent)
        cart_prices = list(
            CartItem.objects.filter(user_id=buyer_id)
            .values_list("product__price", flat=True)[:10]
        )
        for p in cart_prices:
            if p:
                prices.append(float(p))

        # 3. Interacted photographers' base prices
        interacted_prices = list(
            BuyerInteraction.objects.filter(buyer_id=buyer_id)
            .select_related("photographer")
            .values_list("photographer__base_price", flat=True)[:25]
        )
        for p in interacted_prices:
            if p and float(p) > 0:
                prices.append(float(p))

        if not prices:
            return None

        # Median / mean estimation for spending comfort zone
        prices.sort()
        mid = len(prices) // 2
        median_price = (
            prices[mid]
            if len(prices) % 2 != 0
            else (prices[mid - 1] + prices[mid]) / 2.0
        )

        if median_price <= 0:
            return None

        # Tolerance band: +/- 45% of median price (min tolerance 10,000 PKR)
        tolerance = max(median_price * 0.45, 10000.0)
        return (median_price, tolerance)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not compute buyer budget preference: %s", exc)
        return None


def _budget_fit_score(base_price: float, budget_pref: tuple[float, float] | None) -> float:
    """
    Gaussian-style affinity curve centered on the buyer's budget comfort zone.
    Returns a score multiplier from 0.0 to 1.0 (1.0 = exact budget match).
    """
    if budget_pref is None or base_price <= 0:
        return 0.5  # Neutral when no budget history is known

    target, tolerance = budget_pref
    diff = abs(base_price - target)
    # Bell-curve decay: high affinity within tolerance, decays naturally for luxury outliers
    return math.exp(-0.5 * (diff / tolerance) ** 2)


def _business_score(photographer) -> float:
    """
    Hand-tuned adjustments the models cannot express.
    """
    score = 0.5

    if photographer.is_accepting_bookings:
        score += 0.2
    if photographer.is_verified:
        score += 0.15
    if photographer.is_featured:
        score += 0.15

    if photographer.total_bookings > 5:
        cancel_rate = photographer.cancelled_bookings / photographer.total_bookings
        if cancel_rate > 0.3:
            score -= 0.3

    return max(min(score, 1.0), 0.0)


def _reason(
    photographer,
    content: float,
    collab: float,
    strategy: str,
    budget_fit_score: float | None = None,
    in_buyer_city: bool = False,
    view_city: str = "",
    content_sim: float = 0.0,
) -> str:
    """
    A human-readable justification.

    Non-negotiable for this product: a Pakistani buyer choosing a wedding
    photographer is making one of the largest discretionary purchases of their
    year. "Because our model said 0.87" earns no trust. "4.9★ from 214
    reviews, replies within an hour" does.
    """
    parts = []

    # Which personal signal put this photographer here comes FIRST, so it is
    # never cut by the four-part limit below.
    if strategy == "CONTENT" and content_sim >= 0.5:
        parts.append("Similar to photographers you liked")
    elif strategy == "COLLABORATIVE" and collab > 0.5:
        parts.append("Buyers like you also booked")

    if photographer.avg_rating and photographer.reviews_count:
        parts.append(
            f"{float(photographer.avg_rating):.1f}★ from "
            f"{photographer.reviews_count} reviews"
        )
    if view_city:
        parts.append(f"in {view_city}, like your recent views")
    elif in_buyer_city:
        parts.append("based in your city")
    if photographer.is_verified:
        parts.append("verified")

    category = photographer.categories.first() if photographer.pk else None
    if category:
        parts.append(f"specialises in {category.name}")

    hours = float(photographer.avg_response_time_hours or 24)
    if hours <= 1:
        parts.append("replies within an hour")
    elif hours <= 6:
        parts.append(f"replies in ~{int(hours)}h")

    if budget_fit_score is not None and budget_fit_score >= 0.82:
        parts.append("matches your budget")
    if strategy == "EXPLORATION":
        parts.append("new on SnapSphere")
    if photographer.completed_bookings > 40:
        parts.append(f"{photographer.completed_bookings} shoots completed")

    return " · ".join(parts[:4]) if parts else "Recommended for you"


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def recommend(
    *,
    buyer=None,
    category: str | None = None,
    city: str | None = None,
    max_price: float | None = None,
    limit: int = 20,
    use_cache: bool = True,
) -> dict:
    """
    Return ranked photographers with explanations.

    This is the ONLY function the API layer calls. Swapping the whole engine
    for an HTTP call to a separate ML service later means rewriting this
    function body and nothing else (ADR-003).
    """
    from apps.profiles import selectors

    buyer_id = buyer.pk if buyer and buyer.is_authenticated else None
    # The city the buyer has been browsing (see recent_view_city). Worked out
    # BEFORE the cache lookup and made part of the key, so the moment it
    # changes the buyer gets a freshly ranked list instead of a 30-minute-old
    # one. Not used when they filtered by city themselves.
    view_city = recent_view_city(buyer_id) if buyer_id and not city else ""
    cache_key = _cache_key(buyer_id, category, city, max_price, limit, view_city)

    if use_cache:
        hit = _cache_get(cache_key)
        if hit is not None:
            return hit

    # ─── 1. Candidate generation ─────────────────────────────────────────────
    queryset = selectors.photographers_for_list().filter(is_accepting_bookings=True)
    if category:
        queryset = queryset.filter(categories__slug=category)
    if city:
        queryset = queryset.filter(user__city__iexact=city)
    if max_price:
        queryset = queryset.filter(base_price__lte=max_price)

    # Cap the candidate pool: scoring is linear in candidates, and beyond a
    # few hundred the extra rows never reach the top 20 anyway.
    candidates = list(queryset.distinct()[:200])

    if not candidates:
        result = _relaxed_fallback(category, city, max_price, limit)
        _cache_set(cache_key, result)
        return result

    # ─── 2-5. Score ──────────────────────────────────────────────────────────
    from apps.recommendations import content as content_model

    ranker = _load_ranker()
    quality = _quality_scores(candidates)
    content = content_model.content_similarity_scores(buyer_id, candidates)
    collab = _collab_scores(buyer_id, candidates)
    has_content = any(c > 0 for c in content)
    has_collab = any(c > 0 for c in collab)

    # Redistribute the weight of any signal this buyer has no data for (no
    # history → no content or collaborative score) across the signals that
    # remain, rather than letting a block of zeros drag every score down.
    weights = {
        "content": settings.REC_WEIGHT_CONTENT if has_content else 0.0,
        "collab": settings.REC_WEIGHT_COLLAB if has_collab else 0.0,
        "quality": settings.REC_WEIGHT_QUALITY,
        "business": settings.REC_WEIGHT_BUSINESS,
    }
    total = sum(weights.values()) or 1.0
    w_content, w_collab, w_quality, w_business = (
        weights[k] / total for k in ("content", "collab", "quality", "business")
    )

    budget_pref = _get_buyer_budget_preference(buyer_id)

    # The buyer's own city, from their account. Not applied when the caller
    # already filtered by city — every candidate is local then anyway — nor
    # when the buyer's recent views point at a city: what they are browsing
    # right now outranks where their account says they live.
    buyer_city = (
        (getattr(buyer, "city", "") or "").strip().lower()
        if buyer_id and not city and not view_city
        else ""
    )

    scored = []
    for photographer, q_score, c_score, cf_score in zip(candidates, quality, content, collab):
        business = _business_score(photographer)
        base_price_val = float(photographer.base_price or 0)
        b_fit = _budget_fit_score(base_price_val, budget_pref) if budget_pref else None

        content_part = w_content * c_score
        collab_part = w_collab * cf_score
        raw_final = content_part + collab_part + w_quality * q_score + w_business * business

        # When a buyer's spending zone is known, blend budget fit into the final score
        # (up to +0.20 boost for exact budget matches, smoothly scaling down for luxury mismatches)
        if b_fit is not None:
            budget_boost = (b_fit - 0.5) * 0.30
            final = max(0.0, min(1.0, raw_final + budget_boost))
        else:
            final = raw_final

        # Local photographers first: people book someone they can meet.
        in_buyer_city = bool(buyer_city) and (
            (photographer.user.city or "").strip().lower() == buyer_city
        )
        if in_buyer_city:
            final = min(1.0, final + CITY_BOOST)

        in_view_city = bool(view_city) and (
            (photographer.user.city or "").strip().lower() == view_city
        )

        from django.utils import timezone

        is_new = (
            (timezone.now() - photographer.created_at).days <= 30
            and photographer.completed_bookings == 0
        )
        # Label each photographer by the personal signal that contributed
        # most to their score — that is what the reason string explains.
        if is_new:
            strategy = "EXPLORATION"
        elif collab_part > 0 and collab_part >= content_part:
            strategy = "COLLABORATIVE"
        elif content_part > 0:
            strategy = "CONTENT"
        elif ranker is None:
            strategy = "POPULARITY"
        else:
            strategy = "HYBRID"

        photographer.score = round(final, 4)
        photographer.quality_score = round(q_score, 4)
        photographer.content_score = round(c_score, 4)
        photographer.collab_score = round(cf_score, 4)
        photographer.business_score = round(business, 4)
        photographer.budget_fit_score = round(b_fit, 4) if b_fit is not None else None
        photographer.strategy = strategy
        photographer.in_buyer_city = in_buyer_city
        photographer.in_view_city = in_view_city
        photographer.reason = _reason(
            photographer, q_score, cf_score, strategy, budget_fit_score=b_fit,
            in_buyer_city=in_buyer_city,
            view_city=photographer.user.city if in_view_city else "",
            content_sim=c_score,
        )
        scored.append(photographer)

    # Viewing several photographers in one city is a clear signal, so it also
    # makes the list personal ("Picked for you") even before the
    # collaborative model has enough history.
    personalised = has_collab or has_content or bool(view_city)

    # The model score decides WHO makes the page; _order_for_display then
    # decides the ORDER the page is shown in (rating for "Top rated", score
    # for a personalised "Picked for you").
    scored.sort(key=lambda p: p.score, reverse=True)
    # Apply Multi-Armed Bandit (UCB1) for New Talent cold-start promotion
    if view_city:
        # Every photographer in the browsing city goes to the top (best score
        # first), then the rest of the list in score order.
        ranked = _apply_bandit_exploration(scored, len(scored))
        top = sorted(ranked, key=lambda p: (not p.in_view_city, -p.score))[:limit]
    else:
        top = _apply_bandit_exploration(scored, limit)
    top = _order_for_display(top, personalised=personalised)

    result = {
        "photographers": top,
        "strategy": (
            "HYBRID" if has_collab and has_content
            else "COLLABORATIVE" if has_collab
            else "CONTENT" if has_content
            else "POPULARITY"
        ),
        "personalised": personalised,
        "model_mode": getattr(ranker, "mode", "none") if ranker else "none",
        "relaxed": None,
    }
    _cache_set(cache_key, result)
    return result


def recent_view_city(buyer_id) -> str:
    """
    The city the buyer is browsing right now, or "" when there is none.

    Looks at the last RECENT_VIEWS_WINDOW DIFFERENT photographers whose
    profiles they opened (opening the same one five times counts once). If at
    least RECENT_VIEWS_SAME_CITY of them are in the same city, that city is
    returned, lower-cased. It follows the buyer: open three or four
    photographers in another city and that city takes over. One small query on
    an indexed table; never raises.
    """
    if not buyer_id:
        return ""
    try:
        from collections import Counter

        from apps.recommendations.models import BuyerInteraction, BuyerInteractionType

        recent = (
            BuyerInteraction.objects.filter(
                buyer_id=buyer_id, interaction_type=BuyerInteractionType.VIEW
            )
            .order_by("-created_at")
            .values_list("photographer_id", "photographer__user__city")[:50]
        )
        seen, cities = set(), []
        for photographer_id, photographer_city in recent:
            if photographer_id in seen:
                continue
            seen.add(photographer_id)
            cities.append((photographer_city or "").strip().lower())
            if len(cities) == RECENT_VIEWS_WINDOW:
                break

        counts = Counter(c for c in cities if c)
        if not counts:
            return ""
        top_city, n = counts.most_common(1)[0]
        return top_city if n >= RECENT_VIEWS_SAME_CITY else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read recent viewing city: %s", exc)
        return ""


def _order_for_display(rows: list, *, personalised: bool) -> list:
    """
    The engine decides WHO is on the page; the page's own label decides the ORDER.

    WHY THIS EXISTS
    ---------------
    The Home screen titles this feed "Picked for you" when it is personalised and
    "Top rated" when it is not. Score order is right for the first and wrong for
    the second: rating is one of twelve features in the blend, so a "Top rated"
    list came out 4.75, 4.67, 4.78, 3.79, 4.50 — every number correct, the
    sequence apparently random, and the heading promising an order the list did
    not have. A label that lies about its own ordering costs more trust than the
    ranking gains.

    So an unpersonalised page is re-sorted by the rating it DISPLAYS. It is
    deliberately `avg_rating` and not `bayesian_rating`: the card shows the
    average, and sorting by a number the user cannot see reproduces exactly the
    complaint this fixes — Featured is ordered by the Bayesian score and its
    visible averages can still invert (4.76 above 4.78).

    Sorting by the raw average alone would let a 5.0-from-one-review outrank a
    4.8-from-two-hundred. It cannot here, because this only re-orders a page the
    scorer already selected — and the scorer weighs `bayesian_rating` and review
    volume when choosing it. Selection stays evidence-weighted; presentation
    matches its heading.

    A personalised page is returned untouched: its order IS the recommendation,
    every card carries a `reason`, and the header says PERSONALISED.
    """
    if personalised:
        return rows

    rows.sort(
        key=lambda p: (
            -float(p.avg_rating or 0),
            # Same average, better evidence first — 4.8 from 200 reviews above
            # 4.8 from 3.
            -(p.reviews_count or 0),
            -float(p.score or 0),
        )
    )
    return rows


def _compute_newcomer_bandit_scores(newcomers: list) -> dict[int, float]:
    """
    Upper Confidence Bound (UCB1) & Thompson-style Multi-Armed Bandit for new creators.

    Instead of hardcoding fixed slot numbers (which indiscriminately shows all 0-review
    photographers regardless of whether users engage with them):
    - Measures each newcomer's view-to-inquiry/booking conversion rate.
    - Balances exploitation (promotes newcomers who convert well on portfolio views)
      and exploration (provides an uncertainty bonus sqrt(2 * ln(N) / n) for untried newcomers).
    """
    if not newcomers:
        return {}

    try:
        from apps.recommendations.models import BuyerInteraction, BuyerInteractionType

        newcomer_ids = [p.pk for p in newcomers]
        # High-intent engagement actions: INQUIRY, WISHLIST, BOOKING, COMPLETED
        conversion_types = {
            BuyerInteractionType.INQUIRY,
            BuyerInteractionType.WISHLIST,
            BuyerInteractionType.BOOKING,
            BuyerInteractionType.COMPLETED,
        }

        # Query interactions for these newcomers in one batch query
        interactions = list(
            BuyerInteraction.objects.filter(photographer_id__in=newcomer_ids)
            .values("photographer_id", "interaction_type")
        )

        views_count: dict[int, int] = {pid: 0 for pid in newcomer_ids}
        conversions_count: dict[int, int] = {pid: 0 for pid in newcomer_ids}

        for item in interactions:
            pid = item["photographer_id"]
            itype = item["interaction_type"]
            if itype in (BuyerInteractionType.VIEW, BuyerInteractionType.CLICK):
                views_count[pid] = views_count.get(pid, 0) + 1
            elif itype in conversion_types:
                conversions_count[pid] = conversions_count.get(pid, 0) + 1

        total_trials = max(sum(views_count.values()), len(newcomers))
        bandit_scores = {}

        for p in newcomers:
            pid = p.pk
            n = views_count.get(pid, 0)
            k = conversions_count.get(pid, 0)

            # If untried or minimal impressions, give standard optimistic prior exploration
            if n <= 1:
                # Prior mean = 0.5, high exploration bonus
                bandit_scores[pid] = 0.5 + math.sqrt(2.0 * math.log(total_trials + 1) / (n + 1))
            else:
                # Empirical conversion rate (exploitation)
                conversion_rate = k / float(n)
                # UCB uncertainty bonus (exploration)
                exploration_bonus = math.sqrt(2.0 * math.log(total_trials + 1) / float(n))
                bandit_scores[pid] = conversion_rate + 0.65 * exploration_bonus

        return bandit_scores
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not compute bandit scores for newcomers: %s", exc)
        return {p.pk: 0.5 for p in newcomers}


def _apply_bandit_exploration(scored: list, limit: int) -> list:
    """
    Multi-Armed Bandit (UCB1) for New Talent & Cold Start.

    Replaces rigid static slots with dynamic reward-driven promotion:
    - Identifies EXPLORATION candidates (new photographers with < 30 days & low/0 bookings).
    - Ranks newcomers by their UCB conversion / uncertainty score.
    - Seamlessly elevates high-performing newcomers into natural ranking positions.
    """
    if len(scored) <= limit:
        return scored[:limit]

    newcomers = [p for p in scored if p.strategy == "EXPLORATION"]
    if not newcomers:
        return scored[:limit]

    bandit_scores = _compute_newcomer_bandit_scores(newcomers)

    # Attach bandit score and re-rank newcomers dynamically
    for p in newcomers:
        b_score = bandit_scores.get(p.pk, 0.5)
        p.bandit_score = round(b_score, 4)
        # Dynamic bandit score boost applied to model score
        p.score = round(p.score + min(0.35, b_score * 0.25), 4)

    # Re-sort to let high-performing newcomers naturally compete with established creators
    scored.sort(key=lambda p: p.score, reverse=True)

    return scored[:limit]


def _relaxed_fallback(category, city, max_price, limit) -> dict:
    """
    Progressive relaxation when the filters match nobody.

    An empty state is a dead end. Widening the budget, then dropping the city,
    then dropping the category gives the buyer something to act on — and the
    `relaxed` field tells the UI what was loosened so it can say so honestly
    instead of pretending these were exact matches.
    """
    from apps.profiles import selectors

    attempts = [
        ("budget widened by 25%", {"category": category, "city": city,
                                   "max_price": max_price * 1.25 if max_price else None}),
        ("searched nearby cities", {"category": category, "city": None,
                                    "max_price": max_price}),
        ("showing all categories", {"category": None, "city": city, "max_price": None}),
        ("showing top-rated photographers", {"category": None, "city": None,
                                             "max_price": None}),
    ]

    for label, params in attempts:
        qs = selectors.photographers_for_list().filter(is_accepting_bookings=True)
        if params["category"]:
            qs = qs.filter(categories__slug=params["category"])
        if params["city"]:
            qs = qs.filter(user__city__iexact=params["city"])
        if params["max_price"]:
            qs = qs.filter(base_price__lte=params["max_price"])

        rows = list(qs.distinct().order_by("-avg_rating", "-reviews_count")[:limit])
        if rows:
            for p in rows:
                p.score = round(float(p.avg_rating or 0) / 5.0, 4)
                p.quality_score = p.score
                p.content_score = 0.0
                p.collab_score = 0.0
                p.business_score = _business_score(p)
                p.strategy = "POPULARITY"
                p.reason = _reason(p, p.score, 0.0, "POPULARITY")
            rows = _order_for_display(rows, personalised=False)
            return {
                "photographers": rows,
                "strategy": "POPULARITY",
                "personalised": False,
                "model_mode": "none",
                "relaxed": label,
            }

    return {
        "photographers": [],
        "strategy": "POPULARITY",
        "personalised": False,
        "model_mode": "none",
        "relaxed": "no photographers available",
    }


# ═══════════════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════════════
def _cache_key(buyer_id, category, city, max_price, limit, view_city="") -> str:
    payload = json.dumps(
        {"b": buyer_id, "c": category, "city": city, "p": max_price, "n": limit,
         "vc": view_city},
        sort_keys=True,
    )
    digest = hashlib.md5(payload.encode()).hexdigest()[:16]
    return f"rec:{buyer_id or 'anon'}:{digest}"


#: Score attributes attached to each photographer by recommend().
_SCORE_ATTRS = (
    "score", "quality_score", "content_score", "collab_score", "business_score",
    "strategy", "reason",
)


def _cache_set(key: str, value: dict) -> None:
    """
    Cache the IDS AND SCORES ONLY — never the model instances.

    Pickling ORM objects into Redis stores a snapshot of every column, so a
    photographer who raises their price or gets blocked keeps being served
    with stale data for the whole TTL. Worse, the pickle breaks outright the
    next time the model gains a field.

    Re-fetching by id on a hit costs one indexed query. What the cache is
    actually saving is the scoring pass — the feature frame, the ranker
    predict and the CF matrix multiply — which is the expensive part.
    """
    try:
        cache.set(
            key,
            {
                "ids": [p.pk for p in value["photographers"]],
                "scores": {
                    p.pk: {attr: getattr(p, attr, None) for attr in _SCORE_ATTRS}
                    for p in value["photographers"]
                },
                "strategy": value["strategy"],
                "personalised": value["personalised"],
                "model_mode": value["model_mode"],
                "relaxed": value["relaxed"],
            },
            settings.REC_CACHE_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recommendation cache write failed: %s", exc)


def _cache_get(key: str) -> dict | None:
    """Rehydrate a cached result from live rows. Returns None on any problem."""
    try:
        payload = cache.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recommendation cache read failed: %s", exc)
        return None

    if not payload:
        return None

    try:
        from apps.profiles import selectors

        ids = payload["ids"]
        if not ids:
            return None

        rows = {p.pk: p for p in selectors.photographers_for_list().filter(pk__in=ids)}

        ordered = []
        for pk in ids:
            photographer = rows.get(pk)
            if photographer is None:
                # Blocked, deleted or unapproved since we cached. Dropping it
                # is exactly why we re-fetch instead of pickling.
                continue
            for attr, val in payload["scores"].get(pk, {}).items():
                setattr(photographer, attr, val)
            ordered.append(photographer)

        if not ordered:
            return None

        return {
            "photographers": ordered,
            "strategy": payload["strategy"],
            "personalised": payload["personalised"],
            "model_mode": payload["model_mode"],
            "relaxed": payload["relaxed"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recommendation cache rehydrate failed: %s", exc)
        return None
